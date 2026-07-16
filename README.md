# PolicyAssist monitoring service

OpenTelemetry-based LLM observability for PolicyAssist and future Home Office apps.

Every LLM call in an instrumented app emits an OTLP span carrying tokens, model, latency, and a computed £ cost. Spans land in a self-hosted SigNoz backend where the team gets dashboards, alerting, and traces out of the box. A standalone FinOps page projects monthly spend at production volume.

---

## Repository layout

| Path | What it contains |
|---|---|
| `monitoring/` | Instrumentation client package — drop into any Python app |
| `policyassist/` | Reference client (Flask app) already wired up |
| `signoz/` | Instructions for standing up the SigNoz backend |
| `plan.md` | Implementation plan and rationale |
| `CLAUDE.md` | Engineering conventions — branching, commits, CI |
| `ai-log.md` | Rolling record of decisions and progress |

---

## Prerequisites

- Python 3.12
- [`uv`](https://github.com/astral-sh/uv) — fast Python package manager
- An Anthropic API key (for running PolicyAssist)
- Docker Engine 20+ and Docker Compose v2 (for SigNoz)

---

## 1. Install dependencies

```bash
# Install uv (once, if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all runtime and dev dependencies
uv sync --extra dev

# Install pre-commit hooks so lint/format/secret-scan run on every commit
uv run pre-commit install
```

---

## 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in the values:

```
ANTHROPIC_API_KEY=sk-ant-...          # required to run PolicyAssist
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # SigNoz default
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_SERVICE_NAME=policyassist
```

The monitoring client reads all OTel config from environment variables — no code changes needed to point it at a different backend.

---

## 3. Start SigNoz (observability backend)

SigNoz receives the spans your app emits and provides dashboards, traces, and alerting.

```bash
# 1. Install foundryctl (SigNoz's deployment tool)
curl -fsSL https://signoz.io/foundry.sh | bash

# 2. Create a deployment descriptor
cat > casting.yaml <<'EOF'
apiVersion: v1alpha1
kind: Installation
metadata:
  name: signoz
spec:
  deployment:
    flavor: compose
    mode: docker
EOF

# 3. Deploy the stack
foundryctl cast -f casting.yaml
```

Wait for the containers to start, then open **http://localhost:8080**. On first run you will be prompted to create an admin account.

Full SigNoz setup, verification, and dashboard instructions are in [`signoz/README.md`](signoz/README.md).

**No Docker?** Use Honeycomb free tier instead (data leaves the org boundary — demo only):

```
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<api-key>
```

---

## 4. Run PolicyAssist

PolicyAssist is a Flask chat app for Border Force officers. It answers questions against an operational manual using Claude.

### Dev server (auto-reload, single worker)

```bash
uv run flask --app policyassist.app run --port 5000
```

Open **http://localhost:5000** in your browser. Type a question and submit — the app calls Claude, persists the conversation to `policyassist/chat_log.json`, and returns an answer.

### Production-grade server

Never run the Flask dev server in production. Use gunicorn via the top-level `Makefile`:

```bash
make run
```

This starts gunicorn with **four worker processes** bound to `127.0.0.1:5000` and points at `policyassist.app:app`. Four workers is a safe default for a single-node deployment; tune with the `-w` flag if your host has more cores or you observe queueing. The app module never calls `app.run()` at import time, so `gunicorn` picks up a clean WSGI object.

Every request automatically emits an OTLP span to SigNoz. Within a second of asking a question you should see a new trace under **Traces → Filter by `service.name = policyassist`**.

> The app is intentionally minimal — it carries the prototype's behaviour (global shared history, no session isolation, no retries) unchanged. Application-level improvements belong to a separate workstream.

---

## 5. Run the FinOps projection page

The FinOps page answers "what would our £14,200/month bill become with prompt caching?" It computes naive vs cached monthly spend from a workload profile.

```bash
uv run flask --app monitoring.finops run --port 5001
```

Open **http://localhost:5001**.

Every assumption on the page (queries/day, tokens per request, cache hit ratio, model) can be overridden via query string:

```
http://localhost:5001?queries_per_day=3000&cache_hit_ratio=0.85&model=claude-haiku-4-5
```

A JSON API is also available:

```bash
curl http://localhost:5001/api/projection
curl "http://localhost:5001/api/projection?queries_per_day=3000"
```

Default workload assumptions (all overridable):

| Parameter | Default |
|---|---|
| `queries_per_day` | 6,000 |
| `working_days_per_month` | 22 |
| `system_prompt_tokens` | 1,200 |
| `history_tokens_per_request` | 4,000 |
| `user_question_tokens` | 20 |
| `response_tokens` | 200 |
| `cache_hit_ratio` | 0.90 |
| `model` | `claude-sonnet-4-5` |

---

## 6. Instrument a new app

To add monitoring to any other Python app:

```python
from monitoring import instrument_app, traced_llm_call

instrument_app(service_name="your-app")   # call once at startup

# wrap each LLM call
with traced_llm_call(model="claude-sonnet-4-5", session_id=session_id) as span:
    response = llm.invoke(messages)
    span.record_usage(response)
```

Each call emits a span with `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `cost.gbp`, and more. See [`monitoring/README.md`](monitoring/README.md) for the full attribute list, model price configuration, and backend-swap instructions.

---

## 7. Run the tests

```bash
uv run pytest
```

The suite covers cost calculation, FinOps projections, and instrumentation behaviour (46 tests, ~93% coverage). Coverage must stay at or above 80% — `pytest` will fail otherwise.

---

## Adding a new model

Edit `monitoring/prices.yaml` — that is the **only** place price values live:

```yaml
your-new-model-id:
  input_per_million_gbp: 2.40
  output_per_million_gbp: 12.00
  cache_write_per_million_gbp: 3.00
  cache_read_per_million_gbp: 0.24
```

No code changes needed. The FinOps page and cost calculation pick it up automatically.

---

## Contributing

Read [`CLAUDE.md`](CLAUDE.md) before opening a PR. Short version:

- Feature branches only (`feat/`, `fix/`, `chore/`, etc.) — no direct commits to `main`
- [Conventional Commits](https://www.conventionalcommits.org/) enforced by `commitlint`
- Rebase-and-merge only — no merge commits
- CI must pass: lint, format, types, tests (≥80% coverage), bandit, pip-audit, gitleaks
- Append an entry to `ai-log.md` for any non-trivial decision
