"""Rich terminal output. User text is always passed as Text objects, never as markup."""

from __future__ import annotations

import difflib

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tokensaver.counter import TokenCount
from tokensaver.optimizer import Finding, OptimizationResult
from tokensaver.optimizer.base import Risk
from tokensaver.prefix import PrefixCheck
from tokensaver.pricing import ModelInfo, PriceTable, input_cost
from tokensaver.request import CacheEstimate, Part, RequestBreakdown
from tokensaver.scan import ScanResult

CALLS = 1_000  # costs are also shown per this many calls, where they become readable
MAX_DIFF_LINES = 60

ESTIMATE_NOTE = (
    "~ = estimated. No offline tokenizer exists for this model, so the count is "
    "scaled from OpenAI's o200k tokenizer. Real counts can differ by 10-20% or more."
)


def usd(amount: float) -> str:
    """Format dollars with enough precision for tiny per-call costs."""
    if amount == 0:
        return "$0"
    if abs(amount) >= 1:
        return f"${amount:,.2f}"
    if abs(amount) >= 0.01:
        return f"${amount:.4f}"
    return f"${amount:.6f}".rstrip("0")


def tokens_label(count: TokenCount) -> str:
    return f"{count.tokens:,}" if count.exact else f"~{count.tokens:,}"


def accuracy_label(model: ModelInfo) -> Text:
    return Text("exact", style="green") if model.exact else Text("estimated", style="yellow")


def prices_footer(table: PriceTable) -> Text:
    return Text(
        f"Prices: input, standard tier, as of {table.last_updated.isoformat()} "
        "(edit data/prices.json or pass --prices to update).",
        style="dim",
    )


def render_count(
    console: Console, count: TokenCount, model: ModelInfo, table: PriceTable, source: str
) -> None:
    cost = input_cost(count.tokens, model)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("Input", Text(source))
    grid.add_row("Model", Text.assemble(model.name, " (", accuracy_label(model), ")"))
    grid.add_row("Tokens", tokens_label(count))
    grid.add_row("Cost per call", usd(cost))
    grid.add_row(f"Cost per {CALLS:,} calls", usd(cost * CALLS))
    console.print(Panel(grid, title="tokensaver count", box=box.ROUNDED, expand=False))
    if model.notes:
        console.print(Text(f"Note: {model.notes}", style="dim"))
    if not count.exact:
        console.print(Text(ESTIMATE_NOTE, style="yellow"))
    console.print(prices_footer(table))


def cheapest_first(
    rows: list[tuple[ModelInfo, TokenCount]],
) -> list[tuple[ModelInfo, TokenCount]]:
    return sorted(rows, key=lambda r: (input_cost(r[1].tokens, r[0]), r[0].name))


def render_compare(
    console: Console, rows: list[tuple[ModelInfo, TokenCount]], table: PriceTable, source: str
) -> None:
    out = Table(title=f"Token count and input cost: {source}", box=box.SIMPLE_HEAVY)
    out.add_column("Model", no_wrap=True)
    out.add_column("Provider", no_wrap=True)
    out.add_column("Tokens", justify="right", no_wrap=True)
    out.add_column("Count", no_wrap=True)
    out.add_column("$/call", justify="right", no_wrap=True)
    out.add_column(f"$/{CALLS // 1000}k calls", justify="right", no_wrap=True)
    for model, count in cheapest_first(rows):
        cost = input_cost(count.tokens, model)
        out.add_row(
            model.name,
            model.provider,
            tokens_label(count),
            accuracy_label(model),
            usd(cost),
            usd(cost * CALLS),
        )
    console.print(out)
    if any(not count.exact for _, count in rows):
        console.print(Text(ESTIMATE_NOTE, style="yellow"))
    console.print(prices_footer(table))


def render_models(console: Console, table: PriceTable) -> None:
    out = Table(title="Supported models", box=box.SIMPLE_HEAVY)
    out.add_column("Model", no_wrap=True)
    out.add_column("Provider")
    out.add_column("Input / 1M", justify="right")
    out.add_column("Output / 1M", justify="right")
    out.add_column("Cached in / 1M", justify="right")
    out.add_column("Count")
    for model in table.models.values():
        cached = model.cached_input_per_1m
        out.add_row(
            model.name,
            model.provider,
            usd(model.input_per_1m),
            usd(model.output_per_1m),
            usd(cached) if cached is not None else Text("-", style="dim"),
            accuracy_label(model),
        )
    console.print(out)
    console.print(prices_footer(table))


