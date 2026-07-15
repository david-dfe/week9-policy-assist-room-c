"""Tests for the FinOps projection page."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient

from monitoring.finops import WorkloadAssumptions, compute_projection, create_app


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
