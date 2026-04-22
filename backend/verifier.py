"""
verifier.py — 삼성/LG 공식몰 교차검증 엔진
어댑터 패턴을 사용해 제조사별 공식몰 크롤링을 캡슐화한다.
"""
import json
from enum import Enum
from pathlib import Path
from typing import Any

from official_malls.samsung_adapter import SamsungAdapter
from official_malls.lg_adapter import LgAdapter
from official_malls.naver_store_adapter import NaverStoreAdapter

SELECTORS_DIR = Path(__file__).parent / "selectors"


# ─── 상태 Enum ───────────────────────────────────────────────────────────────

class VerifyStatus(str, Enum):
    VERIFIED        = "VERIFIED"        # 공식몰 일치
    CORRECTED       = "CORRECTED"       # 공식몰 기준 보정
    VERIFIED_NAVER  = "VERIFIED_NAVER"  # 네이버 스토어 일치
    CORRECTED_NAVER = "CORRECTED_NAVER" # 네이버 스토어 기준 보정
    UNVERIFIED      = "UNVERIFIED"      # 검증 실패


# ─── 카테고리별 KEY_MAP (다나와 키 → 삼성/LG 공식몰 라벨) ───────────────────

CATEGORY_KEY_MAPS: dict[str, dict[str, str]] = {
    "tv": {
        "refresh_rate":   "주사율",
        "hdr":            "HDR",
        "energy_rating":  "에너지소비효율",
        "speaker_output": "스피커 출력",
        "smart":          "스마트TV",
        "dolby":          "돌비",
    },
    "refrigerator": {
        "energy_rating": "에너지소비효율",
        "inverter":      "인버터컴프레서",
        "cooling_type":  "냉각방식",
        "deodorizer":    "탈취필터",
        "smart":         "스마트",
        "noise":         "소음도",
    },
    "washer": {
        "energy_rating": "에너지소비효율",
        "spin_rpm":      "탈수회전수",
        "modes":         "세탁코스",
        "steam":         "스팀세탁",
        "noise":         "소음도",
        "smart":         "스마트",
    },
    "dryer": {
        "energy_rating": "에너지소비효율",
        "modes":         "건조코스",
        "filter_type":   "필터방식",
        "noise":         "소음도",
        "smart":         "스마트",
    },
    "air_conditioner": {
        "energy_rating": "에너지소비효율",
        "heating":       "냉난방겸용",
        "filter":        "필터종류",
        "noise":         "소음도",
        "smart":         "스마트",
    },
    "dishwasher": {
        "energy_rating": "에너지소비효율",
        "modes":         "코스수",
        "dry_type":      "건조방식",
        "noise":         "소음도",
        "smart":         "스마트",
    },
    "air_purifier": {
        "cadr":        "청정면적(CADR)",
        "noise":       "소음도",
        "smart":       "스마트",
        "filter_life": "필터교체주기",
    },
    "vacuum": {
        "suction":  "흡입력",
        "battery":  "배터리",
        "dust_bin": "먼지통용량",
        "noise":    "소음도",
    },
    "robot_vacuum": {
        "mapping":    "매핑방식",
        "battery":    "배터리",
        "auto_empty": "자동먼지비움",
        "noise":      "소음도",
        "smart":      "스마트",
    },
    "microwave": {
        "power":         "출력",
        "modes":         "조리기능수",
        "coating":       "내부코팅",
        "energy_rating": "에너지소비효율",
    },
    "monitor": {
        "refresh_rate":  "주사율",
        "response_time": "응답속도",
        "hdr":           "HDR",
        "color_gamut":   "색재현율",
        "pivot":         "피벗",
        "speaker":       "스피커",
    },
}


# ─── 내부 헬퍼 ───────────────────────────────────────────────────────────────

def _get_key_map(category: str) -> dict[str, str]:
    return CATEGORY_KEY_MAPS.get(category, {})


def _diff_specs(
    danawa_spec: dict[str, Any],
    official_spec: dict[str, str],
    key_map: dict[str, str],
) -> dict[str, dict]:
    """
    다나와 스펙과 공식몰 스펙을 key_map 기준으로 대조.
    """
    diffs: dict[str, dict] = {}
    for danawa_key, official_label in key_map.items():
        original_d = danawa_spec.get(danawa_key, "")
        original_o = official_spec.get(official_label, "")
        
        d_val = str(original_d).strip().lower()
        o_val = str(original_o).strip().lower()
        
        if not o_val:
            continue # 공식몰에 데이터가 없으면 기준 데이터로 삼을 수 없음

        # 동일성 판단 (단순 lowercase 비교)
        # 만약 "2024년형" vs "2024" 처럼 포함관계가 의미있다면 추가 정규화 필요
        # 현재는 빈 값 처리 및 정확한 매칭을 위해 d_val != o_val 사용
        if d_val != o_val:
            diffs[danawa_key] = {
                "danawa":         original_d,
                "official":       original_o,
                "official_label": official_label,
                "corrected":      True,
            }
    return diffs


