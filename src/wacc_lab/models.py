"""Data models shared by the provider, the store, the service and the API."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    net_income_ttm: float | None = None
    revenue_ttm: float | None = None

    fetched_at: str
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
    warnings: list[str] = Field(default_factory=list)


class TickerInfo(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    country: str | None = None
