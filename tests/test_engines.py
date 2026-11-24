"""Unit tests for the calculation engines (WACC, growth, valuation)."""

import math

import pytest

from wacc_lab.engine.growth import GrowthInputs, apply_growth_caps, compute_growth
from wacc_lab.engine.valuation import ValuationInputs, compute_valuation
from wacc_lab.engine.wacc import WaccInputs, compute_wacc


# --------------------------------------------------------------------------- WACC


def test_wacc_blended_cost_of_capital():
    result = compute_wacc(
        WaccInputs(
            risk_free_rate=0.04,
            beta=1.0,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            debt_weight=0.30,
            equity_weight=0.70,
        ),
        equity_risk_premium=0.05,
    )

    assert result.cost_of_equity == pytest.approx(0.09)
    assert result.after_tax_cost_of_debt == pytest.approx(0.045)
    assert result.wacc == pytest.approx(0.7 * 0.09 + 0.3 * 0.045)
    assert result.wacc == pytest.approx(0.0765)
    assert result.warnings == ()


def test_wacc_normalizes_weights_that_do_not_sum_to_one():
    result = compute_wacc(
        WaccInputs(
            risk_free_rate=0.04,
            beta=1.0,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            debt_weight=0.30,
            equity_weight=0.30,
        )
    )

    assert result.debt_weight == pytest.approx(0.5)
    assert result.equity_weight == pytest.approx(0.5)
    assert any("weights" in w.lower() for w in result.warnings)


def test_wacc_flags_negative_tax_rate():
    result = compute_wacc(
        WaccInputs(
            risk_free_rate=0.04,
            beta=1.0,
            pretax_cost_of_debt=0.06,
            tax_rate=-0.10,
            debt_weight=0.30,
            equity_weight=0.70,
        )
    )

    assert any("tax" in w.lower() for w in result.warnings)


def test_wacc_flags_a_cost_of_equity_above_twenty_five_percent():
    result = compute_wacc(
        WaccInputs(
            risk_free_rate=0.04,
            beta=5.0,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            debt_weight=0.30,
            equity_weight=0.70,
        )
    )

    # Ke = 0.04 + 5.0 * 0.05 = 29%
    assert any("cost of equity" in w.lower() for w in result.warnings)


# ------------------------------------------------------------------------- growth


def test_growth_uses_roe_times_retention_when_below_wacc():
    result = compute_growth(
        GrowthInputs(roe=0.20, retention_ratio=0.20, wacc=0.0765)
    )

    assert result.raw_growth == pytest.approx(0.04)
    assert result.growth == pytest.approx(0.04)
    assert result.capped is False
    assert result.method == "roe_retention"
    assert result.reason is None


def test_growth_is_capped_at_the_ceiling():
    result = compute_growth(
        GrowthInputs(roe=0.20, retention_ratio=0.50, wacc=0.089)
    )

    assert result.raw_growth == pytest.approx(0.10)
    assert result.growth == pytest.approx(0.05)
    assert result.capped is True
    assert "ceiling" in result.reason.lower()


def test_growth_is_forced_below_a_low_wacc():
    result = compute_growth(
        GrowthInputs(roe=0.20, retention_ratio=0.30, wacc=0.045)
    )

    assert result.raw_growth == pytest.approx(0.06)
    assert result.growth == pytest.approx(0.045 - 0.03)
    assert result.growth < 0.045
    assert result.capped is True
    assert "wacc" in result.reason.lower()


def test_growth_keeps_a_minimum_spread_between_the_wacc_and_g():
    result = compute_growth(
        GrowthInputs(roe=0.20, retention_ratio=0.50, wacc=0.06)
    )

    assert result.raw_growth == pytest.approx(0.10)
    assert result.growth == pytest.approx(0.03)
    assert result.capped is True
    assert "between the wacc and g" in result.reason.lower()


def test_growth_is_capped_at_the_ceiling_for_buyback_inflated_roe():
    result = compute_growth(
        GrowthInputs(roe=1.50, retention_ratio=0.85, wacc=0.15)
    )

    assert result.raw_growth == pytest.approx(1.275)
    assert result.growth == pytest.approx(0.05)
    assert result.capped is True
    assert "ceiling" in result.reason.lower()


def test_growth_is_zero_when_roe_is_not_positive():
    result = compute_growth(
        GrowthInputs(roe=-0.05, retention_ratio=0.50, wacc=0.10)
    )

    assert result.growth == pytest.approx(0.0)
    assert result.capped is True
    assert "roe" in result.reason.lower()


