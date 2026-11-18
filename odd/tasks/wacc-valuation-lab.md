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

S7. "cuando no este disponible calcular los valores por alguna razon , usar un extractor analista con llm"
    Scope: A local LLM fills the five inputs Yahoo Finance could not compute (pre-tax cost of debt, effective tax rate, ROE, retention ratio, free cash flow margin). It never overwrites a Yahoo value, it never estimates a scale, and an unknown ticker is never handed to the model. Every value it writes is labelled `llm` in `field_sources`, carries a warning and shows an LLM badge in the interface.
    Acceptance: `?use_llm=false` returns the exact Yahoo values; `?use_llm=true` fills only the gaps; a model failure leaves the company untouched.
    Checks: `uv run pytest tests/test_llm.py tests/test_api.py -k analyst`

S11. "sigue intentando"
    Scope: A second review pass over the parts of the code the first one did not cover: the interface script, the edge cases of the engines, the concurrency of the store, and the inputs the user can actually type.
    Acceptance: The known defects of the second pass are fixed and pinned with a test, and the inputs that come from the user or from the network are covered.
    Checks: `uv run pytest -q`

S10. "arregla el punto de fcf normalizado y luego revisa el codigo para no tener bugs"
    Scope: The valuation base becomes the average of the last three fiscal years instead of the trailing twelve months, with both figures shown and a warning when they differ by more than 25%. Then a review pass over the whole code base.
    Acceptance: The base cash flow is the three year average, the trailing figure stays visible, and the review leaves no known defect behind.
    Checks: `uv run pytest -q`

S9. "dale me parece interesante el siguiente paso"
    Scope: The next step proposed at the end of the previous increment: a WACC x g sensitivity grid, so the interface answers how much of the valuation depends on the two assumptions that carry the most weight, instead of showing a single number.
    Acceptance: The grid is centred on the base case, the base cell matches the valuation shown above it, a cell where g is not below the WACC reports no number, and a cell where the spread is under 3% is flagged as fragile.
    Checks: `uv run pytest tests/test_sensitivity.py tests/test_api.py -k sensitivity`

S8. "las unidades deben ser mas legibles cuando son modena , ademas , me gustaria una seccion de noticias reelvantes q se usan para cuando se usa el llm"
    Scope: Every monetary value in the interface is shown with the currency of the ticker, in compact notation (`$136.06B`, `$179.43`), never as a raw number. A "Recent news" section shows the headlines, and those headlines are the context the analyst model reads before estimating.
    Acceptance: The valuation card, the inputs table and the summary show the currency; the news section lists the stories with publisher and date; the prompt contains the headlines; the model is asked to take them into account and to say when a headline drove the estimate.
    Checks: `uv run pytest tests/test_news.py`

S6. "empezamos desde lo simple a lo complejo siempre"
    Scope: v1 ships the whole flow end-to-end (pick → compute → persist → value). Complexity is added by editing existing units, not by replacing them.
    Acceptance: README documents how to run, the methodology, and a "What it cannot do" section.
    Checks: manual readback

## Tasks

T1 | S2, S3 | inline | done | f260f57 — engines + unit tests (14 tests, RED observed first)
T2 | S1, S4 | inline | done | f254be6 — SQLite store, catalog (69 tickers), provider, API
T3 | S2, S3, S4 | inline | done | ab1e795 — growth ceiling + minimum WACC-g spread, TV share
T4 | S5 | inline | done | f254be6 + ab1e795 — single-page interface, verified in the browser
T5 | S6 | inline | done | README.md — run instructions, methodology, "What it cannot do" (19 limits)
T6 | S7 | inline | done | analyst extractor: OpenAI-compatible client, range validation, provenance, toggle
T7 | S8 | inline | done | news provider + relevance ranking, prompt context, currency formatting, news card
T8 | S9 | inline | done | sensitivity engine, endpoint, grid card with the colour scale and the fragile marks
T9 | S10 | inline | done | normalization engine, provider series, valuation base, UI rows, bug review
T10 | S11 | inline | done | second review: interface script, engine edge cases, store concurrency, hostile inputs

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

