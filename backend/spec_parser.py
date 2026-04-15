"""
spec_parser.py — 다나와 스펙 텍스트를 구조화된 딕셔너리로 변환
카테고리별 텍스트 정규화 + 공통 파서 제공 (11개 카테고리 완전 지원)
"""
import re
from typing import Any


# ─── 공통 유틸 ───────────────────────────────────────────────────────────────

def extract_number(text: str) -> float | None:
    """텍스트에서 첫 번째 숫자(정수/소수)를 추출."""
    if not text:
        return None
    cleaned = re.sub(r",", "", text.strip())
    m = re.search(r"\d+\.?\d*", cleaned)
    return float(m.group()) if m else None


def normalize_bool(text: str) -> bool:
    """'지원','있음','O','Yes' → True  |  '미지원','없음','X','No' → False"""
    t = text.strip().lower()
    pos = {"지원", "있음", "o", "yes", "해당", "포함"}
    neg = {"미지원", "없음", "x", "no", "해당없음", "미포함"}
    if t in pos:
        return True
    if t in neg:
        return False
    for p in pos:
        if p in t:
            return True
    return False


def normalize_energy_rating(text: str) -> str | None:
    """'1등급', '에너지소비효율 1등급' 등 → '1등급'."""
    m = re.search(r"([1-5])등급", text)
    return f"{m.group(1)}등급" if m else None


def normalize_unit_value(text: str) -> float | None:
    """단위 포함 텍스트에서 숫자 추출 (예: '120Hz', '2800Pa', '30dB')."""
    return extract_number(text)


def _meta(raw: dict[str, str]) -> dict[str, Any]:
    """모든 카테고리 공통 메타 스펙 추출."""
    price_text = raw.get("__price__", "0")
    year_text  = raw.get("출시년월", raw.get("__release_year__", raw.get("출시연도", "")))
    m_year = re.search(r"(20\d{2})", year_text)
    return {
        "price":        int(extract_number(price_text) or 0),
        "release_year": int(m_year.group(1)) if m_year else None,
        "brand":        raw.get("__brand__", raw.get("제조회사", "")).strip(),
        "review_count": int(extract_number(raw.get("__review_count__", "0")) or 0),
    }


# ─── TV ──────────────────────────────────────────────────────────────────────

