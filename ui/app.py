"""
ui/app.py — v3.1 (라디오 → 버튼 4개로 변경)

수정: 라디오 버튼 클릭 안 되던 문제 해결.
버튼 4개로 변경하고 선택된 거는 ✓ 표시.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from config import validate_config
from core.recommender import recommend_one
from core.market_signal import get_signal
from data.pool_builder import Market
from storage import history as hist


st.set_page_config(
    page_title="스윙 추천",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden;}
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
[data-testid="manage-app-button"],
.stDeployButton, [data-testid="stAppDeployButton"],
button[title="View fullscreen"] {display: none !important;}

/* 사이드바 강제 표시 - PC, 폰 모두 */
[data-testid="stSidebar"] {
  display: block !important;
  visibility: visible !important;
  transform: translateX(0px) !important;
  margin-left: 0 !important;
  min-width: 280px !important;
  width: 280px !important;
}
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {
  display: block !important;
  visibility: visible !important;
  color: white !important;
  background: #4dabf7 !important;
  padding: 8px !important;
  border-radius: 4px !important;
  position: fixed !important;
  top: 10px !important;
  left: 10px !important;
  z-index: 99999 !important;
}

:root {
  --bg: #0f1115; --card: #1a1d24; --text: #f4f5f7; --text-sub: #adb5bd;
  --text-light: #6c757d; --border: #2c2f36; --primary: #4dabf7;
  --success: #51cf66; --warning: #ffd43b; --danger: #ff6b6b;
}

html, body, [class*="st-"], .stApp {
  background-color: var(--bg) !important; color: var(--text) !important;
}
.stApp { background: var(--bg) !important; }
.block-container { padding-top: 1rem !important; padding-bottom: 5rem; max-width: 720px; }

.market-signal { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 12px; }
.signal-emoji { font-size: 40px; }
.signal-title { font-size: 16px; font-weight: 700; color: var(--text); }
.signal-detail { font-size: 12px; color: var(--text-sub); margin-top: 2px; }

.indices { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 16px; }
.idx-item { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 4px; text-align: center; }
.idx-name { font-size: 10px; color: var(--text-sub); letter-spacing: 0.5px; font-weight: 600; }
.idx-value { font-size: 14px; font-weight: 800; color: var(--text); margin-top: 2px; }
.idx-change { font-size: 11px; margin-top: 1px; font-weight: 600; }
.up { color: var(--danger); }
.down { color: var(--primary); }

.stock-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 0; margin-bottom: 14px; overflow: hidden; }
.stock-head { padding: 16px 18px 12px; border-bottom: 1px solid var(--border); }
.stock-name { font-size: 19px; font-weight: 800; color: var(--text); letter-spacing: -0.5px; }
.stock-meta { font-size: 12px; color: var(--text-sub); margin-top: 3px; }

.grade-box { padding: 22px 16px; text-align: center; color: white; }
.grade-buy { background: linear-gradient(135deg, #339af0, #1971c2); }
.grade-strong-buy { background: linear-gradient(135deg, #51cf66, #2f9e44); }
.grade-hold { background: linear-gradient(135deg, #fab005, #f08c00); color: #fff; }
.grade-reduce { background: linear-gradient(135deg, #fd7e14, #d9480f); }
.grade-avoid { background: linear-gradient(135deg, #e03131, #c92a2a); }
.grade-label { font-size: 32px; font-weight: 900; letter-spacing: -1px; }
.grade-sub { font-size: 13px; opacity: 0.9; margin-top: 4px; }
.grade-summary { font-size: 14px; font-weight: 600; margin-top: 12px; line-height: 1.4; }
.grade-downgrade { font-size: 11px; background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 6px; margin-top: 8px; display: inline-block; }

.veto-box { background: linear-gradient(135deg, #e03131, #962525); color: white; padding: 16px; border-radius: 12px; margin: 8px 0; border: 2px solid #ff6b6b; }
.veto-title { font-size: 16px; font-weight: 900; margin-bottom: 6px; }
.veto-reason { font-size: 13px; opacity: 0.95; }

.price-box { padding: 14px 18px; border-bottom: 1px solid var(--border); }
.price-now { font-size: 28px; font-weight: 800; color: var(--text); letter-spacing: -1px; }
.price-chg { font-size: 13px; font-weight: 700; margin-left: 6px; }

.guide-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 12px; }
.guide-item { padding: 10px; border-radius: 10px; background: var(--bg); text-align: center; }
.guide-item.entry { border: 1px solid var(--primary); }
.guide-item.stop { border: 1px solid var(--danger); }
.guide-item.profit { border: 1px solid var(--success); }
.g-label { font-size: 10px; color: var(--text-sub); font-weight: 700; letter-spacing: 0.5px; }
.g-value { font-size: 14px; font-weight: 800; margin-top: 4px; color: var(--text); }
.g-source { font-size: 9px; color: var(--text-light); margin-top: 2px; }
.g-pct { font-size: 11px; margin-top: 2px; font-weight: 600; }
.pl-ratio { text-align: center; font-size: 12px; color: var(--text-sub); margin-top: 8px; }
.pl-ratio strong { color: var(--success); font-weight: 700; }

.agents-box { padding: 14px 18px; border-bottom: 1px solid var(--border); }
.section-title { font-size: 11px; font-weight: 700; letter-spacing: 1px; color: var(--text-sub); margin-bottom: 10px; text-transform: uppercase; }
.agent-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.agent-row:last-child { margin-bottom: 0; }
.agent-icon { width: 16px; font-size: 13px; }
.agent-name { width: 56px; font-size: 12px; font-weight: 600; color: var(--text); }
.agent-bar { flex: 1; height: 6px; background: var(--bg); border-radius: 3px; overflow: hidden; }
.agent-fill { height: 100%; border-radius: 3px; transition: width .5s; }
.fill-high { background: linear-gradient(90deg, #51cf66, #2f9e44); }
.fill-mid { background: linear-gradient(90deg, #ffd43b, #fab005); }
.fill-low { background: linear-gradient(90deg, #ff6b6b, #e03131); }
.agent-score { width: 28px; text-align: right; font-size: 12px; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--text); }

.contradiction { background: rgba(255, 212, 59, 0.1); border: 1px solid rgba(255, 212, 59, 0.3); color: var(--warning); padding: 8px 12px; border-radius: 8px; margin: 8px 0; font-size: 12px; }
.calibration-card { background: var(--card); border: 1px solid var(--border); padding: 12px; border-radius: 10px; margin-bottom: 10px; }

/* === 버튼 === */
.stButton, .stButton * { outline: 0 !important; box-shadow: none !important; }
.stButton { background: transparent !important; }
.stButton > button {
  background: #1a1d24 !important;
  color: var(--text) !important;
  border: 1px solid #2c2f36 !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  padding: 12px !important;
  width: 100% !important;
  transition: all 0.15s;
  cursor: pointer !important;
}
.stButton > button:hover {
  background: #2c2f36 !important;
  color: white !important;
  border-color: var(--primary) !important;
}
.stButton > button:active {
  background: var(--primary) !important;
}

[data-testid="stExpander"] { background: var(--card) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; }
[data-testid="stExpander"] summary { color: var(--text) !important; }
[data-testid="stMetric"] { background: var(--card); padding: 10px; border-radius: 8px; border: 1px solid var(--border); }

@media (max-width: 400px) {
  .grade-label { font-size: 26px; }
  .price-now { font-size: 24px; }
  .g-value { font-size: 12px; }
}
</style>
""", unsafe_allow_html=True)


