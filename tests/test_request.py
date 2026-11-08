import json

import pytest

from tokensaver.counter import count_tokens
from tokensaver.pricing import load_prices
from tokensaver.request import ToolsError, breakdown, parse_tools, tools_text

TABLE = load_prices()
GPT4O = TABLE.get("gpt-4o")
SONNET = TABLE.get("claude-sonnet-5-5")

OPENAI_TOOL = {
    "type": "function",
    "function": {
        "name": "get_order_status",
        "description": "Look up an order by its number.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
}
ANTHROPIC_TOOL = {
    "name": "get_weather",
    "description": "Current weather for a city.",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
}


# --- parse_tools ---------------------------------------------------------------


def test_parse_tools_list() -> None:
    assert parse_tools(json.dumps([OPENAI_TOOL, ANTHROPIC_TOOL])) == [OPENAI_TOOL, ANTHROPIC_TOOL]


def test_parse_tools_single_tool_object() -> None:
    assert parse_tools(json.dumps(ANTHROPIC_TOOL)) == [ANTHROPIC_TOOL]


def test_parse_tools_request_body_with_tools_key() -> None:
    body = {"model": "gpt-4o", "messages": [], "tools": [OPENAI_TOOL]}
    assert parse_tools(json.dumps(body)) == [OPENAI_TOOL]


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '"a string"', '{"tools": "x"}'])
def test_parse_tools_rejects_bad_input(text: str) -> None:
    with pytest.raises(ToolsError):
        parse_tools(text)


def test_tools_are_counted_compact() -> None:
    pretty = json.dumps([OPENAI_TOOL], indent=4)
    compact = tools_text(parse_tools(pretty))
    assert "\n" not in compact and ": " not in compact
    assert count_tokens(compact, GPT4O).tokens < count_tokens(pretty, GPT4O).tokens


def test_tools_text_keeps_non_ascii() -> None:
    assert "订单" in tools_text([{"description": "查询订单"}])


# --- breakdown ----------------------------------------------------------------


def test_fixed_part_is_system_plus_tools() -> None:
    system = "You are a helpful support agent. Answer briefly."
    result = breakdown(
        GPT4O, system=(system, "system.md"), tools=(json.dumps([OPENAI_TOOL]), "tools.json")
    )
    assert result.system is not None and result.tools is not None
    assert result.system.tokens == count_tokens(system, GPT4O).tokens
    assert result.system.exact
    assert result.tools.tool_count == 1
    assert result.fixed_tokens == result.system.tokens + result.tools.tokens
    assert result.users == []


def test_tool_schemas_are_always_labelled_estimated() -> None:
    result = breakdown(GPT4O, tools=(json.dumps([OPENAI_TOOL]), "tools.json"))
    assert result.tools is not None and not result.tools.exact
    assert not result.fixed_exact


def test_system_only_is_exact_on_exact_model() -> None:
    assert breakdown(GPT4O, system=("Be brief.", "text")).fixed_exact


def test_estimated_model_is_never_exact() -> None:
    result = breakdown(SONNET, system=("Be brief.", "text"), users=[("Hi", "text")])
    assert not result.fixed_exact and not result.users[0].exact


def test_empty_tool_list_counts_zero() -> None:
    result = breakdown(GPT4O, tools=("[]", "tools.json"))
    assert result.tools is not None
    assert result.tools.tokens == 0 and result.tools.tool_count == 0


def test_fixed_part_is_the_same_whatever_the_user_language() -> None:
    """The point of issue #10: only the user part changes with the language."""
    users = [
        ("Where is my order?", "text"),
        ("我的订单在哪里？", "text"),
        ("ਮੇਰਾ ਆਰਡਰ ਕਿੱਥੇ ਹੈ?", "text"),
    ]
    result = breakdown(GPT4O, system=("You are a support agent. " * 20, "system.md"), users=users)
    for user in result.users:
        assert result.request_tokens(user) == result.fixed_tokens + user.tokens
    shares = [result.fixed_percent(user) for user in result.users]
    assert all(0 < share < 100 for share in shares)
    assert len({user.tokens for user in result.users}) > 1


def test_fixed_percent() -> None:
    result = breakdown(GPT4O, system=("a " * 99, "s"), users=[("b " * 99, "u")])
    user = result.users[0]
    assert result.fixed_percent(user) == pytest.approx(
        100 * result.fixed_tokens / (result.fixed_tokens + user.tokens)
    )


