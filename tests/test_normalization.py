"""Tests for the normalization of a flow across fiscal years."""

from __future__ import annotations

import pytest

from wacc_lab.engine.normalization import normalized_average


def test_the_average_uses_the_last_three_years():
    value, years = normalized_average([90.0, 100.0, 120.0, 136.0])

    assert years == 3
    assert value == pytest.approx((100.0 + 120.0 + 136.0) / 3)


def test_a_short_series_uses_what_there_is():
    value, years = normalized_average([120.0, 136.0])

    assert years == 2
    assert value == pytest.approx(128.0)


def test_a_single_year_is_used_as_is():
    value, years = normalized_average([136.0])

    assert years == 1
    assert value == pytest.approx(136.0)


def test_the_missing_years_are_skipped():
    value, years = normalized_average([None, 120.0, None, 136.0])

    assert years == 2
    assert value == pytest.approx(128.0)


def test_an_empty_series_has_no_value():
    value, years = normalized_average([])

    assert value is None
    assert years == 0


def test_the_horizon_can_be_changed():
    value, years = normalized_average([90.0, 100.0, 120.0, 136.0], years=2)

    assert years == 2
    assert value == pytest.approx(128.0)


def test_a_zero_is_a_valid_figure_and_not_a_missing_one():
    value, years = normalized_average([0.0, 120.0, 136.0])

    assert years == 3
    assert value == pytest.approx((0.0 + 120.0 + 136.0) / 3)


def test_the_trailing_figure_reports_how_many_quarters_went_into_it():
    import pandas as pd

    from wacc_lab.providers.yahoo import _ttm

    series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])

    value, quarters = _ttm(series)

    assert value == pytest.approx(100.0)
    assert quarters == 4


def test_a_short_series_reports_fewer_quarters():
    import pandas as pd

    from wacc_lab.providers.yahoo import _ttm

    series = pd.Series([10.0, 20.0, None, None])

    value, quarters = _ttm(series)

    assert value == pytest.approx(30.0)
    assert quarters == 2


def test_no_series_is_no_value_and_no_quarters():
    from wacc_lab.providers.yahoo import _ttm

    value, quarters = _ttm(None)

    assert value is None
    assert quarters == 0
