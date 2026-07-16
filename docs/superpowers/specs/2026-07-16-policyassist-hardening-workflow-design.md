# PolicyAssist hardening — workflow design

**Date:** 2026-07-16
**Status:** Design approved; pending user review before `writing-plans`.
**Feature spec:** `plan-policyassist.md` (owned by the project; NOT modified by this workflow).
**Orchestration plan:** `~/.claude/plans/we-are-looking-to-parsed-hartmanis.md` (agent-side; the runtime plan file).

## 1. Purpose

`plan-policyassist.md` is the feature spec for hardening the PolicyAssist Flask reference client (session isolation, prompt caching, input validation, error surfacing, retries, prod server, evals). It already decomposes the work into 9 slices (A–J) grouped into 5 PRs with explicit parallelization notes at `plan-policyassist.md:305`.

This document is the **workflow design** that layers on top of that feature spec: how the work is executed, who orchestrates, where subagents run, and how shared state is coordinated. It locks in two design decisions that `plan-policyassist.md` left open.

## 2. Non-goals

- Change any content in `plan-policyassist.md`, `CLAUDE.md`, `monitoring/`, `signoz/`, `prices.yaml`.
- Introduce new engineering conventions beyond those in `CLAUDE.md`.
- Author `tests/evals/golden.yaml` content — humans write fact/answer pairs from `manual.txt`; this workflow only supplies the schema.

## 3. Architecture

**Pattern:** Workflow (deterministic DAG), not agent. The main Claude session is a **deterministic orchestrator** that dispatches subagents against pre-committed contracts and pauses at human-gated verification points. Subagents run in git worktrees and never touch `main`.

**Skill layer:** `obra/superpowers` (installed via `/plugin install superpowers@claude-plugins-official`). Skills used:

| Skill | Where it fires |
|---|---|
| `brainstorming` | Wave 0 setup, only for genuinely ambiguous items (this document) |
| `writing-plans` | Once, at end of setup, to produce the authoritative task tree |
| `using-git-worktrees` | Every parallel slice — one worktree per branch |
| `test-driven-development` | Every slice, RED before GREEN |
| `subagent-driven-development` | Each slice dispatch |
| `dispatching-parallel-agents` | Wave 1 and Wave 2 concurrent dispatches |
| `requesting-code-review` | Pre-impl (on RED tests + interface) and pre-merge |
| `receiving-code-review` | When a review returns changes |
| `systematic-debugging` | Any test that flakes twice, or a rebase conflict |
| `verification-before-completion` | Before any "done" claim |
| `finishing-a-development-branch` | Branch integration decision |
| `executing-plans` | Batch runner between human checkpoints |

## 4. The DAG — 4 waves

```
Wave 0:  chore/policyassist-shared-constants           [serial; blocks all]
Wave 1:  feat/policyassist-sessions (A+B)   ∥   feat/policyassist-caching (C)
Wave 2:  feat/policyassist-reliability (D+E+F)  ∥   feat/policyassist-prod-server (G+H)
Wave 3:  feat/policyassist-evals (I+J)                 [serial; depends on C, D, F]
```

- Wave 1 parallelism explicit at `plan-policyassist.md:305`.
- Wave 2 parallelism safe because G is orthogonal and H shares `MAX_QUESTION_LENGTH` with D but reads from `config.py` landed in Wave 0.
- Wave 3 lands last so evals score the finished app (`plan-policyassist.md:303`).

## 5. Locked design decisions

Both approved 2026-07-16.

### Decision 1 — C1 spike (LangChain `cache_control` propagation)

**Chosen:** Option (a) — run a 60-minute spike at Wave 1 start.

The spike is a standalone script that:
1. Instantiates `ChatAnthropic(model="claude-sonnet-4-5", ...)` with the existing `SYSTEM_PROMPT` from `policyassist/app.py`.
2. Sends two identical `[SystemMessage(cache_control={"type":"ephemeral"}), HumanMessage("test")]` calls.
3. Asserts `response.usage_metadata["cache_read_input_tokens"] > 0` on the second call.

Result gates Slice C's contract:
- **Spike passes** → Slice C proceeds with D1 (LangChain path), F uses F2 (Tenacity).
- **Spike fails** → Slice C flips to D2 (native Anthropic SDK for the LLM call), F flips to F1 (SDK built-in retries) *before* Wave 1 dispatch. Half-day rework budgeted; called out at `plan-policyassist.md:328`.

**Rationale:** 60 min is a rounding error in a 2-day sprint. Preempting D2 permanently diverges from `policyassist/app.py`'s current LangChain-native style for no risk-reduction gain.

### Decision 2 — Slice I pre-commit canary

**Chosen:** Option (c) — no pre-commit canary; evals run on demand only.

Slice I ships:
- `tests/evals/golden.yaml` — schema only (human authors content).
- `tests/evals/run_evals.py` — CLI runner; substring/regex scoring per `plan-policyassist.md` (J1).
- `.github/workflows/evals.yml` with `on: workflow_dispatch` only.
- **No `pre-commit` hook** invoking evals.

**Rationale:** For a 2-day sprint, gating on evals at commit time is friction with no clear return. The Day-2 success criterion (`plan-policyassist.md:339`) is met by running `python tests/evals/run_evals.py` once before demo. vcrpy is worth revisiting *after* the sprint if evals become a regression-gate on `main`.

## 6. Per-slice contract (what the orchestrator hands each worker)

