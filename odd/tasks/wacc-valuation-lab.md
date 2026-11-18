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

T1 | S2, S3 | inline | done | f260f57 — engines + unit tests (14 tests, RED observed first)
T2 | S1, S4 | inline | done | f254be6 — SQLite store, catalog (69 tickers), provider, API
T3 | S2, S3, S4 | inline | done | ab1e795 — growth ceiling + minimum WACC-g spread, TV share
T4 | S5 | inline | done | f254be6 + ab1e795 — single-page interface, verified in the browser
T5 | S6 | inline | done | README.md — run instructions, methodology, "What it cannot do" (16 limits)

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

L5 (2026-11-18): Implementation complete on branch `feature/wacc-valuation-lab`. The suite is 30 tests, all green, and it never touches the network (the API tests inject a fake provider).

L6 (2026-11-18): Model correction forced by the real data. The first run priced Apple at $2,190 per share against a $351 quote: with a 10% growth ceiling and a 10.47% WACC the Gordon denominator was 0.47% and the terminal value was 234x FCF. Two policy changes followed, both with tests:
- the perpetual growth ceiling moved from 10% to 5% (a perpetual rate above long-run nominal GDP is not sustainable);
- the minimum WACC-g spread moved from 1.5% to 3%, and it now applies to the final g in every path, not only when g exceeded the WACC.
XOM showed why the second one matters: its beta is genuinely low (0.14 reported, 0.19 computed against the S&P), so the WACC is 5.62% and a 5% g left a 0.62% spread, which put 97% of the EV in the terminal value. After the fix its g is 2.62% and the terminal value share is 87%, with both facts reported as warnings.

L7 (2026-11-18): Data traps found and handled, each with a warning attached: Yahoo's `returnOnEquity` is buyback-inflated (Apple 142%), so ROE is recomputed from trailing net income over average book equity; `^TNX` is quoted in percent but has legacy x10 quoting; an unknown ticker returns `{'trailingPegRatio': None}` instead of an empty dict, so the identity check has to look at `symbol`/`shortName`; companies that pay no dividend (Berkshire Hathaway) have no dividend row at all, which is not the same as zero, and the annual fallback sets retention to 1.0 with an explicit warning.

L8 (2026-11-18): Browser verification of the whole flow on the live server: catalog loaded, NVDA analyzed from the SQLite cache, a manual g override of 2.5% applied and recomputed, then reset back to the automatic value. The reset button did not fire on the first click; the cause was a stale click coordinate after the re-render, not an application defect — the live DELETE endpoint answered 200 and the same click with a fresh ref issued the DELETE.

L9 (2026-11-18): Next step for the user: pick the next increment. The cheapest high-value one is the WACC x g sensitivity grid, because the current output is a single number plus warnings and the sensitivity of the answer to those two inputs is the actual finding.
