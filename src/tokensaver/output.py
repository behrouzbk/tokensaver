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
from tokensaver.pricing import ModelInfo, PriceTable, input_cost
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
    out.add_column("Count")
    for model in table.models.values():
        out.add_row(
            model.name,
            model.provider,
            usd(model.input_per_1m),
            usd(model.output_per_1m),
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
