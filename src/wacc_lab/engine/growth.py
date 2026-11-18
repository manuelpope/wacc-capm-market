"""Growth engine.

Default method: sustainable internal growth, g = ROE * retention ratio.

The raw figure is almost always unusable on its own (buybacks inflate ROE), so
the result is capped before it reaches the valuation:

* at a growth ceiling, because a perpetual growth rate above long-run nominal
  GDP is not sustainable;
* and so that the spread between the WACC and g stays wide enough for the
  Gordon denominator (WACC - g) to mean something.

Both caps report why they fired. A manual growth rate goes through the same
spread rule, but is not subject to the ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_GROWTH_CEILING = 0.05
DEFAULT_MAX_WACC_SPREAD = 0.03


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


def apply_growth_caps(
    raw_growth: float,
    wacc: float,
    ceiling: float | None = None,
    max_wacc_spread: float = DEFAULT_MAX_WACC_SPREAD,
) -> tuple[float, list[str], list[str]]:
    """Apply the ceiling and the minimum-spread rule.

    Returns (growth, reasons, warnings). The reasons explain every cap that
    fired, so the UI can show why the number moved.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    growth = raw_growth

    if ceiling is not None and raw_growth > ceiling:
        growth = ceiling
        reasons.append(f"capped at the {ceiling:.1%} growth ceiling")
        warnings.append(
            f"raw growth {raw_growth:.1%} exceeds the ceiling, the ROE is likely inflated by buybacks"
        )

    if wacc <= 0:
        reasons.append("the WACC is not positive, g was set to 0")
        return 0.0, reasons, warnings

    spread = wacc - growth
    if growth >= wacc:
        reasons.append("capped to stay strictly below the WACC")
        growth = wacc - max_wacc_spread
        warnings.append(
            "growth was forced below the WACC, the terminal value is highly sensitive to this cap"
        )
    elif spread < max_wacc_spread:
        reasons.append(
            f"capped to keep at least {max_wacc_spread:.1%} between the WACC and g"
        )
        growth = wacc - max_wacc_spread
        warnings.append(
            f"the WACC and g were only {spread:.1%} apart, which inflates the terminal "
            "value, so g was reduced"
        )

    if growth < 0:
        growth = 0.0
        reasons.append("the WACC is below the minimum spread, g was set to 0")

    return growth, reasons, warnings


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
    growth, reasons, warnings = apply_growth_caps(
        raw_growth,
        wacc=inputs.wacc,
        ceiling=inputs.ceiling,
        max_wacc_spread=inputs.max_wacc_spread,
    )

    return GrowthResult(
        raw_growth=raw_growth,
        growth=growth,
        method="roe_retention",
        capped=bool(reasons),
        reason="; ".join(reasons) if reasons else None,
        warnings=tuple(warnings),
    )
