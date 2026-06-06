"""
data/news_api.py
NewsAPI + 네이버 뉴스 RSS로 종목 관련 뉴스 수집.

미장: NewsAPI (영문)
국장: 네이버 뉴스 검색 (한글)
"""
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import sys
import re
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import NEWS_API_KEY, TTL_NEWS
from logger import get_logger, cache_get, cache_set

log = get_logger("news")


def get_news_us(ticker: str, company_name: str = "", days: int = 7) -> List[Dict]:
    """미장 종목 뉴스. Returns: [{title, source, published_at, url}, ...]"""
    key = f"news_us_{ticker}"
    cached = cache_get(key, TTL_NEWS)
    if cached is not None:
        return cached
    
    if not NEWS_API_KEY:
        return []
    
    query = ticker if not company_name else f"{ticker} OR \"{company_name}\""
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": from_date,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        )
        if r.status_code != 200:
            log.warning(f"NewsAPI {ticker}: HTTP {r.status_code}")
            cache_set(key, [])
            return []
        
        data = r.json()
        articles = data.get("articles", []) or []
        result = []
        for a in articles[:15]:
            result.append({
                "title": a.get("title", "") or "",
                "description": (a.get("description") or "")[:300],
                "source": (a.get("source") or {}).get("name", ""),
                "published_at": a.get("publishedAt", ""),
                "url": a.get("url", ""),
            })
        cache_set(key, result)
        return result
    except Exception as e:
        log.warning(f"NewsAPI 실패 {ticker}: {e}")
        return []


def get_news_kr(ticker: str, company_name: str) -> List[Dict]:
    """국장 종목 뉴스 - 네이버 뉴스 검색 (HTML 파싱)."""
    key = f"news_kr_{ticker}"
    cached = cache_get(key, TTL_NEWS)
    if cached is not None:
        return cached
    
    if not company_name:
        return []
    
    try:
        url = "https://search.naver.com/search.naver"
        r = requests.get(
            url,
            params={
                "where": "news",
                "query": company_name,
                "sort": "1",  # 최신순
                "pd": "3",    # 1주
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code != 200:
            cache_set(key, [])
            return []
        
        # 간단 HTML 파싱 - 헤드라인만 추출
        html = r.text
        # news_tit 클래스의 제목
        titles = re.findall(r'<a[^>]*class="news_tit"[^>]*title="([^"]+)"', html)
        # 시간 정보
        times = re.findall(r'<span class="info">([^<]*전|[^<]*\d{4}\.\d{2}\.\d{2})</span>', html)
        
        result = []
        for i, title in enumerate(titles[:15]):
            result.append({
                "title": title.strip(),
                "description": "",
                "source": "네이버 뉴스",
                "published_at": times[i] if i < len(times) else "",
                "url": "",
            })
        cache_set(key, result)
        return result
    except Exception as e:
        log.warning(f"네이버뉴스 실패 {ticker}: {e}")
        return []


def summarize_news_for_prompt(news: List[Dict], max_items: int = 10) -> str:
    """뉴스 목록을 프롬프트에 넣을 텍스트로."""
    if not news:
        return "(최근 뉴스 없음)"
    
    lines = []
    for n in news[:max_items]:
        title = n.get("title", "").strip()
        src = n.get("source", "")
        when = n.get("published_at", "")[:10]
        if title:
            lines.append(f"- [{when} | {src}] {title}")
    return "\n".join(lines) if lines else "(뉴스 없음)"
