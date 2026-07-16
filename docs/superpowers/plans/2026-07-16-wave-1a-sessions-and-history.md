# Wave 1A — Slices A + B: Session Isolation and Bounded History

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the global `chat_log.json` with a per-session store keyed on a Flask signed-cookie session id, and trim conversation history to the last `HISTORY_MAX_TURNS` turns before every LLM call.

**Architecture:** A new `policyassist/history.py` module exposes a `HistoryStore` class with `get_context(sid)` (returns trimmed message list) and `append(sid, question, answer)` methods. `HistoryStore` writes JSON files to `policyassist/chat_log/<sid>.json` under an `fcntl.flock` write lock. `policyassist/app.py` reads its session id from Flask's signed-cookie session (`session["sid"]`), assigning a `uuid4()` on first visit. Trimming happens inside `HistoryStore.get_context()` using `policyassist.config.HISTORY_MAX_TURNS`, so `/ask` never sees the strategy.

**Tech Stack:** Flask 3 signed sessions · `uuid`, `fcntl`, `json` stdlib · `policyassist.config` (from Wave 0) · pytest.

## Global Constraints

- Branch: `feat/policyassist-sessions`. Rebase base: `origin/main` at dispatch time.
- Python 3.12; venv at `~/.cache/policyassist-venv`.
- Ruff line-length 100, target `py312`, selects `E, F, W, I, N, UP, B, C4, SIM, RUF`.
- Mypy `strict = true`; CI runs `mypy monitoring` only, but locally verify `mypy monitoring policyassist` still shows only the 5 pre-existing errors (no new ones from this branch).
- Pytest coverage `source = ["monitoring"]` — `policyassist/history.py` and `policyassist/app.py` are not measured for coverage, but tests are required.
- Conventional Commits enforced. Never `--no-verify`. No Claude co-author trailers.
- **Files in scope:** `policyassist/app.py`, `policyassist/history.py` (new), `policyassist/templates/index.html` (only if needed for tests — the current template is session-agnostic already), `tests/test_history.py` (new), `tests/test_app_sessions.py` (new), `.env.example` (add `SECRET_KEY`).
- **Files OUT of scope:** `monitoring/**`, `signoz/**`, `prices.yaml`, `plan-policyassist.md`, `CLAUDE.md`, `docs/**`, `ai-log.md`, `policyassist/config.py`.
- Don't touch the C-slice hotspot (`policyassist/app.py:46-52` SystemMessage construction) unless strictly necessary. If you must move it, keep the constructor form unchanged so Slice C's `cache_control` kwarg can rebase cleanly.

## File Structure

**Created:**
- `policyassist/history.py` — `HistoryStore` class, `SessionId` type alias, `_lock_path()` helper.
- `tests/test_history.py` — unit tests for `HistoryStore` covering isolation, persistence, trimming, and concurrent-write safety.
- `tests/test_app_sessions.py` — Flask test-client tests: cookie set on first `GET /`, two clients get independent histories via `POST /ask`, history persists across requests, trimmed at N turns.

**Modified:**
- `policyassist/app.py` — replace `load_history()`/`save_history()` free functions with `HistoryStore`; add `session["sid"] = uuid4().hex` init; consume `SECRET_KEY` env var; consume `HISTORY_MAX_TURNS` via the store.
- `.env.example` — add `SECRET_KEY=` placeholder.

**Deleted:** none (existing `policyassist/chat_log.json` if present is left as-is; new store writes under `policyassist/chat_log/`).

---

## Task 1: Create the branch

- [ ] **Step 1: Fetch and branch**

```bash
git fetch origin
git worktree add ../policyAssistRoom3-sessions -b feat/policyassist-sessions origin/main
cd ../policyAssistRoom3-sessions
```

Expected: worktree created, HEAD on `feat/policyassist-sessions` off latest `origin/main`.

- [ ] **Step 2: Sanity check**

```bash
git status --short
git log --oneline -3
```

Expected: clean worktree; log shows the Wave 0 commits `5aa50e7` and `b011dc9` at HEAD.

---

## Task 2: RED — write `tests/test_history.py`

**Interfaces produced by later tasks:**
- `policyassist.history.HistoryStore(root: Path)` — instance owns a directory.
- `HistoryStore.get_context(sid: str) -> list[dict[str, str]]` — returns trimmed history (last `HISTORY_MAX_TURNS` turns).
- `HistoryStore.append(sid: str, question: str, answer: str) -> None` — persists a turn.
- `HistoryStore.raw(sid: str) -> list[dict[str, str]]` — untrimmed history, for tests.

