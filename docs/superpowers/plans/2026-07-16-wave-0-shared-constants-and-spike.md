# PolicyAssist Wave 0 + Wave 1 Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the shared config module and workflow design spec in one PR, then run a 60-min spike to decide whether Slice C uses LangChain (`D1`) or the native Anthropic SDK (`D2`).

**Architecture:** A new `policyassist/config.py` module exposes five constants read from environment variables at import time, with committed defaults. The already-drafted design spec at `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md` rides in the same branch as a `docs:` commit. The spike is a throwaway script at `/tmp/cache_control_spike.py` that instantiates `ChatAnthropic`, sends two identical requests with `cache_control` marked on the SystemMessage, and asserts `cache_read_input_tokens > 0` on the second call.

**Tech Stack:** Python 3.12 · Flask 3 · langchain-anthropic 1.4 · pytest 8 · ruff 0.8 · mypy 1.13 strict · pre-commit 4 · gh CLI · Conventional Commits (commitlint).

## Global Constraints

- Python 3.12; venv at `~/.cache/policyassist-venv` (repo is on SMB — no in-tree `.venv`; `uv` not installed).
- Ruff line-length 100, target-version `py312`; selects `E, F, W, I, N, UP, B, C4, SIM, RUF` (per `pyproject.toml`).
- Mypy `strict = true`; pre-commit excludes `tests/` from mypy but CI runs `mypy monitoring policyassist`.
- Pytest coverage `source = ["monitoring"]` (per `pyproject.toml`); `fail_under = 80`. `policyassist/config.py` is not measured for coverage, but tests are still required for quality.
- Conventional Commits enforced by `commitlint.config.cjs`; header ≤100 chars; no trailing period; type ∈ `feat, fix, chore, docs, refactor, test, ci, build, perf, revert`.
- pre-commit hooks (see `.pre-commit-config.yaml`): `no-commit-to-branch` blocks direct commits to `main`; `ruff --fix`, `ruff-format`, `mypy` (excluding `tests/` and `signoz/`), `gitleaks`, plus hygiene checks.
- **Never** `git commit --no-verify`. If a hook fails, fix the code (CLAUDE.md §1 rule 4).
- **No** `Co-Authored-By: Claude` trailer on any commit or PR body (CLAUDE.md §5 authorship rule).
- Rebase-and-merge only; `--force-with-lease` never bare `--force` (CLAUDE.md §4).
- Working tree currently has an untracked design spec at `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md` — it must land inside this PR.

---

## File Structure

**Created:**
- `policyassist/config.py` — five module-level constants, env-var-overridable at import time.
- `tests/test_config.py` — verifies defaults and env overrides for all five constants.

**Modified:** none.

**Already written, not yet committed (lands with this PR):**
- `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md`

**Throwaway (not committed):**
- `/tmp/cache_control_spike.py`

---

## Task 1: Ensure venv has dev tooling

**Files:** none (venv-only)

**Interfaces:**
- Consumes: existing venv at `~/.cache/policyassist-venv` with runtime deps installed.
- Produces: same venv, now also carrying `ruff, mypy, pytest, pytest-cov, bandit, pip-audit, pre-commit, types-PyYAML, types-requests`.

- [ ] **Step 1: Install dev tools into the venv**

Run:
```bash
~/.cache/policyassist-venv/bin/pip install \
  "ruff>=0.8" "mypy>=1.13" "pytest>=8.3" "pytest-cov>=6.0" \
  "bandit[toml]>=1.7" "pip-audit>=2.7" "pre-commit>=4.0" \
  "types-PyYAML" "types-requests"
```
Expected: `Successfully installed ...` line at the end.

- [ ] **Step 2: Install the pre-commit git hook**

Run from the repo root:
```bash
~/.cache/policyassist-venv/bin/pre-commit install
```
Expected: `pre-commit installed at .git/hooks/pre-commit`.

- [ ] **Step 3: Sanity check tools**

Run:
```bash
~/.cache/policyassist-venv/bin/ruff --version
~/.cache/policyassist-venv/bin/mypy --version
~/.cache/policyassist-venv/bin/pytest --version
```
Expected: version lines for each.

---

## Task 2: Create feature branch

**Files:** none (git only)

