"""Tests for policyassist.history.HistoryStore."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import policyassist.config
import policyassist.history


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HISTORY_MAX_TURNS",):
        monkeypatch.delenv(var, raising=False)
    importlib.reload(policyassist.config)


def test_isolated_sessions_do_not_share_history(tmp_path: Path) -> None:
    store = policyassist.history.HistoryStore(tmp_path)
    store.append("sid-a", "q1", "a1")
    store.append("sid-b", "qX", "aX")

    assert store.raw("sid-a") == [{"question": "q1", "answer": "a1"}]
    assert store.raw("sid-b") == [{"question": "qX", "answer": "aX"}]


def test_history_persists_across_store_instances(tmp_path: Path) -> None:
    policyassist.history.HistoryStore(tmp_path).append("sid", "q1", "a1")
    fresh = policyassist.history.HistoryStore(tmp_path)
    assert fresh.raw("sid") == [{"question": "q1", "answer": "a1"}]


def test_get_context_trims_to_history_max_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HISTORY_MAX_TURNS", "3")
    importlib.reload(policyassist.config)
    importlib.reload(policyassist.history)

    store = policyassist.history.HistoryStore(tmp_path)
    for i in range(5):
        store.append("sid", f"q{i}", f"a{i}")

    ctx = store.get_context("sid")
    assert len(ctx) == 3
    assert ctx[0] == {"question": "q2", "answer": "a2"}
    assert ctx[-1] == {"question": "q4", "answer": "a4"}


def test_get_context_empty_for_unknown_session(tmp_path: Path) -> None:
    store = policyassist.history.HistoryStore(tmp_path)
    assert store.get_context("never-seen") == []


def test_get_context_returns_all_when_under_limit(tmp_path: Path) -> None:
    store = policyassist.history.HistoryStore(tmp_path)
    store.append("sid", "q1", "a1")
    store.append("sid", "q2", "a2")
    assert store.get_context("sid") == [
        {"question": "q1", "answer": "a1"},
        {"question": "q2", "answer": "a2"},
    ]


def test_session_id_with_path_separator_is_rejected(tmp_path: Path) -> None:
    store = policyassist.history.HistoryStore(tmp_path)
    with pytest.raises(ValueError):
        store.append("../evil", "q", "a")
    with pytest.raises(ValueError):
        store.get_context("../evil")