def parse_tv(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    size_text = raw.get("화면 크기", raw.get("화면크기", ""))
    m = re.search(r"(\d+)\s*인치", size_text)
    r["screen_size"] = int(m.group(1)) if m else None

    res = raw.get("해상도", "")
    r["resolution"] = (
        "8K" if "8K" in res
        else "4K UHD" if ("4K" in res or "UHD" in res)
        else "FHD" if ("FHD" in res or "1080" in res)
        else res.strip() or None
    )

    panel = raw.get("패널 종류", raw.get("디스플레이 종류", ""))
    r["panel_type"] = panel.split("/")[0].strip() or None

    # 등급 스펙
    refresh = raw.get("주사율", raw.get("화면재생빈도", ""))
    r["refresh_rate"] = normalize_unit_value(refresh)

    hdr = raw.get("HDR", raw.get("HDR 지원", ""))
    r["hdr"] = (
        "돌비비전" if ("돌비비전" in hdr or "Dolby Vision" in hdr.lower())
        else "HDR10+" if "HDR10+" in hdr
        else "HDR10"  if "HDR10" in hdr
        else "미지원"
    )

    smart = raw.get("스마트 TV", raw.get("운영체제", ""))
    r["smart_features"] = (
        "AI" if ("AI" in smart or "인공지능" in smart)
        else "풀스마트" if smart and smart not in ("없음", "미지원", "")
        else "미지원"
    )

    speaker = raw.get("스피커 출력", raw.get("출력", ""))
    r["speaker_output"] = normalize_unit_value(speaker)

    dolby = raw.get("돌비 애트모스", raw.get("Dolby Atmos", ""))
    r["dolby_atmos"] = normalize_bool(dolby) if dolby else False

    energy = raw.get("에너지소비효율", raw.get("에너지 등급", ""))
    r["energy_rating"] = normalize_energy_rating(energy)

    thin = raw.get("두께", raw.get("제품 두께", ""))
    r["design_thinness"] = normalize_unit_value(thin)

    r.update(_meta(raw))
    return r


# ─── 냉장고 ──────────────────────────────────────────────────────────────────

def parse_refrigerator(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    cap = raw.get("냉장고 용량(순용량)", raw.get("전체용량", raw.get("용량", "")))
    r["capacity_l"] = normalize_unit_value(cap)
    r["door_type"]  = raw.get("도어 형태", raw.get("형태", "")).strip() or None

    r["energy_rating"] = normalize_energy_rating(raw.get("에너지소비효율", ""))

    inv = raw.get("인버터 컴프레서", raw.get("인버터", ""))
    r["inverter"] = normalize_bool(inv) if inv else False

    cool = raw.get("냉각 방식", "")
    r["cooling_type"] = (
        "간냉식" if "간냉" in cool
        else "직냉식" if "직냉" in cool
        else None
    )

    deod = raw.get("탈취필터", raw.get("항균", ""))
    r["deodorize_antibacterial"] = normalize_bool(deod) if deod else False

    smart = raw.get("스마트 기능", raw.get("IoT", ""))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if smart else "미지원")

    noise = raw.get("소음", raw.get("소비소음(냉장)", ""))
    r["noise_level"] = normalize_unit_value(noise)

    r.update(_meta(raw))
    return r


# ─── 세탁기 ──────────────────────────────────────────────────────────────────

def parse_washer(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    cap = raw.get("세탁 용량", raw.get("세탁용량", raw.get("용량", "")))
    r["capacity_kg"] = normalize_unit_value(cap)
    r["form_type"]   = raw.get("형태", raw.get("세탁기 형태", "")).strip() or None

    r["energy_rating"] = normalize_energy_rating(raw.get("에너지소비효율", ""))

    spin = raw.get("탈수 회전수", raw.get("탈수RPM", raw.get("최고탈수회전수", "")))
    r["spin_rpm"] = normalize_unit_value(spin)

    modes = raw.get("세탁코스", raw.get("코스 수", raw.get("코스수", "")))
    r["mode_count"] = normalize_unit_value(modes)

    steam = raw.get("스팀", raw.get("스팀세탁", ""))
    r["steam"] = normalize_bool(steam) if steam else False

    noise = raw.get("소음", raw.get("세탁 소음(세탁)", ""))
    r["noise_level"] = normalize_unit_value(noise)

    smart = raw.get("스마트 기능", raw.get("IoT", raw.get("Wi-Fi", "")))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if normalize_bool(smart) else "미지원") if smart else "미지원"

    r.update(_meta(raw))
    return r


# ─── 건조기 ──────────────────────────────────────────────────────────────────

def parse_dryer(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    cap = raw.get("건조 용량", raw.get("건조용량", raw.get("용량", "")))
    r["capacity_kg"] = normalize_unit_value(cap)
    r["dry_method"]  = raw.get("건조 방식", raw.get("건조방식", "")).strip() or None

    r["energy_rating"] = normalize_energy_rating(raw.get("에너지소비효율", ""))

    modes = raw.get("건조코스", raw.get("코스 수", raw.get("코스수", "")))
    r["mode_count"] = normalize_unit_value(modes)

    filt = raw.get("필터 방식", raw.get("필터방식", raw.get("필터 종류", "")))
    r["filter_type"] = filt.strip() or None

    noise = raw.get("소음", raw.get("건조 소음", ""))
    r["noise_level"] = normalize_unit_value(noise)

    smart = raw.get("스마트 기능", raw.get("IoT", raw.get("Wi-Fi", "")))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if normalize_bool(smart) else "미지원") if smart else "미지원"

    r.update(_meta(raw))
    return r


# ─── 에어컨 ──────────────────────────────────────────────────────────────────

def parse_air_conditioner(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    cool = raw.get("냉방 능력", raw.get("냉방능력", ""))
    r["cooling_capacity_btu"] = normalize_unit_value(cool)
    r["form_type"] = raw.get("형태", raw.get("에어컨 형태", "")).strip() or None

    r["energy_rating"] = normalize_energy_rating(raw.get("에너지소비효율", ""))

    heat_text = raw.get("냉난방 겸용", raw.get("난방", ""))
    r["heating_cooling"] = normalize_bool(heat_text) if heat_text else False

    filt = raw.get("필터 종류", raw.get("필터", ""))
    r["filter_type"] = filt.strip() or None

    noise = raw.get("소음", raw.get("실내기 소음(냉방)", ""))
    r["noise_level"] = normalize_unit_value(noise)

    airflow = raw.get("풍량", raw.get("냉방 풍량", ""))
    r["airflow"] = normalize_unit_value(airflow)

    smart = raw.get("스마트 기능", raw.get("Wi-Fi", raw.get("IoT", "")))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if normalize_bool(smart) else "미지원") if smart else "미지원"

    r.update(_meta(raw))
    return r


# ─── 식기세척기 ──────────────────────────────────────────────────────────────

def parse_dishwasher(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    r["install_type"] = raw.get("설치 방식", raw.get("설치방식", "")).strip() or None
    cap = raw.get("세척 용량", raw.get("세척용량", raw.get("식기 용량", "")))
    r["capacity_sets"] = normalize_unit_value(cap)

    r["energy_rating"] = normalize_energy_rating(raw.get("에너지소비효율", ""))

    modes = raw.get("세척코스", raw.get("코스 수", raw.get("코스수", "")))
    r["mode_count"] = normalize_unit_value(modes)

    dry = raw.get("건조 방식", raw.get("건조방식", ""))
    r["dry_method"] = dry.strip() or None

    noise = raw.get("소음", "")
    r["noise_level"] = normalize_unit_value(noise)

    smart = raw.get("스마트 기능", raw.get("Wi-Fi", raw.get("IoT", "")))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if normalize_bool(smart) else "미지원") if smart else "미지원"

    r.update(_meta(raw))
    return r


# ─── 공기청정기 ──────────────────────────────────────────────────────────────

def parse_air_purifier(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    area = raw.get("적용 면적", raw.get("적용면적", raw.get("청정 면적", "")))
    r["coverage_m2"] = normalize_unit_value(area)
    filt = raw.get("필터 종류", raw.get("필터", ""))
    r["filter_type"] = filt.strip() or None

    cadr = raw.get("CADR", raw.get("청정 능력(CADR)", raw.get("청정능력", "")))
    r["cadr"] = normalize_unit_value(cadr)

    noise = raw.get("소음", raw.get("최대 소음", ""))
    r["noise_level"] = normalize_unit_value(noise)

    sensor = raw.get("센서 종류", raw.get("센서", ""))
    r["sensor_type"] = sensor.strip() or None

    life = raw.get("필터 교체 주기", raw.get("필터교체주기", ""))
    r["filter_lifespan_months"] = normalize_unit_value(life)

    smart = raw.get("스마트 기능", raw.get("Wi-Fi", raw.get("IoT", "")))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if normalize_bool(smart) else "미지원") if smart else "미지원"

    r.update(_meta(raw))
    return r


# ─── 청소기 ──────────────────────────────────────────────────────────────────

def parse_vacuum(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    r["form_type"]   = raw.get("형태", raw.get("청소기 형태", "")).strip() or None
    r["cord_type"]   = raw.get("유무선", raw.get("전원 방식", "")).strip() or None

    suction = raw.get("흡입력", raw.get("최대 흡입력", ""))
    r["suction_power_w"] = normalize_unit_value(suction)

    battery = raw.get("배터리 용량", raw.get("배터리", ""))
    r["battery_mah"] = normalize_unit_value(battery)

    dust = raw.get("먼지통 용량", raw.get("먼지통", ""))
    r["dust_bin_l"] = normalize_unit_value(dust)

    noise = raw.get("소음", "")
    r["noise_level"] = normalize_unit_value(noise)

    acc = raw.get("부속품 수", raw.get("구성품 수", raw.get("액세서리", "")))
    r["accessory_count"] = normalize_unit_value(acc)

    r.update(_meta(raw))
    return r


# ─── 로봇청소기 ──────────────────────────────────────────────────────────────

def parse_robot_vacuum(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    suction = raw.get("흡입력", raw.get("최대 흡입력", ""))
    r["suction_pa"] = normalize_unit_value(suction)
    mop = raw.get("물걸레", raw.get("물걸레 기능", ""))
    r["mop_function"] = normalize_bool(mop) if mop else False

    mapping = raw.get("매핑 방식", raw.get("매핑방식", raw.get("지도 생성", "")))
    r["mapping_type"] = mapping.strip() or None

    battery = raw.get("배터리 용량", raw.get("배터리", raw.get("연속 사용 시간", "")))
    r["battery_min"] = normalize_unit_value(battery)

    auto_empty = raw.get("자동 먼지 비움", raw.get("자동먼지비움", raw.get("자동비움", "")))
    r["auto_empty"] = normalize_bool(auto_empty) if auto_empty else False

    noise = raw.get("소음", "")
    r["noise_level"] = normalize_unit_value(noise)

    smart = raw.get("스마트 기능", raw.get("Wi-Fi", raw.get("앱 연동", "")))
    r["smart_features"] = "AI" if "AI" in smart else ("기본" if normalize_bool(smart) else "미지원") if smart else "미지원"

    r.update(_meta(raw))
    return r


# ─── 전자레인지 ──────────────────────────────────────────────────────────────

def parse_microwave(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    cap = raw.get("용량", raw.get("내부 용량", ""))
    r["capacity_l"] = normalize_unit_value(cap)
    r["form_type"]  = raw.get("형태", raw.get("전자레인지 형태", "")).strip() or None

    output = raw.get("출력", raw.get("마이크로파 출력", ""))
    r["output_w"] = normalize_unit_value(output)

    modes = raw.get("조리 기능", raw.get("조리기능", raw.get("메뉴 수", "")))
    r["mode_count"] = normalize_unit_value(modes)

    coating = raw.get("내부 코팅", raw.get("내부코팅", ""))
    r["inner_coating"] = coating.strip() or None

    r["energy_rating"] = normalize_energy_rating(raw.get("에너지소비효율", ""))

    r.update(_meta(raw))
    return r


# ─── 모니터 ──────────────────────────────────────────────────────────────────

def parse_monitor(raw: dict[str, str]) -> dict[str, Any]:
    r: dict[str, Any] = {}

    size_text = raw.get("화면 크기", raw.get("화면크기", ""))
    m = re.search(r"(\d+\.?\d*)\s*인치", size_text)
    r["screen_size"] = float(m.group(1)) if m else None

    panel = raw.get("패널 종류", raw.get("패널", ""))
    r["panel_type"] = panel.split("/")[0].strip() or None

    res = raw.get("해상도", "")
    r["resolution"] = (
        "8K" if "8K" in res
        else "4K UHD" if ("4K" in res or "UHD" in res or "3840" in res)
        else "QHD" if ("QHD" in res or "2560" in res or "2K" in res)
        else "FHD" if ("FHD" in res or "1920" in res)
        else res.strip() or None
    )

    # 등급 스펙
    refresh = raw.get("주사율", raw.get("화면재생빈도", ""))
    r["refresh_rate"] = normalize_unit_value(refresh)

    resp = raw.get("응답속도", raw.get("응답 속도", ""))
    r["response_time_ms"] = normalize_unit_value(resp)

    hdr = raw.get("HDR", raw.get("HDR 지원", ""))
    r["hdr"] = (
        "돌비비전" if ("돌비비전" in hdr or "Dolby" in hdr)
        else "HDR10+" if "HDR10+" in hdr
        else "HDR10"  if "HDR10" in hdr
        else "미지원"
    )

    gamut = raw.get("색재현율", raw.get("색 재현율", ""))
    r["color_gamut_pct"] = normalize_unit_value(gamut)

    pivot = raw.get("피벗", raw.get("높낮이 조절", ""))
    r["pivot"] = normalize_bool(pivot) if pivot else False

    speaker = raw.get("스피커", raw.get("내장 스피커", ""))
    r["speakers"] = normalize_bool(speaker) if speaker else False

    r.update(_meta(raw))
    return r


# ─── 파서 라우터 ─────────────────────────────────────────────────────────────

PARSERS: dict[str, Any] = {
    "tv":              parse_tv,
    "refrigerator":    parse_refrigerator,
    "washer":          parse_washer,
    "dryer":           parse_dryer,
    "air_conditioner": parse_air_conditioner,
    "dishwasher":      parse_dishwasher,
    "air_purifier":    parse_air_purifier,
    "vacuum":          parse_vacuum,
    "robot_vacuum":    parse_robot_vacuum,
    "microwave":       parse_microwave,
    "monitor":         parse_monitor,
}


def parse_spec(category: str, raw: dict[str, str]) -> dict[str, Any]:
    """
    카테고리 이름과 raw 스펙 딕셔너리를 받아 구조화된 스펙 반환.
    등록되지 않은 카테고리는 raw를 그대로 반환 (fallback).
    """
    parser = PARSERS.get(category)
    if parser is None:
        # 알 수 없는 카테고리: raw 그대로 + 메타만 정리
        result = dict(raw)
        result.update(_meta(raw))
        return result
    return parser(raw)
