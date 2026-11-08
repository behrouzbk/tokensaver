import copy
import json
from datetime import date

import pytest

from tokensaver.counter import ENCODINGS_DIR
from tokensaver.pricing import (
    PriceDataError,
    UnknownModelError,
    cache_write_cost,
    cached_input_cost,
    input_cost,
    load_prices,
    parse_prices,
)

VALID = {
    "last_updated": "2026-10-26",
    "models": {
        "demo-model": {
            "provider": "Demo",
            "input_per_1m": 2.0,
            "output_per_1m": 8.0,
            "tokenizer": "o200k_base",
            "exact": False,
            "estimate_factor": 1.2,
            "source_url": "https://example.com/pricing",
        }
    },
}


def test_bundled_prices_load_and_have_date() -> None:
    table = load_prices()
    assert isinstance(table.last_updated, date)
    assert "gpt-4o" in table.models


def test_bundled_prices_are_complete() -> None:
    for model in load_prices().models.values():
        assert model.source_url.startswith("https://"), model.name
        assert model.input_per_1m > 0, model.name
        assert (ENCODINGS_DIR / f"{model.tokenizer}.tiktoken").is_file(), model.name


def test_bundled_prices_cover_three_providers() -> None:
    providers = {m.provider for m in load_prices().models.values()}
    assert {"OpenAI", "Anthropic", "Google"} <= providers


def test_load_from_custom_path(tmp_path) -> None:
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(VALID), encoding="utf-8")
    table = load_prices(path)
    model = table.get("demo-model")
    assert model.estimate_factor == 1.2
    assert model.notes == ""


def test_input_cost() -> None:
    model = parse_prices(VALID).get("demo-model")
    assert input_cost(1_000_000, model) == pytest.approx(2.0)
    assert input_cost(500, model) == pytest.approx(0.001)
    assert input_cost(0, model) == 0


def test_unknown_model_suggests_close_names() -> None:
    table = load_prices()
    with pytest.raises(UnknownModelError) as info:
        table.get("gpt-4-o")
    assert "gpt-4o" in info.value.suggestions
    assert "Did you mean" in str(info.value)


def test_exact_model_ignores_estimate_factor() -> None:
    raw = copy.deepcopy(VALID)
    raw["models"]["demo-model"].update(exact=True, estimate_factor=9.9)
    assert parse_prices(raw).get("demo-model").estimate_factor == 1.0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r.pop("last_updated"), "last_updated"),
        (lambda r: r.update(last_updated="last week"), "date"),
        (lambda r: r.update(models={}), "non-empty"),
        (lambda r: r["models"]["demo-model"].pop("source_url"), "source_url"),
        (lambda r: r["models"]["demo-model"].pop("estimate_factor"), "estimate_factor"),
        (lambda r: r["models"]["demo-model"].update(input_per_1m=-1), "negative"),
        (lambda r: r["models"]["demo-model"].update(estimate_factor=0), "positive"),
        (lambda r: r["models"]["demo-model"].update(cached_input_per_1m=-0.1), "negative"),
        (lambda r: r["models"]["demo-model"].update(cache_write_per_1m=-1), "negative"),
        (lambda r: r["models"]["demo-model"].update(min_cacheable_tokens=1.5), "whole"),
        (lambda r: r["models"]["demo-model"].update(min_cacheable_tokens=-1), "whole"),
        (lambda r: r["models"]["demo-model"].update(script_factors={"Klingon": 2}), "unknown"),
        (lambda r: r["models"]["demo-model"].update(script_factors={"Thai": 0}), "positive"),
        (lambda r: r["models"]["demo-model"].update(script_factors=[1]), "object"),
    ],
)
def test_invalid_price_data_is_rejected(change, message: str) -> None:
    raw = copy.deepcopy(VALID)
    change(raw)
    with pytest.raises(PriceDataError, match=message):
        parse_prices(raw)


# --- prompt caching ------------------------------------------------------------


def test_caching_fields_are_optional() -> None:
    model = parse_prices(VALID).get("demo-model")
    assert not model.caches
    assert model.min_cacheable_tokens is None
    assert cached_input_cost(1_000_000, model) == pytest.approx(2.0)  # no discount known
    assert cache_write_cost(1_000_000, model) == pytest.approx(2.0)


def test_caching_fields_are_parsed() -> None:
    raw = copy.deepcopy(VALID)
    raw["models"]["demo-model"].update(
        cached_input_per_1m=0.2, cache_write_per_1m=2.5, min_cacheable_tokens=512
    )
    model = parse_prices(raw).get("demo-model")
    assert model.caches
    assert cached_input_cost(1_000_000, model) == pytest.approx(0.2)
    assert cache_write_cost(1_000_000, model) == pytest.approx(2.5)
    assert model.min_cacheable_tokens == 512


def test_cache_write_defaults_to_input_price() -> None:
    raw = copy.deepcopy(VALID)
    raw["models"]["demo-model"]["cached_input_per_1m"] = 1.0
    model = parse_prices(raw).get("demo-model")
    assert model.write_per_1m == model.input_per_1m


def test_bundled_models_all_have_cache_prices() -> None:
    for model in load_prices().models.values():
        assert model.caches, model.name
        assert 0 < model.cached_input_per_1m < model.input_per_1m, model.name
        assert model.write_per_1m >= model.input_per_1m, model.name


def test_script_factors_are_parsed() -> None:
    raw = copy.deepcopy(VALID)
    raw["models"]["demo-model"]["script_factors"] = {"Thai": 2.4, "Chinese": 1.5}
    model = parse_prices(raw).get("demo-model")
    assert dict(model.script_factors) == {"Thai": 2.4, "Chinese": 1.5}


def test_exact_model_ignores_script_factors() -> None:
    raw = copy.deepcopy(VALID)
    raw["models"]["demo-model"].update(exact=True, script_factors={"Thai": 2.4})
    assert parse_prices(raw).get("demo-model").script_factors == ()
