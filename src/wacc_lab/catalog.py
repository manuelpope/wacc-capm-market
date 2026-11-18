"""Curated catalog of well-known Yahoo Finance tickers.

The catalog is the default universe of the picker. Any other Yahoo Finance
ticker can still be loaded by typing its symbol in the free-text field.
"""

from __future__ import annotations

from .models import TickerInfo

CATALOG: tuple[TickerInfo, ...] = (
    TickerInfo(ticker="AAPL", name="Apple Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="MSFT", name="Microsoft Corporation", sector="Technology", country="United States"),
    TickerInfo(ticker="NVDA", name="NVIDIA Corporation", sector="Technology", country="United States"),
    TickerInfo(ticker="AMZN", name="Amazon.com, Inc.", sector="Consumer Cyclical", country="United States"),
    TickerInfo(ticker="GOOGL", name="Alphabet Inc.", sector="Communication Services", country="United States"),
    TickerInfo(ticker="META", name="Meta Platforms, Inc.", sector="Communication Services", country="United States"),
    TickerInfo(ticker="TSLA", name="Tesla, Inc.", sector="Consumer Cyclical", country="United States"),
    TickerInfo(ticker="AVGO", name="Broadcom Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="AMD", name="Advanced Micro Devices, Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="INTC", name="Intel Corporation", sector="Technology", country="United States"),
    TickerInfo(ticker="CSCO", name="Cisco Systems, Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="ORCL", name="Oracle Corporation", sector="Technology", country="United States"),
    TickerInfo(ticker="CRM", name="Salesforce, Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="ADBE", name="Adobe Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="IBM", name="International Business Machines Corporation", sector="Technology", country="United States"),
    TickerInfo(ticker="QCOM", name="QUALCOMM Incorporated", sector="Technology", country="United States"),
    TickerInfo(ticker="TXN", name="Texas Instruments Incorporated", sector="Technology", country="United States"),
    TickerInfo(ticker="ACN", name="Accenture plc", sector="Technology", country="United States"),
    TickerInfo(ticker="PLTR", name="Palantir Technologies Inc.", sector="Technology", country="United States"),
    TickerInfo(ticker="BRK-B", name="Berkshire Hathaway Inc.", sector="Financials", country="United States"),
    TickerInfo(ticker="JPM", name="JPMorgan Chase & Co.", sector="Financials", country="United States"),
    TickerInfo(ticker="V", name="Visa Inc.", sector="Financials", country="United States"),
    TickerInfo(ticker="MA", name="Mastercard Incorporated", sector="Financials", country="United States"),
    TickerInfo(ticker="BAC", name="Bank of America Corporation", sector="Financials", country="United States"),
    TickerInfo(ticker="GS", name="Goldman Sachs Group, Inc.", sector="Financials", country="United States"),
    TickerInfo(ticker="MS", name="Morgan Stanley", sector="Financials", country="United States"),
    TickerInfo(ticker="SPGI", name="S&P Global Inc.", sector="Financials", country="United States"),
    TickerInfo(ticker="NFLX", name="Netflix, Inc.", sector="Communication Services", country="United States"),
    TickerInfo(ticker="DIS", name="The Walt Disney Company", sector="Communication Services", country="United States"),
    TickerInfo(ticker="CMCSA", name="Comcast Corporation", sector="Communication Services", country="United States"),
    TickerInfo(ticker="T", name="AT&T Inc.", sector="Communication Services", country="United States"),
    TickerInfo(ticker="VZ", name="Verizon Communications Inc.", sector="Communication Services", country="United States"),
    TickerInfo(ticker="LLY", name="Eli Lilly and Company", sector="Healthcare", country="United States"),
    TickerInfo(ticker="UNH", name="UnitedHealth Group Incorporated", sector="Healthcare", country="United States"),
    TickerInfo(ticker="JNJ", name="Johnson & Johnson", sector="Healthcare", country="United States"),
    TickerInfo(ticker="MRK", name="Merck & Co., Inc.", sector="Healthcare", country="United States"),
    TickerInfo(ticker="ABT", name="Abbott Laboratories", sector="Healthcare", country="United States"),
    TickerInfo(ticker="TMO", name="Thermo Fisher Scientific Inc.", sector="Healthcare", country="United States"),
    TickerInfo(ticker="COST", name="Costco Wholesale Corporation", sector="Consumer Defensive", country="United States"),
    TickerInfo(ticker="WMT", name="Walmart Inc.", sector="Consumer Defensive", country="United States"),
    TickerInfo(ticker="PG", name="The Procter & Gamble Company", sector="Consumer Defensive", country="United States"),
    TickerInfo(ticker="KO", name="The Coca-Cola Company", sector="Consumer Defensive", country="United States"),
    TickerInfo(ticker="PEP", name="PepsiCo, Inc.", sector="Consumer Defensive", country="United States"),
    TickerInfo(ticker="MCD", name="McDonald's Corporation", sector="Consumer Cyclical", country="United States"),
    TickerInfo(ticker="HD", name="The Home Depot, Inc.", sector="Consumer Cyclical", country="United States"),
    TickerInfo(ticker="NKE", name="NIKE, Inc.", sector="Consumer Cyclical", country="United States"),
    TickerInfo(ticker="XOM", name="Exxon Mobil Corporation", sector="Energy", country="United States"),
    TickerInfo(ticker="CVX", name="Chevron Corporation", sector="Energy", country="United States"),
    TickerInfo(ticker="COP", name="ConocoPhillips", sector="Energy", country="United States"),
    TickerInfo(ticker="SLB", name="SLB", sector="Energy", country="United States"),
    TickerInfo(ticker="CAT", name="Caterpillar Inc.", sector="Industrials", country="United States"),
    TickerInfo(ticker="BA", name="The Boeing Company", sector="Industrials", country="United States"),
    TickerInfo(ticker="GE", name="GE Aerospace", sector="Industrials", country="United States"),
    TickerInfo(ticker="HON", name="Honeywell International Inc.", sector="Industrials", country="United States"),
    TickerInfo(ticker="RTX", name="RTX Corporation", sector="Industrials", country="United States"),
    TickerInfo(ticker="LMT", name="Lockheed Martin Corporation", sector="Industrials", country="United States"),
    TickerInfo(ticker="NEE", name="NextEra Energy, Inc.", sector="Utilities", country="United States"),
    TickerInfo(ticker="SHEL", name="Shell plc", sector="Energy", country="United Kingdom"),
    TickerInfo(ticker="BP", name="BP p.l.c.", sector="Energy", country="United Kingdom"),
    TickerInfo(ticker="AZN", name="AstraZeneca PLC", sector="Healthcare", country="United Kingdom"),
    TickerInfo(ticker="ULVR", name="Unilever PLC", sector="Consumer Defensive", country="United Kingdom"),
    TickerInfo(ticker="SAP", name="SAP SE", sector="Technology", country="Germany"),
    TickerInfo(ticker="TM", name="Toyota Motor Corporation", sector="Consumer Cyclical", country="Japan"),
    TickerInfo(ticker="NVO", name="Novo Nordisk A/S", sector="Healthcare", country="Denmark"),
    TickerInfo(ticker="ASML", name="ASML Holding N.V.", sector="Technology", country="Netherlands"),
    TickerInfo(ticker="SAN", name="Banco Santander, S.A.", sector="Financials", country="Spain"),
    TickerInfo(ticker="BABA", name="Alibaba Group Holding Limited", sector="Consumer Cyclical", country="China"),
    TickerInfo(ticker="005930.KS", name="Samsung Electronics Co., Ltd.", sector="Technology", country="South Korea"),
    TickerInfo(ticker="TTE", name="TotalEnergies SE", sector="Energy", country="France"),
)

BY_TICKER: dict[str, TickerInfo] = {item.ticker: item for item in CATALOG}


def list_catalog() -> list[TickerInfo]:
    return list(CATALOG)
