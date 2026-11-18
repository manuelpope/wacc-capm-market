"""Tests for the SQLite store."""

from __future__ import annotations

from wacc_lab.db import Store
from wacc_lab.models import Fundamentals


def test_the_store_does_not_touch_the_file_until_it_is_used(tmp_path):
    path = tmp_path / "lazy.db"
    store = Store(path)

    assert not path.exists()

    store.list_universe()

    assert path.exists()


def test_the_universe_is_seeded_on_the_first_use(tmp_path):
    store = Store(tmp_path / "test.db")

    universe = store.list_universe()

    assert len(universe) > 40
    assert {item["ticker"] for item in universe} >= {"AAPL", "MSFT"}


def test_the_news_are_cached_and_read_back(tmp_path):
    store = Store(tmp_path / "test.db")
    items = [
        {
            "title": "A story",
            "publisher": "Reuters",
            "published_at": "2026-11-18T10:00:00Z",
            "link": "https://example.com/a",
            "summary": "Something happened",
            "relevance": 2,
        }
    ]

    store.save_news("AAPL", items)
    news = store.get_news("AAPL")

    assert len(news) == 1
    assert news[0]["title"] == "A story"
    assert news[0]["relevance"] == 2


def test_an_outdated_snapshot_is_not_read(tmp_path):
    import json
    import sqlite3

    store = Store(tmp_path / "test.db")
    store.list_universe()  # creates the file

    # A snapshot written before the schema version existed.
    with sqlite3.connect(tmp_path / "test.db") as conn:
        conn.execute(
            "INSERT INTO snapshots (ticker, fetched_at, provider, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                "AAPL",
                "2026-11-18T10:00:00+00:00",
                "yahoo",
                json.dumps({"ticker": "AAPL", "fetched_at": "2026-11-18T10:00:00+00:00"}),
            ),
        )

    assert store.get_snapshot("AAPL") is None


def test_a_current_snapshot_is_read(tmp_path):
    store = Store(tmp_path / "test.db")
    store.save_snapshot(
        Fundamentals(
            ticker="AAPL",
            name="Apple Inc.",
            fetched_at="2026-11-18T10:00:00+00:00",
            field_sources={"roe": "yahoo"},
        )
    )

    snapshot = store.get_snapshot("AAPL")

    assert snapshot is not None
    assert snapshot.ticker == "AAPL"
