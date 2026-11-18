"""API tests. They run against a fake provider, so they never touch the network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wacc_lab.api import create_app
from wacc_lab.db import Store
from wacc_lab.models import Fundamentals
from wacc_lab.providers.base import TickerNotFoundError
from wacc_lab.service import AnalysisService

SAMPLE = Fundamentals(
    ticker="AAPL",
    name="Apple Inc.",
    sector="Technology",
    currency="USD",
    price=40.0,
    market_cap=4000.0,
    shares_outstanding=100.0,
    total_debt=1000.0,
    cash=200.0,
    net_debt=800.0,
    equity_book=2000.0,
    risk_free_rate=0.05,
    beta=1.0,
    beta_source="yahoo",
    pretax_cost_of_debt=0.06,
    tax_rate=0.25,
    roe=0.20,
    retention_ratio=0.50,
    fcf_ttm=500.0,
    net_income_ttm=200.0,
    revenue_ttm=2000.0,
    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
)


class FakeProvider:
    def __init__(self, fundamentals: Fundamentals) -> None:
        self.fundamentals = fundamentals
        self.calls: list[str] = []

    def fetch(self, ticker: str) -> Fundamentals:
        self.calls.append(ticker)
        if ticker.upper() == "NOPE":
            raise TickerNotFoundError("NOPE is not a known Yahoo Finance ticker")
        return self.fundamentals.model_copy(
            update={
                "ticker": ticker.upper(),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )


def build_client(tmp_path, ttl_hours: float = 24.0):
    provider = FakeProvider(SAMPLE)
    store = Store(tmp_path / "test.db")
    service = AnalysisService(store=store, provider=provider, ttl_hours=ttl_hours)
    app = create_app(service)
    return TestClient(app), provider


@pytest.fixture
def client(tmp_path):
    test_client, provider = build_client(tmp_path)
    return test_client, provider


def test_tickers_endpoint_lists_the_curated_catalog(client):
    test_client, _ = client
    response = test_client.get("/api/tickers")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 40
    tickers = {item["ticker"] for item in body["tickers"]}
    assert {"AAPL", "MSFT", "NVDA", "SHEL"} <= tickers


def test_analysis_computes_then_serves_from_cache(client):
    test_client, provider = client

    first = test_client.get("/api/analysis/AAPL")
    assert first.status_code == 200
    body = first.json()
    assert body["cache"]["status"] == "computed"
    assert provider.calls == ["AAPL"]

    second = test_client.get("/api/analysis/AAPL")
    assert second.status_code == 200
    assert second.json()["cache"]["status"] == "fresh"
    assert provider.calls == ["AAPL"]


def test_refresh_forces_a_new_provider_call(client):
    test_client, provider = client

    test_client.get("/api/analysis/AAPL")
    refreshed = test_client.get("/api/analysis/AAPL", params={"refresh": "true"})

    assert refreshed.status_code == 200
    assert refreshed.json()["cache"]["status"] == "refreshed"
    assert provider.calls == ["AAPL", "AAPL"]


def test_a_stale_snapshot_is_recomputed(tmp_path):
    test_client, provider = build_client(tmp_path, ttl_hours=0.0)

    test_client.get("/api/analysis/AAPL")
    second = test_client.get("/api/analysis/AAPL")

    assert second.json()["cache"]["status"] == "stale"
    assert provider.calls == ["AAPL", "AAPL"]


def test_wacc_decomposition_matches_the_sample_numbers(client):
    test_client, _ = client

    body = test_client.get("/api/analysis/AAPL").json()
    wacc = body["wacc"]

    # Ke = 0.05 + 1.0 * 0.05, Kd after tax = 0.06 * 0.75
    assert wacc["cost_of_equity"] == pytest.approx(0.10)
    assert wacc["after_tax_cost_of_debt"] == pytest.approx(0.045)
    # D = 1000, E = 4000
    assert wacc["debt_weight"] == pytest.approx(0.20)
    assert wacc["equity_weight"] == pytest.approx(0.80)
    assert wacc["wacc"] == pytest.approx(0.8 * 0.10 + 0.2 * 0.045)


def test_growth_is_capped_strictly_below_the_wacc(client):
    test_client, _ = client

    body = test_client.get("/api/analysis/AAPL").json()
    growth = body["growth"]

    assert growth["raw_growth"] == pytest.approx(0.10)
    assert growth["capped"] is True
    assert growth["growth"] < body["wacc"]["wacc"]
    assert growth["growth"] == pytest.approx(body["wacc"]["wacc"] - 0.015)


def test_valuation_is_consistent_with_the_wacc_and_growth(client):
    test_client, _ = client

    body = test_client.get("/api/analysis/AAPL").json()
    valuation = body["valuation"]

    assert valuation["base_fcf"] == pytest.approx(500.0)
    assert len(valuation["projected_fcf"]) == 5
    assert valuation["enterprise_value"] == pytest.approx(
        valuation["pv_explicit"] + valuation["pv_terminal"]
    )
    assert valuation["equity_value"] == pytest.approx(
        valuation["enterprise_value"] - 800.0
    )
    assert valuation["value_per_share"] == pytest.approx(
        valuation["equity_value"] / 100.0
    )
    assert valuation["upside_pct"] == pytest.approx(
        (valuation["value_per_share"] - 40.0) / 40.0
    )


def test_overrides_are_applied_and_persisted(client):
    test_client, provider = client

    response = test_client.post(
        "/api/analysis/AAPL/overrides", json={"beta": 2.0}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["wacc"]["cost_of_equity"] == pytest.approx(0.15)
    assert body["overrides"]["beta"] == pytest.approx(2.0)

    # The override survives a new request and does not hit the provider again.
    again = test_client.get("/api/analysis/AAPL")
    assert again.json()["overrides"]["beta"] == pytest.approx(2.0)
    assert again.json()["wacc"]["cost_of_equity"] == pytest.approx(0.15)
    assert provider.calls == ["AAPL"]


def test_clearing_overrides_goes_back_to_the_automatic_values(client):
    test_client, provider = client

    test_client.post("/api/analysis/AAPL/overrides", json={"beta": 2.0})
    cleared = test_client.delete("/api/analysis/AAPL/overrides")

    assert cleared.status_code == 200
    body = cleared.json()
    assert body["overrides"] is None
    assert body["wacc"]["cost_of_equity"] == pytest.approx(0.10)
    assert provider.calls == ["AAPL"]


def test_a_manual_growth_rate_is_capped_below_the_wacc(client):
    test_client, _ = client

    body = test_client.post(
        "/api/analysis/AAPL/overrides", json={"growth_rate": 0.50}
    ).json()

    assert body["growth"]["manual"] is True
    assert body["growth"]["capped"] is True
    assert body["growth"]["growth"] < body["wacc"]["wacc"]


def test_an_unknown_ticker_returns_404(client):
    test_client, _ = client

    response = test_client.get("/api/analysis/NOPE")

    assert response.status_code == 404
    assert "NOPE" in response.json()["detail"]


def test_the_web_interface_is_served(client):
    test_client, _ = client

    response = test_client.get("/")

    assert response.status_code == 200
    assert "WACC" in response.text


def test_health_endpoint_reports_the_configuration(client):
    test_client, _ = client

    response = test_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ttl_hours"] == pytest.approx(24.0)
