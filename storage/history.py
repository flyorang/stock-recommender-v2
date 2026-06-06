"""
storage/history.py
SQLite 히스토리.
"""
import sqlite3
import json
from datetime import datetime
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
            data_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations(recommended_at);
        CREATE INDEX IF NOT EXISTS idx_rec_ticker ON recommendations(ticker);
        
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
        return {
            "total_recommendations": total,
            "open_positions": op,
            "closed_count": len(cl),
            "win_count": len(wins),
            "loss_count": len(cl) - len(wins),
            "win_rate_pct": round(len(wins) / len(cl) * 100, 1) if cl else 0,
            "avg_return_pct": round(sum(x["return_pct"] or 0 for x in cl) / len(cl), 2) if cl else 0,
        }