**Interfaces:**
- Consumes: `origin/main` at the latest SHA.
- Produces: local branch `chore/policyassist-shared-constants` checked out.

- [ ] **Step 1: Fetch and branch**

Run from the repo root:
```bash
git fetch origin
git checkout -b chore/policyassist-shared-constants origin/main
```
Expected: `Switched to a new branch 'chore/policyassist-shared-constants'`.

- [ ] **Step 2: Confirm untracked spec doc is still present**

Run:
```bash
git status --short
```
Expected output includes:
```
?? docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md
?? docs/superpowers/plans/2026-07-16-wave-0-shared-constants-and-spike.md
```

(Other untracked files like `monitoring-review.md`, `plan-policyassist.md`, `presentation/` may also appear; ignore them for this PR.)

---

## Task 3: RED — write `tests/test_config.py`

**Files:**
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `policyassist.config` module (not yet created).
- Produces: 11 tests that will fail at import time until Task 5 lands.

- [ ] **Step 1: Create the test file**

Create `tests/test_config.py` with exactly this content:

```python
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
    assert policyassist.config.EVAL_PASS_THRESHOLD == pytest.approx(0.85)


def test_eval_pass_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_PASS_THRESHOLD", "0.95")
    importlib.reload(policyassist.config)
    assert policyassist.config.EVAL_PASS_THRESHOLD == pytest.approx(0.95)


def test_empty_string_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HISTORY_MAX_TURNS", "")
    importlib.reload(policyassist.config)
    assert policyassist.config.HISTORY_MAX_TURNS == 10
```

---

## Task 4: Verify tests fail (RED confirmed)

**Files:** none

**Interfaces:**
- Consumes: `tests/test_config.py` from Task 3.
- Produces: proof the tests fail because the module doesn't exist yet.

- [ ] **Step 1: Run pytest against the new tests**

Run from repo root:
```bash
~/.cache/policyassist-venv/bin/pytest tests/test_config.py -v
```

Expected: **collection error** or **11 failures**, all reporting `ModuleNotFoundError: No module named 'policyassist.config'` (or equivalent import error).

---

## Task 5: GREEN — implement `policyassist/config.py`

**Files:**
- Create: `policyassist/config.py`

**Interfaces:**
- Consumes: `os.environ`.
- Produces: five module-level constants (`HISTORY_MAX_TURNS: int`, `MAX_QUESTION_LENGTH: int`, `LLM_TIMEOUT_SECONDS: int`, `LLM_MAX_RETRIES: int`, `EVAL_PASS_THRESHOLD: float`) with typed defaults and env-var overrides.

- [ ] **Step 1: Create the module**

Create `policyassist/config.py` with exactly this content:

```python
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
```

---

## Task 6: Verify tests pass (GREEN confirmed)

**Files:** none

**Interfaces:**
- Consumes: `policyassist/config.py` from Task 5.
- Produces: 11 green tests.

- [ ] **Step 1: Run pytest**

Run:
```bash
~/.cache/policyassist-venv/bin/pytest tests/test_config.py -v
```

Expected: `11 passed`.

- [ ] **Step 2: Run the whole suite to confirm nothing else broke**

Run:
```bash
~/.cache/policyassist-venv/bin/pytest
```

Expected: all tests pass; coverage report shows `monitoring/` at ≥80%.

---

## Task 7: Commit config module + tests

**Files:** stages `policyassist/config.py` and `tests/test_config.py`.

- [ ] **Step 1: Stage the two files**

Run:
```bash
git add policyassist/config.py tests/test_config.py
```

- [ ] **Step 2: Commit**

Run:
```bash
git commit -m "feat(policyassist): add shared config module

Introduces the five wave-0 constants read from environment variables
at import time, with tests covering defaults and overrides.

Constants: HISTORY_MAX_TURNS, MAX_QUESTION_LENGTH, LLM_TIMEOUT_SECONDS,
LLM_MAX_RETRIES, EVAL_PASS_THRESHOLD. See plan-policyassist.md sections
3 and 4."
```

Expected: pre-commit hooks run (ruff, ruff-format, mypy, gitleaks, hygiene). All pass. Commit lands on `chore/policyassist-shared-constants`.

- [ ] **Step 3: If any hook fails, fix inline and re-stage**

