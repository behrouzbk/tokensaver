"""Remove polite filler and wordy phrases that add tokens but no instructions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tokensaver.optimizer.base import (
    Edit,
    Risk,
    Suggestion,
    drop_overlapping,
    line_number,
    overlaps,
)
from tokensaver.optimizer.fewshot import protected_spans

NAME = "filler"
RISK = Risk.REVIEW


@dataclass(frozen=True)
class Phrase:
    label: str
    pattern: re.Pattern[str]
    replacement: str = ""


def _p(label: str, regex: str, replacement: str = "") -> Phrase:
    return Phrase(label, re.compile(regex, re.IGNORECASE), replacement)


PHRASES: tuple[Phrase, ...] = (
    _p("I would like you to…", r"\bI would (?:really )?(?:like|love) (?:for )?you to (?:please )?"),
    _p("I'd appreciate it if you…", r"\bI(?:'d| would) appreciate it if you (?:could|would) (?:please )?"),  # noqa: E501
    _p("I want you to…", r"\bI want you to (?:please )?"),
    _p("Could you please…", r"\b(?:could|can|would) you (?:please|kindly) "),
    _p("Please note that…", r"\bplease note that "),
    _p("It is important to note that…", r"\bit is (?:very )?important to note that "),
    _p("As an AI…", r"\bas an AI(?: language model| assistant| model)?,? "),
    _p("if it's not too much trouble", r"\bif (?:it's|it is) not too much trouble,? "),
    _p("Kindly…", r"\bkindly "),
    _p("Thank you in advance", r"\b(?:thank you|thanks)(?: so much| very much)?(?: in advance)?(?: for your help)?[.!]+[ \t]*"),  # noqa: E501
    _p("I hope this makes sense", r"\bI hope (?:this|that) (?:makes sense|helps)[.!]*[ \t]*"),
    _p("in order to → to", r"\bin order to\b", "to"),
    _p("due to the fact that → because", r"\bdue to the fact that\b", "because"),
    _p("at this point in time → now", r"\bat this point in time\b", "now"),
    _p("for the purpose of → for", r"\bfor the purpose of\b", "for"),
    _p("in the event that → if", r"\bin the event that\b", "if"),
    _p("with regard to → about", r"\bwith regards? to\b", "about"),
    # Persian: U+200C (ZWNJ) below is invisible; U+064B (tanween) is a non-word char.
    _p("لطفاً…", r"\bلطفاً? "),
    _p("از تو/شما می‌خواهم که…", r"\bاز (?:تو|شما) می[‌ ]?خواهم که "),
    _p("ممنون می‌شوم اگر…", r"\bممنون می[‌ ]?شوم اگر "),
)  # fmt: skip

_SENTENCE_END = ".!?:\n"
_BULLET_TAIL = re.compile(r"(?:^|\n)[ \t]*(?:[-*•]|\d+[.)])[ \t]*\Z")


def _at_sentence_start(text: str, index: int) -> bool:
    before = text[:index]
    trimmed = before.rstrip(" \t")
    return not trimmed or trimmed[-1] in _SENTENCE_END or bool(_BULLET_TAIL.search(before))


def _match_case(replacement: str, original: str) -> str:
    if replacement and original[:1].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _edit_for(text: str, match: re.Match[str], phrase: Phrase) -> Edit:
    start, end = match.span()
    if phrase.replacement:
        return Edit(start, end, _match_case(phrase.replacement, match.group()))
    # Removing a sentence opener: capitalise the next word if needed.
    next_char = text[end : end + 1]
    if next_char.islower() and _at_sentence_start(text, start):
        return Edit(start, end + 1, next_char.upper())
    return Edit(start, end)


def find(text: str) -> list[Suggestion]:
    fences = protected_spans(text)
    candidates: list[tuple[Phrase, Edit]] = []
    for phrase in PHRASES:
        for match in phrase.pattern.finditer(text):
            if not overlaps(match.start(), match.end(), fences):
                candidates.append((phrase, _edit_for(text, match, phrase)))

    kept = set(drop_overlapping(edit for _, edit in candidates))
    suggestions = []
    for phrase in PHRASES:
        edits = tuple(edit for p, edit in candidates if p is phrase and edit in kept)
        if not edits:
            continue
        suggestions.append(
            Suggestion(
                rule=NAME,
                risk=RISK,
                title=f"Filler: “{phrase.label}” (×{len(edits)})",
                reason="Models follow direct instructions just as well; politeness and "
                "wordy phrasing only add tokens.",
                line=line_number(text, edits[0].start),
                edits=edits,
            )
        )
    return sorted(suggestions, key=lambda s: s.line)
