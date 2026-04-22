from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tv_db.db_manager import TVDatabaseManager
from tv_db.match_engine import (
    evaluate_competitiveness,
    find_candidates,
    find_samsung_model,
    rank_candidates,
    score_candidates,
)

DEFAULT_DB_PATH = CURRENT_DIR / "tv_products.db"


def analyze_target_model(
    target: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    top_n: int = 5,
) -> dict[str, Any]:
    db = TVDatabaseManager(db_path)
    try:
        samsung_row = find_samsung_model(db, target)
        if samsung_row is None:
            raise ValueError(f"Samsung TV model not found for query: {target}")

        candidate_rows = find_candidates(db, samsung_row)
        samsung_scored, candidates_scored = score_candidates(samsung_row, candidate_rows)
        top_candidates = rank_candidates(samsung_scored, candidates_scored, top_n=top_n)
        return evaluate_competitiveness(samsung_scored, top_candidates)
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Samsung TV competitor matching CLI")
    parser.add_argument("--target", required=True, help="Samsung model name or partial query")
    parser.add_argument("--top", type=int, default=5, help="Number of competitor matches to return")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to tv_products SQLite database")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = analyze_target_model(args.target, db_path=args.db, top_n=args.top)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    samsung = result["samsung"]
    aggregate = result["aggregate"]
    print(f"Samsung: {samsung['model_name']} ({samsung['year']})")
    print(f"Price: {samsung['price']:,} KRW | Score: {samsung['score']}")
    print(
        f"Weighted CPI: {aggregate['weighted_cpi']} | Verdict: {aggregate['overall_verdict']}"
    )
    print(aggregate["summary"])
    print()
    for match in result["matches"]:
        print(
            f"#{match['rank']} {match['brand']} {match['model_name']} "
            f"({match['year']}) | price={match['price']:,} | score={match['score']} "
            f"| match={match['match_score']} | adjusted_cpi={match['adjusted_cpi']} "
            f"| verdict={match['verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
