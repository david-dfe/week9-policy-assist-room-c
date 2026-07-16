# Wave 1B — Slice C: Prompt Caching

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Mark the ~1200-token operational-manual system prompt with `cache_control={"type":"ephemeral"}` so Anthropic caches it across all requests. Ensure the cache-hit signal reaches the OTel span so SigNoz shows `cache_read_input_tokens > 0` on repeat calls.

**Architecture:** The 2026-07-16 C1 spike (`/tmp/cache_control_spike.py`) confirmed `langchain-anthropic` propagates `cache_control` when the SystemMessage is constructed with a content-block: `SystemMessage(content=[{"type":"text","text":..., "cache_control":{"type":"ephemeral"}}])`. LangChain surfaces the resulting cache read at `response.usage_metadata["input_token_details"]["cache_read"]` — **not** at the top-level `cache_read_input_tokens` field that `monitoring/cost.py:usage_from_response` currently reads. Slice C ships a small adapter in `policyassist/app.py` that lifts the nested field to the top-level key before calling `span.record_usage()`. Fixing `monitoring/cost.py` itself is out of scope per plan-policyassist.md non-goals; a follow-up `fix:` PR against `monitoring/` is captured in ai-log at merge time.

**Tech Stack:** langchain-anthropic 1.4 · langchain-core 1.2 · Anthropic ephemeral cache · policyassist.app.

## Global Constraints

- Branch: `feat/policyassist-caching`. Rebase base: `origin/main` at dispatch time. **Will rebase onto the merged Slice A+B commit before opening for merge.**
- Python 3.12; venv at `~/.cache/policyassist-venv`.
- Same Ruff/mypy/pytest/bandit expectations as Wave 1A.
- Conventional Commits. Never `--no-verify`. No Claude co-author trailers.
- **Files in scope:** `policyassist/app.py` (SystemMessage construction + monitoring adapter), `tests/test_app_caching.py` (new).
- **Files OUT of scope:** `monitoring/**`, `signoz/**`, `prices.yaml`, `plan-policyassist.md`, `CLAUDE.md`, `docs/**`, `ai-log.md`, `policyassist/config.py`, `policyassist/history.py` (owned by Slice A).
- **Rebase risk:** Slice A+B also touches `policyassist/app.py:46-52` (SystemMessage construction). When rebasing, expect one conflict there — resolve by wrapping A's `SystemMessage(content=SYSTEM_PROMPT)` in the content-block form with `cache_control`.

## File Structure

**Created:**
- `tests/test_app_caching.py` — verifies the SystemMessage carries the `cache_control` marker in the content-block form, and that a stub LangChain response with a nested `input_token_details.cache_read` gets normalised to top-level `cache_read_input_tokens` before `span.record_usage`.

**Modified:**
- `policyassist/app.py` — SystemMessage constructed as a content-block with `cache_control`; new `_hoist_cache_metrics(response)` helper called before `span.record_usage()`.

---

## Task 1: Create the worktree

- [ ] **Step 1: Branch from origin/main**

```bash
git fetch origin
git worktree add ../policyAssistRoom3-caching -b feat/policyassist-caching origin/main
cd ../policyAssistRoom3-caching
git status --short
```

Expected: clean worktree on `feat/policyassist-caching` off latest `origin/main`.

---

## Task 2: RED — write `tests/test_app_caching.py`

**Interfaces produced by Task 3:**
- `policyassist.app.SYSTEM_PROMPT_BLOCK` — a `dict` of shape `{"type":"text", "text":..., "cache_control":{"type":"ephemeral"}}` (module-level constant).
- `policyassist.app._hoist_cache_metrics(response) -> None` — mutates `response.usage_metadata` in place to hoist nested cache fields to the top level so `monitoring/cost.py` picks them up.

- [ ] **Step 1: Create the test file**

```python
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
```

- [ ] **Step 2: Run to confirm RED**

```bash
~/.cache/policyassist-venv/bin/pytest tests/test_app_caching.py -v
```

Expected: multiple failures — `SYSTEM_PROMPT_BLOCK` and `_hoist_cache_metrics` don't exist yet.

---

## Task 3: GREEN — update `policyassist/app.py`

- [ ] **Step 1: Extract `SYSTEM_PROMPT_BLOCK` and construct SystemMessage from it**

Locate the current SystemMessage construction. If Slice A has merged, it is inside `ask()`:

