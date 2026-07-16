"""Tests for Slice D (input validation) and Slice E (error surfacing) on /ask.

Validation guards run BEFORE any LLM interaction, so tests here don't
need the stub LLM to be called for the 400 cases -- but we still stub
it so a bug that lets validation fall through won't hit the network.

Error-surfacing tests raise anthropic exceptions from the stub LLM and
assert the HTTP status + JSON body the handler returns to the browser.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest


class _StubMessage:
    def __init__(self, text: str = "stub-answer") -> None:
        self.content = text
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 5}


class _StubLLM:
    """Stub with configurable behaviour: return a canned reply or raise."""

    def __init__(self) -> None:
        self.call_count = 0
        self.exc: BaseException | None = None

    def invoke(self, messages: list[Any]) -> _StubMessage:
        self.call_count += 1
        if self.exc is not None:
            raise self.exc
        return _StubMessage()


@pytest.fixture
def app_and_stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, _StubLLM]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret-not-a-real-secret")
    monkeypatch.setenv("POLICYASSIST_HISTORY_ROOT", str(tmp_path))
    monkeypatch.delenv("MAX_QUESTION_LENGTH", raising=False)
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)

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


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _dummy_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_dummy_request())


# ---------------------------------------------------------------------------
# Slice D -- input validation
# ---------------------------------------------------------------------------


def test_non_json_body_returns_400(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, stub = app_and_stub
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", data="not-json", content_type="text/plain")
    assert res.status_code == 400
    assert "JSON" in res.get_json()["error"]
    assert stub.call_count == 0


def test_missing_question_returns_400(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, stub = app_and_stub
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"not_question": "x"})
    assert res.status_code == 400
    assert "question" in res.get_json()["error"]
    assert stub.call_count == 0


def test_non_string_question_returns_400(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, stub = app_and_stub
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": 42})
    assert res.status_code == 400
    assert "string" in res.get_json()["error"]
    assert stub.call_count == 0


def test_empty_question_returns_400(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, stub = app_and_stub
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "   "})
    assert res.status_code == 400
    assert "empty" in res.get_json()["error"]
    assert stub.call_count == 0


def test_question_exceeds_max_length_returns_400(
    app_and_stub: tuple[Any, _StubLLM],
) -> None:
    app, stub = app_and_stub
    from policyassist.config import MAX_QUESTION_LENGTH

    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "x" * (MAX_QUESTION_LENGTH + 1)})
    assert res.status_code == 400
    assert str(MAX_QUESTION_LENGTH) in res.get_json()["error"]
    assert stub.call_count == 0


def test_valid_question_succeeds(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, _ = app_and_stub
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "how are welfare checks logged?"})
    assert res.status_code == 200
    assert res.get_json()["answer"] == "stub-answer"


def test_validation_does_not_create_session(app_and_stub: tuple[Any, _StubLLM]) -> None:
    """A malformed request must not churn the session cookie."""
    app, _ = app_and_stub
    with app.test_client() as client:
        res = client.post("/ask", data="not-json", content_type="text/plain")
    assert res.status_code == 400
    # No session cookie should be set on a rejected request.
    set_cookies = res.headers.getlist("Set-Cookie")
    assert not any("session" in c for c in set_cookies)


# ---------------------------------------------------------------------------
# Slice E -- error surfacing
# ---------------------------------------------------------------------------


def test_apitimeout_returns_504_and_body_carries_error(
    app_and_stub: tuple[Any, _StubLLM],
) -> None:
    app, stub = app_and_stub
    stub.exc = anthropic.APITimeoutError(request=_dummy_request())
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})
    assert res.status_code == 504
    body = res.get_json()
    assert "error" in body
    assert body["error"]  # non-empty


def test_apiconnection_returns_502(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, stub = app_and_stub
    stub.exc = anthropic.APIConnectionError(request=_dummy_request())
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})
    assert res.status_code == 502
    assert "error" in res.get_json()


def test_apistatuserror_returns_502(app_and_stub: tuple[Any, _StubLLM]) -> None:
    app, stub = app_and_stub
    stub.exc = anthropic.APIStatusError("boom", response=_dummy_response(500), body=None)
    with app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})
    assert res.status_code == 502
    assert "error" in res.get_json()


def test_generic_exception_falls_through_to_500(
    app_and_stub: tuple[Any, _StubLLM],
) -> None:
    app, stub = app_and_stub
    stub.exc = RuntimeError("something else entirely")
    with app.test_client() as client:
        client.get("/")
        # Flask's test client re-raises unhandled exceptions unless we
        # disable exception propagation.
        app.config["TESTING"] = False
        app.config["PROPAGATE_EXCEPTIONS"] = False
        res = client.post("/ask", json={"question": "hi"})
    assert res.status_code == 500
