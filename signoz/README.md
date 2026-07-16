# SigNoz — observability backend

SigNoz is the OTLP-native observability backend for the monitoring service. It receives spans emitted by any app instrumented with the `monitoring/` client and gives us dashboards, alerting, and traces for free.

We do **not** vendor the SigNoz docker-compose file into this repo — it changes independently of us and is well-maintained upstream. Instead we run it out-of-tree and check in only our config additions (OTel Collector customisation, per-app auth, dashboards).

---

## Prerequisites

- Docker Engine 20+ and Docker Compose v2
- ~4 GB free RAM on the host that will run SigNoz
- Ports free: 8080 (frontend), 4317 (OTLP gRPC), 4318 (OTLP HTTP), 8123 (ClickHouse; optional external access)

---

## Bring it up

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

# 3. Deploy the stack (generates docker-compose files and starts containers)
foundryctl cast -f casting.yaml

# 4. Open the UI
open http://localhost:8080
```

First-run: SigNoz will ask you to create an admin user. Any email/password works locally — the credentials persist in the database.

---

## Point PolicyAssist at it

Add to `.env` in this repo (see `.env.example` for the template):

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_SERVICE_NAME=policyassist
```

No auth needed for the default local setup. In a production deployment set `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>`.

Start PolicyAssist (`python -m flask --app policyassist.app run`) and ask a question. Within a second the trace should appear in SigNoz under Traces → Filter by `service.name=policyassist`.

---

## Verify the wiring

Fastest sanity check: send a hand-crafted OTLP span via curl and confirm it lands.

```bash
curl -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  --data @- <<'EOF'
{
  "resourceSpans": [{
    "resource": {"attributes": [
      {"key": "service.name", "value": {"stringValue": "smoke-test"}}
    ]},
    "scopeSpans": [{
      "spans": [{
        "traceId": "5b8aa5a2d2c872e8321cf37308d69df2",
        "spanId": "051581bf3cb55c13",
        "name": "smoke",
        "kind": 1,
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000001000000000",
        "attributes": [
          {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "100"}},
          {"key": "cost.gbp", "value": {"doubleValue": 0.001}}
        ]
      }]
    }]
  }]
}
EOF
```

You should see a `smoke-test` service appear in the Services list.

---

## Dashboards

See `dashboards/README.md` for the four dashboards we build. Dashboards are exported from the SigNoz UI as JSON and committed under `dashboards/`. To import: SigNoz UI → Dashboards → New dashboard → Import from JSON.

---

## What we defer

- **Production deployment** — this README assumes a laptop-local install. Production needs storage sizing, retention, backup, and HA. See `plan.md` §6.
- **SSO / 2FA** — SigNoz supports SSO but requires enterprise config. Local demo uses username/password.
- **Alertmanager wiring** — SigNoz native alerts are enough for the sprint. Slack/email integration needs org secrets and is deferred.

---

## Fallback if Docker is unavailable

Per `plan.md` §5, if Docker is a blocker: Honeycomb free tier (SaaS, OTLP-native, zero infra). Set:

```
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<api-key>
```

Flag as demo-only — data leaves the org boundary.
