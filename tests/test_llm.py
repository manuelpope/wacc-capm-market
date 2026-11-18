"""Tests for the LLM analyst fallback: parsing, validation and provenance."""

from __future__ import annotations

import json

import pytest

from wacc_lab.models import Fundamentals
from wacc_lab.providers.analyst import (
    ESTIMABLE_FIELDS,
    AnalystEstimate,
    AnalystExtractor,
    extract_json_object,
    missing_gaps,
)
from wacc_lab.providers.base import TickerNotFoundError


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls.append(prompt)
        return self.response


def fundamentals(**overrides) -> Fundamentals:
    base = dict(
        ticker="AAPL",
        name="Apple Inc.",
        sector="Technology",
        currency="USD",
        price=200.0,
        market_cap=3_000_000_000_000.0,
        shares_outstanding=15_000_000_000.0,
        total_debt=80_000_000_000.0,
        cash=50_000_000_000.0,
        net_debt=30_000_000_000.0,
        equity_book=60_000_000_000.0,
        risk_free_rate=0.05,
        beta=1.1,
        beta_source="yahoo",
        pretax_cost_of_debt=0.066,
        tax_rate=0.17,
        roe=1.2,
        retention_ratio=0.88,
        fcf_ttm=130_000_000_000.0,
        net_income_ttm=95_000_000_000.0,
        revenue_ttm=480_000_000_000.0,
        fetched_at="2026-11-18T12:00:00+00:00",
        field_sources={
            "pretax_cost_of_debt": "yahoo",
            "tax_rate": "yahoo",
            "roe": "yahoo",
            "retention_ratio": "yahoo",
            "fcf_ttm": "yahoo",
        },
    )
    base.update(overrides)
    return Fundamentals(**base)


# --------------------------------------------------------------------- parsing


def test_extract_json_object_from_a_fenced_block():
    text = 'Here you go:\n```json\n{"tax_rate": 0.17}\n```\nHope it helps.'
    assert extract_json_object(text) == {"tax_rate": 0.17}


def test_extract_json_object_from_prose_around_the_object():
    text = 'Sure. {"tax_rate": 0.17, "notes": {"tax_rate": "typical"}} Done.'
    assert extract_json_object(text)["tax_rate"] == 0.17


def test_extract_json_object_returns_none_when_there_is_no_json():
    assert extract_json_object("I cannot answer that.") is None


# -------------------------------------------------------------------- the gaps


def test_missing_gaps_only_reports_fallback_or_unavailable_fields():
    fund = fundamentals(
        pretax_cost_of_debt=0.066,
        tax_rate=0.17,
        roe=None,
        retention_ratio=0.88,
        fcf_ttm=None,
        field_sources={
            "pretax_cost_of_debt": "estimated_rf_plus_spread",
            "tax_rate": "yahoo",
            "roe": "unavailable",
            "retention_ratio": "yahoo",
            "fcf_ttm": "unavailable",
        },
    )

    gaps = missing_gaps(fund)

    assert "pretax_cost_of_debt" in gaps
    assert "roe" in gaps
    assert "fcf_ttm" in gaps
    assert "tax_rate" not in gaps
    assert "retention_ratio" not in gaps


def test_a_complete_company_has_no_gaps():
    assert missing_gaps(fundamentals()) == []


# ------------------------------------------------------------------ extraction


def test_the_extractor_returns_only_valid_values():
    llm = FakeLLM(
        json.dumps(
            {
                "tax_rate": 0.21,
                "roe": 0.45,
                "retention_ratio": 0.9,
                "pretax_cost_of_debt": 0.05,
                "fcf_margin": 0.28,
                "notes": {"roe": "high because of buybacks"},
            }
        )
    )
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fundamentals(), ["tax_rate", "roe"])

    assert estimate.values["tax_rate"] == pytest.approx(0.21)
    assert estimate.values["roe"] == pytest.approx(0.45)
    assert estimate.notes["roe"] == "high because of buybacks"
    assert "fcf_margin" not in estimate.values


def test_the_extractor_discards_values_out_of_range():
    llm = FakeLLM(json.dumps({"tax_rate": 450, "roe": 250.0}))
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fundamentals(), ["tax_rate", "roe"])

    assert estimate.values == {}
    assert any("tax_rate" in rejection for rejection in estimate.rejections)
    assert any("roe" in rejection for rejection in estimate.rejections)


def test_the_extractor_discards_a_rescued_percentage_below_the_plausible_floor():
    # 2 means 2%, which is not a plausible corporate tax rate.
    llm = FakeLLM(json.dumps({"tax_rate": 2}))
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fundamentals(), ["tax_rate"])

    assert estimate.values == {}
    assert any("tax_rate" in rejection for rejection in estimate.rejections)


def test_the_extractor_normalizes_a_percentage_returned_as_a_whole_number():
    llm = FakeLLM(json.dumps({"tax_rate": 21}))
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fundamentals(), ["tax_rate"])

    assert estimate.values["tax_rate"] == pytest.approx(0.21)


