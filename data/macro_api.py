"""
data/macro_api.py — v2 패치 (제미나이 + ChatGPT 지적 반영)

추가:
1. 이벤트 캐시 무효화 — FOMC/CPI/금통위 발표일/직후 자동 강제 갱신
2. force_refresh 인자 — 수동 갱신 옵션
3. is_event_window() — 현재가 이벤트 직후 24시간 이내인지 체크

기존 호출부 100% 호환. 추가 기능만 들어감.
"""
import requests
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FRED_API_KEY, ALPHA_VANTAGE_API_KEY, TTL_MACRO
from logger import get_logger, cache_get, cache_set, cache_delete

log = get_logger("macro")


# ════════════════════════════════════════════════════════════
# 이벤트 캘린더 — 매크로 캐시 무효화 트리거
# 신규/임박 발표 있을 때 캐시 강제 갱신
# ════════════════════════════════════════════════════════════
# 형식: (날짜 YYYY-MM-DD, 이벤트 종류, 영향도 1~3)
# 사용자가 직접 추가/수정. 매월 첫 주에 갱신 권장.
EVENT_CALENDAR: List[Dict] = [
    # === FOMC 2026 ===
    {"date": "2026-01-28", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-03-18", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-04-29", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-06-17", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-07-29", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-09-16", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-10-28", "event": "FOMC 금리결정", "impact": 3},
    {"date": "2026-12-09", "event": "FOMC 금리결정", "impact": 3},

    # === 한국은행 금통위 (월 1회 추정, 실제 일정 확인 필요) ===
    {"date": "2026-01-15", "event": "한은 금통위", "impact": 3},
    {"date": "2026-02-26", "event": "한은 금통위", "impact": 3},
    {"date": "2026-04-09", "event": "한은 금통위", "impact": 3},
    {"date": "2026-05-28", "event": "한은 금통위", "impact": 3},
    {"date": "2026-07-09", "event": "한은 금통위", "impact": 3},
    {"date": "2026-08-27", "event": "한은 금통위", "impact": 3},
    {"date": "2026-10-15", "event": "한은 금통위", "impact": 3},
    {"date": "2026-11-26", "event": "한은 금통위", "impact": 3},

    # === 미국 CPI (매월 둘째 주 수요일경) ===
    {"date": "2026-01-14", "event": "美 CPI", "impact": 2},
    {"date": "2026-02-11", "event": "美 CPI", "impact": 2},
    {"date": "2026-03-11", "event": "美 CPI", "impact": 2},
    {"date": "2026-04-15", "event": "美 CPI", "impact": 2},
    {"date": "2026-05-13", "event": "美 CPI", "impact": 2},
    {"date": "2026-06-10", "event": "美 CPI", "impact": 2},
    {"date": "2026-07-15", "event": "美 CPI", "impact": 2},
    {"date": "2026-08-12", "event": "美 CPI", "impact": 2},
    {"date": "2026-09-09", "event": "美 CPI", "impact": 2},
    {"date": "2026-10-14", "event": "美 CPI", "impact": 2},
    {"date": "2026-11-12", "event": "美 CPI", "impact": 2},
    {"date": "2026-12-10", "event": "美 CPI", "impact": 2},

    # === 미국 고용지표 (매월 첫째 주 금요일) ===
    {"date": "2026-01-09", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-02-06", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-03-06", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-04-03", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-05-01", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-06-05", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-07-03", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-08-07", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-09-04", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-10-02", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-11-06", "event": "美 비농업고용", "impact": 2},
    {"date": "2026-12-04", "event": "美 비농업고용", "impact": 2},
]


