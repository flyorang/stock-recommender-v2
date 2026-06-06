"""
agents/risk_agent.py
리스크 매니저 - ATR 손절, 변동성, 실적일 임박 체크.
"""
from typing import Dict, Any, Optional


def evaluate(
    quote: Dict,
    indicators: Dict,
    earnings_date: Optional[Dict] = None,
    is_krx: bool = True,
) -> Dict[str, Any]:
    """리스크 점수 (높을수록 안전).
    
    + ATR 기반 손절가 계산
    """
    score = 70  # 기본 안전 가정
    warnings_list = []
    
    cur = quote.get("price", 0)
    atr_val = indicators.get("atr")
    
    # 1. 변동성 (ATR / 가격)
    volatility_level = "중"
    if atr_val and cur > 0:
        atr_pct = (atr_val / cur) * 100
        if atr_pct > 5:
            score -= 20
            volatility_level = "고"
            warnings_list.append(f"높은 변동성 (ATR {atr_pct:.1f}%)")
        elif atr_pct > 3:
            score -= 8
            volatility_level = "중상"
        elif atr_pct < 1:
            volatility_level = "저"
            score += 3
    
    # 2. 최근 변동폭
    ch5 = indicators.get("change_5d_pct")
    ch20 = indicators.get("change_20d_pct")
    if ch5 is not None and abs(ch5) > 15:
        score -= 10
        warnings_list.append(f"5일간 {ch5:+.1f}% 큰 변동")
    if ch20 is not None and abs(ch20) > 30:
        score -= 8
    
    # 3. RSI 극단
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi > 80:
            score -= 15
            warnings_list.append("RSI 80↑ 과매수")
        elif rsi < 20:
            score -= 8
            warnings_list.append("RSI 20↓ 과매도")
    
    # 4. 실적 발표 임박 (미장)
    event_warning = None
    if earnings_date:
        days = earnings_date.get("days_until")
        if days is not None and 0 <= days <= 5:
            score -= 12
            event_warning = f"실적발표 D-{days}"
            warnings_list.append(event_warning)
    
    # 5. 거래량 비정상
    vol = indicators.get("volume", {})
    if vol.get("extreme_spike"):
        score -= 12
        warnings_list.append("거래량 비정상 폭증 (작전 의심)")
    
    score = max(0, min(100, score))
    
    # ATR 기반 손절가 (2 ATR 아래)
    stop_loss_atr = None
    if atr_val and cur > 0:
        stop_loss_atr = round(cur - 2 * atr_val, 2 if not is_krx else 0)
        # 최소 -3%, 최대 -10% 제한
        min_stop = cur * 0.90  # -10%
        max_stop = cur * 0.97  # -3%
        stop_loss_atr = max(min_stop, min(max_stop, stop_loss_atr))
    
    # 최악 시나리오 (2 ATR 손실)
    max_loss_pct = None
    if atr_val and cur > 0:
        max_loss_pct = round((2 * atr_val / cur) * 100, 1)
    
    # 포지션 권장 (변동성 ↑ → 적게)
    if volatility_level == "고":
        position_pct = 3
    elif volatility_level == "중상":
        position_pct = 5
    elif volatility_level == "중":
        position_pct = 7
    else:
        position_pct = 10
    
    if score >= 70:
        comment = "리스크 낮음, 일반 진입 가능"
    elif score >= 50:
        comment = f"변동성 {volatility_level}, 신중 진입"
    elif score >= 30:
        comment = "리스크 높음, 비중 축소 권장"
    else:
        comment = "고위험, 진입 비추천"
    
    return {
        "score": round(score, 1),
        "volatility_level": volatility_level,
        "atr": atr_val,
        "atr_pct": (atr_val / cur * 100) if (atr_val and cur > 0) else None,
        "stop_loss_atr": stop_loss_atr,
        "max_loss_scenario_pct": max_loss_pct,
        "event_warning": event_warning,
        "warnings": warnings_list,
        "position_size_pct": position_pct,
        "comment": comment,
    }
