"""Tests for Slice F: retries + timeouts around llm.invoke().

The retry loop lives inside `traced_llm_call` (one outer span records
the final outcome). We stub `llm.invoke` with a scripted sequence of
outcomes and assert:

- transient errors are retried and eventually succeed;
- persistent transient errors give up after LLM_MAX_RETRIES;
- non-retryable 4xx errors (BadRequestError -> 400) propagate immediately.

Retries use a jittered exponential wait -- to keep tests fast we
monkeypatch the wait strategy on the app module to a no-op via a
minimum wait cap of zero. Tests must run in well under a second.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest


class _StubMessage:
    def __init__(self) -> None:
        self.content = "stub-answer"
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 5}


class _ScriptedLLM:
    """Raises the next exception in ``script`` on each call; None means success."""

    def __init__(self, script: list[BaseException | None]) -> None:
        self._script = list(script)
        self.call_count = 0

    def invoke(self, messages: list[Any]) -> _StubMessage:
        self.call_count += 1
        outcome = self._script.pop(0) if self._script else None
        if outcome is not None:
            raise outcome
        return _StubMessage()


def _dummy_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _dummy_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_dummy_request())


@pytest.fixture
def app_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret-not-a-real-secret")
    monkeypatch.setenv("POLICYASSIST_HISTORY_ROOT", str(tmp_path))
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)

    import policyassist.config
    import policyassist.history

    importlib.reload(policyassist.config)
    importlib.reload(policyassist.history)

    import policyassist.app

    importlib.reload(policyassist.app)

    # Zero-wait retry so the suite stays fast. The module exposes a
    # ``_RETRY_WAIT`` hook that we override; production keeps the
    # jittered exponential wait.
    from tenacity import wait_none

    monkeypatch.setattr(policyassist.app, "_RETRY_WAIT", wait_none())

    policyassist.app.app.config["TESTING"] = True
    return policyassist.app


def test_transient_apiconnection_retries_and_eventually_succeeds(
    app_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _ScriptedLLM([anthropic.APIConnectionError(request=_dummy_request()), None])
    monkeypatch.setattr(app_module, "llm", stub)

    with app_module.app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})

    assert res.status_code == 200
    assert res.get_json()["answer"] == "stub-answer"
    assert stub.call_count == 2  # one failure, one success


def test_persistent_apiconnection_gives_up_after_max_retries(
    app_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from policyassist.config import LLM_MAX_RETRIES

    stub = _ScriptedLLM(
        [anthropic.APIConnectionError(request=_dummy_request())] * (LLM_MAX_RETRIES + 5)
    )
    monkeypatch.setattr(app_module, "llm", stub)

    with app_module.app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})

    assert res.status_code == 502
    assert stub.call_count == LLM_MAX_RETRIES


def test_ratelimit_is_retried(app_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _ScriptedLLM(
        [
            anthropic.RateLimitError("429", response=_dummy_response(429), body=None),
            None,
        ]
    )
    monkeypatch.setattr(app_module, "llm", stub)

    with app_module.app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})

    assert res.status_code == 200
    assert stub.call_count == 2


def test_400_error_not_retried(app_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _ScriptedLLM(
        [
            anthropic.BadRequestError("bad prompt", response=_dummy_response(400), body=None),
        ]
    )
    monkeypatch.setattr(app_module, "llm", stub)

    with app_module.app.test_client() as client:
        client.get("/")
        res = client.post("/ask", json={"question": "hi"})

    # BadRequestError is an APIStatusError -> mapped to 502 by Slice E.
    # The critical assertion is that it was NOT retried.
    assert stub.call_count == 1
    assert res.status_code == 502
