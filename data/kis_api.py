"""
data/kis_api.py
한국투자증권 OpenAPI 클라이언트.

주요 기능:
- 토큰 자동 발급/캐싱
- 국내/해외 주식 시세, 일봉, 주봉
- 거래대금 상위 종목 (자동 풀)
- 외국인/기관 순매수 (수급 분석용)
- Throttling (초당 10회 안전 마진)
"""
import json
import time
import requests
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Dict, Any, List
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL, TOKEN_CACHE,
)
from logger import get_logger

log = get_logger("kis")


class KISError(Exception):
    pass


class KISClient:
    def __init__(self):
        self.app_key = KIS_APP_KEY
        self.app_secret = KIS_APP_SECRET
        self.base_url = KIS_BASE_URL
        self.token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self._last_call = 0.0
        self._min_interval = 0.1  # 초당 10회
        self._load_token()
    
    # ===== 토큰 =====
    def _load_token(self):
        if not TOKEN_CACHE.exists():
            return
        try:
            with open(TOKEN_CACHE, "r", encoding="utf-8") as f:
                d = json.load(f)
            exp = datetime.fromisoformat(d["expires_at"])
            if exp > datetime.now() + timedelta(minutes=30):
                self.token = d["token"]
                self.token_expires_at = exp
        except Exception:
            pass
    
    def _save_token(self):
        try:
            TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
                json.dump({
                    "token": self.token,
                    "expires_at": self.token_expires_at.isoformat(),
                }, f)
        except Exception as e:
            log.warning(f"토큰 캐시 저장 실패: {e}")
    
    def _issue_token(self) -> str:
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        r = requests.post(url, json=body, timeout=10)
        if r.status_code != 200:
            raise KISError(f"토큰 발급 실패 ({r.status_code}): {r.text}")
        d = r.json()
        if "access_token" not in d:
            raise KISError(f"응답 이상: {d}")
        self.token = d["access_token"]
        self.token_expires_at = datetime.now() + timedelta(hours=23)
        self._save_token()
        log.info("✅ 토큰 발급 성공")
        return self.token
    
    def get_token(self) -> str:
        if self.token and self.token_expires_at and \
           self.token_expires_at > datetime.now() + timedelta(minutes=30):
            return self.token
        return self._issue_token()
    
    # ===== 호출 =====
    def _throttle(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()
    
    def _request(
        self,
        method: str,
        endpoint: str,
        tr_id: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
        retries: int = 2,
    ) -> Dict:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        last_err = None
        for attempt in range(retries + 1):
            self._throttle()
            try:
                if method == "GET":
                    r = requests.get(url, headers=headers, params=params, timeout=15)
                else:
                    r = requests.post(url, headers=headers, json=body, timeout=15)
                
                if r.status_code == 200:
                    d = r.json()
                    rt = d.get("rt_cd", "")
                    if rt == "0":
                        return d
                    msg = d.get("msg1", "")
                    last_err = f"rt_cd={rt} msg={msg}"
                    if "EGW00201" in str(d) or "초당" in msg:
                        time.sleep(1.0)
                        continue
                    raise KISError(last_err)
                else:
                    last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            except requests.RequestException as e:
                last_err = f"네트워크: {e}"
            
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
        
        raise KISError(f"요청 실패: {last_err}")
    
    # ===== 국내 시세 =====
    def domestic_price(self, ticker: str) -> Dict[str, Any]:
        d = self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
            },
        )
        out = d.get("output", {})
        if not out:
            raise KISError(f"시세 없음: {ticker}")
        return {
            "ticker": ticker,
            "name": out.get("hts_kor_isnm", ""),
            "price": int(out.get("stck_prpr", 0) or 0),
            "change": int(out.get("prdy_vrss", 0) or 0),
            "change_pct": float(out.get("prdy_ctrt", 0) or 0),
            "volume": int(out.get("acml_vol", 0) or 0),
            "volume_value": int(out.get("acml_tr_pbmn", 0) or 0),
            "high": int(out.get("stck_hgpr", 0) or 0),
            "low": int(out.get("stck_lwpr", 0) or 0),
            "open": int(out.get("stck_oprc", 0) or 0),
            "prev_close": int(out.get("stck_sdpr", 0) or 0),
            "market_cap": int(out.get("hts_avls", 0) or 0) * 100_000_000,
            "per": float(out.get("per", 0) or 0),
            "pbr": float(out.get("pbr", 0) or 0),
            "eps": float(out.get("eps", 0) or 0),
            "high_52w": int(out.get("w52_hgpr", 0) or 0),
            "low_52w": int(out.get("w52_lwpr", 0) or 0),
        }
    
    def domestic_daily(self, ticker: str, days: int = 130) -> List[Dict]:
        """일봉. 최근 → 과거 순."""
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=days * 2)).strftime("%Y%m%d")
        d = self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        bars = d.get("output2", []) or []
        result = []
        for b in bars[:days]:
            try:
                result.append({
                    "date": b.get("stck_bsop_date", ""),
                    "open": int(b.get("stck_oprc", 0) or 0),
                    "high": int(b.get("stck_hgpr", 0) or 0),
                    "low": int(b.get("stck_lwpr", 0) or 0),
                    "close": int(b.get("stck_clpr", 0) or 0),
                    "volume": int(b.get("acml_vol", 0) or 0),
                })
            except (ValueError, TypeError):
                continue
        return result
    
    def domestic_weekly(self, ticker: str, weeks: int = 52) -> List[Dict]:
        """주봉"""
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(weeks=weeks * 2)).strftime("%Y%m%d")
        d = self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": "W",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        bars = d.get("output2", []) or []
        result = []
        for b in bars[:weeks]:
            try:
                result.append({
                    "date": b.get("stck_bsop_date", ""),
                    "open": int(b.get("stck_oprc", 0) or 0),
                    "high": int(b.get("stck_hgpr", 0) or 0),
                    "low": int(b.get("stck_lwpr", 0) or 0),
                    "close": int(b.get("stck_clpr", 0) or 0),
                    "volume": int(b.get("acml_vol", 0) or 0),
                })
            except (ValueError, TypeError):
                continue
        return result
    
    # ===== 국내 거래대금 상위 =====
    def domestic_top_value(self, top_n: int = 30) -> List[Dict]:
        """거래대금 상위 종목."""
        d = self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            tr_id="FHPST01710000",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "3",  # 거래대금 순위
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        return self._parse_rank_response(d, top_n)
    
    def domestic_top_volume(self, top_n: int = 30) -> List[Dict]:
        """거래량 급증 상위 (평소 대비 폭증)"""
        d = self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            tr_id="FHPST01710000",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "1",  # 거래량 증가율
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        return self._parse_rank_response(d, top_n)
    
    def domestic_top_gainers(self, top_n: int = 30) -> List[Dict]:
        """상승률 상위"""
        try:
            d = self._request(
                "GET",
                "/uapi/domestic-stock/v1/ranking/fluctuation",
                tr_id="FHPST01700000",
                params={
                    "fid_cond_mrkt_div_code": "J",
                    "fid_cond_scr_div_code": "20170",
                    "fid_input_iscd": "0000",
                    "fid_rank_sort_cls_code": "0",  # 상승률 순
                    "fid_input_cnt_1": "0",
                    "fid_prc_cls_code": "0",
                    "fid_input_price_1": "",
                    "fid_input_price_2": "",
                    "fid_vol_cnt": "",
                    "fid_trgt_cls_code": "0",
                    "fid_trgt_exls_cls_code": "0",
                    "fid_div_cls_code": "0",
                    "fid_rsfl_rate1": "",
                    "fid_rsfl_rate2": "",
                },
            )
            rows = d.get("output", []) or []
            result = []
            for r in rows[:top_n]:
                try:
                    result.append({
                        "ticker": r.get("stck_shrn_iscd", ""),
                        "name": r.get("hts_kor_isnm", ""),
                        "price": int(r.get("stck_prpr", 0) or 0),
                        "change": int(r.get("prdy_vrss", 0) or 0),
                        "change_pct": float(r.get("prdy_ctrt", 0) or 0),
                        "volume": int(r.get("acml_vol", 0) or 0),
                        "volume_value": int(r.get("acml_tr_pbmn", 0) or 0),
                    })
                except (ValueError, TypeError):
                    continue
            return result
        except Exception as e:
            log.warning(f"상승률 상위 실패: {e}")
            return []
    
    def _parse_rank_response(self, d: Dict, top_n: int) -> List[Dict]:
        rows = d.get("output", []) or []
        result = []
        for r in rows[:top_n]:
            try:
                result.append({
                    "ticker": r.get("mksc_shrn_iscd", ""),
                    "name": r.get("hts_kor_isnm", ""),
                    "price": int(r.get("stck_prpr", 0) or 0),
                    "change": int(r.get("prdy_vrss", 0) or 0),
                    "change_pct": float(r.get("prdy_ctrt", 0) or 0),
                    "volume": int(r.get("acml_vol", 0) or 0),
                    "volume_value": int(r.get("acml_tr_pbmn", 0) or 0),
                })
            except (ValueError, TypeError):
                continue
        return result
    
    # ===== 국내 수급 (외국인/기관) =====
    def domestic_investor_flow(self, ticker: str) -> Dict[str, Any]:
        """외국인/기관 일별 순매수 (최근 거래일).
        
        Returns:
            {
                foreign_net_today: int,
                foreign_net_5d: int,
                foreign_net_20d: int,
                institution_net_today, institution_net_5d, institution_net_20d
            }
        """
        try:
            d = self._request(
                "GET",
                "/uapi/domestic-stock/v1/quotations/inquire-investor",
                tr_id="FHKST01010900",
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": ticker,
                },
            )
            rows = d.get("output", []) or []
            
            def safe_int(v):
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return 0
            
            # 최근 N일 합산
            foreign = [safe_int(r.get("frgn_ntby_qty", 0)) for r in rows]
            inst = [safe_int(r.get("orgn_ntby_qty", 0)) for r in rows]
            
            return {
                "foreign_net_today": foreign[0] if foreign else 0,
                "foreign_net_5d": sum(foreign[:5]) if foreign else 0,
                "foreign_net_20d": sum(foreign[:20]) if foreign else 0,
                "institution_net_today": inst[0] if inst else 0,
                "institution_net_5d": sum(inst[:5]) if inst else 0,
                "institution_net_20d": sum(inst[:20]) if inst else 0,
                "days_available": len(foreign),
            }
        except Exception as e:
            log.warning(f"수급 조회 실패 {ticker}: {e}")
            return {
                "foreign_net_today": 0, "foreign_net_5d": 0, "foreign_net_20d": 0,
                "institution_net_today": 0, "institution_net_5d": 0, "institution_net_20d": 0,
                "days_available": 0,
            }
    
    # ===== 해외 시세 =====
    def overseas_price(self, ticker: str, exchange: str = "NAS") -> Dict[str, Any]:
        d = self._request(
            "GET",
            "/uapi/overseas-price/v1/quotations/price",
            tr_id="HHDFS00000300",
            params={
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": ticker,
            },
        )
        out = d.get("output", {})
        if not out:
            raise KISError(f"해외 시세 없음: {ticker}")
        return {
            "ticker": ticker,
            "exchange": exchange,
            "price": float(out.get("last", 0) or 0),
            "change": float(out.get("diff", 0) or 0),
            "change_pct": float(out.get("rate", 0) or 0),
            "volume": int(out.get("tvol", 0) or 0),
            "volume_value": float(out.get("tamt", 0) or 0),
            "high": float(out.get("high", 0) or 0),
            "low": float(out.get("low", 0) or 0),
            "open": float(out.get("open", 0) or 0),
            "prev_close": float(out.get("base", 0) or 0),
        }
    
    def overseas_daily(self, ticker: str, exchange: str = "NAS", days: int = 130) -> List[Dict]:
        d = self._request(
            "GET",
            "/uapi/overseas-price/v1/quotations/dailyprice",
            tr_id="HHDFS76240000",
            params={
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": ticker,
                "GUBN": "0",
                "BYMD": "",
                "MODP": "1",
            },
        )
        bars = d.get("output2", []) or []
        result = []
        for b in bars[:days]:
            try:
                result.append({
                    "date": b.get("xymd", ""),
                    "open": float(b.get("open", 0) or 0),
                    "high": float(b.get("high", 0) or 0),
                    "low": float(b.get("low", 0) or 0),
                    "close": float(b.get("clos", 0) or 0),
                    "volume": int(b.get("tvol", 0) or 0),
                })
            except (ValueError, TypeError):
                continue
        return result
    
    def overseas_weekly(self, ticker: str, exchange: str = "NAS", weeks: int = 52) -> List[Dict]:
        d = self._request(
            "GET",
            "/uapi/overseas-price/v1/quotations/dailyprice",
            tr_id="HHDFS76240000",
            params={
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": ticker,
                "GUBN": "1",  # 주봉
                "BYMD": "",
                "MODP": "1",
            },
        )
        bars = d.get("output2", []) or []
        result = []
        for b in bars[:weeks]:
            try:
                result.append({
                    "date": b.get("xymd", ""),
                    "open": float(b.get("open", 0) or 0),
                    "high": float(b.get("high", 0) or 0),
                    "low": float(b.get("low", 0) or 0),
                    "close": float(b.get("clos", 0) or 0),
                    "volume": int(b.get("tvol", 0) or 0),
                })
            except (ValueError, TypeError):
                continue
        return result


# ===== 싱글톤 =====
_client: Optional[KISClient] = None


def get_kis() -> KISClient:
    global _client
    if _client is None:
        _client = KISClient()
    return _client
