"""Analysis service: orchestrates provider, cache, overrides and engines."""

from __future__ import annotations

import re
from typing import Any

from .db import Store, utcnow_iso
from .engine.growth import GrowthInputs, apply_growth_caps, compute_growth
from .engine.sensitivity import DEFAULT_SPAN, DEFAULT_STEP, compute_sensitivity
from .engine.valuation import ValuationInputs, compute_valuation
from .engine.wacc import DEFAULT_EQUITY_RISK_PREMIUM, WaccInputs, compute_wacc
from .models import (
    SNAPSHOT_SCHEMA_VERSION,
    AnalysisResult,
    CacheInfo,
    Fundamentals,
    GrowthBreakdown,
    NewsItem,
    Overrides,
    SensitivityCellModel,
    SensitivityGridModel,
    ValuationBreakdown,
    WaccBreakdown,
)
from .providers.analyst import AnalystEstimate, AnalystExtractor, missing_gaps
from .providers.base import FundamentalsProvider, ProviderError
from .providers.news import NewsProvider

DEFAULT_TAX_RATE = 0.21
DEFAULT_RISK_FREE_RATE = 0.04
DEFAULT_COST_OF_DEBT_SPREAD = 0.015
DEFAULT_PROJECTION_YEARS = 5


class AnalysisService:
    def __init__(
        self,
        store: Store,
        provider: FundamentalsProvider,
        ttl_hours: float = 24.0,
        analyst: AnalystExtractor | None = None,
        news_provider: NewsProvider | None = None,
        news_ttl_hours: float = 6.0,
        news_limit: int = 8,
    ) -> None:
        self.store = store
        self.provider = provider
        self.ttl_hours = ttl_hours
        self.analyst = analyst
        self.news_provider = news_provider
        self.news_ttl_hours = news_ttl_hours
        self.news_limit = news_limit

    # ------------------------------------------------------------- public API
    def analyze(
        self, ticker: str, refresh: bool = False, use_llm: bool = True
    ) -> AnalysisResult:
        symbol = ticker.strip().upper()
        fundamentals, status = self._snapshot(symbol, refresh)
        news = self._news_step(symbol, refresh, use_llm, fundamentals.name)
        if use_llm and self.analyst is not None:
            fundamentals = self._analyst_step(symbol, fundamentals, news)
        overrides = self.store.get_overrides(symbol)
        result = self._build(symbol, fundamentals, overrides, status, news)
        result.cache.computed_at = utcnow_iso()
        return result

    def set_overrides(
        self, ticker: str, overrides: Overrides, use_llm: bool = True
    ) -> AnalysisResult:
        symbol = ticker.strip().upper()
        self.store.save_overrides(symbol, overrides)
        return self.analyze(symbol, use_llm=use_llm)

    def clear_overrides(self, ticker: str, use_llm: bool = True) -> AnalysisResult:
        symbol = ticker.strip().upper()
        self.store.delete_overrides(symbol)
        return self.analyze(symbol, use_llm=use_llm)

    def sensitivity(
        self,
        ticker: str,
        use_llm: bool = True,
        span: float = DEFAULT_SPAN,
        step: float = DEFAULT_STEP,
    ) -> SensitivityGridModel:
        """The value per share for combinations of WACC and g around the base case."""
        symbol = ticker.strip().upper()
        analysis = self.analyze(symbol, use_llm=use_llm)

        valuation = analysis.valuation
        if valuation is None:
            return SensitivityGridModel(
                ticker=symbol,
                currency=analysis.currency,
                price=analysis.price,
                base={
                    "wacc": analysis.wacc.wacc,
                    "g": analysis.growth.growth,
                    "value_per_share": None,
                },
                warnings=[
                    "the valuation is not available for this company, the grid is empty"
                ],
            )

        shares = float(analysis.inputs.get("shares_outstanding") or 0.0)
        grid = compute_sensitivity(
            base_fcf=valuation.base_fcf,
            net_debt=valuation.net_debt,
            shares_outstanding=shares,
            current_price=analysis.price,
            base_wacc=analysis.wacc.wacc,
            base_growth=analysis.growth.growth,
            span=span,
            step=step,
            years=valuation.years,
        )

        base_cell = grid.cells[grid.base_row][grid.base_column]
        return SensitivityGridModel(
            ticker=symbol,
            currency=analysis.currency,
            price=analysis.price,
            base={
                "wacc": analysis.wacc.wacc,
                "g": analysis.growth.growth,
                "value_per_share": base_cell.value_per_share,
                "upside_pct": base_cell.upside_pct,
                "price": analysis.price,
            },
            wacc_axis=grid.wacc_axis,
            g_axis=grid.g_axis,
            cells=[
                [
                    SensitivityCellModel(
                        valid=cell.valid,
                        value_per_share=cell.value_per_share,
                        upside_pct=cell.upside_pct,
                        fragile=cell.fragile,
                    )
                    for cell in row
                ]
                for row in grid.cells
            ],
            base_row=grid.base_row,
            base_column=grid.base_column,
            span=grid.span,
            step=grid.step,
            warnings=list(grid.warnings),
        )

    # -------------------------------------------------------------- internals
    def _news_step(
        self,
        symbol: str,
        refresh: bool,
        use_llm: bool,
        company_name: str | None = None,
    ) -> list[NewsItem]:
        """Load the stories that feed the analyst, with a cache of their own."""
        if not use_llm or self.news_provider is None:
            return []
        age = self.store.news_age_hours(symbol)
        if refresh or age is None or age > self.news_ttl_hours:
            try:
                items = self.news_provider.fetch(
                    symbol, limit=self.news_limit, company_name=company_name
                )
            except ProviderError:
                # The news are context, not the analysis: a failure here must not
                # take the whole valuation down.
                items = []
            if items:
                self.store.save_news(symbol, [item.model_dump() for item in items])
        return [
            NewsItem(**row) for row in self.store.get_news(symbol, self.news_limit)
        ]

    def _snapshot(self, symbol: str, refresh: bool) -> tuple[Fundamentals, str]:
        if refresh:
            fundamentals, status = self._fetch(symbol), "refreshed"
        else:
            fundamentals = self.store.get_snapshot(symbol)
            if fundamentals is None:
                fundamentals, status = self._fetch(symbol), "computed"
            elif (
                not fundamentals.field_sources
                or fundamentals.schema_version != SNAPSHOT_SCHEMA_VERSION
            ):
                # A snapshot written by an older version cannot be used: it would
                # be read with missing fields and the analyst step would not know
                # what Yahoo really computed.
                fundamentals, status = self._fetch(symbol), "stale"
            else:
                age = self.store.snapshot_age_hours(symbol)
                if age is not None and age > self.ttl_hours:
                    fundamentals, status = self._fetch(symbol), "stale"
                else:
                    status = "fresh"

        return fundamentals, status

    def _analyst_step(
        self,
        symbol: str,
        fundamentals: Fundamentals,
        news: list[NewsItem] | None = None,
    ) -> Fundamentals:
        """Fill the gaps the provider left with the analyst model.

        The estimates are stored next to the snapshot, so a second request
        does not pay for the model again, and a request with the analyst
        switched off simply ignores them.
        """
        gaps = missing_gaps(fundamentals)
        if not gaps:
            return fundamentals

        stored = self.store.get_llm_estimates(symbol)
        if (
            stored
            and stored.get("snapshot_at") == fundamentals.fetched_at
            and set(gaps).issubset(stored.get("values", {}))
        ):
            estimate = AnalystEstimate(
                values=stored.get("values", {}), notes=stored.get("notes", {})
            )
        else:
            estimate = self.analyst.estimate(symbol, fundamentals, gaps, news=news)
            if estimate.values:
                self.store.save_llm_estimates(
                    ticker=symbol,
                    snapshot_at=fundamentals.fetched_at,
                    model=self.analyst.model_label,
                    values=estimate.values,
                    notes=estimate.notes,
                )
        return self.analyst.apply(fundamentals, estimate)

    def _fetch(self, symbol: str) -> Fundamentals:
        fundamentals = self.provider.fetch(symbol)
        self.store.save_snapshot(fundamentals)
        return fundamentals

    def _build(
        self,
        symbol: str,
        fundamentals: Fundamentals,
        overrides: Overrides | None,
        status: str,
        news: list[NewsItem] | None = None,
    ) -> AnalysisResult:
        active = overrides or Overrides()
        warnings: list[str] = [
            re.sub(r"^\[[a-z_]+\] ", "", warning) for warning in fundamentals.warnings
        ]

        risk_free_rate = self._resolve(
            active.risk_free_rate,
            fundamentals.risk_free_rate,
            DEFAULT_RISK_FREE_RATE,
            "the risk-free rate was not available, 4.0% was used",
            warnings,
        )
        beta = self._resolve(
            active.beta,
            fundamentals.beta,
            1.0,
            "beta was not available, 1.0 was used as a neutral assumption",
            warnings,
        )
        equity_risk_premium = self._resolve(
            active.equity_risk_premium,
            DEFAULT_EQUITY_RISK_PREMIUM,
            DEFAULT_EQUITY_RISK_PREMIUM,
            "",
            warnings,
        )
        pretax_cost_of_debt = self._resolve(
            active.pretax_cost_of_debt,
            fundamentals.pretax_cost_of_debt,
            risk_free_rate + DEFAULT_COST_OF_DEBT_SPREAD,
            "the cost of debt was not available, the risk-free rate plus 1.5% was used",
            warnings,
        )
        tax_rate = self._resolve(
            active.tax_rate,
            fundamentals.tax_rate,
            DEFAULT_TAX_RATE,
            "the tax rate was not available, 21.0% was used",
            warnings,
        )

        debt_weight, equity_weight = self._capital_structure(
            fundamentals, active.debt_weight, warnings
        )

        wacc_result = compute_wacc(
            WaccInputs(
                risk_free_rate=risk_free_rate,
                beta=beta,
                pretax_cost_of_debt=pretax_cost_of_debt,
                tax_rate=tax_rate,
                debt_weight=debt_weight,
                equity_weight=equity_weight,
            ),
            equity_risk_premium=equity_risk_premium,
        )
        warnings.extend(wacc_result.warnings)

        growth = self._growth(fundamentals, active, wacc_result.wacc, warnings)

        valuation = self._valuation(
            fundamentals, active, wacc_result.wacc, growth.growth, warnings
        )

        inputs: dict[str, Any] = {
            "risk_free_rate": risk_free_rate,
            "equity_risk_premium": equity_risk_premium,
            "beta": beta,
            "beta_source": fundamentals.beta_source,
            "pretax_cost_of_debt": pretax_cost_of_debt,
            "tax_rate": tax_rate,
            "total_debt": fundamentals.total_debt,
            "cash": fundamentals.cash,
            "market_cap": fundamentals.market_cap,
            "equity_book": fundamentals.equity_book,
            "debt_weight": wacc_result.debt_weight,
            "equity_weight": wacc_result.equity_weight,
            "roe": fundamentals.roe,
            "retention_ratio": fundamentals.retention_ratio,
            "base_fcf": fundamentals.fcf_normalized
            if fundamentals.fcf_normalized is not None
            else fundamentals.fcf_ttm,
            "fcf_ttm": fundamentals.fcf_ttm,
            "fcf_years": fundamentals.fcf_years,
            "net_debt": fundamentals.net_debt,
            "shares_outstanding": fundamentals.shares_outstanding,
            "price": fundamentals.price,
            "net_income_ttm": fundamentals.net_income_ttm,
            "revenue_ttm": fundamentals.revenue_ttm,
        }

        return AnalysisResult(
            ticker=symbol,
            name=fundamentals.name,
            sector=fundamentals.sector,
            currency=fundamentals.currency,
            price=fundamentals.price,
            field_sources=fundamentals.field_sources,
            cache=CacheInfo(
                status=status,
                snapshot_at=fundamentals.fetched_at,
                computed_at=None,
                ttl_hours=self.ttl_hours,
            ),
            inputs=inputs,
            overrides=overrides,
            wacc=WaccBreakdown(
                cost_of_equity=wacc_result.cost_of_equity,
                after_tax_cost_of_debt=wacc_result.after_tax_cost_of_debt,
                wacc=wacc_result.wacc,
                debt_weight=wacc_result.debt_weight,
                equity_weight=wacc_result.equity_weight,
                equity_risk_premium=equity_risk_premium,
            ),
            growth=growth,
            valuation=valuation,
            news=news or [],
            warnings=warnings,
        )

    @staticmethod
    def _resolve(
        override: float | None,
        automatic: float | None,
        fallback: float,
        warning: str,
        warnings: list[str],
    ) -> float:
        if override is not None:
            return override
        if automatic is not None:
            return automatic
        if warning:
            warnings.append(warning)
        return fallback

    @staticmethod
    def _capital_structure(
        fundamentals: Fundamentals,
        override: float | None,
        warnings: list[str],
    ) -> tuple[float, float]:
        if override is not None:
            debt_weight = min(max(override, 0.0), 1.0)
            return debt_weight, 1.0 - debt_weight

        debt = fundamentals.total_debt or 0.0
        equity = fundamentals.market_cap or fundamentals.equity_book
        if not equity or equity <= 0:
            if debt > 0:
                warnings.append(
                    "the market value of equity is unavailable, the capital structure was set to all debt"
                )
                return 1.0, 0.0
            warnings.append(
                "neither debt nor equity could be read, the capital structure was set to all equity"
            )
            return 0.0, 1.0

        debt_weight = debt / (debt + equity)
        return debt_weight, 1.0 - debt_weight

    @staticmethod
    def _growth(
        fundamentals: Fundamentals,
        overrides: Overrides,
        wacc: float,
        warnings: list[str],
    ) -> GrowthBreakdown:
        if overrides.growth_rate is not None:
            manual = overrides.growth_rate
            growth, reasons, growth_warnings = apply_growth_caps(
                manual, wacc=wacc, ceiling=None
            )
            warnings.extend(growth_warnings)
            return GrowthBreakdown(
                method="manual",
                raw_growth=manual,
                growth=growth,
                capped=bool(reasons),
                reason="; ".join(reasons) if reasons else None,
                manual=True,
            )

        result = compute_growth(
            GrowthInputs(
                roe=fundamentals.roe,
                retention_ratio=fundamentals.retention_ratio,
                wacc=wacc,
            )
        )
        warnings.extend(result.warnings)
        return GrowthBreakdown(
            method=result.method,
            raw_growth=result.raw_growth,
            growth=result.growth,
            capped=result.capped,
            reason=result.reason,
            manual=False,
        )

    @staticmethod
    def _valuation(
        fundamentals: Fundamentals,
        overrides: Overrides,
        wacc: float,
        growth: float,
        warnings: list[str],
    ) -> ValuationBreakdown | None:
        if overrides.base_fcf is not None:
            base_fcf = overrides.base_fcf
        elif fundamentals.fcf_normalized is not None:
            base_fcf = fundamentals.fcf_normalized
        else:
            base_fcf = fundamentals.fcf_ttm

        if (
            overrides.base_fcf is None
            and fundamentals.fcf_ttm
            and fundamentals.fcf_normalized
        ):
            difference = (
                fundamentals.fcf_normalized - fundamentals.fcf_ttm
            ) / abs(fundamentals.fcf_ttm)
            if abs(difference) > 0.25:
                direction = "above" if difference > 0 else "below"
                extreme = ""
                if abs(difference) > 0.5:
                    extreme = (
                        " The trailing figure looks like a cycle extreme, so the "
                        "normalized base is the one to question."
                    )
                warnings.append(
                    f"the normalized free cash flow "
                    f"({fundamentals.fcf_years} years, {fundamentals.fcf_normalized:,.0f}) is "
                    f"{abs(difference):.0%} {direction} the trailing twelve months "
                    f"({fundamentals.fcf_ttm:,.0f}), the valuation uses the normalized one."
                    f"{extreme}"
                )
        years = overrides.projection_years or DEFAULT_PROJECTION_YEARS
        if base_fcf is None:
            warnings.append(
                "free cash flow is unavailable, the valuation was not computed"
            )
            return None
        try:
            result = compute_valuation(
                ValuationInputs(
                    base_fcf=base_fcf,
                    growth_rate=growth,
                    wacc=wacc,
                    years=years,
                    net_debt=fundamentals.net_debt,
                    shares_outstanding=fundamentals.shares_outstanding or 0.0,
                    current_price=fundamentals.price,
                )
            )
        except ValueError as exc:
            warnings.append(f"the valuation could not be computed: {exc}")
            return None

        warnings.extend(result.warnings)
        return ValuationBreakdown(
            base_fcf=base_fcf,
            growth_rate=growth,
            wacc=wacc,
            years=years,
            projected_fcf=result.projected_fcf,
            pv_explicit=result.pv_explicit,
            terminal_value=result.terminal_value,
            pv_terminal=result.pv_terminal,
            enterprise_value=result.enterprise_value,
            net_debt=fundamentals.net_debt,
            equity_value=result.equity_value,
            terminal_value_share=result.terminal_value_share,
            value_per_share=result.value_per_share,
            upside_pct=result.upside_pct,
        )
