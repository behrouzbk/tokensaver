"""Cost per successful task, from logged API responses.

Cost per request can drop while cost per task goes up: a shorter prompt that leaves out
an instruction the model needed leads to retries and follow-up turns. This module reads a
log of real calls, groups them by task, prices each call from the usage counts the
provider returned (not from estimated token counts), and divides the total spend by the
number of tasks that passed.

Log format: JSON Lines, one call per line::

    {"task": "order-123", "passed": true, "response": {...the raw API response...}}

Instead of "response", a line can hold "usage" (and "model") directly. A task's outcome
is the last "passed" value given on any of its lines; tasks without one are "unknown"
and never counted as successes. An optional "type" groups tasks in the report.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from tokensaver.pricing import TOKENS_PER_PRICE_UNIT, ModelInfo, PriceTable, UnknownModelError

# Anthropic bills 1-hour cache writes at 2x the input price (5-minute writes: 1.25x).
ONE_HOUR_WRITE_MULTIPLIER = 2.0


class TaskLogError(ValueError):
    """A log line is not a call this module can price."""


@dataclass(frozen=True)
class Usage:
    """Billed token counts for one call, split by price."""

    input: int = 0  # uncached input, normal price
    cache_read: int = 0
    cache_write: int = 0  # default (shortest) cache duration
    cache_write_1h: int = 0  # Anthropic 1-hour cache writes
    output: int = 0  # includes reasoning/thinking tokens

    @property
    def input_total(self) -> int:
        return self.input + self.cache_read + self.cache_write + self.cache_write_1h

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input + other.input,
            self.cache_read + other.cache_read,
            self.cache_write + other.cache_write,
            self.cache_write_1h + other.cache_write_1h,
            self.output + other.output,
        )


def _int(usage: dict, key: str) -> int:
    value = usage.get(key) or 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TaskLogError(f"usage field '{key}' must be a whole, non-negative number.")
    return value


def parse_usage(usage: dict) -> Usage:
    """Usage from an Anthropic, OpenAI (Chat Completions or Responses) or Gemini response.

    OpenAI and Gemini report cached tokens as part of the input total; Anthropic reports
    them separately from input_tokens.
    """
    if not isinstance(usage, dict):
        raise TaskLogError("'usage' must be an object.")
    if "promptTokenCount" in usage or "candidatesTokenCount" in usage:  # Gemini
        cached = _int(usage, "cachedContentTokenCount")
        prompt = _int(usage, "promptTokenCount")
        output = _int(usage, "candidatesTokenCount") + _int(usage, "thoughtsTokenCount")
        return Usage(input=max(prompt - cached, 0), cache_read=cached, output=output)
    if "prompt_tokens" in usage:  # OpenAI Chat Completions
        cached = _int(usage.get("prompt_tokens_details") or {}, "cached_tokens")
        prompt = _int(usage, "prompt_tokens")
        return Usage(
            input=max(prompt - cached, 0),
            cache_read=cached,
            output=_int(usage, "completion_tokens"),
        )
    if "input_tokens_details" in usage:  # OpenAI Responses
        cached = _int(usage["input_tokens_details"] or {}, "cached_tokens")
        prompt = _int(usage, "input_tokens")
        return Usage(
            input=max(prompt - cached, 0), cache_read=cached, output=_int(usage, "output_tokens")
        )
    if "input_tokens" in usage or "output_tokens" in usage:  # Anthropic
        write_total = _int(usage, "cache_creation_input_tokens")
        write_1h = _int(usage.get("cache_creation") or {}, "ephemeral_1h_input_tokens")
        write_1h = min(write_1h, write_total)  # the breakdown is part of the total
        return Usage(
            input=_int(usage, "input_tokens"),
            cache_read=_int(usage, "cache_read_input_tokens"),
            cache_write=write_total - write_1h,
            cache_write_1h=write_1h,
            output=_int(usage, "output_tokens"),
        )
    raise TaskLogError(
        "'usage' has no token counts this tool knows (Anthropic, OpenAI or Gemini format)."
    )


def call_cost(usage: Usage, model: ModelInfo) -> float:
    """Dollar cost of one call at the price table's standard-tier prices."""
    read_price = (
        model.input_per_1m if model.cached_input_per_1m is None else model.cached_input_per_1m
    )
    dollars_per_1m = (
        usage.input * model.input_per_1m
        + usage.cache_read * read_price
        + usage.cache_write * model.write_per_1m
        + usage.cache_write_1h * model.input_per_1m * ONE_HOUR_WRITE_MULTIPLIER
        + usage.output * model.output_per_1m
    )
    return dollars_per_1m / TOKENS_PER_PRICE_UNIT


def resolve_model(name: str, table: PriceTable) -> ModelInfo:
    """A model from the table by its exact name, or by the API's dated ID.

    APIs return IDs such as "gpt-4o-2024-08-06" or "claude-sonnet-5-5-20261001"; the
    longest table name that the ID starts with (followed by "-") is used.
    """
    if name in table.models:
        return table.models[name]
    matches = [known for known in table.models if name.startswith(known + "-")]
    if matches:
        return table.models[max(matches, key=len)]
    return table.get(name)  # raises UnknownModelError with suggestions


@dataclass(frozen=True)
class Call:
    task: str
    model: ModelInfo
    usage: Usage
    cost: float
    passed: bool | None = None
    type: str | None = None


def _model_name(entry: dict, response: dict) -> str | None:
    name = entry.get("model") or response.get("model") or response.get("modelVersion")
    return name if isinstance(name, str) and name else None


