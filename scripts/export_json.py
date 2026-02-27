"""
export_json.py — Export dữ liệu từ SQLite sang JSON để Next.js trên Vercel đọc được.
Chạy sau mỗi lần cập nhật database.
"""

import sqlite3
import json
import os
import logging
import sys
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH      = os.getenv("DB_PATH", "data/stock.db")
EXPORT_DIR   = os.getenv("EXPORT_DIR", "data/exports")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))   # 6 tháng cho web


def export_latest_prices():
    """Export bảng giá gần nhất (6 tháng) ra JSON."""
    since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    conn  = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT sp.symbol, sp.date, sp.open, sp.high, sp.low, sp.close, sp.volume,
               s.short_name, s.exchange, s.industry, s.market_cap, s.pe, s.roe, s.beta
        FROM stock_prices sp
        LEFT JOIN symbols s ON s.symbol = sp.symbol
        WHERE sp.date >= ?
        ORDER BY sp.date DESC
    """, (since,))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    out_path = os.path.join(EXPORT_DIR, "prices.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "count": len(rows),
            "data": rows,
        }, f, ensure_ascii=False)

    log.info(f"Exported {len(rows)} rows → {out_path}")


def export_symbols():
    """Export bảng symbols ra JSON."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute("SELECT * FROM symbols ORDER BY market_cap DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    out_path = os.path.join(EXPORT_DIR, "symbols.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "count": len(rows),
            "data": rows,
        }, f, ensure_ascii=False)

    log.info(f"Exported {len(rows)} symbols → {out_path}")


def export_summary():
    """Export summary thống kê nhanh cho dashboard."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    # Lấy ngày giao dịch gần nhất
    cur.execute("SELECT MAX(date) as latest FROM stock_prices")
    latest_date = cur.fetchone()["latest"]

    # Top 10 tăng mạnh nhất trong ngày
    cur.execute("""
        WITH today AS (
            SELECT symbol, close, open
            FROM stock_prices WHERE date = ?
        )
        SELECT t.symbol, s.short_name, t.open, t.close,
               ROUND((t.close - t.open) / t.open * 100, 2) AS change_pct,
               s.market_cap, s.industry
        FROM today t
        LEFT JOIN symbols s ON s.symbol = t.symbol
        WHERE t.open > 0
        ORDER BY change_pct DESC LIMIT 10
    """, (latest_date,))
    top_gainers = [dict(r) for r in cur.fetchall()]

    # Top 10 giảm mạnh nhất
    cur.execute("""
        WITH today AS (
            SELECT symbol, close, open
            FROM stock_prices WHERE date = ?
        )
        SELECT t.symbol, s.short_name, t.open, t.close,
               ROUND((t.close - t.open) / t.open * 100, 2) AS change_pct,
               s.market_cap, s.industry
        FROM today t
        LEFT JOIN symbols s ON s.symbol = t.symbol
        WHERE t.open > 0
        ORDER BY change_pct ASC LIMIT 10
    """, (latest_date,))
    top_losers = [dict(r) for r in cur.fetchall()]

    # Top 10 khối lượng cao nhất
    cur.execute("""
        SELECT sp.symbol, s.short_name, sp.volume, sp.close, s.industry
        FROM stock_prices sp
        LEFT JOIN symbols s ON s.symbol = sp.symbol
        WHERE sp.date = ?
        ORDER BY sp.volume DESC LIMIT 10
    """, (latest_date,))
    top_volume = [dict(r) for r in cur.fetchall()]

    # Top 10 giá thấp nhất (lọc > 0)
    cur.execute("""
        SELECT sp.symbol, s.short_name, MIN(sp.low) AS min_price, s.industry
        FROM stock_prices sp
        LEFT JOIN symbols s ON s.symbol = sp.symbol
        WHERE sp.date >= date(?, '-90 days') AND sp.low > 0
        GROUP BY sp.symbol
        ORDER BY min_price ASC LIMIT 10
    """, (latest_date,))
    cheapest = [dict(r) for r in cur.fetchall()]

    conn.close()

    out_path = os.path.join(EXPORT_DIR, "summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "latest_date": latest_date,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "top_volume": top_volume,
            "cheapest_90d": cheapest,
        }, f, ensure_ascii=False)

    log.info(f"Exported summary → {out_path}")


if __name__ == "__main__":
    os.makedirs(EXPORT_DIR, exist_ok=True)
    export_symbols()
    export_latest_prices()
    export_summary()
    log.info("✅ Export hoàn tất!")
