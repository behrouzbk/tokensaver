import json

import pytest

from tokensaver.prefix import (
    RequestInputError,
    _dynamic_kind,
    check,
    render_body,
    render_input,
)
from tokensaver.pricing import load_prices

TABLE = load_prices()
GPT4O = TABLE.get("gpt-4o")

TOOL = {
    "type": "function",
    "function": {
        "name": "get_order_status",
        "description": "Look up an order by its number.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
    },
}
SYSTEM = "You are a support assistant for an online shop.\nAlways ask for the order number."


def body(system: str, user: str, tools: list | None = None) -> str:
    data = {
        "model": "gpt-4o",
        "tools": tools if tools is not None else [TOOL],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    return json.dumps(data, indent=2)


def run(*texts: str):
    return check([render_input(t, f"r{i}.json") for i, t in enumerate(texts)], GPT4O)


# --- rendering -----------------------------------------------------------------


def test_render_body_order_is_tools_system_messages() -> None:
    data = {
        "messages": [{"role": "user", "content": "hi"}],
        "system": "Be brief.",
        "tools": [TOOL],
    }
    labels = [s.label for s in render_body(data)]
    assert labels == ["tools", "system", "messages[0] (user)"]


def test_render_body_responses_api_shape() -> None:
    segments = render_body({"instructions": "Be brief.", "input": "Where is my order?"})
    assert [(s.label, s.fixed) for s in segments] == [("instructions", True), ("input", False)]


def test_system_and_developer_messages_are_fixed() -> None:
    data = {
        "messages": [
            {"role": "developer", "content": "Rules"},
            {"role": "user", "content": "hi"},
        ]
    }
    assert [s.fixed for s in render_body(data)] == [True, False]


def test_json_formatting_does_not_matter() -> None:
    pretty = body(SYSTEM, "hi")
    compact = json.dumps(json.loads(pretty), separators=(",", ":"))
    assert run(pretty, compact).identical


def test_plain_text_is_a_system_prompt_with_optional_tools() -> None:
    request = render_input(SYSTEM, "system.md", tools=json.dumps([TOOL]))
    assert [s.label for s in request.segments] == ["tools", "system"]


def test_json_without_request_keys_is_plain_text() -> None:
    request = render_input('{"name": "string"}', "schema.json")
    assert [s.label for s in request.segments] == ["system"]


def test_body_with_nothing_to_compare_is_an_error() -> None:
    with pytest.raises(RequestInputError):
        render_input('{"tools": [], "messages": []}', "empty.json")


def test_body_with_bad_tools_is_an_error() -> None:
    with pytest.raises(RequestInputError):
        render_input('{"tools": "x"}', "bad.json")


# --- check ---------------------------------------------------------------------


def test_needs_two_requests() -> None:
    with pytest.raises(ValueError):
        check([render_input(SYSTEM, "a")], GPT4O)


def test_identical_requests() -> None:
    result = run(body(SYSTEM, "hi"), body(SYSTEM, "hi"))
    assert result.identical and not result.fixed_differs
    assert result.differences == []
    assert result.requests[0].shared_tokens == result.requests[0].tokens


def test_only_user_message_differs() -> None:
    result = run(body(SYSTEM, "Where is my order?"), body(SYSTEM, "I want a refund"))
    assert not result.identical and not result.fixed_differs
    assert {d.part for d in result.differences} == {"messages[1] (user)"}
    assert all(d.line == 1 and d.column == 1 for d in result.differences)
    assert 0 < result.shared_tokens < min(r.tokens for r in result.requests)


def test_timestamp_in_system_prompt_is_found() -> None:
    a = body("Current time: 2026-11-07T10:15:00Z\n" + SYSTEM, "hi")
    b = body("Current time: 2026-11-07T10:16:42Z\n" + SYSTEM, "hi")
    result = run(a, b)
    assert result.fixed_differs
    first = result.differences[0]
    assert first.part == "messages[0] (system)"
    assert (first.line, first.column) == (1, 30)
    assert first.dynamic == "date/time"
    assert "10:15:00Z" in first.snippet


def test_changed_tools_break_the_prefix_before_the_system_prompt() -> None:
    other = {**TOOL, "function": {**TOOL["function"], "description": "Find an order."}}
    result = run(body(SYSTEM, "hi"), body(SYSTEM, "hi", tools=[other]))
    assert result.fixed_differs
    assert {d.part for d in result.differences} == {"tools"}


def test_different_roles_are_reported() -> None:
    a = json.dumps({"messages": [{"role": "system", "content": "x"}]})
    b = json.dumps({"messages": [{"role": "developer", "content": "x"}]})
    result = run(a, b)
    assert [(d.line, d.snippet) for d in result.differences] == [(0, "system"), (0, "developer")]


def test_request_that_ends_inside_the_prefix() -> None:
    short = json.dumps({"messages": [{"role": "system", "content": SYSTEM}]})
    long = body(SYSTEM, "hi", tools=[])
    result = run(short, long)
    ends, goes_on = result.differences
    assert ends.part is None
    assert goes_on.part == "messages[1] (user)"


def test_three_variants_share_only_the_common_start() -> None:
    result = run(
        "Answer in English. " + SYSTEM, "Answer in German. " + SYSTEM, "Answer in Italian."
    )
    assert result.shared_chars == len("Answer in ")
    assert len(result.differences) == 3


def test_tools_make_counts_estimates() -> None:
    assert not run(body(SYSTEM, "a"), body(SYSTEM, "b")).exact
    assert run(SYSTEM, SYSTEM + " More.").exact


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("id 3f2b8c1e-9d4a-4f6b-8e2a-1c3d5e7f9a0b end", "UUID or session ID"),
        ("today is 2026-11-07 ok", "date/time"),
        ("at 10:15:00 sharp", "time"),
        ("session a1b2c3d4e5f6a7b8c9d0 end", "hex ID"),
        ("ts 1762510500 end", "timestamp or long number"),
        ("plain words here", None),
    ],
)
def test_dynamic_kind(text: str, kind: str | None) -> None:
    offset = next((i for i, ch in enumerate(text) if ch.isdigit()), 3)
    assert _dynamic_kind(text, offset + 1) == kind


def test_shorter_system_prompt_is_reported_in_the_system_prompt() -> None:
    result = run(body(SYSTEM, "hi"), body(SYSTEM + " Be brief.", "hi"))
    assert [d.part for d in result.differences] == ["messages[0] (system)"] * 2
    assert result.fixed_differs
