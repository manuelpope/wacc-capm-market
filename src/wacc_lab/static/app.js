const state = { ticker: null, analysis: null };

const OVERRIDE_FIELDS = [
  { key: "beta", label: "Beta", auto: (a) => a.inputs.beta, step: "0.01" },
  { key: "risk_free_rate", label: "Risk-free rate (%)", auto: (a) => a.inputs.risk_free_rate, percent: true, step: "0.01" },
  { key: "equity_risk_premium", label: "Equity risk premium (%)", auto: (a) => a.inputs.equity_risk_premium, percent: true, step: "0.01" },
  { key: "pretax_cost_of_debt", label: "Pre-tax cost of debt (%)", auto: (a) => a.inputs.pretax_cost_of_debt, percent: true, step: "0.01" },
  { key: "tax_rate", label: "Tax rate (%)", auto: (a) => a.inputs.tax_rate, percent: true, step: "0.01" },
  { key: "debt_weight", label: "Debt weight (%)", auto: (a) => a.inputs.debt_weight, percent: true, step: "0.01" },
  { key: "growth_rate", label: "Growth g (%)", auto: (a) => a.growth.raw_growth, percent: true, step: "0.01" },
  { key: "base_fcf", label: "Base free cash flow (normalized)", auto: (a) => a.inputs.base_fcf, step: "1" },
  { key: "projection_years", label: "Projection horizon (years)", auto: () => 5, step: "1" }
];

const $ = (id) => document.getElementById(id);

function pct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

const CURRENCY_SYMBOLS = {
  USD: "$", EUR: "€", GBP: "£", JPY: "¥", CNY: "¥", CHF: "CHF ", CAD: "CA$",
  AUD: "A$", BRL: "R$", ARS: "AR$", MXN: "MX$", INR: "₹", KRW: "₩", SEK: "SEK ",
  NOK: "NOK ", DKK: "DKK ", HKD: "HK$", TWD: "NT$"
};

function currencyPrefix(currency) {
  if (!currency) return "";
  return CURRENCY_SYMBOLS[currency] || `${currency} `;
}

