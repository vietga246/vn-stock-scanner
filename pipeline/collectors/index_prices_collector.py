"""
index_prices_collector.py — Index Price History Collector

Thu thập lịch sử giá OHLCV cho các chỉ số thị trường:
  VNINDEX, VN30, HNX30, UPCOM (nếu có)

Features:
- Lưu vào bảng index_prices (symbol, date, open, high, low, close, volume)
- DAYS_LOOKBACK: mặc định 7 ngày (daily collect), 365 ngày (bootstrap)
- Skip nếu đã có data của ngày đó (idempotent)
- Inspect log sau khi collect

Chạy:
    python pipeline/collectors/index_prices_collector.py
    DAYS_LOOKBACK=365 python pipeline/collectors/index_prices_collector.py
"""

from vnstock import Quote
from datetime import datetime, timedelta
import sqlite3
import logging
import sys
import os
import time

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import (
    normalize_date,
    safe_float,
    safe_int,
    create_db_connection,
    setup_logging,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH      = os.getenv("DB_PATH",      "data/db/stock.db")
DAYS_LOOKBACK = int(os.getenv("DAYS_LOOKBACK", "7"))
API_KEY      = os.getenv("VNSTOCK_API_KEY", "")

# Danh sách index cần thu thập (UPCOM không hỗ trợ bởi VCI API)
INDEX_SYMBOLS = ["VNINDEX", "VN30", "HNX30"]

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS index_prices (
            symbol   TEXT,
            date     TEXT,
            open     REAL,
            high     REAL,
            low      REAL,
            close    REAL,
            volume   REAL,
            PRIMARY KEY (symbol, date)
        );

        CREATE INDEX IF NOT EXISTS idx_index_prices_symbol
            ON index_prices(symbol);
        CREATE INDEX IF NOT EXISTS idx_index_prices_date
            ON index_prices(date);
    """)
    conn.commit()
    log.info("✅ DB initialized — bảng index_prices OK")


# ─── FETCH ─────────────────────────────────────────────────────────────────

def fetch_index(symbol: str, start: str, end: str) -> list[dict]:
    """
    Lấy lịch sử OHLCV cho 1 chỉ số.
    Trả về list dict: [{symbol, date, open, high, low, close, volume}, ...]
    """
    try:
        quote = Quote(symbol=symbol, source="VCI")
        df = quote.history(start=start, end=end)

        if df is None or df.empty:
            log.warning("[%s] Empty response", symbol)
            return []

        rows = []
        for _, row in df.iterrows():
            d = row.to_dict()
            # vnstock có thể trả về 'time' hoặc 'date'
            raw_date = d.get("time") or d.get("date") or d.get("Date") or d.get("Time")
            date_str = normalize_date(raw_date)
            if not date_str:
                continue

            rows.append({
                "symbol": symbol,
                "date":   date_str,
                "open":   safe_float(d.get("open")   or d.get("Open")),
                "high":   safe_float(d.get("high")   or d.get("High")),
                "low":    safe_float(d.get("low")    or d.get("Low")),
                "close":  safe_float(d.get("close")  or d.get("Close")),
                "volume": safe_float(d.get("volume") or d.get("Volume")),
            })

        log.info("[%s] Fetched %d rows (start=%s, end=%s)", symbol, len(rows), start, end)
        return rows

    except Exception as e:
        log.error("[%s] Fetch failed: %s", symbol, e)
        return []


# ─── INSPECT ───────────────────────────────────────────────────────────────

def inspect(conn: sqlite3.Connection):
    """In inspect log sau khi collect."""
    sep = "=" * 65

    print(f"\n{sep}")
    print(f"  INSPECT — index_prices")
    print(sep)

    # Row count per symbol
    rows = conn.execute("""
        SELECT symbol,
               COUNT(*) AS rows,
               MIN(date) AS from_date,
               MAX(date) AS to_date
        FROM index_prices
        GROUP BY symbol
        ORDER BY symbol
    """).fetchall()

    if not rows:
        print("  (empty)")
    else:
        print(f"  {'Symbol':<12} {'Rows':>6}  {'From':<12} {'To':<12}")
        print(f"  {'-'*12} {'-'*6}  {'-'*12} {'-'*12}")
        for r in rows:
            print(f"  {r[0]:<12} {r[1]:>6}  {r[2]:<12} {r[3]:<12}")

    # 5 ngày gần nhất của VNINDEX
    recent = conn.execute("""
        SELECT date, open, high, low, close, volume
        FROM index_prices
        WHERE symbol = 'VNINDEX'
        ORDER BY date DESC
        LIMIT 5
    """).fetchall()

    if recent:
        print(f"\n  VNINDEX — 5 phiên gần nhất:")
        print(f"  {'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>14}")
        print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*14}")
        for r in recent:
            print(f"  {r[0]:<12} {r[1]:>10,.2f} {r[2]:>10,.2f} {r[3]:>10,.2f} {r[4]:>10,.2f} {r[5]:>14,.0f}")

    # 5 ngày gần nhất VN30
    recent30 = conn.execute("""
        SELECT date, close,
               ROUND((close - LAG(close) OVER (ORDER BY date)) /
                     LAG(close) OVER (ORDER BY date) * 100, 2) AS chg_pct
        FROM index_prices
        WHERE symbol = 'VN30'
        ORDER BY date DESC
        LIMIT 5
    """).fetchall()

    if recent30:
        print(f"\n  VN30 — 5 phiên gần nhất:")
        print(f"  {'Date':<12} {'Close':>10} {'Chg%':>8}")
        print(f"  {'-'*12} {'-'*10} {'-'*8}")
        for r in recent30:
            chg = f"{r[2]:+.2f}%" if r[2] is not None else "N/A"
            print(f"  {r[0]:<12} {r[1]:>10,.2f} {chg:>8}")

    print(f"\n{sep}\n")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def collect_index_prices():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (no API key)")

    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=DAYS_LOOKBACK + 3)).strftime("%Y-%m-%d")
    # +3 để đảm bảo có data dù API bỏ qua ngày cuối tuần

    log.info("─" * 60)
    log.info("📈 Index Prices Collector")
    log.info("   Symbols: %s", INDEX_SYMBOLS)
    log.info("   Period : %s → %s (%d days lookback)", start_date, end_date, DAYS_LOOKBACK)
    log.info("─" * 60)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = create_db_connection(DB_PATH)
    init_db(conn)

    total_inserted = 0
    total_skipped  = 0

    for symbol in INDEX_SYMBOLS:
        rows = fetch_index(symbol, start_date, end_date)
        if not rows:
            log.warning("[%s] Không có dữ liệu — bỏ qua", symbol)
            time.sleep(1)
            continue

        inserted = 0
        skipped  = 0
        for row in rows:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO index_prices
                        (symbol, date, open, high, low, close, volume)
                    VALUES
                        (:symbol, :date, :open, :high, :low, :close, :volume)
                """, row)
                if conn.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                log.warning("[%s] Insert error: %s", symbol, e)
                skipped += 1

        conn.commit()
        log.info("[%s] ✅ Inserted: %d | Skipped (already exist): %d",
                 symbol, inserted, skipped)
        total_inserted += inserted
        total_skipped  += skipped

        time.sleep(0.5)   # nhẹ nhàng giữa các index

    log.info("─" * 60)
    log.info("💾 TOTAL — Inserted: %d | Skipped: %d", total_inserted, total_skipped)
    log.info("─" * 60)

    inspect(conn)
    conn.close()


if __name__ == "__main__":
    collect_index_prices()