def _status(finding: Finding) -> Text:
    """One word combining risk and whether the change was applied."""
    if finding.suggestion.flag_only:
        return Text("flag", style="yellow")
    if finding.applied:
        return Text("applied", style="green")
    if finding.suggestion.risk is Risk.REVIEW:
        return Text("review", style="yellow")
    return Text("skipped", style="dim")


def _findings_table(result: OptimizationResult) -> Table:
    out = Table(box=box.SIMPLE_HEAVY, show_lines=True)
    out.add_column("#", justify="right", style="dim")
    out.add_column("Suggestion", ratio=1)
    out.add_column("Tokens", justify="right", no_wrap=True)
    out.add_column(f"$/{CALLS // 1000}k calls", justify="right", no_wrap=True)
    out.add_column("Status", no_wrap=True)
    for number, finding in enumerate(result.findings, start=1):
        s = finding.suggestion
        description = Text(s.title, style="bold")
        description.append(f"  line {s.line}\n", style="dim")
        description.append(s.reason, style="dim")
        if s.see_line is not None:
            description.append(f" First at line {s.see_line}.", style="dim")
        tokens = f"≤{finding.tokens:,}" if s.flag_only else f"-{finding.tokens:,}"
        out.add_row(
            str(number), description, tokens, usd(finding.dollars * CALLS), _status(finding)
        )
    return out


def _show_trailing_space(line: str) -> str:
    stripped = line.rstrip(" \t")
    return stripped + "·" * (len(line) - len(stripped))


def diff_text(before: str, after: str, max_lines: int = MAX_DIFF_LINES) -> Text:
    lines = list(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), "before", "after", lineterm="", n=1
        )
    )
    out = Text()
    for line in lines[:max_lines]:
        style = "dim"
        if line.startswith("+") and not line.startswith("+++"):
            style = "green"
            line = _show_trailing_space(line)
        elif line.startswith("-") and not line.startswith("---"):
            style = "red"
            line = _show_trailing_space(line)
        elif line.startswith("@@"):
            style = "cyan"
        out.append(line + "\n", style=style)
    if len(lines) > max_lines:
        out.append(
            f"... {len(lines) - max_lines} more diff lines (save with --output to see all)\n",
            style="dim",
        )
    return out


def _summary(result: OptimizationResult) -> Panel:
    model = result.model
    approx = "" if model.exact else "~"
    lines = Text()
    lines.append("Before: ", style="bold")
    lines.append(f"{approx}{result.tokens_before:,} tokens\n")
    lines.append("After:  ", style="bold")
    lines.append(f"{approx}{result.tokens_after:,} tokens\n")
    lines.append("Saved:  ", style="bold")
    lines.append(
        f"{approx}{result.tokens_saved:,} tokens ({result.percent_saved:.1f}%) = "
        f"{usd(result.dollars_saved)} per call, "
        f"{usd(result.dollars_saved * CALLS)} per {CALLS:,} calls, "
        f"{usd(result.dollars_saved * 1_000_000)} per 1M calls",
        style="bold green" if result.tokens_saved > 0 else "",
    )
    return Panel(lines, title=f"Total savings on {model.name}", box=box.ROUNDED, expand=False)


def render_optimize(
    console: Console,
    result: OptimizationResult,
    table: PriceTable,
    source: str,
    show_diff: bool = True,
    extra_if_all: int = 0,
) -> None:
    """Render an optimization. `extra_if_all` is the measured extra saving of --apply all."""
    header = Text.assemble(
        ("tokensaver optimize", "bold"),
        f"  {source}  ·  {result.model.name} (",
        accuracy_label(result.model),
        ")",
    )
    console.print(header)

    if result.findings:
        console.print(_findings_table(result))
    else:
        console.print(Text("No suggestions: this prompt is already lean.", style="green"))
    if result.tidied:
        console.print(
            Text(
                f"Also tidied {result.tidied} whitespace spot(s) that cost no tokens "
                "on this model (applied for a cleaner file).",
                style="dim",
            )
        )

    pending = [f for f in result.findings if not f.applied and not f.suggestion.flag_only]
    if pending:
        extra = (
            f"applying all of them saves {extra_if_all:,} more tokens = "
            f"{usd(input_cost(extra_if_all, result.model) * CALLS)} per {CALLS:,} calls"
        )
        console.print(
            Text(
                f"{len(pending)} review suggestion(s) not applied; {extra}. "
                "Check them, then use --apply all or --apply <rule,...>.",
                style="yellow",
            )
        )

    if show_diff and result.optimized != result.original:
        console.print(Panel(diff_text(result.original, result.optimized), title="Diff"))

    console.print(_summary(result))
    if not result.model.exact:
        console.print(Text(ESTIMATE_NOTE, style="yellow"))
    console.print(prices_footer(table))


