"""Machine-readable output for --json: plain dicts, printed as JSON.

Non-ASCII text is escaped (\\uXXXX), so the output stays valid on any console encoding.
"""

from __future__ import annotations

import json
from pathlib import Path

from tokensaver.counter import TokenCount
from tokensaver.optimizer import Finding, OptimizationResult
from tokensaver.prefix import PrefixCheck
from tokensaver.pricing import ModelInfo, PriceTable, input_cost
from tokensaver.request import CacheEstimate, CacheSaving, Part, RequestBreakdown
from tokensaver.scan import ScanResult
from tokensaver.tasks import TaskSummary


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2)


def _dollars(amount: float) -> float:
    return round(amount, 10)  # drop float noise such as 0.00015500000000000002


def _header(model: ModelInfo, table: PriceTable) -> dict:
    return {
        "model": model.name,
        "exact": model.exact,
        "prices_last_updated": table.last_updated.isoformat(),
    }


def count_report(count: TokenCount, model: ModelInfo, table: PriceTable, source: str) -> dict:
    return {
        "source": source,
        **_header(model, table),
        "tokens": count.tokens,
        "cost_per_call": _dollars(input_cost(count.tokens, model)),
    }


def compare_report(
    rows: list[tuple[ModelInfo, TokenCount]], table: PriceTable, source: str
) -> dict:
    """`rows` in the order to report them (the CLI passes them cheapest first)."""
    return {
        "source": source,
        "prices_last_updated": table.last_updated.isoformat(),
        "models": [
            {
                "model": model.name,
                "provider": model.provider,
                "exact": model.exact,
                "tokens": count.tokens,
                "cost_per_call": _dollars(input_cost(count.tokens, model)),
            }
            for model, count in rows
        ],
    }


def _finding(finding: Finding) -> dict:
    s = finding.suggestion
    return {
        "rule": s.rule,
        "risk": s.risk.value,
        "title": s.title,
        "line": s.line,
        "see_line": s.see_line,
        "flag_only": s.flag_only,
        "tokens": finding.tokens,
        "dollars_per_call": _dollars(finding.dollars),
        "applied": finding.applied,
    }


def optimize_report(
    result: OptimizationResult,
    table: PriceTable,
    source: str,
    extra_if_all: int = 0,
    saved_to: Path | None = None,
    cache: CacheSaving | None = None,
    hit_rate: float | None = None,
) -> dict:
    """`caching` is added only when a hit rate is given (null if the model has no price)."""
    report = {
        "source": source,
        **_header(result.model, table),
        "tokens_before": result.tokens_before,
        "tokens_after": result.tokens_after,
        "tokens_saved": result.tokens_saved,
        "percent_saved": round(result.percent_saved, 2),
        "dollars_saved_per_call": _dollars(result.dollars_saved),
        "extra_tokens_if_all_applied": extra_if_all,
        "tidied": result.tidied,
        "findings": [_finding(f) for f in result.findings],
        "saved_to": str(saved_to) if saved_to is not None else None,
    }
    if hit_rate is not None:
        report["caching"] = _cache_saving(cache, hit_rate)
    return report


def _cache_saving(cache: CacheSaving | None, hit_rate: float) -> dict | None:
    if cache is None:
        return None
    average = cache.average
    return {
        "hit_rate": hit_rate,
        "fixed_tokens_before": cache.before.tokens,
        "fixed_tokens_after": cache.after.tokens,
        "min_cacheable_tokens": cache.before.min_tokens,
        "below_minimum_before": cache.before.below_minimum,
        "below_minimum_after": cache.after.below_minimum,
        "loses_caching": cache.loses_caching,
        "dollars_saved_per_call": {
            "uncached": _dollars(cache.uncached),
            "first_call": _dollars(cache.first_call),
            "cached_call": _dollars(cache.cached_call),
            "average": _dollars(average) if average is not None else None,
        },
    }


def scan_report(result: ScanResult, table: PriceTable, folder: str) -> dict:
    model = result.model
    return {
        "folder": folder,
        **_header(model, table),
        "files": [
            {
                "path": f.path,
                "tokens": f.tokens,
                "cost_per_call": _dollars(input_cost(f.tokens, model)),
                "safe_tokens_saved": f.safe_saved,
                "all_tokens_saved": f.all_saved,
                "dollars_saved_per_call_all": _dollars(input_cost(f.all_saved, model)),
            }
            for f in result.files
        ],
        "total": {
            "files": len(result.files),
            "tokens": result.tokens,
            "safe_tokens_saved": result.safe_saved,
            "all_tokens_saved": result.all_saved,
            "dollars_saved_per_call_all": _dollars(result.dollars_saved_all),
        },
        "skipped": result.skipped,
    }


