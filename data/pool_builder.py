"""
data/pool_builder.py — v3.2 패치

변경:
- 당일 ±25% → ±15% 로 강화 (추격매수 방지)
- 풀이 약간 줄어들지만 본인이 원한 "이미 오른 종목 제외" 반영
"""
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    POOL_TOP_N_KRX, POOL_TOP_N_US, TTL_POOL,
    KRX_MIN_MARKET_CAP, KRX_MIN_VOLUME_VALUE,
    US_MIN_MARKET_CAP_USD, US_MIN_VOLUME_USD,
    EXCLUDE_SURGE_5D_PCT,
)
from data.kis_api import get_kis
from data.us_movers import get_us_top_active
from logger import get_logger, cache_get, cache_set

log = get_logger("pool")


class Market(Enum):
    KRX = "KRX"
    US = "US"


@dataclass
class PoolStock:
    ticker: str
    name: str
    market: Market
    exchange: str = ""
    sector: str = ""
    price: float = 0
    change_pct: float = 0
    volume_value: float = 0
    market_cap: float = 0
    source: str = "auto"


US_EXCHANGE_MAP = {
    "AAPL": "NAS", "MSFT": "NAS", "GOOGL": "NAS", "GOOG": "NAS", "AMZN": "NAS",
    "META": "NAS", "NVDA": "NAS", "TSLA": "NAS", "AMD": "NAS", "AVGO": "NAS",
    "ARM": "NAS", "MU": "NAS", "INTC": "NAS", "QCOM": "NAS", "MRVL": "NAS",
    "SMCI": "NAS", "ON": "NAS", "LRCX": "NAS", "AMAT": "NAS", "KLAC": "NAS",
    "ASML": "NAS", "TSM": "NYS", "NFLX": "NAS", "ADBE": "NAS", "COST": "NAS",
    "PYPL": "NAS", "INTU": "NAS", "FTNT": "NAS", "PANW": "NAS", "CRWD": "NAS",
    "ZS": "NAS", "OKTA": "NAS", "DDOG": "NAS", "MDB": "NAS", "TEAM": "NAS",
    "MNDY": "NAS", "CFLT": "NAS", "DUOL": "NAS", "ABNB": "NAS", "DASH": "NAS",
    "MELI": "NAS", "BKNG": "NAS", "PEP": "NAS", "TMUS": "NAS", "CSCO": "NAS",
    "WBD": "NAS", "EA": "NAS", "TTWO": "NAS", "ROBLOX": "NYS", "RBLX": "NYS",
    "MSTR": "NAS", "COIN": "NAS", "MARA": "NAS", "RIOT": "NAS", "CLSK": "NAS",
    "HOOD": "NAS", "SOFI": "NAS", "AFRM": "NAS", "UPST": "NAS",
    "RIVN": "NAS", "LCID": "NAS", "MRNA": "NAS", "VKTX": "NAS",
    "RKLB": "NAS", "ASTS": "NAS", "LUNR": "NAS",
    "RGTI": "NAS", "BBAI": "NYS", "SOUN": "NAS", "PATH": "NYS",
    "CELH": "NAS", "ANF": "NYS",
}


KRX_BLACKLIST = {
    "005930", "000660", "005380", "005490", "035420", "035720", "051910",
    "006400", "373220", "207940", "068270", "000270", "105560", "055550",
    "086790", "316140", "323410", "017670", "030200", "032830", "003550",
    "066570", "015760", "033780", "096770", "010950", "028260", "138930",
    "024110", "047810", "012330", "267250", "036460", "000810",
}

US_BLACKLIST = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "BRK.A", "BRK.B", "JNJ", "V", "MA", "PG", "JPM", "BAC", "WMT",
    "HD", "DIS", "NFLX", "ADBE", "ORCL", "CSCO", "INTC", "CRM",
    "PFE", "ABBV", "MRK", "TMO", "ABT", "LLY",
    "XOM", "CVX", "COP", "T", "VZ", "KO", "PEP", "MCD", "NKE", "F", "GM",
}


def _get_exchange(ticker: str) -> str:
    if ticker in US_EXCHANGE_MAP:
        return US_EXCHANGE_MAP[ticker]
    return "NAS"


