"""
agents/pattern_agent.py — NEW (차트 패턴 분석가)

4가지 핵심 패턴 감지:
1. 눌림목 매수 (Pullback to MA): 20일선 지지 + 거래량 감소→증가
2. 돌파 후 되돌림 (Breakout & Retest): 전고점 돌파 후 -3~5% 조정
3. 갭상승 후 메우기 (Gap Fill): 갭상승 후 갭 메우러 가는 중
4. VCP 패턴 (Volatility Contraction): 변동성 수축 후 돌파 임박

AI 호출 X (코드 계산).
indicators.py에서 이미 계산된 데이터 활용.
"""
from typing import Dict, Any, List, Optional


def _detect_pullback_to_ma20(bars: List[Dict], indicators: Dict) -> Optional[Dict]:
    """눌림목 매수 패턴.
    
    조건:
    - 현재가가 20일선 위 0~3% (지지선 부근)
    - 5일 전부터 거래량 감소 추세
    - 최근 1~2일 거래량 회복
    - 20일선 자체가 상승 추세
    """
    if len(bars) < 25:
        return None

    cur = indicators.get("current_price", 0)
    ma20 = (indicators.get("sma") or {}).get("20")
    if not cur or not ma20:
        return None

    # 1. 20일선 위 0~3%
    diff_pct = (cur / ma20 - 1) * 100
    if diff_pct < -1 or diff_pct > 3:
        return None

    # 2. 정배열 또는 상승추세
    align = indicators.get("alignment", "")
    if align not in ("uptrend", "perfect_uptrend", "sideways"):
        return None

    # 3. 거래량 패턴 (5일 전부터 감소 → 최근 회복)
    sb = sorted(bars, key=lambda x: x.get("date", ""))
    if len(sb) < 7:
        return None
    vol_old = sum(b.get("volume", 0) for b in sb[-7:-3]) / 4  # 7~3일 전 평균
    vol_recent = sum(b.get("volume", 0) for b in sb[-2:]) / 2  # 최근 2일 평균

    if vol_recent > vol_old * 1.2:  # 최근 거래량 회복
        return {
            "pattern": "눌림목 매수",
            "confidence": 70,
            "evidence": f"20일선 +{diff_pct:.1f}% + 거래량 회복",
            "action": "지지선 확인 후 분할 매수",
        }
    return None


def _detect_breakout_retest(bars: List[Dict], indicators: Dict) -> Optional[Dict]:
    """돌파 후 되돌림 패턴.
    
    조건:
    - 최근 5~10일 내 전고점 돌파 시도
    - 현재가가 돌파선 -1~5% 지점
    - 거래량 양호
    """
    if len(bars) < 30:
        return None
    sb = sorted(bars, key=lambda x: x.get("date", ""))
    closes = [b["close"] for b in sb if b.get("close")]
    highs = [b.get("high", 0) for b in sb if b.get("high")]
    if len(closes) < 30:
        return None

    cur = closes[-1]
    # 30일 전~10일 전 사이의 고점
    prior_high_window = highs[-30:-10]
    if not prior_high_window:
        return None
    prior_high = max(prior_high_window)

    # 최근 10일 안에 prior_high 돌파한 적 있나
    recent_highs = highs[-10:]
    breakout = any(h > prior_high * 1.01 for h in recent_highs)
    if not breakout:
        return None

    # 현재가가 돌파선 -1~5% 지점 (재테스트)
    retest_pct = (cur / prior_high - 1) * 100
    if -5 <= retest_pct <= 1:
        # 거래량 확인 (전체 평균 대비)
        vol = (indicators.get("volume") or {}).get("ratio", 0)
        if vol >= 0.8:  # 거래량 너무 죽지 않음
            return {
                "pattern": "돌파 후 되돌림",
                "confidence": 75,
                "evidence": f"{int(prior_high)} 돌파 후 {retest_pct:+.1f}% 재테스트",
                "action": "지지 확인 시 매수",
            }
    return None


def _detect_gap_fill(bars: List[Dict], indicators: Dict) -> Optional[Dict]:
    """갭상승 후 메우기 패턴.
    
    조건:
    - 최근 10일 내 +3% 이상 갭상승 발생
    - 현재가가 갭 시작 가격 근처 (-1~3%)
    """
    if len(bars) < 12:
        return None
    sb = sorted(bars, key=lambda x: x.get("date", ""))
    if len(sb) < 12:
        return None

    cur = sb[-1].get("close", 0)
    if not cur:
        return None

    # 갭 찾기 (전날 종가 → 다음날 시가)
    gap_info = None
    for i in range(len(sb) - 10, len(sb) - 1):
        if i < 1:
            continue
        prev_close = sb[i - 1].get("close", 0)
        today_open = sb[i].get("open", 0)
        if not prev_close or not today_open:
            continue
        gap_pct = (today_open / prev_close - 1) * 100
        if gap_pct >= 3:
            gap_info = {
                "gap_pct": gap_pct,
                "gap_target": prev_close,  # 갭 메우면 갈 가격
                "days_ago": len(sb) - 1 - i,
            }
            break

    if not gap_info:
        return None

    # 현재가가 갭 메움 타깃 -1~3% 안쪽이면 매수 후보
    target = gap_info["gap_target"]
    diff_pct = (cur / target - 1) * 100
    if -1 <= diff_pct <= 5:
        return {
            "pattern": "갭 메우기 완료",
            "confidence": 60,
            "evidence": f"{gap_info['days_ago']}일 전 +{gap_info['gap_pct']:.1f}% 갭 메움 임박",
            "action": "갭 메움 완료 후 반등 매수",
        }
    elif diff_pct < -1:
        # 갭 이미 메우고 더 빠짐 - 약한 신호
        return None
    return None


