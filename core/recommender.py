"""
core/recommender.py
통합 추천 엔진. 전체 흐름:

1. 자동 풀 추출 (캐시)
2. 풀 1차 스크리닝 (간단 점수)
3. 상위 N개에서 1개 선정 (가중 랜덤)
4. 선정 종목 풀 분석 (시세, 일봉, 주봉, 수급, 뉴스, 매크로)
5. 6 에이전트 평가 (병렬)
6. 종합 판정관
7. 검증 + 결과 반환
"""
import random
import concurrent.futures
from typing import Dict, Any, Optional, List
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import POOL_SELECT_TOP
from data.kis_api import get_kis
from data.finnhub_api import get_finnhub
from data.macro_api import get_macro
from data.pool_builder import build_pool, Market, PoolStock
from data.news_api import get_news_kr, get_news_us
from analysis.indicators import analyze_bars
from agents import chart_agent, fundamental_agent, supply_agent, risk_agent, macro_agent, news_agent, synthesizer
from logger import get_logger, cache_get, cache_set
from config import TTL_AGENT_RESULT

log = get_logger("recommender")


def _quick_score(stock_data: Dict) -> float:
    """1차 스크리닝 - 간단한 차트 점수만으로 후보 추리기."""
    ind = stock_data.get("indicators", {})
    if ind.get("error"):
        return 0
    
    chart = chart_agent.evaluate(ind)
    return chart.get("score", 0)


def _fetch_stock_data(
    pool_stock: PoolStock,
    skip_weekly: bool = False,
) -> Dict[str, Any]:
    """종목 1개의 모든 데이터 수집."""
    market = pool_stock.market
    ticker = pool_stock.ticker
    is_krx = market == Market.KRX
    
    result = {
        "ticker": ticker,
        "name": pool_stock.name,
        "market": market.value,
        "sector": pool_stock.sector,
        "is_krx": is_krx,
    }
    
    try:
        kis = get_kis()
        if is_krx:
            result["quote"] = kis.domestic_price(ticker)
            result["daily_bars"] = kis.domestic_daily(ticker, days=130)
            result["indicators"] = analyze_bars(result["daily_bars"])
            if not skip_weekly:
                try:
                    result["weekly_bars"] = kis.domestic_weekly(ticker, weeks=52)
                    result["weekly_indicators"] = analyze_bars(result["weekly_bars"])
                except Exception as e:
                    log.warning(f"주봉 실패 {ticker}: {e}")
            try:
                result["investor_flow"] = kis.domestic_investor_flow(ticker)
            except Exception as e:
                log.warning(f"수급 실패 {ticker}: {e}")
        else:
            exch = pool_stock.exchange or "NAS"
            result["quote"] = kis.overseas_price(ticker, exch)
            result["daily_bars"] = kis.overseas_daily(ticker, exch, days=130)
            result["indicators"] = analyze_bars(result["daily_bars"])
            if not skip_weekly:
                try:
                    result["weekly_bars"] = kis.overseas_weekly(ticker, exch, weeks=52)
                    result["weekly_indicators"] = analyze_bars(result["weekly_bars"])
                except Exception as e:
                    log.warning(f"미장 주봉 실패 {ticker}: {e}")
        
        # 이름 보강
        if not result.get("name"):
            result["name"] = result.get("quote", {}).get("name", ticker)
    except Exception as e:
        log.error(f"데이터 수집 실패 {ticker}: {e}")
        result["error"] = str(e)
    
    return result


def _fetch_us_extras(ticker: str) -> Dict[str, Any]:
    """미장 보강: profile, metrics, earnings"""
    try:
        fh = get_finnhub()
        return {
            "profile": fh.profile(ticker),
            "metrics": fh.metrics(ticker),
            "earnings_date": fh.earnings_calendar(ticker),
        }
    except Exception as e:
        log.warning(f"미장 보강 실패 {ticker}: {e}")
        return {}


def _run_agents(stock_data: Dict, macro_data: Dict) -> Dict[str, Any]:
    """6 에이전트 병렬 실행."""
    ind = stock_data.get("indicators", {})
    weekly_ind = stock_data.get("weekly_indicators")
    quote = stock_data.get("quote", {})
    is_krx = stock_data.get("is_krx", True)
    
    profile = stock_data.get("profile")
    metrics = stock_data.get("metrics")
    earnings = stock_data.get("earnings_date")
    investor_flow = stock_data.get("investor_flow")
    news = stock_data.get("news", [])
    
    stock_info = {
        "ticker": stock_data.get("ticker"),
        "name": stock_data.get("name"),
        "market": stock_data.get("market"),
        "sector": stock_data.get("sector"),
    }
    
    # 코드 기반 에이전트 (즉시 실행)
    chart_result = chart_agent.evaluate(ind, weekly_ind)
    fundamental_result = fundamental_agent.evaluate(quote, profile, metrics, is_krx)
    supply_result = supply_agent.evaluate(quote, investor_flow, ind, is_krx)
    risk_result = risk_agent.evaluate(quote, ind, earnings, is_krx)
    
    # AI 에이전트 병렬
    macro_result, news_result = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_macro = ex.submit(macro_agent.evaluate, stock_info, macro_data)
        f_news = ex.submit(news_agent.evaluate, stock_info, news)
        macro_result = f_macro.result()
        news_result = f_news.result()
    
    return {
        "chart": chart_result,
        "fundamental": fundamental_result,
        "macro": macro_result,
        "news": news_result,
        "supply": supply_result,
        "risk": risk_result,
    }