```python
    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=SYSTEM_PROMPT)
    ]
```

Add above the `SYSTEM_PROMPT` string, at module scope, a new content-block constant:

```python
SYSTEM_PROMPT_BLOCK: dict[str, Any] = {
    "type": "text",
    "text": SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"},
}
```

Then change the SystemMessage construction inside `ask()` to:

```python
    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=[SYSTEM_PROMPT_BLOCK])
    ]
```

(The rest of `ask()` — HumanMessage/AIMessage loop, `traced_llm_call`, history append — is unchanged.)

- [ ] **Step 2: Add the monitoring adapter helper**

Add just before `def _ensure_sid()`:

```python
def _hoist_cache_metrics(response: Any) -> None:
    """Copy nested langchain-anthropic cache metrics to the top level.

    langchain-anthropic surfaces cache reads under
    ``usage_metadata["input_token_details"]["cache_read"]``, but
    ``monitoring/cost.py:usage_from_response`` looks for
    ``cache_read_input_tokens`` at the top level. Copy across, but do
    NOT overwrite a top-level value already set by the native SDK shape.
    """
    meta = getattr(response, "usage_metadata", None)
    if not isinstance(meta, dict):
        return
    details = meta.get("input_token_details")
    if not isinstance(details, dict):
        return
    for src, dst in (
        ("cache_read", "cache_read_input_tokens"),
        ("cache_creation", "cache_creation_input_tokens"),
    ):
        if dst in meta:
            continue
        val = details.get(src)
        if val is None:
            continue
        meta[dst] = int(val)
```

- [ ] **Step 3: Call the adapter inside `ask()` between invoke and record_usage**

Change:

```python
    with traced_llm_call(model=MODEL) as span:
        response = llm.invoke(messages)
        span.record_usage(response)
```

to:

```python
    with traced_llm_call(model=MODEL) as span:
        response = llm.invoke(messages)
        _hoist_cache_metrics(response)
        span.record_usage(response)
```

- [ ] **Step 4: Run tests, confirm GREEN**

```bash
~/.cache/policyassist-venv/bin/pytest tests/test_app_caching.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Full suite still green**

```bash
~/.cache/policyassist-venv/bin/pytest
```

Expected: all pass, monitoring coverage ≥ 80%.

---

## Task 4: Local CI-equivalent

Run:
```bash
~/.cache/policyassist-venv/bin/ruff check .
~/.cache/policyassist-venv/bin/ruff format --check .
~/.cache/policyassist-venv/bin/mypy monitoring
~/.cache/policyassist-venv/bin/bandit -r monitoring policyassist -c pyproject.toml
~/.cache/policyassist-venv/bin/pre-commit run gitleaks --all-files
```

All expected: clean.

---

## Task 5: Commit and rebase-if-needed

- [ ] **Step 1: Commit**

```bash
git add policyassist/app.py tests/test_app_caching.py
~/.cache/policyassist-venv/bin/pre-commit run --from-ref origin/main --to-ref HEAD
git commit -m "feat(policyassist): cache system prompt via cache_control

Marks the operational-manual portion of the system prompt with
cache_control={\"type\":\"ephemeral\"} so Anthropic caches it across
requests. Cuts input-token cost on the manual portion by ~90% after
the first request in each 5-minute window.

Also adds _hoist_cache_metrics(), a small adapter that copies
langchain-anthropic's nested input_token_details.cache_read /
cache_creation fields up to the top-level cache_read_input_tokens /
cache_creation_input_tokens keys that monitoring/cost.py reads.
Slice-scoped shim -- a follow-up fix: PR against monitoring/ should
teach usage_from_response about the nested shape directly.
"
```

- [ ] **Step 2: If Slice A+B has landed on main since branch time, rebase**

```bash
git fetch origin
git rebase origin/main
```

Expected conflict: `policyassist/app.py:ask()` — the SystemMessage construction. Resolve by keeping BOTH:
- Slice A's session-scoped message loop
- Slice C's content-block SystemMessage with `cache_control`

Final `ask()` shape (excerpt):

```python
    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=[SYSTEM_PROMPT_BLOCK])
    ]
    for entry in history_store.get_context(sid):
        messages.append(HumanMessage(content=entry["question"]))
        messages.append(AIMessage(content=entry["answer"]))
    messages.append(HumanMessage(content=question))

    with traced_llm_call(model=MODEL) as span:
        response = llm.invoke(messages)
        _hoist_cache_metrics(response)
        span.record_usage(response)
