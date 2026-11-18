"""Provider interface and errors."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Fundamentals


class ProviderError(RuntimeError):
    """The provider could not answer (network problem, bad payload, ...)."""


class TickerNotFoundError(ProviderError):
    """Yahoo Finance does not know this ticker."""


@runtime_checkable
class FundamentalsProvider(Protocol):
    def fetch(self, ticker: str, use_llm: bool = True) -> Fundamentals: ...
