"""
agents/synthesizer.py
종합 판정관.

6개 에이전트 결과를 받아:
1. 가중 평균 점수 계산
2. 등급 부여 (코드 룰)
3. 손절가/익절가 산정
4. 핵심 근거/리스크 종합
5. 매매 시나리오 작성

AI 1회 호출로 시나리오 텍스트만 생성. 등급은 코드가 결정.
"""
import json
from typing import Dict, Any, Optional
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


def _compute_total(agents: Dict) -> float:
    """가중 평균 점수"""
    total = 0.0
    for key, weight in AGENT_WEIGHTS.items():
        score = agents.get(key, {}).get("score", 50)
        total += score * weight
    return round(total, 1)


def _grade_from_score(score: float, chart_score: float, alignment: str) -> Dict[str, Any]:
    """점수 -> 등급. 추세 역행 시 강제 하향."""
    
    # 추세 역행 차단
    if alignment in ("downtrend", "perfect_downtrend") and score < 70:
        return {
            "grade": "비중축소",
            "emoji": "🟠",
            "color_class": "reduce",
        }
    
    # 차트 점수 너무 낮으면 강제 하향
    if chart_score < 35:
        if score >= GRADE_THRESHOLDS["buy"]:
            return {"grade": "관망", "emoji": "🟡", "color_class": "hold"}
    
    if score >= GRADE_THRESHOLDS["strong_buy"]:
        return {"grade": "적극매수", "emoji": "🟢🟢", "color_class": "strong-buy"}
    if score >= GRADE_THRESHOLDS["buy"]:
        return {"grade": "매수", "emoji": "🟢", "color_class": "buy"}
    if score >= GRADE_THRESHOLDS["hold"]:
        return {"grade": "관망", "emoji": "🟡", "color_class": "hold"}
    if score >= GRADE_THRESHOLDS["reduce"]:
        return {"grade": "비중축소", "emoji": "🟠", "color_class": "reduce"}
    return {"grade": "회피", "emoji": "🔴", "color_class": "avoid"}


def _compute_confidence(agents: Dict, total: float) -> int:
    """에이전트 의견 분산도 기반 확신도 (1~10)"""
    scores = [a.get("score", 50) for a in agents.values()]
    if not scores:
        return 5
    avg = sum(scores) / len(scores)
    var = sum((s - avg) ** 2 for s in scores) / len(scores)
    std = var ** 0.5
    
    # 표준편차 작으면 (의견 일치) 확신도 높음
    # 표준편차 0 → 10, 표준편차 30+ → 3
    if std < 5:
        conf = 10
    elif std < 10:
        conf = 9
    elif std < 15:
        conf = 8
    elif std < 20:
        conf = 7
    elif std < 25:
        conf = 6
    else:
        conf = 5
    
    # 점수 극단이면 확신도 가산
    if total >= 80 or total <= 20:
        conf = min(10, conf + 1)
    
    return conf


def _compute_prices(
    quote: Dict,
    chart: Dict,
    risk: Dict,
    is_krx: bool,
) -> Dict[str, Any]:
    """진입가/손절가/익절가 계산. 항상 검증된 값."""
    cur = quote.get("price", 0)
    if cur <= 0:
        return {
            "entry_low": 0, "entry_high": 0, "entry_label": "—",
            "stop_loss": 0, "take_profit": 0,
            "expected_return_pct": 0, "expected_risk_pct": 0,
            "profit_loss_ratio": 0,
        }
    
    # 손절가: ATR 기반 우선, 없으면 -7%
    stop = risk.get("stop_loss_atr")
    if not stop or stop >= cur:
        stop = round(cur * (1 - DEFAULT_STOP_PCT / 100), 2 if not is_krx else 0)
    
    # 익절가: 저항선 기반, 없거나 너무 가까우면 +10%
    resistance = chart.get("resistance")
    if resistance and resistance > cur * 1.03:
        # 저항선 -1% 안쪽
        take = round(resistance * 0.99, 2 if not is_krx else 0)
    else:
        take = round(cur * (1 + DEFAULT_PROFIT_PCT / 100), 2 if not is_krx else 0)
    
    # 최소 +5% 보장
    min_take = cur * 1.05
    if take < min_take:
        take = round(min_take, 2 if not is_krx else 0)
    
    # 진입가 구간
    entry_low = round(cur * 0.99, 2 if not is_krx else 0)
    entry_high = round(cur * 1.01, 2 if not is_krx else 0)
    
    # 수익/위험률
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
        "take_profit": take,
        "expected_return_pct": ret_pct,
        "expected_risk_pct": risk_pct,
        "profit_loss_ratio": pl_ratio,
    }