If ruff auto-fixed something, `git add -u` the changes and re-run `git commit`. If mypy failed, fix the type annotation in `policyassist/config.py` and re-commit. Never `--no-verify`.

---

## Task 8: Commit the design spec doc

**Files:** stages `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md` and `docs/superpowers/plans/2026-07-16-wave-0-shared-constants-and-spike.md`.

- [ ] **Step 1: Stage the docs**

Run:
```bash
git add docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md \
        docs/superpowers/plans/2026-07-16-wave-0-shared-constants-and-spike.md
```

- [ ] **Step 2: Commit**

Run:
```bash
git commit -m "docs: add policyassist hardening workflow design and wave 0 plan

Locks in the workflow orchestration pattern (deterministic DAG driven
by the main session, worker subagents in worktrees, four waves) and
records the two design decisions taken 2026-07-16: run a 60-min
langchain-anthropic cache_control spike; no pre-commit eval canary."
```

Expected: pre-commit hooks pass (docs-only diff; only hygiene hooks touch it). Commit lands.

---

## Task 9: Local CI-equivalent

**Files:** none

**Interfaces:**
- Consumes: the two commits from Tasks 7 and 8.
- Produces: proof CI will pass.

- [ ] **Step 1: Lint**

Run:
```bash
~/.cache/policyassist-venv/bin/ruff check .
```
Expected: `All checks passed!`.

- [ ] **Step 2: Format check**

Run:
```bash
~/.cache/policyassist-venv/bin/ruff format --check .
```
Expected: `X files already formatted`.

- [ ] **Step 3: Type check**

Run:
```bash
~/.cache/policyassist-venv/bin/mypy monitoring policyassist
```
Expected: `Success: no issues found`.

- [ ] **Step 4: Test suite with coverage**

Run:
```bash
~/.cache/policyassist-venv/bin/pytest
```
Expected: all tests pass; coverage on `monitoring/` ≥ 80%.

- [ ] **Step 5: Security scan**

Run:
```bash
~/.cache/policyassist-venv/bin/bandit -r monitoring policyassist -c pyproject.toml
```
Expected: `No issues identified.`.

- [ ] **Step 6: Dependency audit (best-effort)**

Run:
```bash
~/.cache/policyassist-venv/bin/pip-audit
```
Expected: `No known vulnerabilities found.` (or a clean report). If a pre-existing CVE surfaces from an unrelated dep, note it in the PR body but proceed — this branch does not add dependencies.

---

## Task 10: Push branch and open PR

**Files:** none (remote-only)

**Interfaces:**
- Consumes: local branch with two commits.
- Produces: remote branch and open PR against `main`.

- [ ] **Step 1: Push the branch**

Run:
```bash
git push -u origin chore/policyassist-shared-constants
```
Expected: `Branch 'chore/policyassist-shared-constants' set up to track 'origin/chore/policyassist-shared-constants'`.

- [ ] **Step 2: Open the PR via gh**

Run:
```bash
gh pr create \
  --base main \
  --title "chore: add shared config module and workflow design docs" \
  --body "$(cat <<'EOF'
## Summary

- Adds `policyassist/config.py` with the five constants that later slices (A–I) will read from: `HISTORY_MAX_TURNS`, `MAX_QUESTION_LENGTH`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `EVAL_PASS_THRESHOLD`. Each is env-overridable; defaults match `plan-policyassist.md` §3.
- Adds the design spec at `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md` and the wave-0 implementation plan at `docs/superpowers/plans/2026-07-16-wave-0-shared-constants-and-spike.md`.

## Why now

`plan-policyassist.md` §3 warns against scattering magic numbers across slices. Landing a shared module first eliminates the `MAX_QUESTION_LENGTH` collision between slices D and H before parallel work starts. The workflow spec locks in the two design decisions taken 2026-07-16: a 60-min `langchain-anthropic` `cache_control` propagation spike at Wave 1 start; no pre-commit eval canary.

## Test plan

- [x] `pytest tests/test_config.py -v` — 11 passed
- [x] `pytest` — full suite green, `monitoring/` coverage ≥ 80%
- [x] `ruff check .` — clean
- [x] `ruff format --check .` — clean
- [x] `mypy monitoring policyassist` — clean
- [x] `bandit -r monitoring policyassist` — clean
- [x] `pip-audit` — clean
- [ ] Reviewer confirms the two decisions in `docs/superpowers/specs/2026-07-16-...` match team intent before Wave 1 dispatches.
EOF
)"
```