def _saving(tokens: int, approx: str) -> str:
    return f"{approx}-{tokens:,}" if tokens else "0"


def render_scan(
    console: Console, result: ScanResult, table: PriceTable, folder: str, patterns: str
) -> None:
    model = result.model
    approx = "" if model.exact else "~"
    header = Text.assemble(("tokensaver scan", "bold"), f"  {folder}  ·  {model.name} (")
    console.print(Text.assemble(header, accuracy_label(model), ")"))
    if not result.files:
        console.print(Text(f"No prompt files found (looked for {patterns}).", style="yellow"))
    else:
        out = Table(box=box.SIMPLE_HEAVY, show_footer=True)
        cost = input_cost(result.tokens, model) * CALLS
        saved = result.dollars_saved_all * CALLS
        out.add_column("File", footer=f"Total ({len(result.files)} files)")
        out.add_column("Tokens", f"{approx}{result.tokens:,}", justify="right", no_wrap=True)
        out.add_column(f"$/{CALLS // 1000}k calls", usd(cost), justify="right", no_wrap=True)
        out.add_column(
            "Safe fixes", _saving(result.safe_saved, approx), justify="right", no_wrap=True
        )
        out.add_column(
            "All fixes", _saving(result.all_saved, approx), justify="right", no_wrap=True
        )
        out.add_column("Saved $/1k", usd(saved), justify="right", no_wrap=True)
        for f in result.files:
            out.add_row(
                Text(f.path),
                f"{approx}{f.tokens:,}",
                usd(input_cost(f.tokens, model) * CALLS),
                _saving(f.safe_saved, approx),
                _saving(f.all_saved, approx),
                usd(input_cost(f.all_saved, model) * CALLS),
            )
        console.print(out)
        console.print(
            Text(
                "Safe fixes are what 'optimize' applies by default; all fixes include review "
                "suggestions. Run 'tokensaver optimize FILE' to see them.",
                style="dim",
            )
        )
    if result.skipped:
        console.print(
            Text(f"Skipped (not UTF-8 text): {', '.join(result.skipped)}", style="yellow")
        )
    if not model.exact:
        console.print(Text(ESTIMATE_NOTE, style="yellow"))
    console.print(prices_footer(table))


TOOLS_NOTE = (
    "~ on tool schemas: counted as compact JSON. Providers turn tool definitions into "
    "their own hidden format before the model sees them, so the real count can differ."
)
OVERHEAD_NOTE = "Message overhead (roles and formatting, a few tokens per message) is not counted."


def _part_tokens(tokens: int, exact: bool) -> str:
    return f"{tokens:,}" if exact else f"~{tokens:,}"


def _fixed_table(result: RequestBreakdown) -> Table:
    model = result.model
    out = Table(title="Fixed part: sent with every request", box=box.SIMPLE_HEAVY)
    out.add_column("Part", no_wrap=True)
    out.add_column("Source")
    out.add_column("Tokens", justify="right", no_wrap=True)
    out.add_column(f"$/{CALLS // 1000}k calls", justify="right", no_wrap=True)
    rows: list[tuple[str, Part]] = []
    if result.system is not None:
        rows.append(("System prompt", result.system))
    if result.tools is not None:
        n = result.tools.tool_count
        rows.append((f"Tool schemas ({n} tool{'' if n == 1 else 's'})", result.tools))
    for label, part in rows:
        out.add_row(
            label,
            Text(part.label),
            _part_tokens(part.tokens, part.exact),
            usd(input_cost(part.tokens, model) * CALLS),
        )
    out.add_section()
    out.add_row(
        Text("Fixed part", style="bold"),
        "",
        Text(_part_tokens(result.fixed_tokens, result.fixed_exact), style="bold"),
        Text(usd(input_cost(result.fixed_tokens, model) * CALLS), style="bold"),
    )
    return out


