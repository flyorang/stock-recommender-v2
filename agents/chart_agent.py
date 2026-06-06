"""
agents/chart_agent.py
차트 분석가 - AI 없이 코드 계산.

입력: 일봉/주봉 분석 결과
출력: {score, daily_trend, weekly_trend, key_signals, support, resistance, comment}
"""
from typing import Dict, Any, List


def evaluate(daily: Dict, weekly: Dict = None) -> Dict[str, Any]:
    """차트 점수 계산.
    
    Args:
        daily: indicators.analyze_bars() 결과
        weekly: 주봉 분석 결과 (선택)
    """
    if daily.get("error"):
        return {"score": 0, "comment": "차트 데이터 부족", "key_signals": []}
    
    score = 50  # 기본
    signals = []
    
    # 1. 일봉 추세 (가중 40%)
    align = daily.get("alignment", "unknown")
    if align == "perfect_uptrend":
        score += 25
        signals.append("완전 정배열")
    elif align == "uptrend":
        score += 18
        signals.append("정배열")
    elif align == "sideways":
        score += 0
    elif align == "downtrend":
        score -= 18
        signals.append("역배열")
    elif align == "perfect_downtrend":
        score -= 25
        signals.append("완전 역배열")
    
    # 2. 골든/데드 크로스 (가중 15%)
    gc520 = daily.get("ma_cross_5_20", {})
    gc2060 = daily.get("ma_cross_20_60", {})
    if gc520.get("golden_cross"):
        score += 8
        signals.append("5-20 골든크로스")
    if gc2060.get("golden_cross"):
        score += 12
        signals.append("20-60 골든크로스")
    if gc520.get("dead_cross"):
        score -= 8
        signals.append("5-20 데드크로스")
    if gc2060.get("dead_cross"):
        score -= 12
        signals.append("20-60 데드크로스")
    
    # 3. MACD (가중 15%)
    macd = daily.get("macd", {})
    if macd.get("cross_up"):
        score += 10
        signals.append("MACD 양전환")
    elif macd.get("cross_down"):
        score -= 10
        signals.append("MACD 음전환")
    elif macd.get("hist") is not None:
        if macd["hist"] > 0:
            score += 3
    
    # 4. RSI (가중 10%)
    rsi_v = daily.get("rsi")
    if rsi_v is not None:
        if rsi_v >= 80:
            score -= 12
            signals.append(f"RSI {rsi_v:.0f} 극과매수")
        elif rsi_v >= 70:
            score -= 5
            signals.append(f"RSI {rsi_v:.0f} 과매수")
        elif rsi_v <= 25:
            score += 8
            signals.append(f"RSI {rsi_v:.0f} 과매도")
        elif 40 <= rsi_v <= 65:
            score += 3
    
    # 5. 볼린저밴드 (가중 5%)
    bb = daily.get("bollinger", {})
    pos = bb.get("position")
    if pos is not None:
        if pos > 0.95:
            score -= 3
        elif pos < 0.1:
            score += 3
    
    # 6. 거래량 (가중 15%)
    vol = daily.get("volume", {})
    ratio = vol.get("ratio", 0)
    if vol.get("extreme_spike"):
        # 너무 큰 폭증은 위험 신호
        score -= 5
        signals.append("거래량 비정상 폭증")
    elif vol.get("spike"):
        if align in ("uptrend", "perfect_uptrend"):
            score += 8
            signals.append("거래량 동반 상승")
        else:
            score += 2
    elif vol.get("drying"):
        score -= 3
    
    # 7. 주봉 추세 (보너스 +/-5)
    weekly_trend = "unknown"
    if weekly and not weekly.get("error"):
        wa = weekly.get("alignment", "unknown")
        if wa in ("uptrend", "perfect_uptrend"):
            score += 5
            weekly_trend = "상승"
        elif wa in ("downtrend", "perfect_downtrend"):
            score -= 5
            weekly_trend = "하락"
        else:
            weekly_trend = "횡보"
    
    # 8. 20일선 위/아래
    if daily.get("above_ma20") is False:
        score -= 5
    if daily.get("above_ma60") is False:
        score -= 3
    
    # 클램프
    score = max(0, min(100, score))
    
    sr = daily.get("support_resistance", {})
    
    # 코멘트 생성
    if score >= 75:
        comment = f"강한 상승 신호 ({', '.join(signals[:2])})"
    elif score >= 60:
        comment = f"긍정적 ({', '.join(signals[:2]) or '추세 양호'})"
    elif score >= 45:
        comment = "혼조세, 방향성 확인 필요"
    elif score >= 30:
        comment = "약세 진입, 매수 보류"
    else:
        comment = "하락 추세, 회피"
    
    return {
        "score": round(score, 1),
        "daily_trend": align,
        "weekly_trend": weekly_trend,
        "key_signals": signals[:5],
        "support": sr.get("support"),
        "resistance": sr.get("resistance"),
        "rsi": rsi_v,
        "macd_status": "양전환" if macd.get("cross_up") else
                       "음전환" if macd.get("cross_down") else
                       "강세" if (macd.get("hist") or 0) > 0 else "약세",
        "comment": comment,
    }
