# Plan — Monitoring Service

**Team:** PolicyAssist / Breakout Room 3
**Scope:** 2-day sprint. **Monitoring service only** — this plan does not cover changes to the PolicyAssist app beyond the minimum instrumentation needed to prove the service works. Prompt caching, session management, evals, retries, and gunicorn belong to a separate workstream and are out of scope here.
**Deliverable:** A running observability backend that any Home Office app can point at over OTLP, with LLM-aware dashboards, cost enrichment, alerts, and a small FinOps projection page. PolicyAssist is wired up as the reference client to demonstrate the end-to-end path.

---

## 1. Why this shape

The brief calls for *"a standalone cost-monitoring service with its own API and dashboard that other teams could point their apps at — the ambitious version is a real product."*

A real product means:

- **OpenTelemetry as the wire format.** OTLP is the industry standard. GenAI semantic conventions exist (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, cache-token attributes). Future apps instrument once and point at any OTLP backend — no bespoke schema to version and support.
- **SigNoz as the backend.** OTLP-native, ClickHouse-backed, self-hostable via docker-compose. Traces, metrics, dashboards, and alerting come out of the box.
- **A tiny bespoke FinOps page.** The one thing we hand-build is the "naive vs post-caching monthly bill at 6,000 q/day" projection — the specific FinOps artefact the brief asks for that doesn't have a natural home in a generic observability UI.

Rejected alternative: bespoke Flask API + hand-rolled dashboard. Rejected reason: half the code duplicates what SigNoz gives free, and it locks other teams into our schema.

Alternatives noted in §5: Langfuse if LLM-native views matter more than general observability; Honeycomb free tier if Docker is a hard blocker.

---

## 2. What we are building

### 2.1 The backend — SigNoz

Standard docker-compose install from the SigNoz repo. Runs on a team member's machine or a small cloud VM. Accepts OTLP over HTTP/gRPC on the standard ports. Bearer token via `OTEL_EXPORTER_OTLP_HEADERS` for ingest auth.

### 2.2 Instrumentation client

A `monitoring/` package (published as `policymetrics-client` or vendored alongside PolicyAssist for now) that gives other teams a one-import path to instrumented LLM calls:

```python
from monitoring import instrument_app, traced_llm_call

instrument_app(service_name="policyassist")

with traced_llm_call(model=MODEL, session_id=session_id) as span:
    response = llm.invoke(messages)
    span.record_usage(response)   # extracts tokens + cache tokens
                                  # computes cost.gbp from prices.yaml
                                  # sets all gen_ai.* attributes
```

Under the hood: OTel SDK setup, OTLP exporter, GenAI semantic-convention attributes, cost enrichment from `prices.yaml`, error/exception capture on the span.

Try **OpenLLMetry (`traceloop-sdk`)** first — it monkey-patches Anthropic/LangChain to emit these spans automatically. If it works cleanly on our LangChain version, ship it as the recommended path and keep the manual helper as the fallback for apps not using LangChain.

### 2.3 Cost enrichment

A `prices.yaml` shipped with the client:

```yaml
claude-sonnet-4-5:
  input_per_million_gbp: 2.40
  output_per_million_gbp: 12.00
  cache_write_per_million_gbp: 3.00
  cache_read_per_million_gbp: 0.24
```

`compute_cost()` reads this and returns £ for a given usage payload; the value is set as a `cost.gbp` span attribute. Prices pinned; USD→GBP rate documented as an assumption. New models are added by editing this file — no code change.

### 2.4 Dashboards — checked into the repo as JSON

Built in the SigNoz UI, exported as JSON, committed under `signoz/dashboards/`. Restorable on any fresh install.

- **Cost:** £ per hour/day; £ per session (top 10); cost split by cache-read vs uncached input tokens.
- **Usage:** requests/min, tokens in/out over time, cache hit ratio.
- **Reliability:** error rate by exception class, p50/p95/p99 latency, timeout rate.
- **Per-app breakdown:** stacked £ by `service.name` — so when a second app is added, its usage shows up automatically.

### 2.5 Alerts

SigNoz native, defined alongside dashboards:

- Daily spend > threshold (£X/day).
- Error rate > 2% over 5 min.
- p95 latency > 5s over 5 min.

### 2.6 The FinOps projection page

One small Flask route (`/finops`) served alongside — or as part of — the monitoring service:

- Reads recent per-request avg cost from SigNoz's query API.
- Displays: **naive** £/month at 6,000 q/day (uncached, current model), **projected** £/month assuming prompt caching hits on the static system prompt portion, and **actual** current run-rate from live data.
- Shows the calculation inline with the current pricing values.

### 2.7 PolicyAssist wiring — minimum change, reference client only

