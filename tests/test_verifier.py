"""
test_verifier.py — 교차검증 엔진 단위 테스트 (mock 기반)
실제 Playwright 크롤링 없이 어댑터를 mock해서 로직만 검증
"""
from unittest.mock import AsyncMock, patch

import pytest

from verifier import (
    VerifyStatus,
    CATEGORY_KEY_MAPS,
    _get_key_map,
    _diff_specs,
    _apply_diffs,
    verify_samsung,
    verify_competitor,
)


# ─── VerifyStatus ────────────────────────────────────────────────────────────

class TestVerifyStatus:
    def test_all_statuses_exist(self):
        assert VerifyStatus.VERIFIED   == "VERIFIED"
        assert VerifyStatus.CORRECTED  == "CORRECTED"
        assert VerifyStatus.UNVERIFIED == "UNVERIFIED"

    def test_is_str_subclass(self):
        assert isinstance(VerifyStatus.VERIFIED, str)


# ─── KEY_MAP ─────────────────────────────────────────────────────────────────

class TestCategoryKeyMaps:
    def test_all_11_categories_present(self):
        expected = {
            "tv", "refrigerator", "washer", "dryer", "air_conditioner",
            "dishwasher", "air_purifier", "vacuum", "robot_vacuum",
            "microwave", "monitor",
        }
        assert set(CATEGORY_KEY_MAPS.keys()) == expected

    def test_get_key_map_tv(self):
        km = _get_key_map("tv")
        assert "refresh_rate" in km
        assert "energy_rating" in km

    def test_get_key_map_unknown_returns_empty(self):
        km = _get_key_map("unknown_category")
        assert km == {}

    @pytest.mark.parametrize("category", list(CATEGORY_KEY_MAPS.keys()))
    def test_each_category_has_at_least_one_key(self, category):
        km = _get_key_map(category)
        assert len(km) >= 1


# ─── _diff_specs ─────────────────────────────────────────────────────────────

class TestDiffSpecs:
    def test_no_diff_when_values_match(self):
        danawa  = {"refresh_rate": "120Hz"}
        official = {"주사율": "120Hz"}
        key_map  = {"refresh_rate": "주사율"}
        diffs = _diff_specs(danawa, official, key_map)
        assert diffs == {}

    def test_diff_detected_when_values_differ(self):
        danawa   = {"refresh_rate": "60Hz"}
        official = {"주사율": "120Hz"}
        key_map  = {"refresh_rate": "주사율"}
        diffs = _diff_specs(danawa, official, key_map)
        assert "refresh_rate" in diffs
        assert diffs["refresh_rate"]["danawa"]   == "60Hz"
        assert diffs["refresh_rate"]["official"] == "120Hz"
        assert diffs["refresh_rate"]["corrected"] is True

    def test_no_diff_when_official_key_missing(self):
        danawa   = {"refresh_rate": "60Hz"}
        official = {}   # 공식몰에 해당 키 없음
        key_map  = {"refresh_rate": "주사율"}
        diffs = _diff_specs(danawa, official, key_map)
        assert diffs == {}

    def test_empty_danawa_value_diff(self):
        danawa   = {"energy_rating": ""}
        official = {"에너지소비효율": "1등급"}
        key_map  = {"energy_rating": "에너지소비효율"}
        diffs = _diff_specs(danawa, official, key_map)
        assert "energy_rating" in diffs

    def test_official_label_stored_in_diff(self):
        danawa   = {"hdr": "HDR10"}
        official = {"HDR": "HDR10+"}
        key_map  = {"hdr": "HDR"}
        diffs = _diff_specs(danawa, official, key_map)
        assert diffs["hdr"]["official_label"] == "HDR"


# ─── _apply_diffs ────────────────────────────────────────────────────────────

