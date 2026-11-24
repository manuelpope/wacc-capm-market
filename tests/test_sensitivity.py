"""Tests for the WACC x g sensitivity grid."""

from __future__ import annotations

import pytest

from wacc_lab.engine.sensitivity import compute_sensitivity


def test_the_axes_are_centred_on_the_base_case():
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.10,
        base_growth=0.03,
    )

    assert len(grid.wacc_axis) == 9
    assert len(grid.g_axis) == 9
    assert grid.wacc_axis[4] == pytest.approx(0.10)
    assert grid.g_axis[4] == pytest.approx(0.03)
    assert grid.wacc_axis[0] == pytest.approx(0.08)
    assert grid.wacc_axis[-1] == pytest.approx(0.12)
    assert grid.g_axis[0] == pytest.approx(0.01)
    assert grid.g_axis[-1] == pytest.approx(0.05)


def test_the_base_cell_matches_the_base_valuation():
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.10,
        base_growth=0.03,
    )

    cell = grid.cells[grid.base_row][grid.base_column]

    assert cell.valid is True
    assert cell.value_per_share == pytest.approx(147.14285714285708, rel=1e-9)
    assert cell.upside_pct == pytest.approx((147.14285714285708 - 20.0) / 20.0)


def test_a_cell_where_growth_is_not_below_the_wacc_is_invalid():
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.06,
        base_growth=0.05,
    )

    # g = 0.07 and WACC = 0.06: the terminal value does not exist.
    row = grid.g_axis.index(0.07)
    column = grid.wacc_axis.index(0.06)

    cell = grid.cells[row][column]

    assert cell.valid is False
    assert cell.value_per_share is None
    assert cell.upside_pct is None


def test_a_cell_with_a_narrow_spread_is_flagged_as_fragile():
    # A low WACC makes the axes overlap, and the cells where they do come
    # with a spread under the 3% floor.
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.06,
        base_growth=0.04,
    )

    # g = 0.055 against a WACC of 0.06 leaves a 0.5% spread.
    row = grid.g_axis.index(0.055)
    column = grid.wacc_axis.index(0.06)
    wide_row = grid.g_axis.index(0.02)

    assert grid.cells[row][column].valid is True
    assert grid.cells[row][column].fragile is True
    assert grid.cells[wide_row][column].fragile is False


def test_the_value_falls_when_the_wacc_rises_and_rises_when_growth_rises():
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.10,
        base_growth=0.03,
    )

    base = grid.cells[grid.base_row][grid.base_column].value_per_share
    # The axes grow: a higher column is a higher WACC, a lower row is a lower g.
    pricier_discount = grid.cells[grid.base_row][grid.base_column + 1].value_per_share
    faster_growth = grid.cells[grid.base_row + 1][grid.base_column].value_per_share

    assert pricier_discount < base
    assert faster_growth > base


def test_a_negative_base_cash_flow_leaves_the_grid_without_values():
    grid = compute_sensitivity(
        base_fcf=-50.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.10,
        base_growth=0.03,
    )

    assert all(
        cell.value_per_share is None
        for row in grid.cells
        for cell in row
    )
    assert any("cash flow" in warning.lower() for warning in grid.warnings)


def test_the_grid_reports_the_span_it_used():
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.10,
        base_growth=0.03,
        span=0.01,
        step=0.005,
    )

    assert len(grid.wacc_axis) == 5
    assert grid.wacc_axis[0] == pytest.approx(0.09)
    assert grid.span == pytest.approx(0.01)


# ------------------------------------------------------------------ the limits


def test_a_negative_span_is_rejected():
    # A negative span used to build an empty axis, and the empty grid then
    # made the endpoint fail with an index error.
    with pytest.raises(ValueError):
        compute_sensitivity(
            base_fcf=100.0,
            net_debt=0.0,
            shares_outstanding=10.0,
            current_price=20.0,
            base_wacc=0.10,
            base_growth=0.03,
            span=-0.01,
        )


def test_a_zero_step_is_rejected():
    with pytest.raises(ValueError):
        compute_sensitivity(
            base_fcf=100.0,
            net_debt=0.0,
            shares_outstanding=10.0,
            current_price=20.0,
            base_wacc=0.10,
            base_growth=0.03,
            step=0.0,
        )


def test_a_grid_that_would_be_too_big_is_rejected():
    with pytest.raises(ValueError):
        compute_sensitivity(
            base_fcf=100.0,
            net_debt=0.0,
            shares_outstanding=10.0,
            current_price=20.0,
            base_wacc=0.10,
            base_growth=0.03,
            span=1.0,
            step=0.0001,
        )


def test_a_normal_grid_is_still_built():
    grid = compute_sensitivity(
        base_fcf=100.0,
        net_debt=0.0,
        shares_outstanding=10.0,
        current_price=20.0,
        base_wacc=0.10,
        base_growth=0.03,
        span=0.02,
        step=0.005,
    )

    assert len(grid.wacc_axis) == 9
    assert len(grid.cells) == 9