def _requests_table(result: RequestBreakdown) -> Table:
    model = result.model
    out = Table(title="Each request: fixed part + user message", box=box.SIMPLE_HEAVY)
    out.add_column("User message", no_wrap=True, overflow="ellipsis", max_width=40)
    out.add_column("User tokens", justify="right", no_wrap=True)
    out.add_column("Request tokens", justify="right", no_wrap=True)
    out.add_column("Fixed share", justify="right", no_wrap=True)
    out.add_column(f"$/{CALLS // 1000}k calls", justify="right", no_wrap=True)
    for user in result.users:
        total = result.request_tokens(user)
        out.add_row(
            Text(user.label),
            _part_tokens(user.tokens, user.exact),
            _part_tokens(total, result.fixed_exact and user.exact),
            share_label(result.fixed_percent(user)),
            usd(input_cost(total, model) * CALLS),
        )
    return out


def share_label(percent: float) -> str:
    """A whole percent, but never 0% or 100% for a share that is neither none nor all.

    99.6% rounds to 100%, which would read as if the user message cost nothing.
    """
    whole = f"{percent:.0f}"
    if percent <= 0 or percent >= 100 or whole not in ("0", "100"):
        return f"{whole}%"
    one_decimal = f"{percent:.1f}"
    if one_decimal not in ("0.0", "100.0"):
        return f"{one_decimal}%"
    return "<0.1%" if percent < 50 else ">99.9%"


def _share_range(result: RequestBreakdown) -> str:
    shares = [result.fixed_percent(user) for user in result.users]
    low, high = share_label(min(shares)), share_label(max(shares))
    return low if low == high else f"{low} to {high}"


def _hit_rate_label(rate: float) -> str:
    percent = rate * 100
    return f"{percent:.0f}%" if percent == round(percent) else f"{percent:.1f}%"


def _cache_table(cache: CacheEstimate) -> Table:
    out = Table(title="Fixed part with prompt caching", box=box.SIMPLE_HEAVY)
    out.add_column("Call", no_wrap=True)
    out.add_column("$/call", justify="right", no_wrap=True)
    out.add_column(f"$/{CALLS // 1000}k calls", justify="right", no_wrap=True)
    rows = [
        ("No caching", cache.uncached),
        ("First call (writes the cache)", cache.first_call),
        ("Later calls (read from the cache)", cache.cached_call),
    ]
    for label, cost in rows:
        out.add_row(label, usd(cost), usd(cost * CALLS))
    if cache.average is not None and cache.hit_rate is not None:
        out.add_section()
        out.add_row(
            Text(f"Average at {_hit_rate_label(cache.hit_rate)} cache hits", style="bold"),
            Text(usd(cache.average), style="bold"),
            Text(usd(cache.average * CALLS), style="bold"),
        )
    return out


def _render_cache(console: Console, result: RequestBreakdown, cache: CacheEstimate) -> None:
    model = result.model
    tokens = _part_tokens(cache.tokens, result.fixed_exact)
    if cache.below_minimum:
        console.print(
            Text(
                f"Prompt caching: the fixed part ({tokens} tokens) is below {model.name}'s "
                f"minimum of {cache.min_tokens:,} tokens, so it is not cached and every call "
                "pays the full input price.",
                style="yellow",
            )
        )
        return
    console.print(_cache_table(cache))
    console.print(
        Text(
            f"A cached call pays {cache.saving_percent:.0f}% less for the fixed part. The user "
            "message is always billed at the full input price.",
            style="bold",
        )
    )
    if cache.min_tokens is None:
        console.print(
            Text(
                f"{model.provider} publishes no fixed minimum cacheable length for {model.name}; "
                "check that your fixed part is long enough to be cached.",
                style="dim",
            )
        )
    if cache.hit_rate is None:
        console.print(
            Text("Add --cache-hit-rate 0.9 (for example) to see the average per call.", style="dim")
        )


