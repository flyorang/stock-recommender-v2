"""
agents/synthesizer.py — v3 (옵션 B - 다른 채팅 통찰 반영)

v2와 다른 점:
1. 확신도 점수 (1-10) → 폐기. "강한 매수 동의 4/8" 식 사실 표시로 대체
2. regime 자동 분류 폐기 → 사용자 토글값 받기 (recommend_one(market, regime=...)로 전달)
3. AI veto 시스템 추가 — 작전주/명백한 함정/실적임박 약세 시 강제 회피
4. event/pattern 에이전트 가중치 통합

기존 유지:
- 모순 점수 차감 + 등급 다운
- 뉴스 게이트
- 손절가 지지선 클램프
- 국면별 가중치 멀티플라이어 (regime 인자 받으면 적용)
"""
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, AGENT_WEIGHTS,
    GRADE_THRESHOLDS, HOLD_DAYS_MIN, HOLD_DAYS_MAX,
    DEFAULT_STOP_PCT, DEFAULT_PROFIT_PCT,
)
from logger import get_logger

log = get_logger("synth")

_client = None
def _get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ════════════════════════════════════════════════════════════
# 국면별 가중치 멀티플라이어 (사용자 토글값 받음)
# ════════════════════════════════════════════════════════════
REGIME_WEIGHT_MULTIPLIERS = {
    "bull":     {"chart": 1.3, "news": 1.2, "supply": 1.1, "fundamental": 0.7, "macro": 0.7, "risk": 0.9,  "event": 1.0, "pattern": 1.2},
    "bear":     {"chart": 0.8, "news": 0.9, "supply": 0.9, "fundamental": 1.1, "macro": 1.4, "risk": 1.5,  "event": 1.1, "pattern": 0.9},
    "sideways": {"chart": 0.9, "news": 0.9, "supply": 1.3, "fundamental": 1.4, "macro": 0.9, "risk": 1.0,  "event": 1.0, "pattern": 1.1},
    "unknown":  {"chart": 1.0, "news": 1.0, "supply": 1.0, "fundamental": 1.0, "macro": 1.0, "risk": 1.0,  "event": 1.0, "pattern": 1.0},
}


def _resolve_weights(regime: Optional[str] = None) -> Dict[str, float]:
    """국면별 멀티플라이어 적용 후 합 1.0이 되게 정규화"""
    if not regime or regime not in REGIME_WEIGHT_MULTIPLIERS:
        return AGENT_WEIGHTS
    mult = REGIME_WEIGHT_MULTIPLIERS[regime]
    raw = {k: AGENT_WEIGHTS.get(k, 0) * mult.get(k, 1.0) for k in AGENT_WEIGHTS}
    total = sum(raw.values())
    if total <= 0:
        return AGENT_WEIGHTS
    return {k: v / total for k, v in raw.items()}


def _compute_total(agents: Dict, regime: Optional[str] = None) -> float:
    weights = _resolve_weights(regime)
    total = 0.0
    for key, weight in weights.items():
        score = agents.get(key, {}).get("score", 50)
        total += score * weight
    return round(total, 1)


# ════════════════════════════════════════════════════════════
# 에이전트 합의 표시 (확신도 점수 대체)
# 다른 채팅 제안: "강한 합의 N개 / 약한 합의 N개" 사실만 표시
# ════════════════════════════════════════════════════════════
def _compute_consensus(agents: Dict) -> Dict[str, Any]:
    """에이전트들의 점수 분포를 사실로 표시.
    
    - 강한 매수 동의: score >= 65 인 에이전트 수
    - 강한 매도 동의: score <= 35 인 에이전트 수
    - 중립: 나머지
    """
    excluded = {"regime", "consensus"}  # 메타 키 제외
    valid_agents = {k: v for k, v in agents.items()
                    if k not in excluded and isinstance(v, dict) and "score" in v}

    if not valid_agents:
        return {"buy_strong": 0, "sell_strong": 0, "neutral": 0, "total": 0, "label": "데이터 없음"}

    buy_strong = sum(1 for a in valid_agents.values() if a.get("score", 50) >= 65)
    sell_strong = sum(1 for a in valid_agents.values() if a.get("score", 50) <= 35)
    total = len(valid_agents)
    neutral = total - buy_strong - sell_strong

    # 각 에이전트 입장 라벨 (UI 표시용)
    by_agent = {}
    for k, a in valid_agents.items():
        sc = a.get("score", 50)
        if sc >= 65:
            by_agent[k] = "강한 매수"
        elif sc >= 55:
            by_agent[k] = "매수"
        elif sc >= 45:
            by_agent[k] = "중립"
        elif sc >= 35:
            by_agent[k] = "매도"
        else:
            by_agent[k] = "강한 매도"

    # 한 줄 요약 - 강한 동의 N개 기준 단순화
    if buy_strong >= 6:
        label = f"강한 합의 (매수 {buy_strong}/{total})"
    elif sell_strong >= 6:
        label = f"강한 매도 합의 ({sell_strong}/{total})"
    elif buy_strong >= 3:
        label = f"매수 우세 (강한 동의 {buy_strong}/{total})"
    elif sell_strong >= 4:
        label = f"매도 우세 ({sell_strong}/{total})"
    else:
        label = f"의견 갈림 (매수 {buy_strong}, 매도 {sell_strong} / {total})"

    return {
        "buy_strong": buy_strong,
        "sell_strong": sell_strong,
        "neutral": neutral,
        "total": total,
        "label": label,
        "by_agent": by_agent,
    }


