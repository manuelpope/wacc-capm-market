"""API tests. They run against a fake provider, so they never touch the network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wacc_lab.api import create_app
from wacc_lab.db import Store
from wacc_lab.models import Fundamentals
from wacc_lab.providers.analyst import AnalystExtractor
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
    field_sources={
        "pretax_cost_of_debt": "yahoo",
        "tax_rate": "yahoo",
        "roe": "yahoo",
        "retention_ratio": "yahoo",
        "fcf_ttm": "yahoo",
    },
)


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls.append(prompt)
        return self.response


KNOWN_TICKERS = {"AAPL", "MSFT", "NVDA"}


class FakeProvider:
    def __init__(self, fundamentals: Fundamentals) -> None:
        self.fundamentals = fundamentals
        self.calls: list[str] = []

    def fetch(self, ticker: str, use_llm: bool = True) -> Fundamentals:
        self.calls.append(ticker)
        if ticker.strip().upper() not in KNOWN_TICKERS:
            raise TickerNotFoundError(
                f"{ticker} is not a known Yahoo Finance ticker"
            )
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


def test_growth_is_capped_at_the_ceiling_and_stays_below_the_wacc(client):
    test_client, _ = client

    body = test_client.get("/api/analysis/AAPL").json()
    growth = body["growth"]

    assert growth["raw_growth"] == pytest.approx(0.10)
    assert growth["capped"] is True
    assert growth["growth"] == pytest.approx(0.05)
    assert growth["growth"] < body["wacc"]["wacc"]


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
    assert valuation["terminal_value_share"] == pytest.approx(
        valuation["pv_terminal"] / valuation["enterprise_value"]
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


def test_a_manual_growth_rate_keeps_the_minimum_spread_below_the_wacc(client):
    test_client, _ = client

    body = test_client.post(
        "/api/analysis/AAPL/overrides", json={"growth_rate": 0.065}
    ).json()

    assert body["growth"]["manual"] is True
    assert body["growth"]["capped"] is True
    assert body["growth"]["growth"] == pytest.approx(body["wacc"]["wacc"] - 0.03)


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


# ------------------------------------------------------------- analyst fallback


def build_client_with_analyst(tmp_path, response: str, fundamentals: Fundamentals):
    provider = FakeProvider(fundamentals)
    store = Store(tmp_path / "test.db")
    analyst = AnalystExtractor(
        FakeLLM(response), model_label="the analyst model (test)"
    )
    service = AnalysisService(
        store=store, provider=provider, ttl_hours=24, analyst=analyst
    )
    return TestClient(create_app(service)), provider


def test_the_analyst_fills_a_missing_input_and_the_source_is_reported(tmp_path):
    gap = SAMPLE.model_copy(
        update={
            "roe": None,
            "field_sources": {**SAMPLE.field_sources, "roe": "unavailable"},
        }
    )
    test_client, _ = build_client_with_analyst(
        tmp_path, '{"roe": 0.35, "notes": {"roe": "typical for the sector"}}', gap
    )

    body = test_client.get("/api/analysis/AAPL").json()

    assert body["inputs"]["roe"] == pytest.approx(0.35)
    assert body["field_sources"]["roe"] == "llm"
    assert any("roe" in warning for warning in body["warnings"])


def test_the_analyst_is_skipped_when_it_is_switched_off(tmp_path):
    gap = SAMPLE.model_copy(
        update={
            "roe": None,
            "field_sources": {**SAMPLE.field_sources, "roe": "unavailable"},
        }
    )
    test_client, provider = build_client_with_analyst(
        tmp_path, '{"roe": 0.35}', gap
    )

    body = test_client.get("/api/analysis/AAPL", params={"use_llm": "false"}).json()

    assert body["inputs"]["roe"] is None
    assert body["field_sources"]["roe"] == "unavailable"


def test_the_analyst_estimates_are_reused_instead_of_being_asked_again(tmp_path):
    gap = SAMPLE.model_copy(
        update={
            "roe": None,
            "field_sources": {**SAMPLE.field_sources, "roe": "unavailable"},
        }
    )
    test_client, provider = build_client_with_analyst(
        tmp_path, '{"roe": 0.35}', gap
    )

    first = test_client.get("/api/analysis/AAPL")
    second = test_client.get("/api/analysis/AAPL")

    assert first.json()["inputs"]["roe"] == pytest.approx(0.35)
    assert second.json()["inputs"]["roe"] == pytest.approx(0.35)
    assert provider.calls == ["AAPL"]


def build_client_with_a_counted_analyst(tmp_path, response: str, fundamentals):
    provider = FakeProvider(fundamentals)
    store = Store(tmp_path / "test.db")
    llm = FakeLLM(response)
    analyst = AnalystExtractor(llm, model_label="the analyst model (test)")
    service = AnalysisService(
        store=store, provider=provider, ttl_hours=24, analyst=analyst
    )
    return TestClient(create_app(service)), llm


def test_the_model_is_not_asked_again_when_it_declines_every_field(tmp_path):
    gap = SAMPLE.model_copy(
        update={
            "roe": None,
            "field_sources": {**SAMPLE.field_sources, "roe": "unavailable"},
        }
    )
    test_client, llm = build_client_with_a_counted_analyst(
        tmp_path, '{"roe": null}', gap
    )

    first = test_client.get("/api/analysis/AAPL")
    second = test_client.get("/api/analysis/AAPL")

    # A model that declines every field is an answer too: asking it again on
    # every request would pay its latency for nothing.
    assert first.json()["inputs"]["roe"] is None
    assert second.json()["inputs"]["roe"] is None
    assert len(llm.calls) == 1


def test_a_failure_of_the_model_is_not_cached(tmp_path):
    gap = SAMPLE.model_copy(
        update={
            "roe": None,
            "field_sources": {**SAMPLE.field_sources, "roe": "unavailable"},
        }
    )
    test_client, llm = build_client_with_a_counted_analyst(
        tmp_path, "I cannot answer that.", gap
    )

    test_client.get("/api/analysis/AAPL")
    test_client.get("/api/analysis/AAPL")

    # The model may well be reachable on the next request.
    assert len(llm.calls) == 2


# ------------------------------------------------------------------ sensitivity


def test_the_sensitivity_endpoint_returns_the_grid(client):
    test_client, _ = client

    response = test_client.get("/api/analysis/AAPL/sensitivity")
    assert response.status_code == 200
    body = response.json()

    assert len(body["wacc_axis"]) == 9
    assert len(body["g_axis"]) == 9
    assert len(body["cells"]) == 9
    assert len(body["cells"][0]) == 9

    base_cell = body["cells"][body["base_row"]][body["base_column"]]
    assert base_cell["valid"] is True
    assert base_cell["value_per_share"] == pytest.approx(body["base"]["value_per_share"])


def test_the_sensitivity_grid_is_centred_on_the_base_case(client):
    test_client, _ = client

    body = test_client.get("/api/analysis/AAPL/sensitivity").json()

    assert body["base"]["wacc"] == pytest.approx(0.089)
    assert body["wacc_axis"][body["base_column"]] == pytest.approx(body["base"]["wacc"])
    assert body["g_axis"][body["base_row"]] == pytest.approx(body["base"]["g"])


def test_the_sensitivity_grid_marks_a_cell_that_cannot_be_computed(client):
    test_client, _ = client

    body = test_client.get("/api/analysis/AAPL/sensitivity").json()

    invalid = [
        cell
        for row in body["cells"]
        for cell in row
        if not cell["valid"]
    ]
    assert invalid, "the grid should contain at least one invalid cell"


def test_the_sensitivity_endpoint_rejects_a_negative_span(client):
    test_client, _ = client

    response = test_client.get(
        "/api/analysis/AAPL/sensitivity", params={"span": "-1"}
    )

    assert response.status_code == 422


def test_the_sensitivity_endpoint_rejects_a_zero_step(client):
    test_client, _ = client

    response = test_client.get(
        "/api/analysis/AAPL/sensitivity", params={"step": "0"}
    )

    assert response.status_code == 422


def test_the_sensitivity_endpoint_rejects_a_grid_that_would_be_too_big(client):
    test_client, _ = client

    response = test_client.get(
        "/api/analysis/AAPL/sensitivity",
        params={"span": "10", "step": "0.0001"},
    )

    assert response.status_code == 422


def test_an_override_that_is_not_a_number_is_rejected(client):
    test_client, _ = client

    # Python's JSON parser accepts NaN and Infinity as literals, and they
    # would spread through the whole model as NaN.
    response = test_client.post(
        "/api/analysis/AAPL/overrides",
        content=b'{"beta": NaN}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    # The error body quotes the offending value back, and a body cannot hold
    # an infinity, so the error itself has to stay renderable.
    assert "beta" in response.text


def test_an_override_of_infinity_is_rejected(client):
    test_client, _ = client

    response = test_client.post(
        "/api/analysis/AAPL/overrides",
        content=b'{"growth_rate": Infinity}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert "growth_rate" in response.text


def test_a_negative_manual_growth_rate_is_reported_as_zero(client):
    test_client, _ = client

    body = test_client.post(
        "/api/analysis/AAPL/overrides", json={"growth_rate": -0.02}
    ).json()

    assert body["growth"]["growth"] == pytest.approx(0.0)
    assert "negative" in body["growth"]["reason"].lower()


# ------------------------------------------------------------------ adversarial


def test_a_lower_case_ticker_is_accepted(client):
    test_client, provider = client

    response = test_client.get("/api/analysis/aapl")

    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"
    assert provider.calls == ["AAPL"]


def test_a_ticker_that_is_not_a_ticker_returns_404(client):
    test_client, _ = client

    response = test_client.get("/api/analysis/ZZZZNOTATICKER")

    assert response.status_code == 404


def test_an_empty_ticker_returns_404(client):
    test_client, _ = client

    response = test_client.get("/api/analysis/%20")

    assert response.status_code == 404


def test_a_sql_injection_attempt_harms_nothing(client):
    test_client, _ = client

    response = test_client.get("/api/analysis/AAPL%27%3B%20DROP%20TABLE%20snapshots%3B--")

    # The provider is the fake one, so the ticker is unknown: the point is that
    # the database is still there afterwards.
    assert response.status_code in (200, 404)

    tables = test_client.get("/api/health").json()
    assert tables["status"] == "ok"

    # And the store still answers with the catalog.
    assert test_client.get("/api/tickers").json()["count"] > 40


def test_two_requests_for_the_same_ticker_in_parallel_both_answer(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    test_client, provider = build_client(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(lambda _: test_client.get("/api/analysis/AAPL"), range(8))
        )

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["ticker"] == "AAPL" for response in responses)


def test_writes_and_reads_in_parallel_do_not_collide(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    test_client, _ = build_client(tmp_path)

    def mixed(index: int):
        if index % 2 == 0:
            return test_client.get("/api/analysis/AAPL").status_code
        return test_client.post(
            "/api/analysis/AAPL/overrides", json={"beta": 1.0 + index / 100}
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(mixed, range(12)))

    assert all(code == 200 for code in codes)
