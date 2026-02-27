"""
export_json.py — Export dữ liệu từ SQLite sang JSON để Next.js trên Vercel đọc được.
Chạy sau mỗi lần cập nhật database.

Schema symbols mới:
  symbol, organ_name, en_organ_name, exchange, type,
  industry_code, industry_name, updated_at
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

DB_PATH       = os.getenv("DB_PATH", "data/stock.db")
EXPORT_DIR    = os.getenv("EXPORT_DIR", "data/exports")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))


def table_exists(cur, table_name: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cur.fetchone() is not None


def export_symbols():
    """Export bảng symbols ra JSON."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    if not table_exists(cur, "symbols"):
        log.warning("⚠️  Bảng symbols chưa tồn tại — bỏ qua export_symbols")
        conn.close()
        return

    cur.execute("SELECT * FROM symbols ORDER BY symbol ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    out_path = os.path.join(EXPORT_DIR, "symbols.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "count": len(rows),
            "data": rows,
        }, f, ensure_ascii=False)

    log.info(f"✅ Exported {len(rows)} symbols → {out_path}")


def export_latest_prices():
    """Export bảng giá gần nhất (6 tháng) ra JSON."""
    since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    conn  = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur   = conn.cursor()

    if not table_exists(cur, "stock_prices"):
        log.warning("⚠️  Bảng stock_prices chưa tồn tại — bỏ qua export_latest_prices")
        conn.close()
        return

    if table_exists(cur, "symbols"):
        cur.execute("""
            SELECT sp.symbol, sp.date, sp.open, sp.high, sp.low, sp.close, sp.volume,
                   s.organ_name, s.en_organ_name, s.exchange, s.industry_name
            FROM stock_prices sp
            LEFT JOIN symbols s ON s.symbol = sp.symbol
            WHERE sp.date >= ?
            ORDER BY sp.date DESC
        """, (since,))
    else:
        cur.execute("""
            SELECT symbol, date, open, high, low, close, volume
            FROM stock_prices
            WHERE date >= ?
            ORDER BY date DESC
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

    log.info(f"✅ Exported {len(rows)} rows → {out_path}")


def export_summary():
    """Export summary thống kê nhanh cho dashboard."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    if not table_exists(cur, "stock_prices"):
        log.warning("⚠️  Bảng stock_prices chưa tồn tại — bỏ qua export_summary")
        conn.close()
        return

    has_symbols = table_exists(cur, "symbols")

    cur.execute("SELECT MAX(date) as latest FROM stock_prices")
    row = cur.fetchone()
    latest_date = row["latest"] if row else None

    if not latest_date:
        log.warning("⚠️  Không có dữ liệu giá — bỏ qua export_summary")
        conn.close()
        return

    # Tuỳ có bảng symbols hay không
    if has_symbols:
        join_sym    = "LEFT JOIN symbols s ON s.symbol = t.symbol"
        join_sym_sp = "LEFT JOIN symbols s ON s.symbol = sp.symbol"
        sel_sym     = "s.organ_name, s.industry_name"
    else:
        join_sym    = ""
        join_sym_sp = ""
        sel_sym     = "NULL AS organ_name, NULL AS industry_name"

    # Top 10 tăng mạnh nhất
    cur.execute(f"""
        WITH today AS (
            SELECT symbol, close, open
            FROM stock_prices WHERE date = ?
        )
        SELECT t.symbol, {sel_sym}, t.open, t.close,
               ROUND((t.close - t.open) / t.open * 100, 2) AS change_pct
        FROM today t
        {join_sym}
        WHERE t.open > 0
        ORDER BY change_pct DESC LIMIT 10
    """, (latest_date,))
    top_gainers = [dict(r) for r in cur.fetchall()]

    # Top 10 giảm mạnh nhất
    cur.execute(f"""
        WITH today AS (
            SELECT symbol, close, open
            FROM stock_prices WHERE date = ?
        )
        SELECT t.symbol, {sel_sym}, t.open, t.close,
               ROUND((t.close - t.open) / t.open * 100, 2) AS change_pct
        FROM today t
        {join_sym}
        WHERE t.open > 0
        ORDER BY change_pct ASC LIMIT 10
    """, (latest_date,))
    top_losers = [dict(r) for r in cur.fetchall()]

    # Top 10 khối lượng cao nhất
    cur.execute(f"""
        SELECT sp.symbol, {sel_sym}, sp.volume, sp.close
        FROM stock_prices sp
        {join_sym_sp}
        WHERE sp.date = ?
        ORDER BY sp.volume DESC LIMIT 10
    """, (latest_date,))
    top_volume = [dict(r) for r in cur.fetchall()]

    # Top 10 giá thấp nhất 90 ngày
    cur.execute(f"""
        SELECT sp.symbol, {sel_sym}, MIN(sp.low) AS min_price
        FROM stock_prices sp
        {join_sym_sp}
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

    log.info(f"✅ Exported summary → {out_path}")


if __name__ == "__main__":
    os.makedirs(EXPORT_DIR, exist_ok=True)
    export_symbols()
    export_latest_prices()
    export_summary()
    log.info("✅ Export hoàn tất!")