- [ ] **Step 1: Create `tests/test_history.py`**

```python
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
```

- [ ] **Step 2: Run to confirm RED**

```bash
~/.cache/policyassist-venv/bin/pytest tests/test_history.py -v
```

Expected: import error `ModuleNotFoundError: No module named 'policyassist.history'`.

---

## Task 3: GREEN — implement `policyassist/history.py`

- [ ] **Step 1: Create the module**

```python
"""Per-session history store for PolicyAssist.

Stores one JSON file per session id under a configurable root directory.
Writes are serialised with a POSIX advisory lock (fcntl.flock) so
concurrent gunicorn workers don't clobber each other. Trimming to the
last HISTORY_MAX_TURNS turns happens in get_context() so callers never
see the strategy.

The session id is treated as a filesystem-safe token: only [A-Za-z0-9_-]
is allowed. Path traversal ('..', '/') raises ValueError.
"""

from __future__ import annotations

import fcntl
import json
import re
from pathlib import Path

from policyassist.config import HISTORY_MAX_TURNS

_SID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_sid(sid: str) -> None:
    if not _SID_RE.fullmatch(sid):
        raise ValueError(f"invalid session id: {sid!r}")


class HistoryStore:
    """File-per-session JSON history under a single root directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, sid: str) -> Path:
        _validate_sid(sid)
        return self._root / f"{sid}.json"

    def raw(self, sid: str) -> list[dict[str, str]]:
        path = self._path(sid)
        if not path.exists():
            return []
        with path.open("r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data: list[dict[str, str]] = json.load(f)
                return data
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_context(self, sid: str) -> list[dict[str, str]]:
        history = self.raw(sid)
        if HISTORY_MAX_TURNS <= 0:
            return history
        return history[-HISTORY_MAX_TURNS:]

    def append(self, sid: str, question: str, answer: str) -> None:
        path = self._path(sid)
        # Open r+ if exists so we can lock and read-modify-write atomically.
        # Otherwise create empty and lock.
        if path.exists():
            with path.open("r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    data = json.load(f)
                    data.append({"question": question, "answer": answer})
                    f.seek(0)
                    f.truncate()
                    json.dump(data, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        else:
            with path.open("w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump([{"question": question, "answer": answer}], f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 2: Run tests, confirm GREEN**

```bash
~/.cache/policyassist-venv/bin/pytest tests/test_history.py -v
```

Expected: 6 passed.

---

## Task 4: RED — write `tests/test_app_sessions.py`

**Interfaces produced by Task 5:**
- Flask `app` still importable as `policyassist.app.app`.
- `session["sid"]` set to a 32-hex UUID on first visit.
- `/ask` reads history via `HistoryStore` keyed on `session["sid"]`.

- [ ] **Step 1: Create the test file**

```python
"""Integration tests for session-scoped history in policyassist.app.

These tests never call the real LLM — we monkeypatch policyassist.app.llm
to return a canned response, so we exercise the session/history path
end-to-end without cost or network.
"""

from __future__ import annotations

