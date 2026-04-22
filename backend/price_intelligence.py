"""
price_intelligence.py — CPI(경쟁가격지수) 및 VFM(가성비) 분석 엔진
"""
from typing import Any

def calculate_cpi(company_price: int, competitor_price: int) -> float:
    """
    CPI (Competitive Price Index) 계산.
    100: 가격 평형
    100 미만: 경쟁사보다 저렴 (가격 경쟁력 우위)
    100 초과: 경쟁사보다 비쌈 (프리미엄 정당화 필요)
    """
    if not company_price or not competitor_price:
        return 0.0
    return round((company_price / competitor_price) * 100, 2)

def calculate_vfm(score: float, price: int) -> float:
    """
    VFM (Value for Money) 계산. (점수 / 가격) * 10,000
    높을수록 가성비가 좋음.
    """
    if not price or not score:
        return 0.0
    return round((score / price) * 10000, 4)

def get_price_adequacy_verdict(cpi: float, score_diff: float) -> dict[str, Any]:
    """
    CPI와 스펙 차이(company - competitor)를 기반으로 가격 적정성 판정.
    """
    verdict = "UNKNOWN"
    reason = ""
    
    # 7단계 전략적 판정 매트릭스
    if cpi <= 85:
        if score_diff >= -5:
            verdict = "과도한 저가"
            reason = "스펙 대비 가격이 너무 낮아 마진 확보 저조 가능성"
        else:
            verdict = "공격적 가격"
            reason = "스펙 열세를 가격으로 극복 중"
    elif 85 < cpi <= 95:
        if score_diff >= 5:
            verdict = "가성비 우위"
            reason = "스펙 우위와 가격 경쟁력 동시 확보"
        else:
            verdict = "합리적 경쟁"
            reason = "경쟁사 대비 적정 수준의 가격 우위"
    elif 95 < cpi <= 105:
        verdict = "가격 평형"
        reason = "시장에서 경쟁사와 대등한 가격/스펙 포지셔닝"
    elif 105 < cpi <= 115:
        if score_diff >= 10:
            verdict = "프리미엄 정당화"
            reason = "높은 스펙 우위가 가격 인상을 뒷받침함"
        else:
            verdict = "가격 열세"
            reason = "스펙 대비 가격이 비싸 경쟁력 저하 우려"
    else: # cpi > 115
        if score_diff >= 15:
            verdict = "고가 프리미엄"
            reason = "최상위 스펙 기반의 고가 정책"
        else:
            verdict = "과항 고가"
            reason = "스펙 대비 가격이 지나치게 높아 판매 부진 가능성"

    return {
        "verdict": verdict,
        "reason": reason,
        "cpi": cpi,
        "score_diff": round(score_diff, 2)
    }
