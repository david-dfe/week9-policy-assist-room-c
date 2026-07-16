"""FinOps projection page — the money shot for the monitoring service.

Given an assumed workload profile (tokens per request, queries per day,
working days per month) and one or more models from ``prices.yaml``,
computes for each model:

- **naive** monthly bill with no prompt caching, and
- **projected** monthly bill assuming the static system-prompt portion
  hits the Anthropic prompt cache at a given hit ratio.

Defaults are pinned to the brief's stated Finance projection: **~£14,200
per month** on Sonnet 4.5 at 6,000 queries/day (see
``SINS-STANDARDS-CONSTRAINED.md`` §"What the brief says the Head of
Digital actually cares about"). That baseline is the *fully-loaded*
manual — around 42k system-prompt tokens — not the 1200-token teaching
extract shipped in ``policyassist/manual.txt``.

Not a general dashboard — SigNoz owns that. This exists specifically for
the "what would £14,200/month become?" answer the Head of Digital asked
for. Both prompt caching AND a cheaper model (Haiku 4.5) are legitimate
levers, so the default view shows both, side by side.

Runs as its own Flask app (``flask --app monitoring.finops run``) so it
does not require PolicyAssist. Query-string params override the default
workload assumptions — the page is deliberately transparent about every
number that feeds the calculation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from flask import Flask, abort, jsonify, render_template_string, request

from monitoring.cost import Usage, compute_cost, load_prices

BRIEF_NAIVE_TARGET_GBP: float = 14_200.0
"""Finance's stated naive projection from the brief — shown as a reference
value on the page so the demo lands with context.
"""

DEFAULT_COMPARE_MODELS: tuple[str, ...] = (
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
)


@dataclass(frozen=True)
class WorkloadAssumptions:
    """Every number that shapes the projection — all overridable per request.

    Defaults reproduce the brief's £14,200/mo Finance projection on
    Sonnet 4.5 at 6k q/day: a fully-loaded operational manual as the
    system prompt (~42k tokens) plus a bounded rolling-window history
    (~2k tokens for ten short turns).
    """

    queries_per_day: int = 6_000
    working_days_per_month: int = 22
    system_prompt_tokens: int = 42_000
    history_tokens_per_request: int = 2_000
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


def compute_comparison(
    a: WorkloadAssumptions, models: tuple[str, ...] = DEFAULT_COMPARE_MODELS
) -> list[Projection]:
    """Compute projections for each model in ``models`` under the same workload.

    Same ``a`` is used for every model — only ``a.model`` is swapped — so
    the numbers are directly comparable. Order of the returned list mirrors
    ``models``.
    """
    return [compute_projection(replace(a, model=m)) for m in models]


class _AssumptionError(ValueError):
    """Query-param override failed validation. Rendered as HTTP 400."""


_FIELD_TYPES: dict[str, type] = {
    "queries_per_day": int,
    "working_days_per_month": int,
    "system_prompt_tokens": int,
    "history_tokens_per_request": int,
    "user_question_tokens": int,
    "response_tokens": int,
    "cache_hit_ratio": float,
    "model": str,
}

_NON_NEGATIVE_INT_FIELDS = (
    "queries_per_day",
    "working_days_per_month",
    "system_prompt_tokens",
    "history_tokens_per_request",
    "user_question_tokens",
    "response_tokens",
)


def _assumptions_from_request() -> WorkloadAssumptions:
    """Read overrides from query params, keeping defaults for what isn't provided.

    Raises ``_AssumptionError`` on any invalid input — route handlers turn
    that into HTTP 400 so bad URLs surface as bad requests, not 500s.
    """
    defaults = WorkloadAssumptions()
    updates: dict[str, Any] = {}
    for field_name, field_type in _FIELD_TYPES.items():
        raw = request.args.get(field_name)
        if raw is None:
            continue
        try:
            updates[field_name] = field_type(raw)
        except (TypeError, ValueError) as exc:
            raise _AssumptionError(f"invalid value for {field_name!r}: {raw!r}") from exc

    assumptions = replace(defaults, **updates)
    _validate(assumptions)
    return assumptions


def _validate(a: WorkloadAssumptions) -> None:
    for name in _NON_NEGATIVE_INT_FIELDS:
        if getattr(a, name) < 0:
            raise _AssumptionError(f"{name} must be >= 0")
    if not 0.0 <= a.cache_hit_ratio <= 1.0:
        raise _AssumptionError("cache_hit_ratio must be between 0 and 1")
    prices = load_prices()
    if a.model not in prices:
        raise _AssumptionError(
            f"unknown model {a.model!r}; see monitoring/prices.yaml for supported models"
        )


def _projection_to_dict(p: Projection) -> dict[str, Any]:
    return {
        "assumptions": asdict(p.assumptions),
        "naive_per_request_gbp": p.naive_per_request_gbp,
        "cached_per_request_gbp": p.cached_per_request_gbp,
        "monthly_naive_gbp": p.monthly_naive_gbp,
        "monthly_cached_gbp": p.monthly_cached_gbp,
        "savings_gbp_per_month": p.savings_gbp_per_month,
        "savings_pct": p.savings_pct,
    }


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FinOps projection — PolicyAssist</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 900px; margin: 2rem auto;
           padding: 0 1rem; color: #0b0c0c; }
    h1 { border-bottom: 4px solid #1d70b8; padding-bottom: .3rem; }
    h2 { margin-top: 2rem; }
    .brief { background: #f3f2f1; padding: 1rem 1.2rem; border-left: 6px solid #1d70b8;
             margin: 1rem 0; }
    .brief .target { font-size: 1.4rem; font-weight: 700; color: #d4351c; }
    .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
                  margin: 1.5rem 0; }
    .model-card { border: 1px solid #b1b4b6; padding: 1rem 1.2rem; }
    .model-card h3 { margin: 0 0 .4rem; font-size: 1.1rem; }
    .model-card .row { display: flex; justify-content: space-between; align-items: baseline;
                       padding: .5rem 0; border-bottom: 1px solid #dee0e2; }
    .model-card .row:last-child { border-bottom: none; }
    .model-card .label { color: #505a5f; font-size: .9rem; }
    .model-card .value { font-size: 1.4rem; font-weight: 700; }
    .model-card .naive .value { color: #d4351c; }
    .model-card .cached .value { color: #00703c; }
    .model-card .savings { font-size: .85rem; color: #00703c; margin-top: .3rem; }
    .best { border-left: 6px solid #00703c; background: #f0f7f1; }
    .best-tag { display: inline-block; background: #00703c; color: #fff; font-size: .7rem;
                padding: 2px 8px; margin-left: .5rem; vertical-align: middle; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #dee0e2; }
    th { background: #f3f2f1; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .hint { color: #505a5f; font-size: .85rem; }
    code { background: #f3f2f1; padding: 1px 4px; }
  </style>
</head>
<body>
  <h1>PolicyAssist FinOps projection</h1>

  <div class="brief">
    <div>Finance's naive projection from the brief</div>
    <div class="target">£{{ "%.0f" | format(brief_target) }} / month</div>
    <div class="hint">Uncached Sonnet 4.5 at 6,000 queries/day &times; 22 working days,
      with the full operational manual as the system prompt. The four cells below show
      what caching and a cheaper model do to that number.</div>
  </div>

  <h2>Monthly bill — {{ a.queries_per_day }} q/day &times; {{ a.working_days_per_month }} days</h2>

  <div class="comparison">
    {% for p in projections %}
    <div class="model-card{% if loop.index0 == best_index %} best{% endif %}">
      <h3>{{ p.assumptions.model }}
        {%- if loop.index0 == best_index %}
        <span class="best-tag">BEST</span>
        {%- endif %}
      </h3>
      <div class="row naive">
        <span class="label">Naive (no cache)</span>
        <span class="value">£{{ "%.0f" | format(p.monthly_naive_gbp) }}</span>
      </div>
      <div class="row cached">
        <span class="label">
          With caching ({{ (p.assumptions.cache_hit_ratio * 100) | int }}% hit)
        </span>
        <span class="value">£{{ "%.0f" | format(p.monthly_cached_gbp) }}</span>
      </div>
      <div class="savings">
        Saves £{{ "%.0f" | format(p.savings_gbp_per_month) }}/mo
        ({{ "%.1f" | format(p.savings_pct) }}%) vs same-model naive
        &nbsp;·&nbsp; £{{ "%.4f" | format(p.cached_per_request_gbp) }}/request cached
      </div>
    </div>
    {% endfor %}
  </div>

  <h2>Versus the brief's £{{ "%.0f" | format(brief_target) }} baseline</h2>
  <table>
    <tr>
      <th>Model</th>
      <th>Cache</th>
      <th class="num">Monthly (£)</th>
      <th class="num">vs brief</th>
      <th class="num">Reduction</th>
    </tr>
    {% for p in projections %}
    <tr>
      <td>{{ p.assumptions.model }}</td>
      <td>off</td>
      <td class="num">{{ "%.0f" | format(p.monthly_naive_gbp) }}</td>
      <td class="num">-{{ "%.0f" | format(brief_target - p.monthly_naive_gbp) }}</td>
      <td class="num">{{ "%.1f" | format((1 - p.monthly_naive_gbp / brief_target) * 100) }}%</td>
    </tr>
    <tr>
      <td>{{ p.assumptions.model }}</td>
      <td>on ({{ (p.assumptions.cache_hit_ratio * 100) | int }}%)</td>
      <td class="num">{{ "%.0f" | format(p.monthly_cached_gbp) }}</td>
      <td class="num">-{{ "%.0f" | format(brief_target - p.monthly_cached_gbp) }}</td>
      <td class="num">{{ "%.1f" | format((1 - p.monthly_cached_gbp / brief_target) * 100) }}%</td>
    </tr>
    {% endfor %}
  </table>
  <p class="hint">Same workload assumptions across every row — only the model and
    the cache setting change. Negative "vs brief" values are savings against
    Finance's projection; positive would mean we've overshot it (never happens
    with sensible inputs).</p>

  <h2>How this was calculated</h2>
  <table>
    <tr><th>Assumption</th><th class="num">Value</th></tr>
    <tr><td>Queries per day</td><td class="num">{{ a.queries_per_day }}</td></tr>
    <tr><td>Working days per month</td><td class="num">{{ a.working_days_per_month }}</td></tr>
    <tr><td>System prompt tokens (the manual)</td>
        <td class="num">{{ a.system_prompt_tokens }}</td></tr>
    <tr><td>History tokens per request</td>
        <td class="num">{{ a.history_tokens_per_request }}</td></tr>
    <tr><td>User question tokens</td><td class="num">{{ a.user_question_tokens }}</td></tr>
    <tr><td>Response tokens</td><td class="num">{{ a.response_tokens }}</td></tr>
    <tr><td>Cache hit ratio</td><td class="num">{{ "%.2f" | format(a.cache_hit_ratio) }}</td></tr>
  </table>

  <p class="hint">Prices come from <code>monitoring/prices.yaml</code>, converted from
    Anthropic's USD pricing at an assumed rate of USD 1.00 = GBP 0.80 (documented at
    the top of that file).</p>

  <p class="hint">Override any assumption via query string, e.g.
    <code>?queries_per_day=800&amp;cache_hit_ratio=0.95&amp;system_prompt_tokens=30000</code>.
    Single-model JSON at <a href="/api/projection">/api/projection</a>;
    multi-model JSON at <a href="/api/comparison">/api/comparison</a>.</p>
</body>
</html>"""


