from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from price_intelligence import get_price_adequacy_verdict
from scoring import load_rules, score_pool
from similarity import cosine_similarity
from tv_db.db_manager import TVDatabaseManager
from tv_db.depreciation import MAX_YEAR_DELTA, depreciation_adjusted_price, year_proximity_weight

DEFAULT_SIZE_TOLERANCE = 3.0


def row_to_spec(row: dict[str, Any]) -> dict[str, Any]:
    """Map a DB row into the scoring.py TV spec schema."""
    other = json.loads(row.get("other_specs") or "{}")
    return {
        "refresh_rate": row.get("refresh_rate_hz"),
        "hdr": other.get("hdr"),
        "smart_features": other.get("smart_features") or other.get("operating_system"),
        "speaker_output": other.get("speaker_output"),
        "dolby_atmos": other.get("dolby_atmos", False),
        "energy_rating": other.get("energy_rating"),
        "design_thinness": other.get("design_thinness"),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def find_samsung_model(db: TVDatabaseManager, query: str) -> dict[str, Any] | None:
    """
    Resolve a Samsung target model by partial model-name match.
    """
    pattern = f"%{query.strip()}%"
    row = db.connection.execute(
        """
        SELECT *
        FROM tv_products
        WHERE model_name LIKE ?
          AND (
              manufacturer IN ('삼성전자', 'Samsung', 'SAMSUNG')
              OR brand LIKE '%삼성%'
              OR brand LIKE '%Samsung%'
          )
        ORDER BY current_price DESC, review_count DESC, id ASC
        LIMIT 1
        """,
        (pattern,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def find_candidates(
    db: TVDatabaseManager,
    samsung_row: dict[str, Any],
    size_tolerance: float = DEFAULT_SIZE_TOLERANCE,
    max_year_delta: int = MAX_YEAR_DELTA,
    include_null_panel: bool = True,
) -> list[dict[str, Any]]:
    """
    Find non-Samsung competitors that are close in size, resolution, and year.
    Panel type must match when the Samsung model has a known panel type.
    """
    target_size = samsung_row.get("screen_size_inch")
    target_resolution = samsung_row.get("resolution")
    target_year = samsung_row.get("release_year")

    if target_size is None or target_resolution is None or target_year is None:
        return []

    target_panel = (samsung_row.get("panel_type") or "").strip().lower()
    brand_exclusion = (
        "AND manufacturer NOT IN ('삼성전자', 'Samsung') "
        "AND brand NOT LIKE '%삼성%' "
        "AND brand NOT LIKE '%Samsung%'"
    )

    if target_panel:
        # 패널 완전 일치 필터 적용
        if include_null_panel:
            panel_clause = "AND (LOWER(TRIM(panel_type)) = ? OR panel_type IS NULL OR panel_type = '')"
        else:
            panel_clause = "AND LOWER(TRIM(panel_type)) = ?"
        query = f"""
        SELECT *
        FROM tv_products
        WHERE current_price > 0
          AND ABS(screen_size_inch - ?) <= ?
          AND resolution = ?
          AND ABS(release_year - ?) <= ?
          {panel_clause}
          {brand_exclusion}
        ORDER BY ABS(screen_size_inch - ?) ASC, ABS(release_year - ?) ASC, current_price DESC
        """
        params = (
            target_size, size_tolerance, target_resolution,
            target_year, max_year_delta, target_panel,
            target_size, target_year,
        )
    else:
        # 삼성 모델 패널 정보 없으면 기존 로직 유지
        query = """
        SELECT *
        FROM tv_products
        WHERE current_price > 0
          AND ABS(screen_size_inch - ?) <= ?
          AND resolution = ?
          AND ABS(release_year - ?) <= ?
          AND manufacturer NOT IN ('삼성전자', 'Samsung')
          AND brand NOT LIKE '%삼성%'
          AND brand NOT LIKE '%Samsung%'
        ORDER BY ABS(screen_size_inch - ?) ASC, ABS(release_year - ?) ASC, current_price DESC
        """
        params = (
            target_size, size_tolerance, target_resolution,
            target_year, max_year_delta,
            target_size, target_year,
        )

    rows = db.connection.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def score_candidates(
    samsung_row: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Score the Samsung target and its competitors on a shared relative pool.
    """
    models = [
        {"row": samsung_row, "spec": row_to_spec(samsung_row)},
        *({"row": row, "spec": row_to_spec(row)} for row in candidate_rows),
    ]
    scored_pool = score_pool("tv", models)

    samsung_scored = {**samsung_row, "score": scored_pool[0]["score"]}
    candidates_scored = [
        {**candidate_rows[index], "score": scored_pool[index + 1]["score"]}
        for index in range(len(candidate_rows))
    ]
    return samsung_scored, candidates_scored


def _spec_similarity(
    samsung_scored: dict[str, Any],
    candidate_scored: dict[str, Any],
    rules: dict[str, Any],
) -> float:
    grading_specs = rules["grading_specs"]
    samsung_breakdown = samsung_scored["score"]["breakdown"]
    candidate_breakdown = candidate_scored["score"]["breakdown"]
    samsung_vec = [
        float(samsung_breakdown.get(name, 0.0)) * float(spec_def.get("weight", 1.0))
        for name, spec_def in grading_specs.items()
    ]
    candidate_vec = [
        float(candidate_breakdown.get(name, 0.0)) * float(spec_def.get("weight", 1.0))
        for name, spec_def in grading_specs.items()
    ]
    return cosine_similarity(samsung_vec, candidate_vec)


def rank_candidates(
    samsung_scored: dict[str, Any],
    candidates_scored: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """
    Rank candidates by combined spec, year, size, and panel compatibility.
    """
    rules = load_rules("tv")
    samsung_size = samsung_scored.get("screen_size_inch") or 0.0
    samsung_year = samsung_scored.get("release_year") or 0
    samsung_panel = (samsung_scored.get("panel_type") or "").strip().lower()

    ranked: list[dict[str, Any]] = []
    for candidate in candidates_scored:
        candidate_size = candidate.get("screen_size_inch") or 0.0
        candidate_year = candidate.get("release_year") or 0
        year_weight = year_proximity_weight(samsung_year, candidate_year)
        if year_weight <= 0:
            continue

        size_gap = abs(candidate_size - samsung_size)
        size_closeness = max(0.0, 1.0 - (size_gap / DEFAULT_SIZE_TOLERANCE))
        panel_type_bonus = 1.0 if samsung_panel and samsung_panel == (candidate.get("panel_type") or "").strip().lower() else 0.0
        spec_cosine_similarity = _spec_similarity(samsung_scored, candidate, rules)
        match_score = round(
            spec_cosine_similarity * 0.40
            + year_weight * 0.35
            + size_closeness * 0.15
            + panel_type_bonus * 0.10,
            4,
        )

        ranked.append(
            {
                **candidate,
                "match_score": match_score,
                "year_delta": candidate_year - samsung_year,
                "year_proximity": year_weight,
                "size_closeness": round(size_closeness, 4),
                "panel_type_bonus": panel_type_bonus,
                "spec_cosine_similarity": spec_cosine_similarity,
            }
        )

    ranked.sort(key=lambda item: (item["match_score"], item["score"]["total_score"], -item["current_price"]), reverse=True)
    return ranked[:top_n]


def _aggregate_verdict(weighted_cpi: float) -> str:
    if weighted_cpi > 115:
        return "OVERPRICED"
    if weighted_cpi > 105:
        return "SLIGHT_HIGH"
    if weighted_cpi > 95:
        return "FAIR"
    if weighted_cpi > 85:
        return "GOOD_VALUE"
    return "COMPETITIVE"


def _extract_specs(row: dict[str, Any]) -> dict[str, Any]:
    """Extract key display specs from a DB row."""
    other = json.loads(row.get("other_specs") or "{}")
    return {
        "screen_size_inch": row.get("screen_size_inch"),
        "panel_type": row.get("panel_type"),
        "resolution": row.get("resolution"),
        "refresh_rate_hz": row.get("refresh_rate_hz"),
        "hdr": other.get("hdr"),
    }


def evaluate_competitiveness(
    samsung_scored: dict[str, Any],
    top_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate Samsung pricing against the ranked competitor set.
    """
    samsung_price = int(samsung_scored.get("current_price") or 0)
    samsung_total_score = float(samsung_scored["score"]["total_score"])
    samsung_year = int(samsung_scored.get("release_year") or 0)

    matches: list[dict[str, Any]] = []
    total_weight = 0.0
    weighted_cpi_total = 0.0
    for index, candidate in enumerate(top_candidates, start=1):
        candidate_price = int(candidate.get("current_price") or 0)
        candidate_score = float(candidate["score"]["total_score"])
        candidate_year = int(candidate.get("release_year") or 0)
        adjusted_price = depreciation_adjusted_price(candidate_price, samsung_year, candidate_year)
        raw_cpi = round((samsung_price / candidate_price) * 100, 2) if candidate_price else 0.0
        adjusted_cpi = round((samsung_price / adjusted_price) * 100, 2) if adjusted_price else 0.0
        score_diff = round(samsung_total_score - candidate_score, 2)
        verdict = get_price_adequacy_verdict(adjusted_cpi, score_diff)
        match_weight = float(candidate.get("match_score") or 0.0)

        weighted_cpi_total += adjusted_cpi * match_weight
        total_weight += match_weight
        matches.append(
            {
                "rank": index,
                "model_name": candidate.get("model_name"),
                "brand": candidate.get("brand"),
                "year": candidate_year,
                "price": candidate_price,
                "score": candidate_score,
                "year_delta": candidate.get("year_delta"),
                "match_score": match_weight,
                "spec_cosine_similarity": candidate.get("spec_cosine_similarity"),
                "size_closeness": candidate.get("size_closeness"),
                "year_proximity": candidate.get("year_proximity"),
                "panel_type_bonus": candidate.get("panel_type_bonus"),
                "raw_cpi": raw_cpi,
                "adjusted_price": round(adjusted_price, 2),
                "adjusted_cpi": adjusted_cpi,
                "score_diff": score_diff,
                "verdict": verdict["verdict"],
                "verdict_reason": verdict["reason"],
                "specs": _extract_specs(candidate),
            }
        )

    weighted_cpi = round(weighted_cpi_total / total_weight, 2) if total_weight else 0.0
    overall_verdict = _aggregate_verdict(weighted_cpi) if matches else "NO_MATCH"
    summary = (
        f"{samsung_scored['model_name']} weighted CPI is {weighted_cpi}, "
        f"classified as {overall_verdict} across {len(matches)} comparable competitors."
        if matches
        else "No comparable competitors were found in the TV database."
    )
    return {
        "samsung": {
            "model_name": samsung_scored.get("model_name"),
            "price": samsung_price,
            "score": samsung_total_score,
            "year": samsung_year,
            "specs": _extract_specs(samsung_scored),
        },
        "matches": matches,
        "aggregate": {
            "weighted_cpi": weighted_cpi,
            "overall_verdict": overall_verdict,
            "summary": summary,
        },
    }
