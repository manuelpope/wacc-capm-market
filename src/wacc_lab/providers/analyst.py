"""The analyst extractor.

When Yahoo Finance cannot supply a number, the model is asked to estimate it.
The rules that keep this honest:

* the model only fills fields Yahoo could not compute, it never overwrites a
  Yahoo value;
* it is asked for a decimal fraction, and a value that comes back as a whole
  percentage is normalized instead of discarded;
* every value has to land inside a plausible band for its field, otherwise it
  is rejected and reported;
* a field the model declines (null) stays missing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from ..models import Fundamentals, NewsItem

SYSTEM_PROMPT = (
    "You are a careful equity analyst. You answer with JSON only, no prose. "
    "You never invent a number you cannot justify, and you return null when "
    "you are not reasonably confident."
)

# field -> (label, accept range, plausible range, output key)
ESTIMABLE_FIELDS: dict[str, dict] = {
    "pretax_cost_of_debt": {
        "label": "annual pre-tax cost of debt (blended with existing debt and new issuance)",
        "accept": (0.0, 0.30),
        "plausible": (0.005, 0.20),
        "output_key": "pretax_cost_of_debt",
    },
    "tax_rate": {
        "label": "effective corporate tax rate",
        "accept": (0.0, 0.50),
        "plausible": (0.03, 0.45),
        "output_key": "tax_rate",
    },
    "roe": {
        "label": "return on equity (net income over average book equity)",
        "accept": (-0.50, 1.50),
        "plausible": (-0.30, 1.00),
        "output_key": "roe",
    },
    "retention_ratio": {
        "label": "share of net income retained (1 - payout ratio)",
        "accept": (0.0, 1.0),
        "plausible": (0.0, 1.0),
        "output_key": "retention_ratio",
    },
    "fcf_ttm": {
        "label": "free cash flow as a share of revenue",
        "accept": (-0.30, 0.60),
        "plausible": (-0.10, 0.45),
        "output_key": "fcf_margin",
    },
}

# Which provider source means "Yahoo could not compute this".
GAP_SOURCES: dict[str, set[str]] = {
    "pretax_cost_of_debt": {"estimated_rf_plus_spread", "unavailable"},
    "tax_rate": {"default", "unavailable"},
    "roe": {"unavailable"},
    "retention_ratio": {"unavailable"},
    "fcf_ttm": {"unavailable"},
}


class LLMClient(Protocol):
    def complete(self, prompt: str, system: str | None = None) -> str: ...


@dataclass
class AnalystEstimate:
    values: dict[str, float] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    rejections: list[str] = field(default_factory=list)
    error: str | None = None


def extract_json_object(text: str) -> dict | None:
    """Pull the first balanced JSON object out of a model answer."""
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        cleaned = re.sub(r"```[a-zA-Z]*", " ", cleaned)
    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def missing_gaps(fundamentals: Fundamentals) -> list[str]:
    """Fields the provider could not compute on its own."""
    gaps: list[str] = []
    for name, bad_sources in GAP_SOURCES.items():
        source = fundamentals.field_sources.get(name, "unavailable")
        if source in bad_sources:
            gaps.append(name)
    return gaps


class AnalystExtractor:
    def __init__(self, client: LLMClient, model_label: str = "the analyst model") -> None:
        self.client = client
        self.model_label = model_label

    def estimate(
        self,
        ticker: str,
        fundamentals: Fundamentals | None,
        gaps: list[str],
        news: list[NewsItem] | None = None,
    ) -> AnalystEstimate:
        wanted = [name for name in gaps if name in ESTIMABLE_FIELDS]
        if not wanted:
            return AnalystEstimate()

        prompt = self._build_prompt(ticker, fundamentals, wanted, news or [])
        try:
            raw = self.client.complete(prompt, system=SYSTEM_PROMPT)
        except Exception as exc:  # the model is a best effort, never a hard dependency
            return AnalystEstimate(error=str(exc))

        payload = extract_json_object(raw)
        if payload is None:
            return AnalystEstimate(error="the analyst model did not return a JSON object")

        notes = payload.get("notes") if isinstance(payload.get("notes"), dict) else {}
        values: dict[str, float] = {}
        kept_notes: dict[str, str] = {}
        rejections: list[str] = []

        for name in wanted:
            spec = ESTIMABLE_FIELDS[name]
            raw_value = payload.get(spec["output_key"])
            if raw_value is None:
                continue
            number = _to_float(raw_value)
            if number is None:
                rejections.append(f"{name}: the model returned {raw_value!r}")
                continue

            low, high = spec["accept"]
            if not low <= number <= high:
                plausible_low, plausible_high = spec["plausible"]
                scaled = number / 100.0
                if plausible_low <= scaled <= plausible_high:
                    number = scaled
                else:
                    rejections.append(
                        f"{name}: the model returned {raw_value!r}, outside the plausible "
                        f"range {plausible_low:.0%}-{plausible_high:.0%}"
                    )
                    continue
            values[name] = number
            note = notes.get(name)
            if note:
                kept_notes[name] = str(note)

        return AnalystEstimate(values=values, notes=kept_notes, rejections=rejections)

    def apply(
        self,
        fundamentals: Fundamentals,
        estimate: AnalystEstimate,
    ) -> Fundamentals:
        """Write the estimated values into the fundamentals, with provenance."""
        warnings = list(fundamentals.warnings)
        sources = dict(fundamentals.field_sources)
        updates: dict[str, object] = {}

        if estimate.error:
            warnings.append(
                f"the analyst model could not be used: {estimate.error}"
            )

        for name, value in estimate.values.items():
            # The provider warning about the fallback is stale once the model
            # answered that field.
            warnings = [
                warning
                for warning in warnings
                if not warning.startswith(f"[{name}] ")
            ]
            if name == "fcf_ttm":
                if not fundamentals.revenue_ttm:
                    warnings.append(
                        "the analyst model estimated a free cash flow margin but the "
                        "trailing revenue is unknown, the cash flow stays missing"
                    )
                    continue
                value = fundamentals.revenue_ttm * value
            updates[name] = value
            sources[name] = "llm"
            note = estimate.notes.get(name)
            message = f"{name} was estimated by {self.model_label}"
            if note:
                message = f"{message}: {note}"
            warnings.append(message)

        for rejection in estimate.rejections:
            warnings.append(f"the analyst model answer was discarded, {rejection}")

        if not updates:
            return fundamentals.model_copy(
                update={"warnings": warnings, "field_sources": sources}
            )
        return fundamentals.model_copy(
            update={**updates, "warnings": warnings, "field_sources": sources}
        )

    # ----------------------------------------------------------------- prompt
    def _build_prompt(
        self,
        ticker: str,
        fundamentals: Fundamentals | None,
        wanted: list[str],
        news: list[NewsItem] | None = None,
    ) -> str:
        facts = self._known_facts(fundamentals)
        lines = [
            "Estimate the missing inputs of a discounted cash flow model for one company.",
            "",
            f"Ticker: {ticker}",
        ]
        if fundamentals is not None:
            lines.append(f"Company: {fundamentals.name}")
            if fundamentals.sector:
                lines.append(f"Sector: {fundamentals.sector}")
            if fundamentals.currency:
                lines.append(f"Currency: {fundamentals.currency}")
        lines.extend(["", "Known facts:", *facts] if facts else ["", "No facts are available."])
        headlines = self._news_lines(news or [])
        if headlines:
            lines.extend(["", "Recent news about this company:", *headlines])
            lines.extend(
                [
                    "- Take the news into account when it changes the estimate "
                    "(a debt issue, a dividend decision, an acquisition, an outage, "
                    "a leadership change).",
                    "- Say in the note when a headline drove the estimate.",
                ]
            )
        lines.extend(["", "Estimate ONLY these fields:"])
        for name in wanted:
            spec = ESTIMABLE_FIELDS[name]
            low, high = spec["plausible"]
            lines.append(
                f'- "{spec["output_key"]}": {spec["label"]}, as a decimal fraction '
                f"between {low:.2f} and {high:.2f}"
            )
        lines.extend(
            [
                "",
                "Rules:",
                "- Answer with JSON only, no prose.",
                "- Use decimal fractions (0.21, not 21).",
                "- If you are not reasonably confident about a field, return null for it.",
                "- Base the estimate on durable characteristics of the company and its sector.",
                "- Add a short note per estimated field under a \"notes\" object.",
                "",
                'Format: {"pretax_cost_of_debt": 0.05, "tax_rate": 0.21, "roe": 0.45, '
                '"retention_ratio": 0.85, "fcf_margin": 0.25, '
                '"notes": {"tax_rate": "one short sentence"}}',
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _news_lines(news: list[NewsItem]) -> list[str]:
        lines: list[str] = []
        for item in news[:8]:
            date = (item.published_at or "")[:10]
            publisher = item.publisher or ""
            head = f"- [{date}] {item.title}"
            if publisher:
                head = f"- [{date}] {publisher}: {item.title}"
            lines.append(head)
            if item.summary:
                lines.append(f"  {item.summary[:220]}")
        return lines

    @staticmethod
    def _known_facts(fundamentals: Fundamentals | None) -> list[str]:
        if fundamentals is None:
            return []
        facts: list[str] = []
        if fundamentals.market_cap:
            facts.append(f"- Market capitalisation: {fundamentals.market_cap:,.0f}")
        if fundamentals.total_debt:
            facts.append(f"- Total debt: {fundamentals.total_debt:,.0f}")
        if fundamentals.cash:
            facts.append(f"- Cash: {fundamentals.cash:,.0f}")
        if fundamentals.revenue_ttm:
            facts.append(f"- Trailing twelve month revenue: {fundamentals.revenue_ttm:,.0f}")
        if fundamentals.net_income_ttm:
            facts.append(f"- Trailing twelve month net income: {fundamentals.net_income_ttm:,.0f}")
        if fundamentals.price:
            facts.append(f"- Share price: {fundamentals.price:,.2f}")
        return facts


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None
