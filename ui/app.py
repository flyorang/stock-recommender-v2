"""
ui/app.py
스윙 추천기 - Streamlit UI

- 다크모드 기본
- 카드형 레이아웃
- 6 에이전트 점수 막대그래프
- 접었다 펴기
- 재분석 버튼
- 모바일 최적화
"""
import sys
from pathlib import Path
from datetime import datetime

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
    initial_sidebar_state="collapsed",
)

# ===== CSS (다크모드 기본) =====
st.markdown("""
<style>
:root {
  --bg: #0f1115;
  --card: #1a1d24;
  --text: #f4f5f7;
  --text-sub: #adb5bd;
  --text-light: #6c757d;
  --border: #2c2f36;
  --primary: #4dabf7;
  --success: #51cf66;
  --warning: #ffd43b;
  --danger: #ff6b6b;
}

html, body, [class*="st-"], .stApp {
  background-color: var(--bg) !important;
  color: var(--text) !important;
}
.stApp { background: var(--bg) !important; }
.block-container { padding-top: 1rem !important; padding-bottom: 5rem; max-width: 720px; }

/* 시장 신호 박스 */
.market-signal {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.signal-emoji { font-size: 40px; }
.signal-title { font-size: 16px; font-weight: 700; color: var(--text); }
.signal-detail { font-size: 12px; color: var(--text-sub); margin-top: 2px; }

/* 지수 그리드 */
.indices {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin-bottom: 16px;
}
.idx-item {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 4px;
  text-align: center;
}
.idx-name { font-size: 10px; color: var(--text-sub); letter-spacing: 0.5px; font-weight: 600; }
.idx-value { font-size: 14px; font-weight: 800; color: var(--text); margin-top: 2px; }
.idx-change { font-size: 11px; margin-top: 1px; font-weight: 600; }
.up { color: var(--danger); }
.down { color: var(--primary); }

/* 종목 카드 */
.stock-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 0;
  margin-bottom: 14px;
  overflow: hidden;
}
.stock-head {
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--border);
}
.stock-name {
  font-size: 19px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.5px;
}
.stock-meta {
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 3px;
}

/* 등급 박스 */
.grade-box {
  padding: 22px 16px;
  text-align: center;
  color: white;
}
.grade-buy { background: linear-gradient(135deg, #339af0, #1971c2); }
.grade-strong-buy { background: linear-gradient(135deg, #51cf66, #2f9e44); }
.grade-hold { background: linear-gradient(135deg, #fab005, #f08c00); color: #fff; }
.grade-reduce { background: linear-gradient(135deg, #fd7e14, #d9480f); }
.grade-avoid { background: linear-gradient(135deg, #e03131, #c92a2a); }

.grade-label {
  font-size: 32px;
  font-weight: 900;
  letter-spacing: -1px;
}
.grade-sub {
  font-size: 13px;
  opacity: 0.9;
  margin-top: 4px;
}
.grade-summary {
  font-size: 14px;
  font-weight: 600;
  margin-top: 12px;
  line-height: 1.4;
}

/* 가격 */
.price-box {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.price-now {
  font-size: 28px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -1px;
}
.price-chg {
  font-size: 13px;
  font-weight: 700;
  margin-left: 6px;
}

.guide-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  margin-top: 12px;
}
.guide-item {
  padding: 10px;
  border-radius: 10px;
  background: var(--bg);
  text-align: center;
}
.guide-item.entry { border: 1px solid var(--primary); }
.guide-item.stop { border: 1px solid var(--danger); }
.guide-item.profit { border: 1px solid var(--success); }
.g-label { font-size: 10px; color: var(--text-sub); font-weight: 700; letter-spacing: 0.5px; }
.g-value { font-size: 14px; font-weight: 800; margin-top: 4px; color: var(--text); }
.g-pct { font-size: 11px; margin-top: 2px; font-weight: 600; }
.pl-ratio { text-align: center; font-size: 12px; color: var(--text-sub); margin-top: 8px; }
.pl-ratio strong { color: var(--success); font-weight: 700; }

/* 에이전트 */
.agents-box { padding: 14px 18px; border-bottom: 1px solid var(--border); }
.section-title { font-size: 11px; font-weight: 700; letter-spacing: 1px; color: var(--text-sub); margin-bottom: 10px; text-transform: uppercase; }
.agent-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.agent-row:last-child { margin-bottom: 0; }
.agent-icon { width: 16px; font-size: 13px; }
.agent-name { width: 48px; font-size: 12px; font-weight: 600; color: var(--text); }
.agent-bar { flex: 1; height: 6px; background: var(--bg); border-radius: 3px; overflow: hidden; }
.agent-fill { height: 100%; border-radius: 3px; transition: width .5s; }
.fill-high { background: linear-gradient(90deg, #51cf66, #2f9e44); }
.fill-mid { background: linear-gradient(90deg, #ffd43b, #fab005); }
.fill-low { background: linear-gradient(90deg, #ff6b6b, #e03131); }
.agent-score { width: 28px; text-align: right; font-size: 12px; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--text); }

/* 모순 경고 */
.contradiction {
  background: rgba(255, 212, 59, 0.1);
  border: 1px solid rgba(255, 212, 59, 0.3);
  color: var(--warning);
  padding: 8px 12px;
  border-radius: 8px;
  margin: 8px 0;
  font-size: 12px;
}

/* 추가 정보 박스 */
.info-list { padding-left: 0; list-style: none; }
.info-list li {
  padding: 6px 0 6px 18px;
  font-size: 13px;
  color: var(--text);
  position: relative;
  line-height: 1.5;
}
.info-list li::before {
  content: "•";
  position: absolute;
  left: 4px;
  color: var(--primary);
  font-weight: 800;
}
.info-list.risk li::before { color: var(--danger); }

/* Streamlit 컴포넌트 색 보정 */
/* 버튼 - 얇은 형광 테두리 */
.stButton, .stButton * {
  outline: 0 !important;
  box-shadow: none !important;
}
.stButton {
  background: transparent !important;
}
.stButton > button {
  background: #1a1d24 !important;
  color: #00ffaa !important;
  border: 1px solid #00ffaa !important;
  border-radius: 10px !important;
  font-weight: 700 !important;
  padding: 12px !important;
  width: 100% !important;
  transition: all 0.15s;
}
.stButton > button:hover {
  background: #00ffaa !important;
  color: #0f1115 !important;
  border-color: #00ffaa !important;
}
.stButton > button:active {
  background: #00d68f !important;
  border-color: #00d68f !important;
}
[data-testid="stExpander"] {
  background: var(--card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
}
[data-testid="stExpander"] summary {
  color: var(--text) !important;
}
[data-testid="stMetric"] {
  background: var(--card);
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
}

/* 라디오 */
.stRadio > div { 
  background: var(--card) !important; 
  padding: 4px !important; 
  border-radius: 10px !important; 
  border: 1px solid var(--border) !important;
}
.stRadio label { color: var(--text) !important; }

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
st.caption("국장 + 미장 · 3~7일 보유 · 6 에이전트 분석")


# ===== 시장 신호 =====
with st.spinner("시장 분석..."):
    signal = get_signal()

psy = signal["psychology"]
psy_emoji = {"fear": "🟢", "neutral": "🟡", "greed": "🔴"}[psy]
macro = signal.get("macro", {})

st.markdown(f"<div class='market-signal'><div class='signal-emoji'>{psy_emoji}</div><div><div class='signal-title'>{signal['label']}</div><div class='signal-detail'>{signal['detail']}</div></div></div>", unsafe_allow_html=True)

# 지수
kospi = macro.get("kospi") or {}
sp500 = macro.get("sp500") or {}

k_chg_class = "up" if kospi.get("change_pct", 0) >= 0 else "down"
s_chg_class = "up" if sp500.get("change_pct", 0) >= 0 else "down"

indices_html = (
    f"<div class='indices'>"
    f"<div class='idx-item'><div class='idx-name'>KOSPI</div><div class='idx-value'>{kospi.get('price', 0):.0f}</div><div class='idx-change {k_chg_class}'>{kospi.get('change_pct', 0):+.2f}%</div></div>"
    f"<div class='idx-item'><div class='idx-name'>S&P</div><div class='idx-value'>{sp500.get('price', 0):.0f}</div><div class='idx-change {s_chg_class}'>{sp500.get('change_pct', 0):+.2f}%</div></div>"
    f"<div class='idx-item'><div class='idx-name'>VIX</div><div class='idx-value'>{(macro.get('vix') or 0):.1f}</div><div class='idx-change'>—</div></div>"
    f"<div class='idx-item'><div class='idx-name'>USD</div><div class='idx-value'>{(macro.get('usd_krw') or 0):.0f}</div><div class='idx-change'>—</div></div>"
    f"</div>"
)
st.markdown(indices_html, unsafe_allow_html=True)


# ===== 메인 버튼 =====
col1, col2 = st.columns([3, 1])
get_btn = col1.button("🎯 추천 받기", use_container_width=True)
clear_btn = col2.button("🔄 초기화", use_container_width=True)

if clear_btn:
    st.session_state.krx_result = None
    st.session_state.us_result = None
    st.rerun()


# ===== 카드 렌더링 =====
def render_card(result: dict, flag: str, card_idx: str):
    if not result:
        return
    
    si = result["stock_info"]
    quote = result.get("quote", {})
    synth = result["synthesis"]
    agents = result["agents"]
    ind = result.get("indicators", {})
    is_krx = si.get("market") == "KRX"
    
    # 헤더
    st.markdown(
        f"<div class='stock-head'><div class='stock-name'>{flag} {si.get('name', '')} <span style='color:var(--text-sub);font-size:14px;font-weight:500'>({si.get('ticker', '')})</span></div><div class='stock-meta'>📁 {si.get('sector', '—')}</div></div>",
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
    
    st.markdown(
        f"<div class='grade-box {css_class}'><div class='grade-label'>{synth.get('grade_emoji', '')} {synth.get('grade', '')}</div><div class='grade-sub'>종합 {synth.get('total_score', 0):.0f}/100 · 확신도 {synth.get('confidence', 0)}/10</div><div class='grade-summary'>{synth.get('summary', '')}</div></div>",
        unsafe_allow_html=True
    )
    
    # 모순 경고
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
    
    price_html = (
        f"<div class='price-box'>"
        f"<div><span class='price-now'>{price_str}</span><span class='price-chg {chg_class}'>{chg_sign}{change_pct:.2f}%</span></div>"
        f"<div class='guide-grid'>"
        f"<div class='guide-item entry'><div class='g-label'>🎯 진입</div><div class='g-value'>{prices.get('entry_label', '—')}</div></div>"
        f"<div class='guide-item stop'><div class='g-label'>🛑 손절</div><div class='g-value'>{fmt_p(prices.get('stop_loss'))}</div><div class='g-pct down'>-{prices.get('expected_risk_pct', 0)}%</div></div>"
        f"<div class='guide-item profit'><div class='g-label'>💰 익절</div><div class='g-value'>{fmt_p(prices.get('take_profit'))}</div><div class='g-pct up'>+{prices.get('expected_return_pct', 0)}%</div></div>"
        f"</div>"
        f"<div class='pl-ratio'>손익비 <strong>1 : {prices.get('profit_loss_ratio', 0)}</strong> · 보유 {synth.get('hold_days', '')}</div>"
        f"</div>"
    )
    st.markdown(price_html, unsafe_allow_html=True)
    
    # 6 에이전트
    def fill_class(s):
        return "fill-high" if s >= 70 else "fill-mid" if s >= 45 else "fill-low"
    
    ag_rows = ""
    for key, icon, label in [
        ("chart", "📈", "차트"),
        ("fundamental", "📊", "펀더"),
        ("macro", "🌍", "매크로"),
        ("news", "📰", "뉴스"),
        ("supply", "💰", "수급"),
        ("risk", "🛡️", "리스크"),
    ]:
        s = agents.get(key, {}).get("score", 0)
        ag_rows += f"<div class='agent-row'><div class='agent-icon'>{icon}</div><div class='agent-name'>{label}</div><div class='agent-bar'><div class='agent-fill {fill_class(s)}' style='width:{s}%'></div></div><div class='agent-score'>{s:.0f}</div></div>"
    
    st.markdown(f"<div class='agents-box'><div class='section-title'>📊 6개 에이전트 분석</div>{ag_rows}</div>", unsafe_allow_html=True)
    
    # 핵심 근거
    with st.expander("📌 핵심 근거", expanded=True):
        for r in synth.get("key_reasons", []):
            st.markdown(f"- {r}")
    
    # 리스크
    with st.expander("⚠️ 리스크 요인"):
        for r in synth.get("risk_factors", []):
            st.markdown(f"- {r}")
    
    # 시나리오
    with st.expander("🎬 매매 시나리오"):
        if synth.get("scenario_profit"):
            st.markdown(f"📈 **익절**: {synth['scenario_profit']}")
        if synth.get("scenario_stop"):
            st.markdown(f"🛑 **손절**: {synth['scenario_stop']}")
        ed = result.get("earnings_date")
        if ed and ed.get("date"):
            st.warning(f"⏰ 실적 발표 임박: {ed['date']} (D-{ed.get('days_until', '?')})")
    
    # 보조 지표
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
    
    # 액션 버튼
    cc1, cc2 = st.columns(2)
    if cc1.button("💰 매수함", key=f"buy_{card_idx}", use_container_width=True):
        hist.open_position(
            market=si.get("market"),
            ticker=si.get("ticker"),
            name=si.get("name"),
            entry_price=cur,
            stop_loss=prices.get("stop_loss"),
            take_profit=prices.get("take_profit"),
        )
        st.success(f"✅ {si.get('name')} 보유 처리됨")
    
    # 재분석 버튼
    if cc2.button("↻ 재분석", key=f"redo_{card_idx}", use_container_width=True):
        with st.spinner("재분석 중..."):
            held = hist.get_held_tickers()
            excluded = [si.get("ticker")] + (hist.get_recent_tickers(3))
            new_r = recommend_one(
                Market.KRX if is_krx else Market.US,
                held_tickers=held,
                excluded_tickers=excluded,
            )
            if new_r:
                if is_krx:
                    st.session_state.krx_result = new_r
                else:
                    st.session_state.us_result = new_r
                _save_result(new_r)
                st.rerun()


def _save_result(r: dict):
    si = r["stock_info"]
    synth = r["synthesis"]
    quote = r.get("quote", {})
    hist.save_recommendation(
        market=si["market"], ticker=si["ticker"], name=si["name"],
        sector=si.get("sector", ""), price=quote.get("price", 0),
        grade=synth.get("grade", ""),
        score=synth.get("total_score", 0),
        stop_loss=synth.get("prices", {}).get("stop_loss", 0),
        take_profit=synth.get("prices", {}).get("take_profit", 0),
        data={"agents": r.get("agents", {}), "synthesis": synth},
    )


# ===== 실행 =====
if get_btn:
    held = hist.get_held_tickers()
    recent = hist.get_recent_tickers(3)
    
    with st.spinner("🇰🇷 국장 분석 중 (1~2분)..."):
        try:
            r = recommend_one(Market.KRX, held_tickers=held, excluded_tickers=recent)
            if r:
                st.session_state.krx_result = r
                _save_result(r)
        except Exception as e:
            st.error(f"국장 실패: {e}")
            import traceback
            with st.expander("상세 오류"):
                st.code(traceback.format_exc())
    
    with st.spinner("🇺🇸 미장 분석 중 (1~2분)..."):
        try:
            r = recommend_one(Market.US, held_tickers=held, excluded_tickers=recent)
            if r:
                st.session_state.us_result = r
                _save_result(r)
        except Exception as e:
            st.error(f"미장 실패: {e}")
            import traceback
            with st.expander("상세 오류"):
                st.code(traceback.format_exc())


# ===== 카드 표시 =====
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
    if stats["closed_count"] > 0:
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
        st.caption(f"{r['recommended_at'][:10]} {emoji} {r['name']}")

st.divider()
st.caption("⚠️ 투자 참고용. 매매 책임은 본인. 손절은 토스에서 직접.")
