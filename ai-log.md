# AI Development Log

Rolling record of design decisions, progress, blockers, and handovers for the PolicyAssist monitoring service. See `CLAUDE.md` §8 for the format and when to append.

**Rules of the log:**
- Newest entry at the top.
- One entry per meaningful unit of work (>30 min, or any non-obvious decision).
- Link commits and PRs — the log points *to* git; it does not duplicate it.
- No secrets, no real user data, no verbatim officer questions.

---

## 2026-07-15 13:45 — Repo hardening branch pushed for review

**Author:** claude (on behalf of david-dfe)
**Branch / PR:** `chore/repo-hardening` — PR pending push
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
