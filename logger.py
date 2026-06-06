"""
logger.py - 공통 로깅 + 캐시 헬퍼
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
CACHE_DIR = LOG_DIR / "cache"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    fh = logging.FileHandler(
        LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log",
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(ch)
    return log


# ===== 캐시 헬퍼 =====
def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_").replace(" ", "_")
    return CACHE_DIR / f"{safe}.json"


def cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    """캐시 조회. 만료되면 None."""
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            entry = json.load(f)
        saved_at = entry.get("_saved_at", 0)
        if time.time() - saved_at > ttl_seconds:
            return None
        return entry.get("value")
    except Exception:
        return None


def cache_set(key: str, value: Any) -> None:
    p = _cache_path(key)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"_saved_at": time.time(), "value": value}, f, ensure_ascii=False)
    except Exception as e:
        get_logger("cache").warning(f"캐시 저장 실패 {key}: {e}")


def cache_delete(key: str) -> None:
    p = _cache_path(key)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