def recommend_one(
    market: Market,
    held_tickers: Optional[List[str]] = None,
    excluded_tickers: Optional[List[str]] = None,
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """시장당 1개 추천. 관망/회피 시 최대 max_retries번까지 재시도.
    """
    excluded = set((held_tickers or []) + (excluded_tickers or []))
    tried_tickers = []  # 시도한 종목 추적
    
    last_result = None  # 마지막 결과 (전부 실패 시 폴백)
    
    for attempt in range(max_retries):
        result = _recommend_one_attempt(market, excluded | set(tried_tickers))
        if result is None:
            continue
        
        tried_tickers.append(result["stock_info"]["ticker"])
        last_result = result
        
        grade = result.get("synthesis", {}).get("grade", "")
        if grade in ("매수", "적극매수"):
            log.info(f"[{market.value}] ✅ 매수 등급 ({attempt+1}회 시도): {result['stock_info']['name']}")
            return result
        else:
            log.info(f"[{market.value}] 시도 {attempt+1}: {result['stock_info']['name']} = {grade}, 재시도")
    
    # 매수 못 찾으면 마지막 결과 반환
    log.info(f"[{market.value}] {max_retries}회 시도 후 매수 등급 못 찾음, 마지막 결과 반환")
    return last_result


def _recommend_one_attempt(
    market: Market,
    excluded: set,
) -> Optional[Dict[str, Any]]:
    """1회 추천 시도"""
    
    # 1. 풀 추출
    log.info(f"[{market.value}] 풀 추출 시작")
    pool = build_pool(market)
    if not pool:
        log.error(f"[{market.value}] 풀 비어있음")
        return None
    
    # 제외 종목 필터
    pool = [p for p in pool if p.ticker not in excluded]
    if not pool:
        log.warning(f"[{market.value}] 제외 후 풀 0")
        return None
    
    log.info(f"[{market.value}] 풀 {len(pool)}개")
    
    # 2. 1차 스크리닝 - 거래대금/모멘텀 기준 상위 후보를 더 많이 가져가 차트 점수
    top_candidates = pool[:15]
    
    scored = []
    for ps in top_candidates:
        d = _fetch_stock_data(ps, skip_weekly=True)
        if d.get("error"):
            continue
        if d.get("indicators", {}).get("error"):
            continue
        d["quick_score"] = _quick_score(d)
        scored.append(d)
    
    if not scored:
        log.error(f"[{market.value}] 후보 분석 실패")
        return None
    
    # 3. 상위 N개 가중 랜덤
    scored.sort(key=lambda x: x["quick_score"], reverse=True)
    top = scored[:POOL_SELECT_TOP]
    if not top:
        return None
    
    weights = [(s["quick_score"] ** 2) + 1 for s in top]
    chosen = random.choices(top, weights=weights, k=1)[0]
    
    log.info(f"[{market.value}] 선정: {chosen.get('name')} ({chosen.get('ticker')}) "
             f"1차점수 {chosen['quick_score']:.1f}")
    
    # 4. 선정 종목 - 주봉 + 미장 extras + 뉴스 추가 수집
    pool_stock = next((p for p in pool if p.ticker == chosen["ticker"]), None)
    if pool_stock and chosen.get("market") == "KRX":
        # 주봉 추가
        try:
            kis = get_kis()
            chosen["weekly_bars"] = kis.domestic_weekly(chosen["ticker"], weeks=52)
            chosen["weekly_indicators"] = analyze_bars(chosen["weekly_bars"])
        except Exception as e:
            log.warning(f"주봉 보강 실패: {e}")
    elif pool_stock and chosen.get("market") == "US":
        try:
            kis = get_kis()
            chosen["weekly_bars"] = kis.overseas_weekly(
                chosen["ticker"], pool_stock.exchange or "NAS", weeks=52
            )
            chosen["weekly_indicators"] = analyze_bars(chosen["weekly_bars"])
        except Exception as e:
            log.warning(f"미장 주봉 보강 실패: {e}")
        
        # Finnhub 보강
        chosen.update(_fetch_us_extras(chosen["ticker"]))
    
    # 뉴스 수집
    try:
        if chosen.get("market") == "KRX":
            chosen["news"] = get_news_kr(chosen["ticker"], chosen.get("name", ""))
        else:
            company_name = (chosen.get("profile") or {}).get("name", "") or chosen.get("name", "")
            chosen["news"] = get_news_us(chosen["ticker"], company_name)
    except Exception as e:
        log.warning(f"뉴스 실패: {e}")
        chosen["news"] = []
    
    # 5. 매크로
    try:
        macro_data = get_macro().get_all()
    except Exception as e:
        log.warning(f"매크로 실패: {e}")
        macro_data = {}
    
    # 6. 6 에이전트 실행
    log.info(f"[{market.value}] 6 에이전트 분석 시작")
    agents_results = _run_agents(chosen, macro_data)
    
    # 7. 종합 판정관
    stock_info = {
        "ticker": chosen["ticker"],
        "name": chosen.get("name", ""),
        "sector": chosen.get("sector", ""),
        "market": chosen.get("market", ""),
    }
    synthesis = synthesizer.evaluate(
        stock_info=stock_info,
        quote=chosen.get("quote", {}),
        agents=agents_results,
        is_krx=(chosen.get("market") == "KRX"),
    )
    
    log.info(f"[{market.value}] ✅ 완료: {chosen.get('name')} - "
             f"{synthesis['grade']} ({synthesis['total_score']:.0f}점)")
    
    return {
        "stock_info": stock_info,
        "quote": chosen.get("quote", {}),
        "indicators": chosen.get("indicators", {}),
        "weekly_indicators": chosen.get("weekly_indicators"),
        "agents": agents_results,
        "synthesis": synthesis,
        "macro": macro_data,
        "news_count": len(chosen.get("news", [])),
        "earnings_date": chosen.get("earnings_date"),
    }
