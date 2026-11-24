"""Relevant news for a ticker.

Yahoo Finance returns the stories that mention the company, not only the ones
published by the company itself, so the items are ranked by how directly they
mention the ticker or the company name.

The headlines are also the context the analyst model receives: a recent debt
issue, a dividend decision or an acquisition changes what a sensible cost of
debt or retention ratio looks like.
"""

from __future__ import annotations

import re
from typing import Protocol

import yfinance as yf
from pydantic import ValidationError

from ..models import NewsItem
from .base import ProviderError

LEGAL_SUFFIXES = ("inc.", "inc", "corp.", "corp", "plc", "ltd.", "ltd", "co.", "co", "s.a.", "sa", "n.v.", "nv", "a.g.", "ag")


def _mentions(haystack: str, needle: str) -> bool:
    """Whether the text mentions the term.

    A short ticker such as "T" or "V" would match almost any text, so it only
    counts when it appears as a word of its own.
    """
    if not needle:
        return False
    if len(needle) <= 3:
        return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
    return needle in haystack


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


def _as_text(value: object) -> str | None:
    """A field of the payload as text, or nothing when it is not one.

    Yahoo is not consistent about the types it returns: a publication date
    can be an ISO string in one build and an epoch in another. A field that
    cannot be read is dropped instead of breaking the whole analysis.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


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
            if not isinstance(entry, dict):
                continue
            try:
                item = self._to_item(entry)
            except ValidationError:
                # A story that does not fit the shape is dropped: the news
                # are context, not the analysis.
                continue
            if item is not None:
                items.append(item)

        return self._rank(items, symbol, company_name)[:limit]

    # ----------------------------------------------------------------- parts
    @staticmethod
    def _to_item(entry: dict) -> NewsItem | None:
        # yfinance 1.8 nests the story in "content"; older builds are flat.
        content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
        title = _as_text(content.get("title"))
        if not title:
            return None

        provider = content.get("provider")
        publisher = None
        if isinstance(provider, dict):
            publisher = _as_text(provider.get("displayName"))
        elif isinstance(provider, str):
            publisher = provider
        if not publisher:
            # The legacy flat shape used "publisher".
            publisher = _as_text(content.get("publisher"))

        link = None
        for key in ("clickThroughUrl", "canonicalUrl", "previewUrl"):
            candidate = content.get(key)
            if isinstance(candidate, dict) and candidate.get("url"):
                link = _as_text(candidate["url"])
                break
            if isinstance(candidate, str) and candidate:
                link = candidate
                break

        summary = _as_text(content.get("summary")) or _as_text(
            content.get("description")
        )

        return NewsItem(
            title=title,
            publisher=publisher,
            published_at=_as_text(content.get("pubDate"))
            or _as_text(content.get("displayTime")),
            link=link,
            summary=summary,
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
            if _mentions(haystack, symbol.upper()):
                score += 2
            if name and _mentions(haystack, name):
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