def test_the_extractor_keeps_a_null_as_a_declined_estimate():
    llm = FakeLLM(json.dumps({"tax_rate": None, "roe": 0.3}))
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fundamentals(), ["tax_rate", "roe"])

    assert "tax_rate" not in estimate.values
    assert estimate.values["roe"] == pytest.approx(0.3)


def test_the_extractor_prompt_carries_the_company_and_the_known_facts():
    llm = FakeLLM(json.dumps({"tax_rate": 0.2}))
    extractor = AnalystExtractor(llm)

    extractor.estimate("AAPL", fundamentals(), ["tax_rate"])

    prompt = llm.calls[0]
    assert "AAPL" in prompt
    assert "Apple Inc." in prompt
    assert "Technology" in prompt
    assert "tax_rate" in prompt


# ------------------------------------------------------------- applying values


def test_the_estimates_never_overwrite_a_yahoo_value():
    llm = FakeLLM(json.dumps({"tax_rate": 0.30, "roe": 0.25}))
    fund = fundamentals(
        tax_rate=0.17,
        roe=None,
        field_sources={
            "pretax_cost_of_debt": "yahoo",
            "tax_rate": "yahoo",
            "roe": "unavailable",
            "retention_ratio": "yahoo",
            "fcf_ttm": "yahoo",
        },
    )
    extractor = AnalystExtractor(llm)

    result = extractor.apply(fund, extractor.estimate("AAPL", fund, ["roe"]))

    assert result.tax_rate == pytest.approx(0.17)
    assert result.field_sources["tax_rate"] == "yahoo"


def test_the_applied_values_are_marked_as_coming_from_the_model():
    llm = FakeLLM(json.dumps({"roe": 0.25}))
    fund = fundamentals(
        roe=None,
        field_sources={
            "pretax_cost_of_debt": "yahoo",
            "tax_rate": "yahoo",
            "roe": "unavailable",
            "retention_ratio": "yahoo",
            "fcf_ttm": "yahoo",
        },
    )
    extractor = AnalystExtractor(llm)

    result = extractor.apply(fund, extractor.estimate("AAPL", fund, ["roe"]))

    assert result.roe == pytest.approx(0.25)
    assert result.field_sources["roe"] == "llm"
    assert any("roe" in warning for warning in result.warnings)


def test_an_fcf_margin_becomes_a_cash_flow_figure():
    llm = FakeLLM(json.dumps({"fcf_margin": 0.25}))
    fund = fundamentals(
        fcf_ttm=None,
        revenue_ttm=400_000_000_000.0,
        field_sources={
            "pretax_cost_of_debt": "yahoo",
            "tax_rate": "yahoo",
            "roe": "yahoo",
            "retention_ratio": "yahoo",
            "fcf_ttm": "unavailable",
        },
    )
    extractor = AnalystExtractor(llm)

    result = extractor.apply(fund, extractor.estimate("AAPL", fund, ["fcf_ttm"]))

    assert result.fcf_ttm == pytest.approx(100_000_000_000.0)
    assert result.field_sources["fcf_ttm"] == "llm"


def test_a_model_failure_leaves_the_yahoo_values_untouched():
    llm = FakeLLM("I am not going to answer that.")
    fund = fundamentals(
        roe=None,
        field_sources={
            "pretax_cost_of_debt": "yahoo",
            "tax_rate": "yahoo",
            "roe": "unavailable",
            "retention_ratio": "yahoo",
            "fcf_ttm": "yahoo",
        },
    )
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fund, ["roe"])
    result = extractor.apply(fund, estimate)

    assert result.roe is None
    assert result.field_sources["roe"] == "unavailable"
    assert any("analyst" in warning.lower() for warning in result.warnings)


def test_the_estimable_fields_are_a_closed_set():
    assert set(ESTIMABLE_FIELDS) == {
        "pretax_cost_of_debt",
        "tax_rate",
        "roe",
        "retention_ratio",
        "fcf_ttm",
    }


def test_the_provider_fallback_warning_is_dropped_when_the_model_answers():
    llm = FakeLLM(json.dumps({"pretax_cost_of_debt": 0.035}))
    fund = fundamentals(
        pretax_cost_of_debt=0.066,
        field_sources={
            "pretax_cost_of_debt": "estimated_rf_plus_spread",
            "tax_rate": "yahoo",
            "roe": "yahoo",
            "retention_ratio": "yahoo",
            "fcf_ttm": "yahoo",
        },
        warnings=[
            "[pretax_cost_of_debt] interest expense is unavailable, the cost of debt was "
            "estimated as the risk-free rate plus 1.5%",
            "[retention_ratio] no dividend line is reported",
        ],
    )
    extractor = AnalystExtractor(llm)

    estimate = extractor.estimate("AAPL", fund, ["pretax_cost_of_debt"])
    result = extractor.apply(fund, estimate)

    assert result.pretax_cost_of_debt == pytest.approx(0.035)
    assert not any(
        warning.startswith("[pretax_cost_of_debt]") for warning in result.warnings
    )
    # A warning about a field the model did not answer stays.
    assert any(warning.startswith("[retention_ratio]") for warning in result.warnings)
