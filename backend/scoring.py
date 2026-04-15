"""
scoring.py — 카테고리 룰셋 기반 가중 점수 계산 (0~100점)
"""
import json
import math
from pathlib import Path
from typing import Any

RULES_DIR = Path(__file__).parent / "rules"


def load_rules(category: str) -> dict:
    """rules/{category}.json 로드"""
    path = RULES_DIR / f"{category}.json"
    if not path.exists():
        raise FileNotFoundError(f"룰셋 파일 없음: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _score_spec(value: Any, spec_def: dict, all_values: list[float | None]) -> float:
    """
    단일 스펙의 raw 점수를 계산 (0.0 ~ 10.0).

    - levels 있는 경우: levels 딕셔너리에서 직접 매핑
    - boolean: true_value / false_value
    - 연속값: Min-Max 정규화 후 direction 적용
    """
    if value is None:
        return 0.0

    direction = spec_def.get("direction", "higher_better")

    # 1) levels 매핑
    if "levels" in spec_def:
        levels: dict = spec_def["levels"]
        key = str(value).strip()
        if key in levels:
            return float(levels[key])
        # 숫자 key인 경우 float로 변환해서 nearest 찾기
        try:
            num = float(value)
            numeric_levels = {float(k): float(v) for k, v in levels.items()}
            if direction == "higher_better":
                # 해당 값 이하인 것 중 최대 key 선택
                valid = [(k, v) for k, v in numeric_levels.items() if k <= num]
                if valid:
                    return float(max(valid, key=lambda x: x[0])[1])
            elif direction == "lower_better":
                valid = [(k, v) for k, v in numeric_levels.items() if k >= num]
                if valid:
                    return float(min(valid, key=lambda x: x[0])[1])
        except (TypeError, ValueError):
            pass
        return 0.0

    # 2) boolean
    if direction == "boolean":
        return float(spec_def.get("true_value", 10)) if value else float(spec_def.get("false_value", 0))

    # 3) 연속값 Min-Max 정규화
    numeric_values = [v for v in all_values if v is not None]
    if not numeric_values:
        return 0.0

    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0

    min_val = min(numeric_values)
    max_val = max(numeric_values)

    if math.isclose(max_val, min_val):
        return 5.0  # 모든 값 동일 → 중간 점수

    normalized = (num - min_val) / (max_val - min_val)
    if direction == "lower_better":
        normalized = 1.0 - normalized

    return round(normalized * 10, 4)


def score_model(category: str, spec: dict[str, Any], pool: list[dict[str, Any]] | None = None) -> dict:
    """
    단일 모델의 스펙을 채점.

    Args:
        category: 카테고리 이름 (예: 'tv')
        spec: 구조화된 스펙 딕셔너리
        pool: Min-Max 정규화용 동일 카테고리 모델 풀 (없으면 단일 모델 기준)

    Returns:
        {
          "total_score": 82.5,
          "breakdown": { "refresh_rate": 8.75, ... },
          "category": "tv"
        }
    """
    rules = load_rules(category)
    grading = rules["grading_specs"]

    if pool is None:
        pool = [spec]

    breakdown: dict[str, float] = {}
    total = 0.0

    for spec_name, spec_def in grading.items():
        weight = float(spec_def["weight"])
        # 풀 전체 값 수집 (Min-Max용)
        all_values = [m.get(spec_name) for m in pool]
        raw_score = _score_spec(spec.get(spec_name), spec_def, all_values)
        weighted = raw_score * weight * 10  # 0~10 → 0~100 환산 (weight 반영)
        breakdown[spec_name] = round(raw_score, 2)
        total += weighted

    return {
        "category": category,
        "total_score": round(total, 2),
        "breakdown": breakdown,
    }


def score_pool(category: str, models: list[dict[str, Any]]) -> list[dict]:
    """
    여러 모델을 동일 풀 기준으로 채점 (Min-Max 공유).
    반환: 각 모델에 score 결과가 추가된 리스트
    """
    results = []
    for model in models:
        score_result = score_model(category, model["spec"], pool=[m["spec"] for m in models])
        results.append({**model, "score": score_result})
    return results
