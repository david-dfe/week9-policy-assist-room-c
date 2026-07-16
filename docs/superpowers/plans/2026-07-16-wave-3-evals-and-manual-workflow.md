# Wave 3 — Slices I + J: Evals + Manual Update Workflow

> **For agentic workers:** subagent-driven; TDD-first for the runner; commit types conventional.

**Goal:** Make PolicyAssist's answer quality measurable via a golden-set eval harness (Slice I) and document the manual-update workflow (Slice J).

**Branch:** `feat/policyassist-evals`. Single subagent.

**Tech Stack:** PyYAML · pytest (for runner-logic unit tests) · Anthropic API (only invoked on demand, not in CI-per-PR).

## Global Constraints

- **In scope:** `tests/evals/golden.yaml` (new), `tests/evals/run_evals.py` (new), `tests/evals/__init__.py` (new empty), `tests/evals/test_runner.py` (new — unit tests for scoring logic only, no live API), `.github/workflows/evals.yml` (new — `workflow_dispatch` trigger only), `policyassist/README.md` (new — includes Slice J's manual-update section), `README.md` (add pointer to `policyassist/README.md`).
- **Out of scope:** `monitoring/**`, `signoz/**`, `prices.yaml`, `plan-policyassist.md`, `CLAUDE.md`, `policyassist/app.py`, `policyassist/history.py`, `policyassist/config.py`, `docs/**`, `ai-log.md`, root `.github/workflows/ci.yml`.
- Read `EVAL_PASS_THRESHOLD` from `policyassist.config` (default 0.85).
- Never `--no-verify`; never Claude co-author trailer; rebase-and-merge only.
- Python 3.12; venv `~/.cache/policyassist-venv`.

## Slice I — Golden set + runner + workflow_dispatch CI

### 1. `tests/evals/golden.yaml`

Author 15 fact/answer pairs derived from `policyassist/manual.txt` (104 lines). Each entry supports multiple acceptable patterns for robustness against paraphrasing.

Schema:

```yaml
- id: welfare-checks-interval
  question: How often must welfare checks be recorded in a short-term holding room?
  # A list of substring OR regex patterns; a case-insensitive match against
  # ANY of these counts as pass. Regex patterns start with 're:'.
  expect_any:
    - "30 minutes"
    - "every 30"
    - "re:every\\s+thirty\\s+min"
  # Canonical form used on the demo dashboard.
  canonical: "Every 30 minutes."
  # Optional: manual section this fact comes from.
  section: "4.3"
```

Cover these facts (derived from manual.txt; subagent MUST re-read manual.txt and derive its own set — do not blindly copy this list):

1. Welfare check interval (30 min, §4.3)
2. Max continuous short-term holding time (24 hours, §4.1)
3. Water/refreshments interval in holding room (no more than 2 hours, §4.2)
4. DHO referral for expired documents (yes, §1.2)
5. Queue-time threshold for opening ePassport gates (45 min, §2.1)
6. Case Referral System log deadline (1 hour, §3.2)
7. Unaccompanied minors referral (Safeguarding Lead, §1.4)
8. Cash declaration threshold (£10,000 — check §5)
9. DHO unavailable escalation (Regional Operations Centre after 20 min, §3.3)
10. DHO review cadence for prolonged holding (4 hours, §4.4)
11. ETA electronic verification fallback (manual via Border Crossing system, §1.3)
12. ePassport gates during outage (closed — check §6 if present, otherwise say "not covered" and skip this entry with a placeholder pattern that will fail — better to drop the entry than fabricate)
13. Port Duty Manager authority for closing staffed desks (yes/authorisation required, §2.2)
14. Officer ID on welfare check record (yes, §4.3)
15. Priority lane target passengers (mobility/medical/infants, §2.3)

**Subagent responsibility:** verify each fact against the actual manual.txt before including. If a fact isn't present, drop the entry — do NOT fabricate.

### 2. `tests/evals/run_evals.py`

CLI tool with this shape:

```python
#!/usr/bin/env python3
"""Runs the golden-set evals against real Claude.

  python tests/evals/run_evals.py [--golden PATH] [--threshold FLOAT] [--json]

Costs real money (~£0.05 per full run at Sonnet 4.5). Prints a pass/fail
table plus overall pass rate. Exits non-zero if the pass rate is below
the threshold.
"""
```

Requirements:
- Reads `tests/evals/golden.yaml` by default; `--golden PATH` to override.
- Threshold defaults to `policyassist.config.EVAL_PASS_THRESHOLD`; `--threshold` to override.
- For each entry: instantiates `ChatAnthropic` with the SAME `SYSTEM_PROMPT_BLOCK` shape used by the production app (import from `policyassist.app`). Send `[SystemMessage(content=[SYSTEM_PROMPT_BLOCK]), HumanMessage(content=question)]`. No history — evals are stateless per question.
- Score: case-insensitive substring or regex (patterns prefixed with `re:`) match against `.content` of the response.
- Print a table: `id | pass | reason` where reason is the first matched pattern (or the response snippet on fail).
- Print `Overall: X / N (Y%)`.
- Exit code `0` if pass rate ≥ threshold, `1` otherwise.
- Support `--json` for structured output (used by CI later).
- **No history persistence** — do NOT touch `HistoryStore` or write to `chat_log/`.

### 3. `tests/evals/test_runner.py` — unit tests (offline, no API)

Cover only the scoring/parsing logic. Never invoke Claude in these tests.

- `test_substring_pattern_matches_case_insensitive`
- `test_regex_pattern_matches`
- `test_no_match_returns_fail`
- `test_empty_expect_any_treated_as_placeholder_and_fails`
- `test_load_golden_returns_list_of_dicts`
- `test_score_returns_pass_count_and_total`

Use a monkeypatched "LLM" that returns canned answers so the runner logic can be exercised without a network call.

### 4. `.github/workflows/evals.yml`

Trigger: `workflow_dispatch` only. **Not** on `push` or `pull_request` (per plan-policyassist.md:235 — costs money).

Job steps:
1. Checkout.
2. Set up uv + Python 3.12 (mirror the existing CI workflow's setup).
3. Install runtime deps: `uv sync --extra dev`.
4. Run: `uv run python tests/evals/run_evals.py --json` with `ANTHROPIC_API_KEY` from repository secrets.
5. Upload the JSON output as an artefact.
6. Fail the job if exit code != 0.

Note: this workflow will not run automatically on this PR. The subagent verifies the runner works via one hand-invoked run in the worktree.

## Slice J — Manual update workflow (docs only)

### `policyassist/README.md`

Create this new file with the following top-level sections:

1. **What PolicyAssist is** — one paragraph. Point back to the root `README.md` for install/run.
2. **Manual update workflow** — the concrete procedure:
   1. Edit `policyassist/manual.txt` on a feature branch (`docs/manual-vN`).
   2. Run the eval suite: `uv run python tests/evals/run_evals.py`. Expect some cases to change (new policy = new correct answer).
   3. Update `tests/evals/golden.yaml` accordingly. Add new entries for new policies; remove entries for removed policies.
   4. Re-run evals. Must pass at ≥ `EVAL_PASS_THRESHOLD` before merge.
   5. Open PR. Reviewer manually triggers the `evals` workflow via `gh workflow run evals` or the Actions UI. Attach the JSON artefact link to the PR.
   6. On merge, note in `ai-log.md`: "manual updated to vN; first requests after deploy pay uncached prices while Anthropic rebuilds the cache. Not an anomaly."

3. **Handover items** — mirror the "out of scope" bullets from `plan-policyassist.md:309-322` so the next writer of `ai-log.md` doesn't treat them as bugs:
    - Home Office SSO / 2FA (real auth).
    - Encryption at rest for the conversation store.
    - DPIA covering officer query content.
    - ATRS registration.
    - Anthropic DPA review, data residency assessment.
    - Formal procurement through CCS framework.
    - Full prompt injection prevention (NCSC: not achievable).

### Root `README.md` update

Add one line to the existing "Repository layout" table or nearby section: `| policyassist/README.md | PolicyAssist-specific docs and manual-update workflow |`. Do NOT rewrite the root README.

## Verification checklist

- `pytest` full suite green; monitoring coverage ≥ 80% (untouched).
- `ruff check .`, `ruff format --check .`, `mypy monitoring`, `bandit -r monitoring policyassist -c pyproject.toml` all clean.
- **Live eval smoke test** (one-off, spends ~£0.05): `uv run python tests/evals/run_evals.py` — should print the table and show overall pass rate. It's OK if the rate is below 0.85 initially; that means the golden set needs tuning, which is the next iteration's job. The subagent should report the actual rate observed.
- `gh workflow list` shows the new `evals.yml` workflow.

## PR body

Title: `feat(evals): golden set, runner, workflow_dispatch job, and manual update workflow`

Body sections:
- Summary (three bullets: golden.yaml, runner, workflow / plus the docs).
- Verification (checkboxes for the CI-equivalent checks + the actual eval pass rate observed).
- Ongoing note: the initial pass rate is a baseline, not a target — the golden set should evolve as the manual and prompt change.
- Reviewer checklist: read `tests/evals/golden.yaml` and sanity-check every fact against `policyassist/manual.txt` before merging.