def test_inline_text_is_labelled_by_its_start() -> None:
    result = breakdown(GPT4O, system=("x", "s"), users=[("\n  Where is my order?\nmore", "text")])
    assert result.users[0].label == "Where is my order?"


def test_long_preview_is_cut() -> None:
    result = breakdown(GPT4O, system=("x", "s"), users=[("word " * 50, "text")])
    label = result.users[0].label
    assert len(label) <= 60 and label.endswith("…")


def test_file_is_labelled_by_name() -> None:
    result = breakdown(GPT4O, system=("x", "s"), users=[("Hello", "question.txt")])
    assert result.users[0].label == "question.txt"


# --- prompt caching ------------------------------------------------------------


def _fixed(model, tokens_text: str = "word " * 2000):
    return breakdown(model, system=(tokens_text, "system.md"), users=[("hi", "text")])


def test_no_estimate_without_cache_prices() -> None:
    from dataclasses import replace

    from tokensaver.request import cache_estimate

    model = replace(GPT4O, cached_input_per_1m=None)
    assert cache_estimate(_fixed(model)) is None


def test_cache_estimate_costs() -> None:
    from tokensaver.pricing import cache_write_cost, cached_input_cost, input_cost
    from tokensaver.request import cache_estimate

    result = _fixed(SONNET)
    cache = cache_estimate(result)
    tokens = result.fixed_tokens
    assert cache.uncached == pytest.approx(input_cost(tokens, SONNET))
    assert cache.first_call == pytest.approx(cache_write_cost(tokens, SONNET))
    assert cache.cached_call == pytest.approx(cached_input_cost(tokens, SONNET))
    assert cache.first_call > cache.uncached > cache.cached_call
    assert cache.saving_percent == pytest.approx(95)
    assert cache.average is None


def test_cache_average_at_hit_rate() -> None:
    from tokensaver.request import cache_estimate

    cache = cache_estimate(_fixed(SONNET), hit_rate=0.9)
    expected = 0.9 * cache.cached_call + 0.1 * cache.first_call
    assert cache.average == pytest.approx(expected)
    assert cache_estimate(_fixed(SONNET), hit_rate=0.0).average == pytest.approx(cache.first_call)


def test_below_minimum_is_never_cached() -> None:
    from tokensaver.request import cache_estimate

    gpt6 = TABLE.get("gpt-6.1-sol")
    cache = cache_estimate(_fixed(gpt6, "Be brief."), hit_rate=1.0)
    assert cache.below_minimum
    assert cache.average == pytest.approx(cache.uncached)
    assert cache.saving_percent == 0


def test_unknown_minimum_is_not_below() -> None:
    from tokensaver.request import cache_estimate

    cache = cache_estimate(_fixed(GPT4O, "Be brief."))
    assert cache.min_tokens is None
    assert not cache.below_minimum


# --- cache saving (optimize) ---------------------------------------------------


def test_cache_saving_differences() -> None:
    from tokensaver.request import cache_saving, estimate_cache

    saving = cache_saving(2000, 1500, SONNET, hit_rate=0.9)
    before = estimate_cache(2000, SONNET, 0.9)
    after = estimate_cache(1500, SONNET, 0.9)
    assert saving.uncached == pytest.approx(before.uncached - after.uncached)
    assert saving.cached_call == pytest.approx(before.cached_call - after.cached_call)
    assert saving.average == pytest.approx(before.average - after.average)
    assert saving.first_call > saving.uncached > saving.cached_call > 0
    assert not saving.loses_caching


def test_cache_saving_can_lose_caching() -> None:
    from tokensaver.request import cache_saving

    gpt6 = TABLE.get("gpt-6.1-sol")  # minimum 1,024 tokens, cache reads at 5%
    saving = cache_saving(1100, 900, gpt6, hit_rate=0.9)
    assert saving.loses_caching
    assert saving.average < 0  # cached calls now pay full price


def test_cache_saving_needs_a_price() -> None:
    from dataclasses import replace

    from tokensaver.request import cache_saving

    assert cache_saving(2000, 1500, replace(SONNET, cached_input_per_1m=None)) is None
