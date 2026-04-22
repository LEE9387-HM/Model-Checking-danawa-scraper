from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class TVProductRecord:
    model_name: str
    product_url: str
    manufacturer: str
    brand: str
    release_year: int | None
    screen_size_inch: float | None
    resolution: str | None
    panel_type: str | None
    refresh_rate_hz: float | None
    operating_system: str | None
    current_price: int
    review_count: int
    other_specs: dict[str, Any]
    raw_specs: dict[str, Any]
    source: str = "danawa"


class TVDatabaseManager:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tv_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL UNIQUE,
                product_url TEXT NOT NULL,
                manufacturer TEXT NOT NULL DEFAULT '',
                brand TEXT NOT NULL DEFAULT '',
                release_year INTEGER,
                screen_size_inch REAL,
                resolution TEXT,
                panel_type TEXT,
                refresh_rate_hz REAL,
                operating_system TEXT,
                current_price INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                other_specs TEXT NOT NULL DEFAULT '{}',
                raw_specs TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT 'danawa',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tv_price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                crawled_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'danawa',
                FOREIGN KEY(product_id) REFERENCES tv_products(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tv_products_release_year
                ON tv_products(release_year);

            CREATE INDEX IF NOT EXISTS idx_tv_price_history_product_id
                ON tv_price_history(product_id);

            CREATE INDEX IF NOT EXISTS idx_tv_price_history_crawled_at
                ON tv_price_history(crawled_at);
            """
        )
        self.connection.commit()

    def upsert_product(self, record: TVProductRecord, crawled_at: str | None = None) -> int:
        timestamp = crawled_at or utc_now_iso()
        current = self.connection.execute(
            "SELECT id, first_seen_at FROM tv_products WHERE model_name = ?",
            (record.model_name,),
        ).fetchone()

        payload = (
            record.product_url,
            record.manufacturer,
            record.brand,
            record.release_year,
            record.screen_size_inch,
            record.resolution,
            record.panel_type,
            record.refresh_rate_hz,
            record.operating_system,
            max(0, int(record.current_price)),
            max(0, int(record.review_count)),
            json.dumps(record.other_specs, ensure_ascii=False, sort_keys=True),
            json.dumps(record.raw_specs, ensure_ascii=False, sort_keys=True),
            record.source,
            timestamp,
            timestamp,
        )

        if current is None:
            cursor = self.connection.execute(
                """
                INSERT INTO tv_products (
                    model_name, product_url, manufacturer, brand, release_year,
                    screen_size_inch, resolution, panel_type, refresh_rate_hz,
                    operating_system, current_price, review_count, other_specs,
                    raw_specs, source, first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record.model_name, *payload[:-2], timestamp, timestamp, payload[-2], payload[-1]),
            )
            product_id = int(cursor.lastrowid)
        else:
            product_id = int(current["id"])
            self.connection.execute(
                """
                UPDATE tv_products
                SET product_url = ?, manufacturer = ?, brand = ?, release_year = ?,
                    screen_size_inch = ?, resolution = ?, panel_type = ?, refresh_rate_hz = ?,
                    operating_system = ?, current_price = ?, review_count = ?, other_specs = ?,
                    raw_specs = ?, source = ?, last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (*payload, product_id),
            )

        self.connection.execute(
            """
            INSERT INTO tv_price_history (product_id, price, review_count, crawled_at, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                product_id,
                max(0, int(record.current_price)),
                max(0, int(record.review_count)),
                timestamp,
                record.source,
            ),
        )
        self.connection.commit()
        return product_id

    def fetch_products(self) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT model_name, brand, release_year, current_price, review_count
            FROM tv_products
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        return list(rows)

    def fetch_summary_counts(self) -> dict[str, int]:
        product_count = self.connection.execute(
            "SELECT COUNT(*) FROM tv_products"
        ).fetchone()[0]
        history_count = self.connection.execute(
            "SELECT COUNT(*) FROM tv_price_history"
        ).fetchone()[0]
        return {
            "tv_products": int(product_count),
            "tv_price_history": int(history_count),
        }
