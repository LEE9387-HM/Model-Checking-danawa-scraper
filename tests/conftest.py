"""
conftest.py — pytest 공통 설정 + fixtures
"""
import sys
from pathlib import Path

# backend 패키지를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


import pytest


# ─── 공통 샘플 스펙 ──────────────────────────────────────────────────────────

@pytest.fixture
def tv_raw():
    return {
        "화면 크기": "65인치",
        "해상도": "4K UHD",
        "패널 종류": "QLED",
        "주사율": "120Hz",
        "HDR": "HDR10+",
        "스마트 TV": "AI 스마트TV",
        "스피커 출력": "60W",
        "돌비 애트모스": "지원",
        "에너지소비효율": "2등급",
        "두께": "25mm",
        "__price__": "1800000",
        "__brand__": "삼성전자",
        "__review_count__": "1200",
        "출시년월": "2024년 1월",
    }


@pytest.fixture
def tv_spec(tv_raw):
    from spec_parser import parse_spec
    return parse_spec("tv", tv_raw)


@pytest.fixture
def washer_raw():
    return {
        "세탁 용량": "24kg",
        "형태": "드럼",
        "에너지소비효율": "1등급",
        "탈수 회전수": "1400RPM",
        "세탁코스": "22코스",
        "스팀": "지원",
        "소음": "44dB",
        "스마트 기능": "AI 세탁",
        "__price__": "1500000",
        "__brand__": "삼성전자",
        "__review_count__": "300",
    }


@pytest.fixture
def monitor_raw():
    return {
        "화면 크기": "27인치",
        "패널 종류": "IPS",
        "해상도": "QHD (2560x1440)",
        "주사율": "165Hz",
        "응답속도": "1ms",
        "HDR": "HDR10",
        "색재현율": "99% sRGB",
        "피벗": "지원",
        "스피커": "미지원",
        "__price__": "450000",
        "__brand__": "LG전자",
        "__review_count__": "800",
    }
