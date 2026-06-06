"""
data/finnhub_api.py
Finnhub - 미장 보조 데이터.

- 거래대금 상위 (활성 종목)
- 회사 프로필, 시총
- 기본 재무 (PER, PBR, ROE)
- 실적 발표일
"""
import time
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path
import sys
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FINNHUB_API_KEY
from logger import get_logger

log = get_logger("finnhub")


class FinnhubError(Exception):
    pass


class FinnhubClient:
    BASE = "https://finnhub.io/api/v1"
    
    def __init__(self):
        self.key = FINNHUB_API_KEY
        self._last = 0.0
        self._min_int = 1.1  # 분당 60회 안전
    
    def _throttle(self):
        e = time.time() - self._last
        if e < self._min_int:
            time.sleep(self._min_int - e)
        self._last = time.time()
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        self._throttle()
        params = params or {}
        params["token"] = self.key
        try:
            r = requests.get(f"{self.BASE}{endpoint}", params=params, timeout=10)
            if r.status_code == 429:
                time.sleep(3)
                r = requests.get(f"{self.BASE}{endpoint}", params=params, timeout=10)
            if r.status_code != 200:
                raise FinnhubError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        except requests.RequestException as e:
            raise FinnhubError(f"네트워크: {e}")
    
    def quote(self, ticker: str) -> Dict[str, Any]:
        d = self._get("/quote", {"symbol": ticker})
        if not d or d.get("c") in (0, None):
            raise FinnhubError(f"시세 없음: {ticker}")
        return {
            "ticker": ticker,
            "price": float(d.get("c", 0)),
            "change": float(d.get("d", 0) or 0),
            "change_pct": float(d.get("dp", 0) or 0),
            "high": float(d.get("h", 0) or 0),
            "low": float(d.get("l", 0) or 0),
            "open": float(d.get("o", 0) or 0),
            "prev_close": float(d.get("pc", 0) or 0),
        }
    
    def profile(self, ticker: str) -> Dict[str, Any]:
        try:
            d = self._get("/stock/profile2", {"symbol": ticker})
            return {
                "ticker": ticker,
                "name": d.get("name", ""),
                "industry": d.get("finnhubIndustry", ""),
                "country": d.get("country", ""),
                "exchange": d.get("exchange", ""),
                "market_cap_musd": float(d.get("marketCapitalization", 0) or 0),
                "ipo": d.get("ipo", ""),
                "shares_outstanding": float(d.get("shareOutstanding", 0) or 0),
            }
        except Exception as e:
            log.warning(f"profile 실패 {ticker}: {e}")
            return {}
    
    def metrics(self, ticker: str) -> Dict[str, Any]:
        try:
            d = self._get("/stock/metric", {"symbol": ticker, "metric": "all"})
            m = d.get("metric", {}) if d else {}
            return {
                "pe": float(m.get("peNormalizedAnnual", 0) or 0),
                "pb": float(m.get("pbAnnual", 0) or 0),
                "roe": float(m.get("roeRfy", 0) or 0),
                "dividend_yield": float(m.get("dividendYieldIndicatedAnnual", 0) or 0),
                "high_52w": float(m.get("52WeekHigh", 0) or 0),
                "low_52w": float(m.get("52WeekLow", 0) or 0),
                "beta": float(m.get("beta", 0) or 0),
                "ev_ebitda": float(m.get("currentEv/freeCashFlowTTM", 0) or 0),
                "revenue_growth_ttm": float(m.get("revenueGrowthTTMYoy", 0) or 0),
                "eps_growth_ttm": float(m.get("epsGrowthTTMYoy", 0) or 0),
            }
        except Exception as e:
            log.warning(f"metrics 실패 {ticker}: {e}")
            return {}
    
    def earnings_calendar(self, ticker: str) -> Optional[Dict]:
        """다음 실적 발표일"""
        today = date.today()
        end = today + timedelta(days=60)
        try:
            d = self._get("/calendar/earnings", {
                "from": today.isoformat(),
                "to": end.isoformat(),
                "symbol": ticker,
            })
            earnings = d.get("earningsCalendar", []) if d else []
            if earnings:
                e = earnings[0]
                return {
                    "date": e.get("date", ""),
                    "eps_estimate": e.get("epsEstimate"),
                    "hour": e.get("hour", ""),
                    "days_until": (
                        datetime_from_str(e.get("date", "")) - today
                    ).days if e.get("date") else None,
                }
        except Exception as e:
            log.warning(f"earnings 실패 {ticker}: {e}")
        return None
    
    def top_movers(self, exchange: str = "US") -> List[Dict]:
        """주요 시장의 활발한 종목 목록 - Finnhub은 symbol list만 줘서
        실제 거래대금 상위는 quote 호출로 직접 확인 필요.
        대신 'stock/symbol' 로 활성 종목 목록 + Polygon 활용."""
        # 미장은 별도 풀러에서 처리 (us_movers.py)
        return []


def datetime_from_str(s: str):
    from datetime import datetime
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return date.today()


_client: Optional[FinnhubClient] = None


def get_finnhub() -> FinnhubClient:
    global _client
    if _client is None:
        _client = FinnhubClient()
    return _client
