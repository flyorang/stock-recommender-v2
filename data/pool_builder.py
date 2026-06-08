"""
data/pool_builder.py
자동 풀 빌더.

매번 한투(국장)/Yahoo(미장)에서 거래대금 상위 종목 가져와서
잡주/관리종목/급등주 필터링 후 후보 풀 구성.
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


# 미장 ticker -> exchange 매핑 (주요 종목)
US_EXCHANGE_MAP = {
    # NASDAQ
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


# 대형 우량주 블랙리스트 - 사용자가 이미 알고 있는 종목 (제외)
KRX_BLACKLIST = {
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "005380",  # 현대차
    "005490",  # POSCO홀딩스
    "035420",  # NAVER
    "035720",  # 카카오
    "051910",  # LG화학
    "006400",  # 삼성SDI
    "373220",  # LG에너지솔루션
    "207940",  # 삼성바이오로직스
    "068270",  # 셀트리온
    "000270",  # 기아
    "105560",  # KB금융
    "055550",  # 신한지주
    "086790",  # 하나금융지주
    "316140",  # 우리금융지주
    "323410",  # 카카오뱅크
    "017670",  # SK텔레콤
    "030200",  # KT
    "032830",  # 삼성생명
    "003550",  # LG
    "066570",  # LG전자
    "015760",  # 한국전력
    "033780",  # KT&G
    "096770",  # SK이노베이션
    "010950",  # S-Oil
    "028260",  # 삼성물산
    "138930",  # BNK금융지주
    "024110",  # 기업은행
    "316140",  # 우리금융지주
    "047810",  # 한국항공우주
    "012330",  # 현대모비스
    "267250",  # HD현대
    "036460",  # 한국가스공사
    "000810",  # 삼성화재
}

US_BLACKLIST = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "BRK.A", "BRK.B", "JNJ", "V", "MA", "PG", "JPM", "BAC", "WMT",
    "HD", "DIS", "NFLX", "ADBE", "ORCL", "CSCO", "INTC", "CRM",
    "PFE", "ABBV", "MRK", "TMO", "ABT", "LLY",
    "XOM", "CVX", "COP",
    "T", "VZ",  # 거대 통신
    "KO", "PEP",  # 거대 음료
    "MCD", "NKE",
    "F", "GM",  # 자동차 대형
}


def _get_exchange(ticker: str) -> str:
    if ticker in US_EXCHANGE_MAP:
        return US_EXCHANGE_MAP[ticker]
    # 기본 NAS
    return "NAS"


def build_krx_pool(force_refresh: bool = False) -> List[PoolStock]:
    """국장 자동 풀.
    
    거래대금 상위 + 거래량 급증 + 상승률 상위 합치기.
    """
    if not force_refresh:
        cached = cache_get("pool_krx_built", TTL_POOL)
        if cached is not None:
            return [PoolStock(**s, market=Market.KRX) if not isinstance(s.get("market"), Market) else PoolStock(**s) 
                    for s in cached]
    
    kis = get_kis()
    all_rows = {}  # ticker -> row (중복 제거)
    
    # 1. 거래대금 상위 50
    try:
        top_value = kis.domestic_top_value(top_n=50)
        for r in top_value:
            t = r.get("ticker", "")
            if t and t not in all_rows:
                r["source"] = "거래대금"
                all_rows[t] = r
    except Exception as e:
        log.warning(f"거래대금 상위 실패: {e}")
    
    # 2. 거래량 급증 30
    try:
        top_volume = kis.domestic_top_volume(top_n=30)
        for r in top_volume:
            t = r.get("ticker", "")
            if t and t not in all_rows:
                r["source"] = "거래량급증"
                all_rows[t] = r
    except Exception as e:
        log.warning(f"거래량 급증 실패: {e}")
    
    # 3. 상승률 상위 30
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
        # 블랙리스트 (대형주 제외)
        if ticker in KRX_BLACKLIST:
            continue
        
        # ETF/ETN 강력 필터
        name = r.get("name", "")
        # 1. ETF 운용사 이름
        etf_brands = [
            "KODEX", "TIGER", "ARIRANG", "KBSTAR", "HANARO", "ACE", "SOL",
            "TIMEFOLIO", "PLUS", "RISE", "WOORI", "KOSEF", "KINDEX",
            "KIWOOM", "MASTER", "FOCUS", "WON", "BNK", "마이다스",
            "한투", "삼성", "신한", "미래에셋", "키움", "NH",
        ]
        # 2. ETF 특성 키워드
        etf_kw = [
            "ETN", "ETF", "레버리지", "인버스", "선물", "곱버스",
            "Fn", "FnGuide", "지수", "인덱스",
            "2X", "3X", "X2", "X3",
        ]
        # 운용사 + 특성 키워드 둘 다 체크
        if any(b in name for b in etf_brands) or any(k in name for k in etf_kw):
            continue
        
        # 3. 종목코드 기반: 한국 ETF는 코드 패턴이 다름 (5자리 시작 등)
        # 일반 주식은 보통 0/1/2/3/4로 시작, ETF는 그 외
        # 보수적으로 보면, 종목코드가 3으로 시작하고 명에 'KIM' 등이 있으면 ETF 가능성
        
        # 거래대금 필터 (너무 작은 종목 제외)
        if r.get("volume_value", 0) < KRX_MIN_VOLUME_VALUE:
            continue
        
        # 너무 비싼 종목 제외 (50만원 초과 - 1주 부담)
        price = r.get("price", 0)
        if price > 500000:
            continue
        
        # 페니스톡 제외 (천원 미만)
        if price > 0 and price < 1000:
            continue
        
        # 급등 너무 큰 거 제외 (이미 +30%↑)
        if abs(r.get("change_pct", 0)) > 25:
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
    
    # 캐시 저장
    cache_set("pool_krx_built", [
        {
            "ticker": p.ticker, "name": p.name, "exchange": p.exchange,
            "sector": p.sector, "price": p.price, "change_pct": p.change_pct,
            "volume_value": p.volume_value, "market_cap": p.market_cap,
            "source": p.source,
        } for p in pool
    ])
    log.info(f"국장 풀 구성: {len(pool)}개 (블랙리스트 제외 후)")
    return pool


def build_us_pool(force_refresh: bool = False) -> List[PoolStock]:
    """미장 자동 풀."""
    if not force_refresh:
        cached = cache_get("pool_us_built", TTL_POOL)
        if cached is not None:
            return [PoolStock(**s, market=Market.US) if not isinstance(s.get("market"), Market) else PoolStock(**s)
                    for s in cached]
    
    try:
        top = get_us_top_active(top_n=80)  # 더 많이 가져오기
    except Exception as e:
        log.error(f"미장 활성 종목 실패: {e}")
        return []
    
    pool = []
    for r in top:
        ticker = r.get("ticker", "")
        if not ticker:
            continue
        
        # 블랙리스트 (대형주)
        if ticker in US_BLACKLIST:
            log.info(f"블랙리스트 제외: {ticker}")
            continue
        
        # 너무 비싼 종목 제외 (1주에 500달러 초과 → 70만원 이상)
        price = r.get("price", 0)
        if price > 500:
            log.info(f"고가 제외: {ticker} (${price:.0f})")
            continue
        
        # 너무 싼 종목도 제외 (페니스톡 위험)
        if price > 0 and price < 3:
            log.info(f"저가 제외: {ticker} (${price:.2f})")
            continue
        
        # 1차 필터
        volume_value = r.get("volume_value", 0)
        if volume_value > 0 and volume_value < US_MIN_VOLUME_USD:
            continue
        
        mc = r.get("market_cap_usd", 0)
        if mc > 0 and mc < US_MIN_MARKET_CAP_USD:
            continue
        
        # 급등 제외
        if abs(r.get("change_pct", 0)) > EXCLUDE_SURGE_5D_PCT:
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
