import pytest

from tokensaver.optimizer import filler
from tokensaver.optimizer.base import Risk


def test_needs_review() -> None:
    assert filler.RISK is Risk.REVIEW


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("I would like you to please summarize this.", "Summarize this."),
        ("Could you please translate it.", "Translate it."),
        ("Please note that dates use ISO format.", "Dates use ISO format."),
        ("As an AI language model, you answer briefly.", "You answer briefly."),
        ("Read it. I want you to list the risks.", "Read it. List the risks."),
        ("- I want you to check spelling", "- Check spelling"),
        ("Do it in order to save time.", "Do it to save time."),
        ("In order to help, be brief.", "To help, be brief."),
        ("Skip it due to the fact that it is old.", "Skip it because it is old."),
        ("Summarize it. Thanks in advance!", "Summarize it. "),
        ("Use tables. I hope this makes sense.", "Use tables. "),
        ("لطفاً متن را خلاصه کن.", "متن را خلاصه کن."),
        ("لطفا متن را خلاصه کن.", "متن را خلاصه کن."),
        ("متن را لطفاً خلاصه کن.", "متن را خلاصه کن."),
        ("از تو می‌خواهم که متن را خلاصه کنی.", "متن را خلاصه کنی."),
        ("از شما می خواهم که متن را خلاصه کنی.", "متن را خلاصه کنی."),
        ("از تو میخواهم که متن را خلاصه کنی.", "متن را خلاصه کنی."),
        ("ممنون می‌شوم اگر متن را خلاصه کنی.", "متن را خلاصه کنی."),
        ("ممنون میشوم اگر متن را خلاصه کنی.", "متن را خلاصه کنی."),
        ("لطفاً از تو می‌خواهم که متن را خلاصه کنی.", "متن را خلاصه کنی."),
    ],
)
def test_removes_or_shortens_filler(apply_rule, before: str, after: str) -> None:
    assert apply_rule(filler, before) == after


def test_mid_sentence_removal_keeps_lowercase(apply_rule) -> None:
    assert apply_rule(filler, "Then kindly reply in English.") == "Then reply in English."


def test_plain_instructions_are_untouched() -> None:
    assert filler.find("Summarize the text in three bullet points.") == []


def test_omitted_conditional_phrases_are_untouched() -> None:
    # Deliberately NOT added: "if possible" can be a real condition, and
    # removing it would make the request mandatory.
    assert filler.find("اگر امکان دارد تست هم بنویس.") == []
    assert filler.find("اگر ممکن است زودتر جواب بده.") == []


def test_plain_persian_instructions_are_untouched() -> None:
    assert filler.find("متن را در سه نکته خلاصه کن.") == []


def test_ignores_code_blocks() -> None:
    assert filler.find("```\n# in order to run, call main()\n```") == []


def test_groups_repeated_phrases() -> None:
    [suggestion] = filler.find("Kindly read. Kindly answer. Kindly stop.")
    assert "×3" in suggestion.title
    assert len(suggestion.edits) == 3