Expected: PR URL printed to stdout. **Copy the URL** into the ai-log entry (Task 12).

---

## Task 11: HUMAN CHECKPOINT — pause until PR merges

- [ ] **Step 1: Post the PR URL in chat and stop**

The orchestrator (main session) reports the PR URL and pauses. The human reviews and rebase-merges via the GitHub UI.

- [ ] **Step 2: On merge, orchestrator appends an `ai-log.md` entry**

After the user confirms merge, the orchestrator prepends to `ai-log.md` (newest first, per CLAUDE.md §8):

```markdown
## 2026-07-16 HH:MM — Wave 0: shared constants + workflow design landed

**Author:** claude
**Branch / PR:** `chore/policyassist-shared-constants` — <PR URL>
**Type:** progress

Shipped `policyassist/config.py` with the five wave-0 constants
(HISTORY_MAX_TURNS, MAX_QUESTION_LENGTH, LLM_TIMEOUT_SECONDS,
LLM_MAX_RETRIES, EVAL_PASS_THRESHOLD) plus 11 tests, and the
workflow design spec at
`docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md`.
Two open decisions locked in:
- Slice C: run a 60-min langchain-anthropic cache_control
  propagation spike before dispatching Wave 1.
- Slice I: no pre-commit eval canary; evals via `workflow_dispatch`
  and pre-demo `run_evals.py` only.

Next: run the spike, then dispatch Wave 1 (A+B and C in worktrees).
```

The orchestrator commits the `ai-log.md` update on a tiny follow-up branch `docs/ai-log-wave-0` (single commit, docs type, rebase-merge). Alternatively, if the team prefers batching, the entry rides with the next feature PR — orchestrator asks user which.

---

## Task 12: Wave 1 spike — write `/tmp/cache_control_spike.py`

**Files:**
- Create: `/tmp/cache_control_spike.py` (throwaway; NOT committed to the repo).

**Interfaces:**
- Consumes: `ANTHROPIC_API_KEY` env var and the `~/.cache/policyassist-venv` venv.
- Produces: pass/fail signal for the C1 risk (`plan-policyassist.md:328`).

- [ ] **Step 1: Create the script**

Write to `/tmp/cache_control_spike.py`:

```python
#!/usr/bin/env python3
"""Spike: does langchain-anthropic propagate cache_control on SystemMessage?

Sends two identical requests with an ephemeral cache_control marker on
the SystemMessage. On the second call, cache_read_input_tokens should be
positive if the header actually reached Anthropic.

Cost cap: ~2000 input tokens per call × 2 calls = well under £0.01.

Result gates:
- PASS  → Slice C uses D1 (LangChain path), Slice F uses F2 (Tenacity).
- FAIL  → Slice C uses D2 (native Anthropic SDK), Slice F uses F1 (SDK retries).
"""

from __future__ import annotations

import os
import sys

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

MODEL = "claude-sonnet-4-5"

# Ephemeral cache needs ≥1024 input tokens; pad deterministically so the
# cache actually engages.
SYSTEM_TEXT = "PolicyAssist test system prompt. " * 200


def _system_message() -> SystemMessage:
    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": SYSTEM_TEXT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


def run() -> int:
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    llm = ChatAnthropic(model=MODEL, max_tokens=64)

    print(">>> First call (warm the cache)")
    r1 = llm.invoke([_system_message(), HumanMessage(content="Reply with just: OK.")])
    print("usage:", r1.usage_metadata)

    print(">>> Second call (expect cache read)")
    r2 = llm.invoke([_system_message(), HumanMessage(content="Reply with just: OK.")])
    print("usage:", r2.usage_metadata)

    read_1 = (r1.usage_metadata or {}).get("cache_read_input_tokens", 0)
    read_2 = (r2.usage_metadata or {}).get("cache_read_input_tokens", 0)

    print(f"\ncache_read first={read_1} second={read_2}")

    if read_2 and read_2 > 0:
        print("SPIKE PASS — langchain-anthropic propagates cache_control")
        print("Decision: Slice C=D1 (LangChain), Slice F=F2 (Tenacity)")
        return 0

    print("SPIKE FAIL — cache_control did not propagate through langchain-anthropic")
    print("Decision: Slice C=D2 (native Anthropic SDK), Slice F=F1 (SDK retries)")
    return 1


if __name__ == "__main__":
    sys.exit(run())
```

