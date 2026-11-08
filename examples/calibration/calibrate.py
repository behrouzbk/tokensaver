"""Calibrate tokensaver's Claude and Gemini estimates against the official token counters.

tokensaver has no offline tokenizer for Claude or Gemini, so it estimates their counts
as `o200k_base count x estimate_factor` (from prices.json). This script counts the texts
in corpus/ both ways and fits the factor per model (issue #3).

    pip install prompt-tokensaver anthropic
    python calibrate.py --dry-run          # offline o200k counts and current estimates only
    python calibrate.py --only claude      # needs ANTHROPIC_API_KEY (or `ant auth login`)
    python calibrate.py --only gemini      # needs GEMINI_API_KEY or GOOGLE_API_KEY
    python calibrate.py --analyze          # rebuild results/summary.md from saved counts

Counts are saved to results/counts.json after each provider, so the two providers can be
run separately. tokensaver itself stays offline; this is a one-time calibration.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tokensaver.counter import count_raw
from tokensaver.pricing import load_prices

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
RESULTS = HERE / "results"
COUNTS_FILE = RESULTS / "counts.json"

CLAUDE = [
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-haiku-4-5",
]
GEMINI = [
    "gemini-4-argon",
    "gemini-3.8-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
# Texts also counted twice in a row, to measure the API's per-request framing tokens.
PROBES = ["lang_en.txt", "prose_readme_limitations.txt", "code_scan_1.py.txt"]
DOUBLED = "2x:"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:countTokens"
LANGUAGES = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "ru": "Russian",
    "ar": "Arabic",
    "he": "Hebrew",
    "hi": "Hindi",
    "pa": "Punjabi",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "th": "Thai",
}


# --- corpus ------------------------------------------------------------------------


def load_corpus() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(CORPUS.iterdir())}


def category(name: str) -> str:
    """'English prose', 'code', 'JSON', 'mixed' or the language of a lang_xx text."""
    kind = name.split("_", 1)[0]
    if kind == "lang":
        return LANGUAGES[name.split("_", 1)[1].split(".")[0]]
    return {"prose": "English prose", "code": "code", "json": "JSON"}.get(kind, "mixed")


# --- counting ----------------------------------------------------------------------


def count_claude(models: list[str], texts: dict[str, str]) -> dict[str, dict[str, int]]:
    import anthropic

    client = anthropic.Anthropic()

    def one(job):
        model, name = job
        response = client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": texts[name]}]
        )
        return model, name, response.input_tokens

    return _run(one, models, texts)


def count_gemini(models: list[str], texts: dict[str, str]) -> dict[str, dict[str, int]]:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("Set GEMINI_API_KEY or GOOGLE_API_KEY to count Gemini tokens.")

    def one(job):
        model, name = job
        body = json.dumps({"contents": [{"parts": [{"text": texts[name]}]}]}).encode("utf-8")
        request = urllib.request.Request(
            GEMINI_URL.format(model=model),
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return model, name, json.load(response)["totalTokens"]
            except urllib.error.HTTPError as error:
                if error.code in (429, 500, 503) and attempt < 5:
                    time.sleep(2**attempt)
                    continue
                detail = error.read().decode("utf-8", "replace")[:300]
                if error.code == 404:
                    raise ModelUnavailable(f"{model}: HTTP 404 {detail}") from None
                raise RuntimeError(f"{model} {name}: HTTP {error.code} {detail}") from None

    return _run(one, models, texts)


class ModelUnavailable(RuntimeError):
    """The provider no longer serves this model (to this account)."""


def _run(one, models, texts) -> dict[str, dict[str, int]]:
    """Count every text on every model. A model the provider no longer serves is skipped."""
    out: dict[str, dict[str, int]] = {}
    for model in models:
        jobs = [(model, n) for n in texts]
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                out[model] = {name: tokens for _, name, tokens in pool.map(one, jobs)}
        except ModelUnavailable as error:
            print(f"  {model}: skipped, not available ({str(error)[:120]})", flush=True)
            continue
        print(f"  {model}: {len(out[model])} texts counted", flush=True)
    return out


# --- analysis ----------------------------------------------------------------------


def overhead(official: dict[str, int]) -> float:
    """Framing tokens the API adds per request: 2 x count(text) - count(text twice)."""
    values = [
        2 * official[name] - official[DOUBLED + name]
        for name in PROBES
        if name in official and DOUBLED + name in official
    ]
    return statistics.median(values) if values else 0.0


def analyze(counts: dict) -> str:
    raw = counts["o200k"]
    prices = load_prices()
    lines = [
        "# Token estimate calibration",
        "",
        f"{len(raw)} texts in `corpus/`. Each text is counted offline with o200k (as tokensaver",
        "does) and with the provider's official counter. The API adds a few framing tokens",
        "per request; that overhead is measured by counting a few texts once and twice in a",
        "row, and subtracted. The fitted factor is the median of `(official - overhead) / o200k`",
        "over all texts, so one unusual script cannot pull it far.",
        "",
        "| Model | Current factor | Fitted factor | Overhead | Median error now "
        "| Median error fitted |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    per_category: dict[str, dict[str, list[float]]] = {}
    for model, official in counts["models"].items():
        names = [n for n in raw if n in official]
        if not names:
            continue
        framing = overhead(official)
        xs = [raw[n] for n in names]
        real = [official[n] - framing for n in names]  # the text's own tokens
        factor = statistics.median(y / x for x, y in zip(xs, real, strict=True))
        current = prices.get(model).estimate_factor if model in prices.models else float("nan")
        err_now = [abs(current * x - y) / y for x, y in zip(xs, real, strict=True)]
        err_fit = [abs(factor * x - y) / y for x, y in zip(xs, real, strict=True)]
        lines.append(
            f"| {model} | {current:.2f} | {factor:.3f} | {framing:+.1f} | "
            f"{statistics.median(err_now):.1%} | {statistics.median(err_fit):.1%} |"
        )
        for n, x, y in zip(names, xs, real, strict=True):
            per_category.setdefault(model, {}).setdefault(category(n), []).append(y / x)

    cats = sorted({c for model in per_category.values() for c in model})
    lines += ["", "## Ratio by kind of text (median, min-max)", ""]
    lines.append("| Kind | " + " | ".join(per_category) + " |")
    lines.append("|---|" + "---:|" * len(per_category))
    for cat in cats:
        cells = []
        for model in per_category:
            values = per_category[model].get(cat, [])
            if not values:
                cells.append("")
            elif len(values) == 1:
                cells.append(f"{values[0]:.2f}")
            else:
                cells.append(
                    f"{statistics.median(values):.2f} ({min(values):.2f}-{max(values):.2f})"
                )
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# --- main --------------------------------------------------------------------------


def load_counts(texts: dict[str, str]) -> dict:
    if COUNTS_FILE.exists():
        counts = json.loads(COUNTS_FILE.read_text(encoding="utf-8"))
    else:
        counts = {"models": {}}
    counts["o200k"] = {name: count_raw(text, "o200k_base") for name, text in texts.items()}
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Offline counts only.")
    group.add_argument("--only", choices=["claude", "gemini"], help="Count one provider.")
    group.add_argument("--analyze", action="store_true", help="Re-analyze saved counts.")
    args = parser.parse_args()

    texts = load_corpus()
    counts = load_counts(texts)

    if args.dry_run:
        prices = load_prices()
        print(f"{len(texts)} texts, {sum(counts['o200k'].values()):,} o200k tokens in total")
        for name, tokens in counts["o200k"].items():
            print(f"  {name:36} {category(name):14} {tokens:6,} o200k tokens")
        print("Current estimates for the whole corpus:")
        for model in CLAUDE + GEMINI:
            factor = prices.get(model).estimate_factor
            total = round(sum(counts["o200k"].values()) * factor)
            print(f"  {model:24} x{factor:<5} ~{total:,} tokens")
        print("No API calls were made.")
        return 0

    if not args.analyze:
        providers = [args.only] if args.only else ["claude", "gemini"]
        for provider in providers:
            models = CLAUDE if provider == "claude" else GEMINI
            print(f"Counting {len(texts)} texts on {len(models)} {provider} models...")
            to_count = {**texts, **{DOUBLED + n: texts[n] * 2 for n in PROBES}}
            counter = count_claude if provider == "claude" else count_gemini
            counted = counter(models, to_count)
            counts["models"].update(counted)
            RESULTS.mkdir(exist_ok=True)
            COUNTS_FILE.write_text(json.dumps(counts, indent=2), encoding="utf-8")

    if not counts["models"]:
        sys.exit("No saved counts yet. Run with --only claude or --only gemini first.")
    summary = analyze(counts)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.md").write_text(summary, encoding="utf-8")
    print()
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
