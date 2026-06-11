"""
core/recommender.py — v3 (옵션 B 통합)

변경점:
1. market_regime_agent 호출 제거 → 사용자 토글값을 인자로 받음
2. event_agent + pattern_agent 통합
3. synthesizer에 indicators / earnings_date 전달 (veto 체크용)
4. 추천 결과 자동 DB 저장

기존 함수 시그니처 유지 + regime 인자 추가 (옵셔널).
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
from agents import (
    chart_agent, fundamental_agent, supply_agent, risk_agent,
    macro_agent, news_agent, synthesizer,
    event_agent, pattern_agent,  # NEW
)
from storage.history import save_recommendation
from logger import get_logger

log = get_logger("recommender")


def _quick_score(stock_data: Dict) -> float:
    ind = stock_data.get("indicators", {})
    if ind.get("error"):
        return 0
    chart = chart_agent.evaluate(ind)
    return chart.get("score", 0)


def _fetch_stock_data(pool_stock: PoolStock, skip_weekly: bool = False) -> Dict[str, Any]:
    market = pool_stock.market
    ticker = pool_stock.ticker
    is_krx = market == Market.KRX

    result = {
        "ticker": ticker,
        "name": pool_stock.name,
        "market": market.value,
        "sector": pool_stock.sector,
        "exchange": pool_stock.exchange,
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

        if not result.get("name"):
            result["name"] = result.get("quote", {}).get("name", ticker)
    except Exception as e:
        log.error(f"데이터 수집 실패 {ticker}: {e}")
        result["error"] = str(e)

    return result


def _fetch_us_extras(ticker: str) -> Dict[str, Any]:
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
    """모든 에이전트 실행 (event + pattern 포함)"""
    ind = stock_data.get("indicators", {})
    weekly_ind = stock_data.get("weekly_indicators")
    quote = stock_data.get("quote", {})
    is_krx = stock_data.get("is_krx", True)
    bars = stock_data.get("daily_bars", [])

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

    # NEW: event + pattern (코드 기반)
    event_result = event_agent.evaluate(stock_info, earnings)
    pattern_result = pattern_agent.evaluate(bars, ind)

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
        "event": event_result,
        "pattern": pattern_result,
    }


def recommend_one(
    market: Market,
    held_tickers: Optional[List[str]] = None,
    excluded_tickers: Optional[List[str]] = None,
    max_retries: int = 3,
    regime: Optional[str] = None,  # NEW: 사용자 토글값 'bull'/'bear'/'sideways'/'unknown'
) -> Optional[Dict[str, Any]]:
    excluded = set((held_tickers or []) + (excluded_tickers or []))
    tried_tickers = []
    last_result = None

    for attempt in range(max_retries):
        result = _recommend_one_attempt(market, excluded | set(tried_tickers), regime)
        if result is None:
            continue
        tried_tickers.append(result["stock_info"]["ticker"])
        last_result = result

        grade = result.get("synthesis", {}).get("grade", "")
        if grade in ("매수", "적극매수"):
            log.info(f"[{market.value}] ✅ 매수 등급 ({attempt+1}회): {result['stock_info']['name']}")
            return result
        else:
            log.info(f"[{market.value}] 시도 {attempt+1}: {result['stock_info']['name']} = {grade}, 재시도")

    log.info(f"[{market.value}] {max_retries}회 후 매수 못 찾음, 마지막 결과 반환")
    return last_result


def _recommend_one_attempt(
    market: Market,
    excluded: set,
    regime: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    log.info(f"[{market.value}] 풀 추출 시작 (regime={regime})")
    pool = build_pool(market)
    if not pool:
        log.error(f"[{market.value}] 풀 비어있음")
        return None

    pool = [p for p in pool if p.ticker not in excluded]
    if not pool:
        log.warning(f"[{market.value}] 제외 후 풀 0")
        return None
    log.info(f"[{market.value}] 풀 {len(pool)}개")

    top_candidates = pool[:15]
    scored = []
    for ps in top_candidates:
        d = _fetch_stock_data(ps, skip_weekly=True)
        if d.get("error") or d.get("indicators", {}).get("error"):
            continue
        # NEW: 5일 +15% 이상 폭등 종목 제외 (추격매수 방지)
        ch5 = (d.get("indicators") or {}).get("change_5d_pct") or 0
        if ch5 > 15:
            log.info(f"  추격매수 방지 제외: {ps.ticker} 5일 +{ch5:.1f}%")
            continue
        d["quick_score"] = _quick_score(d)
        scored.append(d)

    if not scored:
        log.error(f"[{market.value}] 후보 분석 실패")
        return None

    scored.sort(key=lambda x: x["quick_score"], reverse=True)
    top = scored[:POOL_SELECT_TOP]
    if not top:
        return None

    weights = [(s["quick_score"] ** 2) + 1 for s in top]
    chosen = random.choices(top, weights=weights, k=1)[0]

    log.info(f"[{market.value}] 선정: {chosen.get('name')} ({chosen.get('ticker')}) "
             f"1차점수 {chosen['quick_score']:.1f}")

    # 주봉 + 미장 extras 보강
    pool_stock = next((p for p in pool if p.ticker == chosen["ticker"]), None)
    if pool_stock and chosen.get("market") == "KRX":
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
        chosen.update(_fetch_us_extras(chosen["ticker"]))

    # 뉴스
    try:
        if chosen.get("market") == "KRX":
            chosen["news"] = get_news_kr(chosen["ticker"], chosen.get("name", ""))
        else:
            company_name = (chosen.get("profile") or {}).get("name", "") or chosen.get("name", "")
            chosen["news"] = get_news_us(chosen["ticker"], company_name)
    except Exception as e:
        log.warning(f"뉴스 실패: {e}")
        chosen["news"] = []

    # 매크로
    try:
        macro_data = get_macro().get_all()
    except Exception as e:
        log.warning(f"매크로 실패: {e}")
        macro_data = {}

    # 모든 에이전트 실행 (event + pattern 포함)
    log.info(f"[{market.value}] 8 에이전트 분석 시작 (chart/fund/macro/news/supply/risk/event/pattern)")
    agents_results = _run_agents(chosen, macro_data)

    # 종합 - regime 전달 + veto 체크용 데이터 같이 넘김
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
        regime=regime,
        indicators=chosen.get("indicators", {}),
        earnings_date=chosen.get("earnings_date"),
    )

    log.info(f"[{market.value}] ✅ 완료: {chosen.get('name')} - "
             f"{synthesis['grade']} ({synthesis['total_score']:.0f}점)"
             + (f" [VETO: {synthesis.get('vetoed_reason')}]" if synthesis.get("vetoed_reason") else ""))

    full_result = {
        "stock_info": stock_info,
        "quote": chosen.get("quote", {}),
        "indicators": chosen.get("indicators", {}),
        "weekly_indicators": chosen.get("weekly_indicators"),
        "agents": agents_results,
        "synthesis": synthesis,
        "macro": macro_data,
        "news_count": len(chosen.get("news", [])),
        "earnings_date": chosen.get("earnings_date"),
        "regime": regime,
    }

    # DB 저장 (트래킹용)
    try:
        save_recommendation(
            market=stock_info["market"],
            ticker=stock_info["ticker"],
            name=stock_info["name"],
            sector=stock_info["sector"],
            price=chosen.get("quote", {}).get("price", 0),
            grade=synthesis["grade"],
            score=synthesis["total_score"],
            stop_loss=synthesis["prices"]["stop_loss"],
            take_profit=synthesis["prices"]["take_profit"],
            data=full_result,
        )
    except Exception as e:
        log.warning(f"DB 저장 실패 (추천은 정상): {e}")

    return full_result
