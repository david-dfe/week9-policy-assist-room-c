"""Integration tests for session-scoped history in policyassist.app.

These tests never call the real LLM — we monkeypatch policyassist.app.llm
to return a canned response, so we exercise the session/history path
end-to-end without cost or network.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest


class _StubMessage:
    def __init__(self, text: str) -> None:
        self.content = text
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 5}


class _StubLLM:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any]) -> _StubMessage:
        self.calls.append(messages)
        return _StubMessage("stub-answer")


@pytest.fixture
def app_and_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, _StubLLM]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret-not-a-real-secret")
    monkeypatch.setenv("POLICYASSIST_HISTORY_ROOT", str(tmp_path))
    # Ensure HISTORY_MAX_TURNS is at its default (10). Reload both config
    # and history so any stale binding from prior test modules is cleared.
    monkeypatch.delenv("HISTORY_MAX_TURNS", raising=False)

    import policyassist.config
    import policyassist.history

    importlib.reload(policyassist.config)
    importlib.reload(policyassist.history)

    import policyassist.app

    importlib.reload(policyassist.app)

    stub = _StubLLM()
    monkeypatch.setattr(policyassist.app, "llm", stub)

    policyassist.app.app.config["TESTING"] = True
    return policyassist.app.app, stub


def test_cookie_set_on_first_visit(app_and_store: tuple[Any, _StubLLM]) -> None:
    app, _ = app_and_store
    with app.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        # Flask sets the session cookie on the response.
        assert any("session" in c for c in response.headers.getlist("Set-Cookie"))


def test_two_clients_have_isolated_histories(
    app_and_store: tuple[Any, _StubLLM],
) -> None:
    app, _ = app_and_store
    # Two clients cannot share a nested ``with`` block: Flask's per-client
    # request-context teardown pops in the wrong order and raises
    # LookupError. Sequential blocks give each client its own scope.
    c1 = app.test_client()
    c2 = app.test_client()
    c1.get("/")
    c2.get("/")
    c1.post("/ask", json={"question": "alice-q"})
    c2.post("/ask", json={"question": "bob-q"})

    page_a = c1.get("/").get_data(as_text=True)
    page_b = c2.get("/").get_data(as_text=True)

    assert "alice-q" in page_a and "bob-q" not in page_a
    assert "bob-q" in page_b and "alice-q" not in page_b


def test_history_persists_across_requests_same_client(
    app_and_store: tuple[Any, _StubLLM],
) -> None:
    app, _ = app_and_store
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": "first"})
        client.post("/ask", json={"question": "second"})
        page = client.get("/").get_data(as_text=True)
    assert "first" in page and "second" in page


def test_context_trimmed_to_history_max_turns(
    app_and_store: tuple[Any, _StubLLM], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, stub = app_and_store
    # Fill more than N turns; final call's context should be trimmed.
    with app_and_store[0].test_client() as client:
        client.get("/")
        for i in range(15):
            client.post("/ask", json={"question": f"q{i}"})

    # Last invoke: 1 SystemMessage + up to HISTORY_MAX_TURNS * 2 chat messages + 1 latest human
    from policyassist.config import HISTORY_MAX_TURNS

    last_call = stub.calls[-1]
    # First is SystemMessage; last is HumanMessage("q14"); middle is the trimmed history.
    assert len(last_call) == 1 + HISTORY_MAX_TURNS * 2 + 1
