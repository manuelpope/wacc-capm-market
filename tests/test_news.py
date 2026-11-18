"""Tests for the news provider, the prompt context and the news flow."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from wacc_lab.api import create_app
from wacc_lab.db import Store
from wacc_lab.models import NewsItem
from wacc_lab.providers.analyst import AnalystExtractor
from wacc_lab.providers.base import ProviderError
from wacc_lab.providers.news import YahooNewsProvider
from wacc_lab.service import AnalysisService

from test_api import FakeProvider, SAMPLE  # noqa: F401  (shared fixtures)


def story(title: str, publisher: str = "Reuters", summary: str = "A story.", day: str = "2026-11-18"):
    return {
        "id": "abc",
        "content": {
            "contentType": "STORY",
            "title": title,
            "summary": summary,
            "pubDate": f"{day}T10:00:00Z",
            "provider": {"displayName": publisher},
            "clickThroughUrl": {"url": f"https://example.com/{title[:12].replace(' ', '-')}"},
        },
    }


class FakeTicker:
    def __init__(self, news):
        self.news = news


def test_the_provider_normalizes_the_nested_yahoo_shape(monkeypatch):
    import wacc_lab.providers.news as news_module

    monkeypatch.setattr(
        news_module.yf,
        "Ticker",
        lambda symbol: FakeTicker([story("Apple buys a startup", publisher="Bloomberg")]),
    )

    items = YahooNewsProvider().fetch("AAPL")

    assert len(items) == 1
    assert items[0].title == "Apple buys a startup"
    assert items[0].publisher == "Bloomberg"
    assert items[0].published_at.startswith("2026-11-18")
    assert items[0].link == "https://example.com/Apple-buys-a"


def test_the_provider_reads_the_flat_legacy_shape(monkeypatch):
    import wacc_lab.providers.news as news_module

    monkeypatch.setattr(
        news_module.yf,
        "Ticker",
        lambda symbol: FakeTicker(
            [
                {
                    "title": "Legacy shape",
                    "publisher": "Dow Jones",
                    "providerPublishTime": 1700000000,
                    "link": {"url": "https://example.com/legacy"},
                }
            ]
        ),
    )

    items = YahooNewsProvider().fetch("AAPL")

    assert items[0].title == "Legacy shape"
    assert items[0].publisher == "Dow Jones"


def test_the_provider_drops_the_stories_that_say_nothing_about_the_company(monkeypatch):
    import wacc_lab.providers.news as news_module

    monkeypatch.setattr(
        news_module.yf,
        "Ticker",
        lambda symbol: FakeTicker(
            [
                story("Apple announces a buyback"),
                story("Apple to open a new store in Madrid"),
                story("Apple signs a cloud supplier deal"),
                story("Why Is Snap Stock Going Up?"),
                story("Planes, banks and the NSA all went down in one week"),
            ]
        ),
    )

    items = YahooNewsProvider().fetch("AAPL", company_name="Apple Inc.")

    assert len(items) == 3
    assert all("apple" in item.title.lower() for item in items)


def test_the_provider_keeps_everything_when_too_little_is_relevant(monkeypatch):
    import wacc_lab.providers.news as news_module

    monkeypatch.setattr(
        news_module.yf,
        "Ticker",
        lambda symbol: FakeTicker(
            [story("Apple announces a buyback"), story("Markets rally on rate hopes")]
        ),
    )

    items = YahooNewsProvider().fetch("AAPL", company_name="Apple Inc.")

    assert len(items) == 2


def test_the_provider_ranks_the_stories_that_name_the_ticker_first(monkeypatch):
    import wacc_lab.providers.news as news_module

    monkeypatch.setattr(
        news_module.yf,
        "Ticker",
        lambda symbol: FakeTicker(
            [
                story("Markets rally on rate hopes"),
                story("AAPL announces a buyback"),
            ]
        ),
    )

    items = YahooNewsProvider().fetch("AAPL")

    assert items[0].title == "AAPL announces a buyback"
    assert items[0].relevance == 2
    assert items[1].relevance == 0


def test_the_provider_survives_a_yahoo_failure(monkeypatch):
    import wacc_lab.providers.news as news_module

    class Boom:
        @property
        def news(self):
            raise RuntimeError("yahoo is down")

    monkeypatch.setattr(news_module.yf, "Ticker", lambda symbol: Boom())

    with pytest.raises(ProviderError):
        YahooNewsProvider().fetch("AAPL")


# --------------------------------------------------------------- prompt context


def test_the_prompt_carries_the_headlines():
    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt, system=None):
            self.prompts.append(prompt)
            return json.dumps({"tax_rate": 0.2})

    llm = FakeLLM()
    extractor = AnalystExtractor(llm)
    news = [
        NewsItem(
            title="Apple issues 10-year bonds",
            publisher="Reuters",
            published_at="2026-11-17T08:00:00Z",
            summary="The company priced a new benchmark bond.",
        )
    ]

    extractor.estimate("AAPL", SAMPLE, ["tax_rate"], news=news)

    prompt = llm.prompts[0]
    assert "Apple issues 10-year bonds" in prompt
    assert "Reuters" in prompt
    assert "Take the news into account" in prompt


# ------------------------------------------------------------------- the flow


class FakeNewsProvider:
    def __init__(self, items=None, fail=False):
        self.items = items or [
            NewsItem(title="Apple issues bonds", publisher="Reuters", published_at="2026-11-17")
        ]
        self.fail = fail
        self.calls = 0

    def fetch(self, ticker, limit=8, company_name=None):
        self.calls += 1
        if self.fail:
            raise ProviderError("the news could not be read")
        return self.items[:limit]


def build_client(tmp_path, news_provider, use_news=True):
    provider = FakeProvider(SAMPLE)
    store = Store(tmp_path / "test.db")
    service = AnalysisService(
        store=store,
        provider=provider,
        ttl_hours=24,
        analyst=AnalystExtractor(_FakeLLM(), model_label="the analyst model (test)"),
        news_provider=news_provider if use_news else None,
    )
    return TestClient(create_app(service)), provider, news_provider


class _FakeLLM:
    def complete(self, prompt, system=None):
        return json.dumps({"tax_rate": 0.2})


def test_the_analysis_returns_the_news(tmp_path):
    news_provider = FakeNewsProvider()
    test_client, _, _ = build_client(tmp_path, news_provider)

    body = test_client.get("/api/analysis/AAPL").json()

    assert len(body["news"]) == 1
    assert body["news"][0]["title"] == "Apple issues bonds"
    assert news_provider.calls == 1


def test_the_news_are_cached_and_not_fetched_again(tmp_path):
    news_provider = FakeNewsProvider()
    test_client, _, _ = build_client(tmp_path, news_provider)

    test_client.get("/api/analysis/AAPL")
    second = test_client.get("/api/analysis/AAPL").json()

    assert len(second["news"]) == 1
    assert news_provider.calls == 1


def test_the_news_are_not_loaded_when_the_analyst_is_off(tmp_path):
    news_provider = FakeNewsProvider()
    test_client, _, _ = build_client(tmp_path, news_provider)

    body = test_client.get("/api/analysis/AAPL", params={"use_llm": "false"}).json()

    assert body["news"] == []
    assert news_provider.calls == 0


def test_a_news_failure_does_not_take_the_analysis_down(tmp_path):
    news_provider = FakeNewsProvider(fail=True)
    test_client, _, _ = build_client(tmp_path, news_provider)

    response = test_client.get("/api/analysis/AAPL")

    assert response.status_code == 200
    assert response.json()["news"] == []


def test_a_short_ticker_only_matches_a_standalone_word(monkeypatch):
    import wacc_lab.providers.news as news_module

    monkeypatch.setattr(
        news_module.yf,
        "Ticker",
        lambda symbol: FakeTicker(
            [
                story("The market rallied on rate hopes"),
                story("T closes the quarter with a profit"),
            ]
        ),
    )

    items = YahooNewsProvider().fetch("T", company_name="AT&T")

    # "The" is not a standalone "T".
    assert items[0].title.startswith("T closes")
    assert items[0].relevance == 2