---

## Task 13: Run the spike

**Files:** none

- [ ] **Step 1: Execute against the real API**

Run:
```bash
set -a; source /home/lab-admin/Documents/readwrite-classroom/breakout-collaborations/week9/policyAssistRoom3/.env; set +a
~/.cache/policyassist-venv/bin/python /tmp/cache_control_spike.py
```

Expected: two `usage` lines, then either `SPIKE PASS` or `SPIKE FAIL` printed.

- [ ] **Step 2: Cost sanity check**

Confirm the total input tokens across both calls is under 10 000 (well under £0.01 at Sonnet 4.5 rates). If usage looks anomalous, stop and investigate before deciding.

---

## Task 14: Record spike outcome and lock C/F contracts

**Files:**
- Prep-only: draft ai-log entry to append after the next PR merges (do NOT modify `ai-log.md` on `main` outside a PR).

- [ ] **Step 1: Draft the ai-log entry**

Draft locally (paste into chat when handing back to the orchestrator):

```markdown
## 2026-07-16 HH:MM — C1 spike result: <PASS | FAIL>

**Author:** claude
**Branch / PR:** none — throwaway spike, `/tmp/cache_control_spike.py`
**Type:** decision

Ran the 60-min langchain-anthropic cache_control propagation spike. Second
call's `cache_read_input_tokens = <N>` (first call: <M>).

Locked contracts for Wave 1:
- Slice C: <D1 LangChain path | D2 native Anthropic SDK>
- Slice F: <F2 Tenacity | F1 SDK built-in retries>

Wave 1 dispatch unblocked.
```

- [ ] **Step 2: Update the workflow design spec if the spike failed**

If `SPIKE FAIL`, open a follow-up commit to `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md` §5 Decision 1 recording the D2 flip. Land as a `docs:` PR before Wave 1 dispatch. If `SPIKE PASS`, no update needed.

- [ ] **Step 3: Update the TaskList**

Mark tasks #8 and #9 completed. Task #10 (Wave 1 dispatch) is now unblocked; the orchestrator can plan and dispatch it.

---

## Failure modes

- **CI red on `chore/policyassist-shared-constants`:** fix on-branch, push, wait for CI. Two consecutive failures → invoke `superpowers:systematic-debugging` with the CI log.
- **pre-commit `no-commit-to-branch` fires:** you are on `main`. Return to Task 2 and create the branch.
- **`mypy monitoring policyassist` fails due to unrelated pre-existing error:** the fix should be scoped to `policyassist/config.py`. If a pre-existing mypy error surfaces, log it in the PR body but do not fix it in this branch — open a separate `fix:` PR.
- **Spike fails silently (no exception but `cache_read_input_tokens` is `None`/0 on both calls):** the SDK version may not surface the field. Upgrade `langchain-anthropic` in the venv temporarily and re-run before concluding. If it still fails, treat as SPIKE FAIL.
- **Spike token cost anomaly:** stop, investigate, do not proceed to Wave 1 until understood.

---

## Self-Review

**Spec coverage:**
- Design spec §5 Decision 1 (C1 spike) → covered by Tasks 12–14.
- Design spec §5 Decision 2 (no canary) → covered by explicit non-goal in Wave 0 tasks; will be enforced when Slice I plan is written.
- Design spec §11 critical files: `policyassist/config.py`, `tests/test_config.py` → Tasks 3, 5.
- Global constraints match `pyproject.toml`, `.pre-commit-config.yaml`, `commitlint.config.cjs`.

**Placeholder scan:** No TBDs, TODOs, or "fill in later" placeholders. Every code block is complete.

**Type consistency:** `_int_env` and `_float_env` used consistently; constant types match test assertions (`int` vs `pytest.approx(float)`).

No issues found; nothing to fix.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-wave-0-shared-constants-and-spike.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
