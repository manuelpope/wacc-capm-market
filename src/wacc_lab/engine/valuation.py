"""Valuation engine: a deliberately simple FCFF-style DCF.

5-year constant-growth projection of free cash flow, Gordon terminal value,
enterprise value -> equity value -> value per share.

It is a teaching-grade model on purpose: one horizon, one growth rate, one
discount rate. It is not a full three-statement DCF.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PROJECTION_YEARS = 5


@dataclass(frozen=True)
class ValuationInputs:
    base_fcf: float
    growth_rate: float
    wacc: float
    years: int = DEFAULT_PROJECTION_YEARS
    net_debt: float = 0.0
    shares_outstanding: float = 0.0
    current_price: float | None = None


@dataclass(frozen=True)
class ValuationResult:
    projected_fcf: list[float]
    pv_explicit: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    terminal_value_share: float
    value_per_share: float | None
    upside_pct: float | None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def compute_valuation(inputs: ValuationInputs) -> ValuationResult:
    if inputs.wacc <= inputs.growth_rate:
        raise ValueError(
            "the growth rate must stay below the WACC, otherwise the terminal value diverges"
        )
    if inputs.years < 1:
        raise ValueError("the projection horizon must be at least one year")

    warnings: list[str] = []

    projected: list[float] = []
    pv_explicit = 0.0
    fcf = inputs.base_fcf
    for year in range(1, inputs.years + 1):
        fcf *= 1.0 + inputs.growth_rate
        projected.append(fcf)
        pv_explicit += fcf / ((1.0 + inputs.wacc) ** year)

    terminal_value = projected[-1] * (1.0 + inputs.growth_rate) / (
        inputs.wacc - inputs.growth_rate
    )
    pv_terminal = terminal_value / ((1.0 + inputs.wacc) ** inputs.years)

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - inputs.net_debt

    value_per_share: float | None = None
    upside_pct: float | None = None
    if inputs.shares_outstanding > 0:
        value_per_share = equity_value / inputs.shares_outstanding
        if inputs.current_price and inputs.current_price > 0:
            upside_pct = (value_per_share - inputs.current_price) / inputs.current_price
    else:
        warnings.append("shares outstanding are unavailable, value per share was not computed")

    terminal_value_share = pv_terminal / enterprise_value if enterprise_value else 0.0
    if terminal_value_share > 0.85:
        warnings.append(
            f"the terminal value is {terminal_value_share:.0%} of the enterprise value, "
            "the result lives almost entirely on the perpetuity assumption"
        )

    if inputs.base_fcf <= 0:
        warnings.append(
            "free cash flow is not positive, the valuation rests on a negative base and is not meaningful"
        )
    if equity_value < 0:
        warnings.append(
            "equity value is negative, net debt exceeds the enterprise value"
        )
    if upside_pct is not None and abs(upside_pct) > 5:
        warnings.append(
            "the implied upside is extreme, the model is more sensitive to g and WACC than to the price"
        )

    return ValuationResult(
        projected_fcf=projected,
        pv_explicit=pv_explicit,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        terminal_value_share=terminal_value_share,
        value_per_share=value_per_share,
        upside_pct=upside_pct,
        warnings=tuple(warnings),
    )
