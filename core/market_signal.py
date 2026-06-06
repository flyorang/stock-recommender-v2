"""
core/market_signal.py
시장 환경 신호등.
"""
from typing import Dict, Any
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import VIX_FEAR, VIX_GREED, FNG_FEAR, FNG_GREED
from data.macro_api import get_macro


def get_signal() -> Dict[str, Any]:
    """현재 시장 신호 종합"""
    macro = get_macro().get_all()
    
    vix = macro.get("vix")
    fng = macro.get("fear_greed")
    
    # 심리 판정
    psy = "neutral"
    if vix is not None:
        if vix >= VIX_FEAR:
            psy = "fear"
        elif vix <= VIX_GREED:
            psy = "greed"
    
    if fng is not None:
        if fng <= FNG_FEAR:
            psy = "fear"
        elif fng >= FNG_GREED:
            psy = "greed"
    
    # 메시지
    parts = []
    if vix is not None: parts.append(f"VIX {vix:.1f}")
    if fng is not None: parts.append(f"F&G {fng}")
    msg = " · ".join(parts) if parts else "—"
    
    label = {
        "fear": "공포 — 저점 매수 기회",
        "neutral": "중립",
        "greed": "과열 — 조정 임박 주의",
    }[psy]
    
    return {
        "psychology": psy,
        "label": label,
        "detail": msg,
        "macro": macro,
    }
