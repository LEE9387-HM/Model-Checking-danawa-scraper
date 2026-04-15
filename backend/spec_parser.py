"""
spec_parser.py — 다나와 스펙 텍스트를 구조화된 딕셔너리로 변환
카테고리별 텍스트 정규화 + 공통 파서 제공
"""
import re
from typing import Any


# ─── 공통 유틸 ──────────────────────────────────────────────────────────────────

def extract_number(text: str) -> float | None:
    """텍스트에서 첫 번째 숫자(정수/소수)를 추출"""
    if not text:
        return None
    m = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    return float(m.group()) if m else None


def normalize_bool(text: str) -> bool:
    """'지원', '있음', 'O', 'Yes' → True; '미지원', '없음', 'X', 'No' → False"""
    text_lower = text.strip().lower()
    pos = {"지원", "있음", "o", "yes", "해당", "포함"}
    neg = {"미지원", "없음", "x", "no", "해당없음", "미포함"}
    if text_lower in pos:
        return True
    if text_lower in neg:
        return False
    # 부분 매칭
    for p in pos:
        if p in text_lower:
            return True
    return False


def normalize_energy_rating(text: str) -> str | None:
    """'1등급', '에너지소비효율 1등급' 등 → '1등급' 형식으로 정규화"""
    m = re.search(r"([1-5])등급", text)
    return f"{m.group(1)}등급" if m else None


def normalize_unit_value(text: str, unit_hint: str = "") -> float | None:
    """단위가 포함된 텍스트에서 숫자 추출 (예: '120Hz', '2800Pa', '30dB')"""
    if not text:
        return None
    cleaned = text.strip()
    return extract_number(cleaned)


# ─── TV 파서 ────────────────────────────────────────────────────────────────────

def parse_tv(raw: dict[str, str]) -> dict[str, Any]:
    """
    raw: {스펙항목명: 스펙값} 딕셔너리 (다나와 스펙 테이블 raw)
    returns: 구조화된 스펙 딕셔너리
    """
    result: dict[str, Any] = {}

    # 필수 스펙
    size_text = raw.get("화면 크기", raw.get("화면크기", ""))
    m = re.search(r"(\d+)\s*인치", size_text)
    result["screen_size"] = int(m.group(1)) if m else None

    resolution = raw.get("해상도", "")
    if "8K" in resolution:
        result["resolution"] = "8K"
    elif "4K" in resolution or "UHD" in resolution:
        result["resolution"] = "4K UHD"
    elif "FHD" in resolution or "1080" in resolution:
        result["resolution"] = "FHD"
    else:
        result["resolution"] = resolution.strip() or None

    panel = raw.get("패널 종류", raw.get("디스플레이 종류", ""))
    result["panel_type"] = panel.split("/")[0].strip() if panel else None

    # 등급 스펙
    refresh_text = raw.get("주사율", raw.get("화면재생빈도", ""))
    result["refresh_rate"] = normalize_unit_value(refresh_text, "Hz")

    hdr_text = raw.get("HDR", raw.get("HDR 지원", ""))
    if "돌비비전" in hdr_text or "Dolby Vision" in hdr_text.lower():
        result["hdr"] = "돌비비전"
    elif "HDR10+" in hdr_text:
        result["hdr"] = "HDR10+"
    elif "HDR10" in hdr_text:
        result["hdr"] = "HDR10"
    else:
        result["hdr"] = "미지원"

    smart_text = raw.get("스마트 TV", raw.get("운영체제", ""))
    if "AI" in smart_text or "인공지능" in smart_text:
        result["smart_features"] = "AI"
    elif smart_text and smart_text not in ("없음", "미지원", ""):
        result["smart_features"] = "풀스마트"
    else:
        result["smart_features"] = "미지원"

    speaker_text = raw.get("스피커 출력", raw.get("출력", ""))
    result["speaker_output"] = normalize_unit_value(speaker_text, "W")

    dolby_text = raw.get("돌비 애트모스", raw.get("Dolby Atmos", ""))
    result["dolby_atmos"] = normalize_bool(dolby_text) if dolby_text else False

    energy_text = raw.get("에너지소비효율", raw.get("에너지 등급", ""))
    result["energy_rating"] = normalize_energy_rating(energy_text)

    thin_text = raw.get("두께", raw.get("제품 두께", ""))
    result["design_thinness"] = normalize_unit_value(thin_text, "mm")

    # 메타 스펙
    price_text = raw.get("__price__", "0")
    result["price"] = int(extract_number(price_text) or 0)

    year_text = raw.get("출시년월", raw.get("출시 연도", ""))
    m_year = re.search(r"(20\d{2})", year_text)
    result["release_year"] = int(m_year.group(1)) if m_year else None

    result["brand"] = raw.get("__brand__", raw.get("제조회사", "")).strip()
    result["review_count"] = int(extract_number(raw.get("__review_count__", "0")) or 0)

    return result


# ─── 냉장고 파서 ─────────────────────────────────────────────────────────────────

def parse_refrigerator(raw: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    # 필수 스펙
    cap_text = raw.get("냉장고 용량(순용량)", raw.get("전체용량", ""))
    result["capacity_l"] = normalize_unit_value(cap_text, "L")
    result["door_type"] = raw.get("도어 형태", raw.get("형태", "")).strip() or None

    # 등급 스펙
    energy_text = raw.get("에너지소비효율", "")
    result["energy_rating"] = normalize_energy_rating(energy_text)

    inverter_text = raw.get("인버터 컴프레서", raw.get("인버터", ""))
    result["inverter"] = normalize_bool(inverter_text) if inverter_text else False

    cooling_text = raw.get("냉각 방식", "")
    result["cooling_type"] = "간냉식" if "간냉" in cooling_text else ("직냉식" if "직냉" in cooling_text else None)

    deod_text = raw.get("탈취필터", raw.get("항균", ""))
    result["deodorize_antibacterial"] = normalize_bool(deod_text) if deod_text else False

    smart_text = raw.get("스마트 기능", raw.get("IoT", ""))
    result["smart_features"] = "AI" if "AI" in smart_text else ("기본" if smart_text else "미지원")

    noise_text = raw.get("소음", raw.get("소비소음(냉장)", ""))
    result["noise_level"] = normalize_unit_value(noise_text, "dB")

    # 메타
    price_text = raw.get("__price__", "0")
    result["price"] = int(extract_number(price_text) or 0)
    year_text = raw.get("출시년월", "")
    m_year = re.search(r"(20\d{2})", year_text)
    result["release_year"] = int(m_year.group(1)) if m_year else None
    result["brand"] = raw.get("__brand__", "").strip()
    result["review_count"] = int(extract_number(raw.get("__review_count__", "0")) or 0)

    return result


# ─── 공통 파서 라우터 ────────────────────────────────────────────────────────────

PARSERS = {
    "tv": parse_tv,
    "refrigerator": parse_refrigerator,
}

def parse_spec(category: str, raw: dict[str, str]) -> dict[str, Any]:
    """
    카테고리 이름과 raw 스펙 딕셔너리를 받아 구조화된 스펙 반환.
    등록되지 않은 카테고리는 raw를 그대로 반환 (fallback).
    """
    parser = PARSERS.get(category)
    if parser is None:
        return {k: v for k, v in raw.items()}
    return parser(raw)
