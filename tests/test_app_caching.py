"""Tests for Slice C: prompt caching + monitoring adapter."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest


class _StubMessage:
    def __init__(self, usage_metadata: dict[str, Any] | None) -> None:
        self.content = "stub-answer"
        self.usage_metadata = usage_metadata


class _StubLLM:
    def __init__(self, response: _StubMessage) -> None:
        self._response = response
        self.received_messages: list[Any] = []

    def invoke(self, messages: list[Any]) -> _StubMessage:
        self.received_messages = messages
        return self._response


@pytest.fixture
def app_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("POLICYASSIST_HISTORY_ROOT", str(tmp_path))

    import policyassist.app

    importlib.reload(policyassist.app)
    policyassist.app.app.config["TESTING"] = True
    return policyassist.app


def test_system_prompt_block_carries_cache_control(app_module: Any) -> None:
    block = app_module.SYSTEM_PROMPT_BLOCK
    assert isinstance(block, dict)
    assert block["type"] == "text"
    assert block["cache_control"] == {"type": "ephemeral"}
    assert "BORDER FORCE OPERATIONAL MANUAL" in block["text"]


def test_llm_receives_content_block_system_message(
    app_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubLLM(
        _StubMessage(
            {
                "input_tokens": 100,
                "output_tokens": 5,
                "input_token_details": {"cache_read": 0, "cache_creation": 100},
            }
        )
    )
    monkeypatch.setattr(app_module, "llm", stub)

    with app_module.app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": "hi"})

    system_msg = stub.received_messages[0]
    # SystemMessage.content should be a list with one block carrying cache_control.
    assert isinstance(system_msg.content, list)
    assert len(system_msg.content) == 1
    assert system_msg.content[0]["cache_control"] == {"type": "ephemeral"}


def test_hoist_cache_metrics_moves_nested_field_to_top_level(app_module: Any) -> None:
    response = _StubMessage(
        {
            "input_tokens": 100,
            "output_tokens": 5,
            "input_token_details": {"cache_read": 1402, "cache_creation": 0},
        }
    )
    app_module._hoist_cache_metrics(response)
    assert response.usage_metadata["cache_read_input_tokens"] == 1402
    assert response.usage_metadata["cache_creation_input_tokens"] == 0


def test_hoist_cache_metrics_preserves_top_level_when_already_set(
    app_module: Any,
) -> None:
    response = _StubMessage(
        {
            "input_tokens": 100,
            "output_tokens": 5,
            "cache_read_input_tokens": 999,  # already at top level (native SDK shape)
            "input_token_details": {"cache_read": 111, "cache_creation": 0},
        }
    )
    app_module._hoist_cache_metrics(response)
    # Native SDK top-level value wins; do NOT overwrite.
    assert response.usage_metadata["cache_read_input_tokens"] == 999


def test_hoist_cache_metrics_no_op_on_missing_usage(app_module: Any) -> None:
    response = _StubMessage(None)
    app_module._hoist_cache_metrics(response)  # must not raise
    assert response.usage_metadata is None


def test_hoist_cache_metrics_no_op_when_no_nested_details(app_module: Any) -> None:
    response = _StubMessage({"input_tokens": 100, "output_tokens": 5})
    app_module._hoist_cache_metrics(response)
    # No nested fields to hoist; no keys added.
    assert "cache_read_input_tokens" not in response.usage_metadata
