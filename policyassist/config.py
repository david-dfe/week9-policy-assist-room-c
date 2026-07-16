"""Shared configuration constants for PolicyAssist.

Defaults live here; each is overridable at process start via the
matching environment variable. Values are read once at import time.

See plan-policyassist.md sections 3 and 4 for provenance.
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


HISTORY_MAX_TURNS: int = _int_env("HISTORY_MAX_TURNS", 10)
MAX_QUESTION_LENGTH: int = _int_env("MAX_QUESTION_LENGTH", 500)
LLM_TIMEOUT_SECONDS: int = _int_env("LLM_TIMEOUT_SECONDS", 30)
LLM_MAX_RETRIES: int = _int_env("LLM_MAX_RETRIES", 3)
EVAL_PASS_THRESHOLD: float = _float_env("EVAL_PASS_THRESHOLD", 0.85)


__all__ = [
    "EVAL_PASS_THRESHOLD",
    "HISTORY_MAX_TURNS",
    "LLM_MAX_RETRIES",
    "LLM_TIMEOUT_SECONDS",
    "MAX_QUESTION_LENGTH",
]