class TestApplyDiffs:
    def test_corrected_value_applied(self):
        spec  = {"refresh_rate": "60Hz", "hdr": "HDR10"}
        diffs = {"refresh_rate": {"official": "120Hz", "corrected": True}}
        result = _apply_diffs(spec, diffs)
        assert result["refresh_rate"] == "120Hz"
        assert result["hdr"] == "HDR10"   # 변경 없음

    def test_original_spec_not_mutated(self):
        spec  = {"refresh_rate": "60Hz"}
        diffs = {"refresh_rate": {"official": "120Hz", "corrected": True}}
        _apply_diffs(spec, diffs)
        assert spec["refresh_rate"] == "60Hz"  # 원본 불변


# ─── verify_samsung (mock) ───────────────────────────────────────────────────

class TestVerifySamsung:
    @pytest.mark.asyncio
    async def test_returns_unverified_when_adapter_empty(self):
        with patch("verifier.SamsungAdapter") as MockAdapter:
            MockAdapter.return_value.fetch = AsyncMock(return_value={})
            result = await verify_samsung("QN65QN85C", {"refresh_rate": "120"}, "tv")
        assert result["status"] == VerifyStatus.UNVERIFIED
        assert result["diffs"] == {}

    @pytest.mark.asyncio
    async def test_returns_verified_when_specs_match(self):
        official = {"주사율": "120Hz", "HDR": "HDR10+"}
        danawa   = {"refresh_rate": "120Hz", "hdr": "HDR10+"}
        with patch("verifier.SamsungAdapter") as MockAdapter:
            MockAdapter.return_value.fetch = AsyncMock(return_value=official)
            result = await verify_samsung("MODEL", danawa, "tv")
        assert result["status"] == VerifyStatus.VERIFIED
        assert result["diffs"] == {}

    @pytest.mark.asyncio
    async def test_returns_corrected_when_specs_differ(self):
        official = {"주사율": "120Hz"}
        danawa   = {"refresh_rate": "60Hz"}
        with patch("verifier.SamsungAdapter") as MockAdapter:
            MockAdapter.return_value.fetch = AsyncMock(return_value=official)
            result = await verify_samsung("MODEL", danawa, "tv")
        assert result["status"] == VerifyStatus.CORRECTED
        assert "refresh_rate" in result["diffs"]
        assert result["corrected_spec"]["refresh_rate"] == "120Hz"

    @pytest.mark.asyncio
    async def test_corrected_spec_preserves_unmodified_keys(self):
        official = {"주사율": "120Hz"}
        danawa   = {"refresh_rate": "60Hz", "price": 1000000}
        with patch("verifier.SamsungAdapter") as MockAdapter:
            MockAdapter.return_value.fetch = AsyncMock(return_value=official)
            result = await verify_samsung("MODEL", danawa, "tv")
        assert result["corrected_spec"]["price"] == 1000000


# ─── verify_competitor (mock) ────────────────────────────────────────────────

class TestVerifyCompetitor:
    @pytest.mark.asyncio
    async def test_lg_brand_uses_lg_adapter(self):
        with patch("verifier.LgAdapter") as MockLg:
            MockLg.return_value.fetch = AsyncMock(return_value={})
            result = await verify_competitor("OLED65C3KNA", "LG전자", {}, "tv")
        assert result["status"] == VerifyStatus.UNVERIFIED
        MockLg.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_lg_uses_naver_adapter(self):
        with patch("verifier.NaverStoreAdapter") as MockNaver:
            MockNaver.return_value.fetch = AsyncMock(return_value={})
            result = await verify_competitor("QN65Q60C", "소니코리아", {}, "tv")
        assert result["status"] == VerifyStatus.UNVERIFIED
        MockNaver.assert_called_once()

    @pytest.mark.asyncio
    async def test_lg_brand_alias_korean(self):
        with patch("verifier.LgAdapter") as MockLg:
            MockLg.return_value.fetch = AsyncMock(return_value={})
            await verify_competitor("MODEL", "엘지전자", {}, "tv")
        MockLg.assert_called_once()