def _part(part: Part, model: ModelInfo) -> dict:
    return {
        "source": part.source,
        "tokens": part.tokens,
        "exact": part.exact,
        "cost_per_call": _dollars(input_cost(part.tokens, model)),
    }


def _cache(cache: CacheEstimate | None, model: ModelInfo) -> dict | None:
    if cache is None:
        return None
    return {
        "cached_input_per_1m": model.cached_input_per_1m,
        "cache_write_per_1m": model.write_per_1m,
        "min_cacheable_tokens": cache.min_tokens,
        "below_minimum": cache.below_minimum,
        "hit_rate": cache.hit_rate,
        "fixed_cost_per_call": {
            "uncached": _dollars(cache.uncached),
            "first_call": _dollars(cache.first_call),
            "cached_call": _dollars(cache.cached_call),
            "average": _dollars(cache.average) if cache.average is not None else None,
        },
        "cached_call_saving_percent": round(cache.saving_percent, 2),
    }


def request_report(
    result: RequestBreakdown, table: PriceTable, cache: CacheEstimate | None = None
) -> dict:
    model = result.model
    tools = result.tools
    return {
        **_header(model, table),
        "fixed": {
            "tokens": result.fixed_tokens,
            "exact": result.fixed_exact,
            "cost_per_call": _dollars(input_cost(result.fixed_tokens, model)),
            "system": _part(result.system, model) if result.system else None,
            "tools": {**_part(tools, model), "tool_count": tools.tool_count} if tools else None,
        },
        "requests": [
            {
                "user": _part(user, model),
                "tokens": result.request_tokens(user),
                "exact": result.fixed_exact and user.exact,
                "fixed_percent": round(result.fixed_percent(user), 2),
                "cost_per_call": _dollars(input_cost(result.request_tokens(user), model)),
            }
            for user in result.users
        ],
        "caching": _cache(cache, model),
    }


def prefix_report(result: PrefixCheck, table: PriceTable, min_tokens: int) -> dict:
    return {
        **_header(result.model, table),
        "identical": result.identical,
        "fixed_part_differs": result.fixed_differs,
        "shared_prefix": {
            "tokens": result.shared_tokens,
            "exact": result.exact,
            "characters": result.shared_chars,
            "below_min_cacheable": result.shared_tokens < min_tokens,
            "min_cacheable_tokens": min_tokens,
        },
        "requests": [
            {
                "source": request.source,
                "tokens": request.tokens,
                "shared_prefix_tokens": request.shared_tokens,
                "tokens_after_prefix": request.rest_tokens,
            }
            for request in result.requests
        ],
        "differences": [
            {
                "source": diff.source,
                "part": diff.part,
                "fixed": diff.fixed,
                "line": diff.line,
                "column": diff.column,
                "snippet": diff.snippet,
                "looks_like": diff.dynamic,
            }
            for diff in result.differences
        ],
    }


def _optional_dollars(amount: float | None) -> float | None:
    return None if amount is None else _dollars(amount)


def _task_summary(summary: TaskSummary, with_types: bool = True) -> dict:
    usage = summary.usage
    rate = summary.success_rate
    report = {
        "label": summary.label,
        "models": summary.models,
        "tasks": len(summary.tasks),
        "passed": summary.passed,
        "failed": summary.failed,
        "unknown": summary.unknown,
        "success_rate": round(rate, 4) if rate is not None else None,
        "calls": summary.calls,
        "calls_per_task": round(summary.calls_per_task, 4),
        "usage": {
            "input": usage.input,
            "cache_read": usage.cache_read,
            "cache_write": usage.cache_write,
            "cache_write_1h": usage.cache_write_1h,
            "output": usage.output,
        },
        "cache_read_share": round(summary.cache_read_share, 4),
        "cost": _dollars(summary.cost),
        "cost_per_call": _dollars(summary.cost_per_call),
        "cost_per_task": _dollars(summary.cost_per_task),
        "cost_failed": _dollars(summary.cost_failed),
        "cost_per_successful_task": _optional_dollars(summary.cost_per_success),
    }
    if with_types:
        report["by_type"] = {
            name: _task_summary(group, with_types=False) for name, group in summary.by_type.items()
        }
    return report


def task_cost_report(summaries: list[TaskSummary], table: PriceTable) -> dict:
    """One entry per log; with two logs, `change` is the second minus the first."""
    report: dict = {
        "prices_last_updated": table.last_updated.isoformat(),
        "logs": [_task_summary(s) for s in summaries],
    }
    if len(summaries) == 2:
        first, second = summaries
        before, after = first.cost_per_success, second.cost_per_success
        report["change"] = {
            "cost_per_call": _dollars(second.cost_per_call - first.cost_per_call),
            "cost_per_successful_task": (
                _dollars(after - before) if before is not None and after is not None else None
            ),
        }
    return report