function money(value, currency) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const prefix = currencyPrefix(currency);
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${prefix}${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${prefix}${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${prefix}${(value / 1e6).toFixed(2)}M`;
  return `${prefix}${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function price(value, currency) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${currencyPrefix(currency)}${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
}

function number(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function setText(id, text) {
  const node = $(id);
  if (node) node.textContent = text;
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const raw = await response.text();
  let body = null;
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch (err) {
      body = { detail: raw };
    }
  }
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `request failed (${response.status})`;
    throw new Error(detail);
  }
  return body;
}

function setStatus(message, kind = "idle") {
  const node = $("status");
  node.textContent = message;
  node.className = `status status-${kind}`;
}

async function loadCatalog() {
  const data = await request("/api/tickers");
  const select = $("ticker-select");
  select.innerHTML = "";
  const bySector = new Map();
  for (const item of data.tickers) {
    const sector = item.sector || "Other";
    if (!bySector.has(sector)) bySector.set(sector, []);
    bySector.get(sector).push(item);
  }
  const sectors = [...bySector.keys()].sort();
  for (const sector of sectors) {
    const group = document.createElement("optgroup");
    group.label = sector;
    for (const item of bySector.get(sector)) {
      const option = document.createElement("option");
      option.value = item.ticker;
      option.textContent = `${item.ticker} — ${item.name}`;
      group.appendChild(option);
    }
    select.appendChild(group);
  }
  const saved = window.localStorage.getItem("wacc-lab-ticker");
  if (saved) {
    const match = data.tickers.find((item) => item.ticker === saved);
    if (match) select.value = saved;
  }
}

function renderInputs(analysis) {
  const currency = analysis.currency;
  const body = $("inputs-body");
  body.innerHTML = "";
  const overrides = analysis.overrides || {};
  const sources = analysis.field_sources || {};

  for (const field of OVERRIDE_FIELDS) {
    const row = document.createElement("tr");
    const label = document.createElement("th");
    label.textContent = field.label;

    const automatic = document.createElement("td");
    const autoValue = field.auto(analysis);
    automatic.textContent = field.percent
      ? pct(autoValue)
      : field.key === "base_fcf"
        ? money(autoValue, currency)
        : autoValue ?? "—";
    const sourceKeys =
      field.key === "base_fcf" ? ["fcf_normalized", "fcf_ttm"] : [field.key];
    if (sourceKeys.some((key) => sources[key] === "llm")) {
      const badge = document.createElement("span");
      badge.className = "badge-llm";
      badge.textContent = "llm";
      badge.title = "this value was estimated by the analyst model, not read from Yahoo Finance";
      automatic.appendChild(badge);
    }

    const overrideCell = document.createElement("td");
    const input = document.createElement("input");
    input.type = "number";
    input.step = field.step || "0.01";
    input.dataset.key = field.key;
    input.dataset.percent = field.percent ? "1" : "0";
    const stored = overrides[field.key];
    if (stored !== null && stored !== undefined) {
      input.value = field.percent ? (stored * 100).toFixed(2) : stored;
    }
    overrideCell.appendChild(input);

    row.append(label, automatic, overrideCell);
    body.appendChild(row);
  }
}

function renderSensitivity(grid) {
  const host = $("sensitivity");
  const legend = $("sensitivity-legend");
  host.innerHTML = "";
  legend.innerHTML = "";

  if (!grid || !grid.cells || !grid.cells.length) {
    host.innerHTML = `<p class="news-empty">${
      (grid && grid.warnings && grid.warnings[0]) ||
      "The grid is not available for this company."
    }</p>`;
    return;
  }

  const table = document.createElement("table");
  table.className = "grid-table";

  const head = table.createTHead().insertRow();
  const corner = document.createElement("th");
  corner.textContent = "g \ WACC";
  head.appendChild(corner);
  for (const wacc of grid.wacc_axis) {
    const cell = document.createElement("th");
    cell.textContent = pct(wacc, 2);
    head.appendChild(cell);
  }

  const body = table.createTBody();
  for (let row = grid.g_axis.length - 1; row >= 0; row -= 1) {
    const line = body.insertRow();
    const rowHead = document.createElement("th");
    rowHead.textContent = pct(grid.g_axis[row], 2);
    line.appendChild(rowHead);

    for (let column = 0; column < grid.wacc_axis.length; column += 1) {
      const source = grid.cells[row][column];
      const cell = document.createElement("td");
      if (!source.valid) {
        cell.className = "invalid";
        cell.textContent = "n/a";
        cell.title = "the growth rate is not below the WACC, so the terminal value does not exist";
      } else {
        cell.textContent = price(source.value_per_share, grid.currency);
        if (source.upside_pct !== null && source.upside_pct !== undefined) {
          const up = source.upside_pct >= 0;
          cell.classList.add(up ? "up" : "down");
          const alpha = Math.min(0.32, Math.abs(source.upside_pct) * 0.32);
          cell.style.background = up
            ? `rgba(56, 211, 159, ${alpha})`
            : `rgba(255, 107, 107, ${alpha})`;
        }
        if (source.fragile) {
          cell.classList.add("fragile");
          cell.title = "the WACC and g are less than 3% apart, the terminal value dominates this number";
        }
        if (row === grid.base_row && column === grid.base_column) {
          cell.classList.add("base");
          cell.title = "base case";
        }
      }
      line.appendChild(cell);
    }
  }
  host.appendChild(table);

  const items = [
    ["background: rgba(56, 211, 159, 0.35)", "above the current price"],
    ["background: rgba(255, 107, 107, 0.35)", "below the current price"],
    ["outline: 2px solid #4da3ff; outline-offset: -2px", "base case"],
    ["border: 1px dashed #ffb020", "the WACC and g are less than 3% apart"]
  ];
  for (const [style, label] of items) {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.setAttribute("style", style);
    item.append(swatch, document.createTextNode(label));
    legend.appendChild(item);
  }
  const note = document.createElement("span");
  note.textContent = "n/a = the growth rate is not below the WACC";
  legend.appendChild(note);

  for (const warning of grid.warnings || []) {
    const line = document.createElement("div");
    line.className = "news-summary";
    line.style.color = "var(--warn)";
    line.textContent = warning;
    legend.appendChild(line);
  }
}

async function loadSensitivity(ticker, useLlm) {
  const host = $("sensitivity");
  host.innerHTML = '<p class="news-empty">Building the grid…</p>';
  try {
    const grid = await request(
      `/api/analysis/${encodeURIComponent(ticker)}/sensitivity?use_llm=${useLlm}`
    );
    renderSensitivity(grid);
  } catch (err) {
    host.innerHTML = `<p class="news-empty">${err.message}</p>`;
  }
}

function renderNews(analysis) {
  const list = $("news");
  list.innerHTML = "";
  const items = analysis.news || [];
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "news-empty";
    empty.textContent =
      "No news loaded. The headlines are read when the analyst model is enabled.";
    list.appendChild(empty);
    return;
  }
  for (const item of items) {
    const entry = document.createElement("li");
    const title = document.createElement("div");
    if (item.link) {
      const link = document.createElement("a");
      link.href = item.link;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.title;
      title.appendChild(link);
    } else {
      title.textContent = item.title;
    }
    const meta = document.createElement("div");
    meta.className = "news-meta";
    const date = (item.published_at || "").slice(0, 10);
    meta.textContent = [item.publisher, date].filter(Boolean).join(" · ");
    entry.append(title, meta);
    if (item.summary) {
      const summary = document.createElement("div");
      summary.className = "news-summary";
      summary.textContent = item.summary;
      entry.appendChild(summary);
    }
    list.appendChild(entry);
  }
}

function renderWarnings(analysis) {
  const list = $("warnings");
  list.innerHTML = "";
  for (const warning of analysis.warnings || []) {
    const item = document.createElement("li");
    item.textContent = warning;
    list.appendChild(item);
  }
}

function render(analysis) {
  state.analysis = analysis;
  const inputs = analysis.inputs;
  const wacc = analysis.wacc;
  const growth = analysis.growth;
  const valuation = analysis.valuation;

  document.getElementById("results").classList.remove("hidden");

  setText("company-name", analysis.name);
  setText(
    "company-meta",
    [analysis.ticker, analysis.sector, analysis.currency].filter(Boolean).join(" · ")
  );
  setText("headline-wacc", pct(wacc.wacc));
  setText("headline-growth", pct(growth.growth));
  setText(
    "headline-growth-meta",
    growth.manual ? "manual override" : `ROE × retention (raw ${pct(growth.raw_growth)})`
  );
  setText(
    "headline-value",
    valuation && valuation.value_per_share
      ? price(valuation.value_per_share, analysis.currency)
      : "—"
  );
  setText(
    "headline-value-meta",
    analysis.price ? `current price ${price(analysis.price, analysis.currency)}` : "DCF estimate"
  );

  setText("wacc-rf", pct(inputs.risk_free_rate));
  setText("wacc-erp", pct(inputs.equity_risk_premium));
  setText("wacc-beta", `${number(inputs.beta)} (${inputs.beta_source})`);
  setText("wacc-ke", pct(wacc.cost_of_equity));
  setText("wacc-kd", pct(inputs.pretax_cost_of_debt));
  setText("wacc-tax", pct(inputs.tax_rate));
  setText("wacc-kd-at", pct(wacc.after_tax_cost_of_debt));
  setText("wacc-wd", pct(wacc.debt_weight));
  setText("wacc-we", pct(wacc.equity_weight));
  setText("wacc-final", pct(wacc.wacc));

  setText("growth-method", growth.manual ? "manual" : "ROE × retention");
  setText("growth-roe", pct(inputs.roe));
  setText("growth-retention", pct(inputs.retention_ratio));
  setText("growth-raw", pct(growth.raw_growth));
  setText("growth-capped", growth.capped ? "yes" : "no");
  setText("growth-reason", growth.reason || "—");
  setText("growth-final", pct(growth.growth));

  if (valuation) {
    const currency = analysis.currency;
    setText("val-fcf", money(valuation.base_fcf, currency));
    setText("val-fcf-years", analysis.inputs.fcf_years ? `${analysis.inputs.fcf_years} years` : "—");
    setText("val-fcf-ttm", money(analysis.inputs.fcf_ttm, currency));
    setText("val-years", `${valuation.years} years`);
    setText("val-pv-explicit", money(valuation.pv_explicit, currency));
    setText("val-tv", money(valuation.terminal_value, currency));
    setText("val-pv-tv", money(valuation.pv_terminal, currency));
    setText("val-ev", money(valuation.enterprise_value, currency));
    setText("val-tv-share", pct(valuation.terminal_value_share, 1));
    setText("val-net-debt", money(valuation.net_debt, currency));
    setText("val-equity", money(valuation.equity_value, currency));
    setText("val-per-share", valuation.value_per_share ? price(valuation.value_per_share, currency) : "—");
    setText("val-price", analysis.price ? price(analysis.price, currency) : "—");
    const upside = $("val-upside");
    if (valuation.upside_pct === null || valuation.upside_pct === undefined) {
      upside.textContent = "—";
      upside.className = "";
    } else {
      upside.textContent = pct(valuation.upside_pct, 1);
      upside.className = valuation.upside_pct >= 0 ? "up" : "down";
    }
    const projection = valuation.projected_fcf
      .map((fcf, index) => `Y${index + 1}: ${money(fcf, analysis.currency)}`)
      .join("  ·  ");
    setText("val-projection", projection);
  } else {
    ["val-fcf", "val-fcf-years", "val-fcf-ttm", "val-years", "val-pv-explicit", "val-tv", "val-pv-tv", "val-ev", "val-tv-share", "val-net-debt", "val-equity", "val-per-share", "val-price", "val-upside", "val-projection"].forEach((id) => setText(id, "—"));
  }

  renderInputs(analysis);
  renderNews(analysis);
  renderWarnings(analysis);

  const statusLabels = {
    computed: "computed and stored",
    fresh: "served from the SQLite cache",
    stale: "cached snapshot was stale, recomputed",
    refreshed: "recomputed from Yahoo Finance"
  };
  setStatus(
    `${analysis.ticker}: ${statusLabels[analysis.cache.status] || analysis.cache.status}. ` +
      `snapshot ${analysis.cache.snapshot_at || "—"} · computed ${analysis.cache.computed_at || "—"}`,
    "ok"
  );
}

async function analyze(ticker, refresh = false) {
  const symbol = ticker.trim().toUpperCase();
  if (!symbol) {
    setStatus("Type a ticker first.", "error");
    return;
  }
  state.ticker = symbol;
  window.localStorage.setItem("wacc-lab-ticker", symbol);
  $("load-btn").disabled = true;
  $("refresh-btn").disabled = true;
  setStatus(`Loading ${symbol} from Yahoo Finance…`);
  try {
    const useLlm = $("llm-toggle").checked;
    const query = refresh ? `?refresh=true&use_llm=${useLlm}` : `?use_llm=${useLlm}`;
    const analysis = await request(`/api/analysis/${encodeURIComponent(symbol)}${query}`);
    render(analysis);
    loadSensitivity(symbol, useLlm);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    $("load-btn").disabled = false;
    $("refresh-btn").disabled = false;
  }
}

async function saveOverrides() {
  if (!state.ticker) return;
  const payload = {};
  for (const input of document.querySelectorAll("#inputs-body input")) {
    const raw = input.value.trim();
    if (raw === "") continue;
    let value = Number(raw);
    if (!Number.isFinite(value)) continue;
    if (input.dataset.percent === "1") value = value / 100;
    payload[input.dataset.key] = value;
  }
  $("save-btn").disabled = true;
  try {
    const useLlm = $("llm-toggle").checked;
    const analysis = await request(`/api/analysis/${encodeURIComponent(state.ticker)}/overrides?use_llm=${useLlm}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    render(analysis);
    loadSensitivity(state.ticker, useLlm);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    $("save-btn").disabled = false;
  }
}

async function resetOverrides() {
  if (!state.ticker) return;
  $("reset-btn").disabled = true;
  try {
    const useLlm = $("llm-toggle").checked;
    const analysis = await request(`/api/analysis/${encodeURIComponent(state.ticker)}/overrides?use_llm=${useLlm}`, {
      method: "DELETE"
    });
    render(analysis);
    loadSensitivity(state.ticker, useLlm);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    $("reset-btn").disabled = false;
  }
}

async function init() {
  try {
    const health = await request("/api/health");
    $("health").textContent = `SQLite · TTL ${health.ttl_hours}h`;
    await loadCatalog();
    const saved = window.localStorage.getItem("wacc-lab-ticker");
    if (saved) {
      analyze(saved);
    }
  } catch (err) {
    setStatus(err.message, "error");
  }

  $("load-btn").addEventListener("click", () => {
    const typed = $("ticker-input").value.trim();
    const ticker = typed || $("ticker-select").value;
    analyze(ticker);
  });

  $("refresh-btn").addEventListener("click", () => {
    const typed = $("ticker-input").value.trim();
    const ticker = typed || $("ticker-select").value || state.ticker;
    analyze(ticker, true);
  });

  $("ticker-select").addEventListener("change", (event) => {
    $("ticker-input").value = "";
    analyze(event.target.value);
  });

  $("ticker-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      $("load-btn").click();
    }
  });

  $("save-btn").addEventListener("click", saveOverrides);
  $("reset-btn").addEventListener("click", resetOverrides);
}

document.addEventListener("DOMContentLoaded", init);