```

Re-run:
```bash
~/.cache/policyassist-venv/bin/pytest
~/.cache/policyassist-venv/bin/ruff check .
~/.cache/policyassist-venv/bin/mypy monitoring
```

All must be green post-rebase before the force-push.

- [ ] **Step 3: Force-with-lease and open PR**

```bash
git push --force-with-lease -u origin feat/policyassist-caching
gh pr create --base main --title "feat(policyassist): cache system prompt via cache_control" --body "$(cat <<'EOF'
## Summary

Wave 1 Slice C from plan-policyassist.md.

- Marks the ~1200-token operational-manual portion of `SYSTEM_PROMPT` with `cache_control={"type":"ephemeral"}` so Anthropic caches it across all requests.
- The C1 spike (2026-07-16) confirmed `langchain-anthropic` propagates the marker; second call surfaces `cache_read=1402` under `usage_metadata.input_token_details.cache_read`.
- Adds `_hoist_cache_metrics()` in `policyassist/app.py` to copy those nested cache fields up to `cache_read_input_tokens` / `cache_creation_input_tokens` at the top level, where `monitoring/cost.py:usage_from_response` reads them. Native-SDK top-level values are preserved (never overwritten).

## Verification

- [x] `pytest tests/test_app_caching.py -v` — all pass (6 tests)
- [x] Full suite green
- [x] `ruff check .`, `mypy monitoring`, `bandit`, `gitleaks` — all clean
- [ ] Reviewer: hit `/ask` twice with identical questions; SigNoz shows a span with `gen_ai.usage.cache_read_input_tokens > 0` on the second call.

## Follow-up (out of scope for this PR)

`monitoring/cost.py:usage_from_response` should be widened to read from `input_token_details.cache_read` directly, so no per-app adapter is needed. Recommend a small `fix: monitoring reads LangChain nested cache fields` PR.

## Rebase notes

Rebased on top of PR #<A+B PR number> to reconcile the SystemMessage construction site. Conflict resolved by keeping Slice A's session-scoped message loop and applying Slice C's content-block form + `cache_control`.
EOF
)"
```

Expected: PR URL. Report to orchestrator.

---

## Task 6: HUMAN CHECKPOINT

Orchestrator pauses. Reviewer merges via GitHub UI after confirming SigNoz cache-hit visibility on the running app.

---

## Failure modes

- **Cache doesn't propagate after all:** the C1 spike ran against `langchain-anthropic 1.4.8`. If a version bump in `pyproject.toml` breaks propagation, re-run `/tmp/cache_control_spike.py` (still in `/tmp` from Wave 0). If it fails, fall back to D2 (native Anthropic SDK bypass of LangChain for the `/ask` call). D2 rewrite is roughly half a day; owner escalates.
- **Rebase collision beyond SystemMessage:** if Slice A+B moved the LLM invocation elsewhere, apply `_hoist_cache_metrics` at whichever new call site exists. Preserve `traced_llm_call` context manager boundaries.
- **`bandit` complaining about `dict` mutation on external response:** the adapter mutates a dict that is our own response wrapper (`response.usage_metadata` is documented as mutable by langchain-anthropic). If bandit flags this, add a `# nosec` narrow comment with rule id; do not disable bandit wholesale.

---

## Self-review

**Spec coverage:**
- plan-policyassist.md Slice C "Mark the system prompt with cache_control" → Task 3 Step 1.
- plan-policyassist.md Slice C "Ensure the cached block is at the start of the messages list and never mutated between requests" → Task 3: SYSTEM_PROMPT_BLOCK is a module-level constant, referenced by every call.
- plan-policyassist.md Slice C "Confirm record_usage() picks up cache_read_input_tokens" → Task 3 Step 2 + Task 2 tests 3–6.
- plan-policyassist.md Slice C decision D1 (LangChain path) → confirmed by 2026-07-16 spike; locked in ai-log.

**Placeholder scan:** no TBDs; every code block is complete.

**Type consistency:** `_hoist_cache_metrics(response) -> None` signature stable between plan interfaces block and Task 3 implementation. `SYSTEM_PROMPT_BLOCK` type `dict[str, Any]` matches usage.

No issues found.

---

## Execution Handoff

Single subagent; use `subagent-driven-development`. This slice is small (~30 LOC of app changes + 6 tests) and should complete inside one focused session.
