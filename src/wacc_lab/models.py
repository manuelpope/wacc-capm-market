"""Data models shared by the provider, the store, the service and the API."""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator

# Bumped whenever the shape of a snapshot changes, so a snapshot written by
# an older version is refreshed instead of being read with missing fields.
SNAPSHOT_SCHEMA_VERSION = 2


class Fundamentals(BaseModel):
    """Raw market and financial facts for one ticker, as seen by the provider."""

    ticker: str
    name: str
    sector: str | None = None
    currency: str | None = None
    provider: str = "yahoo"

    price: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None

    total_debt: float | None = None
    cash: float | None = None
    net_debt: float = 0.0
    equity_book: float | None = None

    risk_free_rate: float | None = None
    beta: float | None = None
    beta_source: str = "unavailable"
    pretax_cost_of_debt: float | None = None
    tax_rate: float | None = None

    roe: float | None = None
    retention_ratio: float | None = None

    fcf_ttm: float | None = None
    fcf_normalized: float | None = None
    fcf_years: int = 0
    net_income_ttm: float | None = None
    revenue_ttm: float | None = None

    fetched_at: str
    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    field_sources: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Overrides(BaseModel):
    """Manual inputs that win over whatever the provider returned."""

    beta: float | None = None
    risk_free_rate: float | None = None
    equity_risk_premium: float | None = None
    pretax_cost_of_debt: float | None = None
    tax_rate: float | None = None
    debt_weight: float | None = None
    growth_rate: float | None = None
    base_fcf: float | None = None
    projection_years: int | None = None

    @field_validator("*", mode="after")
    @classmethod
    def _has_to_be_finite(cls, value: object) -> object:
        """Reject NaN and infinity.

        The JSON parser of Python accepts `NaN` and `Infinity` as literals,
        so a request can carry them. They would then spread through the whole
        model: every number of the answer would become a NaN and the response
        would look successful while saying nothing.
        """
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("an override has to be a finite number")
        return value


class CacheInfo(BaseModel):
    status: str
    snapshot_at: str | None = None
    computed_at: str | None = None
    ttl_hours: float


class WaccBreakdown(BaseModel):
    cost_of_equity: float
    after_tax_cost_of_debt: float
    wacc: float
    debt_weight: float
    equity_weight: float
    equity_risk_premium: float


class GrowthBreakdown(BaseModel):
    method: str
    raw_growth: float
    growth: float
    capped: bool
    reason: str | None = None
    manual: bool = False


class ValuationBreakdown(BaseModel):
    base_fcf: float
    growth_rate: float
    wacc: float
    years: int
    projected_fcf: list[float]
    pv_explicit: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    terminal_value_share: float = 0.0
    value_per_share: float | None = None
    upside_pct: float | None = None


class AnalysisResult(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    currency: str | None = None
    price: float | None = None
    cache: CacheInfo
    inputs: dict[str, float | str | None]
    field_sources: dict[str, str] = Field(default_factory=dict)
    overrides: Overrides | None = None
    wacc: WaccBreakdown
    growth: GrowthBreakdown
    valuation: ValuationBreakdown | None = None
    news: list[NewsItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    title: str
    publisher: str | None = None
    published_at: str | None = None
    link: str | None = None
    summary: str | None = None
    relevance: int = 0


class SensitivityCellModel(BaseModel):
    valid: bool
    value_per_share: float | None = None
    upside_pct: float | None = None
    fragile: bool = False


class SensitivityGridModel(BaseModel):
    ticker: str
    currency: str | None = None
    price: float | None = None
    base: dict[str, float | str | None] = Field(default_factory=dict)
    wacc_axis: list[float] = Field(default_factory=list)
    g_axis: list[float] = Field(default_factory=list)
    cells: list[list[SensitivityCellModel]] = Field(default_factory=list)
    base_row: int = 0
    base_column: int = 0
    span: float = 0.0
    step: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class TickerInfo(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    country: str | None = None
