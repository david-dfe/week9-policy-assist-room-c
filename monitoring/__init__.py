"""OpenTelemetry-based LLM observability client.

See ``CLAUDE.md`` §9 for domain rules governing what may and may not
appear on OTel spans (no raw prompt or completion text).
"""

from monitoring.cost import (
    ModelPrices,
    Usage,
    compute_cost,
    load_prices,
    usage_from_response,
)
from monitoring.instrumentation import LLMSpan, instrument_app, traced_llm_call

__version__ = "0.1.0"

__all__ = [
    "LLMSpan",
    "ModelPrices",
    "Usage",
    "__version__",
    "compute_cost",
    "instrument_app",
    "load_prices",
    "traced_llm_call",
    "usage_from_response",
]
