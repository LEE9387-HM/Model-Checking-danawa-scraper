"""
similarity.py — 코사인 유사도 계산 + 복합 랭킹 산출
"""
import math
from typing import Any


def _build_vector(spec: dict[str, Any], grading_specs: dict[str, dict]) -> list[float]:
    """가중치가 적용된 수치 벡터 생성."""
    vec = []
    # grading_specs에 정의된 순서대로 벡터 생성
    for name, spec_def in grading_specs.items():
        val = spec.get(name)
        weight = float(spec_def.get("weight", 1.0))
        
        # scoring.py의 _score_spec 로직과 유사하게 0~10점 스케일로 정규화된 값을 가져오면 좋겠지만,
        # 여기서는 단순 가중치 기반 벡터를 구성 (나중에 scoring.py의 결과를 활용하도록 개선 가능)
        if isinstance(val, bool):
            score = 10.0 if val else 0.0
        elif isinstance(val, (int, float)):
            # 연속값은 벡터 구성 시 직접 넣기보다 해당 카테고리의 룰에 따라 변환된 점수가 유리함
            # 여기서는 편의상 float 변환 (추후 score_model 결과 연동 권장)
            score = float(val)
        else:
            score = 0.0
            
        vec.append(score * weight)
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
    samsung_data: dict[str, Any],
    competitors: list[dict[str, Any]],
    rules: dict[str, Any],
    similarity_threshold: float = 0.70,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    경쟁사 모델 목록에서 코사인 유사도 필터 후 복합 랭킹 정렬.
    엄격한 세그먼트 매칭(Primary Specs 일치) 및 출시년도 일치 필수.
    """
    from price_intelligence import calculate_cpi, calculate_vfm
    
    grading_specs = rules.get("grading_specs", {})
    primary_specs = rules.get("primary_specs", [])
    samsung_spec = samsung_data.get("spec", {})
    samsung_price = samsung_data.get("price", 0)
    samsung_score = samsung_data.get("score", {}).get("total_score", 0)
    samsung_year = samsung_spec.get("release_year")
    
    samsung_vec = _build_vector(samsung_spec, grading_specs)
    total = len(competitors)

    filtered = []
    for i, comp in enumerate(competitors):
        comp_spec = comp.get("spec", {})
        
        # 0) 출시년도 및 주요 스펙(Primary Specs) 일치 여부 확인
        # 삼성/경쟁사 모두 출시년도가 있는 경우에만 동일년도 체크 (크롤러에서 이미 필터링되지만 재검증)
        comp_year = comp_spec.get("release_year")
        is_same_year = (samsung_year == comp_year) if (samsung_year and comp_year) else True
        
        # 주요 스펙(화면 크기, 패널 종류 등)이 일치하는지 확인 (세그먼트 정규화)
        primary_match = True
        for ps in primary_specs:
            if ps == "release_year": continue
            if str(samsung_spec.get(ps, "")).strip() != str(comp_spec.get(ps, "")).strip():
                primary_match = False
                break
        
        # 출시년도가 다르거나 주요 스펙이 다르면 CPI 분석 대상에서 제외하거나 점수 대폭 삭감
        # 여기서는 사용자의 요청에 따라 '동일 조건' 모델 위주로 필터링
        if not is_same_year: 
            continue # N+1 모델 방지
            
        comp_vec = _build_vector(comp_spec, grading_specs)
        sim = cosine_similarity(samsung_vec, comp_vec)
        
        # 주요 스펙이 일치하지 않으면 유사도가 높더라도 순위에서 밀려나도록 조정
        if not primary_match:
            sim *= 0.5 
            
        if sim >= (similarity_threshold * 0.5): # 관대한 필터 후 랭킹에서 조정
            comp_price = comp.get("price", 0)
            comp_score = comp.get("score", {}).get("total_score", 0)
            
            cpi = calculate_cpi(samsung_price, comp_price)
            vfm = calculate_vfm(comp_score, comp_price)
            
            filtered.append({
                **comp, 
                "similarity": sim, 
                "primary_match": primary_match,
                "cpi": cpi,
                "vfm": vfm,
                "_idx": i
            })

    if not filtered:
        return []

    # ─ 정규화 및 랭킹 ─
    max_rank = total
    max_reviews = max((c.get("review_count", 0) for c in filtered), default=1) or 1
    
    ranked = []
    for comp in filtered:
        # 1. 인기점수 (Inverse Rank)
        pop_rank = comp.get("popularity_rank", max_rank)
        pop_score = (max_rank - pop_rank) / max(max_rank - 1, 1)

        # 2. 리뷰점수
        reviews = comp.get("review_count", 0)
        review_score = min(reviews / max_reviews, 1.0)

        # 3. 복합 유사도 (Primary Match 가중치 부여)
        # 주요 스펙이 일치하는 모델에게 압도적 가중치 (0.4 -> 0.6 등으로 조정 가능)
        sim = comp["similarity"]
        match_bonus = 0.2 if comp["primary_match"] else 0.0
        
        # 4. 가격 근접성
        price_closeness = 1.0 - min(abs(100 - comp["cpi"]) / 100, 1.0)
        
        # 합산: 유사도(30%) + 주요스펙보너스(20%) + 인기(25%) + 리뷰(15%) + 가격근접성(10%)
        composite = sim * 0.3 + match_bonus + pop_score * 0.25 + review_score * 0.15 + price_closeness * 0.1
        comp["composite_rank_score"] = round(composite, 4)
        ranked.append(comp)

    # ─ 정렬 후 top_n ─
    ranked.sort(key=lambda x: x["composite_rank_score"], reverse=True)
    for i, item in enumerate(ranked[:top_n]):
        item["rank"] = i + 1

    return ranked[:top_n]
