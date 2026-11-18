"""SQLite persistence: raw snapshots, computed analyses, manual overrides."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import list_catalog
from .models import Fundamentals, Overrides

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ticker      TEXT PRIMARY KEY,
    fetched_at  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    ticker       TEXT PRIMARY KEY,
    computed_at  TEXT NOT NULL,
    payload      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS overrides (
    ticker      TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        self.seed_universe()

    def seed_universe(self) -> None:
        now = utcnow_iso()
        rows = [
            (item.ticker, item.name, item.sector, item.country, now)
            for item in list_catalog()
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO universe (ticker, name, sector, country, added_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, "
                "sector=excluded.sector, country=excluded.country",
                rows,
            )

    # ------------------------------------------------------------- snapshots
    def save_snapshot(self, fundamentals: Fundamentals) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM snapshots WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        return Fundamentals.model_validate_json(row["payload"])

    def snapshot_age_hours(self, ticker: str) -> float | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fetched_at FROM snapshots WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        return (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0

    # -------------------------------------------------------------- analyses
    def save_analysis(self, ticker: str, payload: dict[str, Any]) -> str:
        computed_at = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO analyses (ticker, computed_at, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET computed_at=excluded.computed_at, "
                "payload=excluded.payload",
                (ticker, computed_at, json.dumps(payload)),
            )
        return computed_at

    def get_analysis(self, ticker: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM analyses WHERE ticker = ?", (ticker,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    # ------------------------------------------------------------- overrides
    def save_overrides(self, ticker: str, overrides: Overrides) -> str:
        updated_at = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO overrides (ticker, updated_at, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET updated_at=excluded.updated_at, "
                "payload=excluded.payload",
                (ticker, updated_at, overrides.model_dump_json()),
            )
        return updated_at

    def get_overrides(self, ticker: str) -> Overrides | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM overrides WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        return Overrides.model_validate_json(row["payload"])

    def delete_overrides(self, ticker: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM overrides WHERE ticker = ?", (ticker,))
            return cursor.rowcount > 0

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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticker, name, sector, country FROM universe ORDER BY ticker"
            ).fetchall()
        return [dict(row) for row in rows]
