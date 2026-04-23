"""
Precompute TV product scores into the SQLite TV database.

Usage:
    python scripts/compute_scores.py --db backend/tv_db/tv_products.db
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from pathlib import Path
from typing import Any


TV_RULES_PATH = Path(__file__).resolve().parent.parent / "backend" / "rules" / "tv.json"
TV_PRODUCTS_COLUMNS = [
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
TV_PRICE_HISTORY_COLUMNS = [
    "id",
    "product_id",
    "price",
    "review_count",
    "crawled_at",
    "source",
]


def load_tv_rules() -> dict[str, Any]:
    with TV_RULES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def open_source_connection(db_path: str) -> sqlite3.Connection:
    source_uri = f"file:{Path(db_path).as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(source_uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def create_output_database(temp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(temp_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.executescript(
        """
        CREATE TABLE tv_products (
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
            updated_at TEXT NOT NULL,
            score_total REAL DEFAULT 0.0,
            score_breakdown TEXT DEFAULT '{}'
        );

        CREATE TABLE tv_price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            crawled_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'danawa',
            FOREIGN KEY(product_id) REFERENCES tv_products(id) ON DELETE CASCADE
        );

        CREATE INDEX idx_tv_price_history_crawled_at
            ON tv_price_history(crawled_at);
        CREATE INDEX idx_tv_price_history_product_id
            ON tv_price_history(product_id);
        CREATE INDEX idx_tv_products_release_year
            ON tv_products(release_year);
        """
    )
    return conn


def safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_lower(value: Any) -> str:
    return normalize_text(value).lower()


def is_truthy_text(value: Any) -> bool:
    text = normalize_lower(value)
    if not text:
        return False
    return text not in {"x", "미지원", "없음", "false", "0", "n", "no"}


def first_number(text: str) -> float | None:
    digits = []
    dot_seen = False
    started = False
    for char in text:
        if char.isdigit():
            digits.append(char)
            started = True
        elif char == "." and started and not dot_seen:
            digits.append(char)
            dot_seen = True
        elif started:
            break
    if not digits:
        return None
    number_text = "".join(digits)
    if number_text == ".":
        return None
    return float(number_text)


def extract_watts(value: Any) -> float | None:
    text = normalize_text(value)
    if "W" not in text and "w" not in text:
        return None
    return first_number(text)


def extract_thickness_mm(value: Any) -> float | None:
    text = normalize_text(value)
    if "mm" not in text.lower():
        return None
    candidates = []
    token = []
    for char in text:
        if char.isdigit() or char == ".":
            token.append(char)
        else:
            if token:
                try:
                    candidates.append(float("".join(token)))
                except ValueError:
                    pass
                token = []
    if token:
        try:
            candidates.append(float("".join(token)))
        except ValueError:
            pass
    realistic = [number for number in candidates if 1.0 <= number <= 250.0]
    if not realistic:
        return None
    return min(realistic)


def detect_hdr(other_specs: dict[str, Any]) -> str:
    found_hdr = False
    for key, value in other_specs.items():
        key_text = normalize_text(key)
        value_text = normalize_text(value)
        merged = f"{key_text} {value_text}".lower()
        if "돌비비전" in merged or "dolby vision" in merged:
            return "돌비비전"
        if "hdr10+" in merged:
            return "HDR10+"
        if "hdr10" in merged:
            found_hdr = True
        elif "hdr" in merged and is_truthy_text(value_text):
            found_hdr = True
    return "HDR10" if found_hdr else "미지원"


def detect_smart_features(other_specs: dict[str, Any], operating_system: Any) -> str:
    os_text = normalize_lower(operating_system)
    if any(name in os_text for name in ("tizen", "webos", "google tv", "android", "fire tv", "roku")):
        return "풀스마트"

    seen_smart = False
    for key, value in other_specs.items():
        key_text = normalize_lower(key)
        value_text = normalize_lower(value)
        merged = f"{key_text} {value_text}"
        if any(name in merged for name in ("tizen", "webos", "google tv", "android", "fire tv", "roku")):
            return "풀스마트"
        if "ai" in merged and "스마트" in merged:
            return "AI"
        if "스마트" in key_text or "smart" in key_text:
            if is_truthy_text(value_text) or value_text:
                seen_smart = True
        if key_text in {"운영체제", "os"} and value_text:
            return "풀스마트"

    if seen_smart:
        return "기본"
    return "미지원"


def detect_speaker_output(other_specs: dict[str, Any]) -> float | None:
    candidate_keys = (
        "출력",
        "스피커",
        "사운드",
        "오디오출력",
        "speaker",
        "audio",
        "sound",
    )
    for key, value in other_specs.items():
        key_text = normalize_lower(key)
        if any(token in key_text for token in candidate_keys):
            watts = extract_watts(value)
            if watts is not None:
                return watts

    for value in other_specs.values():
        watts = extract_watts(value)
        if watts is not None:
            return watts
    return None


def detect_dolby_atmos(other_specs: dict[str, Any]) -> bool:
    for key, value in other_specs.items():
        merged = f"{normalize_lower(key)} {normalize_lower(value)}"
        if "돌비애트모스" in merged or "dolby atmos" in merged:
            return is_truthy_text(value) or "돌비애트모스" in normalize_lower(key)
    return False


def detect_energy_rating(other_specs: dict[str, Any]) -> str | None:
    for key, value in other_specs.items():
        key_text = normalize_lower(key)
        value_text = normalize_text(value)
        if "에너지효율" in key_text or "energy" in key_text:
            for grade in ("1등급", "2등급", "3등급", "4등급", "5등급"):
                if grade in value_text:
                    return grade
    return None


def detect_design_thinness(other_specs: dict[str, Any]) -> float | None:
    preferred_keys = (
        "두께",
        "깊이",
        "크기",
        "사이즈",
        "지원",
        "dimensions",
        "size",
    )
    for key, value in other_specs.items():
        key_text = normalize_lower(key)
        if any(token in key_text for token in preferred_keys):
            thickness = extract_thickness_mm(value)
            if thickness is not None:
                return thickness
    return None


def row_to_spec(row: dict[str, Any]) -> dict[str, Any]:
    other_specs = safe_json_loads(row.get("other_specs"))
    return {
        "refresh_rate": row.get("refresh_rate_hz"),
        "hdr": detect_hdr(other_specs),
        "smart_features": detect_smart_features(other_specs, row.get("operating_system")),
        "speaker_output": detect_speaker_output(other_specs),
        "dolby_atmos": detect_dolby_atmos(other_specs),
        "energy_rating": detect_energy_rating(other_specs),
        "design_thinness": detect_design_thinness(other_specs),
    }


def score_spec(value: Any, spec_def: dict[str, Any], all_values: list[Any]) -> float:
    if value is None:
        return 0.0

    direction = spec_def.get("direction", "higher_better")
    if "levels" in spec_def:
        levels = spec_def["levels"]
        key = normalize_text(value)
        if key in levels:
            return float(levels[key])
        try:
            numeric_levels = {float(level_key): float(level_value) for level_key, level_value in levels.items()}
            number = float(value)
        except (TypeError, ValueError):
            return 0.0

        if direction == "higher_better":
            valid = [(level_key, score) for level_key, score in numeric_levels.items() if level_key <= number]
            return float(max(valid, key=lambda pair: pair[0])[1]) if valid else 0.0
        if direction == "lower_better":
            valid = [(level_key, score) for level_key, score in numeric_levels.items() if level_key >= number]
            return float(min(valid, key=lambda pair: pair[0])[1]) if valid else 0.0
        return 0.0

    if direction == "boolean":
        return float(spec_def.get("true_value", 10.0)) if bool(value) else float(spec_def.get("false_value", 0.0))

    numeric_values = []
    for item in all_values:
        try:
            if item is not None:
                numeric_values.append(float(item))
        except (TypeError, ValueError):
            continue

    if not numeric_values:
        return 0.0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    minimum = min(numeric_values)
    maximum = max(numeric_values)
    if math.isclose(maximum, minimum):
        return 5.0

    normalized = (number - minimum) / (maximum - minimum)
    if direction == "lower_better":
        normalized = 1.0 - normalized
    return round(normalized * 10.0, 4)


def score_pool(models: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    grading_specs = rules["grading_specs"]
    pool_specs = [model["spec"] for model in models]
    scored = []
    for model in models:
        breakdown: dict[str, float] = {}
        total_score = 0.0
        for spec_name, spec_def in grading_specs.items():
            all_values = [spec.get(spec_name) for spec in pool_specs]
            raw_score = score_spec(model["spec"].get(spec_name), spec_def, all_values)
            breakdown[spec_name] = round(raw_score, 2)
            total_score += raw_score * float(spec_def["weight"]) * 10.0
        scored.append(
            {
                "id": model["id"],
                "score_total": round(total_score, 2),
                "score_breakdown": breakdown,
            }
        )
    return scored


def compute_all_scores(db_path: str) -> None:
    rules = load_tv_rules()
    source_conn = open_source_connection(db_path)
    rows = source_conn.execute(
        """
        SELECT *
        FROM tv_products
        ORDER BY id
        """
    ).fetchall()

    models = []
    for row in rows:
        row_dict = dict(row)
        models.append({"id": row_dict["id"], "spec": row_to_spec(row_dict)})

    print(f"Scoring {len(models)} products...")
    scored_rows = score_pool(models, rules)

    score_map = {
        item["id"]: (
            item["score_total"],
            json.dumps(item["score_breakdown"], ensure_ascii=False, separators=(",", ":")),
        )
        for item in scored_rows
    }
    price_history_rows = source_conn.execute(
        """
        SELECT *
        FROM tv_price_history
        ORDER BY id
        """
    ).fetchall()
    source_conn.close()

    db_file = Path(db_path)
    temp_db = db_file.with_name(f"{db_file.name}.scored.{os.getpid()}.tmp")
    output_conn = create_output_database(temp_db)

    output_conn.executemany(
        """
        INSERT INTO tv_products (
            id, model_name, product_url, manufacturer, brand, release_year,
            screen_size_inch, resolution, panel_type, refresh_rate_hz,
            operating_system, current_price, review_count, other_specs,
            raw_specs, source, first_seen_at, last_seen_at, created_at,
            updated_at, score_total, score_breakdown
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            tuple(
                list(dict(row)[column] for column in TV_PRODUCTS_COLUMNS[:-2])
                + list(score_map.get(row["id"], (0.0, "{}")))
            )
            for row in rows
        ],
    )

    output_conn.executemany(
        """
        INSERT INTO tv_price_history (
            id, product_id, price, review_count, crawled_at, source
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            tuple(dict(row)[column] for column in TV_PRICE_HISTORY_COLUMNS)
            for row in price_history_rows
        ],
    )
    output_conn.commit()
    output_conn.close()

    os.replace(temp_db, db_file)
    print(f"Done. {len(scored_rows)} products scored.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="backend/tv_db/tv_products.db")
    args = parser.parse_args()
    compute_all_scores(args.db)


if __name__ == "__main__":
    main()