def build_krx_pool(force_refresh: bool = False) -> List[PoolStock]:
    if not force_refresh:
        cached = cache_get("pool_krx_built", TTL_POOL)
        if cached is not None:
            return [PoolStock(**s, market=Market.KRX) if not isinstance(s.get("market"), Market) else PoolStock(**s)
                    for s in cached]

    kis = get_kis()
    all_rows = {}

    try:
        top_value = kis.domestic_top_value(top_n=50)
        for r in top_value:
            t = r.get("ticker", "")
            if t and t not in all_rows:
                r["source"] = "거래대금"
                all_rows[t] = r
    except Exception as e:
        log.warning(f"거래대금 상위 실패: {e}")

    try:
        top_volume = kis.domestic_top_volume(top_n=30)
        for r in top_volume:
            t = r.get("ticker", "")
            if t and t not in all_rows:
                r["source"] = "거래량급증"
                all_rows[t] = r
    except Exception as e:
        log.warning(f"거래량 급증 실패: {e}")

    try:
        top_gainers = kis.domestic_top_gainers(top_n=30)
        for r in top_gainers:
            t = r.get("ticker", "")
            if t and t not in all_rows:
                r["source"] = "상승률"
                all_rows[t] = r
    except Exception as e:
        log.warning(f"상승률 상위 실패: {e}")

    log.info(f"국장 원천 데이터 (중복 제거): {len(all_rows)}개")

    pool = []
    for ticker, r in all_rows.items():
        if ticker in KRX_BLACKLIST:
            continue

        name = r.get("name", "")
        etf_brands = [
            "KODEX", "TIGER", "ARIRANG", "KBSTAR", "HANARO", "ACE", "SOL",
            "TIMEFOLIO", "PLUS", "RISE", "WOORI", "KOSEF", "KINDEX",
            "KIWOOM", "MASTER", "FOCUS", "WON", "BNK", "마이다스",
            "한투", "삼성", "신한", "미래에셋", "키움", "NH",
        ]
        etf_kw = [
            "ETN", "ETF", "레버리지", "인버스", "선물", "곱버스",
            "Fn", "FnGuide", "지수", "인덱스",
            "2X", "3X", "X2", "X3",
        ]
        if any(b in name for b in etf_brands) or any(k in name for k in etf_kw):
            continue

        if r.get("volume_value", 0) < KRX_MIN_VOLUME_VALUE:
            continue

        price = r.get("price", 0)
        if price > 500000:
            continue
        if price > 0 and price < 1000:
            continue

        # 추격매수 방지 — 당일 ±15% 이상 제외 (이전 25%→15% 강화)
        if abs(r.get("change_pct", 0)) > 15:
            continue

        pool.append(PoolStock(
            ticker=ticker,
            name=r.get("name", ""),
            market=Market.KRX,
            price=r.get("price", 0),
            change_pct=r.get("change_pct", 0),
            volume_value=r.get("volume_value", 0),
            source=r.get("source", "auto"),
        ))

    cache_set("pool_krx_built", [
        {
            "ticker": p.ticker, "name": p.name, "exchange": p.exchange,
            "sector": p.sector, "price": p.price, "change_pct": p.change_pct,
            "volume_value": p.volume_value, "market_cap": p.market_cap,
            "source": p.source,
        } for p in pool
    ])
    log.info(f"국장 풀 구성: {len(pool)}개")
    return pool


def build_us_pool(force_refresh: bool = False) -> List[PoolStock]:
    if not force_refresh:
        cached = cache_get("pool_us_built", TTL_POOL)
        if cached is not None:
            return [PoolStock(**s, market=Market.US) if not isinstance(s.get("market"), Market) else PoolStock(**s)
                    for s in cached]

    try:
        top = get_us_top_active(top_n=80)
    except Exception as e:
        log.error(f"미장 활성 종목 실패: {e}")
        return []

    pool = []
    for r in top:
        ticker = r.get("ticker", "")
        if not ticker:
            continue
        if ticker in US_BLACKLIST:
            continue

        price = r.get("price", 0)
        if price > 500:
            continue
        if price > 0 and price < 3:
            continue

        volume_value = r.get("volume_value", 0)
        if volume_value > 0 and volume_value < US_MIN_VOLUME_USD:
            continue

        mc = r.get("market_cap_usd", 0)
        if mc > 0 and mc < US_MIN_MARKET_CAP_USD:
            continue

        # 추격매수 방지 — 당일 ±15% 이상 제외
        if abs(r.get("change_pct", 0)) > 15:
            continue

        pool.append(PoolStock(
            ticker=ticker,
            name=r.get("name", ""),
            market=Market.US,
            exchange=_get_exchange(ticker),
            price=r.get("price", 0),
            change_pct=r.get("change_pct", 0),
            volume_value=volume_value,
            market_cap=mc,
            source="us_movers",
        ))

    cache_set("pool_us_built", [
        {
            "ticker": p.ticker, "name": p.name, "exchange": p.exchange,
            "sector": p.sector, "price": p.price, "change_pct": p.change_pct,
            "volume_value": p.volume_value, "market_cap": p.market_cap,
            "source": p.source,
        } for p in pool
    ])
    log.info(f"미장 풀 구성: {len(pool)}개")
    return pool


def build_pool(market: Market, force_refresh: bool = False) -> List[PoolStock]:
    if market == Market.KRX:
        return build_krx_pool(force_refresh)
    return build_us_pool(force_refresh)