def get_recent_events(within_hours: int = 24) -> List[Dict]:
    """현재로부터 within_hours 이내에 발생/예정된 이벤트.
    
    캐시 무효화 판단용. 임팩트 2 이상 이벤트만 반환.
    """
    now = datetime.now()
    upcoming = []
    for ev in EVENT_CALENDAR:
        if ev.get("impact", 0) < 2:
            continue
        try:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d")
            # 이벤트 -6시간 ~ +24시간 윈도우
            delta_hours = (now - ev_date).total_seconds() / 3600
            if -6 <= delta_hours <= within_hours:
                upcoming.append({
                    **ev,
                    "hours_from_now": round(delta_hours, 1),
                })
        except ValueError:
            continue
    return upcoming


def is_event_window() -> bool:
    """현재가 매크로 이벤트 직전/직후 윈도우인지"""
    return len(get_recent_events()) > 0


# 매크로 캐시 키 목록 (무효화 시 일괄 삭제)
MACRO_CACHE_KEYS = [
    "macro_kospi", "macro_sp500", "macro_nasdaq",
    "macro_vix", "macro_wti", "macro_dxy",
    "macro_us10y", "macro_us2y",
    "macro_usdkrw", "macro_fng",
]


def invalidate_macro_cache():
    """매크로 캐시 일괄 삭제 — 이벤트 직후 자동 호출됨"""
    for key in MACRO_CACHE_KEYS:
        cache_delete(key)
    log.info("📢 매크로 캐시 일괄 무효화 (이벤트 트리거)")


# 마지막 이벤트 체크 시점 (메모리 캐시)
_last_event_check = {"ts": 0, "had_event": False}


def _check_and_invalidate_on_event():
    """매크로 fetch 시 자동 호출. 이벤트 윈도우 진입 시 1회 캐시 무효화."""
    import time
    now = time.time()
    # 1분에 한 번씩만 체크
    if now - _last_event_check["ts"] < 60:
        return
    _last_event_check["ts"] = now

    had_event = is_event_window()
    if had_event and not _last_event_check["had_event"]:
        # 이벤트 윈도우 새로 진입 → 캐시 무효화
        invalidate_macro_cache()
    _last_event_check["had_event"] = had_event


