"""
naver_store_adapter.py — 네이버 브랜드스토어 크롤링 어댑터
Phase 4에서 구현 예정. 현재는 UNVERIFIED를 유도하는 stub.
"""
from official_malls.base_adapter import BaseAdapter


class NaverStoreAdapter(BaseAdapter):
    """네이버 브랜드스토어 어댑터 (Phase 4 구현 예정)."""

    ADAPTER_NAME = "naver"

    def __init__(self, brand: str = "") -> None:
        self.brand = brand

    async def search_and_parse(self, model_name: str) -> dict[str, str]:
        # TODO Phase 4: 네이버 브랜드스토어 크롤링 구현
        return {}
