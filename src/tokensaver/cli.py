"""Command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from tokensaver import __version__
from tokensaver.counter import count_tokens
from tokensaver.inputs import PromptInput, resolve_input
from tokensaver.optimizer import RULE_NAMES, optimize, resolve_selection
from tokensaver.output import (
    cheapest_first,
    render_compare,
    render_count,
    render_models,
    render_optimize,
    render_prefix,
    render_request,
    render_scan,
)
from tokensaver.prefix import RequestInputError, check, render_input
from tokensaver.pricing import (
    ModelInfo,
    PriceDataError,
    PriceTable,
    UnknownModelError,
    load_prices,
)
from tokensaver.report import (
    compare_report,
    count_report,
    dumps,
    optimize_report,
    prefix_report,
    request_report,
    scan_report,
)
from tokensaver.request import ToolsError, breakdown, cache_estimate
from tokensaver.scan import DEFAULT_PATTERNS, scan

DEFAULT_MODEL = "gpt-4o"
MIN_CACHEABLE_TOKENS = 1024  # OpenAI GPT-5.6+; earlier models and other providers vary

app = typer.Typer(
    help="Count tokens, compare model costs and get concrete savings for your prompts. "
    "Everything runs offline; your prompt never leaves your machine.",
    no_args_is_help=True,
    add_completion=False,
)

InputArg = Annotated[
    str,
    typer.Argument(help="A file path, '-' for stdin, or the prompt text itself.", metavar="INPUT"),
]
ModelOpt = Annotated[
    str, typer.Option("--model", "-m", help="Model to price against (see 'tokensaver models').")
]
PricesOpt = Annotated[
    Path | None,
    typer.Option(help="Use a custom prices.json instead of the bundled one.", dir_okay=False),
]
JsonOpt = Annotated[
    bool, typer.Option("--json", help="Print JSON instead of tables, for scripts and CI.")
]


def _console() -> Console:
    return Console(highlight=False)


def _fail(message: str) -> typer.Exit:
    Console(stderr=True, highlight=False).print(f"[red]Error:[/red] {message}", markup=True)
    return typer.Exit(code=2)


def _load_table(prices: Path | None) -> PriceTable:
    try:
        return load_prices(prices)
    except FileNotFoundError:
        raise _fail(f"Prices file not found: {prices}") from None
    except (PriceDataError, ValueError) as error:
        raise _fail(f"Invalid prices file: {error}") from None


def _get_model(table: PriceTable, name: str) -> ModelInfo:
    try:
        return table.get(name)
    except UnknownModelError as error:
        raise _fail(f"{error} Run 'tokensaver models' to list them.") from None


def _read(value: str) -> PromptInput:
    try:
        return resolve_input(value)
    except FileNotFoundError as error:
        raise _fail(str(error)) from None
    except UnicodeDecodeError:
        raise _fail(f"{value} is not UTF-8 text.") from None


@app.callback()
def main() -> None:
    """Count tokens, compare model costs and get concrete savings for your prompts."""
    # Never crash on characters a legacy Windows code page cannot show.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


@app.command()
def count(
    input: InputArg,
    model: ModelOpt = DEFAULT_MODEL,
    prices: PricesOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """Show the token count and input cost for one model."""
    table = _load_table(prices)
    info = _get_model(table, model)
    prompt = _read(input)
    tokens = count_tokens(prompt.text, info)
    if json_output:
        typer.echo(dumps(count_report(tokens, info, table, prompt.source)))
    else:
        render_count(_console(), tokens, info, table, prompt.source)


@app.command()
def compare(
    input: InputArg,
    models: Annotated[
        str | None,
        typer.Option(help="Comma-separated models to compare (default: all)."),
    ] = None,
    prices: PricesOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """Compare tokens and input cost across models, cheapest first."""
    table = _load_table(prices)
    names = [n.strip() for n in models.split(",") if n.strip()] if models else list(table.models)
    infos = [_get_model(table, name) for name in names]
    prompt = _read(input)
    rows = [(info, count_tokens(prompt.text, info)) for info in infos]
    if json_output:
        typer.echo(dumps(compare_report(cheapest_first(rows), table, prompt.source)))
    else:
        render_compare(_console(), rows, table, prompt.source)


@app.command(name="optimize")
def optimize_command(
    input: InputArg,
    model: ModelOpt = DEFAULT_MODEL,
    apply: Annotated[
        str,
        typer.Option(
            help="Rules to apply: 'safe' (default), 'all', 'none' or a comma list of: "
            + ", ".join(RULE_NAMES)
        ),
    ] = "safe",
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Save the optimized prompt to this file.", dir_okay=False
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite --output if it already exists.")
    ] = False,
    diff: Annotated[
        bool, typer.Option("--diff/--no-diff", help="Show the before/after diff.")
    ] = True,
    prices: PricesOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """Suggest concrete changes, with the tokens and dollars each one saves."""
    table = _load_table(prices)
    info = _get_model(table, model)
    try:
        selected = resolve_selection(apply)
    except ValueError as error:
        raise _fail(str(error)) from None
    prompt = _read(input)

    if output is not None:
        _check_output(output, prompt, force)

    result = optimize(prompt.text, info, selected)
    extra_if_all = 0
    if any(not f.applied and not f.suggestion.flag_only for f in result.findings):
        everything = optimize(prompt.text, info, resolve_selection("all"))
        extra_if_all = max(result.tokens_after - everything.tokens_after, 0)
    if output is not None:
        output.write_text(result.optimized, encoding="utf-8")

    if json_output:
        report = optimize_report(result, table, prompt.source, extra_if_all, saved_to=output)
        typer.echo(dumps(report))
        return
    console = _console()
    render_optimize(
        console, result, table, prompt.source, show_diff=diff, extra_if_all=extra_if_all
    )
    if output is not None:
        console.print(f"Saved optimized prompt to {output}", markup=False)


def _check_output(output: Path, prompt: PromptInput, force: bool) -> None:
    """Never overwrite the input file; only overwrite other files with --force."""
    if prompt.path is not None and output.exists() and output.resolve() == prompt.path.resolve():
        raise _fail("--output must be a different file; the original is never overwritten.")
    if output.exists() and not force:
        raise _fail(f"{output} already exists. Use --force to overwrite it.")


@app.command(name="scan")
def scan_command(
    folder: Annotated[
        Path, typer.Argument(help="Folder to scan, subfolders included.", show_default=False)
    ],
    model: ModelOpt = DEFAULT_MODEL,
    glob: Annotated[
        list[str] | None,
        typer.Option(
            "--glob",
            help="File name pattern to include; repeat for several. "
            "Default: " + " ".join(DEFAULT_PATTERNS),
        ),
    ] = None,
    prices: PricesOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """Measure every prompt file in a folder, biggest possible saving first."""
    table = _load_table(prices)
    info = _get_model(table, model)
    if not folder.is_dir():
        raise _fail(f"Not a folder: {folder}. For a single file, use 'tokensaver optimize'.")
    patterns = tuple(glob) if glob else DEFAULT_PATTERNS
    result = scan(folder, info, patterns)
    if json_output:
        typer.echo(dumps(scan_report(result, table, str(folder))))
    else:
        render_scan(_console(), result, table, str(folder), " ".join(patterns))


@app.command(name="request")
def request_command(
    system: Annotated[
        str | None,
        typer.Option(help="System prompt: a file path, '-' for stdin, or the text itself."),
    ] = None,
    tools: Annotated[
        str | None,
        typer.Option(help="Tool schemas as JSON (OpenAI or Anthropic format): a file or '-'."),
    ] = None,
    user: Annotated[
        list[str] | None,
        typer.Option(
            "--user",
            help="A user message (file, '-' or text). Repeat it to compare several, "
            "for example the same message in different languages.",
        ),
    ] = None,
    cache_hit_rate: Annotated[
        float | None,
        typer.Option(
            help="Share of calls that read the fixed part from the prompt cache (0 to 1), "
            "to show the average cost per call.",
            min=0.0,
            max=1.0,
        ),
    ] = None,
    model: ModelOpt = DEFAULT_MODEL,
    prices: PricesOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """Split a request into its fixed part (system prompt + tools) and the user message."""
    if system is None and tools is None:
        raise _fail("Pass --system and/or --tools: they are the fixed part of every request.")
    users = user or []
    if [system, tools, *users].count("-") > 1:
        raise _fail("Only one input can be read from stdin ('-').")
    table = _load_table(prices)
    info = _get_model(table, model)
    system_in = _read(system) if system is not None else None
    tools_in = _read(tools) if tools is not None else None
    users_in = [_read(value) for value in users]
    try:
        result = breakdown(
            info,
            system=(system_in.text, system_in.source) if system_in else None,
            tools=(tools_in.text, tools_in.source) if tools_in else None,
            users=[(u.text, u.source) for u in users_in],
        )
    except ToolsError as error:
        raise _fail(str(error)) from None
    cache = cache_estimate(result, cache_hit_rate)
    if json_output:
        typer.echo(dumps(request_report(result, table, cache)))
    else:
        render_request(_console(), result, table, cache)


@app.command(name="cache-check")
def cache_check_command(
    inputs: Annotated[
        list[str],
        typer.Argument(
            help="Two or more requests to compare: request bodies as JSON (tools, "
            "system/instructions, messages/input) or plain-text system prompts. "
            "Each is a file path or '-' for stdin.",
            metavar="REQUEST...",
            show_default=False,
        ),
    ],
    tools: Annotated[
        str | None,
        typer.Option(help="Tool schemas (JSON file or '-') to put in front of plain-text prompts."),
    ] = None,
    min_tokens: Annotated[
        int,
        typer.Option(
            help="Warn when the shared prefix is shorter than this. 1,024 is OpenAI's minimum "
            "for GPT-5.6+; check your provider's docs.",
            min=0,
        ),
    ] = MIN_CACHEABLE_TOKENS,
    model: ModelOpt = DEFAULT_MODEL,
    prices: PricesOpt = None,
    json_output: JsonOpt = False,
) -> None:
    """Check that requests start with the same bytes, so prompt caching can reuse them."""
    if len(inputs) < 2:
        raise _fail("Pass at least two requests to compare.")
    if [*inputs, tools].count("-") > 1:
        raise _fail("Only one input can be read from stdin ('-').")
    table = _load_table(prices)
    info = _get_model(table, model)
    tools_in = _read(tools) if tools is not None else None
    try:
        rendered = [
            render_input(p.text, p.source, tools_in.text if tools_in else None)
            for p in (_read(value) for value in inputs)
        ]
    except (RequestInputError, ToolsError) as error:
        raise _fail(str(error)) from None
    result = check(rendered, info)
    if json_output:
        typer.echo(dumps(prefix_report(result, table, min_tokens)))
    else:
        render_prefix(_console(), result, min_tokens)


@app.command()
def models(prices: PricesOpt = None) -> None:
    """List supported models and their prices."""
    render_models(_console(), _load_table(prices))


@app.command()
def version() -> None:
    """Show the installed version."""
    typer.echo(__version__)
