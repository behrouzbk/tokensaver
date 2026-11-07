"""Check that requests share the same prefix, so prompt caching can reuse it.

Providers cache the start of a request (tools, then system prompt, then messages) and
reuse it only when the next request starts with exactly the same content. One field that
changes on every call, such as a timestamp near the top of the system prompt, means the
prefix never matches and every call pays the full input price.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from tokensaver.counter import count_tokens
from tokensaver.pricing import ModelInfo
from tokensaver.request import parse_tools, tools_text

# Keys that mark a JSON object as a request body rather than plain prompt text.
BODY_KEYS = ("tools", "system", "instructions", "messages", "input")
FIXED_ROLES = ("system", "developer")
SNIPPET_BEFORE = 20
SNIPPET_AFTER = 40

# Values that typically change on every call. Checked in order; the first match wins.
DYNAMIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "UUID or session ID",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
    (
        "date/time",
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
        ),
    ),
    ("time", re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")),
    ("hex ID", re.compile(r"\b[0-9a-fA-F]{16,}\b")),
    ("timestamp or long number", re.compile(r"\b\d{9,}\b")),
]


class RequestInputError(ValueError):
    """An input could not be read as a request."""


@dataclass(frozen=True)
class Segment:
    label: str  # "tools", "system", "messages[2] (user)", ...
    text: str
    fixed: bool  # sent the same way on every call (tools, system prompt)
    header: int = 0  # length of a leading "role" line; positions are reported after it


@dataclass(frozen=True)
class RenderedRequest:
    source: str
    segments: list[Segment]

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)

    def locate(self, offset: int, next_part: bool = False) -> tuple[Segment | None, int]:
        """The segment holding a character offset of `text`, and the offset inside it.

        An offset on the separator after a segment belongs to that segment (its end),
        or to the segment after it when `next_part` is set.
        """
        start = 0
        for i, segment in enumerate(self.segments):
            end = start + len(segment.text)
            if offset < end or (offset == end and not next_part):
                return segment, offset - start
            if offset == end:
                following = self.segments[i + 1] if i + 1 < len(self.segments) else None
                return following, 0
            start = end + 1  # the "\n" between segments
        return None, 0

    def at_boundary(self, offset: int) -> bool:
        """The offset is where a segment ends (or the whole request ends)."""
        end = -1
        for segment in self.segments:
            end += 1 + len(segment.text)
            if offset == end:
                return True
        return offset >= len(self.text)


@dataclass(frozen=True)
class Difference:
    source: str
    part: str | None  # None: the request ends where the others go on
    fixed: bool
    line: int  # 1-based inside the part's text; 0 when the message roles differ
    column: int
    snippet: str
    dynamic: str | None  # what the differing value looks like, if recognised


@dataclass(frozen=True)
class RequestPrefix:
    source: str
    tokens: int
    shared_tokens: int

    @property
    def rest_tokens(self) -> int:
        return max(self.tokens - self.shared_tokens, 0)


@dataclass(frozen=True)
class PrefixCheck:
    model: ModelInfo
    requests: list[RequestPrefix]
    shared_chars: int
    identical: bool
    differences: list[Difference]  # one per request, empty when identical
    has_tools: bool

    @property
    def shared_tokens(self) -> int:
        return self.requests[0].shared_tokens if self.requests else 0

    @property
    def fixed_differs(self) -> bool:
        """The requests part ways in the tools or system prompt, not in the user turn."""
        return any(d.fixed for d in self.differences)

    @property
    def exact(self) -> bool:
        return self.model.exact and not self.has_tools


def _compact(value: object) -> str:
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    )


def _role(message: object) -> str:
    return str(message.get("role", "")) if isinstance(message, dict) else ""


def _message(label: str, message: object) -> Segment:
    """A chat message as its role line plus its content, so positions point into the text.

    Anything besides the role and string content (content parts, tool calls, names) is
    compared as compact JSON after the content.
    """
    if not isinstance(message, dict):
        return Segment(label, _compact(message), False)
    role = _role(message)
    rest = {k: v for k, v in message.items() if k != "role"}
    content = rest.pop("content") if isinstance(rest.get("content"), str) else ""
    text = content + ("\n" + _compact(rest) if rest else "")
    header = f"{role}\n"
    return Segment(label, header + text, role in FIXED_ROLES, header=len(header))


def render_body(body: dict) -> list[Segment]:
    """Segments in the order providers cache them: tools, system prompt, then messages."""
    segments: list[Segment] = []
    if body.get("tools"):
        segments.append(Segment("tools", tools_text(parse_tools(json.dumps(body["tools"]))), True))
    for key in ("instructions", "system"):  # OpenAI Responses / Anthropic Messages
        if body.get(key):
            segments.append(Segment(key, _compact(body[key]), True))
    for key in ("messages", "input"):
        value = body.get(key)
        if isinstance(value, str) and value:
            segments.append(Segment(key, value, False))
        elif isinstance(value, list):
            for i, message in enumerate(value):
                role = _role(message)
                label = f"{key}[{i}] ({role})" if role else f"{key}[{i}]"
                segments.append(_message(label, message))
    return segments


def render_input(text: str, source: str, tools: str | None = None) -> RenderedRequest:
    """A request body (JSON with tools/system/messages) or a plain-text system prompt.

    `tools` (JSON text) is added in front of plain-text prompts only; request bodies
    carry their own tools.
    """
    body = None
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and any(key in data for key in BODY_KEYS):
            body = data
    if body is not None:
        try:
            segments = render_body(body)
        except ValueError as error:
            raise RequestInputError(f"{source}: {error}") from None
    else:
        segments = []
        if tools is not None:
            segments.append(Segment("tools", tools_text(parse_tools(tools)), True))
        segments.append(Segment("system", text, True))
    if not segments:
        raise RequestInputError(f"{source}: no tools, system prompt or messages found.")
    return RenderedRequest(source=source, segments=segments)


def _dynamic_kind(text: str, offset: int) -> str | None:
    """What the value at `offset` looks like, if it is a typical per-call value."""
    for kind, pattern in DYNAMIC_PATTERNS:
        for match in pattern.finditer(text):
            if match.start() <= offset < match.end() or (
                offset == match.end() and match.end() > match.start()
            ):
                return kind
            if match.start() > offset:
                break
    return None


def _snippet(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    line_end = len(text) if line_end == -1 else line_end
    start = max(line_start, offset - SNIPPET_BEFORE)
    if start > line_start and not text[start - 1].isspace():
        space = text.find(" ", start, offset)  # start at a word, not inside one
        start = space + 1 if space != -1 else start
    end = min(line_end, offset + SNIPPET_AFTER)
    snippet = text[start:end]
    return ("…" if start > line_start else "") + snippet + ("…" if end < line_end else "")


def _difference(request: RenderedRequest, offset: int, next_part: bool) -> Difference:
    segment, inner = request.locate(offset, next_part)
    if segment is None or offset >= len(request.text):
        return Difference(request.source, None, False, 0, 0, "", None)
    if inner < segment.header:  # the message roles differ
        role = segment.text[: segment.header - 1]
        return Difference(request.source, segment.label, segment.fixed, 0, 0, role, None)
    text, inner = segment.text[segment.header :], inner - segment.header
    before = text[:inner]
    line = before.count("\n") + 1
    column = inner - (before.rfind("\n") + 1) + 1
    return Difference(
        source=request.source,
        part=segment.label,
        fixed=segment.fixed,
        line=line,
        column=column,
        snippet=_snippet(text, inner),
        dynamic=_dynamic_kind(text, inner),
    )


def check(requests: list[RenderedRequest], model: ModelInfo) -> PrefixCheck:
    """Find the longest prefix all requests share and where each one leaves it."""
    if len(requests) < 2:
        raise ValueError("Need at least two requests to compare.")
    texts = [r.text for r in requests]
    shared = os.path.commonprefix(texts)
    identical = all(t == texts[0] for t in texts)
    shared_tokens = count_tokens(shared, model).tokens if shared else 0
    # When every request finishes a part right here, the difference is in what comes
    # next (a new message, or the end of a request), not in the part that just ended.
    next_part = all(r.at_boundary(len(shared)) for r in requests)
    return PrefixCheck(
        model=model,
        requests=[
            RequestPrefix(r.source, count_tokens(t, model).tokens, shared_tokens)
            for r, t in zip(requests, texts, strict=True)
        ],
        shared_chars=len(shared),
        identical=identical,
        differences=[] if identical else [_difference(r, len(shared), next_part) for r in requests],
        has_tools=any(s.label == "tools" for r in requests for s in r.segments),
    )
