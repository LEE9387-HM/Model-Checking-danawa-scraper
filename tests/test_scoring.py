"""
test_scoring.py — 채점 엔진 단위 테스트
"""
import json
from pathlib import Path

import pytest

from spec_parser import parse_spec, PARSERS
from scoring import score_model, score_pool, load_rules


RULES_DIR = Path(__file__).parent.parent / "backend" / "rules"
ALL_CATEGORIES = list(PARSERS.keys())


# ─── 룰셋 무결성 ─────────────────────────────────────────────────────────────

class TestRulesIntegrity:
    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_weight_sum_is_one(self, category):
        """모든 카테고리의 grading_spec 가중치 합이 1.0이어야 한다."""
        rules = load_rules(category)
        total_weight = sum(
            v["weight"] for v in rules["grading_specs"].values()
        )
        assert abs(total_weight - 1.0) < 1e-6, (
            f"{category}: 가중치 합 = {total_weight} (기대값 1.0)"
        )

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_grading_spec_keys_match_parser(self, category):
        """grading_spec 키가 파서 출력 키에 모두 포함되어야 한다."""
        rules = load_rules(category)
        parsed = PARSERS[category]({})
        grading_keys = set(rules["grading_specs"].keys())
        parsed_keys  = set(parsed.keys())
        missing = grading_keys - parsed_keys
        assert not missing, f"{category}: 파서에 없는 키 → {missing}"

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_rules_file_exists(self, category):
        assert (RULES_DIR / f"{category}.json").exists()


# ─── 파서 동작 ───────────────────────────────────────────────────────────────

class TestSpecParser:
    def test_tv_screen_size(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["screen_size"] == 65

    def test_tv_resolution_4k(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["resolution"] == "4K UHD"

    def test_tv_refresh_rate(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["refresh_rate"] == 120.0

    def test_tv_hdr_level(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["hdr"] == "HDR10+"

    def test_tv_dolby_atmos_bool(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["dolby_atmos"] is True

    def test_tv_energy_rating_normalized(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["energy_rating"] == "2등급"

    def test_tv_release_year(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["release_year"] == 2024

    def test_tv_meta_brand(self, tv_raw):
        spec = parse_spec("tv", tv_raw)
        assert spec["brand"] == "삼성전자"

    def test_washer_steam_bool(self, washer_raw):
        spec = parse_spec("washer", washer_raw)
        assert spec["steam"] is True

    def test_washer_spin_rpm(self, washer_raw):
        spec = parse_spec("washer", washer_raw)
        assert spec["spin_rpm"] == 1400.0

    def test_monitor_resolution_qhd(self, monitor_raw):
        spec = parse_spec("monitor", monitor_raw)
        assert spec["resolution"] == "QHD"

    def test_monitor_pivot_bool(self, monitor_raw):
        spec = parse_spec("monitor", monitor_raw)
        assert spec["pivot"] is True

    def test_unknown_category_returns_raw(self):
        raw = {"foo": "bar", "__price__": "0", "__review_count__": "0"}
        result = parse_spec("unknown_cat", raw)
        assert result["foo"] == "bar"


# ─── 채점 엔진 ───────────────────────────────────────────────────────────────

class TestScoreModel:
    def test_total_score_range(self, tv_spec):
        result = score_model("tv", tv_spec)
        assert 0 <= result["total_score"] <= 100

    def test_breakdown_keys_match_grading_specs(self, tv_spec):
        result = score_model("tv", tv_spec)
        rules  = load_rules("tv")
        assert set(result["breakdown"].keys()) == set(rules["grading_specs"].keys())

    def test_breakdown_values_range(self, tv_spec):
        result = score_model("tv", tv_spec)
        for k, v in result["breakdown"].items():
            assert 0 <= v <= 10, f"{k}={v} out of range"

    def test_category_field_in_result(self, tv_spec):
        result = score_model("tv", tv_spec)
        assert result["category"] == "tv"

    def test_higher_refresh_rate_higher_score(self):
        """주사율 높을수록 더 높은 점수 (Min-Max 비교)."""
        raw60  = {"주사율": "60Hz",  "HDR": "미지원", "__price__": "0", "__review_count__": "0", "__brand__": ""}
        raw120 = {"주사율": "120Hz", "HDR": "미지원", "__price__": "0", "__review_count__": "0", "__brand__": ""}
        s60  = score_model("tv", parse_spec("tv", raw60),  pool=[parse_spec("tv", raw60),  parse_spec("tv", raw120)])
        s120 = score_model("tv", parse_spec("tv", raw120), pool=[parse_spec("tv", raw60),  parse_spec("tv", raw120)])
        assert s120["breakdown"]["refresh_rate"] > s60["breakdown"]["refresh_rate"]

    def test_score_pool_relative_order(self):
        """score_pool은 같은 풀 안에서 상대 순위를 유지해야 한다."""
        best = {"spec": parse_spec("washer", {
            "세탁 용량": "24kg", "형태": "드럼", "에너지소비효율": "1등급",
            "탈수 회전수": "1600RPM", "세탁코스": "30코스", "스팀": "지원",
            "소음": "40dB", "스마트 기능": "AI",
            "__price__": "0", "__review_count__": "0", "__brand__": "",
        })}
        worst = {"spec": parse_spec("washer", {
            "세탁 용량": "12kg", "형태": "통돌이", "에너지소비효율": "5등급",
            "탈수 회전수": "700RPM", "세탁코스": "5코스", "스팀": "미지원",
            "소음": "70dB", "스마트 기능": "",
            "__price__": "0", "__review_count__": "0", "__brand__": "",
        })}
        results = score_pool("washer", [best, worst])
        assert results[0]["score"]["total_score"] > results[1]["score"]["total_score"]

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    def test_empty_spec_does_not_crash(self, category):
        """빈 스펙으로도 채점이 오류 없이 동작해야 한다."""
        spec   = parse_spec(category, {})
        result = score_model(category, spec)
        assert "total_score" in result
        assert result["total_score"] >= 0