# ===== 설정 검증 =====
try:
    validate_config()
except Exception as e:
    st.error(f"❌ {e}")
    st.stop()


# ===== 세션 =====
if "krx_result" not in st.session_state:
    st.session_state.krx_result = None
if "us_result" not in st.session_state:
    st.session_state.us_result = None


# ===== 헤더 =====
st.markdown("# 📈 스윙 추천")
st.caption("국장 + 미장 · 3~7일 보유 · 8 에이전트 분석")


# ===== 시장 신호 =====
with st.spinner("시장 분석..."):
    signal = get_signal()

psy = signal["psychology"]
psy_emoji = {"fear": "🟢", "neutral": "🟡", "greed": "🔴"}[psy]
macro = signal.get("macro", {})

st.markdown(
    f"<div class='market-signal'><div class='signal-emoji'>{psy_emoji}</div>"
    f"<div><div class='signal-title'>{signal['label']}</div>"
    f"<div class='signal-detail'>{signal['detail']}</div></div></div>",
    unsafe_allow_html=True
)

kospi = macro.get("kospi") or {}
sp500 = macro.get("sp500") or {}
k_chg_class = "up" if kospi.get("change_pct", 0) >= 0 else "down"
s_chg_class = "up" if sp500.get("change_pct", 0) >= 0 else "down"