def test_growth_is_zero_when_inputs_are_missing():
    result = compute_growth(
        GrowthInputs(roe=None, retention_ratio=None, wacc=0.10)
    )

    assert result.growth == pytest.approx(0.0)
    assert result.capped is True
    assert "data" in result.reason.lower()


def test_a_negative_growth_rate_is_reported_as_such():
    # The reason has to name the real cause: the WACC was not the problem.
    growth, reasons, _warnings = apply_growth_caps(
        -0.02, wacc=0.10, ceiling=None
    )

    assert growth == pytest.approx(0.0)
    assert any("negative" in reason.lower() for reason in reasons)
    assert not any("wacc" in reason.lower() for reason in reasons)


def test_a_wacc_below_the_minimum_spread_is_reported_as_such():
    growth, reasons, _warnings = apply_growth_caps(
        0.05, wacc=0.01, ceiling=None
    )

    assert growth == pytest.approx(0.0)
    assert any("wacc" in reason.lower() for reason in reasons)


# ---------------------------------------------------------------------- valuation


def test_valuation_discounts_fcf_and_applies_gordon_terminal_value():
    result = compute_valuation(
        ValuationInputs(
            base_fcf=100.0,
            growth_rate=0.03,
            wacc=0.08,
            years=5,
            net_debt=200.0,
            shares_outstanding=10.0,
            current_price=20.0,
        )
    )

    assert result.projected_fcf == pytest.approx(
        [103.0, 106.09, 109.2727, 112.550881, 115.92740739]
    )
    assert result.pv_explicit == pytest.approx(434.6961412055962)
    assert result.terminal_value == pytest.approx(2388.104593058)
    assert result.pv_terminal == pytest.approx(1625.3038587944031)
    assert result.enterprise_value == pytest.approx(2059.999999999999)
    assert result.equity_value == pytest.approx(1859.999999999999)
    assert result.value_per_share == pytest.approx(186.0)
    assert result.upside_pct == pytest.approx(8.3)


def test_valuation_rejects_growth_at_or_above_wacc():
    with pytest.raises(ValueError):
        compute_valuation(
            ValuationInputs(
                base_fcf=100.0,
                growth_rate=0.08,
                wacc=0.08,
                years=5,
                net_debt=0.0,
                shares_outstanding=10.0,
            )
        )


def test_valuation_warns_on_negative_free_cash_flow():
    result = compute_valuation(
        ValuationInputs(
            base_fcf=-50.0,
            growth_rate=0.02,
            wacc=0.09,
            years=5,
            net_debt=0.0,
            shares_outstanding=10.0,
        )
    )

    assert any("free cash flow" in w.lower() for w in result.warnings)


def test_valuation_reports_no_value_per_share_on_a_negative_free_cash_flow():
    result = compute_valuation(
        ValuationInputs(
            base_fcf=-50.0,
            growth_rate=0.02,
            wacc=0.09,
            years=5,
            net_debt=0.0,
            shares_outstanding=10.0,
            current_price=20.0,
        )
    )

    assert result.value_per_share is None
    assert result.upside_pct is None


def test_valuation_without_shares_reports_no_per_share_value():
    result = compute_valuation(
        ValuationInputs(
            base_fcf=100.0,
            growth_rate=0.02,
            wacc=0.09,
            years=5,
            net_debt=0.0,
            shares_outstanding=0.0,
        )
    )

    assert result.value_per_share is None
    assert result.upside_pct is None
    assert any("shares" in w.lower() for w in result.warnings)


def test_valuation_uses_math_isclose_for_terminal_value():
    # A hand-checkable case: 100 growing at 5% forever, discounted at 10%.
    result = compute_valuation(
        ValuationInputs(
            base_fcf=100.0,
            growth_rate=0.05,
            wacc=0.10,
            years=1,
            net_debt=0.0,
            shares_outstanding=1.0,
        )
    )

    expected_fcf = 105.0
    expected_tv = expected_fcf * 1.05 / (0.10 - 0.05)
    assert math.isclose(result.terminal_value, expected_tv, rel_tol=1e-12)
    assert math.isclose(result.enterprise_value, expected_fcf / 1.1 + expected_tv / 1.1)


def test_the_terminal_value_share_is_zero_when_the_enterprise_value_is_negative():
    result = compute_valuation(
        ValuationInputs(
            base_fcf=-50.0,
            growth_rate=0.02,
            wacc=0.09,
            years=5,
            net_debt=0.0,
            shares_outstanding=10.0,
        )
    )

    assert result.enterprise_value < 0
    assert result.terminal_value_share == pytest.approx(0.0)
