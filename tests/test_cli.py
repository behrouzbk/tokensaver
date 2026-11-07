import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tokensaver import __version__
from tokensaver.cli import app
from tokensaver.output import share_label, usd
from tokensaver.pricing import load_prices

MESSY = (
    "I would like you to please summarize the text below.   \n"
    "Always respond in JSON format.\n\n\n\n"
    '{\n    "name": "string",\n    "tags": [\n        "a",\n        "b"\n    ]\n}\n\n'
    "Remember to always respond in JSON.\n"
    "Thanks in advance!\n"
)


@pytest.fixture
def run():
    runner = CliRunner()

    def invoke(*args: str, input: str | None = None):
        return runner.invoke(app, list(args), input=input, env={"COLUMNS": "200"})

    return invoke


@pytest.fixture
def messy_file(tmp_path: Path) -> Path:
    path = tmp_path / "messy.txt"
    path.write_text(MESSY, encoding="utf-8")
    return path


# --- count -------------------------------------------------------------------


def test_count_text(run) -> None:
    result = run("count", "Hello, world!")
    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "exact" in result.output
    assert "Tokens" in result.output and " 4 " in result.output
    assert "2026-11-07" in result.output


def test_count_file(run, messy_file: Path) -> None:
    result = run("count", str(messy_file), "--model", "gpt-4o-mini")
    assert result.exit_code == 0
    assert "messy.txt" in result.output


def test_count_stdin(run) -> None:
    result = run("count", "-", input="piped prompt")
    assert result.exit_code == 0
    assert "stdin" in result.output


def test_count_estimated_model_is_labelled(run) -> None:
    result = run("count", "Hello, world!", "-m", "claude-opus-5-5")
    assert result.exit_code == 0
    assert "estimated" in result.output
    assert "~" in result.output


def test_count_unknown_model(run) -> None:
    result = run("count", "Hello", "-m", "gpt-4-o")
    assert result.exit_code == 2
    assert "Did you mean" in result.output
    assert "gpt-4o" in result.output


def test_count_missing_file(run) -> None:
    result = run("count", "no_such_file.txt")
    assert result.exit_code == 2
    assert "File not found" in result.output


