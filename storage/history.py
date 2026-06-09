"""
storage/history.py — v2 (추천 결과 트래킹 추가)

기존 기능 유지 + 추가:
1. recommendations 테이블 컨펌: 3일/7일 후 결과 자동 라벨링용 컬럼
2. label_outcome(): 추천 시점부터 N일 후 실제 결과 기록
3. get_calibration_stats(): 에이전트별/등급별 적중률 통계

매일 1회 cron으로 unlabeled 추천에 대해 label_outcome() 호출 권장.
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_PATH


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommended_at TEXT,
            market TEXT,
            ticker TEXT,
            name TEXT,
            sector TEXT,
            price REAL,
            grade TEXT,
            score REAL,
            stop_loss REAL,
            take_profit REAL,
            data_json TEXT,
            -- NEW: 결과 트래킹
            outcome_3d_price REAL,
            outcome_3d_return_pct REAL,
            outcome_7d_price REAL,
            outcome_7d_return_pct REAL,
            outcome_hit_stop INTEGER DEFAULT 0,
            outcome_hit_target INTEGER DEFAULT 0,
            outcome_max_high_7d REAL,
            outcome_max_low_7d REAL,
            outcome_labeled_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations(recommended_at);
        CREATE INDEX IF NOT EXISTS idx_rec_ticker ON recommendations(ticker);
        CREATE INDEX IF NOT EXISTS idx_rec_labeled ON recommendations(outcome_labeled_at);

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_at TEXT,
            market TEXT,
            ticker TEXT,
            name TEXT,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL
        );
        CREATE INDEX IF NOT EXISTS idx_pos_ticker ON positions(ticker);

        CREATE TABLE IF NOT EXISTS closed_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_at TEXT, closed_at TEXT,
            market TEXT, ticker TEXT, name TEXT,
            entry_price REAL, exit_price REAL, return_pct REAL
        );
        """)
        # ALTER TABLE: 기존 DB에 새 컬럼 추가
        _migrate_add_outcome_columns(c)


def _migrate_add_outcome_columns(c):
    """기존 DB에 outcome 컬럼이 없으면 추가"""
    cols = {row["name"] for row in c.execute("PRAGMA table_info(recommendations)")}
    migrations = [
        ("outcome_3d_price", "REAL"),
        ("outcome_3d_return_pct", "REAL"),
        ("outcome_7d_price", "REAL"),
        ("outcome_7d_return_pct", "REAL"),
        ("outcome_hit_stop", "INTEGER DEFAULT 0"),
        ("outcome_hit_target", "INTEGER DEFAULT 0"),
        ("outcome_max_high_7d", "REAL"),
        ("outcome_max_low_7d", "REAL"),
        ("outcome_labeled_at", "TEXT"),
    ]
    for col, typ in migrations:
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE recommendations ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass


def save_recommendation(
    market: str, ticker: str, name: str, sector: str,
    price: float, grade: str, score: float,
    stop_loss: float, take_profit: float, data: Dict,
) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO recommendations
            (recommended_at, market, ticker, name, sector, price, grade, score, stop_loss, take_profit, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(), market, ticker, name, sector,
             price, grade, score, stop_loss, take_profit,
             json.dumps(data, ensure_ascii=False, default=str)),
        )
        return cur.lastrowid


def get_recent_recommendations(limit: int = 20) -> List[Dict]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM recommendations ORDER BY recommended_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_tickers(limit: int = 5) -> List[str]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT ticker FROM recommendations ORDER BY recommended_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r["ticker"] for r in rows]


