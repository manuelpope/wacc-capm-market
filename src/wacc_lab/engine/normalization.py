"""Normalization of a flow across fiscal years.

The valuation needs a base free cash flow that does not carry the noise of a
single unusual quarter. The average of the last fiscal years is that base: it
is what the business earned on average, and the model then grows it.

The helper is deliberately pure so it can be tested without a provider.
"""

from __future__ import annotations

from typing import Iterable

DEFAULT_HORIZON_YEARS = 3


def normalized_average(
    values: Iterable[float | None],
    years: int = DEFAULT_HORIZON_YEARS,
) -> tuple[float | None, int]:
    """The average of the last `years` figures, and how many were used.

    The values are expected in chronological order, oldest first. Missing
    figures are skipped; a zero is a real figure and is kept.
    """
    if years < 1:
        raise ValueError("the horizon has to be at least one year")

    usable = [value for value in values if value is not None]
    if not usable:
        return None, 0

    chosen = usable[-years:]
    return sum(chosen) / len(chosen), len(chosen)
