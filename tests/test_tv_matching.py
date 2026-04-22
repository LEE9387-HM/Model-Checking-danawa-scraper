from __future__ import annotations

from tv_db.db_manager import TVDatabaseManager, TVProductRecord
from tv_db.depreciation import depreciation_adjusted_price, year_proximity_weight
from tv_db.match_engine import (
    evaluate_competitiveness,
    find_candidates,
    find_samsung_model,
    rank_candidates,
    score_candidates,
)
from tv_db.tv_matching import analyze_target_model


def make_record(
    model_name: str,
    manufacturer: str,
    brand: str,
    price: int,
    year: int,
    size: float = 65.0,
    panel: str = "OLED",
    resolution: str = "4K UHD",
    refresh_rate: float = 120.0,
    other_specs: dict | None = None,
) -> TVProductRecord:
    return TVProductRecord(
        model_name=model_name,
        product_url=f"https://example.com/{model_name}",
        manufacturer=manufacturer,
        brand=brand,
        release_year=year,
        screen_size_inch=size,
        resolution=resolution,
        panel_type=panel,
        refresh_rate_hz=refresh_rate,
        operating_system="Tizen" if "Samsung" in brand else "webOS",
        current_price=price,
        review_count=100,
        other_specs=other_specs
        or {
            "hdr": "HDR10+",
            "smart_features": "AI",
            "speaker_output": 60,
            "dolby_atmos": True,
            "energy_rating": "2등급",
            "design_thinness": 25,
        },
        raw_specs={"model_name": model_name},
    )


def seed_db(tmp_path):
    manager = TVDatabaseManager(tmp_path / "tv.db")
    manager.initialize()
    records = [
        # Samsung target (QLED) — panel filter will restrict competitors to QLED
        make_record("QN65QN90D", "삼성전자", "삼성", 1800000, 2024, panel="QLED"),
        # QLED competitors — pass the panel filter
        make_record("KQ65QD80", "TCL", "TCL", 1300000, 2024, panel="QLED", refresh_rate=144.0),
        make_record("QLED65H1", "하이센스", "하이센스", 900000, 2024, panel="QLED"),
        make_record("QLED65P1", "필립스", "필립스", 1100000, 2024, panel="QLED"),
        make_record("QLED65X1", "이노스", "이노스", 750000, 2023, panel="QLED"),
        # OLED competitors — filtered out by panel filter when Samsung has QLED
        make_record("OLED65C4", "LG전자", "LG", 1700000, 2024),
        make_record("OLED65C3", "LG전자", "LG", 1500000, 2023),
        make_record("OLED55B4", "LG전자", "LG", 1200000, 2024, size=55.0),
        make_record("OLED65G5", "LG전자", "LG", 2200000, 2025),
    ]
    for record in records:
        manager.upsert_product(record, crawled_at="2026-04-22T00:00:00+00:00")
    return manager


def test_depreciation_helpers_apply_expected_year_logic():
    assert year_proximity_weight(2024, 2024) == 1.0
    assert year_proximity_weight(2024, 2025) == 0.7
    assert year_proximity_weight(2024, 2027) == 0.0
    assert round(depreciation_adjusted_price(1500000, 2024, 2023), 2) == round(1500000 / 0.85, 2)
    assert round(depreciation_adjusted_price(2200000, 2024, 2025), 2) == round(2200000 * 0.85, 2)


def test_find_and_rank_candidates_from_db(tmp_path):
    manager = seed_db(tmp_path)
    samsung = find_samsung_model(manager, "QN65QN90D")
    assert samsung is not None

    candidates = find_candidates(manager, samsung)
    # Panel filter: Samsung is QLED → only QLED competitors returned
    candidate_names = {c["model_name"] for c in candidates}
    assert "KQ65QD80" in candidate_names
    assert "QLED65H1" in candidate_names
    assert "QLED65P1" in candidate_names
    assert "OLED65C4" not in candidate_names  # OLED excluded by panel filter
    assert "OLED65C3" not in candidate_names  # OLED excluded by panel filter

    samsung_scored, candidates_scored = score_candidates(samsung, candidates)
    ranked = rank_candidates(samsung_scored, candidates_scored, top_n=3)
    assert len(ranked) == 3
    # All top-ranked should be QLED competitors (OLED filtered out)
    ranked_names = {r["model_name"] for r in ranked}
    assert ranked_names <= {"KQ65QD80", "QLED65H1", "QLED65P1", "QLED65X1"}
    manager.close()


def test_evaluate_competitiveness_uses_adjusted_prices(tmp_path):
    manager = seed_db(tmp_path)
    samsung = find_samsung_model(manager, "QN65QN90D")
    candidates = find_candidates(manager, samsung)
    samsung_scored, candidates_scored = score_candidates(samsung, candidates)
    ranked = rank_candidates(samsung_scored, candidates_scored, top_n=3)

    result = evaluate_competitiveness(samsung_scored, ranked)
    assert result["aggregate"]["overall_verdict"] in {
        "OVERPRICED",
        "SLIGHT_HIGH",
        "FAIR",
        "GOOD_VALUE",
        "COMPETITIVE",
    }
    assert len(result["matches"]) == 3
    assert result["matches"][0]["adjusted_cpi"] > 0
    manager.close()


def test_cli_analysis_returns_top_matches(tmp_path):
    manager = seed_db(tmp_path)
    manager.close()

    result = analyze_target_model("QN65QN90D", db_path=tmp_path / "tv.db", top_n=2)
    assert result["samsung"]["model_name"] == "QN65QN90D"
    assert len(result["matches"]) == 2
    assert result["matches"][0]["rank"] == 1
