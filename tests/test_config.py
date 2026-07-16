"""Tests for policyassist.config.

The config module reads environment variables at import time. Tests use
importlib.reload to re-read after monkeypatching the environment. The
autouse fixture clears every managed env var before each test so results
are independent of the shell environment.
"""

from __future__ import annotations

import importlib

import pytest

import policyassist.config

_MANAGED = (
    "HISTORY_MAX_TURNS",
    "MAX_QUESTION_LENGTH",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "EVAL_PASS_THRESHOLD",
)


@pytest.fixture(autouse=True)
def _reload_with_clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _MANAGED:
        monkeypatch.delenv(var, raising=False)
    importlib.reload(policyassist.config)


def test_history_max_turns_default() -> None:
    assert policyassist.config.HISTORY_MAX_TURNS == 10


def test_history_max_turns_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HISTORY_MAX_TURNS", "25")
    importlib.reload(policyassist.config)
    assert policyassist.config.HISTORY_MAX_TURNS == 25


def test_max_question_length_default() -> None:
    assert policyassist.config.MAX_QUESTION_LENGTH == 500


def test_max_question_length_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_QUESTION_LENGTH", "1000")
    importlib.reload(policyassist.config)
    assert policyassist.config.MAX_QUESTION_LENGTH == 1000


def test_llm_timeout_seconds_default() -> None:
    assert policyassist.config.LLM_TIMEOUT_SECONDS == 30


def test_llm_timeout_seconds_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
    importlib.reload(policyassist.config)
    assert policyassist.config.LLM_TIMEOUT_SECONDS == 60


def test_llm_max_retries_default() -> None:
    assert policyassist.config.LLM_MAX_RETRIES == 3


def test_llm_max_retries_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    importlib.reload(policyassist.config)
    assert policyassist.config.LLM_MAX_RETRIES == 5


def test_eval_pass_threshold_default() -> None:
    assert pytest.approx(0.85) == policyassist.config.EVAL_PASS_THRESHOLD


def test_eval_pass_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_PASS_THRESHOLD", "0.95")
    importlib.reload(policyassist.config)
    assert pytest.approx(0.95) == policyassist.config.EVAL_PASS_THRESHOLD


def test_empty_string_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HISTORY_MAX_TURNS", "")
    importlib.reload(policyassist.config)
    assert policyassist.config.HISTORY_MAX_TURNS == 10
