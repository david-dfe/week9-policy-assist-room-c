# Wave 2B — Slices G + H: Production Server + Prompt-Injection Partial Mitigation

> **For agentic workers:** subagent-driven; TDD-first; commit types conventional.

**Goal:** Give PolicyAssist a proper WSGI entrypoint (gunicorn) with `debug=True` nowhere in the tree, and record enough per-request signal on OTel spans to spot prompt-injection anomalies without ever writing user content to a durable store.

**Scope:** Slices G, H from `plan-policyassist.md:177-222`. Branch `feat/policyassist-prod-server`.

**Tech Stack:** gunicorn (new dev dep, G1 decision) · Python `hashlib.sha256` · OTel span attributes.

## Global Constraints

- **In scope:** `policyassist/app.py` (remove `app.run`, add span attribute recording), `pyproject.toml` (add gunicorn to dev extras), `Makefile` (new), `README.md` (add `make run`), `tests/test_app_injection_signals.py` (new).
- **Out of scope:** `monitoring/**` (span attribute names are set from the app via `traced_llm_call`'s span object — do NOT modify monitoring/), `signoz/**`, `prices.yaml`, `plan-policyassist.md`, `CLAUDE.md`, `docs/**`, `ai-log.md`, `policyassist/history.py`, `policyassist/config.py`.
- Read `MAX_QUESTION_LENGTH` from `policyassist.config` (imported in Slice D too — no textual conflict; both read it, no one redefines).
- Never `--no-verify`; never Claude co-author trailer; rebase-and-merge only.
- Python 3.12; venv `~/.cache/policyassist-venv`.

## Slice G — Production server

**Code changes:**

1. **Remove `app.run(port=5000)` from module scope.** Replace the trailing `if __name__ == "__main__": app.run(port=5000)` block entirely with:
   ```python
   if __name__ == "__main__":
       # Dev-only local runner. Prod uses gunicorn — see Makefile.
       app.run(port=5000)
   ```
   The gate is already `if __name__ == "__main__"` so importing the module doesn't start a server — verify this survives your change.

2. **Add gunicorn to `pyproject.toml` `[project.optional-dependencies].dev`:**
   ```toml
   "gunicorn>=23,<24",
   ```

3. **New `Makefile`** at repo root:
   ```
   .PHONY: run dev test lint

   run:
   	uv run gunicorn -w 4 -b 127.0.0.1:5000 policyassist.app:app

   dev:
   	uv run flask --app policyassist.app run --port 5000

   test:
   	uv run pytest

   lint:
   	uv run ruff check . && uv run ruff format --check . && uv run mypy monitoring
   ```
   Use TABS for indentation (Makefile requirement).

4. **Update `README.md`:** in the "Run PolicyAssist" section, add a subsection "Production-grade server" showing `make run` and calling out the 4-worker default. Keep the existing `flask run` line as "dev".

5. **Confirm** `instrument_app()` is idempotent under gunicorn workers — `monitoring/instrumentation.py` already has an `_INSTRUMENTED` flag; verify by grepping. Don't change monitoring.

## Slice H — Prompt-injection partial mitigation

**Code changes in `policyassist/app.py:ask()`, after validation but before the LLM call:**

1. Import `hashlib` at the top.
2. Inside `ask()`, after Slice D's validation passes and after `_ensure_sid()`, compute:
   ```python
   question_length = len(question)
   question_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()[:8]
   ```
3. Attach both to the current OTel span. `traced_llm_call` yields an `LLMSpan` — that class already exposes `set_attribute` (see `monitoring/instrumentation.py`). Use it:
   ```python
   with traced_llm_call(model=MODEL) as span:
       span.set_attribute("policyassist.question.length", question_length)
       span.set_attribute("policyassist.question.hash", question_hash)
       response = llm.invoke(messages)
       _hoist_cache_metrics(response)
       span.record_usage(response)
       answer = response.content if isinstance(response.content, str) else str(response.content)
       span.set_attribute("policyassist.answer.length", len(answer))
   ```
   (The `answer.length` recording happens INSIDE the `with` so it lands on the same span.)

4. **Do NOT set any attribute containing the raw question or answer text.** That's a hard constraint from CLAUDE.md §9.1.

5. Verify `SYSTEM_PROMPT` still contains the `=== BORDER FORCE OPERATIONAL MANUAL (EXTRACT) ===` sentinel delimiters on both sides (already does; just don't remove them).

6. `MAX_QUESTION_LENGTH` enforcement rides in Slice D (already covered by shared config). H does NOT re-implement the length check.

## Tests (RED before impl)

### `tests/test_app_injection_signals.py`

Use the same stub-LLM pattern from `tests/test_app_sessions.py`. Also stub `traced_llm_call` to capture recorded attributes — you can `monkeypatch` `monitoring.instrumentation.traced_llm_call` OR use a local fake context manager that records `set_attribute` calls.

- `test_question_length_recorded_on_span`
- `test_question_hash_recorded_on_span_and_is_8_hex_chars`
- `test_answer_length_recorded_on_span`
- `test_raw_question_text_not_recorded_on_span_attributes` (assert no attribute value contains the question string)
- `test_two_different_questions_produce_different_hashes`
- `test_two_identical_questions_produce_identical_hashes` (correlation without reversal)

## Rebase courtesy

Wave 2A (`feat/policyassist-reliability`) also touches `ask()` for validation, error handling, and retries. Both branches import `policyassist.config` for shared constants — no textual conflict. If Wave 2A lands first:
- Add Slice H's span attribute recording INSIDE the try-block, alongside the LLM call.
- Add `question_length` / `question_hash` computation AFTER Wave 2A's validation guards pass.

Expected rebase conflict: 1 hunk around the `with traced_llm_call(...) as span:` block. Resolve by nesting Wave 2A's retry loop INSIDE the with-block and adding Wave 2B's `set_attribute` calls before the LLM invocation.

## Verification checklist

- `pytest` full suite green; monitoring coverage ≥ 80%.
- `ruff check .`, `ruff format --check .`, `mypy monitoring`, `bandit -r monitoring policyassist -c pyproject.toml` all clean.
- Live smoke: `~/.cache/policyassist-venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 policyassist.app:app` binds and serves `/`. Ask a question; SigNoz span shows `policyassist.question.length` and `policyassist.question.hash` (8-char hex) but NO raw content.

## PR body

Title: `feat(policyassist): production server and injection anomaly signals`

Body sections: Summary (two bullets); Verification (checkbox); Deps added (`gunicorn>=23,<24`); Rebase notes wrt Wave 2A; Reviewer checklist for the gunicorn smoke and SigNoz span attribute inspection; Explicit note that this is partial mitigation per NCSC guidance.
