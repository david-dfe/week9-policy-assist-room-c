# `monitoring` — LLM observability client

An OpenTelemetry-based instrumentation client that any Python app can drop in to gain LLM-aware traces, cost enrichment, and error capture. Ships spans over OTLP to any backend (SigNoz by default; Honeycomb, Grafana Cloud, or Langfuse all work).

## Install

For now, vendor the folder into your app or install from a git URL:

```bash
uv pip install "git+https://github.com/david-dfe/week9-policy-assist-room-c.git#subdirectory=."
```

Long-term plan: publish to an internal PyPI index (see `plan.md` §6).

## Instrument a new app in three lines

```python
from monitoring import instrument_app, traced_llm_call

instrument_app(service_name="your-app")

# ...inside the request handler...
with traced_llm_call(model="claude-sonnet-4-5", session_id=session_id) as span:
    response = llm.invoke(messages)
    span.record_usage(response)
```

That's it. Every LLM call now emits an OTLP span with:

- `gen_ai.system` — provider (default: `anthropic`)
- `gen_ai.request.model` — model ID
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- `gen_ai.usage.cache_read_input_tokens`, `gen_ai.usage.cache_creation_input_tokens`
- `cost.gbp` — computed from `prices.yaml`
- `app.session_id` — opaque, only if you pass it in
- `error.class` — exception class name if the block raised

## Configuration — env vars only

| Var | Purpose | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP endpoint on your backend | http://localhost:4318 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Wire format | http/protobuf |
| `OTEL_EXPORTER_OTLP_HEADERS` | e.g. bearer token | *(unset)* |
| `OTEL_SERVICE_NAME` | Overrides `service_name` in code | unknown-app |

The client is **backend-agnostic** — swapping SigNoz → Honeycomb → Langfuse is an env-var change only, no code touched.

## Adding a new model

Edit `monitoring/prices.yaml`. Add a block:

```yaml
your-new-model-id:
  input_per_million_gbp: 2.40
  output_per_million_gbp: 12.00
  cache_write_per_million_gbp: 3.00
  cache_read_per_million_gbp: 0.24
```

That's the only place price values live in the codebase (CLAUDE.md §9 rule 3). No code change needed.

## FinOps projection page

`monitoring/finops.py` is a standalone Flask app that projects the monthly bill under a workload profile. Run it locally:

```bash
uv run flask --app monitoring.finops run --port 5001
open http://localhost:5001
```

Query-string params override any assumption (queries/day, cache hit ratio, model, etc.). `GET /api/projection` returns JSON.

## Domain rules

- **No raw prompt or completion text on spans.** Tokens, model, cost, session id, error class — yes. Question or answer text — no. See `../CLAUDE.md` §9 rule 1.
- **All prices in `prices.yaml`, nowhere else.** See `../CLAUDE.md` §9 rule 3.
- **Backend-agnostic.** No SigNoz-specific code in this package. See `../CLAUDE.md` §9 rule 2.

## What's not here yet

- Auto-instrumentation of non-Anthropic providers (OpenAI, Bedrock, etc.). The core code path is provider-neutral; add per-provider `usage_from_response()` heuristics as needed.
- Sampling controls. Currently every span is exported. Add `TraceIdRatioBased` sampler when volume warrants.
- Retry / batching tuning on the OTLP exporter. Defaults are sensible for < 100 rps.
