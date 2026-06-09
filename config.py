"""
config.py — v3 (옵션 B: event/pattern 가중치 통합)

가중치 변경 (이전 v2 대비):
- chart 30 → 28 (-2)
- supply 22 → 20 (-2)
- fundamental 10 → 8 (-2)
- macro 12 → 11 (-1)
- news 13 → 12 (-1)
- risk 13 → 11 (-2)
- event 0 → 5 (NEW)
- pattern 0 → 5 (NEW)
합계 = 100
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default: str = "") -> str:
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        import streamlit as st
        return str(st.secrets.get(key, default)).strip()
    except Exception:
        return default


# ===== API 키 =====
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
KIS_APP_KEY = _get("KIS_APP_KEY")
KIS_APP_SECRET = _get("KIS_APP_SECRET")
KIS_ACCOUNT_NO = _get("KIS_ACCOUNT_NO")
FINNHUB_API_KEY = _get("FINNHUB_API_KEY")
ALPHA_VANTAGE_API_KEY = _get("ALPHA_VANTAGE_API_KEY")
NEWS_API_KEY = _get("NEWS_API_KEY")
FRED_API_KEY = _get("FRED_API_KEY")
DART_API_KEY = _get("DART_API_KEY")
POLYGON_API_KEY = _get("POLYGON_API_KEY")


# ===== 한투 =====
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"


# ===== 경로 =====
LOG_DIR = BASE_DIR / "logs"
CACHE_DIR = LOG_DIR / "cache"
TOKEN_CACHE = LOG_DIR / "kis_token.json"
DB_PATH = LOG_DIR / "history.db"

LOG_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ===== 캐싱 TTL =====
TTL_QUOTE = 60
TTL_DAILY = 1800
TTL_INDICATORS = 1800
TTL_POOL = 3600
TTL_NEWS = 1800
TTL_MACRO = 86400
TTL_AGENT_RESULT = 1800


# ===== 자동 풀 =====
POOL_TOP_N_KRX = 30
POOL_TOP_N_US = 30
POOL_SELECT_TOP = 5


# ===== 풀 필터링 =====
KRX_MIN_MARKET_CAP = 300_000_000_000
KRX_MIN_VOLUME_VALUE = 10_000_000_000
US_MIN_MARKET_CAP_USD = 2_000_000_000
US_MIN_VOLUME_USD = 50_000_000
EXCLUDE_SURGE_5D_PCT = 40
EXCLUDE_VOLUME_SPIKE = 8
EXCLUDE_RSI_ABOVE = 85


# ════════════════════════════════════════════════════════════
# 에이전트 가중치 v3 — event + pattern 통합
# ════════════════════════════════════════════════════════════
AGENT_WEIGHTS = {
    "chart": 0.28,
    "supply": 0.20,
    "fundamental": 0.08,
    "macro": 0.11,
    "news": 0.12,
    "risk": 0.11,
    "event": 0.05,    # NEW
    "pattern": 0.05,  # NEW
}
# 합계 = 1.00


# ===== 등급 임계점 =====
GRADE_THRESHOLDS = {
    "strong_buy": 78,
    "buy": 62,
    "hold": 48,
    "reduce": 32,
}


# ===== 스윙 매매 =====
HOLD_DAYS_MIN = 3
HOLD_DAYS_MAX = 7
DEFAULT_STOP_PCT = 7
DEFAULT_PROFIT_PCT = 10


# ===== Claude =====
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_MAX_TOKENS = 1500


# ===== 시장 신호등 =====
VIX_FEAR = 25
VIX_GREED = 12
FNG_FEAR = 25
FNG_GREED = 75


def validate_config():
    required = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "KIS_APP_KEY": KIS_APP_KEY,
        "KIS_APP_SECRET": KIS_APP_SECRET,
        "KIS_ACCOUNT_NO": KIS_ACCOUNT_NO,
        "FINNHUB_API_KEY": FINNHUB_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(
            f"❌ .env에 필수 키 누락: {', '.join(missing)}\n"
            f"📁 .env 위치: {BASE_DIR / '.env'}"
        )

    optional = {
        "NEWS_API_KEY": NEWS_API_KEY,
        "FRED_API_KEY": FRED_API_KEY,
        "DART_API_KEY": DART_API_KEY,
        "ALPHA_VANTAGE_API_KEY": ALPHA_VANTAGE_API_KEY,
    }
    missing_opt = [k for k, v in optional.items() if not v]
    if missing_opt:
        print(f"⚠️ 선택 키 누락 (기능 일부 제한): {', '.join(missing_opt)}")

    return True


if __name__ == "__main__":
    try:
        validate_config()
        print("✅ 설정 OK")
        print(f"가중치 합계: {sum(AGENT_WEIGHTS.values()):.2f}")
    except Exception as e:
        print(f"❌ {e}")