The only PolicyAssist change in scope here is dropping the instrumentation client in. Two lines at startup, one wrapper around `llm.invoke()`. No caching, no session changes, no gunicorn switch, no retries — all of that is a separate workstream and this plan does not depend on it.

If the app workstream separately enables caching / sessions / evals / retries, those show up on our dashboards automatically because the OTel attributes carry them (cache tokens, `session_id`, exception class, eval spans). No monitoring change required.

### 2.8 Docs — how another team points their app at this

A short `README.md` for the monitoring service covering:

- How to run SigNoz locally.
- How to install the client (`pip install ...` or vendor the `monitoring/` package).
- The three lines needed to instrument an app.
- How to add a new model to `prices.yaml`.
- Where to find the shared bearer token in the team vault (placeholder for now).

---

## 3. Architecture

```
┌─────────────────┐   OTLP/HTTP    ┌──────────────────┐
│  PolicyAssist   │───────────────▶│      SigNoz      │
│  + monitoring   │                │  (docker-compose)│
│    client       │                │  ClickHouse + UI │
└─────────────────┘                └────────┬─────────┘
                                            │
┌─────────────────┐   OTLP/HTTP             │
│  Future app N   │───────────────▶─────────┤
│  + monitoring   │                          │
│    client       │                          │
└─────────────────┘                          │
                                             │
                          ┌──────────────────▼──┐
                          │   /finops page      │
                          │   (projection)      │
                          └─────────────────────┘
```

Standard wire format, one backend, one small bespoke page. Adding a new client app requires zero changes to the monitoring service.

---

## 4. Day-by-day

### Day 1 AM — backend + client scaffold (parallel)
- **Person A:** Stand up SigNoz via docker-compose. Verify OTLP ingest with a `curl` / `otel-cli` example.
- **Person B:** Build the `monitoring/` client package: `instrument_app()`, `traced_llm_call()`, `prices.yaml`, `compute_cost()`. Unit-test cost math against known token counts.
- **Milestone:** send a hand-crafted trace from the client to SigNoz and see `cost.gbp` on the span.

### Day 1 PM — wire PolicyAssist as reference client + dashboards
- Add the client to PolicyAssist. Two-line setup + one wrapper around `llm.invoke()`. No other PolicyAssist changes.
- Try `traceloop-sdk` in parallel; if it produces cleaner spans than the manual helper, keep it as the recommended path.
- Build the four dashboards in SigNoz. Export JSON. Commit.
- **Milestone:** ask a question in PolicyAssist, see the trace with tokens and cost in SigNoz; dashboards render.

### Day 2 AM — FinOps page
- Build `/finops`. Query SigNoz for recent avg cost. Compute naive vs projected monthly bill. Show the calculation.
- **Milestone:** page is live and matches SigNoz data.

### Day 2 PM — alerts + docs
- Configure the three alerts. Trigger each once (force a burst of test traffic, force an error) to confirm they fire.
- Write the client README.
- **Milestone:** a second dummy app (a 10-line script) can be pointed at SigNoz using only the README and appears in the per-app cost dashboard.

---

## 5. Backend alternatives if the primary doesn't fit

- **Langfuse** — better fit for pure-LLM shops: tokens, cost, sessions, prompt versioning first-class; costs computed from model IDs automatically. Trade-off: less useful if future Home Office apps aren't LLM apps. Swap SigNoz → Langfuse and the rest of this plan holds.
- **Honeycomb free tier** — SaaS, OTLP-native, zero infra. Use this if Docker is a hard blocker on team machines. Data leaves the org boundary — flag as demo-only, not production.
- **Grafana Cloud free tier + OTel Collector** — similar zero-infra option; more work to build LLM-relevant panels.

The OTel instrumentation in the client is backend-agnostic — swapping backend does not change the client code.

---

## 6. Out of scope

- Home Office SSO / 2FA on the SigNoz UI (local access only for this sprint).
- Data classification review of span attributes shipped (we deliberately do *not* put question or answer text on spans — a Security Advisor should confirm the attributes we do ship are OK).
- DPIA covering the telemetry pipeline.
- Production SigNoz deployment: storage sizing, retention policy, backups, HA.
- Migration to an internal Home Office observability platform if one exists.
- A proper Python package on an internal index instead of a vendored `monitoring/` folder.
- Automated `prices.yaml` update workflow when Anthropic changes prices.

---

## 7. Risk

The one real risk is Day 1 AM SigNoz spin-up. Mitigation: it runs in parallel to client-package work, and if it stalls past lunch we cut over to Honeycomb free tier and keep moving. The OTel instrumentation is backend-agnostic — that's the point.
