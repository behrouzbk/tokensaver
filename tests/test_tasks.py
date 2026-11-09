import json

import pytest

from tokensaver.pricing import load_prices
from tokensaver.tasks import (
    TaskLogError,
    Usage,
    call_cost,
    parse_log,
    parse_usage,
    resolve_model,
    summarize,
)

TABLE = load_prices()
SONNET = TABLE.get("claude-sonnet-5-5")  # $2 in, $10 out, $0.10 read, $2.50 write
GPT4O = TABLE.get("gpt-4o")  # $2.50 in, $10 out, $1.25 read


def line(task: str, usage: dict, passed: bool | None = None, **extra: object) -> str:
    entry: dict = {"task": task, "model": "claude-sonnet-5-5", "usage": usage, **extra}
    if passed is not None:
        entry["passed"] = passed
    return json.dumps(entry)


def anthropic(inp: int = 0, read: int = 0, write: int = 0, out: int = 0) -> dict:
    return {
        "input_tokens": inp,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": write,
        "output_tokens": out,
    }


# --- parse_usage -----------------------------------------------------------------


def test_anthropic_usage_keeps_cache_separate() -> None:
    usage = parse_usage(anthropic(inp=50, read=1000, write=200, out=80))
    assert usage == Usage(input=50, cache_read=1000, cache_write=200, output=80)


def test_anthropic_one_hour_writes_are_split_out() -> None:
    raw = {
        **anthropic(inp=10, write=300, out=5),
        "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200},
    }
    usage = parse_usage(raw)
    assert (usage.cache_write, usage.cache_write_1h) == (100, 200)


def test_openai_chat_usage_subtracts_cached_from_prompt() -> None:
    raw = {
        "prompt_tokens": 1200,
        "completion_tokens": 90,
        "prompt_tokens_details": {"cached_tokens": 1024},
    }
    assert parse_usage(raw) == Usage(input=176, cache_read=1024, output=90)


def test_openai_responses_usage() -> None:
    raw = {
        "input_tokens": 1500,
        "output_tokens": 40,
        "input_tokens_details": {"cached_tokens": 1280},
    }
    assert parse_usage(raw) == Usage(input=220, cache_read=1280, output=40)


def test_gemini_usage_counts_thinking_as_output() -> None:
    raw = {
        "promptTokenCount": 2000,
        "cachedContentTokenCount": 1500,
        "candidatesTokenCount": 100,
        "thoughtsTokenCount": 300,
    }
    assert parse_usage(raw) == Usage(input=500, cache_read=1500, output=400)


@pytest.mark.parametrize("raw", [{}, {"total": 5}, {"input_tokens": -1}, {"input_tokens": 1.5}])
def test_bad_usage_is_rejected(raw: dict) -> None:
    with pytest.raises(TaskLogError):
        parse_usage(raw)


# --- pricing ----------------------------------------------------------------------


def test_call_cost_prices_each_kind_of_token() -> None:
    usage = Usage(input=1_000_000, cache_read=1_000_000, cache_write=1_000_000, output=1_000_000)
    assert call_cost(usage, SONNET) == pytest.approx(2 + 0.10 + 2.50 + 10)


def test_one_hour_write_costs_twice_the_input_price() -> None:
    assert call_cost(Usage(cache_write_1h=1_000_000), SONNET) == pytest.approx(4.0)


def test_cache_read_is_cheaper_than_input() -> None:
    cold = call_cost(Usage(input=1000), GPT4O)
    warm = call_cost(Usage(cache_read=1000), GPT4O)
    assert warm == pytest.approx(cold / 2)


def test_resolve_model_accepts_dated_ids() -> None:
    assert resolve_model("gpt-4o-2024-08-06", TABLE).name == "gpt-4o"
    assert resolve_model("gpt-4o-mini-2024-07-18", TABLE).name == "gpt-4o-mini"  # longest
    assert resolve_model("claude-sonnet-5-5-20261001", TABLE).name == "claude-sonnet-5-5"


# --- parse_log ----------------------------------------------------------------------


def test_log_reads_raw_responses() -> None:
    response = {"model": "claude-sonnet-5-5-20261001", "usage": anthropic(inp=10, out=5)}
    calls = parse_log(json.dumps({"task": 1, "passed": True, "response": response}), TABLE)
    assert calls[0].task == "1"
    assert calls[0].model.name == "claude-sonnet-5-5"


