"""Token counting. Exact for OpenAI models via tiktoken, labelled estimates otherwise.

The tiktoken encoding files ship inside the package, so counting never touches the
network. The definitions below mirror tiktoken_ext.openai_public; tests compare the
results against counts produced by the official tiktoken loader.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import tiktoken

from tokensaver.pricing import ModelInfo

ENCODINGS_DIR = Path(__file__).parent / "data" / "encodings"

_O200K_PATTERN = "|".join(
    [
        r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
        r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
        r"""\p{N}{1,3}""",
        r""" ?[^\s\p{L}\p{N}]+[\r\n/]*""",
        r"""\s*[\r\n]+""",
        r"""\s+(?!\S)""",
        r"""\s+""",
    ]
)
_CL100K_PATTERN = r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"""  # noqa: E501

_ENCODINGS = {
    "o200k_base": {
        "sha256": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
        "pat_str": _O200K_PATTERN,
        "special_tokens": {"<|endoftext|>": 199999, "<|endofprompt|>": 200018},
    },
    "cl100k_base": {
        "sha256": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
        "pat_str": _CL100K_PATTERN,
        "special_tokens": {
            "<|endoftext|>": 100257,
            "<|fim_prefix|>": 100258,
            "<|fim_middle|>": 100259,
            "<|fim_suffix|>": 100260,
            "<|endofprompt|>": 100276,
        },
    },
}


@dataclass(frozen=True)
class TokenCount:
    model: str
    tokens: int
    exact: bool


def _load_ranks(name: str, expected_sha256: str) -> dict[bytes, int]:
    data = (ENCODINGS_DIR / f"{name}.tiktoken").read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise RuntimeError(f"Bundled encoding file {name}.tiktoken is corrupted.")
    ranks = {}
    for line in data.splitlines():
        if line:
            token, rank = line.split()
            ranks[base64.b64decode(token)] = int(rank)
    return ranks


@cache
def get_encoding(name: str) -> tiktoken.Encoding:
    """Build a tiktoken Encoding from the bundled files (no network access)."""
    if name not in _ENCODINGS:
        raise ValueError(f"Unsupported tokenizer '{name}'. Supported: {', '.join(_ENCODINGS)}")
    spec = _ENCODINGS[name]
    return tiktoken.Encoding(
        name=name,
        pat_str=spec["pat_str"],
        mergeable_ranks=_load_ranks(name, spec["sha256"]),
        special_tokens=spec["special_tokens"],
    )


def count_raw(text: str, tokenizer: str) -> int:
    """Token count for a tokenizer. Special-token text is counted as plain text."""
    return len(get_encoding(tokenizer).encode_ordinary(text))


def count_tokens(text: str, model: ModelInfo) -> TokenCount:
    """Count tokens for a model; non-exact models get a scaled estimate.

    With `script_factors`, tokens of text written in a measured script (Arabic, Thai,
    Gurmukhi, ...) are scaled by that script's factor and the rest by `estimate_factor`.
    Text with none of those scripts is scaled exactly as before.
    """
    if model.exact:
        return TokenCount(model=model.name, tokens=count_raw(text, model.tokenizer), exact=True)
    factors = dict(model.script_factors)
    if not factors or not _SCRIPT_CHARS.search(text):
        tokens = round(count_raw(text, model.tokenizer) * model.estimate_factor)
    else:
        tokens = round(
            sum(
                count * factors.get(script, model.estimate_factor)
                for script, count in tokens_by_script(text, model.tokenizer).items()
            )
        )
    return TokenCount(model=model.name, tokens=tokens, exact=False)


def tokens_by_script(text: str, tokenizer: str) -> dict[str, int]:
    """Tokenize the whole text once and count its tokens per script (see script_runs).

    The counts add up to count_raw(text): splitting the text first would add tokens at
    every cut. A token belongs to the script of the first letter it covers, or to the
    run it starts in if it covers no letter.
    """
    encoding = get_encoding(tokenizer)
    tokens = encoding.encode_ordinary(text)
    _, offsets = encoding.decode_with_offsets(tokens)
    labels: list[str] = []
    for script, part in script_runs(text):
        labels.extend([script] * len(part))
    letters = [_script_of(ch) is not None or ch.isalpha() for ch in text]
    counts: dict[str, int] = {}
    ends = [*offsets[1:], len(text)]
    for start, end in zip(offsets, ends, strict=True):
        start = min(start, len(text) - 1)
        first = next((i for i in range(start, max(end, start + 1)) if letters[i]), start)
        script = labels[first]
        counts[script] = counts.get(script, 0) + 1
    return counts


# Writing systems with a measured factor in prices.json (`script_factors`). Everything
# else (Latin letters, other scripts) uses the model's `estimate_factor`.
SCRIPT_RANGES: dict[str, list[tuple[int, int]]] = {
    "Arabic": [
        (0x0600, 0x06FF),
        (0x0750, 0x077F),
        (0x08A0, 0x08FF),
        (0xFB50, 0xFDFF),
        (0xFE70, 0xFEFF),
    ],
    "Hebrew": [(0x0590, 0x05FF), (0xFB1D, 0xFB4F)],
    "Devanagari": [(0x0900, 0x097F), (0xA8E0, 0xA8FF)],
    "Gurmukhi": [(0x0A00, 0x0A7F)],
    "Thai": [(0x0E00, 0x0E7F)],
    "Hangul": [(0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF)],
    "Cyrillic": [(0x0400, 0x052F)],
    "Han": [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)],
    "Kana": [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF)],
}
_SCRIPT_CHARS = re.compile(
    "["
    + "".join(f"\\u{lo:04x}-\\u{hi:04x}" for ranges in SCRIPT_RANGES.values() for lo, hi in ranges)
    + "]"
)
_KANA = re.compile("[぀-ヿㇰ-ㇿ]")


def _script_of(char: str) -> str | None:
    code = ord(char)
    for script, ranges in SCRIPT_RANGES.items():
        if any(lo <= code <= hi for lo, hi in ranges):
            return script
    return None


def script_runs(text: str) -> list[tuple[str, str]]:
    """Split text into (script, part) runs. Script is one of SCRIPTS or "other".

    Spaces, digits and punctuation stay in the run they sit in. Han characters count as
    Japanese when the text has any kana, and as Chinese otherwise.
    """
    japanese = bool(_KANA.search(text))
    runs: list[tuple[str, str]] = []
    current: str | None = None
    start = 0
    for i, char in enumerate(text):
        script = _script_of(char)
        if script in ("Han", "Kana"):
            script = "Japanese" if japanese else "Chinese"
        elif script is None:
            if not char.isalpha():
                continue  # neutral: belongs to the current run
            script = "other"
        if current is None:
            current = script
        elif script != current:
            runs.append((current, text[start:i]))
            current, start = script, i
    runs.append((current or "other", text[start:]))
    return runs
