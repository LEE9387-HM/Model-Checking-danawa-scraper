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
    VERIFIED   = "VERIFIED"
    CORRECTED  = "CORRECTED"
    UNVERIFIED = "UNVERIFIED"


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

    Returns:
        {
            danawa_key: {
                "danawa": <다나와 값>,
                "official": <공식몰 값>,
                "official_label": <공식몰 라벨>,
                "corrected": True,
            },
            ...
        }
    """
    diffs: dict[str, dict] = {}
    for danawa_key, official_label in key_map.items():
        d_val = str(danawa_spec.get(danawa_key, "")).strip()
        o_val = str(official_spec.get(official_label, "")).strip()
        if o_val and d_val != o_val:
            diffs[danawa_key] = {
                "danawa":         d_val,
                "official":       o_val,
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
    삼성 공식몰 교차검증.

    Returns:
        {
            "status":         "VERIFIED" | "CORRECTED" | "UNVERIFIED",
            "corrected_spec": {...},
            "diffs":          {...},   # 변경된 항목만
        }
    """
    adapter = SamsungAdapter()
    official = await adapter.fetch(model_name)

    if not official:
        return {
            "status":         VerifyStatus.UNVERIFIED,
            "corrected_spec": danawa_spec.copy(),
            "diffs":          {},
        }

    key_map = _get_key_map(category)
    diffs = _diff_specs(danawa_spec, official, key_map)
    corrected_spec = _apply_diffs(danawa_spec, diffs)
    status = VerifyStatus.CORRECTED if diffs else VerifyStatus.VERIFIED

    return {
        "status":         status,
        "corrected_spec": corrected_spec,
        "diffs":          diffs,
    }


async def verify_competitor(
    model_name: str,
    brand: str,
    danawa_spec: dict[str, Any],
    category: str = "tv",
) -> dict[str, Any]:
    """
    LG/기타 경쟁사 공식몰 교차검증.
    LG는 직접 어댑터, 나머지는 네이버 브랜드스토어로 fallback.

    Returns: verify_samsung과 동일한 구조
    """
    brand_lower = brand.lower()

    if "lg" in brand_lower or "엘지" in brand_lower:
        adapter = LgAdapter()
        official = await adapter.fetch(model_name)
    else:
        adapter = NaverStoreAdapter(brand=brand)
        official = await adapter.fetch(model_name)

    if not official:
        return {
            "status":         VerifyStatus.UNVERIFIED,
            "corrected_spec": danawa_spec.copy(),
            "diffs":          {},
        }

    key_map = _get_key_map(category)
    diffs = _diff_specs(danawa_spec, official, key_map)
    corrected_spec = _apply_diffs(danawa_spec, diffs)
    status = VerifyStatus.CORRECTED if diffs else VerifyStatus.VERIFIED

    return {
        "status":         status,
        "corrected_spec": corrected_spec,
        "diffs":          diffs,
    }