st.markdown(
    f"<div class='indices'>"
    f"<div class='idx-item'><div class='idx-name'>KOSPI</div><div class='idx-value'>{kospi.get('price', 0):.0f}</div><div class='idx-change {k_chg_class}'>{kospi.get('change_pct', 0):+.2f}%</div></div>"
    f"<div class='idx-item'><div class='idx-name'>S&P</div><div class='idx-value'>{sp500.get('price', 0):.0f}</div><div class='idx-change {s_chg_class}'>{sp500.get('change_pct', 0):+.2f}%</div></div>"
    f"<div class='idx-item'><div class='idx-name'>VIX</div><div class='idx-value'>{(macro.get('vix') or 0):.1f}</div><div class='idx-change'>—</div></div>"
    f"<div class='idx-item'><div class='idx-name'>USD</div><div class='idx-value'>{(macro.get('usd_krw') or 0):.0f}</div><div class='idx-change'>—</div></div>"
    f"</div>",
    unsafe_allow_html=True
)


# ════════════════════════════════════════════════════════════
# 시장 국면 토글 → 폐기. 항상 기본 가중치로 공정하게.
# ════════════════════════════════════════════════════════════
# (이전: 사용자가 강세/약세/박스권/모름 선택. 이제 항상 'unknown' = 기본 가중치)