class MacroData:
    def get_all(self, force_refresh: bool = False) -> Dict[str, Any]:
        """전체 매크로 데이터.
        
        force_refresh=True면 캐시 무시.
        이벤트 윈도우면 자동 무효화.
        """
        if force_refresh:
            invalidate_macro_cache()
        else:
            _check_and_invalidate_on_event()

        recent_evs = get_recent_events()
        return {
            "usd_krw": self.usd_krw(),
            "vix": self.vix(),
            "us10y": self.us_10y(),
            "yield_curve": self.yield_curve(),
            "fear_greed": self.fear_greed(),
            "kospi": self.kospi(),
            "sp500": self.sp500(),
            "nasdaq": self.nasdaq(),
            "wti": self.wti(),
            "dxy": self.dxy(),
            "recent_events": recent_evs,
            "in_event_window": len(recent_evs) > 0,
            "updated_at": datetime.now().isoformat(),
        }

    # ===== Yahoo Finance helper =====
    def _yahoo_chart(self, symbol: str, range_: str = "1mo") -> Optional[Dict]:
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"interval": "1d", "range": range_},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()["chart"]["result"][0]
            meta = data["meta"]
            closes = [c for c in data["indicators"]["quote"][0]["close"] if c is not None]
            current = meta["regularMarketPrice"]
            ma20 = sum(closes[-20:]) / min(len(closes), 20) if closes else current
            prev = meta.get("chartPreviousClose", current)
            return {
                "price": float(current),
                "change_pct": (current / prev - 1) * 100 if prev else 0,
                "ma20": float(ma20),
                "above_ma20": current > ma20,
            }
        except Exception as e:
            log.warning(f"Yahoo {symbol}: {e}")
            return None

    def kospi(self) -> Optional[Dict]:
        cached = cache_get("macro_kospi", TTL_MACRO)
        if cached is not None: return cached
        d = self._yahoo_chart("^KS11")
        if d: cache_set("macro_kospi", d)
        return d

    def sp500(self) -> Optional[Dict]:
        cached = cache_get("macro_sp500", TTL_MACRO)
        if cached is not None: return cached
        d = self._yahoo_chart("^GSPC")
        if d: cache_set("macro_sp500", d)
        return d

    def nasdaq(self) -> Optional[Dict]:
        cached = cache_get("macro_nasdaq", TTL_MACRO)
        if cached is not None: return cached
        d = self._yahoo_chart("^IXIC")
        if d: cache_set("macro_nasdaq", d)
        return d

    def vix(self) -> Optional[float]:
        cached = cache_get("macro_vix", TTL_MACRO)
        if cached is not None: return cached
        d = self._yahoo_chart("^VIX", "5d")
        if d:
            cache_set("macro_vix", d["price"])
            return d["price"]
        return None

    def wti(self) -> Optional[float]:
        cached = cache_get("macro_wti", TTL_MACRO)
        if cached is not None: return cached
        d = self._yahoo_chart("CL=F", "5d")
        if d:
            cache_set("macro_wti", d["price"])
            return d["price"]
        return None

    def dxy(self) -> Optional[float]:
        cached = cache_get("macro_dxy", TTL_MACRO)
        if cached is not None: return cached
        d = self._yahoo_chart("DX-Y.NYB", "5d")
        if d:
            cache_set("macro_dxy", d["price"])
            return d["price"]
        return None

    def _fred_latest(self, series_id: str) -> Optional[float]:
        if not FRED_API_KEY:
            return None
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None
            obs = r.json().get("observations", [])
            for o in obs:
                v = o.get("value", ".")
                if v not in (".", "", None):
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            log.warning(f"FRED {series_id}: {e}")
        return None

    def us_10y(self) -> Optional[float]:
        cached = cache_get("macro_us10y", TTL_MACRO)
        if cached is not None: return cached
        v = self._fred_latest("DGS10")
        if v is not None:
            cache_set("macro_us10y", v)
        return v

    def us_2y(self) -> Optional[float]:
        cached = cache_get("macro_us2y", TTL_MACRO)
        if cached is not None: return cached
        v = self._fred_latest("DGS2")
        if v is not None:
            cache_set("macro_us2y", v)
        return v

    def yield_curve(self) -> Optional[float]:
        t10 = self.us_10y()
        t2 = self.us_2y()
        if t10 is None or t2 is None:
            return None
        return round(t10 - t2, 3)

    def usd_krw(self) -> Optional[float]:
        cached = cache_get("macro_usdkrw", TTL_MACRO)
        if cached is not None: return cached

        if ALPHA_VANTAGE_API_KEY:
            try:
                r = requests.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "CURRENCY_EXCHANGE_RATE",
                        "from_currency": "USD",
                        "to_currency": "KRW",
                        "apikey": ALPHA_VANTAGE_API_KEY,
                    },
                    timeout=10,
                )
                data = r.json()
                v = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
                cache_set("macro_usdkrw", v)
                return v
            except Exception as e:
                log.warning(f"환율 AV 실패: {e}")

        d = self._yahoo_chart("KRW=X", "5d")
        if d:
            cache_set("macro_usdkrw", d["price"])
            return d["price"]
        return None

    def fear_greed(self) -> Optional[int]:
        cached = cache_get("macro_fng", TTL_MACRO)
        if cached is not None: return cached

        try:
            r = requests.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                v = int(data["data"][0]["value"])
                cache_set("macro_fng", v)
                return v
        except Exception as e:
            log.warning(f"F&G alternative.me 실패: {e}")

        try:
            r = requests.get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code == 200:
                v = int(r.json()["fear_and_greed"]["score"])
                cache_set("macro_fng", v)
                return v
        except Exception as e:
            log.warning(f"F&G CNN 실패: {e}")

        return None


_macro: Optional[MacroData] = None


def get_macro() -> MacroData:
    global _macro
    if _macro is None:
        _macro = MacroData()
    return _macro