def _check_contradictions(agents: Dict) -> list:
    """모순 체크"""
    warnings_list = []
    chart = agents.get("chart", {}).get("score", 50)
    macro = agents.get("macro", {}).get("score", 50)
    supply = agents.get("supply", {}).get("score", 50)
    news = agents.get("news", {}).get("score", 50)
    
    if chart >= 75 and macro <= 30:
        warnings_list.append("⚠️ 차트는 강하나 매크로 부정적")
    if chart >= 75 and supply <= 30:
        warnings_list.append("⚠️ 차트 강세지만 수급 빠짐")
    if news <= 25:
        warnings_list.append("⚠️ 최근 악재 뉴스 다수")
    
    return warnings_list


SYSTEM_SYNTH = """당신은 스윙 매매 종합 판정관입니다.
6개 에이전트의 분석 결과와 결정된 등급/가격을 받아, 사용자에게 보여줄 최종 텍스트를 생성합니다.

생성할 것:
1. summary: 한 줄 핵심 요약 (50자 이내, 매력 포인트)
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
) -> Dict[str, Any]:
    """6 에이전트 결과 종합 + 시나리오 생성.
    
    Args:
        stock_info: {ticker, name, sector, market}
        quote: 시세
        agents: {
            "chart": {...}, "fundamental": {...}, "macro": {...},
            "news": {...}, "supply": {...}, "risk": {...}
        }
    """
    # 1. 종합 점수
    total = _compute_total(agents)
    
    # 2. 등급
    chart_score = agents.get("chart", {}).get("score", 50)
    alignment = agents.get("chart", {}).get("daily_trend", "unknown")
    grade = _grade_from_score(total, chart_score, alignment)
    
    # 3. 확신도
    confidence = _compute_confidence(agents, total)
    
    # 4. 가격
    prices = _compute_prices(
        quote=quote,
        chart=agents.get("chart", {}),
        risk=agents.get("risk", {}),
        is_krx=is_krx,
    )
    
    # 5. 모순 체크
    contradictions = _check_contradictions(agents)
    
    # 6. AI로 시나리오 텍스트 생성
    text_result = _generate_scenario_text(stock_info, quote, agents, grade, prices, is_krx)
    
    return {
        "total_score": total,
        "grade": grade["grade"],
        "grade_emoji": grade["emoji"],
        "grade_color_class": grade["color_class"],
        "confidence": confidence,
        "prices": prices,
        "contradictions": contradictions,
        "summary": text_result.get("summary", ""),
        "key_reasons": text_result.get("key_reasons", []),
        "risk_factors": text_result.get("risk_factors", []),
        "scenario_profit": text_result.get("scenario_profit", ""),
        "scenario_stop": text_result.get("scenario_stop", ""),
        "hold_days": f"{HOLD_DAYS_MIN}~{HOLD_DAYS_MAX}일",
    }


def _generate_scenario_text(
    stock_info: Dict, quote: Dict, agents: Dict, grade: Dict, prices: Dict, is_krx: bool
) -> Dict[str, Any]:
    """AI로 시나리오 텍스트만 생성"""
    
    # 에이전트 결과 요약
    ag_summary = []
    for k, label in [
        ("chart", "차트"), ("fundamental", "펀더"), ("macro", "매크로"),
        ("news", "뉴스"), ("supply", "수급"), ("risk", "리스크"),
    ]:
        a = agents.get(k, {})
        ag_summary.append(f"- {label}: {a.get('score', 0):.0f}점 ({a.get('comment', '')})")
    
    cur = quote.get("price", 0)
    cur_str = f"{int(cur):,}원" if is_krx else f"${cur:.2f}"
    
    prompt = f"""종목: {stock_info.get('name', '')} ({stock_info.get('ticker', '')})
섹터: {stock_info.get('sector', '')}
현재가: {cur_str}

6 에이전트 분석:
{chr(10).join(ag_summary)}

시스템 결정:
- 등급: {grade['grade']}
- 진입가: {prices['entry_label']}
- 손절가: {prices['stop_loss']}
- 익절가: {prices['take_profit']}
- 손익비: 1:{prices['profit_loss_ratio']}

JSON으로만 답:
{{
  "summary": "핵심 요약 한 줄 (50자 이내, 매력 포인트)",
  "key_reasons": ["근거1 (50자 이내)", "근거2", "근거3"],
  "risk_factors": ["리스크1 (50자 이내)", "리스크2", "리스크3"],
  "scenario_profit": "익절 시나리오 한 줄 (80자 이내)",
  "scenario_stop": "손절 시나리오 한 줄 (80자 이내)"
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
            "summary": f"{grade['grade']} - 6개 지표 종합 분석 결과",
            "key_reasons": [
                a.get("comment", "") for a in agents.values() if a.get("comment")
            ][:3],
            "risk_factors": agents.get("risk", {}).get("warnings", [])[:3] or ["AI 분석 실패"],
            "scenario_profit": f"진입 후 {prices['take_profit']}까지 도달 시 익절",
            "scenario_stop": f"{prices['stop_loss']} 이탈 시 즉시 손절",
        }
