"""
storage/outcome_labeler.py — NEW
추천 결과 자동 라벨링 잡 (일일 실행 권장).

사용법:
    python -m storage.outcome_labeler
    
또는 cron:
    0 18 * * * cd /path/to/sr2 && python -m storage.outcome_labeler

3거래일 이상 지난 미라벨링 추천에 대해:
1. 현재 가격 조회
2. 3일/7일 후 가격 + 7일 내 고가/저가 계산
3. history.label_outcome() 호출
"""
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from storage.history import get_unlabeled_recommendations, label_outcome
from data.kis_api import get_kis
from logger import get_logger

log = get_logger("labeler")


def _calculate_outcome_from_bars(
    bars: list,
    rec_date_str: str,
) -> dict:
    """일봉 데이터에서 추천일 기준 3일/7일 후 종가 + 7일 내 고/저 추출"""
    if not bars:
        return {}
    rec_date = datetime.fromisoformat(rec_date_str).date()

    # 추천일 이후 일봉만
    after_bars = []
    for b in bars:
        date_str = b.get("date", "")
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date() if "-" in date_str else None
            if d is None:
                # 한투는 YYYYMMDD 형식일 수 있음
                d = datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, TypeError):
            continue
        if d > rec_date:
            after_bars.append((d, b))

    after_bars.sort(key=lambda x: x[0])
    if not after_bars:
        return {}

    result = {}
    # 3일 후 종가
    if len(after_bars) >= 3:
        result["price_3d"] = after_bars[2][1].get("close")
    # 7일 후 종가
    if len(after_bars) >= 7:
        result["price_7d"] = after_bars[6][1].get("close")
    elif after_bars:
        # 7일치 없으면 마지막 사용
        result["price_7d"] = after_bars[-1][1].get("close")

    # 7일 내 최고가/최저가
    seven_bars = [b for _, b in after_bars[:7]]
    if seven_bars:
        highs = [b.get("high", 0) for b in seven_bars if b.get("high")]
        lows = [b.get("low", 0) for b in seven_bars if b.get("low")]
        if highs:
            result["max_high_7d"] = max(highs)
        if lows:
            result["max_low_7d"] = min(lows)

    return result


def label_all_pending(min_days_old: int = 3, max_count: int = 50) -> dict:
    """미라벨링 추천 일괄 처리"""
    pending = get_unlabeled_recommendations(min_days_old=min_days_old)
    log.info(f"미라벨링 추천 {len(pending)}건")

    if not pending:
        return {"processed": 0, "success": 0, "failed": 0}

    kis = get_kis()
    success = 0
    failed = 0

    for i, rec in enumerate(pending[:max_count]):
        ticker = rec.get("ticker")
        market = rec.get("market", "KRX")
        rec_date = rec.get("recommended_at", "")
        rec_id = rec.get("id")

        try:
            # 일봉 30일치 가져오기
            if market == "KRX":
                bars = kis.domestic_daily(ticker, days=30)
            else:
                # 미장은 exchange 정보 필요 — data_json에서 추출
                import json
                data = json.loads(rec.get("data_json", "{}"))
                exch = data.get("stock_info", {}).get("exchange", "NAS")
                bars = kis.overseas_daily(ticker, exch, days=30)

            outcome = _calculate_outcome_from_bars(bars, rec_date)
            if not outcome:
                log.warning(f"  [{i+1}/{len(pending)}] {ticker} 일봉 데이터 부족")
                failed += 1
                continue

            label_outcome(
                rec_id=rec_id,
                price_3d=outcome.get("price_3d"),
                price_7d=outcome.get("price_7d"),
                max_high_7d=outcome.get("max_high_7d"),
                max_low_7d=outcome.get("max_low_7d"),
            )

            ret_7d = ((outcome.get("price_7d") or 0) / rec.get("price", 1) - 1) * 100 if rec.get("price") else 0
            log.info(f"  [{i+1}/{len(pending)}] {ticker} {rec.get('name', '')} → 7일 {ret_7d:+.1f}%")
            success += 1

        except Exception as e:
            log.error(f"  [{i+1}/{len(pending)}] {ticker} 실패: {e}")
            failed += 1

    return {"processed": min(len(pending), max_count), "success": success, "failed": failed}


if __name__ == "__main__":
    result = label_all_pending()
    print(f"\n결과: 처리 {result['processed']} / 성공 {result['success']} / 실패 {result['failed']}")