# ════════════════════════════════════════════════════════════
# 결과 라벨링 (NEW)
# ════════════════════════════════════════════════════════════
def get_unlabeled_recommendations(min_days_old: int = 3) -> List[Dict]:
    """라벨링 안 된 추천 중 N일 이상 지난 것 반환.
    
    매일 cron 등에서 호출 → 각 종목 가격 받아와서 label_outcome() 호출.
    """
    init_db()
    cutoff = (datetime.now() - timedelta(days=min_days_old)).isoformat()
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM recommendations
            WHERE outcome_labeled_at IS NULL
              AND recommended_at < ?
            ORDER BY recommended_at""",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]


def label_outcome(
    rec_id: int,
    price_3d: Optional[float] = None,
    price_7d: Optional[float] = None,
    max_high_7d: Optional[float] = None,
    max_low_7d: Optional[float] = None,
) -> bool:
    """추천 결과 라벨링.
    
    Args:
        rec_id: recommendations.id
        price_3d: 추천 3거래일 후 종가
        price_7d: 추천 7거래일 후 종가
        max_high_7d: 7일 내 최고가 (목표가 도달 여부 판정용)
        max_low_7d: 7일 내 최저가 (손절가 도달 여부 판정용)
    """
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM recommendations WHERE id = ?", (rec_id,)).fetchone()
        if not row:
            return False
        entry = row["price"] or 0
        if entry <= 0:
            return False

        ret_3d = ((price_3d / entry - 1) * 100) if price_3d else None
        ret_7d = ((price_7d / entry - 1) * 100) if price_7d else None

        # 손절/목표 도달 여부
        hit_stop = 0
        hit_target = 0
        if row["stop_loss"] and max_low_7d and max_low_7d <= row["stop_loss"]:
            hit_stop = 1
        if row["take_profit"] and max_high_7d and max_high_7d >= row["take_profit"]:
            hit_target = 1

        c.execute(
            """UPDATE recommendations SET
                outcome_3d_price = ?, outcome_3d_return_pct = ?,
                outcome_7d_price = ?, outcome_7d_return_pct = ?,
                outcome_max_high_7d = ?, outcome_max_low_7d = ?,
                outcome_hit_stop = ?, outcome_hit_target = ?,
                outcome_labeled_at = ?
            WHERE id = ?""",
            (price_3d, ret_3d, price_7d, ret_7d,
             max_high_7d, max_low_7d, hit_stop, hit_target,
             datetime.now().isoformat(), rec_id),
        )
        return True


# ════════════════════════════════════════════════════════════
# 추천 시스템 적중률 통계 (NEW)
# ════════════════════════════════════════════════════════════
def get_calibration_stats(days_window: int = 90) -> Dict[str, Any]:
    """최근 N일 라벨링된 추천 결과 기반 통계.
    
    UI에 "최근 30건 추천 중 익절 X / 손절 Y" 표시용.
    """
    init_db()
    cutoff = (datetime.now() - timedelta(days=days_window)).isoformat()
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM recommendations
            WHERE outcome_labeled_at IS NOT NULL
              AND recommended_at >= ?""",
            (cutoff,)
        ).fetchall()

    if not rows:
        return {
            "total_labeled": 0,
            "hit_target_count": 0,
            "hit_stop_count": 0,
            "holding_count": 0,
            "avg_return_3d_pct": 0,
            "avg_return_7d_pct": 0,
            "win_rate_pct": 0,
            "by_grade": {},
        }

    rows = [dict(r) for r in rows]
    total = len(rows)
    hit_target = sum(1 for r in rows if r["outcome_hit_target"])
    hit_stop = sum(1 for r in rows if r["outcome_hit_stop"])
    holding = total - hit_target - hit_stop

    rets_3d = [r["outcome_3d_return_pct"] for r in rows if r["outcome_3d_return_pct"] is not None]
    rets_7d = [r["outcome_7d_return_pct"] for r in rows if r["outcome_7d_return_pct"] is not None]
    wins_7d = [r for r in rows if (r["outcome_7d_return_pct"] or 0) > 0]

    # 등급별 통계
    by_grade = {}
    for r in rows:
        g = r.get("grade", "unknown")
        if g not in by_grade:
            by_grade[g] = {"count": 0, "wins": 0, "avg_return": 0, "returns": []}
        by_grade[g]["count"] += 1
        if (r.get("outcome_7d_return_pct") or 0) > 0:
            by_grade[g]["wins"] += 1
        if r.get("outcome_7d_return_pct") is not None:
            by_grade[g]["returns"].append(r["outcome_7d_return_pct"])

    for g, v in by_grade.items():
        if v["returns"]:
            v["avg_return"] = round(sum(v["returns"]) / len(v["returns"]), 2)
            v["win_rate"] = round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0
        del v["returns"]

    return {
        "total_labeled": total,
        "hit_target_count": hit_target,
        "hit_stop_count": hit_stop,
        "holding_count": holding,
        "avg_return_3d_pct": round(sum(rets_3d) / len(rets_3d), 2) if rets_3d else 0,
        "avg_return_7d_pct": round(sum(rets_7d) / len(rets_7d), 2) if rets_7d else 0,
        "win_rate_pct": round(len(wins_7d) / len(rows) * 100, 1) if rows else 0,
        "by_grade": by_grade,
        "window_days": days_window,
    }


