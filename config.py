"""
config.py
모든 설정 중앙 관리. 다른 모듈은 여기서 가져옴.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default: str = "") -> str:
    """환경변수 우선, 없으면 Streamlit secrets fallback"""
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


# ===== 캐싱 TTL (초) =====
TTL_QUOTE = 60                    # 시세 1분
TTL_DAILY = 1800                  # 일봉 30분
TTL_INDICATORS = 1800             # 지표 30분
TTL_POOL = 3600                   # 자동 풀 1시간
TTL_NEWS = 1800                   # 뉴스 30분
TTL_MACRO = 86400                 # 매크로 1일
TTL_AGENT_RESULT = 1800           # AI 분석 30분


# ===== 자동 풀 추출 =====
POOL_TOP_N_KRX = 30              # 한투 거래대금 상위에서 30개
POOL_TOP_N_US = 30               # Finnhub 활성 종목 상위 30개
POOL_SELECT_TOP = 5              # 점수 상위 5개에서 1개 선정


# ===== 풀 필터링 =====
KRX_MIN_MARKET_CAP = 300_000_000_000       # 시총 3000억
KRX_MIN_VOLUME_VALUE = 10_000_000_000      # 거래대금 100억
US_MIN_MARKET_CAP_USD = 2_000_000_000      # 시총 20억$
US_MIN_VOLUME_USD = 50_000_000             # 거래대금 5천만$
EXCLUDE_SURGE_5D_PCT = 40                  # 5일 +40% 폭등 제외
EXCLUDE_VOLUME_SPIKE = 8                   # 평소 8배 폭증 제외
EXCLUDE_RSI_ABOVE = 85                     # 극과매수만


# ===== 에이전트 점수 가중치 (합 1.0) =====
AGENT_WEIGHTS = {
    "chart": 0.30,
    "fundamental": 0.15,
    "macro": 0.15,
    "news": 0.10,
    "supply": 0.20,
    "risk": 0.10,
}


# ===== 등급 임계점 =====
GRADE_THRESHOLDS = {
    "strong_buy": 78,
    "buy": 62,
    "hold": 48,
    "reduce": 32,
    # 그 아래는 avoid
}


# ===== 스윙 매매 =====
HOLD_DAYS_MIN = 3
HOLD_DAYS_MAX = 7
DEFAULT_STOP_PCT = 7
DEFAULT_PROFIT_PCT = 10


# ===== Claude =====
CLAUDE_MODEL = "claude-sonnet-4-5"   # 또는 claude-haiku-4-5
CLAUDE_MAX_TOKENS = 1500


# ===== 시장 신호등 =====
VIX_FEAR = 25
VIX_GREED = 12
FNG_FEAR = 25
FNG_GREED = 75


def validate_config():
    """필수 키 검증. 누락 시 RuntimeError."""
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
    
    # 선택 키 경고만
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
    except Exception as e:
        print(f"❌ {e}")
