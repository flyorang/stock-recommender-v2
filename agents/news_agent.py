"""
agents/news_agent.py
뉴스 분석가 - AI로 헤드라인 감성분석.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from data.news_api import summarize_news_for_prompt
from logger import get_logger

log = get_logger("news_agent")

_client = None
def _get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM = """당신은 주식 뉴스 감성 분석가입니다.
종목 관련 최근 뉴스 헤드라인을 보고 매수 관점에서 긍정/중립/부정 판단합니다.

판단 기준:
- 호재 키워드: 신제품, 계약 체결, 실적 호조, 인수합병, 정부 지원, 기술 돌파
- 악재 키워드: 소송, 리콜, 실적 부진, 규제, 횡령, 분식회계, 매도리포트
- 헤드라인 수와 일관성 (호재가 다수면 강한 긍정)

JSON으로만 응답."""


def evaluate(stock_info: Dict, news: List[Dict]) -> Dict[str, Any]:
    """뉴스 감성 점수.
    
    Args:
        stock_info: {ticker, name, market}
        news: news_api에서 가져온 헤드라인 리스트
    """
    if not news:
        return {
            "score": 50,
            "sentiment": "중립",
            "key_events": [],
            "negative_flags": [],
            "comment": "뉴스 없음",
            "news_count": 0,
        }
    
    summary = summarize_news_for_prompt(news, max_items=12)
    
    prompt = f"""종목: {stock_info.get('name', '')} ({stock_info.get('ticker', '')})

최근 뉴스 헤드라인:
{summary}

다음 JSON으로만 답:
{{
  "score": 0-100 정수,
  "sentiment": "긍정/중립/부정",
  "key_events": ["주요 사건 2~3개 (짧게)"],
  "negative_flags": ["악재 키워드"],
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
        
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            text = text[s:e+1]
        
        result = json.loads(text)
        score = result.get("score", 50)
        if not isinstance(score, (int, float)):
            score = 50
        result["score"] = max(0, min(100, float(score)))
        result["news_count"] = len(news)
        return result
    except Exception as e:
        log.warning(f"뉴스 AI 실패: {e}")
        return {
            "score": 50,
            "sentiment": "중립",
            "key_events": [n.get("title", "")[:60] for n in news[:2]],
            "negative_flags": [],
            "comment": "뉴스 분석 실패, 중립 처리",
            "news_count": len(news),
        }
