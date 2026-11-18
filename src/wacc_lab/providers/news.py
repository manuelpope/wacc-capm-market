"""Relevant news for a ticker.

Yahoo Finance returns the stories that mention the company, not only the ones
published by the company itself, so the items are ranked by how directly they
mention the ticker or the company name.

The headlines are also the context the analyst model receives: a recent debt
issue, a dividend decision or an acquisition changes what a sensible cost of
debt or retention ratio looks like.
"""

from __future__ import annotations

from typing import Protocol

import yfinance as yf

from ..models import NewsItem
from .base import ProviderError

LEGAL_SUFFIXES = ("inc.", "inc", "corp.", "corp", "plc", "ltd.", "ltd", "co.", "co", "s.a.", "sa", "n.v.", "nv", "a.g.", "ag")


def _company_keyword(company_name: str | None) -> str:
    """The company name without its legal suffix, for a text match."""
    if not company_name:
        return ""
    name = company_name.strip().lower()
    for suffix in LEGAL_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break
    return name.strip(" ,.")


class NewsProvider(Protocol):
    def fetch(
        self, ticker: str, limit: int = 8, company_name: str | None = None
    ) -> list[NewsItem]: ...


class YahooNewsProvider:
    provider_name = "yahoo"

    def fetch(
        self, ticker: str, limit: int = 8, company_name: str | None = None
    ) -> list[NewsItem]:
        symbol = ticker.strip().upper()
        if not symbol:
            return []
        try:
            raw = yf.Ticker(symbol).news or []
        except Exception as exc:
            raise ProviderError(
                f"Yahoo Finance news request failed for {symbol}: {exc}"
            ) from exc

        items: list[NewsItem] = []
        for entry in raw:
            item = self._to_item(entry)
            if item is not None:
                items.append(item)

        return self._rank(items, symbol, company_name)[:limit]

    # ----------------------------------------------------------------- parts
    @staticmethod
    def _to_item(entry: dict) -> NewsItem | None:
        # yfinance 1.8 nests the story in "content"; older builds are flat.
        content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
        title = (content.get("title") or "").strip()
        if not title:
            return None

        provider = content.get("provider")
        publisher = None
        if isinstance(provider, dict):
            publisher = provider.get("displayName")
        elif isinstance(provider, str):
            publisher = provider
        if not publisher:
            # The legacy flat shape used "publisher".
            legacy = content.get("publisher")
            publisher = legacy if isinstance(legacy, str) else None

        link = None
        for key in ("clickThroughUrl", "canonicalUrl", "previewUrl"):
            candidate = content.get(key)
            if isinstance(candidate, dict) and candidate.get("url"):
                link = candidate["url"]
                break
            if isinstance(candidate, str) and candidate:
                link = candidate
                break

        summary = content.get("summary") or content.get("description") or ""

        return NewsItem(
            title=title,
            publisher=publisher,
            published_at=content.get("pubDate") or content.get("displayTime"),
            link=link,
            summary=(summary or "").strip() or None,
        )

    @staticmethod
    def _rank(
        items: list[NewsItem], symbol: str, company_name: str | None = None
    ) -> list[NewsItem]:
        """Stories that name the ticker or the company come first.

        Yahoo mixes the stories of the whole market into a ticker feed, so the
        items that say nothing about the company are dropped when enough
        relevant ones are left.
        """
        name = _company_keyword(company_name).upper()

        def relevance(item: NewsItem) -> int:
            haystack = f"{item.title} {item.summary or ''}".upper()
            score = 0
            if symbol.upper() in haystack:
                score += 2
            if name and name in haystack:
                score += 1
            return score

        ordered = sorted(
            items,
            key=lambda item: (relevance(item), item.published_at or ""),
            reverse=True,
        )
        ranked = [
            NewsItem(
                title=item.title,
                publisher=item.publisher,
                published_at=item.published_at,
                link=item.link,
                summary=item.summary,
                relevance=relevance(item),
            )
            for item in ordered
        ]

        relevant = [item for item in ranked if item.relevance > 0]
        if len(relevant) >= 3:
            return relevant
        return ranked