def test_log_reads_gemini_responses() -> None:
    response = {
        "modelVersion": "gemini-3.8-flash",
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    calls = parse_log(json.dumps({"task": "a", "response": response}), TABLE)
    assert calls[0].model.name == "gemini-3.8-flash"


def test_log_skips_blank_lines() -> None:
    text = "\n" + line("a", anthropic(inp=1)) + "\n\n" + line("b", anthropic(inp=1)) + "\n"
    assert len(parse_log(text, TABLE)) == 2


def test_model_override_prices_every_call() -> None:
    calls = parse_log(line("a", anthropic(inp=1000)), TABLE, model=GPT4O)
    assert calls[0].model is GPT4O


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "line 1 is not valid JSON"),
        ("[1]", "must be a JSON object"),
        (json.dumps({"usage": anthropic(inp=1), "model": "gpt-4o"}), '"task" ID'),
        (json.dumps({"task": "a", "model": "gpt-4o"}), "has no usage"),
        (json.dumps({"task": "a", "usage": anthropic(inp=1)}), "names no model"),
        (json.dumps({"task": "a", "model": "nope", "usage": anthropic()}), "Unknown model"),
        (
            json.dumps({"task": "a", "model": "gpt-4o", "usage": anthropic(), "passed": "yes"}),
            '"passed" must be',
        ),
        ("", "no calls"),
    ],
)
def test_log_errors_name_the_problem(text: str, message: str) -> None:
    with pytest.raises(TaskLogError, match=message):
        parse_log(text, TABLE)


# --- summarize ------------------------------------------------------------------------


def _log(*lines: str) -> str:
    return "\n".join(lines)


def test_calls_are_grouped_by_task_and_retries_count() -> None:
    text = _log(
        line("a", anthropic(out=100_000)),
        line("a", anthropic(out=100_000), passed=True),  # retry
        line("b", anthropic(out=100_000), passed=True),
    )
    summary = summarize(parse_log(text, TABLE))
    assert len(summary.tasks) == 2
    assert summary.calls == 3
    assert summary.calls_per_task == 1.5
    # 3 calls at $1 each, 2 successes
    assert summary.cost == pytest.approx(3.0)
    assert summary.cost_per_call == pytest.approx(1.0)
    assert summary.cost_per_success == pytest.approx(1.5)


def test_failures_make_each_success_more_expensive() -> None:
    text = _log(
        line("a", anthropic(out=100_000), passed=True),
        line("b", anthropic(out=100_000), passed=False),
    )
    summary = summarize(parse_log(text, TABLE))
    assert summary.success_rate == 0.5
    assert summary.cost_failed == pytest.approx(1.0)
    assert summary.cost_per_success == pytest.approx(2.0)


def test_unknown_outcomes_are_left_out_of_both_sides() -> None:
    text = _log(
        line("a", anthropic(out=100_000), passed=True),
        line("b", anthropic(out=900_000)),  # no outcome
    )
    summary = summarize(parse_log(text, TABLE))
    assert summary.unknown == 1
    assert summary.cost_per_success == pytest.approx(1.0)
    assert summary.success_rate == 1.0


def test_last_outcome_wins() -> None:
    text = _log(line("a", anthropic(inp=1), passed=False), line("a", anthropic(inp=1), passed=True))
    assert summarize(parse_log(text, TABLE)).passed == 1


def test_no_successes_has_no_cost_per_success() -> None:
    summary = summarize(parse_log(line("a", anthropic(inp=1), passed=False), TABLE))
    assert summary.cost_per_success is None
    assert summary.success_rate == 0.0


def test_cache_read_share() -> None:
    text = line("a", anthropic(inp=100, read=900))
    assert summarize(parse_log(text, TABLE)).cache_read_share == pytest.approx(0.9)


def test_tasks_are_grouped_by_type() -> None:
    text = _log(
        line("a", anthropic(out=100_000), passed=True, type="refund"),
        line("b", anthropic(out=100_000), passed=False, type="refund"),
        line("c", anthropic(out=100_000), passed=True, type="status"),
        line("d", anthropic(out=100_000), passed=True),  # untyped: only in the total
    )
    summary = summarize(parse_log(text, TABLE))
    assert list(summary.by_type) == ["refund", "status"]
    assert summary.by_type["refund"].cost_per_success == pytest.approx(2.0)
    assert summary.by_type["status"].cost_per_success == pytest.approx(1.0)
    assert len(summary.tasks) == 4
