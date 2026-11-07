"""Split a request into its fixed part (system prompt + tool schemas) and the user message.

The fixed part is sent with every call, whatever the user types, so it is often the
biggest share of the bill and the first thing worth measuring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from tokensaver.counter import count_tokens
from tokensaver.pricing import ModelInfo, cache_write_cost, cached_input_cost, input_cost


class ToolsError(ValueError):
    """The tools input is not a JSON list of tool definitions."""


PREVIEW_CHARS = 60


@dataclass(frozen=True)
class Part:
    source: str  # file name, "stdin" or "text"
    tokens: int
    exact: bool
    preview: str = ""  # start of the first non-empty line, to tell messages apart

    @property
    def label(self) -> str:
        """What to show for this part: the file name, or the text itself when typed inline."""
        return self.preview if self.source == "text" and self.preview else self.source


@dataclass(frozen=True)
class ToolsPart(Part):
    tool_count: int = 0


@dataclass(frozen=True)
class RequestBreakdown:
    model: ModelInfo
    system: Part | None
    tools: ToolsPart | None
    users: list[Part]  # one request per user message, in the order given

    @property
    def fixed_parts(self) -> list[Part]:
        return [p for p in (self.system, self.tools) if p is not None]

    @property
    def fixed_tokens(self) -> int:
        return sum(p.tokens for p in self.fixed_parts)

    @property
    def fixed_exact(self) -> bool:
        return all(p.exact for p in self.fixed_parts)

    def request_tokens(self, user: Part) -> int:
        return self.fixed_tokens + user.tokens

    def fixed_percent(self, user: Part) -> float:
        total = self.request_tokens(user)
        return 100 * self.fixed_tokens / total if total else 0.0


def parse_tools(text: str) -> list[dict]:
    """Tool definitions from JSON: a list of tools, one tool, or a request body with "tools".

    Works for OpenAI ({"type": "function", "function": {...}}) and Anthropic
    ({"name", "description", "input_schema"}) shapes alike; the JSON is counted as is.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ToolsError(f"Tools are not valid JSON: {error}") from None
    if isinstance(data, dict):
        data = data.get("tools", [data])
    if not isinstance(data, list) or not all(isinstance(tool, dict) for tool in data):
        raise ToolsError("Tools must be a JSON list of tool objects, or an object with 'tools'.")
    return data


def tools_text(tools: list[dict]) -> str:
    """Tools as compact JSON, closer to what is sent than a pretty-printed file."""
    return json.dumps(tools, separators=(",", ":"), ensure_ascii=False)


def _preview(text: str) -> str:
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line if len(line) <= PREVIEW_CHARS else line[: PREVIEW_CHARS - 1] + "…"


def measure_part(text: str, source: str, model: ModelInfo) -> Part:
    count = count_tokens(text, model)
    return Part(source=source, tokens=count.tokens, exact=count.exact, preview=_preview(text))


def measure_tools(text: str, source: str, model: ModelInfo) -> ToolsPart:
    """Always an estimate: providers rewrite tool definitions into their own hidden format."""
    tools = parse_tools(text)
    count = count_tokens(tools_text(tools), model) if tools else None
    tokens = count.tokens if count else 0
    return ToolsPart(source=source, tokens=tokens, exact=False, tool_count=len(tools))


def breakdown(
    model: ModelInfo,
    system: tuple[str, str] | None = None,
    tools: tuple[str, str] | None = None,
    users: list[tuple[str, str]] | None = None,
) -> RequestBreakdown:
    """Measure each part. Every input is a (text, source) pair."""
    return RequestBreakdown(
        model=model,
        system=measure_part(*system, model) if system else None,
        tools=measure_tools(*tools, model) if tools else None,
        users=[measure_part(text, source, model) for text, source in users or []],
    )


@dataclass(frozen=True)
class CacheEstimate:
    """What the fixed part costs per call with prompt caching, for one model.

    Only the fixed part is cached: it comes first in every request and is the same each
    time. The user message is always billed at the normal input price.
    """

    tokens: int
    uncached: float  # no caching: the normal input price
    first_call: float  # the call that writes the fixed part to the cache
    cached_call: float  # a later call that reads it from the cache
    min_tokens: int | None  # the model's minimum cacheable length, if published
    hit_rate: float | None = None  # share of calls that read from the cache, if given

    @property
    def below_minimum(self) -> bool:
        """Too short to be cached at all, so every call pays the normal price."""
        return self.min_tokens is not None and self.tokens < self.min_tokens

    @property
    def average(self) -> float | None:
        """Average cost per call at `hit_rate`; None without a hit rate."""
        if self.hit_rate is None:
            return None
        if self.below_minimum:
            return self.uncached
        return self.hit_rate * self.cached_call + (1 - self.hit_rate) * self.first_call

    @property
    def saving_percent(self) -> float:
        """How much cheaper a cached call's fixed part is than an uncached one."""
        if self.below_minimum or not self.uncached:
            return 0.0
        return 100 * (1 - self.cached_call / self.uncached)


def cache_estimate(result: RequestBreakdown, hit_rate: float | None = None) -> CacheEstimate | None:
    """Fixed-part cost with prompt caching; None when the model has no caching price."""
    model = result.model
    if not model.caches:
        return None
    tokens = result.fixed_tokens
    return CacheEstimate(
        tokens=tokens,
        uncached=input_cost(tokens, model),
        first_call=cache_write_cost(tokens, model),
        cached_call=cached_input_cost(tokens, model),
        min_tokens=model.min_cacheable_tokens,
        hit_rate=hit_rate,
    )