L10 (2026-11-18): Analyst fallback implemented on top of the existing provider. Design decisions, all pinned by tests:
- the model may fill only what the provider marked as a fallback or as unavailable: `pretax_cost_of_debt`, `tax_rate`, `roe`, `retention_ratio` and the free cash flow *margin*. The cash flow itself is the margin multiplied by the trailing revenue Yahoo reported, so the model never invents a scale;
- the provider now records the provenance of every field (`field_sources`), which is what decides whether a field is a gap;
- a value has to land inside a plausible band for its field; a whole percentage (`21`) is normalized to a fraction (`0.21`) when the fraction is plausible, otherwise the answer is discarded and reported;
- the estimates live in their own table next to the snapshot, so a second request costs nothing and `use_llm=false` ignores them completely;
- a ticker Yahoo does not know is never given to the model, and a Yahoo outage is an error, not an invitation to invent a company.

L11 (2026-11-18): The user corrected the model choice: `qwen3.5:9b-mlx` was already installed locally, and no model should be downloaded. The `qwen3:8b` pull (5.2 GB) that was started in the background was removed with `ollama rm`, and the default is now `qwen3.5:9b-mlx`.

L12 (2026-11-18): Latency finding that made the feature usable. A qwen3.5 request took about four minutes with the model defaults (thinking on, a 262k context). With `reasoning_effort: none` and `options: {num_ctx: 8192, num_predict: 600}` the same extraction takes under one second, so the client sends those parameters and falls back to plainer payloads when a server rejects them. A full analysis with a cold model is now under ten seconds and a cached one is under thirty milliseconds.

L13 (2026-11-18): Oracle exposed a modelling defect while verifying in the browser: its trailing free cash flow is negative (-28.7B), and the model reported a value per share of -210, which is arithmetic rather than valuation. The valuation engine no longer reports a value per share when the base cash flow is not positive, and says why.

L14 (2026-11-18): News section and the analyst context. The Yahoo news feed of a ticker is cached in its own table with a 6 hour TTL, ranked by whether the story names the ticker or the company, and the irrelevant ones are dropped when at least three relevant ones remain. Yahoo mixes market-wide stories into a ticker feed, so without the filter the context for the model was full of noise ("Planes, banks and the NSA all went down in one week"). The headlines, the publisher, the date and a truncated summary go into the prompt, and the model is asked to use them and to name the headline that drove the estimate. In the live run it answered: "recent outage news does not materially alter the cost of existing debt". A news failure never takes the valuation down.

L15 (2026-11-18): The units are now readable: the currency of the ticker is carried through the whole response and the interface shows `$136.06B`, `$3.36T`, `$179.43` instead of `127006000000`. Three bugs were found and fixed on the way, all of them in the new code: the news never reached the builder (the service built the analysis before the news were loaded), the legacy flat news shape read `publisher` instead of `provider`, the relevance ranking had its sign inverted (the least relevant stories came first), and the company name was compared in lower case against an upper case haystack.

L16 (2026-11-18): Sensitivity grid. The axes are the base WACC and the base g plus or minus 2 percentage points in steps of 0.5, which is nine by nine cells. Two kinds of cell are not numbers: a cell where g is not below the WACC has no terminal value and reports `n/a`, and a cell where the spread is under 3% is reported but marked as fragile, because the terminal value dominates it. The grid does not apply the growth ceiling of the base case, because exploring assumptions above the ceiling is the point of a grid; it applies only the mathematical rule. For Apple the grid runs from $100.65 to $698.88 around a base case of $179.43, and the two most optimistic corners are exactly the fragile ones, which is the finding the grid exists to deliver.

L17 (2026-11-18): The grid is what makes the earlier corrections legible. The 5% ceiling and the 3% minimum spread are not visible as numbers in the base case, but the grid shows that the whole optimistic corner of the table lives inside the fragile zone, so a bull case built on a narrow spread is arithmetically large and economically weak.

