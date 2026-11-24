"""SQLite persistence: raw snapshots, computed analyses, manual overrides."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import list_catalog
from .models import SNAPSHOT_SCHEMA_VERSION, Fundamentals, Overrides

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ticker      TEXT PRIMARY KEY,
    fetched_at  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS overrides (
    ticker      TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news (
    ticker        TEXT NOT NULL,
    title         TEXT NOT NULL,
    publisher     TEXT,
    published_at  TEXT,
    link          TEXT,
    summary       TEXT,
    relevance     INTEGER NOT NULL DEFAULT 0,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (ticker, title)
);

CREATE TABLE IF NOT EXISTS llm_estimates (
    ticker       TEXT PRIMARY KEY,
    updated_at   TEXT NOT NULL,
    snapshot_at  TEXT NOT NULL,
    model        TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universe (
    ticker    TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    sector    TEXT,
    country   TEXT,
    added_at  TEXT NOT NULL
);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Thin, explicit SQLite wrapper. One short-lived connection per call."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._ready = False
        self._lock = threading.Lock()

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """A connection that is committed and closed.

        The sqlite3 connection context manager only handles the transaction,
        it does not close the connection, so it is wrapped here.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        # The application answers from a thread pool: two requests can write
        # at the same time and SQLite would refuse the second one.
        conn.execute("PRAGMA busy_timeout=10000")
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Create the schema on the first use, not when the object is built.

        Importing the application must not create or touch the database file:
        the module level app object is built at import time.
        """
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                # The journal mode is a property of the file, so it is set
                # once. Changing it needs an exclusive lock, which the busy
                # timeout does not wait for, so a concurrent request would
                # fail with "database is locked".
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            conn.executescript(SCHEMA)
            now = utcnow_iso()
            rows = [
                (item.ticker, item.name, item.sector, item.country, now)
                for item in list_catalog()
            ]
            conn.executemany(
                "INSERT INTO universe (ticker, name, sector, country, added_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, "
                "sector=excluded.sector, country=excluded.country",
                rows,
            )
            conn.commit()
            self._ready = True

    def init_schema(self) -> None:
        """Force the schema to exist (used by tooling and tests)."""
        with self._session() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------- snapshots
    def save_snapshot(self, fundamentals: Fundamentals) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO snapshots (ticker, fetched_at, provider, payload) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET fetched_at=excluded.fetched_at, "
                "provider=excluded.provider, payload=excluded.payload",
                (
                    fundamentals.ticker,
                    fundamentals.fetched_at,
                    fundamentals.provider,
                    fundamentals.model_dump_json(),
                ),
            )

    def get_snapshot(self, ticker: str) -> Fundamentals | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT payload FROM snapshots WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            # A snapshot written by an older version is not readable: it would
            # be missing fields the analysis needs. The caller refetches it.
            return None
        return Fundamentals.model_validate(payload)

    def snapshot_age_hours(self, ticker: str) -> float | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT fetched_at FROM snapshots WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        return (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0

    # ------------------------------------------------------------- overrides
    def save_overrides(self, ticker: str, overrides: Overrides) -> str:
        updated_at = utcnow_iso()
        with self._session() as conn:
            conn.execute(
                "INSERT INTO overrides (ticker, updated_at, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET updated_at=excluded.updated_at, "
                "payload=excluded.payload",
                (ticker, updated_at, overrides.model_dump_json()),
            )
        return updated_at

    def get_overrides(self, ticker: str) -> Overrides | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT payload FROM overrides WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        return Overrides.model_validate_json(row["payload"])

    def delete_overrides(self, ticker: str) -> bool:
        with self._session() as conn:
            cursor = conn.execute("DELETE FROM overrides WHERE ticker = ?", (ticker,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ news
    def save_news(self, ticker: str, items: list[dict[str, Any]]) -> str:
        fetched_at = utcnow_iso()
        rows = [
            (
                ticker,
                item.get("title", ""),
                item.get("publisher"),
                item.get("published_at"),
                item.get("link"),
                item.get("summary"),
                int(item.get("relevance", 0)),
                fetched_at,
            )
            for item in items
            if item.get("title")
        ]
        with self._session() as conn:
            if rows:
                # The feed is replaced, not accumulated: a story that Yahoo no
                # longer publishes would otherwise stay in the cache for good
                # and could still be shown to the model.
                conn.execute("DELETE FROM news WHERE ticker = ?", (ticker,))
            conn.executemany(
                "INSERT INTO news (ticker, title, publisher, published_at, link, summary, "
                "relevance, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker, title) DO UPDATE SET publisher=excluded.publisher, "
                "published_at=excluded.published_at, link=excluded.link, "
                "summary=excluded.summary, relevance=excluded.relevance, "
                "fetched_at=excluded.fetched_at",
                rows,
            )
        return fetched_at

    def get_news(self, ticker: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT title, publisher, published_at, link, summary, relevance FROM news "
                "WHERE ticker = ? ORDER BY relevance DESC, published_at DESC LIMIT ?",
                (ticker, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def news_age_hours(self, ticker: str) -> float | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT MAX(fetched_at) AS latest FROM news WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None or not row["latest"]:
            return None
        fetched = datetime.fromisoformat(row["latest"])
        return (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0

    # -------------------------------------------------------- llm estimates
    def save_llm_estimates(
        self,
        ticker: str,
        snapshot_at: str,
        model: str,
        values: dict[str, float],
        notes: dict[str, str] | None = None,
    ) -> str:
        updated_at = utcnow_iso()
        payload = {"values": values, "notes": notes or {}}
        with self._session() as conn:
            conn.execute(
                "INSERT INTO llm_estimates (ticker, updated_at, snapshot_at, model, payload) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET updated_at=excluded.updated_at, "
                "snapshot_at=excluded.snapshot_at, model=excluded.model, "
                "payload=excluded.payload",
                (ticker, updated_at, snapshot_at, model, json.dumps(payload)),
            )
        return updated_at

    def get_llm_estimates(self, ticker: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT snapshot_at, model, payload FROM llm_estimates WHERE ticker = ?",
                (ticker,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        payload["snapshot_at"] = row["snapshot_at"]
        payload["model"] = row["model"]
        return payload

    # -------------------------------------------------------------- universe
    def list_universe(self) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT ticker, name, sector, country FROM universe ORDER BY ticker"
            ).fetchall()
        return [dict(row) for row in rows]
