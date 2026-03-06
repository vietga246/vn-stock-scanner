"""
market_breadth_processor.py — Market Breadth Calculator

Tính các chỉ số bề rộng thị trường (market breadth) hàng ngày từ bảng stock_prices.

Chỉ số:
  - Advance / Decline / Unchanged count
  - Advance-Decline Line (A/D Line) — cumulative
  - % symbols above MA20, MA50
  - % symbols above previous close (ngày tăng)
  - New 52-week high / low count
  - Total market traded volume và value

Output: bảng market_breadth trong stock.db

Chạy sau technical_indicators.py vì cần MA20/MA50.
Chạy:
    python pipeline/processors/market_breadth_processor.py
    DAYS_LOOKBACK=30 python pipeline/processors/market_breadth_processor.py
"""

import sqlite3
import pandas as pd
import numpy as np
import logging
import sys
import os
from datetime import datetime, timedelta

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import safe_float, create_db_connection, setup_logging

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH      = os.getenv("DB_PATH",      "data/db/stock.db")
DAYS_LOOKBACK = int(os.getenv("DAYS_LOOKBACK", "30"))
# Số ngày tính lại — 1 = chỉ hôm nay, 30 = 30 ngày gần nhất

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_breadth (
            date                TEXT PRIMARY KEY,

            -- Advance / Decline
            advance             INTEGER,    -- số mã tăng giá
            decline             INTEGER,    -- số mã giảm giá
            unchanged           INTEGER,    -- số mã đứng giá
            total_symbols       INTEGER,    -- tổng số mã có data

            -- A/D Line (cumulative)
            ad_net              INTEGER,    -- advance - decline ngày đó
            ad_line             INTEGER,    -- cumulative sum

            -- % above moving averages (từ technical_indicators)
            pct_above_ma20      REAL,
            pct_above_ma50      REAL,

            -- New highs / lows (52 weeks)
            new_52w_high        INTEGER,
            new_52w_low         INTEGER,

            -- Market volume
            total_volume        REAL,       -- tổng KL toàn thị trường
            total_value         REAL,       -- tổng GT toàn thị trường

            -- Derived ratios
            advance_ratio       REAL,       -- advance / total_symbols
            adl_ratio           REAL        -- (advance - decline) / total_symbols
        );

        CREATE INDEX IF NOT EXISTS idx_market_breadth_date
            ON market_breadth(date DESC);
    """)
    conn.commit()
    log.info("✅ DB initialized — bảng market_breadth OK")


# ─── COMPUTE ───────────────────────────────────────────────────────────────

def compute_breadth_for_date(conn: sqlite3.Connection, date: str,
                              prev_ad_line: int = 0) -> dict | None:
    """
    Tính market breadth cho 1 ngày giao dịch cụ thể.
    Cần bảng stock_prices có ngày hôm trước để tính price_change.
    """

    # 1. Lấy giá ngày hiện tại và ngày hôm trước
    prices_today = pd.read_sql_query("""
        SELECT p.symbol, p.close, p.volume,
               p.high AS today_high, p.low AS today_low,
               p.low AS low_raw
        FROM stock_prices p
        WHERE p.date = ?
          AND p.close IS NOT NULL
    """, conn, params=(date,))

    if prices_today.empty:
        return None

    # Lấy giá ngày hôm trước để tính advance/decline
    prev_date_row = conn.execute("""
        SELECT DISTINCT date FROM stock_prices
        WHERE date < ?
        ORDER BY date DESC LIMIT 1
    """, (date,)).fetchone()

    if not prev_date_row:
        return None
    prev_date = prev_date_row[0]

    prices_prev = pd.read_sql_query("""
        SELECT symbol, close AS prev_close
        FROM stock_prices
        WHERE date = ? AND close IS NOT NULL
    """, conn, params=(prev_date,))

    if prices_prev.empty:
        return None

    # Merge
    merged = prices_today.merge(prices_prev, on="symbol", how="inner")
    merged["change"] = merged["close"] - merged["prev_close"]

    advance   = int((merged["change"] > 0).sum())
    decline   = int((merged["change"] < 0).sum())
    unchanged = int((merged["change"] == 0).sum())
    total     = len(merged)

    ad_net   = advance - decline
    ad_line  = prev_ad_line + ad_net

    # 2. % above MA20 / MA50 (từ technical_indicators)
    ma_data = pd.read_sql_query("""
        SELECT ti.symbol, ti.close, ti.ma20, ti.ma50
        FROM technical_indicators ti
        WHERE ti.date = ?
          AND ti.close IS NOT NULL
    """, conn, params=(date,))

    pct_above_ma20 = pct_above_ma50 = None
    if not ma_data.empty:
        with_ma20 = ma_data[ma_data["ma20"].notna()]
        if len(with_ma20) > 0:
            pct_above_ma20 = round(
                (with_ma20["close"] > with_ma20["ma20"]).sum() / len(with_ma20) * 100, 1
            )
        with_ma50 = ma_data[ma_data["ma50"].notna()]
        if len(with_ma50) > 0:
            pct_above_ma50 = round(
                (with_ma50["close"] > with_ma50["ma50"]).sum() / len(with_ma50) * 100, 1
            )

    # 3. New 52-week high / low
    year_ago = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")

    highs_lows = pd.read_sql_query("""
        SELECT symbol,
               MAX(high) AS high_52w,
               MIN(low)  AS low_52w
        FROM stock_prices
        WHERE date BETWEEN ? AND ?
          AND high IS NOT NULL AND low IS NOT NULL
        GROUP BY symbol
    """, conn, params=(year_ago, date))

    new_52w_high = new_52w_low = 0
    if not highs_lows.empty:
        # Join với giá hôm nay
        today_hl = prices_today[["symbol", "today_high", "today_low"]]
        hl_merged = highs_lows.merge(today_hl, on="symbol", how="inner")
        new_52w_high = int((hl_merged["today_high"] >= hl_merged["high_52w"]).sum())
        new_52w_low  = int((hl_merged["today_low"]  <= hl_merged["low_52w"]).sum())

    # 4. Total market volume & value
    total_volume = float(prices_today["volume"].sum())
    # Value: cần từ stock_prices nếu có cột value, nếu không ước tính
    value_row = conn.execute("""
        SELECT SUM(close * volume) FROM stock_prices WHERE date = ?
    """, (date,)).fetchone()
    total_value = safe_float(value_row[0]) if value_row else None

    return {
        "date":           date,
        "advance":        advance,
        "decline":        decline,
        "unchanged":      unchanged,
        "total_symbols":  total,
        "ad_net":         ad_net,
        "ad_line":        ad_line,
        "pct_above_ma20": pct_above_ma20,
        "pct_above_ma50": pct_above_ma50,
        "new_52w_high":   new_52w_high,
        "new_52w_low":    new_52w_low,
        "total_volume":   total_volume,
        "total_value":    total_value,
        "advance_ratio":  round(advance / total * 100, 1) if total > 0 else None,
        "adl_ratio":      round(ad_net / total * 100, 1)  if total > 0 else None,
    }


# ─── INSPECT ───────────────────────────────────────────────────────────────

def inspect(conn: sqlite3.Connection):
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  INSPECT — market_breadth")
    print(sep)

    total = conn.execute("SELECT COUNT(*) FROM market_breadth").fetchone()[0]
    print(f"  Tổng ngày có breadth data: {total}")

    # 10 ngày gần nhất
    recent = conn.execute("""
        SELECT date, advance, decline, unchanged,
               ad_net, ad_line,
               ROUND(pct_above_ma20, 1), ROUND(pct_above_ma50, 1),
               new_52w_high, new_52w_low,
               ROUND(advance_ratio, 1)
        FROM market_breadth
        ORDER BY date DESC
        LIMIT 10
    """).fetchall()

    if recent:
        print(f"\n  10 phiên gần nhất:")
        print(f"  {'Date':<12} {'Adv':>5} {'Dec':>5} {'Unch':>5} {'ADNet':>7} {'ADLine':>8} {'>MA20':>7} {'>MA50':>7} {'52Hi':>5} {'52Lo':>5} {'A%':>5}")
        print(f"  {'-'*12} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*8} {'-'*7} {'-'*7} {'-'*5} {'-'*5} {'-'*5}")
        for r in recent:
            ma20_str = f"{r[6]:.1f}" if r[6] is not None else "N/A"
            ma50_str = f"{r[7]:.1f}" if r[7] is not None else "N/A"
            print(f"  {r[0]:<12} {r[1]:>5} {r[2]:>5} {r[3]:>5} "
                  f"{r[4]:>+7} {r[5]:>8} "
                  f"{ma20_str:>7} {ma50_str:>7} "
                  f"{r[8]:>5} {r[9]:>5} {(r[10] or 0):>5.1f}")

    # Thống kê tổng hợp
    stats = conn.execute("""
        SELECT
            ROUND(AVG(pct_above_ma20), 1) AS avg_pct_above_ma20,
            ROUND(AVG(pct_above_ma50), 1) AS avg_pct_above_ma50,
            ROUND(AVG(advance_ratio), 1)  AS avg_advance_ratio,
            MAX(ad_line) AS max_adline,
            MIN(ad_line) AS min_adline,
            MAX(ad_line) - MIN(ad_line) AS adline_range
        FROM market_breadth
        WHERE date >= date('now', '-30 days')
    """).fetchone()
    if stats:
        print(f"\n  Thống kê 30 ngày gần nhất:")
        print(f"  Avg % above MA20 : {stats[0]}%")
        print(f"  Avg % above MA50 : {stats[1]}%")
        print(f"  Avg advance ratio: {stats[2]}%")
        print(f"  A/D Line range   : {stats[4]} → {stats[3]} (range: {stats[5]})")

    print(f"\n{sep}\n")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def compute_market_breadth():
    log.info("─" * 60)
    log.info("📊 Market Breadth Processor")
    log.info("   DAYS_LOOKBACK: %d", DAYS_LOOKBACK)
    log.info("─" * 60)

    if not os.path.exists(DB_PATH):
        log.error("❌ DB not found: %s", DB_PATH)
        sys.exit(1)

    conn = create_db_connection(DB_PATH)
    init_db(conn)

    # Lấy danh sách ngày cần tính
    start_date = (datetime.now() - timedelta(days=DAYS_LOOKBACK + 5)).strftime("%Y-%m-%d")
    dates = [r[0] for r in conn.execute("""
        SELECT DISTINCT date FROM stock_prices
        WHERE date >= ?
        ORDER BY date ASC
    """, (start_date,)).fetchall()]

    if not dates:
        log.warning("Không có ngày nào trong stock_prices từ %s", start_date)
        conn.close()
        return

    log.info("Tính breadth cho %d ngày: %s → %s", len(dates), dates[0], dates[-1])

    # Lấy ad_line cuối cùng trước khoảng thời gian này để làm baseline
    baseline_row = conn.execute("""
        SELECT ad_line FROM market_breadth
        WHERE date < ?
        ORDER BY date DESC LIMIT 1
    """, (dates[0],)).fetchone()
    baseline_ad_line = baseline_row[0] if baseline_row else 0

    ok = skipped = 0
    prev_ad_line = baseline_ad_line

    for date in dates:
        result = compute_breadth_for_date(conn, date, prev_ad_line)

        if result is None:
            skipped += 1
            continue

        conn.execute("""
            INSERT OR REPLACE INTO market_breadth (
                date, advance, decline, unchanged, total_symbols,
                ad_net, ad_line,
                pct_above_ma20, pct_above_ma50,
                new_52w_high, new_52w_low,
                total_volume, total_value,
                advance_ratio, adl_ratio
            ) VALUES (
                :date, :advance, :decline, :unchanged, :total_symbols,
                :ad_net, :ad_line,
                :pct_above_ma20, :pct_above_ma50,
                :new_52w_high, :new_52w_low,
                :total_volume, :total_value,
                :advance_ratio, :adl_ratio
            )
        """, result)

        prev_ad_line = result["ad_line"]
        ok += 1

    conn.commit()

    log.info("─" * 60)
    log.info("💾 Computed: %d dates | Skipped: %d", ok, skipped)
    log.info("─" * 60)

    inspect(conn)
    conn.close()


if __name__ == "__main__":
    compute_market_breadth()