# ════════════════════════════════════════════════════════════
# 모순 체크 + 점수 차감
# ════════════════════════════════════════════════════════════
def _check_contradictions_and_penalty(agents: Dict) -> Dict[str, Any]:
    warnings_list = []
    score_penalty = 0
    grade_cap = None

    chart = agents.get("chart", {}).get("score", 50)
    macro = agents.get("macro", {}).get("score", 50)
    supply = agents.get("supply", {}).get("score", 50)
    news = agents.get("news", {}).get("score", 50)
    risk = agents.get("risk", {}).get("score", 50)

    if chart >= 75 and macro <= 30:
        warnings_list.append("⚠️ 차트 강세 vs 매크로 약세 — 함정 랠리 가능성")
        score_penalty += 4  # 8→4

    if chart >= 75 and supply <= 30:
        warnings_list.append("⚠️ 차트 강세 vs 수급 빠짐 — 외인/기관 빠져나가는 중")
        score_penalty += 5  # 10→5

    if chart >= 70 and risk <= 30:
        warnings_list.append("⚠️ 차트 강세지만 리스크 매우 높음")
        score_penalty += 3  # 7→3

    news_neg_flags = agents.get("news", {}).get("negative_flags", [])
    if news <= 25:
        warnings_list.append(f"⛔ 강한 악재 (뉴스 {news:.0f}점) — 매수 등급 불가")
        score_penalty += 8  # 12→8 (게이트는 유지)
        grade_cap = "hold"
    elif news <= 35 and len(news_neg_flags) >= 2:
        warnings_list.append(f"⚠️ 다수 악재 ({len(news_neg_flags)}건)")
        score_penalty += 3  # 6→3

    if macro <= 35 and supply <= 35:
        warnings_list.append("⚠️ 매크로 + 수급 동시 약세")
        score_penalty += 3  # 5→3

    return {
        "warnings": warnings_list,
        "score_penalty": score_penalty,
        "grade_cap": grade_cap,
    }