def test_count_with_custom_prices(run, tmp_path: Path) -> None:
    prices = tmp_path / "prices.json"
    prices.write_text(
        json.dumps(
            {
                "last_updated": "2030-01-02",
                "models": {
                    "my-model": {
                        "provider": "Me",
                        "input_per_1m": 1_000_000,
                        "output_per_1m": 0,
                        "tokenizer": "o200k_base",
                        "exact": False,
                        "estimate_factor": 1.0,
                        "source_url": "https://example.com",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = run("count", "Hello, world!", "-m", "my-model", "--prices", str(prices))
    assert result.exit_code == 0
    assert "2030-01-02" in result.output
    assert "$4.00" in result.output  # 4 tokens at $1 each


def test_invalid_prices_file(run, tmp_path: Path) -> None:
    prices = tmp_path / "prices.json"
    prices.write_text('{"models": {}}', encoding="utf-8")
    result = run("count", "Hello", "--prices", str(prices))
    assert result.exit_code == 2
    assert "Invalid prices file" in result.output


# --- compare -----------------------------------------------------------------


def test_compare_all_models(run, messy_file: Path) -> None:
    result = run("compare", str(messy_file))
    assert result.exit_code == 0
    for name in load_prices().models:
        assert name in result.output
    assert "estimated" in result.output and "exact" in result.output
    assert "2026-11-07" in result.output


def test_compare_selected_models_sorted_by_cost(run) -> None:
    result = run("compare", "Some prompt text here.", "--models", "gpt-4o,gpt-4o-mini")
    assert result.exit_code == 0
    assert result.output.index("gpt-4o-mini") < result.output.index("gpt-4o ")
    assert "claude" not in result.output


def test_compare_unknown_model(run) -> None:
    result = run("compare", "text", "--models", "gpt-4o,nope")
    assert result.exit_code == 2


# --- optimize ----------------------------------------------------------------


def test_optimize_shows_suggestions_diff_and_savings(run, messy_file: Path) -> None:
    result = run("optimize", str(messy_file))
    assert result.exit_code == 0
    out = result.output
    assert "Minify JSON block" in out
    assert "applied" in out and "review" in out
    assert "Diff" in out and "--- before" in out
    assert "Total savings on gpt-4o" in out
    assert "--apply all" in out  # hint about unapplied review suggestions


def test_optimize_apply_all_applies_review_rules(run, messy_file: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "out.txt"
    result = run("optimize", str(messy_file), "--apply", "all", "-o", str(out_file))
    assert result.exit_code == 0
    optimized = out_file.read_text(encoding="utf-8")
    assert optimized.startswith("Summarize the text below.")
    assert "Thanks" not in optimized
    assert "Remember to always" not in optimized


def test_optimize_output_keeps_original(run, messy_file: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "optimized.txt"
    result = run("optimize", str(messy_file), "--output", str(out_file))
    assert result.exit_code == 0
    assert "Saved optimized prompt" in result.output
    assert messy_file.read_text(encoding="utf-8") == MESSY
    optimized = out_file.read_text(encoding="utf-8")
    assert '{"name":"string","tags":["a","b"]}' in optimized
    assert "I would like you to" in optimized  # review rules not applied by default


def test_optimize_refuses_to_overwrite_input(run, messy_file: Path) -> None:
    result = run("optimize", str(messy_file), "-o", str(messy_file), "--force")
    assert result.exit_code == 2
    assert "never overwritten" in result.output
    assert messy_file.read_text(encoding="utf-8") == MESSY


def test_optimize_refuses_existing_output_without_force(run, messy_file, tmp_path) -> None:
    out_file = tmp_path / "exists.txt"
    out_file.write_text("keep me", encoding="utf-8")
    result = run("optimize", str(messy_file), "-o", str(out_file))
    assert result.exit_code == 2
    assert out_file.read_text(encoding="utf-8") == "keep me"

    forced = run("optimize", str(messy_file), "-o", str(out_file), "--force")
    assert forced.exit_code == 0
    assert out_file.read_text(encoding="utf-8") != "keep me"


def test_optimize_invalid_apply(run, messy_file: Path) -> None:
    result = run("optimize", str(messy_file), "--apply", "everything")
    assert result.exit_code == 2
    assert "Unknown rule" in result.output


def test_optimize_no_diff(run, messy_file: Path) -> None:
    result = run("optimize", str(messy_file), "--no-diff")
    assert result.exit_code == 0
    assert "--- before" not in result.output


def test_optimize_clean_prompt(run) -> None:
    result = run("optimize", "Summarize the text in three bullet points.")
    assert result.exit_code == 0
    assert "already lean" in result.output


def test_optimize_reports_tidied_whitespace(run) -> None:
    result = run("optimize", "Intro\n\n\n\nBody")
    assert result.exit_code == 0
    assert "Also tidied 1 whitespace spot" in result.output


def test_optimize_estimated_model(run, messy_file: Path) -> None:
    result = run("optimize", str(messy_file), "-m", "gemini-2.5-flash")
    assert result.exit_code == 0
    assert "estimated" in result.output


def test_user_text_is_not_treated_as_markup(run) -> None:
    result = run("optimize", "Use [bold]this[/bold] and [red]that[/red]   ")
    assert result.exit_code == 0
    assert "[bold]this[/bold]" in result.output


EXAMPLE = Path(__file__).parents[1] / "examples" / "messy_prompt.txt"


def test_bundled_example_shows_clear_savings(run, tmp_path: Path) -> None:
    out_file = tmp_path / "optimized.txt"
    result = run("optimize", str(EXAMPLE), "--apply", "all", "-o", str(out_file))
    assert result.exit_code == 0
    assert "Total savings" in result.output

    from tokensaver.optimizer import optimize, resolve_selection

    text = EXAMPLE.read_text(encoding="utf-8")
    full = optimize(text, load_prices().get("gpt-4o"), resolve_selection("all"))
    assert full.percent_saved > 15
    assert optimize(text, load_prices().get("gpt-4o")).tokens_saved > 0  # safe rules alone
    # Few-shot examples are left exactly as written.
    assert "Can you please explain what happened" in out_file.read_text(encoding="utf-8")


# --- scan --------------------------------------------------------------------


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "prompts"
    (folder / "sub").mkdir(parents=True)
    (folder / "messy.txt").write_text(MESSY, encoding="utf-8")
    (folder / "sub" / "lean.md").write_text("Summarize the text.", encoding="utf-8")
    (folder / "notes.py").write_text("print('not a prompt')", encoding="utf-8")
    return folder


def test_scan_lists_files_by_savings(run, prompts_dir: Path) -> None:
    result = run("scan", str(prompts_dir))
    assert result.exit_code == 0
    out = result.output
    assert out.index("messy.txt") < out.index("sub/lean.md")
    assert "notes.py" not in out
    assert "Total (2 files)" in out
    assert "Safe fixes" in out and "All fixes" in out


def test_scan_glob_and_no_matches(run, prompts_dir: Path) -> None:
    result = run("scan", str(prompts_dir), "--glob", "*.md")
    assert result.exit_code == 0
    assert "lean.md" in result.output and "messy.txt" not in result.output

    none = run("scan", str(prompts_dir), "--glob", "*.yaml")
    assert none.exit_code == 0
    assert "No prompt files found" in none.output


def test_scan_rejects_a_file(run, messy_file: Path) -> None:
    result = run("scan", str(messy_file))
    assert result.exit_code == 2
    assert "Not a folder" in result.output


def test_scan_estimated_model(run, prompts_dir: Path) -> None:
    result = run("scan", str(prompts_dir), "-m", "gemini-2.5-flash")
    assert result.exit_code == 0
    assert "estimated" in result.output and "~" in result.output


# --- --json ------------------------------------------------------------------


def test_count_json(run) -> None:
    result = run("count", "Hello, world!", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {
        "source": "text",
        "model": "gpt-4o",
        "exact": True,
        "prices_last_updated": "2026-11-07",
        "tokens": 4,
        "cost_per_call": 0.00001,
    }


def test_compare_json_is_cheapest_first(run) -> None:
    result = run("compare", "Some prompt text here.", "--models", "gpt-4o,gpt-4o-mini", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [m["model"] for m in data["models"]] == ["gpt-4o-mini", "gpt-4o"]
    assert all(m["exact"] for m in data["models"])


def test_optimize_json(run, messy_file: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "out.txt"
    result = run("optimize", str(messy_file), "--json", "-o", str(out_file))
    assert result.exit_code == 0
    data = json.loads(result.output)  # nothing but JSON, even with --output
    assert data["source"] == "messy.txt"
    assert data["tokens_before"] - data["tokens_after"] == data["tokens_saved"] > 0
    assert data["extra_tokens_if_all_applied"] > 0
    assert data["saved_to"] == str(out_file)
    assert out_file.exists()
    rules = {f["rule"]: f for f in data["findings"]}
    assert rules["json"]["risk"] == "safe" and rules["json"]["applied"] is True
    assert rules["filler"]["risk"] == "review" and rules["filler"]["applied"] is False


def test_json_escapes_non_ascii(run) -> None:
    result = run("optimize", "لطفاً متن را خلاصه کن.", "--json")
    assert result.exit_code == 0
    assert result.output.isascii()
    titles = [f["title"] for f in json.loads(result.output)["findings"]]
    assert any("لطفاً" in t for t in titles)


def test_scan_json(run, prompts_dir: Path) -> None:
    result = run("scan", str(prompts_dir), "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [f["path"] for f in data["files"]] == ["messy.txt", "sub/lean.md"]
    assert data["total"]["files"] == 2
    assert data["total"]["all_tokens_saved"] == sum(f["all_tokens_saved"] for f in data["files"])
    assert data["skipped"] == []


# --- request -----------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Look up an order by its number.",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
        },
    }
]


@pytest.fixture
def tools_file(tmp_path: Path) -> Path:
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(TOOLS, indent=2), encoding="utf-8")
    return path


def test_request_breakdown(run, messy_file: Path, tools_file: Path) -> None:
    result = run(
        "request",
        "--system", str(messy_file),
        "--tools", str(tools_file),
        "--user", "Where is my order?",
        "--user", "我的订单在哪里？",
    )  # fmt: skip
    assert result.exit_code == 0
    out = result.output
    assert "System prompt" in out and "messy.txt" in out
    assert "Tool schemas (1 tool)" in out and "tools.json" in out
    assert "Fixed part" in out
    assert "Where is my order?" in out and "我的订单在哪里？" in out
    assert "of each request" in out
    assert "tool definitions" in out  # tool counts are labelled as estimates


def test_request_without_user_hints_at_it(run, messy_file: Path) -> None:
    result = run("request", "--system", str(messy_file))
    assert result.exit_code == 0
    assert "Add --user" in result.output
    assert "tool definitions" not in result.output


def test_request_needs_a_fixed_part(run) -> None:
    result = run("request", "--user", "Hello")
    assert result.exit_code == 2
    assert "--system" in result.output


def test_request_only_one_stdin(run) -> None:
    result = run("request", "--system", "-", "--user", "-", input="x")
    assert result.exit_code == 2
    assert "stdin" in result.output


def test_request_invalid_tools(run, tmp_path: Path) -> None:
    bad = tmp_path / "tools.json"
    bad.write_text("{not json", encoding="utf-8")
    result = run("request", "--tools", str(bad))
    assert result.exit_code == 2
    assert "not valid JSON" in result.output


def test_request_estimated_model(run, messy_file: Path) -> None:
    result = run("request", "--system", str(messy_file), "-m", "claude-sonnet-5-5")
    assert result.exit_code == 0
    assert "estimated" in result.output and "~" in result.output


def test_request_json(run, messy_file: Path, tools_file: Path) -> None:
    result = run(
        "request",
        "--system", str(messy_file),
        "--tools", str(tools_file),
        "--user", "Where is my order?",
        "--json",
    )  # fmt: skip
    assert result.exit_code == 0
    data = json.loads(result.output)
    fixed = data["fixed"]
    assert fixed["system"]["source"] == "messy.txt" and fixed["system"]["exact"] is True
    assert fixed["tools"]["tool_count"] == 1 and fixed["tools"]["exact"] is False
    assert fixed["tokens"] == fixed["system"]["tokens"] + fixed["tools"]["tokens"]
    assert fixed["exact"] is False
    [request] = data["requests"]
    assert request["tokens"] == fixed["tokens"] + request["user"]["tokens"]
    assert 0 < request["fixed_percent"] < 100


def test_request_share_never_rounds_to_100(run, tmp_path: Path) -> None:
    system = tmp_path / "system.txt"
    system.write_text("Answer briefly. " * 100, encoding="utf-8")  # 300 tokens on gpt-4o
    result = run("request", "--system", str(system), "--user", "Hi")  # 1 token: 99.67%
    assert result.exit_code == 0
    assert "100%" not in result.output
    assert "99.7%" in result.output


@pytest.mark.parametrize(
    ("percent", "label"),
    [
        (0, "0%"),
        (0.04, "<0.1%"),
        (0.3, "0.3%"),
        (0.5, "0.5%"),
        (0.7, "1%"),
        (42.4, "42%"),
        (98.6, "99%"),
        (99.4, "99%"),
        (99.6, "99.6%"),
        (99.5, "99.5%"),
        (99.9, "99.9%"),
        (99.94, "99.9%"),
        (99.97, ">99.9%"),
        (100, "100%"),
    ],
)
def test_share_label(percent: float, label: str) -> None:
    assert share_label(percent) == label


# --- models / version / misc -------------------------------------------------


def test_models_lists_everything(run) -> None:
    result = run("models")
    assert result.exit_code == 0
    for name in load_prices().models:
        assert name in result.output


def test_version(run) -> None:
    result = run("version")
    assert result.exit_code == 0
    assert __version__ in result.output


def test_no_args_shows_help(run) -> None:
    result = run()
    assert "count" in result.output and "optimize" in result.output


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (0, "$0"),
        (1234.5, "$1,234.50"),
        (0.0175, "$0.0175"),
        (0.0025, "$0.0025"),
        (2e-6, "$0.000002"),
    ],
)
def test_usd_format(amount: float, text: str) -> None:
    assert usd(amount) == text


# --- cache-check -------------------------------------------------------------


def _request_file(tmp_path: Path, name: str, system: str, user: str) -> Path:
    path = tmp_path / name
    body = {
        "tools": TOOLS,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def test_cache_check_finds_a_timestamp(run, tmp_path: Path) -> None:
    a = _request_file(tmp_path, "a.json", "Now: 2026-11-07T10:15:00Z\n" + MESSY, "hi")
    b = _request_file(tmp_path, "b.json", "Now: 2026-11-07T10:16:42Z\n" + MESSY, "hi")
    result = run("cache-check", str(a), str(b))
    assert result.exit_code == 0
    out = result.output
    assert "messages[0] (system)" in out
    assert "date/time" in out
    assert "fixed part (tools or system prompt) differs" in out
    assert "below 1,024" in out


def test_cache_check_fixed_part_identical(run, tmp_path: Path) -> None:
    a = _request_file(tmp_path, "a.json", MESSY, "Where is my order?")
    b = _request_file(tmp_path, "b.json", MESSY, "I want a refund")
    result = run("cache-check", str(a), str(b), "--min-tokens", "0")
    assert result.exit_code == 0
    assert "The fixed part is identical" in result.output
    assert "below" not in result.output


def test_cache_check_plain_prompts_with_tools(run, messy_file: Path, tools_file: Path) -> None:
    result = run("cache-check", str(messy_file), "-", "--tools", str(tools_file), input=MESSY)
    assert result.exit_code == 0
    assert "All 2 requests are identical" in result.output


def test_cache_check_json(run, tmp_path: Path) -> None:
    a = _request_file(tmp_path, "a.json", MESSY, "Where is my order?")
    b = _request_file(tmp_path, "b.json", MESSY, "I want a refund")
    result = run("cache-check", str(a), str(b), "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["identical"] is False
    assert data["fixed_part_differs"] is False
    assert data["shared_prefix"]["min_cacheable_tokens"] == 1024
    assert [d["part"] for d in data["differences"]] == ["messages[1] (user)"] * 2
    for request in data["requests"]:
        assert request["shared_prefix_tokens"] + request["tokens_after_prefix"] == request["tokens"]


def test_cache_check_needs_two_inputs(run, messy_file: Path) -> None:
    result = run("cache-check", str(messy_file))
    assert result.exit_code == 2
    assert "at least two" in result.output


def test_cache_check_only_one_stdin(run) -> None:
    result = run("cache-check", "-", "-", input="x")
    assert result.exit_code == 2


def test_cache_check_bad_tools_in_body(run, tmp_path: Path, messy_file: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"tools": "x", "system": "hi"}', encoding="utf-8")
    result = run("cache-check", str(bad), str(messy_file))
    assert result.exit_code == 2
    assert "bad.json" in result.output


# --- request: prompt caching ---------------------------------------------------


def test_request_shows_caching(run, messy_file: Path) -> None:
    result = run("request", "--system", str(messy_file), "--user", "hi")
    assert result.exit_code == 0
    out = result.output
    assert "Fixed part with prompt caching" in out
    assert "Later calls (read from the cache)" in out
    assert "50% less" in out  # gpt-4o cached input is half price
    assert "--cache-hit-rate" in out


def test_request_cache_hit_rate(run, messy_file: Path) -> None:
    result = run("request", "--system", str(messy_file), "--cache-hit-rate", "0.9")
    assert result.exit_code == 0
    assert "Average at 90% cache hits" in result.output


def test_request_cache_hit_rate_out_of_range(run, messy_file: Path) -> None:
    result = run("request", "--system", str(messy_file), "--cache-hit-rate", "1.5")
    assert result.exit_code == 2


def test_request_below_minimum(run, messy_file: Path) -> None:
    result = run("request", "--system", str(messy_file), "-m", "gpt-6.1-sol")
    assert result.exit_code == 0
    assert "below gpt-6.1-sol's minimum of 1,024 tokens" in result.output
    assert "Fixed part with prompt caching" not in result.output


def test_request_json_caching(run, tmp_path: Path) -> None:
    long_prompt = tmp_path / "long.txt"
    long_prompt.write_text(MESSY * 20, encoding="utf-8")  # above the 512-token minimum
    args = ("request", "--system", str(long_prompt), "-m", "claude-sonnet-5-5")
    data = json.loads(run(*args, "--cache-hit-rate", "0.5", "--json").output)
    cache = data["caching"]
    assert cache["below_minimum"] is False
    assert cache["cached_input_per_1m"] == 0.1
    assert cache["cache_write_per_1m"] == 2.5
    assert cache["min_cacheable_tokens"] == 512
    assert cache["hit_rate"] == 0.5
    costs = cache["fixed_cost_per_call"]
    assert costs["first_call"] > costs["uncached"] > costs["cached_call"]
    assert costs["average"] == pytest.approx((costs["first_call"] + costs["cached_call"]) / 2)
    assert cache["cached_call_saving_percent"] == pytest.approx(95)


def test_models_lists_cached_price(run) -> None:
    result = run("models")
    assert result.exit_code == 0
    assert "Cached in / 1M" in result.output