def parse_line(
    line: str, number: int, table: PriceTable, model: ModelInfo | None = None
) -> Call | None:
    """One log line as a priced call; None for a blank line.

    `model` overrides the model named in the line.
    """
    if not line.strip():
        return None
    where = f"line {number}"
    try:
        entry = json.loads(line)
    except json.JSONDecodeError as error:
        raise TaskLogError(f"{where} is not valid JSON: {error}") from None
    if not isinstance(entry, dict):
        raise TaskLogError(f"{where} must be a JSON object.")

    task = entry.get("task")
    if not isinstance(task, (str, int)) or isinstance(task, bool) or task == "":
        raise TaskLogError(f'{where} needs a "task" ID, so its calls can be grouped.')
    passed = entry.get("passed")
    if passed is not None and not isinstance(passed, bool):
        raise TaskLogError(f'{where}: "passed" must be true, false or null.')
    kind = entry.get("type")
    if kind is not None and not isinstance(kind, str):
        raise TaskLogError(f'{where}: "type" must be a string.')

    response = entry.get("response") or {}
    if not isinstance(response, dict):
        raise TaskLogError(f'{where}: "response" must be an object.')
    raw_usage = entry.get("usage") or response.get("usage") or response.get("usageMetadata")
    if raw_usage is None:
        raise TaskLogError(f'{where} has no usage (in "usage" or "response").')
    try:
        usage = parse_usage(raw_usage)
    except TaskLogError as error:
        raise TaskLogError(f"{where}: {error}") from None

    if model is None:
        name = _model_name(entry, response)
        if name is None:
            raise TaskLogError(f'{where} names no model. Add "model" or pass --model.')
        try:
            model = resolve_model(name, table)
        except UnknownModelError as error:
            raise TaskLogError(f"{where}: {error} Pass --model to price it as another.") from None
    return Call(
        task=str(task),
        model=model,
        usage=usage,
        cost=call_cost(usage, model),
        passed=passed,
        type=kind,
    )


def parse_log(text: str, table: PriceTable, model: ModelInfo | None = None) -> list[Call]:
    calls = [parse_line(line, n, table, model) for n, line in enumerate(text.splitlines(), 1)]
    out = [call for call in calls if call is not None]
    if not out:
        raise TaskLogError("The log has no calls.")
    return out


@dataclass(frozen=True)
class Task:
    id: str
    calls: list[Call]

    @property
    def passed(self) -> bool | None:
        """The last outcome given on any of its calls; None if none was given."""
        outcomes = [c.passed for c in self.calls if c.passed is not None]
        return outcomes[-1] if outcomes else None

    @property
    def type(self) -> str | None:
        types = [c.type for c in self.calls if c.type is not None]
        return types[-1] if types else None

    @property
    def cost(self) -> float:
        return sum(c.cost for c in self.calls)


def group_tasks(calls: Iterable[Call]) -> list[Task]:
    """Calls grouped by task ID, in the order each task first appears."""
    grouped: dict[str, list[Call]] = {}
    for call in calls:
        grouped.setdefault(call.task, []).append(call)
    return [Task(task_id, task_calls) for task_id, task_calls in grouped.items()]


@dataclass(frozen=True)
class TaskSummary:
    tasks: list[Task]
    label: str = ""
    by_type: dict[str, TaskSummary] = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tasks if t.passed is True)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tasks if t.passed is False)

    @property
    def unknown(self) -> int:
        return sum(1 for t in self.tasks if t.passed is None)

    @property
    def calls(self) -> int:
        return sum(len(t.calls) for t in self.tasks)

    @property
    def calls_per_task(self) -> float:
        return self.calls / len(self.tasks) if self.tasks else 0.0

    @property
    def cost(self) -> float:
        return sum(t.cost for t in self.tasks)

    @property
    def cost_failed(self) -> float:
        """Spend on tasks that failed: what the failures cost."""
        return sum(t.cost for t in self.tasks if t.passed is False)

    @property
    def cost_per_call(self) -> float:
        return self.cost / self.calls if self.calls else 0.0

    @property
    def cost_per_task(self) -> float:
        return self.cost / len(self.tasks) if self.tasks else 0.0

    @property
    def cost_per_success(self) -> float | None:
        """All spend, failures and retries included, divided by the tasks that passed.

        Tasks without an outcome are left out of both sides, so they neither count as
        successes nor make the successes look more expensive. None if nothing passed.
        """
        judged = [t for t in self.tasks if t.passed is not None]
        if not self.passed:
            return None
        return sum(t.cost for t in judged) / self.passed

    @property
    def success_rate(self) -> float | None:
        judged = self.passed + self.failed
        return self.passed / judged if judged else None

    @property
    def usage(self) -> Usage:
        total = Usage()
        for task in self.tasks:
            for call in task.calls:
                total = total + call.usage
        return total

    @property
    def cache_read_share(self) -> float:
        """Share of input tokens that were read from the cache."""
        usage = self.usage
        return usage.cache_read / usage.input_total if usage.input_total else 0.0

    @property
    def models(self) -> list[str]:
        return sorted({c.model.name for t in self.tasks for c in t.calls})


def summarize(calls: list[Call], label: str = "") -> TaskSummary:
    tasks = group_tasks(calls)
    types: dict[str, list[Task]] = {}
    for task in tasks:
        if task.type is not None:
            types.setdefault(task.type, []).append(task)
    by_type = {name: TaskSummary(group, label=name) for name, group in sorted(types.items())}
    return TaskSummary(tasks, label=label, by_type=by_type)
