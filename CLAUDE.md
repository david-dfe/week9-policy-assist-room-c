# CLAUDE.md — engineering conventions for this repo

This file is loaded by Claude Code at the start of every session. Humans, please skim too.

Project: **PolicyAssist monitoring service** (see `plan.md`).
Team: Breakout Room 3, 2-day sprint.
Repo root: this directory (`.../policyAssistRoom3/`).

---

## 1. Golden rules

1. **Log every meaningful action in `ai-log.md`.** Format in §7. Newest entry at top.
2. **Never commit to `main` directly.** Branch → PR → CI green → rebase-merge.
3. **Rebase, do not merge.** Linear history only. No merge commits on `main`.
4. **Do not skip hooks or CI** (`--no-verify`, `[skip ci]`, force-push to shared branches). Fix the failure instead.
5. **Never commit secrets.** No `.env`, no API keys, no `chat_log.json` with real data. `pre-commit` and `gitleaks` will catch most, but you are the last line.

---

## 2. Repo layout

Existing (docs / analysis, committed as-is at repo init):

```
.
├── CLAUDE.md                       # this file
├── ai-log.md                       # rolling development log — see §7
├── plan.md                         # the implementation plan
├── scratchpad.md                   # team scratch space
├── SINS.md                         # standards notes
├── SINS-STANDARDS.md               # full standards analysis
└── SINS-STANDARDS-CONSTRAINED.md   # sprint-scoped standards
```

Added as the sprint progresses:

```
.
├── README.md                       # human-facing project overview
├── pyproject.toml                  # single source of truth for tooling config
├── uv.lock                         # locked dependency graph — committed
├── .pre-commit-config.yaml
├── .github/
│   ├── workflows/ci.yml
│   ├── pull_request_template.md
│   └── CODEOWNERS
├── .gitignore
├── .editorconfig
├── .env.example                    # every env var used by code — no real values
├── monitoring/                     # instrumentation client package
├── policyassist/                   # reference client (Flask app)
├── signoz/                         # dashboards-as-JSON, docker-compose config
└── tests/
```

The PolicyAssist prototype currently lives at `~/Documents/my-work/weeks/w09/breakoutroom3work/policyassist/`. Copy it into `./policyassist/` at repo init — do not symlink.

---

## 3. Repo initialisation (one-time)

```bash
cd /home/lab-admin/Documents/readwrite-classroom/breakout-collaborations/week9/policyAssistRoom3
git init -b main
git add CLAUDE.md ai-log.md plan.md SINS*.md scratchpad.md
git commit -m "chore: initial commit — plan and standards docs"
git remote add origin <team-remote-url>
git push -u origin main
```

Then, on GitHub (or equivalent), configure branch protection per §3 below **before** anyone opens a PR. Doing it after means the first few PRs will bypass the rules.

---

## 4. Branching strategy — GitHub Flow with linear history

- `main` is always deployable. Protected.
- **Feature branches only.** One branch = one PR = one topic.
- **Naming:** `<type>/<short-kebab-description>` where `<type>` ∈ `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`. Example: `feat/otel-client-package`, `fix/prices-yaml-loader`.
- Keep branches **short-lived** (< 1 day). If it's growing, split it.
- Rebase your branch onto `main` before opening a PR and before merging:
  ```
  git fetch origin
  git rebase origin/main
  git push --force-with-lease
  ```
  Always `--force-with-lease`, never bare `--force`.
- **Never rebase a branch someone else is working on.** Coordinate first.

### Branch protection on `main`

- Require pull request before merging.
- Require CI to pass (`ci` workflow, all jobs).
- Require at least one approving review.
- **Require linear history** — this is what enforces "no merge commits".
- Dismiss stale approvals on new commits.
- Restrict direct pushes to `main` to nobody (PR-only).

### Merging a PR

Use **rebase-and-merge** in the GitHub UI, or:
```
gh pr merge <number> --rebase --delete-branch
```
Never "Create a merge commit". Squash is acceptable only when the branch has noisy WIP commits — prefer clean rebased history where each commit stands on its own.

---

## 5. Commits — Conventional Commits

Format:
```
<type>(<scope>): <subject>

<body — the why, wrapped at 72 cols>

<footer — Refs #issue, BREAKING CHANGE: ...>
```

