"""Property tests: invariants that must hold for any input.

The engines are the part of the application that must never surprise anyone,
so instead of testing a handful of examples the invariants are checked against
a seeded set of random inputs.
"""

from __future__ import annotations

import math
import random

import pytest

from wacc_lab.engine.growth import GrowthInputs, compute_growth
from wacc_lab.engine.sensitivity import compute_sensitivity
from wacc_lab.engine.valuation import ValuationInputs, compute_valuation
from wacc_lab.engine.wacc import WaccInputs, compute_wacc


def random_wacc_inputs(rng: random.Random) -> WaccInputs:
    debt_weight = rng.choice([0.0, 0.1, 0.3, 0.5, 0.8, 1.0])
    return WaccInputs(
        risk_free_rate=rng.uniform(0.0, 0.12),
        beta=rng.uniform(-0.5, 2.5),
        pretax_cost_of_debt=rng.uniform(0.0, 0.15),
        tax_rate=rng.uniform(0.0, 0.5),
        debt_weight=debt_weight,
        equity_weight=1.0 - debt_weight,
    )


def test_the_wacc_invariants_hold_for_any_input():
    rng = random.Random(20261118)
    for _ in range(300):
        inputs = random_wacc_inputs(rng)
        result = compute_wacc(inputs, equity_risk_premium=rng.uniform(0.0, 0.1))

        assert math.isfinite(result.wacc)
        assert math.isfinite(result.cost_of_equity)
        assert math.isfinite(result.after_tax_cost_of_debt)
        assert result.debt_weight + result.equity_weight == pytest.approx(1.0)
        assert 0.0 <= result.debt_weight <= 1.0
        assert 0.0 <= result.equity_weight <= 1.0
        # The blended cost sits between the two costs when both weights exist.
        if result.debt_weight > 0 and result.equity_weight > 0:
            low = min(result.cost_of_equity, result.after_tax_cost_of_debt)
            high = max(result.cost_of_equity, result.after_tax_cost_of_debt)
            assert low - 1e-9 <= result.wacc <= high + 1e-9


def test_the_growth_never_reaches_the_discount_rate():
    rng = random.Random(20261118)
    for _ in range(300):
        wacc = rng.uniform(0.01, 0.25)
        result = compute_growth(
            GrowthInputs(
                roe=rng.uniform(-0.5, 2.0),
                retention_ratio=rng.uniform(0.0, 1.0),
                wacc=wacc,
            )
        )

        assert math.isfinite(result.growth)
        assert result.growth >= 0.0
        assert result.growth < wacc
        assert result.capped == (result.reason is not None)


def test_the_valuation_is_monotonic_in_the_discount_rate_and_in_growth():
    rng = random.Random(20261118)
    for _ in range(120):
        base_fcf = rng.uniform(1.0, 1000.0)
        growth = rng.uniform(-0.05, 0.04)
        wacc = rng.uniform(0.06, 0.20)
        if growth >= wacc:
            continue

        def value(wacc_value: float, growth_value: float) -> float:
            return compute_valuation(
                ValuationInputs(
                    base_fcf=base_fcf,
                    growth_rate=growth_value,
                    wacc=wacc_value,
                    years=5,
                    net_debt=0.0,
                    shares_outstanding=10.0,
                    current_price=10.0,
                )
            ).enterprise_value

        assert value(wacc + 0.01, growth) < value(wacc, growth)
        assert value(wacc, growth + 0.005) > value(wacc, growth)


def test_the_valuation_never_produces_a_not_a_number():
    rng = random.Random(20261118)
    for _ in range(200):
        wacc = rng.uniform(0.02, 0.30)
        growth = rng.uniform(-0.10, 0.10)
        if growth >= wacc:
            continue
        result = compute_valuation(
            ValuationInputs(
                base_fcf=rng.uniform(-500.0, 5000.0),
                growth_rate=growth,
                wacc=wacc,
                years=rng.choice([1, 3, 5, 10]),
                net_debt=rng.uniform(-1000.0, 1000.0),
                shares_outstanding=rng.choice([0.0, 1.0, 1e9]),
                current_price=rng.choice([None, 0.0, 10.0]),
            )
        )

        assert math.isfinite(result.enterprise_value)
        assert math.isfinite(result.equity_value)
        assert math.isfinite(result.terminal_value)
        if result.value_per_share is not None:
            assert math.isfinite(result.value_per_share)
        if result.upside_pct is not None:
            assert math.isfinite(result.upside_pct)


def test_the_grid_base_cell_is_the_valuation():
    rng = random.Random(20261118)
    for _ in range(60):
        base_fcf = rng.uniform(10.0, 1000.0)
        wacc = rng.uniform(0.07, 0.20)
        growth = rng.uniform(-0.02, 0.03)
        if growth >= wacc:
            continue

        grid = compute_sensitivity(
            base_fcf=base_fcf,
            net_debt=0.0,
            shares_outstanding=10.0,
            current_price=10.0,
            base_wacc=wacc,
            base_growth=growth,
        )
        cell = grid.cells[grid.base_row][grid.base_column]
        direct = compute_valuation(
            ValuationInputs(
                base_fcf=base_fcf,
                growth_rate=growth,
                wacc=wacc,
                years=5,
                net_debt=0.0,
                shares_outstanding=10.0,
                current_price=10.0,
            )
        )

        assert cell.valid is True
        assert cell.value_per_share == pytest.approx(direct.value_per_share, rel=1e-9)
        assert grid.wacc_axis[grid.base_column] == pytest.approx(wacc, abs=1e-6)
        assert grid.g_axis[grid.base_row] == pytest.approx(growth, abs=1e-6)


def test_the_grid_axes_are_symmetric_around_the_base():
    rng = random.Random(20261118)
    for _ in range(60):
        wacc = rng.uniform(0.06, 0.25)
        growth = rng.uniform(-0.02, 0.05)

        grid = compute_sensitivity(
            base_fcf=100.0,
            net_debt=0.0,
            shares_outstanding=10.0,
            current_price=10.0,
            base_wacc=wacc,
            base_growth=growth,
        )

        middle = len(grid.wacc_axis) // 2
        assert grid.wacc_axis[middle] == pytest.approx(wacc, abs=1e-12)
        assert grid.g_axis[middle] == pytest.approx(growth, abs=1e-12)
        # Symmetric around the base: the neighbours are one step away.
        assert grid.wacc_axis[middle - 1] + grid.wacc_axis[middle + 1] == pytest.approx(
            2 * grid.wacc_axis[middle], abs=1e-9
        )
        assert grid.g_axis[middle - 1] + grid.g_axis[middle + 1] == pytest.approx(
            2 * grid.g_axis[middle], abs=1e-9
        )