# ════════════════════════════════════════════════════════════
# AI VETO — 룰엔진 위에 있는 강제 회피 시스템
# ChatGPT + 다른 채팅 핵심 통찰: AI/룰에 veto 권한 부여
# 등급/점수 무관하게 강제 회피로 보냄
# ════════════════════════════════════════════════════════════
def _check_veto(agents: Dict, quote: Dict, indicators: Dict, earnings_date: Optional[Dict]) -> Optional[Dict]:
    """강제 회피 조건 체크. 해당하면 등급 무조건 '회피'.
    
    Returns:
        None: veto 없음
        Dict: {reason, evidence} — veto 발동
    """
    vetos = []

    # ─── VETO 1: 작전주/펌프 의심 ───
    # 거래량 5배+ 폭증 + 5일 +25%+ + RSI 75+ + 차트 점수 의외로 안 높음 (펌프 끝물)
    vol_ratio = (indicators.get("volume") or {}).get("ratio", 0)
    extreme_spike = (indicators.get("volume") or {}).get("extreme_spike", False)
    ch5 = indicators.get("change_5d_pct") or 0
    rsi = indicators.get("rsi")
    chart_score = agents.get("chart", {}).get("score", 50)

    if extreme_spike and ch5 >= 25 and rsi and rsi >= 75:
        vetos.append({
            "reason": "작전주/펌프 의심",
            "evidence": f"거래량 {vol_ratio:.1f}배 폭증 + 5일 {ch5:+.1f}% + RSI {rsi:.0f}",
        })

    # 또 다른 작전주 패턴: 거래량 8배+ (절대값) + 단기 급등
    if vol_ratio >= 8 and ch5 >= 15:
        vetos.append({
            "reason": "거래량 비정상 폭증 + 단기 급등",
            "evidence": f"거래량 {vol_ratio:.1f}배 + 5일 {ch5:+.1f}%",
        })

    # ─── VETO 2: 명백한 함정 (차트 강세 + 외인/기관 빠짐) ───
    supply_score = agents.get("supply", {}).get("score", 50)
    foreign_flow = agents.get("supply", {}).get("foreign_flow", "")
    institution_flow = agents.get("supply", {}).get("institution_flow", "")

    if chart_score >= 75 and supply_score <= 25:
        if foreign_flow == "유출" and institution_flow == "매도":
            vetos.append({
                "reason": "명백한 함정 패턴",
                "evidence": f"차트 {chart_score:.0f}점이지만 외인/기관 동시 매도",
            })

    # ─── VETO 3: 실적 임박 (D-3 이내) + 강한 악재 또는 약세 ───
    news_score = agents.get("news", {}).get("score", 50)
    news_neg = len(agents.get("news", {}).get("negative_flags", []))

    if earnings_date:
        days_until = earnings_date.get("days_until")
        if days_until is not None and 0 <= days_until <= 3:
            if news_score <= 35 or news_neg >= 2:
                vetos.append({
                    "reason": f"실적발표 임박 (D-{days_until}) + 악재",
                    "evidence": f"뉴스 {news_score:.0f}점, 악재 플래그 {news_neg}건",
                })
            # 매크로도 약세면 veto
            macro_score = agents.get("macro", {}).get("score", 50)
            if macro_score <= 30:
                vetos.append({
                    "reason": f"실적발표 임박 (D-{days_until}) + 매크로 약세",
                    "evidence": f"매크로 {macro_score:.0f}점",
                })

    # ─── VETO 4: RSI 90+ 극과매수 ───
    if rsi and rsi >= 90:
        vetos.append({
            "reason": "RSI 극과매수",
            "evidence": f"RSI {rsi:.0f}",
        })

    # ─── VETO 5: event agent의 강한 부정 이벤트 ───
    event = agents.get("event", {})
    if event and event.get("veto_flag"):
        vetos.append({
            "reason": event.get("veto_reason", "이벤트 리스크"),
            "evidence": event.get("comment", ""),
        })

    if not vetos:
        return None

    return {
        "vetoed": True,
        "primary_reason": vetos[0]["reason"],
        "all_vetos": vetos,
    }


# ════════════════════════════════════════════════════════════
# 등급 산정
# ════════════════════════════════════════════════════════════
def _grade_from_score(
    score: float,
    chart_score: float,
    alignment: str,
    grade_cap: Optional[str] = None,
    veto: Optional[Dict] = None,
) -> Dict[str, Any]:
    """점수 -> 등급. veto가 있으면 무조건 회피."""

    # VETO 발동 - 무조건 회피
    if veto and veto.get("vetoed"):
        return {
            "grade": "회피",
            "emoji": "🔴",
            "color_class": "avoid",
            "level": 0,
            "vetoed_reason": veto.get("primary_reason"),
            "downgraded_reason": f"VETO: {veto.get('primary_reason')}",
        }

    if alignment in ("downtrend", "perfect_downtrend") and score < 70:
        return {"grade": "비중축소", "emoji": "🟠", "color_class": "reduce", "level": 1}

    if chart_score < 25:  # 35→25 (더 약한 차트만 강등)
        if score >= GRADE_THRESHOLDS["buy"]:
            return {"grade": "관망", "emoji": "🟡", "color_class": "hold", "level": 2,
                    "downgraded_reason": "차트 점수 매우 낮음"}

    if score >= GRADE_THRESHOLDS["strong_buy"]:
        grade_info = {"grade": "적극매수", "emoji": "🟢🟢", "color_class": "strong-buy", "level": 4}
    elif score >= GRADE_THRESHOLDS["buy"]:
        grade_info = {"grade": "매수", "emoji": "🟢", "color_class": "buy", "level": 3}
    elif score >= GRADE_THRESHOLDS["hold"]:
        grade_info = {"grade": "관망", "emoji": "🟡", "color_class": "hold", "level": 2}
    elif score >= GRADE_THRESHOLDS["reduce"]:
        grade_info = {"grade": "비중축소", "emoji": "🟠", "color_class": "reduce", "level": 1}
    else:
        grade_info = {"grade": "회피", "emoji": "🔴", "color_class": "avoid", "level": 0}

    if grade_cap == "hold" and grade_info["level"] > 2:
        return {"grade": "관망", "emoji": "🟡", "color_class": "hold", "level": 2,
                "downgraded_reason": "뉴스 게이트 (강한 악재)"}
    if grade_cap == "reduce" and grade_info["level"] > 1:
        return {"grade": "비중축소", "emoji": "🟠", "color_class": "reduce", "level": 1,
                "downgraded_reason": "강제 비중축소"}

    return grade_info


