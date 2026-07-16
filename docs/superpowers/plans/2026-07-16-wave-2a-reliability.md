# Wave 2A — Slices D + E + F: Input Validation, Error Surfacing, Retries

> **For agentic workers:** subagent-driven; TDD-first; commit types conventional.

**Goal:** Make `/ask` return well-formed HTTP errors instead of 500s, surface those errors in a red banner in the UI, and retry transient upstream failures with exponential backoff before giving up.

**Scope:** Slices D, E, F from `plan-policyassist.md:111-174`. Branch `feat/policyassist-reliability`.

**Tech Stack:** Flask · tenacity (new dep, F2 decision — Slice C stayed on LangChain per C1 spike) · anthropic exceptions.

## Global Constraints

- **In scope:** `policyassist/app.py`, `policyassist/templates/index.html`, `pyproject.toml` (add tenacity), `tests/test_app_ask.py` (new), possibly `tests/test_app_retries.py` (new).
- **Out of scope:** `monitoring/**`, `signoz/**`, `prices.yaml`, `plan-policyassist.md`, `CLAUDE.md`, `docs/**`, `ai-log.md`, `policyassist/history.py`, `policyassist/config.py`.
- Constants from `policyassist.config`: `MAX_QUESTION_LENGTH=500` (D+H), `LLM_TIMEOUT_SECONDS=30` (F), `LLM_MAX_RETRIES=3` (F).
- Never `--no-verify`; never Claude co-author trailer; rebase-and-merge only.
- Python 3.12; venv `~/.cache/policyassist-venv`.

## Slice D — Input validation

Add hand-rolled guards (E1 decision) at the top of `ask()`. Return `{"error": "..."}` with 400 for:
1. Non-JSON body → 400 "request body must be JSON"
2. Missing `question` key → 400 "missing 'question'"
3. `question` not a string → 400 "'question' must be a string"
4. `question` empty (after strip) → 400 "'question' must not be empty"
5. `len(question) > MAX_QUESTION_LENGTH` → 400 "'question' exceeds 500 chars"

**Contract:** the validation runs BEFORE `_ensure_sid()` — no session churn for malformed requests.

## Slice E — Error surfacing

Wrap `llm.invoke(messages)` in `try/except`. Catch:
- `anthropic.APITimeoutError` → return `{"error": "The service is slow to respond. Please try again."}`, 504
- `anthropic.APIConnectionError`, `anthropic.APIStatusError`, `anthropic.APIError` (base) → return `{"error": "Upstream service unavailable. Please try again."}`, 502
- Anything else falls through to Flask's default 500.

`traced_llm_call` already records the exception on the span (per `monitoring/instrumentation.py`) — don't record it twice.

**Template (`policyassist/templates/index.html`):** after the `fetch('/ask', ...)` call, if `!res.ok`, render `data.error` as a red banner ABOVE the chat. Keep the question in the input so the officer can retry without retyping. Do NOT append the un-answered question to `#chat`.

Red-banner CSS (add to the existing `<style>` block):
```css
.error-banner { background: #d4351c; color: #fff; padding: .6rem .8rem; margin: .5rem 0; }
```

## Slice F — Retries + timeouts

- Instantiate `ChatAnthropic(..., timeout=LLM_TIMEOUT_SECONDS)`.
- Wrap `llm.invoke(...)` in a `tenacity.Retrying`:
  - `stop=stop_after_attempt(LLM_MAX_RETRIES)` (3)
  - `wait=wait_exponential_jitter(initial=1, max=8)`
  - `retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError))` — narrowly: 429, 529, network blips. Do NOT retry on 400/401/403 (those don't get better).
  - `reraise=True`
- The retry lives INSIDE `traced_llm_call` — one outer span records the FINAL outcome; retries are internal.

Add to `pyproject.toml` dependencies: `"tenacity>=9,<10"`.

## Tests (must be RED before impl)

### `tests/test_app_ask.py`

Fixtures reuse the pattern from `tests/test_app_sessions.py` (monkeypatch env, stub LLM, reload app).

Cover:
- `test_non_json_body_returns_400`
- `test_missing_question_returns_400`
- `test_non_string_question_returns_400`
- `test_empty_question_returns_400`
- `test_question_exceeds_max_length_returns_400`
- `test_valid_question_succeeds`
- `test_apitimeout_returns_504_and_body_carries_error`
- `test_apiconnection_returns_502`
- `test_generic_exception_falls_through_to_500`

### `tests/test_app_retries.py`

- `test_transient_apiconnection_retries_and_eventually_succeeds` (stub LLM raises `APIConnectionError` on first call, returns valid response on second — assert only one span-observable outcome via a counter on the stub)
- `test_persistent_apiconnection_gives_up_after_max_retries` (stub always raises; expect 502 after `LLM_MAX_RETRIES` attempts)
- `test_400_error_not_retried` (stub raises `BadRequestError`; expect immediate propagation, no retry)

## Rebase courtesy

Slice H (`feat/policyassist-prod-server` — Wave 2B) also touches `policyassist/app.py` for logging span attributes, but reads `MAX_QUESTION_LENGTH` via `policyassist.config` — no textual conflict. If Wave 2B lands first, rebase should be clean.

## Verification checklist

- `pytest` full suite green; monitoring coverage ≥ 80%.
- `ruff check .`, `ruff format --check .`, `mypy monitoring`, `bandit -r monitoring policyassist -c pyproject.toml` all clean.
- Live smoke: unset `ANTHROPIC_API_KEY` while the app is running; POST `/ask` returns 502 with a red banner in the UI; question stays in the input.

## PR body

Title: `feat(policyassist): validation, error surfacing, and retries`

Body sections: Summary (three bullets, one per slice); Verification (checkbox list per above); Deps added (`tenacity>=9,<10`); Rebase notes; Reviewer checklist item for the red-banner smoke test.