def render_request(
    console: Console,
    result: RequestBreakdown,
    table: PriceTable,
    cache: CacheEstimate | None = None,
) -> None:
    model = result.model
    console.print(
        Text.assemble(
            ("tokensaver request", "bold"), f"  {model.name} (", accuracy_label(model), ")"
        )
    )
    console.print(_fixed_table(result))
    if result.users:
        console.print(_requests_table(result))
        console.print(
            Text(
                f"The fixed part is {_share_range(result)} of each request. It costs the same "
                "whatever the user writes, so shrinking it saves on every call.",
                style="bold",
            )
        )
    else:
        console.print(
            Text("Add --user to see what share of each request the fixed part is.", style="dim")
        )
    if cache is not None:
        _render_cache(console, result, cache)
    if result.tools is not None:
        console.print(Text(TOOLS_NOTE, style="yellow"))
    if not model.exact:
        console.print(Text(ESTIMATE_NOTE, style="yellow"))
    console.print(Text(OVERHEAD_NOTE, style="dim"))
    console.print(prices_footer(table))


PREFIX_NOTE = (
    "Shared prefix is the most the cache could reuse. Providers cache up to set points "
    "(for example message ends), so the cached part can be shorter."
)
DYNAMIC_HINT = (
    "Values that change on every call (dates, times, IDs) break the cache for everything "
    "after them. Move them after the static part, for example into the user message."
)


def _min_tokens_note(shared: int, min_tokens: int) -> str:
    return (
        f"The shared prefix ({shared:,} tokens) is below {min_tokens:,}, the minimum "
        "cacheable prefix on OpenAI GPT-5.6+ (earlier models and other providers vary), "
        "so it may not be cached at all."
    )


def _prefix_table(result: PrefixCheck) -> Table:
    out = Table(title="Each request: shared prefix + the rest", box=box.SIMPLE_HEAVY)
    out.add_column("Request", no_wrap=True, overflow="ellipsis", max_width=40)
    out.add_column("Tokens", justify="right", no_wrap=True)
    out.add_column("Shared prefix", justify="right", no_wrap=True)
    out.add_column("After it", justify="right", no_wrap=True)
    for request in result.requests:
        out.add_row(
            Text(request.source),
            _part_tokens(request.tokens, result.exact),
            _part_tokens(request.shared_tokens, result.exact),
            _part_tokens(request.rest_tokens, result.exact),
        )
    return out


def _differences_table(result: PrefixCheck) -> Table:
    out = Table(title="Where each request leaves the shared prefix", box=box.SIMPLE_HEAVY)
    out.add_column("Request", no_wrap=True, overflow="ellipsis", max_width=30)
    out.add_column("Part", no_wrap=True)
    out.add_column("Line:col", justify="right", no_wrap=True)
    out.add_column("Text there", overflow="fold")
    out.add_column("Looks like", no_wrap=True)
    for diff in result.differences:
        if diff.part is None:
            out.add_row(Text(diff.source), Text("(request ends)", style="dim"), "", "", "")
            continue
        out.add_row(
            Text(diff.source),
            Text(diff.part, style="red" if diff.fixed else ""),
            f"{diff.line}:{diff.column}" if diff.line else "role",
            Text(diff.snippet) if diff.snippet else Text("(blank line)", style="dim"),
            Text(diff.dynamic or "", style="yellow"),
        )
    return out


def render_prefix(console: Console, result: PrefixCheck, min_tokens: int) -> None:
    model = result.model
    console.print(
        Text.assemble(
            ("tokensaver cache-check", "bold"), f"  {model.name} (", accuracy_label(model), ")"
        )
    )
    console.print(_prefix_table(result))
    shared = _part_tokens(result.shared_tokens, result.exact)
    if result.identical:
        console.print(
            Text(f"All {len(result.requests)} requests are identical.", style="bold green")
        )
    else:
        console.print(_differences_table(result))
        if result.fixed_differs:
            console.print(
                Text(
                    "The fixed part (tools or system prompt) differs between requests, so the "
                    f"cache can reuse at most the first {shared} tokens.",
                    style="bold red",
                )
            )
        else:
            console.print(
                Text(
                    "The fixed part is identical; the requests only differ from the "
                    f"conversation on. Shared prefix: {shared} tokens.",
                    style="bold green",
                )
            )
        if any(d.dynamic for d in result.differences):
            console.print(Text(DYNAMIC_HINT, style="yellow"))
    if result.shared_tokens < min_tokens:
        console.print(Text(_min_tokens_note(result.shared_tokens, min_tokens), style="yellow"))
    if result.has_tools:
        console.print(Text(TOOLS_NOTE, style="yellow"))
    if not model.exact:
        console.print(Text(ESTIMATE_NOTE, style="yellow"))
    console.print(Text(PREFIX_NOTE, style="dim"))
