"""
agents/event_agent.py — NEW (실적/공시 이벤트 분석가)

한국: DART API로 최근 공시 조회
미국: Finnhub earnings_calendar (이미 recommender에서 가져옴)

출력:
- score (0~100, 안전할수록 높음)
- veto_flag (True면 synthesizer가 강제 회피)
- recent_events (최근 이벤트 리스트)
- comment (한 줄 요약)

AI 호출 X (코드 계산).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import sys
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DART_API_KEY
from logger import get_logger, cache_get, cache_set

log = get_logger("event_agent")


# ════════════════════════════════════════════════════════════
# DART 공시 분류 - 호재/악재/중립
# ════════════════════════════════════════════════════════════
# DART 보고서 분류 키워드 (제목 부분 매칭)
POSITIVE_KEYWORDS = [
    "단일판매·공급계약", "공급계약", "수주", "신규시설투자", "주식분할",
    "자기주식취득", "유상감자",  # 주주환원
    "흑자전환", "어닝서프라이즈",
]
NEGATIVE_KEYWORDS = [
    "유상증자", "전환사채발행", "신주인수권부사채", "교환사채",  # 희석
    "감자", "관리종목지정", "상장폐지", "거래정지",
    "횡령", "배임", "분식회계", "감사의견", "회계감리",
    "주식병합",  # 보통 악재
]
EARNINGS_KEYWORDS = [
    "영업(잠정)실적", "잠정실적", "매출액또는손익구조", "결산실적",
]


def _fetch_dart_recent(corp_code: str, days: int = 14) -> List[Dict]:
    """DART 최근 공시 조회.
    
    Args:
        corp_code: DART 고유번호 (8자리). 종목코드 아님.
                   별도 매핑 필요. 일단 종목코드 → 회사명으로 검색.
    """
    if not DART_API_KEY:
        return []

    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bgn_de": start.strftime("%Y%m%d"),
                "end_de": end.strftime("%Y%m%d"),
                "page_count": 50,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status") != "000":
            return []
        return data.get("list", [])
    except Exception as e:
        log.warning(f"DART {corp_code}: {e}")
        return []


def _get_dart_corp_code(ticker: str) -> Optional[str]:
    """종목코드 → DART 고유번호 매핑 (캐시).
    
    DART 코드 ZIP을 다운받아 파싱하는 게 정석이지만,
    캐시로 자주 쓰는 종목만 미리 매핑하는 게 빠름.
    실제 운영에서는 DART corpCode.xml 다운받아 변환 권장.
    """
    cached = cache_get(f"dart_corp:{ticker}", 86400 * 30)  # 30일 캐시
    if cached:
        return cached

    # 자동 매핑 시도 (DART 회사 검색 API)
    if not DART_API_KEY:
        return None
    try:
        # DART는 종목코드로 직접 회사검색이 안 됨
        # corpCode.xml 다운받아 매핑하는 게 정석이나 첫 호출 시 1회만
        # 일단 None 반환 → 사용자가 _DART_TICKER_MAP에 직접 추가
        return None
    except Exception:
        return None


def _classify_event(title: str) -> Dict[str, Any]:
    """공시 제목 → 분류"""
    is_positive = any(k in title for k in POSITIVE_KEYWORDS)
    is_negative = any(k in title for k in NEGATIVE_KEYWORDS)
    is_earnings = any(k in title for k in EARNINGS_KEYWORDS)

    if is_negative:
        impact = "negative"
    elif is_positive:
        impact = "positive"
    elif is_earnings:
        impact = "earnings"
    else:
        impact = "neutral"

    return {"impact": impact}


def evaluate_kr(stock_info: Dict) -> Dict[str, Any]:
    """한국 종목 이벤트 평가"""
    ticker = stock_info.get("ticker", "")
    corp_code = _get_dart_corp_code(ticker)

    if not corp_code:
        return {
            "score": 60,  # 정보 없으면 중립+ (없는 게 보수적이라 약간 가산)
            "veto_flag": False,
            "recent_events": [],
            "comment": "공시 데이터 없음 (DART 매핑 필요)",
        }

    events = _fetch_dart_recent(corp_code, days=14)

    classified = []
    pos_count = 0
    neg_count = 0
    for ev in events:
        title = ev.get("report_nm", "")
        cls = _classify_event(title)
        classified.append({
            "date": ev.get("rcept_dt", ""),
            "title": title,
            "impact": cls["impact"],
        })
        if cls["impact"] == "positive":
            pos_count += 1
        elif cls["impact"] == "negative":
            neg_count += 1

    # 점수 산정
    score = 60
    veto_flag = False
    veto_reason = None

    if neg_count >= 2:
        # 14일 내 악재 공시 2건 이상 → 강한 부정
        score -= neg_count * 15
        if neg_count >= 3:
            veto_flag = True
            veto_reason = f"14일 내 악재 공시 {neg_count}건"
    elif neg_count == 1:
        score -= 10

    if pos_count >= 2:
        score += min(pos_count * 8, 20)
    elif pos_count == 1:
        score += 5

    score = max(0, min(100, score))

    # 코멘트
    if veto_flag:
        comment = f"⛔ {veto_reason}"
    elif neg_count > 0:
        comment = f"악재 공시 {neg_count}건"
    elif pos_count > 0:
        comment = f"호재 공시 {pos_count}건"
    else:
        comment = "주요 공시 없음"

    return {
        "score": round(score, 1),
        "veto_flag": veto_flag,
        "veto_reason": veto_reason,
        "recent_events": classified[:5],
        "positive_count": pos_count,
        "negative_count": neg_count,
        "comment": comment,
    }


def evaluate_us(stock_info: Dict, earnings_date: Optional[Dict] = None) -> Dict[str, Any]:
    """미국 종목 이벤트 평가 (Finnhub earnings 이미 있음)"""
    score = 60
    veto_flag = False
    veto_reason = None
    events = []

    if earnings_date:
        d = earnings_date.get("date")
        days_until = earnings_date.get("days_until")
        eps_estimate = earnings_date.get("estimate")
        if d and days_until is not None:
            events.append({
                "date": d,
                "title": f"실적발표 D-{days_until}",
                "impact": "earnings",
                "estimate": eps_estimate,
            })

            # D-3 이내는 변동성 큼 - 점수 차감
            if 0 <= days_until <= 3:
                score -= 20
                veto_flag = False  # synthesizer veto 체크에서 다른 조건과 결합
            elif 4 <= days_until <= 7:
                score -= 10

    score = max(0, min(100, score))

    if events:
        comment = events[0]["title"]
    else:
        comment = "이벤트 없음"

    return {
        "score": round(score, 1),
        "veto_flag": veto_flag,
        "veto_reason": veto_reason,
        "recent_events": events,
        "comment": comment,
    }


def evaluate(stock_info: Dict, earnings_date: Optional[Dict] = None) -> Dict[str, Any]:
    """라우터: 시장 따라 KR/US 분기"""
    market = stock_info.get("market", "KRX")
    if market == "KRX":
        return evaluate_kr(stock_info)
    else:
        return evaluate_us(stock_info, earnings_date)
