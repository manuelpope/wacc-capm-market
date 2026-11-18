# WACC Lab

FastAPI + HTML tool to compute **WACC**, **g** and a simple DCF for Yahoo Finance
tickers. Results are stored in SQLite and recomputed when they are missing or stale.

The flow is deliberately small: pick a ticker, get the numbers, override whatever
you disagree with, and read the valuation.

![stack](https://img.shields.io/badge/python-3.11%2B-blue) ![deps](https://img.shields.io/badge/deps-fastapi%20%7C%20yfinance%20%7C%20sqlite3-lightgrey)

---

## Quick start

```bash
cd projects/wacc-lab
uv venv --python 3.13
uv pip install -e ".[dev]"

PYTHONPATH=src .venv/bin/python -m uvicorn wacc_lab.api:app --reload
```

Open <http://127.0.0.1:8000>.

The analyst model is read from the environment; the defaults point at the
Ollama running on this machine:

```bash
export WACC_LAB_LLM_BASE_URL=http://127.0.0.1:11434/v1
export WACC_LAB_LLM_MODEL=qwen3.5:9b-mlx
```

Run the tests:

```bash
.venv/bin/python -m pytest -q
```

The test suite never touches the network: the API tests inject a fake provider.

---

## How it works

### 1. Where the inputs come from

Everything is pulled from Yahoo Finance through `yfinance` (quote profile plus the
quarterly income, balance and cash-flow statements).

| Input | Source | Notes |
|---|---|---|
| Risk-free rate | `^TNX` (10Y Treasury) | Quoted in percent, normalized defensively for the legacy ×10 quoting |
| Beta | `info["beta"]` | Falls back to a 5-year monthly beta against `^GSPC`, then to 1.0 |
| Cost of equity | CAPM | `Rf + β × ERP`, ERP = 5.00% by default |
| Cost of debt | Interest expense ÷ total debt | Falls back to `Rf + 1.5%` |
| Tax rate | Tax provision ÷ pre-tax income (TTM) | Falls back to `info["taxRate"]`, then 21% |
| Capital structure | Total debt vs. market cap | Debt weight = D / (D + E) |
| ROE | TTM net income ÷ average book equity | Recomputed, never taken from Yahoo (see below) |
| Retention ratio | 1 − (dividends ÷ net income) | Annual fallback when no quarterly dividend row exists |
| Free cash flow | Annual `Free Cash Flow` series and TTM | Falls back to operating cash flow + capex |

**ROE is recomputed on purpose.** Yahoo's `returnOnEquity` is inflated for
companies that buy back stock (Apple reports ~142%). ROE is therefore taken from
trailing net income over average book equity, which is closer to the textbook
definition — but it is still inflated for companies shrinking their equity.

### 2. The growth rate

`g = ROE × retention ratio` (sustainable internal growth) by default, then capped
twice:

- **at a 5% ceiling** — a perpetual growth rate above long-run nominal GDP is not
  sustainable;
- **so the WACC − g spread stays at least 3% wide** — a narrow spread makes the
  Gordon terminal value explode.

Every cap reports why it fired, in the `Growth` card and in the warnings list. A
manual growth rate skips the ceiling but still obeys the minimum spread.

### 3. The normalized free cash flow

The base cash flow is the **average of the last three fiscal years**, not the
last twelve months. The trailing number carries the noise of a single unusual
quarter (a tax payment, a working capital squeeze, a restructuring), and the
model then grows that base for five years.

Both figures are shown in the interface, and when they differ by more than 25%
the tool says so: for Exxon the normalized base is 32% below the trailing
twelve months, and for Apple it is 16% below, which moves the value per share
from $179 to $151.

### 4. The valuation

A deliberately simple FCFF-style DCF:

```
FCF_t      = FCF_0 × (1 + g)^t
PV explicit = Σ FCF_t / (1 + WACC)^t          for t = 1..5
TV          = FCF_5 × (1 + g) / (WACC − g)
EV          = PV explicit + TV / (1 + WACC)^5
Equity      = EV − net debt
Value/share = Equity / shares outstanding
```

The terminal value share of the EV is displayed on purpose: when it is above 85%
the result lives almost entirely on the perpetuity assumption, and the tool says so.

---

## The analyst fallback

When Yahoo Finance cannot supply a number, a local LLM is asked to estimate it.

**What it may touch.** Only five fields, and only when the provider marked them
as a fallback or as unavailable: the pre-tax cost of debt, the effective tax
rate, ROE, the retention ratio and the free cash flow margin. A value that
Yahoo computed is never overwritten.

**What it may not do.** It never estimates a scale: market cap, revenue, share
count and price always come from Yahoo. The free cash flow is a *margin* the
model provides, multiplied by the trailing revenue that Yahoo reported. A
ticker Yahoo does not know is never handed to the model.

**How the answer is validated.** Every value has to land inside a plausible band
for its field. A value that comes back as a whole percentage (`21`) is
normalized to a fraction (`0.21`) when the fraction is plausible; otherwise it
is discarded and reported. A field the model declines (`null`) stays missing. A
model that fails, times out or answers prose leaves the company exactly as it
was.

**How you know.** Every value the model writes is labelled `llm` in the
`field_sources` map, carries a warning, and shows an `LLM` badge in the inputs
table. The estimates are stored next to the snapshot, so a second request does
not pay for the model again, and the "Analyst model for missing data" switch
turns the whole step off.

```bash
export WACC_LAB_LLM_BASE_URL=http://127.0.0.1:11434/v1   # Ollama, llmlite, llama.cpp, OpenAI
export WACC_LAB_LLM_MODEL=qwen3.5:9b-mlx
export WACC_LAB_LLM_API_KEY=                               # only for hosted providers
export WACC_LAB_LLM_TIMEOUT=180
export WACC_LAB_LLM_MODE=chat                              # "completions" for llama.cpp servers
export WACC_LAB_LLM_ENABLED=1
```

The client speaks the OpenAI-compatible API, so the same code drives Ollama,
llmlite, llama.cpp and the OpenAI API. Servers built on llama.cpp return the
answer in `reasoning_content` instead of `content`; that field is used as a
fallback, and `WACC_LAB_LLM_MODE=completions` switches to the plain
`/v1/completions` endpoint for those builds.

---

## Sensitivity (WACC x g)

A single value per share hides the question that matters: **how much of this
number depends on the two assumptions that carry the most weight?** The grid
answers it by recomputing the valuation for combinations of WACC and g around
the base case.

- **Axes**: the WACC and the g of the base case, plus or minus 2 percentage
  points in steps of 0.5 (`?span=0.02&step=0.005`).
- **Cells**: the value per share, shaded green when it is above the current
  price and red when it is below, with the intensity following the distance.
- **The outlined cell is the base case**, and it always matches the valuation
  shown above.
- **`n/a`** means the growth rate is not below the WACC, so the terminal value
  does not exist and no number is reported.
- **The dashed border** marks a cell where the WACC and g are less than 3%
  apart: the number is there, but the terminal value dominates it, which is
  exactly the corner a bull case lives in.

For Apple the grid runs from $100.65 (WACC 12.43%, g 3%) to $698.88 (WACC
8.43%, g 7%) — a sevenfold range around a base case of $179.43, and the two
most optimistic corners are the fragile ones.

---

## Recent news

The interface has a **Recent news** section, and those headlines are also the
context the analyst model reads before it estimates anything.

- **Source**: the Yahoo Finance news feed of the ticker, cached in SQLite with
  its own TTL (6 hours by default) so a second request does not re-fetch it.
- **Relevance**: Yahoo mixes market-wide stories into a ticker feed. The items
  that name the ticker or the company are ranked first, and the ones that say
  nothing about the company are dropped when enough relevant ones are left.
- **Context for the model**: each headline, its publisher, its date and a
  truncated summary go into the prompt, and the model is asked to take them
  into account (a debt issue, a dividend decision, an acquisition, an outage)
  and to say in the note when a headline drove the estimate.
- **It is context, not the analysis**: a news failure never takes the
  valuation down, it only means the model estimates without the headlines.

```bash
export WACC_LAB_NEWS_TTL_HOURS=6
export WACC_LAB_NEWS_LIMIT=8
```

---

## The interface

Single page, no build step: a ticker picker (curated catalog plus any Yahoo
ticker), the analysis cards (WACC, growth, valuation, inputs, news, warnings)
and an inputs table where every automatic value can be overridden by hand.

Monetary values are shown with the currency of the ticker — `$136.06B`,
`$3.36T`, `$179.43` — never as a raw number, and the values the analyst model
wrote carry an `LLM` badge.

---

## API

| Method | Route | What it does |
|---|---|---|
| `GET` | `/api/tickers` | The curated universe (69 tickers, grouped by sector) |
| `GET` | `/api/analysis/{ticker}` | The full analysis; `?refresh=true` forces a recompute, `?use_llm=false` skips the analyst and the news |
| `POST` | `/api/analysis/{ticker}/overrides` | Saves manual inputs and recomputes |
| `DELETE` | `/api/analysis/{ticker}/overrides` | Drops the overrides and goes back to automatic |
| `GET` | `/api/analysis/{ticker}/sensitivity` | The WACC x g grid; `?span=` and `?step=` size it |
| `GET` | `/api/health` | Database path, cache TTL and the analyst configuration |
| `GET` | `/` | The web interface |

`POST /api/analysis/{ticker}/overrides` accepts any subset of:

```json
{
  "beta": 1.2,
  "risk_free_rate": 0.045,
  "equity_risk_premium": 0.055,
  "pretax_cost_of_debt": 0.055,
  "tax_rate": 0.25,
  "debt_weight": 0.15,
  "growth_rate": 0.03,
  "base_fcf": 1.2e10,
  "projection_years": 5
}
```

---

## Persistence

One SQLite file (`data/wacc_lab.db`) with four tables:

| Table | Content |
|---|---|
| `snapshots` | The raw fundamentals per ticker, with the fetch timestamp |
| `analyses` | The latest computed analysis per ticker |
| `overrides` | The manual inputs per ticker |
| `universe` | The curated ticker catalog |

Cache behaviour:

- ticker not stored → compute it and store it (`cache.status = "computed"`);
- stored but older than the TTL (24h by default) → recompute (`"stale"`);
- stored and fresh → serve from SQLite without touching Yahoo (`"fresh"`);
- `?refresh=true` → always recompute (`"refreshed"`).

Configuration via environment variables:

```bash
WACC_LAB_DB=/path/to/db.sqlite       # default: data/wacc_lab.db
WACC_LAB_TTL_HOURS=24                # default: 24
```

---

## What it cannot do

This is the honest list. None of these are hidden behind defaults.

1. **It is not a full DCF.** One FCF base growing at one rate, discounted at one
   rate. There is no working capital schedule, no capex plan, no debt schedule,
   no three-statement model, and no mid-year convention.
2. **The normalization is an average, not an adjustment.** The base is the mean
   of the last three fiscal years, which smooths the noise but does not correct
   for a known one-off (a restructuring, a year of heavy capex, a litigation
   charge). For a growing company the average sits below the latest year, so
   the model grows from a lower base than the trailing number would give.
   Three years is a short window for a cyclical business.
3. **g is an identity, not a forecast.** `ROE × retention` says what growth the
   current returns can fund; it says nothing about what the market expects. It is
   also inflated by buybacks, which is why it usually hits the 5% ceiling.
4. **The caps are policy, not finance.** The 5% ceiling and the 3% minimum spread
   move the answer. They exist to keep the perpetuity meaningful; they are not
   derived from anything.
5. **Beta is raw.** Yahoo's 5-year monthly beta, with no Blume adjustment, no
   country risk, no size premium and no idiosyncratic risk adjustment. The ERP is
   a fixed 5.00%, not estimated.
6. **The cost of debt is approximate.** Interest expense over the *latest* total
   debt, not the average debt of the period. For companies that changed their
   debt level during the year the ratio is biased, and interest expense that nets
   against interest income understates the true cost.
7. **The capital structure is incomplete.** Market cap plus total debt. Operating
   leases, pensions, minority interests, preferred stock and unfunded obligations
   are ignored.
8. **The tax rate is effective, not marginal.** Trailing tax provision over
   trailing pre-tax income. Net operating losses, credits and deferred taxes are
   ignored.
9. **No currency conversion.** Every figure stays in the reporting currency of the
   ticker. Comparing a US dollar DCF with a euro or yen one is not meaningful.
10. **No consensus estimates, no scenarios, no sensitivity tables.** There is no
    analyst forecast, no bull/base/bear case, no WACC × g grid and no Monte Carlo.
    The model gives one number plus its warnings.
11. **Yahoo Finance data is scraped, not contracted.** `yfinance` reads
    non-public endpoints. Row names change, fields go missing, and rate limiting
    happens. A missing field silently becomes a fallback with a warning, never a
    crash.
12. **TTM assumes four quarters.** If a company has fewer quarters reported, the
    sum covers a shorter period and the tool does not say so.
13. **Value per share ignores future dilution.** It uses current shares
    outstanding; stock-based compensation and convertible instruments are not
    projected.
14. **One local user, one file.** No authentication, no multi-user isolation, no
    migration story beyond the `CREATE TABLE IF NOT EXISTS` schema. The database
    is local and unencrypted.
15. **Only the latest analysis is kept.** There is no valuation history per
    ticker, so you cannot see how the WACC moved over time.
16. **Manual growth is still constrained.** A manual g is not subject to the 5%
    ceiling, but it is forced to keep the minimum spread below the WACC. The
    result reports that it was capped.
17. **The analyst fallback is a model, not data.** An LLM estimate is a
    plausible guess based on the sector and the company profile. It is labelled,
    range-checked and never allowed to overwrite Yahoo, but it is still a guess:
    treat every `llm` value as an assumption, not as a fact.
18. **The analyst cannot rescue a broken snapshot.** If Yahoo Finance is
    unreachable, the request fails with an error instead of quietly serving an
    invented company. The fallback fills gaps, it does not replace the source.
19. **The analyst is slow.** A first call pays the model load plus the
    inference (tens of seconds); the estimate is then cached with the snapshot.
20. **The news are headlines, not articles.** The model reads the title, the
    publisher, the date and a truncated summary. It does not read the full
    story, and Yahoo's own relevance ranking decides what reaches the feed.
21. **The news filter is textual.** A story that mentions the company in one
    sentence is kept, and a story about the company that never says its name
    is dropped. The order of the headlines is a heuristic, not a judgement.
22. **The grid moves one thing at a time.** It perturbs the WACC and the g of a
    simple model, so it inherits every weakness of that model and it ignores
    the correlation between the two inputs: a WACC that falls because the
    business got safer usually comes with a g that falls too, and the grid
    does not show that path.
23. **The fragile flag is a threshold, not a measurement.** A cell is flagged
    when the WACC and g are less than 3% apart, because below that the Gordon
    denominator stops meaning anything. How bad the number is in that corner
    is left to the reader.

---

## Layout

```
src/wacc_lab/
  api.py             FastAPI routes
  service.py         Provider + cache + overrides + analyst + engines
  db.py              SQLite store
  models.py          Pydantic models
  catalog.py         The curated ticker universe
  engine/
    wacc.py          CAPM, after-tax cost of debt, weights
    growth.py        g = ROE × b, with the ceiling and the minimum-spread rule
    valuation.py     The simple DCF
    normalization.py The average of the last fiscal years
    sensitivity.py   The WACC x g grid
  providers/
    yahoo.py         Everything that talks to Yahoo Finance
    analyst.py       The gap detector, the prompt and the range validation
    llm.py           The OpenAI-compatible client
    news.py          The news feed and its relevance ranking
  static/            index.html, app.js, styles.css (no build step)
tests/               Engine, analyst and API tests, all offline
odd/tasks/           The feature document used while building this
```

---

## Where this goes next

Built simple first, on purpose. The next increments, in order of value:

1. Valuation history per ticker, so you can see the WACC move over time.
2. A WACC × g sensitivity grid, which is where the real insight is.
3. Normalized FCF (3-year average) and a scenario per company.
4. A second provider (SEC filings / financialmodelingprep) to cross-check Yahoo.
