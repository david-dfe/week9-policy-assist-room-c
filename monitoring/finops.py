"""FinOps projection page — the money shot for the monitoring service.

Given an assumed workload profile (tokens per request, queries per day,
working days per month) and a model from ``prices.yaml``, computes:

- **naive** monthly bill with no prompt caching, and
- **projected** monthly bill assuming the static system-prompt portion
  hits the Anthropic prompt cache at a given hit ratio.

Not a general dashboard — SigNoz owns that. This exists specifically
for the "what would £14,200/month become?" answer the Head of Digital
asked for.

Runs as its own Flask app (``flask --app monitoring.finops run``) so
it does not require PolicyAssist. Query-string params override the
default workload assumptions — the page is deliberately transparent
about every number that feeds the calculation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from flask import Flask, jsonify, render_template_string, request

from monitoring.cost import Usage, compute_cost


@dataclass(frozen=True)
class WorkloadAssumptions:
    """Every number that shapes the projection — all overridable per request."""

    queries_per_day: int = 6_000
    working_days_per_month: int = 22
    system_prompt_tokens: int = 1_200
    history_tokens_per_request: int = 4_000
    user_question_tokens: int = 20
    response_tokens: int = 200
    cache_hit_ratio: float = 0.90
    model: str = "claude-sonnet-4-5"


@dataclass(frozen=True)
class Projection:
    assumptions: WorkloadAssumptions
    naive_per_request_gbp: float
    cached_per_request_gbp: float
    monthly_naive_gbp: float
    monthly_cached_gbp: float
    savings_gbp_per_month: float
    savings_pct: float


def compute_projection(a: WorkloadAssumptions) -> Projection:
    naive = Usage(
        input_tokens=a.system_prompt_tokens + a.history_tokens_per_request + a.user_question_tokens,
        output_tokens=a.response_tokens,
    )
    naive_per_req = compute_cost(a.model, naive)

    # Steady-state caching: the system prompt portion is served from cache
    # for `cache_hit_ratio` of requests. Cache-creation cost is amortised
    # over the cache TTL and treated as negligible at 6k q/day.
    cache_read = int(a.system_prompt_tokens * a.cache_hit_ratio)
    non_cache_input = a.system_prompt_tokens - cache_read
    cached = Usage(
        input_tokens=non_cache_input + a.history_tokens_per_request + a.user_question_tokens,
        output_tokens=a.response_tokens,
        cache_read_input_tokens=cache_read,
    )
    cached_per_req = compute_cost(a.model, cached)

    monthly_queries = a.queries_per_day * a.working_days_per_month
    monthly_naive = naive_per_req * monthly_queries
    monthly_cached = cached_per_req * monthly_queries

    return Projection(
        assumptions=a,
        naive_per_request_gbp=naive_per_req,
        cached_per_request_gbp=cached_per_req,
        monthly_naive_gbp=monthly_naive,
        monthly_cached_gbp=monthly_cached,
        savings_gbp_per_month=monthly_naive - monthly_cached,
        savings_pct=(1 - monthly_cached / monthly_naive) * 100 if monthly_naive > 0 else 0.0,
    )


def _assumptions_from_request() -> WorkloadAssumptions:
    """Read overrides from query params, keeping defaults for what isn't provided."""
    defaults = WorkloadAssumptions()
    updates: dict[str, Any] = {}
    for field_name, field_type in {
        "queries_per_day": int,
        "working_days_per_month": int,
        "system_prompt_tokens": int,
        "history_tokens_per_request": int,
        "user_question_tokens": int,
        "response_tokens": int,
        "cache_hit_ratio": float,
        "model": str,
    }.items():
        raw = request.args.get(field_name)
        if raw is not None:
            updates[field_name] = field_type(raw)
    return replace(defaults, **updates)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FinOps projection — {{ p.assumptions.model }}</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 780px; margin: 2rem auto;
           padding: 0 1rem; color: #0b0c0c; }
    h1 { border-bottom: 4px solid #1d70b8; padding-bottom: .3rem; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1.5rem 0; }
    .card { border: 1px solid #b1b4b6; padding: 1rem 1.2rem; }
    .card .num { font-size: 2rem; font-weight: 700; color: #0b0c0c; margin: .3rem 0; }
    .card.naive { border-left: 6px solid #d4351c; }
    .card.cached { border-left: 6px solid #00703c; }
    .savings { background: #f3f2f1; padding: 1rem 1.2rem; margin: 1rem 0 1.5rem; }
    .savings .num { font-size: 1.6rem; color: #00703c; font-weight: 700; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #dee0e2; }
    th { background: #f3f2f1; }
    .hint { color: #505a5f; font-size: .85rem; }
  </style>
</head>
<body>
  <h1>PolicyAssist FinOps projection</h1>
  <p class="hint">Projected monthly bill on <strong>{{ p.assumptions.model }}</strong> at
    <strong>{{ p.assumptions.queries_per_day }}</strong> queries/day &times;
    <strong>{{ p.assumptions.working_days_per_month }}</strong> working days.</p>

  <div class="grid">
    <div class="card naive">
      <div>Naive — no prompt caching</div>
      <div class="num">£{{ "%.2f" | format(p.monthly_naive_gbp) }}</div>
      <div class="hint">£{{ "%.4f" | format(p.naive_per_request_gbp) }} per request</div>
    </div>
    <div class="card cached">
      <div>Projected — with prompt caching
        ({{ (p.assumptions.cache_hit_ratio * 100) | int }}% hit)</div>
      <div class="num">£{{ "%.2f" | format(p.monthly_cached_gbp) }}</div>
      <div class="hint">£{{ "%.4f" | format(p.cached_per_request_gbp) }} per request</div>
    </div>
  </div>

  <div class="savings">
    <div>Monthly saving</div>
    <div class="num">£{{ "%.2f" | format(p.savings_gbp_per_month) }}
      <span class="hint">({{ "%.1f" | format(p.savings_pct) }}%)</span></div>
  </div>

  <h2>How this was calculated</h2>
  <table>
    <tr><th>Input</th><th>Value</th></tr>
    <tr><td>Model</td><td>{{ p.assumptions.model }}</td></tr>
    <tr><td>Queries per day</td><td>{{ p.assumptions.queries_per_day }}</td></tr>
    <tr><td>Working days per month</td><td>{{ p.assumptions.working_days_per_month }}</td></tr>
    <tr><td>System prompt tokens</td><td>{{ p.assumptions.system_prompt_tokens }}</td></tr>
    <tr><td>History tokens per request</td>
        <td>{{ p.assumptions.history_tokens_per_request }}</td></tr>
    <tr><td>User question tokens</td><td>{{ p.assumptions.user_question_tokens }}</td></tr>
    <tr><td>Response tokens</td><td>{{ p.assumptions.response_tokens }}</td></tr>
    <tr><td>Cache hit ratio</td><td>{{ "%.2f" | format(p.assumptions.cache_hit_ratio) }}</td></tr>
  </table>

  <p class="hint">Prices come from <code>monitoring/prices.yaml</code>, converted from Anthropic's
    USD pricing at an assumed rate of USD 1.00 = GBP 0.80 (documented at the top of that file).</p>

  <p class="hint">Override any assumption via query string, e.g.
    <code>?queries_per_day=800&amp;cache_hit_ratio=0.95</code>.
    JSON at <a href="/api/projection">/api/projection</a>.</p>
</body>
</html>"""


def create_app() -> Flask:
    """App factory. ``flask --app monitoring.finops:create_app run`` works too."""
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        p = compute_projection(_assumptions_from_request())
        return render_template_string(_TEMPLATE, p=p)

    @app.route("/api/projection")
    def api_projection() -> Any:
        p = compute_projection(_assumptions_from_request())
        return jsonify(
            {
                "assumptions": asdict(p.assumptions),
                "naive_per_request_gbp": p.naive_per_request_gbp,
                "cached_per_request_gbp": p.cached_per_request_gbp,
                "monthly_naive_gbp": p.monthly_naive_gbp,
                "monthly_cached_gbp": p.monthly_cached_gbp,
                "savings_gbp_per_month": p.savings_gbp_per_month,
                "savings_pct": p.savings_pct,
            }
        )

    @app.route("/healthz")
    def healthz() -> tuple[str, int]:
        return "ok", 200

    return app


# Module-level app so `flask --app monitoring.finops run` works.
app = create_app()
