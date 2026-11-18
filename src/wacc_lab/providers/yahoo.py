"""Yahoo Finance provider.

Everything the engines need is extracted from a single `yfinance` pull:
the quote info plus the quarterly income, balance and cash-flow statements.

Two data traps are handled explicitly:

* `info["returnOnEquity"]` is inflated for companies that buy back stock, so
  ROE is recomputed here from trailing net income over average book equity.
* `^TNX` is quoted in percent, but legacy Yahoo quoting multiplied it by ten.
  The value is normalized defensively.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from ..models import Fundamentals
from .base import ProviderError, TickerNotFoundError

RISK_FREE_TICKER = "^TNX"
MARKET_TICKER = "^GSPC"

DEFAULT_RISK_FREE_RATE = 0.04
DEFAULT_TAX_RATE = 0.21
COST_OF_DEBT_SPREAD = 0.015
DEFAULT_BETA = 1.0

INCOME_ROWS = {
    "net_income": (
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income Including Noncontrolling Interests",
    ),
    "pretax_income": ("Pretax Income",),
    "tax_provision": ("Tax Provision",),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "revenue": ("Total Revenue", "Operating Revenue"),
    "diluted_shares": ("Diluted Average Shares", "Basic Average Shares"),
}

CASHFLOW_ROWS = {
    "free_cash_flow": ("Free Cash Flow",),
    "operating_cash_flow": (
        "Operating Cash Flow",
        "Total Cash From Operating Activities",
    ),
    "capex": ("Capital Expenditure",),
    "dividends": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
}

BALANCE_ROWS = {
    "total_debt": ("Total Debt",),
    "equity": (
        "Stockholders Equity",
        "Common Stock Equity",
        "Total Equity Gross Minority Interest",
    ),
    "cash": (
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents",
    ),
}


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _row_series(df: pd.DataFrame | None, names: tuple[str, ...]) -> pd.Series | None:
    if df is None or getattr(df, "empty", True):
        return None
    index = {str(label).strip().lower(): label for label in df.index}
    for name in names:
        label = index.get(name.strip().lower())
        if label is None:
            continue
        row = df.loc[label]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return row
    return None


def _value(series: pd.Series | None, position: int = 0) -> float | None:
    if series is None:
        return None
    try:
        return _to_float(series.iloc[position])
    except Exception:
        return None


def _recent_sum(series: pd.Series | None, periods: int = 4) -> float | None:
    if series is None:
        return None
    values: list[float] = []
    try:
        chunk = series.iloc[:periods]
    except Exception:
        return None
    for raw in chunk:
        number = _to_float(raw)
        if number is not None:
            values.append(number)
    if len(values) < 2:
        return None
    return sum(values)


class YahooProvider:
    """Fetches fundamentals for a ticker from Yahoo Finance."""

    provider_name = "yahoo"

    def fetch(self, ticker: str) -> Fundamentals:
        symbol = ticker.strip().upper()
        if not symbol:
            raise TickerNotFoundError("no ticker was provided")

        warnings: list[str] = []
        handle = yf.Ticker(symbol)
        try:
            info = handle.info or {}
        except Exception as exc:  # network / parsing problems
            raise ProviderError(f"Yahoo Finance request failed for {symbol}: {exc}") from exc

        if not info or not (
            info.get("symbol") or info.get("shortName") or info.get("quoteType")
        ):
            if not self._has_price_history(handle):
                raise TickerNotFoundError(
                    f"{symbol} is not a known Yahoo Finance ticker"
                )
            raise ProviderError(
                f"Yahoo Finance returned no profile data for {symbol}"
            )

        try:
            q_income = handle.quarterly_income_stmt
            q_balance = handle.quarterly_balance_sheet
            q_cashflow = handle.quarterly_cashflow
            a_income = handle.income_stmt
            a_balance = handle.balance_sheet
        except Exception as exc:
            raise ProviderError(
                f"Yahoo Finance statement download failed for {symbol}: {exc}"
            ) from exc

        price = _to_float(info.get("currentPrice")) or _to_float(
            info.get("regularMarketPrice")
        )
        shares = _to_float(info.get("sharesOutstanding")) or _value(
            _row_series(q_income, INCOME_ROWS["diluted_shares"])
        )
        market_cap = _to_float(info.get("marketCap"))
        if market_cap is None and price is not None and shares is not None:
            market_cap = price * shares

        total_debt = _value(_row_series(q_balance, BALANCE_ROWS["total_debt"]))
        if total_debt is None:
            total_debt = _value(_row_series(a_balance, BALANCE_ROWS["total_debt"]))
        cash = _value(_row_series(q_balance, BALANCE_ROWS["cash"]))
        if cash is None:
            cash = _value(_row_series(a_balance, BALANCE_ROWS["cash"]))

        equity_series = _row_series(q_balance, BALANCE_ROWS["equity"])
        equity_latest = _value(equity_series, 0)
        equity_previous = _value(equity_series, 1)
        if equity_latest is None:
            equity_series = _row_series(a_balance, BALANCE_ROWS["equity"])
            equity_latest = _value(equity_series, 0)
            equity_previous = None

        net_income_ttm = _recent_sum(_row_series(q_income, INCOME_ROWS["net_income"]))
        pretax_ttm = _recent_sum(_row_series(q_income, INCOME_ROWS["pretax_income"]))
        tax_ttm = _recent_sum(_row_series(q_income, INCOME_ROWS["tax_provision"]))
        revenue_ttm = _recent_sum(_row_series(q_income, INCOME_ROWS["revenue"]))
        interest_ttm = _recent_sum(
            _row_series(q_income, INCOME_ROWS["interest_expense"])
        )
        if interest_ttm is None:
            # Annual statements hold years, not quarters: take the last fiscal year.
            interest_ttm = _value(
                _row_series(a_income, INCOME_ROWS["interest_expense"]), 0
            )

        fcf_ttm = _recent_sum(_row_series(q_cashflow, CASHFLOW_ROWS["free_cash_flow"]))
        if fcf_ttm is None:
            operating_cf = _recent_sum(
                _row_series(q_cashflow, CASHFLOW_ROWS["operating_cash_flow"])
            )
            capex = _recent_sum(_row_series(q_cashflow, CASHFLOW_ROWS["capex"]))
            if operating_cf is not None and capex is not None:
                fcf_ttm = operating_cf + capex

        dividends_series = _row_series(q_cashflow, CASHFLOW_ROWS["dividends"])
        dividends_ttm = _recent_sum(dividends_series)

        risk_free_rate, rf_warning = self._risk_free_rate()
        if rf_warning:
            warnings.append(rf_warning)

        beta, beta_source = self._beta(symbol, info, risk_free_rate)
        if beta_source == "default":
            warnings.append(
                "beta is unavailable for this ticker, 1.0 was used as a neutral assumption"
            )

        tax_rate = self._tax_rate(tax_ttm, pretax_ttm, info, warnings)
        pretax_cost_of_debt = self._cost_of_debt(
            interest_ttm, total_debt, risk_free_rate, warnings
        )
        roe = self._roe(net_income_ttm, equity_latest, equity_previous)

        retention = self._retention(dividends_ttm, net_income_ttm)
        if retention is None:
            # Some companies ( Berkshire Hathaway ) report no quarterly dividend row.
            retention, annual_note = self._annual_retention(handle, warnings)
            if annual_note:
                warnings.append(annual_note)

        net_debt = (total_debt or 0.0) - (cash or 0.0)

        return Fundamentals(
            ticker=symbol,
            name=str(info.get("shortName") or info.get("longName") or symbol),
            sector=info.get("sector"),
            currency=info.get("currency"),
            provider=self.provider_name,
            price=price,
            market_cap=market_cap,
            shares_outstanding=shares,
            total_debt=total_debt,
            cash=cash,
            net_debt=net_debt,
            equity_book=equity_latest,
            risk_free_rate=risk_free_rate,
            beta=beta,
            beta_source=beta_source,
            pretax_cost_of_debt=pretax_cost_of_debt,
            tax_rate=tax_rate,
            roe=roe,
            retention_ratio=retention,
            fcf_ttm=fcf_ttm,
            net_income_ttm=net_income_ttm,
            revenue_ttm=revenue_ttm,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            warnings=warnings,
        )

    # ------------------------------------------------------------------ parts
    @staticmethod
    def _has_price_history(handle: "yf.Ticker") -> bool:
        try:
            history = handle.history(period="5d")
        except Exception:
            return False
        return history is not None and not history.empty

    @staticmethod
    def _risk_free_rate() -> tuple[float | None, str | None]:
        try:
            history = yf.Ticker(RISK_FREE_TICKER).history(period="5d")
            close = history["Close"].dropna()
        except Exception:
            return None, "the 10-year Treasury yield could not be read, 4.0% was used"
        if close.empty:
            return None, "the 10-year Treasury yield could not be read, 4.0% was used"
        raw = float(close.iloc[-1])
        if raw > 20:  # legacy quoting: 51.0 means 5.10%
            raw = raw / 10.0
        rate = raw / 100.0
        if not 0.0 < rate < 0.25:
            return (
                None,
                "the 10-year Treasury yield is out of range, 4.0% was used",
            )
        return rate, None

    @staticmethod
    def _beta(
        symbol: str, info: dict, risk_free_rate: float | None
    ) -> tuple[float, str]:
        reported = _to_float(info.get("beta"))
        if reported is not None and reported > 0:
            return reported, "yahoo"
        try:
            frame = yf.download(
                [symbol, MARKET_TICKER],
                period="5y",
                interval="1mo",
                progress=False,
                auto_adjust=True,
            )
        except Exception:
            return DEFAULT_BETA, "default"
        if frame is None or frame.empty:
            return DEFAULT_BETA, "default"
        try:
            closes = frame["Close"].dropna()
            returns = closes.pct_change().dropna()
            market = returns.iloc[:, 1]
            variance = float(market.var())
            if variance <= 0:
                return DEFAULT_BETA, "default"
            beta = float(returns.iloc[:, 0].cov(market) / variance)
        except Exception:
            return DEFAULT_BETA, "default"
        if not math.isfinite(beta) or beta <= 0:
            return DEFAULT_BETA, "default"
        return beta, "computed_vs_^GSPC"

    @staticmethod
    def _tax_rate(
        tax_ttm: float | None,
        pretax_ttm: float | None,
        info: dict,
        warnings: list[str],
    ) -> float:
        if pretax_ttm and pretax_ttm > 0 and tax_ttm is not None:
            rate = tax_ttm / pretax_ttm
            if 0.0 <= rate <= 1.0:
                return rate
        reported = _to_float(info.get("taxRate"))
        if reported is not None and 0.0 <= reported <= 1.0:
            return reported
        warnings.append(
            "the effective tax rate could not be read, 21.0% was used as a default"
        )
        return DEFAULT_TAX_RATE

    @staticmethod
    def _cost_of_debt(
        interest_ttm: float | None,
        total_debt: float | None,
        risk_free_rate: float | None,
        warnings: list[str],
    ) -> float:
        if interest_ttm and total_debt and total_debt > 0 and interest_ttm > 0:
            return interest_ttm / total_debt
        base = risk_free_rate if risk_free_rate is not None else DEFAULT_RISK_FREE_RATE
        warnings.append(
            "interest expense is unavailable, the cost of debt was estimated as the "
            "risk-free rate plus 1.5%"
        )
        return base + COST_OF_DEBT_SPREAD

    @staticmethod
    def _roe(
        net_income_ttm: float | None,
        equity_latest: float | None,
        equity_previous: float | None,
    ) -> float | None:
        if net_income_ttm is None or equity_latest is None:
            return None
        if equity_previous is None:
            average = equity_latest
        else:
            average = (equity_latest + equity_previous) / 2.0
        if average <= 0:
            return None
        return net_income_ttm / average

    @staticmethod
    def _retention(
        dividends_ttm: float | None, net_income_ttm: float | None
    ) -> float | None:
        if dividends_ttm is None or net_income_ttm is None or net_income_ttm <= 0:
            return None
        dividends = abs(dividends_ttm)
        retention = 1.0 - dividends / net_income_ttm
        return min(max(retention, 0.0), 1.0)

    @staticmethod
    def _annual_retention(
        handle: "yf.Ticker", warnings: list[str]
    ) -> tuple[float | None, str | None]:
        """Fallback for tickers without a quarterly dividend row.

        Uses the last fiscal year for both dividends and net income, so the
        payout ratio stays internally consistent even if the period differs
        from the TTM used elsewhere.
        """
        try:
            annual_cashflow = handle.cashflow
            annual_income = handle.income_stmt
        except Exception:
            return None, "dividend data is unavailable, g cannot be derived from the retention ratio"

        dividends = _value(_row_series(annual_cashflow, CASHFLOW_ROWS["dividends"]), 0)
        net_income = _value(_row_series(annual_income, INCOME_ROWS["net_income"]), 0)
        if net_income is None or net_income <= 0:
            return None, "dividend data is unavailable, g cannot be derived from the retention ratio"
        if dividends is None:
            # No dividend line at all: the company does not report dividends, so
            # assume it pays none and the whole profit is retained.
            warnings.append(
                "no dividend line is reported, the retention ratio was set to 1.0 assuming no dividends are paid"
            )
            return 1.0, None

        retention = min(max(1.0 - abs(dividends) / net_income, 0.0), 1.0)
        warnings.append(
            "the retention ratio uses the last fiscal year because quarterly dividends are not reported"
        )
        return retention, None
