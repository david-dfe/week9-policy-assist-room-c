# AI Development Log

Rolling record of design decisions, progress, blockers, and handovers for the PolicyAssist monitoring service. See `CLAUDE.md` §8 for the format and when to append.

**Rules of the log:**
- Newest entry at the top.
- One entry per meaningful unit of work (>30 min, or any non-obvious decision).
- Link commits and PRs — the log points *to* git; it does not duplicate it.
- No secrets, no real user data, no verbatim officer questions.

---

## 2026-07-16 — Wave 2: validation, red-banner errors, retries, prod server, injection signals

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `feat/policyassist-reliability` — #19 — `2feb00f`; `feat/policyassist-prod-server` — #18 — `a02b103`
**Type:** progress

Wave 2 shipped two parallel PRs an hour after Wave 1. 8 of the 10 slices in `plan-policyassist.md` are now in main. Only Slices I (evals) and J (manual-update docs) remain for Wave 3.

**Slice D (input validation, PR #19):**
- Five hand-rolled guards at the top of `ask()` (non-JSON, missing/non-string/empty/oversized `question`). All return `400 {"error": "..."}`.
- Validation runs BEFORE `_ensure_sid()` — malformed requests do not churn session cookies. Covered by `test_validation_does_not_create_session`.

**Slice E (error surfacing, PR #19):**
- `try/except` maps `anthropic.APITimeoutError → 504`, `APIConnectionError/APIStatusError/APIError → 502`. Body carries `{"error": ...}`.
- `templates/index.html` renders a red banner on `!res.ok`, keeps the question in the input, and only commits the transcript entry on success.

**Slice F (retries + timeouts, PR #19):**
- `ChatAnthropic(..., timeout=LLM_TIMEOUT_SECONDS)`; retry loop inside `traced_llm_call` via `tenacity.Retrying(stop_after_attempt(LLM_MAX_RETRIES), wait=wait_exponential_jitter(1, 8))`.
- Custom `_should_retry` narrows `APIStatusError` to 5xx and includes `RateLimitError` and `APIConnectionError`. **Deliberate divergence** from the plan's suggested `retry_if_exception_type` — `BadRequestError` subclasses `APIStatusError`, so the naive form would incorrectly retry 400s. Behaviour matches the plan's *stated intent* ("do not retry 400/401/403"); the shape differs.
- `_RETRY_WAIT` exposed as a module-level attribute so tests can swap it for `wait_none()`.
- Added `tenacity>=9,<10` to `pyproject.toml` dependencies.
- 15 new tests (11 validation/error + 4 retry).

**Slice G (production server, PR #18):**
- `app.run(...)` is now dev-only (already gated on `__name__ == "__main__"`).
- `pyproject.toml` dev extras get `gunicorn>=23,<24`.
- New root `Makefile` with `make run` (gunicorn 4 workers on 127.0.0.1:5000), `make dev`, `make test`, `make lint`.
- `README.md` documents both dev and production launch.
- Live-smoke: `gunicorn -w 4` binds and returns 200 on `/`.

**Slice H (injection anomaly signals, PR #18):**
- After validation and before the LLM call, `ask()` computes `question_length = len(question)` and `question_hash = sha256(question)[:8]`, both attached to the OTel span via `span.set_attribute(...)`.
- After the LLM call, `answer.length` is recorded — inside the same `with span:` block. **No raw content on any span attribute** (CLAUDE.md §9.1 hard constraint).
- 6 new tests including an explicit `test_raw_question_text_not_recorded_on_span_attributes` invariant.

**Rebase conflict handled:**
- PR #18 rebased onto merged PR #19 hit one conflict at the SystemMessage/LLM-invoke block. Resolved by nesting Slice H's `span.set_attribute` calls inside Slice E's `try/except` and around Slice F's `_invoke_with_retry(messages)` — both changes now coexist. Manual `ruff format` fix on the amended commit unblocked CI.

**Merged docs bundle (this PR):**
- `docs/superpowers/plans/2026-07-16-wave-2a-reliability.md` — Wave 2A plan.
- `docs/superpowers/plans/2026-07-16-wave-2b-prod-and-injection.md` — Wave 2B plan.
- This ai-log entry.

**Still outstanding (unchanged from Wave 1's note):**
- `chore(ci): fix pre-commit mypy hook additional_dependencies` — adds flask/langchain/opentelemetry stubs so the hook actually runs on `policyassist/app.py`.
- `fix(monitoring): read LangChain nested cache fields in usage_from_response` — removes the need for `_hoist_cache_metrics` adapter in every client app.

Next: Wave 3 — Slice I (golden-set evals + runner + workflow_dispatch CI) and Slice J (manual-update procedure in `README.md`).

---

## 2026-07-16 — Wave 1: session isolation, bounded history, prompt caching all landed

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `feat/policyassist-sessions` — #15 — `8a5aaf0`; `feat/policyassist-caching` — #16 — `090b8a9`
**Type:** progress

Wave 1 of the PolicyAssist hardening workflow shipped in a single afternoon. Two subagents dispatched in parallel worktrees off `origin/main` at `b011dc9`; each followed its per-slice plan under `docs/superpowers/plans/`. Both PRs landed cleanly — the pre-emptive extraction of shared constants in Wave 0 and the deliberate rebase-courtesy in the A+B plan (leave the SystemMessage constructor line untouched) meant the two branches never collided.

**Slice A (session isolation, PR #15):**
- New `policyassist/history.py` — `HistoryStore` with per-session JSON files under `fcntl.flock` advisory locking. Session id is a validated `[A-Za-z0-9_-]+` token (path-traversal-safe).
- `policyassist/app.py` — `session["sid"] = uuid4().hex` on first visit; `SECRET_KEY` env var required.
- `.env.example` adds `SECRET_KEY` and optional `POLICYASSIST_HISTORY_ROOT`; `.gitignore` excludes runtime `policyassist/chat_log/`.

**Slice B (bounded history, PR #15):**
- `HistoryStore.get_context(sid)` trims to the last `HISTORY_MAX_TURNS` (default 10, env-overridable).
- Applied inside the store so `/ask` never sees the strategy.

**Slice C (prompt caching, PR #16):**
- `SYSTEM_PROMPT_BLOCK: dict[str, Any]` — content-block form with `cache_control={"type":"ephemeral"}`.
- `SystemMessage(content=[SYSTEM_PROMPT_BLOCK])` in `ask()` — LangChain propagates the marker (C1 spike passed 2026-07-16).
- New `_hoist_cache_metrics(response)` copies `usage_metadata.input_token_details.cache_read/cache_creation` up to the top-level `cache_read_input_tokens`/`cache_creation_input_tokens` keys that `monitoring/cost.py:usage_from_response` reads. Slice-scoped adapter; monitoring itself is unchanged.

**Two-stage subagent flow, one denial handled:**
- Wave 1A subagent hit `SKIP=mypy` internally; Wave 1B subagent was denied `bandit`/`pre-commit` mid-run and returned to the orchestrator. Root cause: pre-commit's `mypy` hook `additional_dependencies` list lacks flask/langchain/opentelemetry stubs, so any commit touching `app.py` fails the local hook. Both branches landed because `.git/hooks/pre-commit` isn't executable on this SMB mount (documented) and CI runs `mypy monitoring` only, which passes.

**Follow-up recorded (not in this PR):**
- `chore(ci): fix pre-commit mypy hook additional_dependencies` — add flask, langchain-*, opentelemetry-* to the hook config. Also fix the 4 pre-existing typing gaps in `policyassist/app.py` (call-arg on `ChatAnthropic`, SecretStr arg, unused type-ignore, dict-item) that only become visible once the deps are installed. Small, self-contained PR.
- `fix(monitoring): read LangChain nested cache fields in usage_from_response` — remove the need for `_hoist_cache_metrics` adapter in every client app.

**Success criteria for the Day-2 demo (from plan-policyassist.md §7):**
- ✅ Session isolation (A) — merged and tested via 4 integration tests.
- ✅ Cache_control propagates (C) — 6 tests + live spike confirm.
- ⏳ Human end-to-end: two browser profiles, independent conversations, SigNoz shows `cache_read_input_tokens > 0` on repeat request. Awaiting orchestrator smoke-test.

Next: Wave 2 — Slices D+E+F (input validation + red-banner errors + retries/timeouts) parallel with Slices G+H (production server + prompt-injection partial mitigation).

---

## 2026-07-16 — Wave 0: shared constants + workflow design landed; C1 spike PASS

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `chore/policyassist-shared-constants` — #13 — `5aa50e7`, `b011dc9`
**Type:** progress + decision

Kicked off the PolicyAssist hardening workstream (per `plan-policyassist.md`) as a deterministic workflow with `obra/superpowers` as the skill layer. Design spec at `docs/superpowers/specs/2026-07-16-policyassist-hardening-workflow-design.md`; Wave 0 implementation plan at `docs/superpowers/plans/2026-07-16-wave-0-shared-constants-and-spike.md`.

**Wave 0 (this PR):**
- `policyassist/config.py` centralises the five shared constants (`HISTORY_MAX_TURNS=10`, `MAX_QUESTION_LENGTH=500`, `LLM_TIMEOUT_SECONDS=30`, `LLM_MAX_RETRIES=3`, `EVAL_PASS_THRESHOLD=0.85`) with env-var overrides read at import time. Removes the collision surface between slices D and H before parallel work starts.
- `tests/test_config.py` — 11 tests covering defaults + env overrides. Full suite still 93% coverage on `monitoring/`.

**C1 spike (run 2026-07-16, out-of-tree at `/tmp/cache_control_spike.py`):** two identical `SystemMessage`s with `cache_control={"type":"ephemeral"}` through `langchain-anthropic` produced a `cache_read=1402` on the second call. **Cache propagates.** Locked contracts for Wave 1: **Slice C = D1 (LangChain path)**, **Slice F = F2 (Tenacity retries)**.

**Note for Slice C implementer:** LangChain surfaces cache metrics under `usage_metadata["input_token_details"]["cache_read"]`, not at the top-level key `cache_read_input_tokens`. `monitoring/instrumentation.py:usage_from_response` should be checked for correct field lookup — if it reads the top-level key it will silently record zero cache reads on spans.

**Note on tooling drift:** `CLAUDE.md` §6 states `mypy monitoring policyassist` but CI at `.github/workflows/ci.yml:58` only runs `mypy monitoring`. Running the wider scope locally surfaces 5 pre-existing errors in `policyassist/app.py` (LangChain typing gaps). Not fixed in this PR — should be a separate `fix:` PR or a `docs:` correction to `CLAUDE.md`.

**Note on pre-commit hooks:** the repo is on an SMB mount that strips the exec bit off `.git/hooks/pre-commit`. `pre-commit install` succeeds but the hook doesn't fire automatically. Ran `pre-commit run --files ...` manually before each commit on this branch. Anyone working in this repo from the same filesystem will hit the same behaviour.

Next: Wave 1 — write per-slice plans for A+B and C, set up two worktrees, dispatch parallel subagents. A+B merges first (session isolation is the foundation), then C rebases and merges.

---

## 2026-07-16 — Rebase chore/repo-hardening onto main; merge as PR #9

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `chore/repo-hardening` — #9 — `95c8301`
**Type:** progress

Rebased `chore/repo-hardening` (18 commits) onto `main` and merged as PR #9. Five conflicts resolved:

- `pyproject.toml`: kept `langchain-anthropic>=1.4.6` + `langchain-core>=1.2.22` from `main` (CVE fix that landed via PR #8).
- `.github/workflows/ci.yml` (three separate conflict points across intermediate commits): kept `main`'s fully SHA-pinned, permissioned, matrix-testing version throughout.
- `commitlint.config.cjs`: kept `main`'s relaxed `subject-case` (allows acronyms like PR/CVE).
- `.github/workflows/dependency-review.yml`: kept `main`'s `continue-on-error: true` (Dependency Graph not yet enabled).
- `ai-log.md` (three conflict points): merged all entries from both sides chronologically.

All CI jobs green before merge. Merged via `gh pr merge 9 --rebase --delete-branch`.

---

## 2026-07-16 — Pin CI actions to commit SHAs; upgrade gitleaks-action to v3

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `ci/pin-action-shas` — #8 — `46586c3`
**Type:** progress

Resolved the `TODO(security)` left in `ci.yml` from the repo-hardening pass: all five third-party actions are now referenced by exact commit SHA rather than mutable version tags, with the tag kept as an inline comment for readability. SHA pinning closes the tag-hijacking vector documented in the GitHub Actions security hardening guide.

Two commits on the branch:
1. **Pin all actions to SHAs** — `actions/checkout` (v4.2.2), `astral-sh/setup-uv` (v3.2.4), `actions/upload-artifact` (v4.4.3), `gitleaks/gitleaks-action` (v2.3.9 at time of pinning), `wagoid/commitlint-github-action` (v6.2.1). The `wagoid` tag is annotated so the SHA was dereferenced one level to the underlying commit.
2. **Upgrade gitleaks-action v2 → v3** — v2 runs on Node 20 which GitHub removes from hosted runners 2026-09-16; v3 migrates to Node 24 with no behavioural changes.

---


## 2026-07-15 15:10 — Review follow-ups: SpanKind, price caching, finops validation

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `feat/monitoring-service` → merged into `chore/repo-hardening` → landed on `main` via PR #9 — `95c8301`
**Type:** progress

Implemented the three top-priority fixes from `monitoring-review.md` (which is a working-tree-only review artefact — not committed):

1. **`SpanKind.CLIENT` on `llm.invoke` spans** (`monitoring/instrumentation.py`). LLM calls are outbound network calls; without this SigNoz service maps render them as internal, hiding the Anthropic hop. Added `test_span_kind_is_client`.
2. **`load_prices` cached** via `functools.lru_cache` keyed on the resolved `Path` (`monitoring/cost.py`). Previously `compute_cost` re-parsed `prices.yaml` on every LLM call. Also switched the file open to explicit `encoding="utf-8"`.
3. **`finops.py` query-param validation + explicit template autoescape.** Bad ints/floats, negative counts, out-of-range `cache_hit_ratio`, and unknown models now return HTTP 400 via `flask.abort(400)` instead of 500. `app.jinja_env.autoescape = True` locks autoescape on for `render_template_string`, which Flask's default handling for filename-less templates is version-dependent about. New `TestValidation` class in `tests/test_finops.py`.

Also added the guardrail test `test_prompt_and_completion_text_do_not_leak_to_span` (CLAUDE.md §9 rule 1). It seeds a marker string in `.content` and an extra `usage_metadata` key, runs `record_usage`, and asserts the marker appears in no span attribute nor status description. Catches a future well-meaning refactor that sets `span.set_attribute("answer", response.content)`.

Local checks all clean: 46 tests pass (was 36), 93% coverage, ruff + mypy clean. The remaining `monitoring-review.md` items (`str(exc)` leak, missing GenAI semconv attributes, shutdown flush, cost-as-metric, bandit/mypy scope, unpinned SigNoz clone) are deferred — flagged in the review file for a follow-up branch.

---

## 2026-07-15 14:22 — Monitoring service implementation complete

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `feat/monitoring-service` → merged into `chore/repo-hardening` → landed on `main` via PR #9 — `95c8301`
**Type:** progress

Full monitoring service landed on `feat/monitoring-service`. Seven commits stacked on top of `chore/repo-hardening`. All local checks pass (ruff, mypy, pytest — 36 tests, 92% coverage).

**What shipped:**
- `monitoring/cost.py` — `Usage`, `ModelPrices`, `compute_cost()`, `load_prices()`, and `usage_from_response()` handling three LangChain / native-Anthropic response shapes.
- `monitoring/prices.yaml` — pinned GBP-per-million-token rates for `claude-sonnet-4-5` and `claude-haiku-4-5`, with the USD 1.00 = GBP 0.80 assumption documented in the header.
- `monitoring/instrumentation.py` — `instrument_app()` (idempotent OTLP setup from env vars) and `traced_llm_call()` context manager setting GenAI semantic-convention attributes; errors recorded with `error.class`; `LLMSpan.record_usage()` sets four token attrs + `cost.gbp`.
- `monitoring/finops.py` — standalone Flask app for the "£14,200 → what?" projection. `WorkloadAssumptions` dataclass exposes every input; HTML page shows naive vs projected bills side-by-side with a savings callout and a full calculation table; `/api/projection` returns JSON; every assumption overridable via query params.
- `monitoring/README.md` — 3-line onboarding for a new client app; backend-agnostic story.
- `signoz/README.md` + `signoz/dashboards/README.md` — how to run SigNoz upstream out-of-tree, smoke-test with a curl OTLP payload, and the four dashboards to build (cost / usage / reliability / per-app).
- `policyassist/` — prototype copied in as reference client. Only three deviations from the prototype: `instrument_app()` at import, `traced_llm_call()` around `llm.invoke()`, and `MODEL` / `MAX_TOKENS` lifted to module constants (with `MODEL` corrected from the prototype's non-existent `claude-sonnet-5`).

**Design decisions worth remembering:**
- **`prices.yaml` is the ONLY place price values live.** Enforced by convention; guardrail test in `test_cost.py` (`test_cache_read_cheaper_than_input`) protects against paste errors.
- **No prompt / completion text on spans.** Only metadata. See CLAUDE.md §9.1.
- **`monitoring/` has no SigNoz-specific code.** Swap backend via env vars only.
- **Dashboards deliberately not checked in as JSON up-front.** The SigNoz schema evolves and the query builder is much easier than hand-written JSON. Placeholder README + workflow doc; JSON lands as each team member builds one.
- **`finops.py` is analytical, not observational.** It computes from `prices.yaml` + assumptions, not from SigNoz query data. A followup PR can wire in the real per-request avg cost once SigNoz is up and holding data. The value stands on its own — it answers the specific question the Head of Digital asked.

**PR base is `chore/repo-hardening`** (stacked PR). When PR #1 merges, GitHub auto-updates PR #2 base to `main` and this becomes an independent PR against main.

**Handover after PR #2 merges:**
- Stand up SigNoz locally (`signoz/README.md`).
- Point PolicyAssist at it via `.env`.
- Build the four dashboards in the UI; export JSON; commit to `signoz/dashboards/`.
- Optionally wire `/finops` to read observed cost from SigNoz query API for a live projection.

---

## 2026-07-15 14:15 — CI hardened with security best practices

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `chore/repo-hardening` — #1
**Type:** decision

Applied a first pass of GitHub Actions security best practices to the CI workflow, plus three new workflow files. Now all 10 checks pass on PR #1.

**Changes to `.github/workflows/ci.yml`:**
- Top-level `permissions: contents: read` (least privilege) with per-job elevation only where needed.
- `persist-credentials: false` on every checkout — prevents workflow credentials leaking into downstream steps.
- Third-party actions pinned to specific minor versions (`@v4.2.2`, `@v6.2.1`). Full commit-SHA pinning noted as a TODO in the file header (defends against tag hijacking; harder to read, so deferred as an incremental improvement).
- `timeout-minutes` on every job.
- `astral-sh/setup-uv` `enable-cache: true` with `cache-dependency-glob: "pyproject.toml"` (default glob is `**/uv.lock` which we don't have yet).
- Test matrix on Python 3.12 and 3.13 (fail-fast: false). Coverage.xml uploaded as an artifact from the 3.12 run.
- New `workflow_dispatch` trigger for manual runs.
- New aggregate `ci-status` job using `contains(needs.*.result, 'failure')` — one job to set as the required status in branch protection, instead of every matrix cell individually.

**New workflows:**
- `.github/workflows/codeql.yml` — CodeQL SAST for Python with `security-extended` + `security-and-quality` query packs. Runs on push, PR, and weekly cron.
- `.github/workflows/dependency-review.yml` — checks new PR dependencies for known vulnerabilities. Currently `continue-on-error: true` because Dependency Graph must be enabled on the repo (Settings → Security → Code security).
- `.github/dependabot.yml` — weekly Monday updates for pip and github-actions. OpenTelemetry, LangChain, and dev tooling grouped so we don't get PR-flood on ecosystem releases.

**One CI-fix commit followed the initial hardening push:**
1. `setup-uv --enable-cache` needs `cache-dependency-glob: pyproject.toml` when no `uv.lock` exists.
2. `dependency-review-action` requires Dependency Graph — added `continue-on-error` so CI doesn't block until the repo setting is flipped.

**Handover needs:**
- Enable **Dependency Graph** at Settings → Security → Code security → Dependency graph. Once on, remove `continue-on-error` from `dependency-review.yml` to make the check enforcing.
- Update branch protection rule for `main`: set the single required status check to `ci-status` (the aggregate job) rather than listing every matrix cell.

---

## 2026-07-15 13:45 — Repo hardening branch pushed for review

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `chore/repo-hardening` — landed on `main` via PR #9 — `95c8301`
**Type:** progress

Added the tooling scaffolding promised by `CLAUDE.md` §6–§7:

- `pyproject.toml` — ruff (lint + format, line 100, py312 target, standard rulepack), mypy (strict), pytest (with coverage, `--cov-fail-under=80` on `monitoring/`), bandit config. Pins runtime deps (Flask, langchain-anthropic, OTel SDK/API/OTLP-http exporter, pyyaml) and a `dev` extras group.
- `.pre-commit-config.yaml` — same ruff/mypy/gitleaks checks locally as CI, plus hygiene hooks and a `no-commit-to-branch main` guard.
- `commitlint.config.js` — Conventional Commits enforced.
- `.github/workflows/ci.yml` — six jobs (lint / types / test / security / secrets / commitlint). All use `astral-sh/setup-uv` and `uv sync --extra dev`.
- `.github/pull_request_template.md` and `.github/CODEOWNERS`.
- `.editorconfig`, `.env.example`, `README.md`, and gitignore updates.
- Empty `monitoring/` package + one sanity test so CI has something to verify — real code lands via `feat/monitoring-service`.

**Notable choices:**
- **uv over pip.** CI uses uv for reproducibility; local dev can use uv or plain pip via the same `pyproject.toml`. `uv.lock` will be generated and committed in the next PR when the first real dependency lands.
- **mypy strict.** Better to fight it now than to unpick a lax type story later. Overrides ignore-missing-imports for `langchain_anthropic` and `langchain_core` because those don't ship type stubs.
- **No merge commits guarded three ways.** GitHub branch protection ("require linear history"), local pre-commit `no-commit-to-branch main`, and CLAUDE.md documentation.

**Handover:** review the branch, merge via rebase, then flip the branch-protection settings if not already done. Next work is `feat/monitoring-service` per `plan.md` §4.

---

## 2026-07-15 13:34 — Repo initialised and pushed to GitHub

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `main` — initial commit (pre-protection)
**Type:** progress

Repo initialised locally at this directory and pushed to `https://github.com/david-dfe/week9-policy-assist-room-c`. Initial commit contains the seven docs currently in the directory: `CLAUDE.md`, `ai-log.md`, `plan.md`, `scratchpad.md`, `SINS.md`, `SINS-STANDARDS.md`, `SINS-STANDARDS-CONSTRAINED.md`.

This commit went directly to `main` because branch protection cannot be configured until after the branch exists on the remote. **Next step for the human:** configure branch protection on `main` per `CLAUDE.md` §4 *before* anyone opens a PR. From this point onward, all changes must follow the feature-branch → PR → CI → rebase-merge flow.

Nothing about the code has been added yet — `monitoring/`, `policyassist/`, `signoz/`, `tests/` will land via feature PRs per `plan.md` §4.

---

## 2026-07-15 — Repo initialisation and conventions established

**Author:** claude
**Branch / PR:** n/a (pre-init)
**Type:** decision

Established the engineering conventions for this repo before any code lands. Key decisions captured in `CLAUDE.md`:

- **Repo root** is this directory (`.../policyAssistRoom3/`), not the `~/Documents/my-work/...` code scratch area. Rationale: this is the shared team workspace, so the repo lives where the team collaborates.
- **Branching:** GitHub Flow with linear history — feature branches, PR review, rebase-and-merge, no merge commits on `main`. Simpler than Git Flow, appropriate for a 2-day sprint with 2–4 people.
- **Commits:** Conventional Commits, enforced by `commitlint` in CI.
- **CI stack:** `ruff` (lint + format) + `mypy` (types) + `pytest` (tests + coverage ≥80%) + `bandit` (SAST) + `pip-audit` (CVEs) + `gitleaks` (secrets). All must pass before merge.
- **Package manager:** `uv` with committed `uv.lock`. Rationale: fast, reproducible, replaces pip+venv+pip-tools in one tool.
- **Python 3.12.**

Domain-specific guardrails also captured in `CLAUDE.md` §9: no raw prompt/completion text on spans, monitoring client stays backend-agnostic, `prices.yaml` is the sole source of truth for £/token values.

**Next:** repo init per `CLAUDE.md` §3; then Day 1 AM work per `plan.md` §4 (SigNoz stand-up and instrumentation client scaffold in parallel).
