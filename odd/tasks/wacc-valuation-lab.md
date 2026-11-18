# WACC + g Valuation Lab

Objective: FastAPI + HTML tool that computes WACC and g for famous Yahoo Finance tickers, persists results in SQLite, and recomputes when missing or stale.
Branch: feature/wacc-valuation-lab | Delivery: ask-on-risk | Test runner: `uv run pytest`

## Specs

S1. "una herramienta de html con fastapi por la cual pueda elegir de los tickers de yahoo finance mas famosos"
    Scope: Curated catalog of ~45 well-known Yahoo Finance tickers (name, sector, country) served by `GET /api/tickers`, plus a free-text ticker field in the UI so any Yahoo ticker can be loaded.
    Acceptance: The UI shows a picker of curated tickers; a free-text ticker that Yahoo does not know returns a clear error, not a crash.
    Checks: `uv run pytest tests/test_api.py -k ticker`

S2. "el calculo de su wacc y su g"
    Scope: WACC = we·Ke + wd·Kd·(1−t) with Ke = Rf + β·ERP. g = ROE × retention ratio by default. Every input is overridable by hand and recomputed on demand.
    Acceptance: Both engines are pure functions with unit tests; the WACC decomposition (Ke, after-tax Kd, weights, WACC) and the g derivation (raw, cap, reason) are returned to the UI.
    Checks: `uv run pytest tests/test_engines.py`

S3. "para la posterior valuacion"
    Scope: A simple FCFF-style DCF (5-year constant-growth projection, Gordon terminal value) that consumes the computed WACC and g, returning EV, equity value, value per share and upside vs. the current price.
    Acceptance: A company with negative FCF or g >= WACC is reported with a warning instead of a silently wrong number.
    Checks: `uv run pytest tests/test_engines.py`

S4. "usa sqlite para persistir , si no esta recalcula"
    Scope: SQLite storage of raw provider snapshots, computed analyses and manual overrides. A request for a ticker that is not stored computes it; a stored-but-stale ticker (TTL, default 24h) is recomputed; `refresh=true` forces recomputation.
    Acceptance: Two consecutive requests for the same ticker hit the provider once; the second response is flagged as served from cache.
    Checks: `uv run pytest tests/test_api.py`

S5. "esta api tiene una interfaz"
    Scope: Single-page HTML/CSS/JS interface served by FastAPI: ticker picker, input panel with overrides, WACC card, g card, valuation card, warnings area, refresh and reset actions.
    Acceptance: The page loads without a build step and performs the full flow from the browser.
    Checks: `uv run pytest tests/test_api.py -k static` + manual browser check

S6. "empezamos desde lo simple a lo complejo siempre"
    Scope: v1 ships the whole flow end-to-end (pick → compute → persist → value). Complexity is added by editing existing units, not by replacing them.
    Acceptance: README documents how to run, the methodology, and a "What it cannot do" section.
    Checks: manual readback

## Tasks

T1 | S2, S3 | inline | pending | -
T2 | S1, S4 | inline | pending | -
T3 | S2, S3, S4 | inline | pending | -
T4 | S5 | inline | pending | -
T5 | S6 | inline | pending | -

## Log

L1 (2026-11-18): "/odd me gustaria tener una herramienta de html con fastapi por la cual pueda elegir de los tickers de yahoo finance mas famosos el calculo de su wacc y su g  para la posterior valuacion , es decir esta api tiene una interfaz y usa sqlite para persistir , si no esta recalcula , empezamos desde lo simple a lo complejo siempre"

L2 (2026-11-18): User decisions collected via questionnaire:
- g method: ROE × retention (sustainable internal growth) + manual override.
- WACC inputs: auto from Yahoo Finance + editable manual overrides.
- Ticker universe: curated catalog (~40) + free-text search.
- UI language: English.

L3 (2026-11-18): Environment probe. Yahoo Finance is reachable through `yfinance` 1.8.0 (info + quarterly statements + `^TNX` = 5.103). Raw `curl` to query1 returns HTTP 429, so every fetch must go through the library. Python 3.13.3, `uv` available, no global `yfinance` → project uses its own `.venv`.

L4 (2026-11-18): Observed data traps, to be handled explicitly:
- `info['returnOnEquity']` = 1.42 for AAPL (buyback-inflated). ROE is recomputed from quarterly net income over average book equity instead, and g is capped.
- `g` must stay strictly below WACC. Raw `ROE × retention` for AAPL-like ROE yields absurd values, so the growth engine caps at a ceiling and then at `WACC − spread`, and reports the reason.
- `^TNX` is quoted in percent (5.103 → 5.103%). Legacy quoting (×10) is normalized defensively.

Route: direct inline. Understanding fitted one bounded read batch; the work units are sequential and interdependent (provider → cache → engines → API → UI), so no Writer trigger applies.
