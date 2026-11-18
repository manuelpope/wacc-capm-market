"""Growth engine.

Default method: sustainable internal growth, g = ROE * retention ratio.

The raw figure is almost always unusable on its own (buybacks inflate ROE), so
the result is capped twice: first at a growth ceiling, then strictly below the
WACC, because a perpetual growth rate at or above the discount rate makes the
terminal value diverge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_GROWTH_CEILING = 0.10
DEFAULT_MAX_WACC_SPREAD = 0.015


@dataclass(frozen=True)
class GrowthInputs:
    roe: float | None
    retention_ratio: float | None
    wacc: float
    ceiling: float = DEFAULT_GROWTH_CEILING
    max_wacc_spread: float = DEFAULT_MAX_WACC_SPREAD


@dataclass(frozen=True)
class GrowthResult:
    raw_growth: float
    growth: float
    method: str
    capped: bool
    reason: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def compute_growth(inputs: GrowthInputs) -> GrowthResult:
    if inputs.roe is None or inputs.retention_ratio is None:
        return GrowthResult(
            raw_growth=0.0,
            growth=0.0,
            method="roe_retention",
            capped=True,
            reason="insufficient data: ROE or retention ratio is unavailable",
            warnings=(
                "growth could not be derived from the fundamentals, g was set to 0",
            ),
        )

    if inputs.roe <= 0:
        return GrowthResult(
            raw_growth=0.0,
            growth=0.0,
            method="roe_retention",
            capped=True,
            reason="ROE is not positive, g was set to 0",
            warnings=(
                "non-positive ROE, the company is not funding growth from retained earnings",
            ),
        )

    raw_growth = inputs.roe * inputs.retention_ratio
    growth = raw_growth
    reasons: list[str] = []
    warnings: list[str] = []

    if raw_growth > inputs.ceiling:
        growth = inputs.ceiling
        reasons.append(f"capped at the {inputs.ceiling:.1%} growth ceiling")
        warnings.append(
            f"raw growth {raw_growth:.1%} exceeds the ceiling, the ROE is likely inflated by buybacks"
        )

    if growth >= inputs.wacc:
        growth = inputs.wacc - inputs.max_wacc_spread
        reasons.append(
            f"capped at WACC minus {inputs.max_wacc_spread:.1%} to stay strictly below the discount rate"
        )
        warnings.append(
            "growth was forced below the WACC, the terminal value is highly sensitive to this cap"
        )

    return GrowthResult(
        raw_growth=raw_growth,
        growth=growth,
        method="roe_retention",
        capped=bool(reasons),
        reason="; ".join(reasons) if reasons else None,
        warnings=tuple(warnings),
    )
