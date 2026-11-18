"""Sensitivity grid: the value per share for combinations of WACC and g.

The grid is the answer to the question a single number cannot answer: how much
of this valuation depends on the two assumptions that carry the most weight.

Two kinds of cell exist:

* **invalid** — the growth rate is not below the WACC, so the terminal value
  does not exist and no number is reported;
* **fragile** — the spread between the WACC and g is under the minimum that
  keeps the Gordon denominator meaningful, so the number is reported but
  flagged: the terminal value dominates it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .valuation import DEFAULT_PROJECTION_YEARS, ValuationInputs, compute_valuation

DEFAULT_SPAN = 0.02
DEFAULT_STEP = 0.005
DEFAULT_MIN_SPREAD = 0.03


@dataclass(frozen=True)
class SensitivityCell:
    valid: bool
    value_per_share: float | None = None
    upside_pct: float | None = None
    fragile: bool = False


@dataclass(frozen=True)
class SensitivityGrid:
    wacc_axis: list[float]
    g_axis: list[float]
    cells: list[list[SensitivityCell]]
    base_row: int
    base_column: int
    span: float
    step: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _axis(base: float, span: float, step: float) -> list[float]:
    half = int(round(span / step))
    # Rounded so the labels do not show floating point noise.
    return [round(base + offset * step, 6) for offset in range(-half, half + 1)]


def compute_sensitivity(
    base_fcf: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    base_wacc: float,
    base_growth: float,
    span: float = DEFAULT_SPAN,
    step: float = DEFAULT_STEP,
    min_spread: float = DEFAULT_MIN_SPREAD,
    years: int = DEFAULT_PROJECTION_YEARS,
) -> SensitivityGrid:
    if step <= 0:
        raise ValueError("the step of the grid has to be positive")

    wacc_axis = _axis(base_wacc, span, step)
    g_axis = _axis(base_growth, span, step)
    base_row = g_axis.index(round(base_growth, 6))
    base_column = wacc_axis.index(round(base_wacc, 6))

    warnings: list[str] = []
    if base_fcf <= 0:
        warnings.append(
            "the free cash flow is not positive, the grid has no values to show"
        )

    cells: list[list[SensitivityCell]] = []
    for growth in g_axis:
        row: list[SensitivityCell] = []
        for wacc in wacc_axis:
            if growth >= wacc:
                row.append(SensitivityCell(valid=False))
                continue
            try:
                result = compute_valuation(
                    ValuationInputs(
                        base_fcf=base_fcf,
                        growth_rate=growth,
                        wacc=wacc,
                        years=years,
                        net_debt=net_debt,
                        shares_outstanding=shares_outstanding,
                        current_price=current_price,
                    )
                )
            except ValueError:
                row.append(SensitivityCell(valid=False))
                continue
            row.append(
                SensitivityCell(
                    valid=True,
                    value_per_share=result.value_per_share,
                    upside_pct=result.upside_pct,
                    fragile=(wacc - growth) < min_spread,
                )
            )
        cells.append(row)

    return SensitivityGrid(
        wacc_axis=wacc_axis,
        g_axis=g_axis,
        cells=cells,
        base_row=base_row,
        base_column=base_column,
        span=span,
        step=step,
        warnings=tuple(warnings),
    )
