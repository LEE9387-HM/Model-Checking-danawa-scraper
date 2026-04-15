"""
similarity.py — 코사인 유사도 계산 + 복합 랭킹 산출
"""
import math
from typing import Any


def _build_vector(spec: dict[str, Any], spec_names: list[str]) -> list[float]:
    """스펙 딕셔너리를 수치 벡터로 변환 (없는 값은 0)"""
    vec = []
    for name in spec_names:
        val = spec.get(name)
        if isinstance(val, bool):
            vec.append(10.0 if val else 0.0)
        elif isinstance(val, (int, float)):
            vec.append(float(val))
        else:
            vec.append(0.0)
    return vec


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """두 벡터의 코사인 유사도 반환 (0.0 ~ 1.0)"""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a ** 2 for a in vec_a))
    norm_b = math.sqrt(sum(b ** 2 for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 4)


def filter_and_rank(
    samsung_spec: dict[str, Any],
    competitors: list[dict[str, Any]],
    spec_names: list[str],
    similarity_threshold: float = 0.75,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    경쟁사 모델 목록에서 코사인 유사도 필터 후 복합 랭킹 정렬.

    복합 랭킹 공식:
        최종 랭킹 = 인기순×0.5 + 리뷰수×0.3 + 유사도×0.2

    Args:
        samsung_spec: 삼성 모델 구조화 스펙
        competitors: [{spec, popularity_rank, review_count, ...}, ...]
            - popularity_rank: 다나와 인기순 순위 (1이 1위)
        spec_names: 유사도 비교에 사용할 스펙 이름 목록 (등급 스펙)
        similarity_threshold: 코사인 유사도 최소값
        top_n: 최종 반환 개수

    Returns:
        랭킹 순 정렬된 경쟁사 리스트 (similarity, composite_rank 필드 추가)
    """
    samsung_vec = _build_vector(samsung_spec, spec_names)
    total = len(competitors)

    # ─ 유사도 계산 ─
    filtered = []
    for i, comp in enumerate(competitors):
        comp_vec = _build_vector(comp["spec"], spec_names)
        sim = cosine_similarity(samsung_vec, comp_vec)
        if sim >= similarity_threshold:
            filtered.append({**comp, "similarity": sim, "_idx": i})

    if not filtered:
        return []

    # ─ 정규화 ─
    max_rank = total  # 인기순 최대값 (= 크롤링 대상 수)
    max_reviews = max((c.get("review_count", 0) for c in filtered), default=1) or 1
    min_reviews = min((c.get("review_count", 0) for c in filtered), default=0)

    ranked = []
    for comp in filtered:
        pop_rank = comp.get("popularity_rank", max_rank)
        # 인기순 역순 정규화: 1위=1.0, max_rank위=~0
        pop_score = (max_rank - pop_rank) / max(max_rank - 1, 1)

        reviews = comp.get("review_count", 0)
        review_score = (
            (reviews - min_reviews) / (max_reviews - min_reviews)
            if max_reviews != min_reviews
            else 0.5
        )

        sim = comp["similarity"]
        composite = pop_score * 0.5 + review_score * 0.3 + sim * 0.2

        ranked.append({**comp, "composite_rank_score": round(composite, 4)})

    # ─ 정렬 후 top_n ─
    ranked.sort(key=lambda x: x["composite_rank_score"], reverse=True)
    for i, item in enumerate(ranked[:top_n]):
        item["rank"] = i + 1

    return ranked[:top_n]
