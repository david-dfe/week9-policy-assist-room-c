# PolicyAssist monitoring service

OpenTelemetry-based LLM observability for PolicyAssist and future Home Office apps.

- **What it does:** every LLM call in an instrumented app emits an OTLP span carrying tokens, model, latency, and a computed £ cost. Spans land in a self-hosted SigNoz backend where the team gets dashboards, alerting, and traces out of the box. A small FinOps page projects monthly bill at production volume.
- **What it isn't:** feature-complete PolicyAssist. This sprint delivers the monitoring plane. Application-level improvements (prompt caching, session management, retries) belong to a separate workstream that instruments *against* this service.

## Where to look

| File | For |
|---|---|
| [`plan.md`](plan.md) | Implementation plan and rationale |
| [`CLAUDE.md`](CLAUDE.md) | Engineering conventions — branching, commits, CI, local dev |
| [`ai-log.md`](ai-log.md) | Rolling record of decisions and progress |
| [`SINS-STANDARDS-CONSTRAINED.md`](SINS-STANDARDS-CONSTRAINED.md) | Sprint-scoped standards analysis |
| `monitoring/` | The instrumentation client package |
| `policyassist/` | Reference client (Flask app) |
| `signoz/` | Backend docker-compose + dashboards-as-JSON |

## Getting started

Full local dev instructions in [`CLAUDE.md`](CLAUDE.md) §7. Quick version:

```bash
# 1. Install uv (once)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install deps
uv sync --extra dev

# 3. Install pre-commit hooks
uv run pre-commit install

# 4. Copy env template
cp .env.example .env  # fill in ANTHROPIC_API_KEY

# 5. Run tests
uv run pytest
```

## Contributing

Read [`CLAUDE.md`](CLAUDE.md) first. Short version: feature branches, Conventional Commits, rebase-and-merge, CI must pass, `ai-log.md` gets an entry for anything non-obvious.
