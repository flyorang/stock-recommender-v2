"""
agents/supply_agent.py
수급 분석가 - 외국인/기관 흐름 (국장) / 거래량 모멘텀 (미장).
"""
from typing import Dict, Any, Optional


def evaluate(
    quote: Dict,
    investor_flow: Optional[Dict] = None,
    indicators: Optional[Dict] = None,
    is_krx: bool = True,
) -> Dict[str, Any]:
    """수급 점수.
    
    국장: 외국인/기관 순매수
    미장: 거래량 모멘텀 + 가격 위치
    """
    score = 50
    signals = []
    
    if is_krx and investor_flow:
        # 외국인 5일 순매수
        f5 = investor_flow.get("foreign_net_5d", 0)
        f20 = investor_flow.get("foreign_net_20d", 0)
        ft = investor_flow.get("foreign_net_today", 0)
        i5 = investor_flow.get("institution_net_5d", 0)
        i20 = investor_flow.get("institution_net_20d", 0)
        
        # 외국인 (가중 50%)
        if f5 > 0 and f20 > 0:
            score += 18
            signals.append("외국인 5일/20일 순매수")
        elif f5 > 0:
            score += 10
            signals.append("외국인 5일 순매수")
        elif f5 < 0 and f20 < 0:
            score -= 15
            signals.append("외국인 5일/20일 순매도")
        elif f5 < 0:
            score -= 8
            signals.append("외국인 5일 순매도")
        
        # 오늘 흐름
        if ft > 0:
            score += 3
        elif ft < 0:
            score -= 2
        
        # 기관 (가중 30%)
        if i5 > 0 and i20 > 0:
            score += 10
            signals.append("기관 누적 매수")
        elif i5 > 0:
            score += 5
        elif i5 < 0 and i20 < 0:
            score -= 8
            signals.append("기관 매도세")
        elif i5 < 0:
            score -= 4
    else:
        # 미장: 거래량 + 가격 흐름
        if indicators:
            vol = indicators.get("volume", {})
            ratio = vol.get("ratio", 0)
            
            if vol.get("spike") and quote.get("change_pct", 0) > 0:
                score += 15
                signals.append("거래량 동반 상승")
            elif ratio > 1.5 and quote.get("change_pct", 0) > 0:
                score += 8
                signals.append("거래량 증가")
            elif vol.get("drying"):
                score -= 10
                signals.append("거래량 메마름")
            elif vol.get("extreme_spike"):
                score -= 5
                signals.append("거래량 비정상")
            
            # 가격 모멘텀
            ch5 = indicators.get("change_5d_pct", 0) or 0
            ch20 = indicators.get("change_20d_pct", 0) or 0
            if ch5 > 0 and ch20 > 0:
                score += 8
                signals.append("단기/중기 상승")
            elif ch5 > 5:
                score += 5
            elif ch5 < -5:
                score -= 5
    
    # 일반 거래량 활성도
    if indicators:
        vol = indicators.get("volume", {})
        ratio = vol.get("ratio", 0)
        if 1.0 <= ratio <= 2.5:
            score += 3  # 정상 활성
    
    score = max(0, min(100, score))
    
    # 흐름 요약
    if is_krx and investor_flow:
        f5 = investor_flow.get("foreign_net_5d", 0)
        foreign_flow = "유입" if f5 > 0 else "유출" if f5 < 0 else "중립"
        i5 = investor_flow.get("institution_net_5d", 0)
        inst_flow = "매수" if i5 > 0 else "매도" if i5 < 0 else "중립"
    else:
        foreign_flow = "N/A"
        inst_flow = "N/A"
    
    if score >= 70:
        comment = f"수급 강함 ({', '.join(signals[:2])})"
    elif score >= 55:
        comment = f"수급 양호"
    elif score >= 40:
        comment = "수급 중립"
    else:
        comment = "수급 부정적"
    
    return {
        "score": round(score, 1),
        "foreign_flow": foreign_flow,
        "institution_flow": inst_flow,
        "key_signals": signals,
        "comment": comment,
    }
