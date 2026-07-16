"""Tests for the FinOps projection page."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient

from monitoring.finops import (
    BRIEF_NAIVE_TARGET_GBP,
    WorkloadAssumptions,
    compute_comparison,
    compute_projection,
    create_app,
)


class TestComputeProjection:
    def test_defaults_produce_positive_bill(self) -> None:
        p = compute_projection(WorkloadAssumptions())
        assert p.monthly_naive_gbp > 0
        assert p.monthly_cached_gbp > 0

    def test_caching_reduces_cost(self) -> None:
        p = compute_projection(WorkloadAssumptions())
        assert p.monthly_cached_gbp < p.monthly_naive_gbp
        assert p.savings_gbp_per_month > 0
        assert p.savings_pct > 0

    def test_zero_cache_hit_ratio_gives_almost_no_savings(self) -> None:
        # At 0% hit ratio the "cached" path degenerates to the naive path,
        # so bills should match (float precision aside).
        p = compute_projection(WorkloadAssumptions(cache_hit_ratio=0.0))
        assert p.monthly_naive_gbp == pytest.approx(p.monthly_cached_gbp)

    def test_full_cache_hit_ratio_maximises_savings(self) -> None:
        a = WorkloadAssumptions(cache_hit_ratio=1.0)
        p = compute_projection(a)
        # With 100% cache hit on system-prompt tokens, cached-per-req must
        # be lower than at 90% hit.
        p_partial = compute_projection(WorkloadAssumptions(cache_hit_ratio=0.9))
        assert p.cached_per_request_gbp < p_partial.cached_per_request_gbp

    def test_scaling_queries_scales_bill_linearly(self) -> None:
        base = compute_projection(WorkloadAssumptions(queries_per_day=1_000))
        double = compute_projection(WorkloadAssumptions(queries_per_day=2_000))
        assert double.monthly_naive_gbp == pytest.approx(2 * base.monthly_naive_gbp)

    def test_zero_queries_zero_bill(self) -> None:
        p = compute_projection(WorkloadAssumptions(queries_per_day=0))
        assert p.monthly_naive_gbp == 0.0
        assert p.monthly_cached_gbp == 0.0
        # Guard against ZeroDivisionError in savings_pct.
        assert p.savings_pct == 0.0


@pytest.fixture
def client() -> Iterator[FlaskClient]:
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestRoutes:
    def test_healthz(self, client: FlaskClient) -> None:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.data == b"ok"

    def test_index_renders_html(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"FinOps projection" in resp.data
        assert b"claude-sonnet-4-5" in resp.data

    def test_api_returns_json(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "monthly_naive_gbp" in data
        assert "monthly_cached_gbp" in data
        assert "savings_gbp_per_month" in data
        assert data["monthly_naive_gbp"] > data["monthly_cached_gbp"]

    def test_query_params_override(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?queries_per_day=100")
        data = resp.get_json()
        assert data["assumptions"]["queries_per_day"] == 100

    def test_query_params_override_model(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?model=claude-haiku-4-5")
        data = resp.get_json()
        assert data["assumptions"]["model"] == "claude-haiku-4-5"
        # Haiku should be cheaper than the default Sonnet.
        default = client.get("/api/projection").get_json()
        assert data["monthly_naive_gbp"] < default["monthly_naive_gbp"]

    def test_defaults_land_near_brief_target(self) -> None:
        # Defaults must reproduce Finance's ~£14,200/mo naive projection on
        # Sonnet 4.5 — if they don't, the demo loses its punchline. Ten
        # percent slack absorbs FX drift or minor price updates.
        p = compute_projection(WorkloadAssumptions())
        assert p.monthly_naive_gbp == pytest.approx(BRIEF_NAIVE_TARGET_GBP, rel=0.1)


class TestComparison:
    def test_compute_comparison_returns_projection_per_model(self) -> None:
        projections = compute_comparison(
            WorkloadAssumptions(), models=("claude-sonnet-4-5", "claude-haiku-4-5")
        )
        assert [p.assumptions.model for p in projections] == [
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
        ]

    def test_haiku_cached_is_cheapest(self) -> None:
        # Sanity: with the brief's defaults, Haiku + cache should beat every
        # other combination. If this ever fails, prices moved dramatically
        # and the page's "BEST" tag is misleading — worth a look.
        projections = compute_comparison(WorkloadAssumptions())
        cheapest = min(projections, key=lambda p: p.monthly_cached_gbp)
        assert cheapest.assumptions.model == "claude-haiku-4-5"

    def test_api_comparison_endpoint(self, client: FlaskClient) -> None:
        resp = client.get("/api/comparison")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["brief_naive_target_gbp"] == BRIEF_NAIVE_TARGET_GBP
        assert "claude-sonnet-4-5" in data["models"]
        assert "claude-haiku-4-5" in data["models"]
        assert len(data["projections"]) == len(data["models"])
        assert data["best_model"] == "claude-haiku-4-5"

    def test_index_shows_brief_target(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        # The brief target must be visible on the page — that's the demo hook.
        assert b"14200" in resp.data or b"14,200" in resp.data


class TestValidation:
    """Bad query params must return 400, not 500 (or worse, a silent nonsense
    projection). This is the page leadership sees — it needs to fail loudly on
    malformed input."""

    def test_non_numeric_int_field_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?queries_per_day=abc")
        assert resp.status_code == 400

    def test_non_numeric_float_field_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?cache_hit_ratio=maybe")
        assert resp.status_code == 400

    def test_unknown_model_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?model=made-up-model")
        assert resp.status_code == 400

    def test_negative_queries_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?queries_per_day=-1")
        assert resp.status_code == 400

    def test_cache_hit_ratio_below_zero_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?cache_hit_ratio=-0.5")
        assert resp.status_code == 400

    def test_cache_hit_ratio_above_one_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/api/projection?cache_hit_ratio=1.5")
        assert resp.status_code == 400

    def test_index_returns_400_on_bad_input(self, client: FlaskClient) -> None:
        # Same validation must apply to the HTML page, not just the JSON endpoint.
        resp = client.get("/?model=made-up-model")
        assert resp.status_code == 400

    def test_autoescape_enabled(self) -> None:
        """Guard against Flask's version-dependent default for string templates."""
        app = create_app()
        assert app.jinja_env.autoescape is True