- **type**: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`.
- **scope**: `monitoring`, `policyassist`, `signoz`, `ci`, `deps`, etc.
- **subject**: imperative mood, lowercase, no trailing period, ≤ 72 chars.
- **body**: explain *why*, not *what* (the diff shows what).

Commit-message linting runs in CI. If it fails, fix the message with `git commit --amend` and force-push-with-lease.

Small atomic commits. If a diff has "and" in the natural summary, split it.

### Authorship — Claude must not self-attribute

When Claude creates a commit on behalf of a user, the commit is **the user's**. Do not add a `Co-Authored-By: Claude ...` trailer, do not put "Generated with Claude Code" in the body, and do not set the author to anything other than the user's configured git identity. If you are pair-programming with a human, only add `Co-Authored-By:` for the *human* pair, never for yourself. This applies to PR descriptions as well — no "🤖 Generated with Claude Code" footer.

---

## 6. CI pipeline — `.github/workflows/ci.yml`

Every PR runs, in parallel where possible:

| Job | Tool | Fails on |
|---|---|---|
| Lint | `ruff check .` | any warning |
| Format | `ruff format --check .` | any diff |
| Type check | `mypy monitoring policyassist` | any error |
| Test | `pytest --cov --cov-fail-under=80` | any failure or <80% coverage |
| Security (SAST) | `bandit -r monitoring policyassist` | HIGH severity |
| Dependencies | `pip-audit` (or `uv pip audit`) | any known CVE |
| Secrets | `gitleaks detect --no-git -v` | any finding |
| Commit lint | `commitlint` on PR title + commits | non-Conventional |

CI must pass before merge. **Do not add exceptions to make CI pass — fix the code.**

---

## 7. Local dev

- **Python 3.12.** Managed via `uv` (or `pyenv` if `uv` is unavailable).
- **Package manager: `uv`.** All installs via `uv pip install`; lockfile is `uv.lock`, committed.
- **Editor:** anything, but respect `.editorconfig` (LF, UTF-8, 4-space Python indent, trim trailing whitespace).
- **Pre-commit hooks:**
  ```
  uv pip install pre-commit
  pre-commit install
  ```
  Runs `ruff`, `ruff format`, `mypy` (on staged files), `gitleaks`, and end-of-file/trailing-whitespace fixers on every commit. Same checks as CI so you catch failures locally.
- **Running tests locally:** `uv run pytest`.
- **Running the app:** see `policyassist/README.md`.
- **Environment variables:** `.env.example` is committed; `.env` is gitignored. Every env var used by code must appear in `.env.example` with a placeholder value.

---

## 8. `ai-log.md` — how to use it

`ai-log.md` is the running record of what got done, by whom (human or AI), and why. It complements git history — git tells you *what changed*, the log tells you *what was being attempted, what was decided, and what was learned*. If something is only in a Slack DM or a chat transcript, it's not persisted; put it in the log.

### When to append

- Starting a non-trivial task (>30 min of work).
- Making a design decision that isn't self-evident from the code.
- Hitting a blocker or resolving one.
- Finishing a PR — link the PR.
- Any time future-you would want to know "why did we do it this way".

### Entry format

Newest at the top. Every entry uses this shape:

```markdown
## YYYY-MM-DD HH:MM — <one-line summary>

**Author:** <name or "claude">
**Branch / PR:** `feat/xxx` — #NN
**Type:** decision | progress | blocker | handover

<Body: what was done, what was decided, why. Link commits/PRs. Note anything a future contributor should not have to rediscover.>
```

### For Claude specifically

- Read the top ~10 entries at the start of every session — that's your context on what's in flight.
- Append an entry *before* you push, not after — so if you're interrupted the log still reflects the state.
- If you make a decision that contradicts something earlier in the log, say so explicitly and link the prior entry.
- Do not put secrets, real user data, or verbatim officer questions in the log.

---

## 9. Project-specific guardrails

Beyond the generic engineering standards above, this project has three domain rules that come out of `plan.md` and the standards analysis:

1. **No question or answer text on OTel spans.** Tokens, model, cost, latency, error class, session id — yes. Raw prompt or completion content — no. See `plan.md` §6 (deferred: data classification review).
2. **The instrumentation client must be backend-agnostic.** No SigNoz-specific code in `monitoring/`. Backend swap = env var change only.
3. **`prices.yaml` is the only place £/token values live.** No hardcoded numbers in code, tests, dashboards, or the FinOps page. Add new models by editing this file.

---

## 10. Out of scope for this sprint

See `plan.md` §6. Do not silently expand scope. If work drifts into out-of-scope territory, log it in `ai-log.md` and raise it with the team before continuing.