# ════════════════════════════════════════════════════════════
# 가격 산정 - 지지선 클램프 추가
# ════════════════════════════════════════════════════════════
def _compute_prices(quote: Dict, chart: Dict, risk: Dict, is_krx: bool) -> Dict[str, Any]:
    cur = quote.get("price", 0)
    if cur <= 0:
        return {
            "entry_low": 0, "entry_high": 0, "entry_label": "—",
            "stop_loss": 0, "take_profit": 0,
            "expected_return_pct": 0, "expected_risk_pct": 0,
            "profit_loss_ratio": 0,
        }

    stop_atr = risk.get("stop_loss_atr")
    if not stop_atr or stop_atr >= cur:
        stop_atr = round(cur * (1 - DEFAULT_STOP_PCT / 100), 2 if not is_krx else 0)

    support = chart.get("support")
    stop_support = None
    if support and support > 0 and support < cur and support >= cur * 0.90:
        stop_support = round(support * 0.99, 2 if not is_krx else 0)

    if stop_support and stop_support > stop_atr:
        stop = stop_support
        stop_source = "지지선"
    else:
        stop = stop_atr
        stop_source = "ATR"

    min_stop = cur * 0.90
    max_stop = cur * 0.97
    stop = max(min_stop, min(max_stop, stop))
    stop = round(stop, 2 if not is_krx else 0)

    resistance = chart.get("resistance")
    if resistance and resistance > cur * 1.03:
        take = round(resistance * 0.99, 2 if not is_krx else 0)
        take_source = "저항선"
    else:
        take = round(cur * (1 + DEFAULT_PROFIT_PCT / 100), 2 if not is_krx else 0)
        take_source = "기본 +10%"

    min_take = cur * 1.05
    if take < min_take:
        take = round(min_take, 2 if not is_krx else 0)

    entry_low = round(cur * 0.99, 2 if not is_krx else 0)
    entry_high = round(cur * 1.01, 2 if not is_krx else 0)

    ret_pct = round((take / cur - 1) * 100, 1)
    risk_pct = round((1 - stop / cur) * 100, 1)
    pl_ratio = round(ret_pct / risk_pct, 2) if risk_pct > 0 else 0

    if is_krx:
        entry_label = f"{int(entry_low):,}~{int(entry_high):,}원"
    else:
        entry_label = f"${entry_low:.2f}~${entry_high:.2f}"

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_label": entry_label,
        "stop_loss": stop,
        "stop_loss_source": stop_source,
        "take_profit": take,
        "take_profit_source": take_source,
        "expected_return_pct": ret_pct,
        "expected_risk_pct": risk_pct,
        "profit_loss_ratio": pl_ratio,
    }


SYSTEM_SYNTH = """당신은 스윙 매매 종합 판정관입니다.
에이전트 분석 결과와 결정된 등급/가격을 받아, 사용자에게 보여줄 최종 텍스트를 생성합니다.

생성할 것:
1. summary: 한 줄 핵심 요약 (50자 이내)
2. key_reasons: 추천 근거 3가지 (각 50자 이내)
3. risk_factors: 리스크 3가지 (각 50자 이내)
4. scenario_profit: 익절 시나리오 한 줄
5. scenario_stop: 손절 시나리오 한 줄

JSON으로만 응답."""


