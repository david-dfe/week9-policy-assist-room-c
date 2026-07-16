# Dashboards

Four dashboards are checked in here as JSON exports from the SigNoz UI. Build once in the UI (drag-and-drop is easier than editing JSON), export, commit.

## Four dashboards, one purpose each

| File | Purpose | Panels |
|---|---|---|
| `cost.json` *(TBD)* | £ visibility — the money view | £/hour, £/day, £/session top-10, cache-read vs uncached input tokens |
| `usage.json` *(TBD)* | Throughput and cache health | requests/min, input+output tokens over time, cache hit ratio |
| `reliability.json` *(TBD)* | Errors and latency | error rate by `error.class`, p50/p95/p99 latency |
| `per-app.json` *(TBD)* | Multi-app spend | £ stacked by `service.name` — proves the "point any app at this" claim |

## How to build one

1. In the SigNoz UI, Dashboards → **New dashboard**.
2. Add panels using the query builder against the ClickHouse `signoz_traces.signoz_index_v3` table. Attribute names to filter on: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `cost.gbp`, `service.name`, `error.class`.
3. Save.
4. Dashboard settings → **Export JSON**. Save the file here with the name from the table above.
5. Commit with a message like `feat(signoz): add cost dashboard`.

## How to import one

SigNoz UI → Dashboards → **New dashboard** → **Import from JSON** → paste or upload.

## Why we didn't check in dashboard JSON up-front

Writing SigNoz dashboard JSON from scratch — without a running instance to point-and-click against — is fragile: the schema evolves, panel IDs collide on import, and query expressions are much easier to get right in the UI's query builder than by hand. The dashboards land in this folder as each team member builds them.