def _pick_best(projections: list[Projection]) -> int:
    """Index of the projection with the lowest cached monthly bill.

    Ties resolve to the earlier index (stable choice).
    """
    return min(range(len(projections)), key=lambda i: projections[i].monthly_cached_gbp)


def create_app() -> Flask:
    """App factory. ``flask --app monitoring.finops:create_app run`` works too."""
    app = Flask(__name__)
    # The `_TEMPLATE` string interpolates the user-controlled `model` field.
    # Force autoescape on rather than relying on Flask's version-dependent
    # default for string templates.
    app.jinja_env.autoescape = True

    def _load_assumptions() -> WorkloadAssumptions:
        try:
            return _assumptions_from_request()
        except _AssumptionError as exc:
            abort(400, description=str(exc))

    @app.route("/")
    def index() -> str:
        a = _load_assumptions()
        projections = compute_comparison(a)
        return render_template_string(
            _TEMPLATE,
            a=a,
            projections=projections,
            best_index=_pick_best(projections),
            brief_target=BRIEF_NAIVE_TARGET_GBP,
        )

    @app.route("/api/projection")
    def api_projection() -> Any:
        p = compute_projection(_load_assumptions())
        return jsonify(_projection_to_dict(p))

    @app.route("/api/comparison")
    def api_comparison() -> Any:
        a = _load_assumptions()
        projections = compute_comparison(a)
        return jsonify(
            {
                "brief_naive_target_gbp": BRIEF_NAIVE_TARGET_GBP,
                "assumptions": asdict(a),
                "models": [p.assumptions.model for p in projections],
                "projections": [_projection_to_dict(p) for p in projections],
                "best_model": projections[_pick_best(projections)].assumptions.model,
            }
        )

    @app.route("/healthz")
    def healthz() -> tuple[str, int]:
        return "ok", 200

    return app


# Module-level app so `flask --app monitoring.finops run` works.
app = create_app()