def evaluate(
    stock_info: Dict,
    quote: Dict,
    agents: Dict,
    is_krx: bool = True,
    regime: Optional[str] = None,
    indicators: Optional[Dict] = None,
    earnings_date: Optional[Dict] = None,
) -> Dict[str, Any]:
    """종합 평가.
    
    Args:
        regime: 'bull'/'bear'/'sideways'/'unknown' (사용자 토글)
        indicators: 기술지표 (veto 체크용)
        earnings_date: 실적발표일 (veto 체크용)
    """
    # 1. 모순 체크
    contradiction_result = _check_contradictions_and_penalty(agents)

    # 2. 종합 점수 (국면 가중치 적용)
    total_raw = _compute_total(agents, regime=regime)
    total = max(0, total_raw - contradiction_result["score_penalty"])

    # 3. VETO 체크 (신규)
    veto = _check_veto(
        agents=agents,
        quote=quote,
        indicators=indicators or {},
        earnings_date=earnings_date,
    )

    # 4. 등급 (veto + 모순 캡 반영)
    chart_score = agents.get("chart", {}).get("score", 50)
    alignment = agents.get("chart", {}).get("daily_trend", "unknown")
    grade = _grade_from_score(
        total, chart_score, alignment,
        grade_cap=contradiction_result["grade_cap"],
        veto=veto,
    )

    # 5. 합의도 (확신도 점수 대신)
    consensus = _compute_consensus(agents)

    # 5-1. NEW: 합의 약한 매수는 강제 관망
    # 매수/적극매수 등급인데 강한 동의가 3 미만이면 → 관망으로 다운 (이전 4→3 완화)
    if grade.get("level", 0) >= 3 and consensus.get("buy_strong", 0) < 3:
        grade = {
            "grade": "관망",
            "emoji": "🟡",
            "color_class": "hold",
            "level": 2,
            "downgraded_reason": f"합의 약함 (강한 매수 {consensus.get('buy_strong', 0)}/8, 3 미만)",
        }

    # 6. 가격 (지지선 클램프)
    prices = _compute_prices(
        quote=quote,
        chart=agents.get("chart", {}),
        risk=agents.get("risk", {}),
        is_krx=is_krx,
    )

    # 7. 시나리오 텍스트
    text_result = _generate_scenario_text(stock_info, quote, agents, grade, prices, is_krx)

    return {
        "total_score": total,
        "raw_score": total_raw,
        "score_penalty": contradiction_result["score_penalty"],
        "grade": grade["grade"],
        "grade_emoji": grade["emoji"],
        "grade_color_class": grade["color_class"],
        "downgraded_reason": grade.get("downgraded_reason"),
        "vetoed_reason": grade.get("vetoed_reason"),
        "all_vetos": veto.get("all_vetos") if veto else None,
        "consensus": consensus,  # 확신도 대체
        "prices": prices,
        "contradictions": contradiction_result["warnings"],
        "regime": regime,
        "summary": text_result.get("summary", ""),
        "key_reasons": text_result.get("key_reasons", []),
        "risk_factors": text_result.get("risk_factors", []),
        "scenario_profit": text_result.get("scenario_profit", ""),
        "scenario_stop": text_result.get("scenario_stop", ""),
        "hold_days": f"{HOLD_DAYS_MIN}~{HOLD_DAYS_MAX}일",
    }


def _generate_scenario_text(stock_info, quote, agents, grade, prices, is_krx):
    ag_summary = []
    for k, label in [
        ("chart", "차트"), ("fundamental", "펀더"), ("macro", "매크로"),
        ("news", "뉴스"), ("supply", "수급"), ("risk", "리스크"),
        ("event", "이벤트"), ("pattern", "패턴"),
    ]:
        a = agents.get(k, {})
        if a and "score" in a:
            ag_summary.append(f"- {label}: {a.get('score', 0):.0f}점 ({a.get('comment', '')})")

    cur = quote.get("price", 0)
    cur_str = f"{int(cur):,}원" if is_krx else f"${cur:.2f}"

    prompt = f"""종목: {stock_info.get('name', '')} ({stock_info.get('ticker', '')})
섹터: {stock_info.get('sector', '')}
현재가: {cur_str}

에이전트 분석:
{chr(10).join(ag_summary)}

시스템 결정:
- 등급: {grade['grade']}
- 진입가: {prices['entry_label']}
- 손절가: {prices['stop_loss']} ({prices.get('stop_loss_source', 'ATR')})
- 익절가: {prices['take_profit']} ({prices.get('take_profit_source', '기본')})
- 손익비: 1:{prices['profit_loss_ratio']}

JSON으로만:
{{
  "summary": "핵심 요약 (50자 이내)",
  "key_reasons": ["근거1", "근거2", "근거3"],
  "risk_factors": ["리스크1", "리스크2", "리스크3"],
  "scenario_profit": "익절 시나리오 (80자)",
  "scenario_stop": "손절 시나리오 (80자)"
}}"""

    try:
        client = _get_client()
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=SYSTEM_SYNTH,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            text = text[s:e+1]
        return json.loads(text)
    except Exception as e:
        log.warning(f"시나리오 생성 실패: {e}")
        return {
            "summary": f"{grade['grade']} - 종합 분석 결과",
            "key_reasons": [a.get("comment", "") for a in agents.values()
                            if isinstance(a, dict) and a.get("comment")][:3],
            "risk_factors": (agents.get("risk", {}).get("warnings") or ["AI 분석 실패"])[:3],
            "scenario_profit": f"진입 후 {prices['take_profit']}까지 도달 시 익절",
            "scenario_stop": f"{prices['stop_loss']} 이탈 시 즉시 손절",
        }