def get_agent_calibration() -> Dict[str, Dict[str, float]]:
    """각 에이전트별 점수와 실제 결과 상관관계 분석.
    
    데이터가 30건 이상 쌓이면 의미 있는 결과 반환.
    """
    init_db()
    with _conn() as c:
        rows = c.execute(
            """SELECT data_json, outcome_7d_return_pct
            FROM recommendations
            WHERE outcome_labeled_at IS NOT NULL
              AND outcome_7d_return_pct IS NOT NULL"""
        ).fetchall()

    if len(rows) < 10:
        return {"_message": f"라벨링 추천 {len(rows)}건 - 통계는 30건 이상부터 신뢰 가능"}

    # 각 에이전트 점수 vs 7일 수익률 상관관계
    agent_pairs = {agent: [] for agent in ["chart", "fundamental", "macro", "news", "supply", "risk"]}
    for r in rows:
        try:
            data = json.loads(r["data_json"])
            agents = data.get("agents", {})
            ret = r["outcome_7d_return_pct"]
            for agent_name in agent_pairs:
                if agent_name in agents:
                    sc = agents[agent_name].get("score")
                    if sc is not None:
                        agent_pairs[agent_name].append((sc, ret))
        except Exception:
            continue

    # 간단 상관계수 (Pearson)
    result = {}
    for agent, pairs in agent_pairs.items():
        if len(pairs) < 10:
            result[agent] = {"sample_size": len(pairs), "correlation": None}
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        n = len(pairs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
        den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
        corr = num / (den_x * den_y) if den_x and den_y else 0

        # 점수 80+ 추천의 평균 수익률
        high_score_rets = [y for x, y in pairs if x >= 70]
        avg_high = sum(high_score_rets) / len(high_score_rets) if high_score_rets else None

        result[agent] = {
            "sample_size": n,
            "correlation": round(corr, 3),
            "avg_return_when_high_score": round(avg_high, 2) if avg_high is not None else None,
        }

    return result


# ════════════════════════════════════════════════════════════
# 기존 함수들 (변경 없음)
# ════════════════════════════════════════════════════════════
def open_position(market, ticker, name, entry_price, stop_loss=None, take_profit=None):
    init_db()
    with _conn() as c:
        ex = c.execute("SELECT id FROM positions WHERE ticker = ?", (ticker,)).fetchone()
        if ex:
            return ex["id"]
        cur = c.execute(
            """INSERT INTO positions
            (opened_at, market, ticker, name, entry_price, stop_loss, take_profit)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(), market, ticker, name, entry_price, stop_loss, take_profit),
        )
        return cur.lastrowid


def close_position(ticker: str, exit_price: float) -> bool:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
        if not row:
            return False
        entry = row["entry_price"]
        rp = (exit_price / entry - 1) * 100 if entry else 0
        c.execute(
            """INSERT INTO closed_positions
            (opened_at, closed_at, market, ticker, name, entry_price, exit_price, return_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["opened_at"], datetime.now().isoformat(), row["market"],
             row["ticker"], row["name"], entry, exit_price, rp),
        )
        c.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
        return True


def get_open_positions() -> List[Dict]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_held_tickers() -> List[str]:
    return [p["ticker"] for p in get_open_positions()]


def get_closed_positions(limit: int = 50) -> List[Dict]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM closed_positions ORDER BY closed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> Dict[str, Any]:
    init_db()
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) c FROM recommendations").fetchone()["c"]
        op = c.execute("SELECT COUNT(*) c FROM positions").fetchone()["c"]
        cl = c.execute("SELECT * FROM closed_positions").fetchall()
        wins = [x for x in cl if (x["return_pct"] or 0) > 0]
        labeled = c.execute(
            "SELECT COUNT(*) c FROM recommendations WHERE outcome_labeled_at IS NOT NULL"
        ).fetchone()["c"]
        return {
            "total_recommendations": total,
            "labeled_recommendations": labeled,
            "open_positions": op,
            "closed_count": len(cl),
            "win_count": len(wins),
            "loss_count": len(cl) - len(wins),
            "win_rate_pct": round(len(wins) / len(cl) * 100, 1) if cl else 0,
            "avg_return_pct": round(sum(x["return_pct"] or 0 for x in cl) / len(cl), 2) if cl else 0,
        }
