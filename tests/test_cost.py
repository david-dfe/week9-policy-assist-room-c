"""Tests for the cost module."""

from __future__ import annotations

from pathlib import Path

import pytest

from monitoring.cost import (
    ModelPrices,
    Usage,
    compute_cost,
    load_prices,
    usage_from_response,
)

# Reusable test fixture — kept deliberately different from real prices.yaml
# so that swapping the file cannot silently change these expectations.
_TEST_PRICES = {
    "m": ModelPrices(
        input_per_million_gbp=2.0,
        output_per_million_gbp=10.0,
        cache_write_per_million_gbp=3.0,
        cache_read_per_million_gbp=0.5,
    )
}


class TestComputeCost:
    def test_input_only(self) -> None:
        cost = compute_cost("m", Usage(input_tokens=1_000_000), _TEST_PRICES)
        assert cost == pytest.approx(2.0)

    def test_output_only(self) -> None:
        cost = compute_cost("m", Usage(output_tokens=1_000_000), _TEST_PRICES)
        assert cost == pytest.approx(10.0)

    def test_cache_read_discount(self) -> None:
        cost = compute_cost("m", Usage(cache_read_input_tokens=1_000_000), _TEST_PRICES)
        assert cost == pytest.approx(0.5)

    def test_cache_write_premium(self) -> None:
        cost = compute_cost("m", Usage(cache_creation_input_tokens=1_000_000), _TEST_PRICES)
        assert cost == pytest.approx(3.0)

    def test_summed(self) -> None:
        # 1000*2 + 100*10 + 5000*0.5 = 5500 microtokens-of-GBP => 0.0055 GBP
        usage = Usage(input_tokens=1_000, output_tokens=100, cache_read_input_tokens=5_000)
        assert compute_cost("m", usage, _TEST_PRICES) == pytest.approx(0.0055)

    def test_zero_usage_zero_cost(self) -> None:
        assert compute_cost("m", Usage(), _TEST_PRICES) == 0.0

    def test_missing_model_raises(self) -> None:
        with pytest.raises(KeyError, match="unknown-model"):
            compute_cost("unknown-model", Usage(input_tokens=1), {})

    def test_loads_bundled_prices_when_none_passed(self) -> None:
        # Uses monitoring/prices.yaml — should not raise for a known model.
        cost = compute_cost("claude-haiku-4-5", Usage(input_tokens=1_000_000))
        assert cost > 0


class TestLoadPrices:
    def test_loads_bundled_prices(self) -> None:
        prices = load_prices()
        assert "claude-sonnet-4-5" in prices
        assert "claude-haiku-4-5" in prices

    def test_bundled_prices_are_positive(self) -> None:
        for model, p in load_prices().items():
            assert p.input_per_million_gbp > 0, f"{model} input rate must be positive"
            assert p.output_per_million_gbp > 0, f"{model} output rate must be positive"

    def test_cache_read_cheaper_than_input(self) -> None:
        # Anthropic caching only makes sense if reads are discounted; this test
        # protects against a paste error swapping the two values.
        for model, p in load_prices().items():
            assert p.cache_read_per_million_gbp < p.input_per_million_gbp, (
                f"{model}: cache-read must be cheaper than input"
            )

    def test_loads_from_path(self, tmp_path: Path) -> None:
        f = tmp_path / "custom.yaml"
        f.write_text(
            "test-model:\n"
            "  input_per_million_gbp: 1.0\n"
            "  output_per_million_gbp: 5.0\n"
            "  cache_write_per_million_gbp: 1.25\n"
            "  cache_read_per_million_gbp: 0.1\n"
        )
        prices = load_prices(f)
        assert prices["test-model"].input_per_million_gbp == 1.0
        assert prices["test-model"].output_per_million_gbp == 5.0

    def test_empty_yaml_returns_empty_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        f.write_text("")
        assert load_prices(f) == {}


class TestUsageFromResponse:
    def test_langchain_usage_metadata(self) -> None:
        class R:
            usage_metadata = {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 300,
            }

        u = usage_from_response(R())
        assert u == Usage(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=200,
            cache_creation_input_tokens=300,
        )

    def test_langchain_response_metadata_nested(self) -> None:
        class R:
            response_metadata = {"usage": {"input_tokens": 10, "output_tokens": 20}}

        u = usage_from_response(R())
        assert u.input_tokens == 10
        assert u.output_tokens == 20

    def test_native_pydantic_usage(self) -> None:
        class NativeUsage:
            def model_dump(self) -> dict[str, int]:
                return {"input_tokens": 7, "output_tokens": 8}

        class R:
            usage = NativeUsage()

        u = usage_from_response(R())
        assert u.input_tokens == 7
        assert u.output_tokens == 8

    def test_missing_returns_zero(self) -> None:
        assert usage_from_response(object()) == Usage()

    def test_partial_fields_default_to_zero(self) -> None:
        class R:
            usage_metadata = {"input_tokens": 10}

        u = usage_from_response(R())
        assert u.input_tokens == 10
        assert u.output_tokens == 0
        assert u.cache_read_input_tokens == 0
        assert u.cache_creation_input_tokens == 0

    def test_model_dump_non_dict_returns_zero(self) -> None:
        class BadUsage:
            def model_dump(self) -> str:
                return "not a dict"

        class R:
            usage = BadUsage()

        assert usage_from_response(R()) == Usage()
