"""
official_malls — 제조사별 공식몰 크롤링 어댑터 패키지
"""
from official_malls.samsung_adapter import SamsungAdapter
from official_malls.lg_adapter import LgAdapter
from official_malls.naver_store_adapter import NaverStoreAdapter

__all__ = ["SamsungAdapter", "LgAdapter", "NaverStoreAdapter"]
