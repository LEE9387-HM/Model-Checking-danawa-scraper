"""
Export the TV SQLite database to Cloudflare D1-compatible SQL.

Usage:
    python scripts/export_to_d1.py --db backend/tv_db/tv_products.db --out scripts/d1_import.sql
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def export_table(conn: sqlite3.Connection, table_name: str, columns: list[str]) -> list[str]:
    query = f"SELECT {', '.join(columns)} FROM {table_name} ORDER BY id"
    rows = conn.execute(query).fetchall()
    statements = []
    for row in rows:
        values = ", ".join(sql_literal(row[column]) for column in columns)
        statements.append(
            f"INSERT OR REPLACE INTO {table_name} ({', '.join(columns)}) VALUES ({values});"
        )
    return statements


def export(db_path: str, out_path: str) -> None:
    source_uri = f"file:{Path(db_path).as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(source_uri, uri=True)
    conn.row_factory = sqlite3.Row

    product_columns = [
        "id",
        "model_name",
        "product_url",
        "manufacturer",
        "brand",
        "release_year",
        "screen_size_inch",
        "resolution",
        "panel_type",
        "refresh_rate_hz",
        "operating_system",
        "current_price",
        "review_count",
        "other_specs",
        "raw_specs",
        "source",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
        "score_total",
        "score_breakdown",
    ]
    price_history_columns = [
        "id",
        "product_id",
        "price",
        "review_count",
        "crawled_at",
        "source",
    ]

    lines = export_table(conn, "tv_products", product_columns)
    lines.extend(export_table(conn, "tv_price_history", price_history_columns))

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Exported {len(lines)} rows to {out_path}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="backend/tv_db/tv_products.db")
    parser.add_argument("--out", default="scripts/d1_import.sql")
    args = parser.parse_args()
    export(args.db, args.out)


if __name__ == "__main__":
    main()
