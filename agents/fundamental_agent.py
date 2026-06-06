"""
agents/fundamental_agent.py
펀더멘털 분석가 - 코드 계산 (PER/PBR/ROE/매출 추세 기반).
"""
from typing import Dict, Any, Optional


def evaluate(
    quote: Dict,
    profile: Optional[Dict] = None,
    metrics: Optional[Dict] = None,
    is_krx: bool = True,
) -> Dict[str, Any]:
    """펀더멘털 점수.
    
    국장: quote에 per, pbr 포함 (한투 응답)
    미장: profile + metrics 활용 (Finnhub)
    """
    score = 50
    signals = []
    
    if is_krx:
        per = quote.get("per", 0)
        pbr = quote.get("pbr", 0)
        eps = quote.get("eps", 0)
        mc = quote.get("market_cap", 0)
        h52 = quote.get("high_52w", 0)
        l52 = quote.get("low_52w", 0)
        roe = None  # 한투 시세에는 ROE 없음
    else:
        m = metrics or {}
        per = m.get("pe", 0)
        pbr = m.get("pb", 0)
        roe = m.get("roe", 0)
        eps = 0
        h52 = m.get("high_52w", 0)
        l52 = m.get("low_52w", 0)
        mc = (profile or {}).get("market_cap_musd", 0) * 1_000_000
    
    cur_price = quote.get("price", 0)
    
    # 1. PER 평가
    if per > 0:
        if per < 10:
            score += 15
            signals.append(f"저PER ({per:.1f})")
        elif per < 20:
            score += 5
        elif per > 60:
            score -= 12
            signals.append(f"고PER ({per:.1f})")
        elif per > 35:
            score -= 5
    
    # 2. PBR
    if pbr > 0:
        if pbr < 1.0:
            score += 10
            signals.append(f"저PBR ({pbr:.1f})")
        elif pbr < 3.0:
            score += 3
        elif pbr > 8:
            score -= 8
            signals.append(f"고PBR ({pbr:.1f})")
    
    # 3. ROE (미장만)
    if roe is not None and roe > 0:
        if roe > 20:
            score += 12
            signals.append(f"고ROE ({roe:.1f}%)")
        elif roe > 10:
            score += 5
        elif roe < 5:
            score -= 5
    
    # 4. 52주 가격 위치
    if h52 > 0 and l52 > 0 and cur_price > 0:
        position_52w = (cur_price - l52) / (h52 - l52) if h52 != l52 else 0.5
        if 0.4 <= position_52w <= 0.7:
            score += 5  # 적정 구간
        elif position_52w > 0.95:
            score -= 5
            signals.append("52주 신고가 근접")
        elif position_52w < 0.2:
            score += 3  # 저점 반등 기대
    
    # 5. 매출/EPS 성장 (미장)
    if not is_krx and metrics:
        rev_g = metrics.get("revenue_growth_ttm", 0)
        eps_g = metrics.get("eps_growth_ttm", 0)
        if rev_g > 20:
            score += 8
            signals.append(f"매출성장 {rev_g:.0f}%")
        elif rev_g > 5:
            score += 3
        elif rev_g < -10:
            score -= 8
        
        if eps_g > 30:
            score += 5
        elif eps_g < -20:
            score -= 5
    
    score = max(0, min(100, score))
    
    # 평가
    if score >= 70:
        valuation = "저평가/우량"
    elif score >= 55:
        valuation = "적정"
    elif score >= 40:
        valuation = "다소 부담"
    else:
        valuation = "고평가/부실"
    
    # 코멘트
    if signals:
        comment = f"{valuation} ({', '.join(signals[:2])})"
    else:
        comment = valuation
    
    return {
        "score": round(score, 1),
        "valuation": valuation,
        "per": per,
        "pbr": pbr,
        "roe": roe,
        "key_signals": signals,
        "comment": comment,
    }
