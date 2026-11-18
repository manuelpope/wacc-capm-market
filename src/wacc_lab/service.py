"""Analysis service: orchestrates provider, cache, overrides and engines."""

from __future__ import annotations

import re
from typing import Any

from .db import Store
from .engine.growth import GrowthInputs, apply_growth_caps, compute_growth
from .engine.valuation import ValuationInputs, compute_valuation
from .engine.wacc import DEFAULT_EQUITY_RISK_PREMIUM, WaccInputs, compute_wacc
from .models import (
    AnalysisResult,
    CacheInfo,
    Fundamentals,
    GrowthBreakdown,
    Overrides,
    ValuationBreakdown,
    WaccBreakdown,
)
from .providers.analyst import AnalystEstimate, AnalystExtractor, missing_gaps
from .providers.base import FundamentalsProvider

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
    ) -> None:
        self.store = store
        self.provider = provider
        self.ttl_hours = ttl_hours
        self.analyst = analyst

    # ------------------------------------------------------------- public API
    def analyze(
        self, ticker: str, refresh: bool = False, use_llm: bool = True
    ) -> AnalysisResult:
        symbol = ticker.strip().upper()
        fundamentals, status = self._snapshot(symbol, refresh, use_llm)
        overrides = self.store.get_overrides(symbol)
        result = self._build(symbol, fundamentals, overrides, status)
        computed_at = self.store.save_analysis(symbol, result.model_dump(mode="json"))
        result.cache.computed_at = computed_at
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

    # -------------------------------------------------------------- internals
    def _snapshot(
        self, symbol: str, refresh: bool, use_llm: bool
    ) -> tuple[Fundamentals, str]:
        if refresh:
            fundamentals, status = self._fetch(symbol), "refreshed"
        else:
            fundamentals = self.store.get_snapshot(symbol)
            if fundamentals is None:
                fundamentals, status = self._fetch(symbol), "computed"
            elif not fundamentals.field_sources:
                # A snapshot written before the provenance was tracked cannot be
                # used: the analyst step would not know what Yahoo really computed.
                fundamentals, status = self._fetch(symbol), "stale"
            else:
                age = self.store.snapshot_age_hours(symbol)
                if age is not None and age > self.ttl_hours:
                    fundamentals, status = self._fetch(symbol), "stale"
                else:
                    status = "fresh"

        if use_llm and self.analyst is not None:
            fundamentals = self._analyst_step(symbol, fundamentals)
        return fundamentals, status

    def _analyst_step(self, symbol: str, fundamentals: Fundamentals) -> Fundamentals:
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
            estimate = self.analyst.estimate(symbol, fundamentals, gaps)
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
            "base_fcf": fundamentals.fcf_ttm,
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
        base_fcf = (
            overrides.base_fcf
            if overrides.base_fcf is not None
            else fundamentals.fcf_ttm
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
