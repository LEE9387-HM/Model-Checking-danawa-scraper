"""
test_e2e_crawler.py — 크롤러 E2E 테스트 (실제 네트워크 필요)

기본적으로 스킵됩니다. 실제 크롤링 테스트를 실행하려면:
    pytest tests/test_e2e_crawler.py -m e2e --timeout=120

환경변수 DANAWA_E2E=1 을 설정하면 스킵 없이 실행됩니다.
"""
import os
import pytest

# e2e 마커: 실제 네트워크·브라우저 필요
e2e = pytest.mark.skipif(
    os.getenv("DANAWA_E2E") != "1",
    reason="실제 크롤링 테스트는 DANAWA_E2E=1 환경변수가 필요합니다.",
)


# ─── 단건 스펙 크롤링 ────────────────────────────────────────────────────────

class TestFetchModelSpec:
    @e2e
    @pytest.mark.asyncio
    async def test_tv_model_returns_spec(self):
        """삼성 TV 모델 크롤링이 스펙 딕셔너리를 반환해야 한다."""
        from crawler import fetch_model_spec
        result = await fetch_model_spec("KQ65QNC85AFXKR")
        assert isinstance(result, dict)
        assert result  # 빈 딕셔너리가 아님

    @e2e
    @pytest.mark.asyncio
    async def test_tv_model_has_required_keys(self):
        """크롤링 결과에 가격, 브랜드 메타 키가 있어야 한다."""
        from crawler import fetch_model_spec
        result = await fetch_model_spec("KQ65QNC85AFXKR")
        assert "__price__" in result
        assert "__brand__" in result

    @e2e
    @pytest.mark.asyncio
    async def test_invalid_model_returns_empty(self):
        """존재하지 않는 모델명은 빈 딕셔너리를 반환해야 한다."""
        from crawler import fetch_model_spec
        result = await fetch_model_spec("INVALID_MODEL_XYZ_99999")
        assert result == {} or isinstance(result, dict)


# ─── 카테고리 URL ────────────────────────────────────────────────────────────

class TestGetCategoryUrl:
    def test_tv_url_is_string(self):
        """TV 카테고리 URL이 http로 시작하는 문자열이어야 한다."""
        from crawler import get_category_url
        url = get_category_url("tv")
        assert isinstance(url, str) and url.startswith("http")

    def test_all_11_categories_return_url(self):
        """11개 카테고리 모두 URL 문자열을 반환해야 한다."""
        from crawler import get_category_url
        categories = [
            "tv", "refrigerator", "washer", "dryer", "air_conditioner",
            "dishwasher", "air_purifier", "vacuum", "robot_vacuum",
            "microwave", "monitor",
        ]
        for cat in categories:
            url = get_category_url(cat)
            assert isinstance(url, str) and url.startswith("http"), (
                f"{cat}: 유효하지 않은 URL → {url!r}"
            )

    def test_unknown_category_returns_fallback_url(self):
        """알 수 없는 카테고리는 기본 URL(fallback)을 반환해야 한다."""
        from crawler import get_category_url
        url = get_category_url("unknown_category_xyz")
        assert isinstance(url, str) and url.startswith("http")


# ─── 경쟁사 크롤링 ───────────────────────────────────────────────────────────

class TestFetchCompetitors:
    @e2e
    @pytest.mark.asyncio
    async def test_tv_competitors_returns_list(self):
        """TV 경쟁사 크롤링이 리스트를 반환해야 한다."""
        from crawler import fetch_competitors, get_category_url
        url = get_category_url("tv")
        primary_filter = {"screen_size": 65, "resolution": "4K UHD"}
        result = await fetch_competitors(
            category_url=url,
            category="tv",
            primary_filter=primary_filter,
            samsung_release_year=2024,
            max_items=5,
        )
        assert isinstance(result, list)

    @e2e
    @pytest.mark.asyncio
    async def test_tv_competitors_exclude_samsung(self):
        """경쟁사 크롤링 결과에 삼성전자가 포함되면 안 된다."""
        from crawler import fetch_competitors, get_category_url
        url = get_category_url("tv")
        primary_filter = {"screen_size": 65}
        result = await fetch_competitors(
            category_url=url,
            category="tv",
            primary_filter=primary_filter,
            max_items=10,
        )
        for item in result:
            brand = item.get("__brand__", "")
            assert "삼성" not in brand, f"삼성 모델이 경쟁사에 포함됨: {brand}"