Every subagent dispatch supplies:
- **Slice ref** (line range in `plan-policyassist.md`).
- **Branch name** from `plan-policyassist.md:299-303`.
- **Rebase base** (`origin/main` SHA at dispatch time).
- **Files in scope** — explicit allow-list.
- **Files out of scope** — explicit deny-list (e.g. Slice C cannot touch `policyassist/history.py`).
- **RED tests first** (TDD skill) — named tests derived from the slice's success-criteria bullet in `plan-policyassist.md:334-342`.
- **Done ≡** the specific success bullet + green CI (ruff, mypy strict, pytest ≥80%, bandit, pip-audit, gitleaks per CLAUDE.md §6).
- **Pre-impl gate:** `requesting-code-review` on RED tests + interface.
- **Pre-merge gate:** `requesting-code-review` on diff.
- **Draft `ai-log.md` entry** returned as task output.

## 7. Shared-state coordination

- **Config constants:** exclusively in `policyassist/config.py` (Wave 0). Workers import; never redefine.
- **HistoryStore interface:** owned by Slice A. Slice C reads via the exported interface if needed; C's contract lists `history.py` as out-of-scope.
- **`ai-log.md`:** orchestrator-only. Written after each PR merges, newest-on-top (CLAUDE.md §8). Subagents return a draft entry; orchestrator concatenates.
- **Worktrees:** `using-git-worktrees` skill; one worktree per active branch. Wave 1's two branches never share a filesystem checkout.

## 8. Merge and rebase discipline

CLAUDE.md §4 mandates rebase-only, `--force-with-lease`, linear history. Orchestrator owns all rebases; subagents never touch `main`.

- **Wave 1 order:** A+B merges first (foundation); C rebases onto new `main` and re-runs CI before its merge.
- **Wave 2 order:** D+E+F merges first (larger surface); G+H rebases second.
- **Between waves:** `git fetch origin && git rebase origin/main && git push --force-with-lease` inside each active worktree.
- **Conflict triage:** any `config.py` conflict = Wave 0 contract violation, blocks merge until root-caused. Other conflicts go through `systematic-debugging`.
- **Known rebase hotspot:** `policyassist/app.py:46-52` (SystemMessage construction). Slice C's `cache_control` kwarg re-applied on top of Slice A's session-scoped message construction manually.

## 9. Human-gated verification checkpoints

Orchestrator pauses; human runs the checks in `plan-policyassist.md:334-342`:

| After | Check |
|---|---|
| Wave 1 merges | Two-browser session-isolation demo; SigNoz shows `cache_read_input_tokens > 0` on second request |
| Wave 2 merges | Deliberate API failure → red banner (no hang); `gunicorn -w 4 policyassist.app:app` binds and serves |
| Wave 3 merges | `python tests/evals/run_evals.py` prints overall score ≥ 85% |

None are automatable; none skippable for the Day-2 demo.

## 10. Failure modes

- **CI red on a worker branch:** worker fixes on-branch. Two consecutive failures → orchestrator invokes `systematic-debugging` with CI log + RED tests. Never `--no-verify`.
- **C1 spike fails:** Slice C flips to D2, F flips to F1, before Wave 1 dispatch.
- **A/B file-store race under gunicorn** (`plan-policyassist.md:329`): `fcntl.flock` on write in Slice A. If flaky under load, follow-up PR switches to SQLite (B2).
- **Eval flapping** (`plan-policyassist.md:330`): golden YAML supports pattern lists per question + "canonical answer" field.

## 11. Critical files (added or modified)

| Path | Status | Owner |
|---|---|---|
| `policyassist/config.py` | new | Wave 0 |
| `tests/test_config.py` | new | Wave 0 |
| `policyassist/history.py` | new | Slice A |
| `tests/test_history.py` | new | Slice A |
| `policyassist/app.py` | modified | A, C, D, E, F |
| `policyassist/templates/index.html` | modified | A (session UI), E (red banner) |
| `pyproject.toml` | modified | F (tenacity or SDK config), G (gunicorn) |
| `tests/evals/golden.yaml` | new — schema only | Slice I |
| `tests/evals/run_evals.py` | new | Slice I |
| `.github/workflows/evals.yml` | new | Slice I |
| `ai-log.md` | appended | orchestrator only |

## 12. Verification (end-to-end)

- After Wave 0: `pytest tests/test_config.py -v` green; `python -c "import policyassist.config"` succeeds.
- After Wave 1: two Chrome profiles hit `http://127.0.0.1:5000` and hold independent conversations. SigNoz shows a span with `gen_ai.usage.cache_read_input_tokens > 0` on the second question.
- After Wave 2: unset `ANTHROPIC_API_KEY` mid-session; `POST /ask` returns 502 with a red-banner UI; `gunicorn -w 4 policyassist.app:app` binds and serves.
- After Wave 3: `python tests/evals/run_evals.py` prints table with overall ≥ 0.85.
- Final: `git log --oneline main..HEAD` empty; linear history preserved.

## 13. Alternatives considered

- **Fully agentic orchestrator** — rejected. DAG is knowable up front; agent flexibility buys nothing and loses CLAUDE.md's PR-checkpoint discipline.
- **One agent per slice (9 workers)** — rejected. Shared-constant + rebase coordination overhead exceeds the wins on a codebase this small.
- **Single agent, sequential** — viable but slower; not chosen because user asked for multi-agent and the plan already declares parallel points.
- **Skipping superpowers** — viable but requires reinventing brainstorming/TDD/review scaffolding by hand.
