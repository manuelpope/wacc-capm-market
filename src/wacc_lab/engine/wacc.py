"""Cost of capital engine.

Ke = Rf + beta * ERP
Kd_after_tax = Kd * (1 - t)
WACC = We * Ke + Wd * Kd_after_tax
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_EQUITY_RISK_PREMIUM = 0.05


@dataclass(frozen=True)
class WaccInputs:
    risk_free_rate: float
    beta: float
    pretax_cost_of_debt: float
    tax_rate: float
    debt_weight: float
    equity_weight: float


@dataclass(frozen=True)
class WaccResult:
    cost_of_equity: float
    after_tax_cost_of_debt: float
    wacc: float
    debt_weight: float
    equity_weight: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def compute_wacc(
    inputs: WaccInputs,
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM,
) -> WaccResult:
    warnings: list[str] = []

    total_weight = inputs.debt_weight + inputs.equity_weight
    if total_weight <= 0:
        raise ValueError("capital structure weights must sum to a positive number")
    debt_weight = inputs.debt_weight / total_weight
    equity_weight = inputs.equity_weight / total_weight
    if abs(total_weight - 1.0) > 1e-9:
        warnings.append(
            f"capital structure weights summed to {total_weight:.4f} and were normalized"
        )

    tax_rate = inputs.tax_rate
    if not 0.0 <= tax_rate <= 1.0:
        warnings.append(f"tax rate {tax_rate:.4f} is outside [0, 1] and was clamped")
        tax_rate = min(max(tax_rate, 0.0), 1.0)

    beta = inputs.beta
    if beta < 0:
        warnings.append(f"beta {beta:.3f} is negative")

    cost_of_equity = inputs.risk_free_rate + beta * equity_risk_premium
    after_tax_cost_of_debt = inputs.pretax_cost_of_debt * (1.0 - tax_rate)
    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt

    if cost_of_equity > 0.25:
        warnings.append(
            f"cost of equity {cost_of_equity:.2%} is above 25%, review the beta or the risk-free rate"
        )
    if wacc <= 0:
        warnings.append(f"WACC {wacc:.2%} is not positive, the discount rate is unusable")
    elif wacc < 0.06:
        warnings.append(
            f"the WACC is only {wacc:.2%}, the terminal value of a perpetuity is extremely sensitive to it"
        )

    return WaccResult(
        cost_of_equity=cost_of_equity,
        after_tax_cost_of_debt=after_tax_cost_of_debt,
        wacc=wacc,
        debt_weight=debt_weight,
        equity_weight=equity_weight,
        warnings=tuple(warnings),
    )
