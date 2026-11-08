import socket

import pytest
import tiktoken

from tokensaver import counter
from tokensaver.counter import count_raw, count_tokens, get_encoding
from tokensaver.pricing import load_prices

SAMPLES = {
    "empty": "",
    "hello": "Hello, world!",
    "special": "Text with <|endoftext|> inside",
    "unicode": "Grüße aus Köln — 東京 🚀 naïve café",
    "code": 'def f(x):\n    return {"a": [1, 2, 3]}\n\n\n',
    "spaces": "a    b\t\tc\n\n\n\nd   ",
}

# Produced by the official tiktoken.get_encoding() loader (tiktoken 0.14).
GOLDEN = {
    "o200k_base": {"empty": 0, "hello": 4, "special": 10, "unicode": 12, "code": 19, "spaces": 8},
    "cl100k_base": {"empty": 0, "hello": 4, "special": 9, "unicode": 16, "code": 19, "spaces": 8},
}


@pytest.mark.parametrize("encoding", sorted(GOLDEN))
@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_bundled_encoding_matches_official_counts(encoding: str, sample: str) -> None:
    assert count_raw(SAMPLES[sample], encoding) == GOLDEN[encoding][sample]


def test_counting_needs_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    get_encoding.cache_clear()
    assert count_raw("offline check", "o200k_base") > 0


def test_unknown_tokenizer_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported tokenizer"):
        get_encoding("p50k_base")


def test_corrupted_encoding_file_is_detected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "o200k_base.tiktoken").write_bytes(b"dGVzdA== 0\n")
    monkeypatch.setattr(counter, "ENCODINGS_DIR", tmp_path)
    get_encoding.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="corrupted"):
            get_encoding("o200k_base")
    finally:
        get_encoding.cache_clear()


def test_exact_model_returns_raw_count() -> None:
    model = load_prices().get("gpt-4o")
    result = count_tokens("Hello, world!", model)
    assert result.tokens == 4
    assert result.exact is True
    assert result.model == "gpt-4o"


def test_estimated_model_scales_and_is_labelled() -> None:
    model = load_prices().get("claude-opus-5-5")
    text = "Hello, world! " * 50
    raw = count_raw(text, model.tokenizer)
    result = count_tokens(text, model)
    assert result.exact is False
    assert result.tokens == round(raw * model.estimate_factor)


def test_exact_models_match_tiktoken_model_map() -> None:
    """A model may only claim exact counts if tiktoken maps it to the same encoding."""
    for model in load_prices().models.values():
        if model.exact:
            assert tiktoken.encoding_name_for_model(model.name) == model.tokenizer, model.name


# --- script factors ------------------------------------------------------------


def _with_factors(name: str = "claude-sonnet-5-5", **factors: float):
    from dataclasses import replace

    model = load_prices().get(name)
    return replace(model, script_factors=tuple(factors.items())) if factors else model


def test_script_runs_keep_neutral_characters_in_the_run() -> None:
    from tokensaver.counter import script_runs

    runs = script_runs("Hello, world! ਮੇਰਾ ਆਰਡਰ 123? Bye.")
    assert [s for s, _ in runs] == ["other", "Gurmukhi", "other"]
    assert "".join(part for _, part in runs) == "Hello, world! ਮੇਰਾ ਆਰਡਰ 123? Bye."
    assert runs[1][1].endswith("123? ")


def test_han_is_japanese_only_with_kana() -> None:
    from tokensaver.counter import script_runs

    assert {s for s, _ in script_runs("始终以格式回答。")} == {"Chinese"}
    assert {s for s, _ in script_runs("常に形式で回答してください。")} == {"Japanese"}


def test_text_without_measured_scripts_is_unchanged() -> None:
    model = _with_factors(Gurmukhi=3.9)
    text = 'Answer in JSON: {"a": 1}\nÜbersetze das bitte. def f(x): return x'
    raw = count_raw(text, model.tokenizer)
    assert count_tokens(text, model).tokens == round(raw * model.estimate_factor)


def test_script_factor_scales_that_script_only() -> None:
    model = _with_factors(Gurmukhi=3.9)
    punjabi = "ਮੇਰਾ ਆਰਡਰ ਕਿੱਥੇ ਹੈ?"
    english = "Where is my order?"
    assert count_tokens(punjabi, model).tokens == round(count_raw(punjabi, "o200k_base") * 3.9)
    mixed = count_tokens(english + " " + punjabi, model).tokens
    expected = (
        count_raw(english + " ", "o200k_base") * model.estimate_factor
        + count_raw(punjabi, "o200k_base") * 3.9
    )
    assert mixed == round(expected)


def test_unmeasured_script_uses_the_default_factor() -> None:
    model = _with_factors(Gurmukhi=3.9)
    greek = "Απάντα πάντα σε μορφή JSON."
    raw = count_raw(greek, model.tokenizer)
    assert count_tokens(greek, model).tokens == round(raw * model.estimate_factor)


def test_bundled_claude_models_have_script_factors() -> None:
    for model in load_prices().models.values():
        if model.provider == "Anthropic":
            factors = dict(model.script_factors)
            assert factors["Gurmukhi"] > factors["Chinese"] > 1, model.name
