"""SQLite persistence: every alert, every outcome, every scan.

The scoring run at the end of the month reads nothing but this file, so an
alert is only considered sent once it is written here.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    item_id                  TEXT PRIMARY KEY,
    scanned_at               TEXT NOT NULL,
    title                    TEXT NOT NULL,
    url                      TEXT NOT NULL,
    category_id              TEXT,
    category_kind            TEXT,
    end_time                 TEXT,
    price_at_alert           REAL,
    currency                 TEXT,
    bid_count_at_alert       INTEGER,
    watch_count              INTEGER,
    seller_username          TEXT,
    seller_feedback_score    INTEGER,
    seller_feedback_pct      REAL,
    estimated_value          REAL NOT NULL,
    matched_card_count       INTEGER NOT NULL,
    unmatched_card_count     INTEGER NOT NULL,
    min_confidence           REAL NOT NULL,
    value_weighted_confidence REAL NOT NULL,
    flagged_low_confidence   INTEGER NOT NULL,
    vision_model             TEXT,
    vision_error             TEXT,
    identified_json          TEXT NOT NULL,
    images_json              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    item_id          TEXT PRIMARY KEY REFERENCES alerts(item_id),
    settled_at       TEXT NOT NULL,
    sold             INTEGER,
    final_price      REAL,
    final_bid_count  INTEGER,
    source           TEXT NOT NULL,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    candidates_seen  INTEGER DEFAULT 0,
    passed_filters   INTEGER DEFAULT 0,
    vision_calls     INTEGER DEFAULT 0,
    alerts_sent      INTEGER DEFAULT 0,
    errors           TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_end_time ON alerts(end_time);
CREATE INDEX IF NOT EXISTS idx_alerts_scanned_at ON alerts(scanned_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AlertRecord:
    item_id: str
    title: str
    url: str
    estimated_value: float
    min_confidence: float
    value_weighted_confidence: float
    flagged_low_confidence: bool
    end_time: str | None
    price_at_alert: float | None
    final_price: float | None = None
    sold: bool | None = None


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---- alerts -------------------------------------------------------

    def already_alerted(self, item_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alerts WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row is not None

    def record_alert(self, **fields) -> None:
        fields.setdefault("scanned_at", utcnow())
        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)
        with self.tx() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO alerts ({columns}) VALUES ({placeholders})",
                fields,
            )

    def alerts_between(self, start: str, end: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """
                SELECT a.*, o.sold, o.final_price, o.final_bid_count, o.source AS outcome_source
                FROM alerts a
                LEFT JOIN outcomes o ON o.item_id = a.item_id
                WHERE a.scanned_at >= ? AND a.scanned_at < ?
                ORDER BY a.scanned_at
                """,
                (start, end),
            )
        )

    def alerts_awaiting_settlement(self, ended_before: str) -> list[sqlite3.Row]:
        """Alerts whose auction has ended but which have no outcome row yet."""
        return list(
            self._conn.execute(
                """
                SELECT a.* FROM alerts a
                LEFT JOIN outcomes o ON o.item_id = a.item_id
                WHERE o.item_id IS NULL
                  AND a.end_time IS NOT NULL
                  AND a.end_time < ?
                ORDER BY a.end_time
                """,
                (ended_before,),
            )
        )

    # ---- outcomes -----------------------------------------------------

    def record_outcome(
        self,
        item_id: str,
        sold: bool | None,
        final_price: float | None,
        final_bid_count: int | None,
        source: str,
        notes: str | None = None,
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outcomes
                    (item_id, settled_at, sold, final_price, final_bid_count, source, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    utcnow(),
                    None if sold is None else int(sold),
                    final_price,
                    final_bid_count,
                    source,
                    notes,
                ),
            )

    # ---- scan runs ----------------------------------------------------

    def start_run(self) -> int:
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO scan_runs (started_at) VALUES (?)", (utcnow(),)
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        candidates_seen: int,
        passed_filters: int,
        vision_calls: int,
        alerts_sent: int,
        errors: list[str] | None = None,
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                """
                UPDATE scan_runs
                SET finished_at = ?, candidates_seen = ?, passed_filters = ?,
                    vision_calls = ?, alerts_sent = ?, errors = ?
                WHERE id = ?
                """,
                (
                    utcnow(),
                    candidates_seen,
                    passed_filters,
                    vision_calls,
                    alerts_sent,
                    json.dumps(errors or []),
                    run_id,
                ),
            )

    def run_stats(self, start: str, end: str) -> dict:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS runs,
                   COALESCE(SUM(candidates_seen), 0) AS candidates_seen,
                   COALESCE(SUM(passed_filters), 0) AS passed_filters,
                   COALESCE(SUM(vision_calls), 0) AS vision_calls,
                   COALESCE(SUM(alerts_sent), 0) AS alerts_sent
            FROM scan_runs
            WHERE started_at >= ? AND started_at < ?
            """,
            (start, end),
        ).fetchone()
        return dict(row) if row else {}