def _detect_vcp(bars: List[Dict], indicators: Dict) -> Optional[Dict]:
    """VCP (Volatility Contraction Pattern) - 미너비니식 변동성 수축.
    
    조건:
    - 최근 20~40일 동안 변동폭이 점진적으로 줄어듦
    - 거래량도 함께 감소
    - 베이스(저점) 유지
    """
    if len(bars) < 40:
        return None
    sb = sorted(bars, key=lambda x: x.get("date", ""))
    if len(sb) < 40:
        return None

    # 3구간 변동폭 비교: 30~40일전 / 15~25일전 / 최근 10일
    def _range_pct(window):
        highs = [b.get("high", 0) for b in window if b.get("high")]
        lows = [b.get("low", 0) for b in window if b.get("low")]
        if not highs or not lows:
            return None
        hi = max(highs)
        lo = min(lows)
        if lo <= 0:
            return None
        return (hi - lo) / lo * 100

    early = _range_pct(sb[-40:-25])
    mid = _range_pct(sb[-25:-10])
    recent = _range_pct(sb[-10:])

    if early is None or mid is None or recent is None:
        return None

    # 변동폭이 단계적으로 줄어들어야 함
    if early > mid > recent and recent < early * 0.6:
        # 거래량도 감소했는지
        vol_early = sum(b.get("volume", 0) for b in sb[-40:-25]) / 15
        vol_recent = sum(b.get("volume", 0) for b in sb[-10:]) / 10
        vol_dried = vol_recent < vol_early * 0.7

        confidence = 70 if vol_dried else 55
        return {
            "pattern": "VCP (변동성 수축)",
            "confidence": confidence,
            "evidence": f"변동폭 {early:.0f}% → {mid:.0f}% → {recent:.0f}%" + (
                " + 거래량 마름" if vol_dried else ""
            ),
            "action": "수축 끝나는 시점 돌파 매수",
        }
    return None


def _detect_negative_patterns(bars: List[Dict], indicators: Dict) -> Optional[Dict]:
    """부정 패턴 감지 (감점)
    
    - 헤드앤숄더 (간단 버전): 3봉우리에 가운데가 가장 높고 양쪽이 비슷
    - 데드 캣 바운스: 큰 하락 후 약한 반등
    """
    if len(bars) < 30:
        return None
    sb = sorted(bars, key=lambda x: x.get("date", ""))
    closes = [b["close"] for b in sb if b.get("close")]
    if len(closes) < 20:
        return None

    # 데드 캣 바운스: 20일 내 -15%↓ 후 최근 3일간 약한 반등 (+1~5%)
    high_20d = max(closes[-20:])
    low_recent = min(closes[-7:])
    cur = closes[-1]
    if low_recent / high_20d - 1 < -0.15:  # 큰 하락 있었음
        rebound = (cur / low_recent - 1) * 100
        if 1 <= rebound <= 5:
            return {
                "pattern": "데드 캣 바운스 의심",
                "confidence": 60,
                "evidence": f"20일 -{(1 - low_recent/high_20d)*100:.0f}% 후 {rebound:+.1f}% 반등",
                "action": "추격 매수 위험",
                "negative": True,
            }
    return None


def evaluate(bars: List[Dict], indicators: Dict) -> Dict[str, Any]:
    """패턴 종합 평가.
    
    Args:
        bars: 일봉 데이터 [{date, open, high, low, close, volume}]
        indicators: analyze_bars() 결과
    """
    if not bars or len(bars) < 20 or indicators.get("error"):
        return {"score": 50, "patterns": [], "comment": "데이터 부족", "key_signals": []}

    patterns_detected = []

    # 긍정 패턴
    for detector in [
        _detect_pullback_to_ma20,
        _detect_breakout_retest,
        _detect_gap_fill,
        _detect_vcp,
    ]:
        result = detector(bars, indicators)
        if result:
            patterns_detected.append(result)

    # 부정 패턴
    neg = _detect_negative_patterns(bars, indicators)
    if neg:
        patterns_detected.append(neg)

    # 점수 산정
    score = 50
    positive_patterns = [p for p in patterns_detected if not p.get("negative")]
    negative_patterns = [p for p in patterns_detected if p.get("negative")]

    if positive_patterns:
        # 가장 신뢰도 높은 패턴 기준
        best = max(positive_patterns, key=lambda p: p.get("confidence", 0))
        score += (best.get("confidence", 50) - 50) * 0.8
        if len(positive_patterns) >= 2:
            score += 5  # 복합 패턴 보너스

    if negative_patterns:
        for n in negative_patterns:
            score -= n.get("confidence", 50) * 0.3

    score = max(0, min(100, score))

    # 코멘트
    if positive_patterns:
        primary = max(positive_patterns, key=lambda p: p.get("confidence", 0))
        comment = f"{primary['pattern']} ({primary['confidence']}%)"
    elif negative_patterns:
        comment = f"⚠️ {negative_patterns[0]['pattern']}"
    else:
        comment = "특별한 패턴 없음"

    key_signals = [p["pattern"] for p in patterns_detected[:3]]

    return {
        "score": round(score, 1),
        "patterns": patterns_detected,
        "positive_count": len(positive_patterns),
        "negative_count": len(negative_patterns),
        "key_signals": key_signals,
        "comment": comment,
    }
