"""
data/macro_api.py
매크로 통합:
- FRED: 미국 10년물, 장단기 금리차, DXY
- Yahoo: VIX, 코스피, S&P500, 나스닥, WTI
- Alpha Vantage: 원/달러
- alternative.me: Fear & Greed (CNN 대신)
"""
import requests
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FRED_API_KEY, ALPHA_VANTAGE_API_KEY, TTL_MACRO
from logger import get_logger, cache_get, cache_set

log = get_logger("macro")


class MacroData:
    def get_all(self) -> Dict[str, Any]:
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
    
    # ===== FRED =====
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
        """장단기 금리차 (10년 - 2년). 음수면 역전."""
        t10 = self.us_10y()
        t2 = self.us_2y()
        if t10 is None or t2 is None:
            return None
        return round(t10 - t2, 3)
    
    # ===== 환율 =====
    def usd_krw(self) -> Optional[float]:
        cached = cache_get("macro_usdkrw", TTL_MACRO)
        if cached is not None: return cached
        
        # 1. Alpha Vantage
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
        
        # 2. Yahoo fallback
        d = self._yahoo_chart("KRW=X", "5d")
        if d:
            cache_set("macro_usdkrw", d["price"])
            return d["price"]
        return None
    
    # ===== Fear & Greed (alternative.me) =====
    def fear_greed(self) -> Optional[int]:
        cached = cache_get("macro_fng", TTL_MACRO)
        if cached is not None: return cached
        
        # 1. alternative.me (크립토 F&G - 대체용)
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
        
        # 2. CNN 공식 시도
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
