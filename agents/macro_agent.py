"""
agents/macro_agent.py
매크로 분석가 - AI (Claude Sonnet) 사용.

매크로 지표 + 섹터 + 종목 정보를 받아 "이 종목에 매크로가 어떤 영향?" 판단.
"""
import json
from typing import Dict, Any, Optional
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from logger import get_logger

log = get_logger("macro_agent")

_client = None
def _get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM = """당신은 매크로 시장 환경 분석가입니다. 주어진 매크로 지표와 종목 정보를 보고
이 종목이 현재 매크로 환경에서 얼마나 유리한지 평가합니다.

평가 기준:
- 시장 추세 (코스피/S&P) 와 종목 섹터의 정렬
- 금리/환율의 섹터별 영향 (고금리=성장주 불리, 가치주 유리)
- VIX 공포지수 (높으면 저점매수 기회 vs 변동성 위험)
- 장단기 금리차 (역전이면 경기침체 신호)
- DXY 강달러 (수출기업 유리, 신흥국 불리)

반드시 JSON으로만 응답. 다른 텍스트 X."""


def _format_macro(macro: Dict, sector: str, is_krx: bool) -> str:
    parts = []
    if macro.get("kospi"):
        k = macro["kospi"]
        parts.append(f"코스피 {k['price']:.0f} ({k['change_pct']:+.2f}%) {'20일선↑' if k.get('above_ma20') else '20일선↓'}")
    if macro.get("sp500"):
        s = macro["sp500"]
        parts.append(f"S&P500 {s['price']:.0f} ({s['change_pct']:+.2f}%) {'20일선↑' if s.get('above_ma20') else '20일선↓'}")
    if macro.get("nasdaq"):
        n = macro["nasdaq"]
        parts.append(f"나스닥 {n['price']:.0f} ({n['change_pct']:+.2f}%)")
    if macro.get("vix") is not None:
        parts.append(f"VIX {macro['vix']:.1f}")
    if macro.get("us10y") is not None:
        parts.append(f"미국 10년 {macro['us10y']:.2f}%")
    if macro.get("yield_curve") is not None:
        yc = macro["yield_curve"]
        parts.append(f"장단기차 {yc:+.2f}%p {'(역전!)' if yc < 0 else ''}")
    if macro.get("usd_krw"):
        parts.append(f"환율 {macro['usd_krw']:.0f}원")
    if macro.get("dxy"):
        parts.append(f"DXY {macro['dxy']:.1f}")
    if macro.get("wti"):
        parts.append(f"WTI ${macro['wti']:.1f}")
    if macro.get("fear_greed") is not None:
        parts.append(f"F&G {macro['fear_greed']}")
    return " / ".join(parts)


def evaluate(stock_info: Dict, macro: Dict) -> Dict[str, Any]:
    """매크로 환경 → 종목 평가.
    
    Args:
        stock_info: {ticker, name, sector, market: "KRX"/"US"}
        macro: macro_api.get_all() 결과
    """
    market = stock_info.get("market", "KRX")
    is_krx = market == "KRX"
    sector = stock_info.get("sector", "")
    name = stock_info.get("name", "")
    
    macro_str = _format_macro(macro, sector, is_krx)
    
    prompt = f"""종목: {name} ({stock_info.get('ticker', '')})
시장: {'한국' if is_krx else '미국'}
섹터: {sector}

현재 매크로:
{macro_str}

다음 JSON으로만 답변:
{{
  "score": 0-100 정수,
  "market_phase": "공포/중립/탐욕",
  "sector_momentum": "강세/중립/약세",
  "favor_for_stock": "우호/중립/부정",
  "key_factors": ["영향 요인 2~3개"],
  "comment": "한 줄 요약 (50자 이내)"
}}"""
    
    try:
        client = _get_client()
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        
        # JSON 추출
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            text = text[s:e+1]
        
        result = json.loads(text)
        # 검증
        score = result.get("score", 50)
        if not isinstance(score, (int, float)):
            score = 50
        result["score"] = max(0, min(100, float(score)))
        return result
    except Exception as e:
        log.warning(f"매크로 AI 실패: {e}")
        # Fallback: 코드 기반 간단 점수
        return _fallback_macro(macro, is_krx)


def _fallback_macro(macro: Dict, is_krx: bool) -> Dict[str, Any]:
    score = 50
    factors = []
    
    vix = macro.get("vix")
    if vix is not None:
        if vix >= 25:
            score += 8
            factors.append(f"공포 (VIX {vix:.0f})")
        elif vix <= 12:
            score -= 10
            factors.append(f"과열 (VIX {vix:.0f})")
    
    idx = macro.get("kospi" if is_krx else "sp500")
    if idx:
        if idx.get("above_ma20") and idx.get("change_pct", 0) > 0:
            score += 10
            factors.append("지수 상승추세")
        elif not idx.get("above_ma20"):
            score -= 8
            factors.append("지수 약세")
    
    yc = macro.get("yield_curve")
    if yc is not None and yc < 0:
        score -= 5
        factors.append("금리역전")
    
    return {
        "score": max(0, min(100, score)),
        "market_phase": "공포" if (vix or 0) > 25 else "탐욕" if (vix or 0) < 12 else "중립",
        "sector_momentum": "중립",
        "favor_for_stock": "중립",
        "key_factors": factors,
        "comment": f"매크로 {'우호' if score >= 60 else '중립' if score >= 45 else '부정'}",
    }
