"""
data/us_movers.py
미장 거래량/거래대금 상위 종목.

Polygon.io 무료 티어 사용 (분당 5회 제한).
또는 Yahoo Finance trending tickers fallback.
"""
import requests
from typing import List, Dict, Optional
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import POLYGON_API_KEY
from logger import get_logger, cache_get, cache_set
from config import TTL_POOL

log = get_logger("us_movers")


def get_us_top_active(top_n: int = 30) -> List[Dict]:
    """미장 활발한 종목 상위.
    Polygon -> Yahoo fallback.
    
    Returns: [{ticker, price, change_pct, volume}, ...]
    """
    cached = cache_get("us_movers", TTL_POOL)
    if cached:
        return cached[:top_n]
    
    # 1. Polygon 시도
    if POLYGON_API_KEY:
        try:
            result = _polygon_movers(top_n)
            if result:
                cache_set("us_movers", result)
                return result
        except Exception as e:
            log.warning(f"Polygon 실패, Yahoo fallback: {e}")
    
    # 2. Yahoo Finance fallback (most-active)
    try:
        result = _yahoo_most_active(top_n)
        if result:
            cache_set("us_movers", result)
            return result
    except Exception as e:
        log.warning(f"Yahoo 실패: {e}")
    
    # 3. 최종 fallback - 정적 인기 종목 리스트
    return _fallback_static_list()[:top_n]


def _polygon_movers(top_n: int) -> List[Dict]:
    """Polygon snapshot - gainers/losers/most active"""
    url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers"
    r = requests.get(url, params={"apiKey": POLYGON_API_KEY}, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    tickers = data.get("tickers", []) or []
    
    # most active도 같이
    url2 = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/losers"
    r2 = requests.get(url2, params={"apiKey": POLYGON_API_KEY}, timeout=10)
    if r2.status_code == 200:
        tickers.extend(r2.json().get("tickers", []) or [])
    
    result = []
    seen = set()
    for t in tickers:
        ticker = t.get("ticker", "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        day = t.get("day", {}) or {}
        prev = t.get("prevDay", {}) or {}
        result.append({
            "ticker": ticker,
            "price": float(day.get("c", 0) or 0),
            "change_pct": float(t.get("todaysChangePerc", 0) or 0),
            "volume": int(day.get("v", 0) or 0),
            "volume_value": float(day.get("v", 0) or 0) * float(day.get("vw", 0) or 0),
        })
        if len(result) >= top_n:
            break
    return result


def _yahoo_most_active(top_n: int) -> List[Dict]:
    """Yahoo Finance screener - most active + gainers + losers 합치기"""
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    result = []
    # 거래량 활발 + 상승률 상위 + 낙폭과대(반등 후보)
    for scrid in ["most_actives", "day_gainers", "day_losers"]:
        try:
            r = requests.get(
                url,
                params={"scrIds": scrid, "count": 50, "lang": "en-US", "region": "US"},
                headers=headers,
                timeout=10,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
            for q in quotes:
                ticker = q.get("symbol", "")
                if not ticker or "." in ticker or "-" in ticker:
                    continue
                # ETF 제외 (quoteType이 ETF면)
                qtype = q.get("quoteType", "")
                if qtype == "ETF":
                    continue
                # 알려진 ETF 티커도 제외
                etf_tickers = {"SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VEA", "VWO",
                              "TQQQ", "SQQQ", "SOXL", "SOXS", "TLT", "GLD", "SLV",
                              "ARKK", "XLF", "XLE", "XLK", "XLY", "XLP", "XLV", "XLI",
                              "EEM", "EFA", "AGG", "BND"}
                if ticker in etf_tickers:
                    continue
                # 미국 거래소만
                exch = q.get("fullExchangeName", "")
                if "NYSE" not in exch and "Nasdaq" not in exch and "NASDAQ" not in exch:
                    continue
                # 너무 큰 등락은 작전/뉴스 종목 가능성 - 제외
                chg = float(q.get("regularMarketChangePercent", 0) or 0)
                if abs(chg) > 30:
                    continue
                result.append({
                    "ticker": ticker,
                    "price": float(q.get("regularMarketPrice", 0) or 0),
                    "change_pct": chg,
                    "volume": int(q.get("regularMarketVolume", 0) or 0),
                    "volume_value": float(q.get("regularMarketVolume", 0) or 0) * float(q.get("regularMarketPrice", 0) or 0),
                    "name": q.get("shortName", ""),
                    "market_cap_usd": float(q.get("marketCap", 0) or 0),
                    "source": scrid,
                })
        except Exception as e:
            log.warning(f"Yahoo {scrid} 실패: {e}")
            continue
    
    # 중복 제거 + 정렬 (거래대금 순)
    seen = set()
    dedup = []
    for r in result:
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        dedup.append(r)
    
    dedup.sort(key=lambda x: x["volume_value"], reverse=True)
    return dedup[:top_n]


def _fallback_static_list() -> List[Dict]:
    """모든 API 실패시 정적 인기 종목 리스트"""
    return [
        {"ticker": t, "price": 0, "change_pct": 0, "volume": 0, "volume_value": 1e9}
        for t in [
            "NVDA", "TSLA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "AMZN",
            "PLTR", "SMCI", "COIN", "MSTR", "MARA", "RIOT", "AVGO", "MU",
            "ARM", "SNOW", "NET", "CRWD", "PANW", "ZS", "DDOG", "MDB",
            "SHOP", "UBER", "ABNB", "RBLX", "RIVN", "HOOD",
        ]
    ]