def _apply_diffs(spec: dict[str, Any], diffs: dict[str, dict]) -> dict[str, Any]:
    corrected = spec.copy()
    for key, diff in diffs.items():
        corrected[key] = diff["official"]
    return corrected


# ─── 공개 API ────────────────────────────────────────────────────────────────

async def verify_samsung(
    model_name: str,
    danawa_spec: dict[str, Any],
    category: str = "tv",
) -> dict[str, Any]:
    """
    삼성 모델 교차검증 (Waterfall 패턴).
    1차: 삼성 공식몰 -> 2차: 네이버 브랜드스토어 -> 3차: UNVERIFIED
    """
    key_map = _get_key_map(category)
    
    # 1단계: 삼성 공식몰
    adapter = SamsungAdapter()
    official = await adapter.fetch(model_name)

    if official:
        diffs = _diff_specs(danawa_spec, official, key_map)
        corrected_spec = _apply_diffs(danawa_spec, diffs)
        status = VerifyStatus.CORRECTED if diffs else VerifyStatus.VERIFIED
        return {
            "status":         status,
            "source":         "samsung.com",
            "confidence":     "high",
            "corrected_spec": corrected_spec,
            "diffs":          diffs,
        }

    # 2단계: 네이버 브랜드스토어 (삼성전자)
    naver_adapter = NaverStoreAdapter(brand="삼성전자")
    naver_official = await naver_adapter.fetch(model_name)

    if naver_official:
        diffs = _diff_specs(danawa_spec, naver_official, key_map)
        corrected_spec = _apply_diffs(danawa_spec, diffs)
        status = VerifyStatus.CORRECTED_NAVER if diffs else VerifyStatus.VERIFIED_NAVER
        return {
            "status":         status,
            "source":         "naver_store",
            "confidence":     "medium",
            "corrected_spec": corrected_spec,
            "diffs":          diffs,
        }

    # 3단계: 검증 불가
    return {
        "status":         VerifyStatus.UNVERIFIED,
        "source":         "none",
        "confidence":     "low",
        "corrected_spec": danawa_spec.copy(),
        "diffs":          {},
    }


async def verify_competitor(
    model_name: str,
    brand: str,
    danawa_spec: dict[str, Any],
    category: str = "tv",
) -> dict[str, Any]:
    """
    경쟁사 모델 교차검증.
    """
    brand_lower = brand.lower()
    key_map = _get_key_map(category)
    source = "none"
    confidence = "low"
    
    official = None

    if "lg" in brand_lower or "엘지" in brand_lower:
        adapter = LgAdapter()
        official = await adapter.fetch(model_name)
        source = "lge.co.kr"
        confidence = "high"
        
        # LG 공식몰 실패 시 네이버 Fallback
        if not official:
            naver_adapter = NaverStoreAdapter(brand="LG전자")
            official = await naver_adapter.fetch(model_name)
            source = "naver_store"
            confidence = "medium"
    else:
        # 기타 브랜드는 네이버 스토어 우선
        naver_adapter = NaverStoreAdapter(brand=brand)
        official = await naver_adapter.fetch(model_name)
        source = "naver_store"
        confidence = "medium"

    if not official:
        return {
            "status":         VerifyStatus.UNVERIFIED,
            "source":         "none",
            "confidence":     "low",
            "corrected_spec": danawa_spec.copy(),
            "diffs":          {},
        }

    diffs = _diff_specs(danawa_spec, official, key_map)
    corrected_spec = _apply_diffs(danawa_spec, diffs)
    
    # 소스에 따른 상태 결정
    if source == "naver_store":
        status = VerifyStatus.CORRECTED_NAVER if diffs else VerifyStatus.VERIFIED_NAVER
    else:
        status = VerifyStatus.CORRECTED if diffs else VerifyStatus.VERIFIED

    return {
        "status":         status,
        "source":         source,
        "confidence":     confidence,
        "corrected_spec": corrected_spec,
        "diffs":          diffs,
    }