L18 (2026-11-18): Normalized free cash flow. The base is now the average of the last three fiscal years of the `Free Cash Flow` line of the annual statement, instead of the trailing twelve months. Both are kept: the trailing figure stays visible in the interface, and when the two differ by more than 25% the tool says which way and by how much. The effect is not cosmetic: Apple's base drops from $136.06B to $114.54B and the value per share from $179.43 to $151.53, and Exxon's base drops from $42.96B to $29.26B.

L19 (2026-11-18): Review pass. Ten defects found and fixed, each one pinned with a test:
1. `with sqlite3.connect(...)` does not close the connection, only the transaction: fifteen connections leaked per store call. A session manager now commits and closes.
2. Importing the module created the database file, because the module level app was built at import time and the store created its schema in the constructor. The schema is now created on the first use.
3. A snapshot written by an older version was read as if it were current, and the analysis ran with missing fields. Snapshots carry a schema version and the outdated ones are fetched again.
4. The warning about the normalized cash flow said the opposite of what it meant: it reported the normalized base as "32% above" the trailing figure when it was 32% below.
5. The analyst could replace a computed normalized cash flow with its own estimate when only the trailing figure was missing. It no longer overwrites a base that Yahoo computed.
6. A short ticker matched every headline: "T" (AT&T) appeared in every story. Short symbols now have to appear as a word of their own.
7. The grid hid its own warnings when it had cells, so a company with a negative cash flow showed an empty grid with no explanation.
8. The health endpoint reported the environment configuration instead of the service that was running.
9. The inputs table looked for a provenance key that did not exist, so a cash flow estimated by the model never got its LLM badge.
10. The grid stayed stale after saving or resetting an override, and the provider downloaded the annual cash flow statement twice.

L20 (2026-11-18): The same kind of mistake appeared in the tooling itself twice: two patches did not apply because the anchor text had changed, and both were caught only by running the code afterwards. Every patch in this increment is verified against the real behaviour, not against the diff.

L21 (2026-11-18): Second review pass, on the parts the first one did not cover. Ten more defects fixed:
1. Two XSS holes in the interface: the error message and the grid warning were injected as raw HTML. Both are text now.
2. The "automatic" value of the growth override showed the raw growth (106% for Apple) instead of the growth the model used (5%).
3. A race in the interface: two requests could arrive out of order and the older answer overwrote the newer one.
4. An override typed with a comma decimal was ignored without a word. The interface now says which fields it could not read.
5. Amounts under a thousand were rounded to zero.
6. The axes of the grid were rounded to six decimals, so the base cell was not exactly the valuation shown above it. The rounding is gone.
7. "database is locked" under concurrent requests: the journal mode pragma was executed on every connection and needs an exclusive lock that the busy timeout does not wait for. It is set once, when the schema is created.
8. A trailing figure made of fewer than four quarters was presented as a year. The provider now counts the quarters and says so.
9. The share of the terminal value was computed over a negative enterprise value, where the ratio means nothing.
10. The `analyses` table was written on every request and never read: the snapshot is the cache. The table is gone.

L22 (2026-11-18): One suspicion turned out not to be a defect. Samsung's trailing cash flow looked four times its annual figure, which is the signature of cumulative quarters. The quarterly statements were checked against the annual ones for four companies: the quarters are discrete (Apple's four quarters sum to 478.9 against an annual 478.8), so the trailing figure was right. The gap is real: Samsung's 2026 is a cycle extreme and the three year average includes a negative 2023. The tool says so, and now the warning names the cycle when the difference is extreme.

L23 (2026-11-18): The second pass added the kind of tests that were missing: property tests over the engines with seeded random inputs (the invariants hold for every input: the growth never reaches the discount rate, the value falls when the discount rate rises and rises when growth rises, nothing is ever a NaN, the base cell of the grid is the valuation), hostile inputs against the API (a SQL injection attempt, an empty ticker, a lowercase ticker, eight parallel requests, and parallel reads and writes), and a test for the store that proves the database file is not touched at import.