# ===== 보유 종목 (메인 화면에 표시) =====
ops_main = hist.get_open_positions()
if ops_main:
    st.markdown("### 💼 보유 종목")
    for p in ops_main:
        with st.expander(f"📌 {p['name']} ({p['ticker']})", expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.metric("진입가", f"{p['entry_price']:,.0f}")
            if p["stop_loss"]:
                c2.metric("손절", f"{p['stop_loss']:,.0f}")
            if p["take_profit"]:
                c3.metric("익절", f"{p['take_profit']:,.0f}")
            ep = st.number_input(
                "매도가 입력",
                value=float(p["entry_price"]),
                key=f"main_ep_{p['ticker']}",
            )
            if st.button("💰 매도 처리", key=f"main_cl_{p['ticker']}", use_container_width=True):
                hist.close_position(p["ticker"], ep)
                st.success(f"✅ {p['name']} 매도 완료")
                st.rerun()
    st.markdown("---")


# ===== 메인 버튼 =====
col1, col2 = st.columns([3, 1])
get_btn = col1.button("🎯 추천 받기", use_container_width=True, key="get_rec")
clear_btn = col2.button("🔄 초기화", use_container_width=True, key="clear_btn")

if clear_btn:
    st.session_state.krx_result = None
    st.session_state.us_result = None
    st.rerun()


# ═══════════════════════════════════════════════════════════
# 카드 렌더링
# ═══════════════════════════════════════════════════════════
def render_card(result: dict, flag: str, card_idx: str):
    if not result:
        return

    si = result["stock_info"]
    quote = result.get("quote", {})
    synth = result["synthesis"]
    agents = result["agents"]
    ind = result.get("indicators", {})
    is_krx = si.get("market") == "KRX"

    st.markdown(
        f"<div class='stock-head'><div class='stock-name'>{flag} {si.get('name', '')} "
        f"<span style='color:var(--text-sub);font-size:14px;font-weight:500'>({si.get('ticker', '')})</span></div>"
        f"<div class='stock-meta'>📁 {si.get('sector', '—')}</div></div>",
        unsafe_allow_html=True
    )

    # VETO 박스
    if synth.get("vetoed_reason"):
        vetos = synth.get("all_vetos") or []
        evidence = vetos[0].get("evidence", "") if vetos else ""
        st.markdown(
            f"<div class='veto-box'>"
            f"<div class='veto-title'>⛔ VETO 발동: {synth.get('vetoed_reason')}</div>"
            f"<div class='veto-reason'>{evidence}</div>"
            f"<div class='veto-reason' style='margin-top:6px'>→ 점수와 무관하게 매수 금지</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    # 등급
    grade_class = synth.get("grade_color_class", "hold")
    grade_class_map = {
        "strong-buy": "grade-strong-buy",
        "buy": "grade-buy",
        "hold": "grade-hold",
        "reduce": "grade-reduce",
        "avoid": "grade-avoid",
    }
    css_class = grade_class_map.get(grade_class, "grade-hold")
    consensus = synth.get("consensus", {})
    consensus_label = consensus.get("label", "—")

    downgrade_html = ""
    if synth.get("downgraded_reason"):
        downgrade_html = f"<div class='grade-downgrade'>↓ {synth['downgraded_reason']}</div>"

    st.markdown(
        f"<div class='grade-box {css_class}'>"
        f"<div class='grade-label'>{synth.get('grade_emoji', '')} {synth.get('grade', '')}</div>"
        f"<div class='grade-sub'>종합 {synth.get('total_score', 0):.0f}/100 · {consensus_label}</div>"
        f"<div class='grade-summary'>{synth.get('summary', '')}</div>"
        f"{downgrade_html}"
        f"</div>",
        unsafe_allow_html=True
    )

    for c in synth.get("contradictions", []):
        st.markdown(f"<div class='contradiction'>{c}</div>", unsafe_allow_html=True)

    # 가격
    cur = quote.get("price", 0)
    change_pct = quote.get("change_pct", 0)
    price_str = f"{int(cur):,}원" if is_krx else f"${cur:.2f}"
    chg_class = "up" if change_pct >= 0 else "down"
    chg_sign = "+" if change_pct >= 0 else ""
    prices = synth.get("prices", {})

    def fmt_p(v):
        if not v: return "—"
        return f"{int(v):,}원" if is_krx else f"${v:.2f}"

    stop_src = prices.get("stop_loss_source", "ATR")
    take_src = prices.get("take_profit_source", "기본")

    st.markdown(
        f"<div class='price-box'>"
        f"<div><span class='price-now'>{price_str}</span><span class='price-chg {chg_class}'>{chg_sign}{change_pct:.2f}%</span></div>"
        f"<div class='guide-grid'>"
        f"<div class='guide-item entry'><div class='g-label'>🎯 진입</div><div class='g-value'>{prices.get('entry_label', '—')}</div></div>"
        f"<div class='guide-item stop'><div class='g-label'>🛑 손절</div><div class='g-value'>{fmt_p(prices.get('stop_loss'))}</div><div class='g-source'>{stop_src} 기반</div><div class='g-pct down'>-{prices.get('expected_risk_pct', 0)}%</div></div>"
        f"<div class='guide-item profit'><div class='g-label'>💰 익절</div><div class='g-value'>{fmt_p(prices.get('take_profit'))}</div><div class='g-source'>{take_src}</div><div class='g-pct up'>+{prices.get('expected_return_pct', 0)}%</div></div>"
        f"</div>"
        f"<div class='pl-ratio'>손익비 <strong>1 : {prices.get('profit_loss_ratio', 0)}</strong> · 보유 {synth.get('hold_days', '')}</div>"
        f"</div>",
        unsafe_allow_html=True
    )

    # 에이전트 막대
    def fill_class(s):
        return "fill-high" if s >= 70 else "fill-mid" if s >= 45 else "fill-low"

    ag_rows = ""
    for key, icon, label in [
        ("chart", "📈", "차트"), ("supply", "💰", "수급"), ("pattern", "🔍", "패턴"),
        ("fundamental", "📊", "펀더"), ("macro", "🌍", "매크로"),
        ("news", "📰", "뉴스"), ("event", "📅", "이벤트"), ("risk", "🛡️", "리스크"),
    ]:
        a = agents.get(key)
        if not a or "score" not in a:
            continue
        s = a.get("score", 0)
        ag_rows += (
            f"<div class='agent-row'>"
            f"<div class='agent-icon'>{icon}</div>"
            f"<div class='agent-name'>{label}</div>"
            f"<div class='agent-bar'><div class='agent-fill {fill_class(s)}' style='width:{s}%'></div></div>"
            f"<div class='agent-score'>{s:.0f}</div>"
            f"</div>"
        )
    st.markdown(
        f"<div class='agents-box'><div class='section-title'>📊 에이전트 분석</div>{ag_rows}</div>",
        unsafe_allow_html=True
    )

    with st.expander("📌 핵심 근거", expanded=True):
        for r in synth.get("key_reasons", []):
            st.markdown(f"- {r}")

    with st.expander("⚠️ 리스크 요인"):
        for r in synth.get("risk_factors", []):
            st.markdown(f"- {r}")

    pattern = agents.get("pattern", {})
    if pattern.get("patterns"):
        with st.expander(f"🔍 차트 패턴 ({pattern.get('comment', '')})"):
            for p in pattern.get("patterns", []):
                neg = " ⚠️" if p.get("negative") else ""
                st.markdown(f"**{p['pattern']}**{neg} ({p.get('confidence', 0)}%)")
                st.caption(f"근거: {p.get('evidence', '')}")
                if p.get("action"):
                    st.caption(f"→ {p['action']}")

    event = agents.get("event", {})
    if event.get("recent_events"):
        with st.expander(f"📅 이벤트 ({event.get('comment', '')})"):
            for ev in event.get("recent_events", []):
                impact = ev.get("impact", "neutral")
                icon = {"positive": "🟢", "negative": "🔴", "earnings": "📊", "neutral": "·"}.get(impact, "·")
                st.markdown(f"{icon} **{ev.get('date', '')}** {ev.get('title', '')}")

    with st.expander("🎬 매매 시나리오"):
        if synth.get("scenario_profit"):
            st.markdown(f"📈 **익절**: {synth['scenario_profit']}")
        if synth.get("scenario_stop"):
            st.markdown(f"🛑 **손절**: {synth['scenario_stop']}")
        ed = result.get("earnings_date")
        if ed and ed.get("date"):
            st.warning(f"⏰ 실적 발표 임박: {ed['date']} (D-{ed.get('days_until', '?')})")

    with st.expander("📊 보조 지표"):
        c1, c2, c3 = st.columns(3)
        chart = agents.get("chart", {})
        c1.metric("이평선", {
            "perfect_uptrend": "완전정배열", "uptrend": "정배열",
            "sideways": "횡보", "downtrend": "역배열",
            "perfect_downtrend": "완전역배열"
        }.get(chart.get("daily_trend", ""), "—"))
        c2.metric("RSI", f"{chart.get('rsi', 0):.1f}" if chart.get('rsi') else "—")
        c3.metric("MACD", chart.get("macd_status", "—"))
        c4, c5, c6 = st.columns(3)
        c4.metric("주봉", chart.get("weekly_trend", "—"))
        ch5 = ind.get("change_5d_pct")
        c5.metric("5일변동", f"{ch5:+.1f}%" if ch5 is not None else "—")
        c6.metric("거래량", f"{ind.get('volume', {}).get('ratio', 0):.1f}배")

    cc1, cc2 = st.columns(2)
    if cc1.button("💰 매수함", key=f"buy_{card_idx}", use_container_width=True):
        hist.open_position(
            market=si.get("market"), ticker=si.get("ticker"), name=si.get("name"),
            entry_price=cur, stop_loss=prices.get("stop_loss"), take_profit=prices.get("take_profit"),
        )
        st.success(f"✅ {si.get('name')} 보유 처리됨")

    if cc2.button("↻ 재분석", key=f"redo_{card_idx}", use_container_width=True):
        with st.spinner("재분석 중..."):
            held = hist.get_held_tickers()
            excluded = [si.get("ticker")] + (hist.get_recent_tickers(3))
            new_r = recommend_one(
                Market.KRX if is_krx else Market.US,
                held_tickers=held, excluded_tickers=excluded,
                regime="unknown",
            )
            if new_r:
                if is_krx:
                    st.session_state.krx_result = new_r
                else:
                    st.session_state.us_result = new_r
                st.rerun()


# ===== 실행 =====
if get_btn:
    held = hist.get_held_tickers()
    recent = hist.get_recent_tickers(3)
    with st.spinner("🇰🇷 국장 분석 중 (1~2분)..."):
        try:
            r = recommend_one(Market.KRX, held_tickers=held, excluded_tickers=recent, regime="unknown")
            if r:
                st.session_state.krx_result = r
        except Exception as e:
            st.error(f"국장 실패: {e}")
            import traceback
            with st.expander("상세 오류"):
                st.code(traceback.format_exc())
    with st.spinner("🇺🇸 미장 분석 중 (1~2분)..."):
        try:
            r = recommend_one(Market.US, held_tickers=held, excluded_tickers=recent, regime="unknown")
            if r:
                st.session_state.us_result = r
        except Exception as e:
            st.error(f"미장 실패: {e}")
            import traceback
            with st.expander("상세 오류"):
                st.code(traceback.format_exc())


if st.session_state.krx_result:
    st.markdown("<div class='stock-card'>", unsafe_allow_html=True)
    render_card(st.session_state.krx_result, "🇰🇷", "krx")
    st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.us_result:
    st.markdown("<div class='stock-card'>", unsafe_allow_html=True)
    render_card(st.session_state.us_result, "🇺🇸", "us")
    st.markdown("</div>", unsafe_allow_html=True)


# ===== 사이드바 =====
with st.sidebar:
    st.header("📊 현황")
    stats = hist.get_stats()
    a, b = st.columns(2)
    a.metric("추천", stats["total_recommendations"])
    b.metric("보유", stats["open_positions"])

    try:
        calib = hist.get_calibration_stats(days_window=90)
        if calib.get("total_labeled", 0) > 0:
            st.markdown("---")
            st.subheader("🎯 최근 90일 성과")
            st.markdown(
                f"<div class='calibration-card'>"
                f"<div style='font-size:13px;color:var(--text-sub)'>라벨링 {calib['total_labeled']}건</div>"
                f"<div style='font-size:24px;font-weight:800;color:var(--text);margin-top:4px'>승률 {calib['win_rate_pct']}%</div>"
                f"<div style='font-size:12px;color:var(--text-sub);margin-top:4px'>"
                f"✅ 목표 {calib['hit_target_count']} / ❌ 손절 {calib['hit_stop_count']} / ⏸ 홀딩 {calib['holding_count']}</div>"
                f"<div style='font-size:12px;color:var(--text-sub);margin-top:4px'>"
                f"평균: 3일 {calib['avg_return_3d_pct']:+.1f}% / 7일 {calib['avg_return_7d_pct']:+.1f}%</div>"
                f"</div>",
                unsafe_allow_html=True
            )
            if calib.get("by_grade"):
                with st.expander("등급별 상세"):
                    for g, v in calib["by_grade"].items():
                        if v["count"] > 0:
                            st.caption(f"**{g}** ({v['count']}건) 승률 {v.get('win_rate', 0):.0f}% / 평균 {v.get('avg_return', 0):+.1f}%")
        else:
            st.markdown("---")
            st.caption("📝 라벨링된 결과 없음 — 추천 후 3일 지나면 라벨링 가능")
    except Exception as e:
        st.caption(f"통계 실패: {e}")

    st.markdown("---")
    if st.button("🔄 결과 라벨링 갱신", use_container_width=True, key="refresh_labels"):
        with st.spinner("라벨링 중..."):
            try:
                from storage.outcome_labeler import label_all_pending
                result = label_all_pending()
                st.success(f"✅ {result['success']}건 라벨링 (실패 {result['failed']})")
                st.rerun()
            except Exception as e:
                st.error(f"라벨링 실패: {e}")

    if stats["closed_count"] > 0:
        st.markdown("---")
        st.subheader("💼 클로즈드")
        st.metric("승률", f"{stats['win_rate_pct']}%", f"평균 {stats['avg_return_pct']:+.1f}%")

    st.divider()
    st.subheader("💼 보유 종목")
    ops = hist.get_open_positions()
    if not ops:
        st.caption("없음")
    else:
        for p in ops:
            with st.expander(f"{p['name']}"):
                st.write(f"진입: {p['entry_price']:,.0f}")
                if p["stop_loss"]:
                    st.write(f"손절: {p['stop_loss']:,.0f}")
                if p["take_profit"]:
                    st.write(f"익절: {p['take_profit']:,.0f}")
                ep = st.number_input("매도가", value=float(p["entry_price"]), key=f"ep_{p['ticker']}")
                if st.button("매도 처리", key=f"cl_{p['ticker']}"):
                    hist.close_position(p["ticker"], ep)
                    st.rerun()

    st.divider()
    st.subheader("📜 최근 추천")
    for r in hist.get_recent_recommendations(15):
        g = r["grade"] or ""
        emoji = "🟢🟢" if g == "적극매수" else "🟢" if g == "매수" else "🟡" if g == "관망" else "🟠" if g == "비중축소" else "🔴" if g == "회피" else "·"
        outcome_str = ""
        if r.get("outcome_7d_return_pct") is not None:
            ret = r["outcome_7d_return_pct"]
            outcome_str = f" ({ret:+.1f}%)"
        st.caption(f"{r['recommended_at'][:10]} {emoji} {r['name']}{outcome_str}")

st.divider()
st.caption("⚠️ 투자 참고용. 매매 책임은 본인. 손절은 토스에서 직접.")
