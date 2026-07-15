"""Cost computation from token usage.

All GBP values live in ``prices.yaml``. This module deliberately contains
no hardcoded numbers (CLAUDE.md §9 rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PRICES_PATH = Path(__file__).parent / "prices.yaml"


@dataclass(frozen=True)
class Usage:
    """Token counts for a single LLM request."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class ModelPrices:
    """Per-million-token GBP rates for a single model."""

    input_per_million_gbp: float
    output_per_million_gbp: float
    cache_write_per_million_gbp: float
    cache_read_per_million_gbp: float


def load_prices(path: Path | str | None = None) -> dict[str, ModelPrices]:
    """Load model prices from ``prices.yaml`` (or a caller-provided path).

    Results are cached per resolved path so the YAML is not re-parsed on
    every LLM call. The returned dict is shared — treat it as read-only.
    """
    p = Path(path) if path is not None else DEFAULT_PRICES_PATH
    return _load_prices_cached(p)


@lru_cache(maxsize=8)
def _load_prices_cached(path: Path) -> dict[str, ModelPrices]:
    with path.open(encoding="utf-8") as f:
        raw: dict[str, dict[str, float]] = yaml.safe_load(f) or {}
    return {model: ModelPrices(**vals) for model, vals in raw.items()}


def compute_cost(
    model: str,
    usage: Usage,
    prices: dict[str, ModelPrices] | None = None,
) -> float:
    """Return GBP cost for a single LLM request.

    ``input_tokens`` from Anthropic represents non-cached input; cache
    read/write tokens are counted separately by the SDK.
    """
    if prices is None:
        prices = load_prices()
    if model not in prices:
        raise KeyError(f"No price defined for model {model!r} in prices.yaml")
    p = prices[model]
    return (
        usage.input_tokens * p.input_per_million_gbp
        + usage.output_tokens * p.output_per_million_gbp
        + usage.cache_read_input_tokens * p.cache_read_per_million_gbp
        + usage.cache_creation_input_tokens * p.cache_write_per_million_gbp
    ) / 1_000_000


def usage_from_response(response: Any) -> Usage:
    """Best-effort extraction of a Usage from a LangChain or native SDK response.

    Handles three shapes:
    - LangChain ``response.usage_metadata`` (dict, ≥ 0.3)
    - LangChain ``response.response_metadata["usage"]`` (dict)
    - Native Anthropic ``response.usage`` (Pydantic model or dict)
    """
    for source in (
        getattr(response, "usage_metadata", None),
        (getattr(response, "response_metadata", None) or {}).get("usage"),
        getattr(response, "usage", None),
    ):
        d = _coerce_to_dict(source)
        if d:
            return Usage(
                input_tokens=int(d.get("input_tokens", 0)),
                output_tokens=int(d.get("output_tokens", 0)),
                cache_read_input_tokens=int(d.get("cache_read_input_tokens", 0)),
                cache_creation_input_tokens=int(d.get("cache_creation_input_tokens", 0)),
            )
    return Usage()


def _coerce_to_dict(obj: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        result = dump()
        return result if isinstance(result, dict) else None
    return None
