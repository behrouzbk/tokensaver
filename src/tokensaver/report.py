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
from tokensaver.request import CacheEstimate, Part, RequestBreakdown
from tokensaver.scan import ScanResult


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
) -> dict:
    return {
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
