"""
tests/test_full.py

본인 PC에서 한 번 실행 - 모든 API/모듈 작동 검증.
사용법: python -m tests.test_full
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    print("=" * 60)
    print("스윙 추천기 전체 검증")
    print("=" * 60)
    
    # 1. 설정
    print("\n[1] 설정 검증...")
    try:
        from config import validate_config
        validate_config()
        print("    ✅ .env 설정 OK")
    except Exception as e:
        print(f"    ❌ {e}")
        return
    
    # 2. 한투 API
    print("\n[2] 한투 API...")
    try:
        from data.kis_api import get_kis
        kis = get_kis()
        token = kis.get_token()
        assert token
        print(f"    ✅ 토큰 OK (...{token[-10:]})")
        
        # 삼성전자 시세
        q = kis.domestic_price("005930")
        assert q["price"] > 0
        print(f"    ✅ 삼성전자: {q['price']:,}원 ({q['change_pct']:+.2f}%)")
        
        # 일봉
        bars = kis.domestic_daily("005930", days=30)
        assert len(bars) > 5
        print(f"    ✅ 일봉 {len(bars)}건")
        
        # 거래대금 상위
        top = kis.domestic_top_value(top_n=5)
        assert len(top) >= 3
        print(f"    ✅ 거래대금 상위: {', '.join(t['name'] for t in top[:3])}")
        
        # 외국인/기관
        flow = kis.domestic_investor_flow("005930")
        print(f"    ✅ 수급 조회 ({flow.get('days_available', 0)}일치)")
        
        # 미장
        usq = kis.overseas_price("AAPL", "NAS")
        print(f"    ✅ AAPL: ${usq['price']:.2f}")
        
    except Exception as e:
        print(f"    ❌ {e}")
        return
    
    # 3. Finnhub
    print("\n[3] Finnhub...")
    try:
        from data.finnhub_api import get_finnhub
        fh = get_finnhub()
        q = fh.quote("NVDA")
        assert q["price"] > 0
        print(f"    ✅ NVDA: ${q['price']:.2f}")
    except Exception as e:
        print(f"    ⚠️  {e}")
    
    # 4. 매크로
    print("\n[4] 매크로 (FRED/Yahoo/AV)...")
    try:
        from data.macro_api import get_macro
        m = get_macro()
        d = m.get_all()
        print(f"    환율: {d.get('usd_krw', '—')}")
        print(f"    VIX: {d.get('vix', '—')}")
        print(f"    10년 금리: {d.get('us10y', '—')}%")
        print(f"    F&G: {d.get('fear_greed', '—')}")
        print(f"    코스피: {(d.get('kospi') or {}).get('price', '—')}")
        print(f"    S&P500: {(d.get('sp500') or {}).get('price', '—')}")
        print("    ✅ 매크로 OK")
    except Exception as e:
        print(f"    ⚠️  {e}")
    
    # 5. 뉴스
    print("\n[5] 뉴스...")
    try:
        from data.news_api import get_news_us, get_news_kr
        us_news = get_news_us("NVDA", "Nvidia")
        kr_news = get_news_kr("005930", "삼성전자")
        print(f"    NVDA 뉴스: {len(us_news)}건")
        print(f"    삼성전자 뉴스: {len(kr_news)}건")
        print("    ✅ 뉴스 OK")
    except Exception as e:
        print(f"    ⚠️  {e}")
    
    # 6. 미장 풀
    print("\n[6] 미장 활성 종목...")
    try:
        from data.us_movers import get_us_top_active
        us_top = get_us_top_active(top_n=5)
        print(f"    상위: {', '.join(t['ticker'] for t in us_top[:5])}")
        print("    ✅ 미장 풀 OK")
    except Exception as e:
        print(f"    ⚠️  {e}")
    
    # 7. 자동 풀 빌더
    print("\n[7] 풀 빌더...")
    try:
        from data.pool_builder import build_krx_pool, build_us_pool
        krx = build_krx_pool()
        us = build_us_pool()
        print(f"    국장: {len(krx)}개")
        print(f"    미장: {len(us)}개")
        print("    ✅ 풀 OK")
    except Exception as e:
        print(f"    ⚠️  {e}")
    
    # 8. 시장 신호
    print("\n[8] 시장 신호등...")
    try:
        from core.market_signal import get_signal
        sig = get_signal()
        print(f"    심리: {sig['label']}")
        print("    ✅ 신호등 OK")
    except Exception as e:
        print(f"    ⚠️  {e}")
    
    # 9. Claude AI (실제 호출 - 비용 발생)
    print("\n[9] Claude AI 호출...")
    try:
        from agents.macro_agent import evaluate as macro_eval
        fake_macro = {
            "vix": 18, "us10y": 4.2, "usd_krw": 1380,
            "kospi": {"price": 2520, "change_pct": 0.5, "above_ma20": True},
            "sp500": {"price": 5700, "change_pct": 0.3, "above_ma20": True},
            "fear_greed": 45,
        }
        r = macro_eval({"ticker":"TEST","name":"테스트","market":"KRX","sector":"반도체"}, fake_macro)
        print(f"    매크로 평가: {r.get('score', 0)}점")
        print(f"    🪙 약 0.5센트 소진")
        print("    ✅ Claude AI OK")
    except Exception as e:
        print(f"    ❌ {e}")
    
    # 10. DB
    print("\n[10] 히스토리 DB...")
    try:
        from storage.history import init_db, get_stats
        init_db()
        s = get_stats()
        print(f"    추천: {s['total_recommendations']}, 보유: {s['open_positions']}")
        print("    ✅ DB OK")
    except Exception as e:
        print(f"    ❌ {e}")
    
    # 11. 전체 추천 흐름
    print("\n[11] 통합 추천 1회 (국장)...")
    print("    이건 30~60초 걸립니다.")
    try:
        from core.recommender import recommend_one
        from data.pool_builder import Market
        r = recommend_one(Market.KRX)
        if r:
            s = r["synthesis"]
            si = r["stock_info"]
            print(f"    ✅ {si.get('name')} - {s.get('grade')} ({s.get('total_score'):.0f}점)")
            print(f"       진입: {s.get('prices', {}).get('entry_label')}")
            print(f"       손절: {s.get('prices', {}).get('stop_loss')}")
            print(f"       익절: {s.get('prices', {}).get('take_profit')}")
        else:
            print("    ⚠️ 추천 결과 없음")
    except Exception as e:
        print(f"    ❌ {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("🎉 검증 완료")
    print("=" * 60)
    print("\n다음: streamlit run ui/app.py")


if __name__ == "__main__":
    main()