import importlib
import json
import os
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
    with app.test_client() as c1, app.test_client() as c2:
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
```

- [ ] **Step 2: Run to confirm RED**

```bash
~/.cache/policyassist-venv/bin/pytest tests/test_app_sessions.py -v
```

Expected: failures — either an import error (because `POLICYASSIST_HISTORY_ROOT` isn't consumed yet) or missing session/SECRET_KEY behaviour.

---

## Task 5: GREEN — rewire `policyassist/app.py`

- [ ] **Step 1: Replace `policyassist/app.py`**

Replace the current file contents with:

```python
"""PolicyAssist -- internal guidance chat tool.

Reference client for the monitoring service. Wave 1 hardening:

* Flask signed-cookie session gives each browser a stable sid.
* HistoryStore isolates per-session conversation, trimmed to
  HISTORY_MAX_TURNS turns before every LLM call.
* Monitoring instrumentation preserved from the prototype+monitoring
  bridge -- no changes to the traced_llm_call surface.

Remaining SINs (retries, caching, validation, red-banner errors) land in
later slices; this file will grow -- keep the top-of-file section list
in sync so a reader can find each concern in ~10 seconds.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, render_template, request, session
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from monitoring import instrument_app, traced_llm_call
from policyassist.history import HistoryStore

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1024

_HISTORY_ROOT = Path(
    os.environ.get(
        "POLICYASSIST_HISTORY_ROOT",
        str(Path(__file__).parent / "chat_log"),
    )
)
MANUAL_PATH = Path(__file__).parent / "manual.txt"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]

instrument_app(service_name="policyassist")

llm = ChatAnthropic(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    api_key=os.environ["ANTHROPIC_API_KEY"],
)

history_store = HistoryStore(_HISTORY_ROOT)

MANUAL = MANUAL_PATH.read_text()

SYSTEM_PROMPT = (
    "You are PolicyAssist, an internal assistant for Border Force officers. "
    "Answer questions using ONLY the operational manual below. "
    "If the manual does not cover the question, say so and advise the officer "
    "to contact the Duty Higher Officer. Be concise and practical.\n\n"
    "=== BORDER FORCE OPERATIONAL MANUAL (EXTRACT) ===\n\n" + MANUAL
)


def _ensure_sid() -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid4().hex
        session["sid"] = sid
    return sid


@app.route("/")
def index() -> str:
    sid = _ensure_sid()
    return render_template("index.html", history=history_store.raw(sid))


@app.route("/ask", methods=["POST"])
def ask() -> dict[str, Any]:
    sid = _ensure_sid()
    question: str = request.json["question"]  # type: ignore[index]

    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=SYSTEM_PROMPT)
    ]
    for entry in history_store.get_context(sid):
        messages.append(HumanMessage(content=entry["question"]))
        messages.append(AIMessage(content=entry["answer"]))
    messages.append(HumanMessage(content=question))

    with traced_llm_call(model=MODEL) as span:
        response = llm.invoke(messages)
        span.record_usage(response)

    answer = response.content
    history_store.append(sid, question, answer)

    return {"answer": answer}


if __name__ == "__main__":
    app.run(port=5000)
```

- [ ] **Step 2: Update `.env.example`**

Append (do not replace existing lines):

```
# --- Session cookie signing key (Slice A) ---
# Any long random string; keep out of git. Generate with:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=

# Optional: override per-session history storage root (defaults to
# policyassist/chat_log/ relative to the app module).
POLICYASSIST_HISTORY_ROOT=
```

- [ ] **Step 3: Add `chat_log/` to `.gitignore`**

Append to `.gitignore`:

```
# Session-scoped history files written at runtime (Slice A).
policyassist/chat_log/
```

Also verify the old `policyassist/chat_log.json` (if it exists as a working-tree artifact from the prototype) is either committed-ignored or removed — do NOT commit real user data.

- [ ] **Step 4: Run tests, confirm GREEN**

```bash
~/.cache/policyassist-venv/bin/pytest tests/test_history.py tests/test_app_sessions.py -v
```

Expected: all pass (6 history + 4 session tests = 10 total).

- [ ] **Step 5: Run full suite**

```bash
~/.cache/policyassist-venv/bin/pytest
```

Expected: all tests pass. Monitoring coverage stays ≥ 80%.

---

## Task 6: Local CI-equivalent

- [ ] **Step 1: Lint**

```bash
~/.cache/policyassist-venv/bin/ruff check .
```

Expected: clean. If ruff complains about anything, `ruff check --fix .` and re-run.

- [ ] **Step 2: Format check**

```bash
~/.cache/policyassist-venv/bin/ruff format --check .
```

Expected: clean. `ruff format .` if not.

- [ ] **Step 3: Type check (CI scope)**

```bash
~/.cache/policyassist-venv/bin/mypy monitoring
```

Expected: `Success: no issues found in 4 source files`.

- [ ] **Step 4: Security scan**

```bash
~/.cache/policyassist-venv/bin/bandit -r monitoring policyassist -c pyproject.toml
```

Expected: no issues (fcntl usage is fine; JSON I/O is fine).

- [ ] **Step 5: Secrets scan**

```bash
~/.cache/policyassist-venv/bin/pre-commit run gitleaks --all-files
```

Expected: `Passed`. The `.env.example` placeholder `SECRET_KEY=` must have no value.

---

## Task 7: Commit and open PR

- [ ] **Step 1: Stage and commit**

Three logical commits (one per test file cycle) is ideal, but a single squashable commit is acceptable:

```bash
git add policyassist/history.py policyassist/app.py policyassist/chat_log/.gitkeep \
        tests/test_history.py tests/test_app_sessions.py \
        .env.example .gitignore
~/.cache/policyassist-venv/bin/pre-commit run --from-ref origin/main --to-ref HEAD
git commit -m "feat(policyassist): session isolation and bounded history

Introduces HistoryStore keyed on a Flask signed-cookie session id, and
trims conversation context to HISTORY_MAX_TURNS turns before every LLM
call. Closes SIN 2 (shared history) and SIN 3 (unbounded token growth).

- policyassist/history.py: file-per-session JSON store with fcntl advisory
  locking on writes.
- policyassist/app.py: session[\"sid\"] init, HistoryStore wiring, trim
  via HistoryStore.get_context().
- .env.example: SECRET_KEY placeholder for Flask session signing.
- .gitignore: exclude policyassist/chat_log/ (runtime data).
"
```

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin feat/policyassist-sessions
gh pr create --base main --title "feat(policyassist): session isolation and bounded history" --body "$(cat <<'EOF'
## Summary

Wave 1 slices A + B from plan-policyassist.md.

- **Slice A — Session isolation.** Every browser gets a Flask signed-cookie session id on first visit. History is now stored per-session under `policyassist/chat_log/<sid>.json` with `fcntl.flock` on writes.
- **Slice B — Bounded history.** `HistoryStore.get_context(sid)` returns only the last `HISTORY_MAX_TURNS` turns (default 10, env-overridable via the Wave 0 config module).

## Verification

- [x] `pytest tests/test_history.py tests/test_app_sessions.py -v` — all pass
- [x] Full suite green; monitoring coverage still ≥ 80%
- [x] `ruff check .` — clean
- [x] `mypy monitoring` — clean
- [x] `bandit -r monitoring policyassist -c pyproject.toml` — clean
- [ ] Reviewer: two browser profiles hit the app, hold independent conversations. Confirm each `<sid>.json` file appears under `policyassist/chat_log/`.

## Notes

- New env var: `SECRET_KEY` (Flask session signing). Placeholder added to `.env.example`; anyone running the app must set a real value (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- `policyassist/chat_log/` is now git-ignored; `.gitkeep` retained to keep the empty dir.
- Slice C (caching) will rebase onto this PR; the SystemMessage construction at `policyassist/app.py` is intentionally left in the same shape as before to keep C's rebase trivial.
EOF
)"
```

Expected: PR URL printed. Report it to the orchestrator.

---

## Task 8: HUMAN CHECKPOINT

Orchestrator (main session) pauses. Human reviews and rebase-merges via GitHub UI. Success criterion satisfied when two browsers show independent conversations against the merged branch.

---

## Failure modes

- **`SECRET_KEY` missing at import time:** the app now `KeyError`s on module import if `SECRET_KEY` is unset. This is intentional — matches the existing behaviour for `ANTHROPIC_API_KEY`.
- **`fcntl` unavailable:** Linux/macOS only. Windows users would need `msvcrt` — out of scope for this sprint (CI is Linux, demo is Linux).
- **Existing `policyassist/chat_log.json` from prototype:** ignore. New store writes under `policyassist/chat_log/` (directory), not `chat_log.json` (file). Old file can be manually deleted; documented in ai-log for the next handover.
- **Test flakes on `test_context_trimmed_to_history_max_turns`:** if the test asserts the wrong count, re-derive: `1 SystemMessage + HISTORY_MAX_TURNS * 2 messages (question+answer per turn) + 1 latest HumanMessage`. If `HISTORY_MAX_TURNS = 10`, expect `22`.

---

## Self-review

**Spec coverage:**
- plan-policyassist.md Slice A "session identifier per browser, HistoryStore keyed on session id" → Task 5.
- plan-policyassist.md Slice A "Migrate the existing `chat_log.json` schema" → handled via new directory + gitignore; old file left in place.
- plan-policyassist.md Slice B "trim messages before llm.invoke, HISTORY_MAX_TURNS, applied in HistoryStore.get_context" → Task 3 + Task 5.
- plan-policyassist.md §6 A/B race mitigation ("`fcntl.flock` on write") → Task 3.

**Placeholder scan:** no TBDs; every code block is complete.

**Type consistency:** `HistoryStore` signatures match between plan interfaces block and Task 3 implementation.

No issues found.

---

## Execution Handoff

Single subagent recommended (this plan is one cohesive slice). Use `subagent-driven-development` to dispatch a fresh worker with a copy of this plan and the design spec.
