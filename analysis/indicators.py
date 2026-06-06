"""
analysis/indicators.py
순수 함수 기술지표.
"""
import math
from typing import List, Optional, Dict, Any


def sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - (100 / (1 + rs))


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    if len(closes) < slow + signal:
        return {"macd": None, "signal": None, "hist": None, "cross_up": False, "cross_down": False}
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    diff = len(ef) - len(es)
    if diff > 0:
        ef = ef[diff:]
    line = [a - b for a, b in zip(ef, es)]
    if len(line) < signal:
        return {"macd": line[-1] if line else None, "signal": None, "hist": None,
                "cross_up": False, "cross_down": False}
    sig = ema_series(line, signal)
    if not sig:
        return {"macd": line[-1], "signal": None, "hist": None,
                "cross_up": False, "cross_down": False}
    m = line[-1]
    s = sig[-1]
    cu = cd = False
    if len(line) >= 2 and len(sig) >= 2:
        if line[-2] < sig[-2] and m > s: cu = True
        if line[-2] > sig[-2] and m < s: cd = True
    return {"macd": m, "signal": s, "hist": m - s, "cross_up": cu, "cross_down": cd}


def bollinger(closes: List[float], period: int = 20, stdev: float = 2.0) -> Dict:
    if len(closes) < period:
        return {"upper": None, "middle": None, "lower": None, "position": None}
    w = closes[-period:]
    m = sum(w) / period
    sd = math.sqrt(sum((v - m) ** 2 for v in w) / period)
    u = m + stdev * sd
    l = m - stdev * sd
    p = closes[-1]
    return {
        "upper": u, "middle": m, "lower": l,
        "position": (p - l) / (u - l) if u != l else 0.5,
    }


def ma_cross(closes: List[float], short: int, long: int) -> Dict:
    if len(closes) < long + 1:
        return {"golden_cross": False, "dead_cross": False, "short_above_long": False}
    sn = sma(closes, short)
    ln = sma(closes, long)
    sp = sma(closes[:-1], short)
    lp = sma(closes[:-1], long)
    if None in (sn, ln, sp, lp):
        return {"golden_cross": False, "dead_cross": False, "short_above_long": False}
    return {
        "golden_cross": sp <= lp and sn > ln,
        "dead_cross": sp >= lp and sn < ln,
        "short_above_long": sn > ln,
    }


def alignment(closes: List[float]) -> str:
    """이평선 배열 상태"""
    m5 = sma(closes, 5)
    m20 = sma(closes, 20)
    m60 = sma(closes, 60)
    m120 = sma(closes, 120) if len(closes) >= 120 else None
    if None in (m5, m20, m60):
        return "unknown"
    if m120 is not None:
        if m5 > m20 > m60 > m120:
            return "perfect_uptrend"
        if m5 < m20 < m60 < m120:
            return "perfect_downtrend"
    if m5 > m20 > m60:
        return "uptrend"
    if m5 < m20 < m60:
        return "downtrend"
    return "sideways"


def support_resistance(closes: List[float], highs: List[float], lows: List[float], lookback: int = 60) -> Dict:
    if not closes or len(closes) < 10:
        return {"resistance": None, "support": None}
    h = highs[-lookback:] if len(highs) >= lookback else highs
    l = lows[-lookback:] if len(lows) >= lookback else lows
    cur = closes[-1]
    above = [x for x in h if x > cur]
    below = [x for x in l if x < cur]
    r = min(above) if above else max(h)
    s = max(below) if below else min(l)
    return {
        "resistance": r,
        "support": s,
        "to_resistance_pct": (r / cur - 1) * 100 if r else None,
        "to_support_pct": (s / cur - 1) * 100 if s else None,
    }


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


def volume_analysis(volumes: List[int], period: int = 20) -> Dict:
    if len(volumes) < period:
        return {"avg": 0, "ratio": 0, "spike": False, "drying": False}
    avg = sum(volumes[-period:-1]) / (period - 1) if period > 1 else volumes[-1]
    today = volumes[-1]
    ratio = today / avg if avg > 0 else 0
    return {
        "avg": avg,
        "today": today,
        "ratio": ratio,
        "spike": ratio >= 2.0,
        "extreme_spike": ratio >= 5.0,
        "drying": ratio < 0.3,
    }


def analyze_bars(bars: List[Dict]) -> Dict[str, Any]:
    """일봉 데이터로 전체 지표 계산.
    bars: [{date, open, high, low, close, volume}, ...]
    """
    if not bars or len(bars) < 5:
        return {"error": "데이터 부족", "bars_count": len(bars) if bars else 0}
    
    sb = sorted(bars, key=lambda x: x.get("date", ""))
    closes = [b["close"] for b in sb if b.get("close")]
    highs = [b["high"] for b in sb if b.get("high")]
    lows = [b["low"] for b in sb if b.get("low")]
    volumes = [b.get("volume", 0) for b in sb]
    
    if not closes:
        return {"error": "종가 없음"}
    
    cur = closes[-1]
    return {
        "current_price": cur,
        "bars_count": len(sb),
        "sma": {
            "5": sma(closes, 5),
            "20": sma(closes, 20),
            "60": sma(closes, 60),
            "120": sma(closes, 120) if len(closes) >= 120 else None,
            "200": sma(closes, 200) if len(closes) >= 200 else None,
        },
        "alignment": alignment(closes),
        "above_ma20": cur > (sma(closes, 20) or 0),
        "above_ma60": cur > (sma(closes, 60) or 0),
        "above_ma120": cur > (sma(closes, 120) or 0) if len(closes) >= 120 else None,
        "ma_cross_5_20": ma_cross(closes, 5, 20),
        "ma_cross_20_60": ma_cross(closes, 20, 60),
        "rsi": rsi(closes, 14),
        "macd": macd(closes),
        "bollinger": bollinger(closes),
        "support_resistance": support_resistance(closes, highs, lows),
        "atr": atr(highs, lows, closes),
        "volume": volume_analysis(volumes),
        "change_5d_pct": (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else None,
        "change_20d_pct": (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else None,
        "change_60d_pct": (closes[-1] / closes[-61] - 1) * 100 if len(closes) >= 61 else None,
    }
