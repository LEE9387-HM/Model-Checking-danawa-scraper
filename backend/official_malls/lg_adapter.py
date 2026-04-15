"""
lg_adapter.py — LG전자 공식몰(lgelectronics.co.kr) 크롤링 어댑터
Phase 4에서 구현 예정. 현재는 UNVERIFIED를 유도하는 stub.
"""
from official_malls.base_adapter import BaseAdapter


class LgAdapter(BaseAdapter):
    """LG전자 공식몰 어댑터 (Phase 4 구현 예정)."""

    ADAPTER_NAME = "lg"

    async def search_and_parse(self, model_name: str) -> dict[str, str]:
        # TODO Phase 4: lgelectronics.co.kr 크롤링 구현
        return {}
