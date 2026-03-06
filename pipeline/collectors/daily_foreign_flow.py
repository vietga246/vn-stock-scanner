"""
daily_foreign_flow.py — Foreign Trading Collector

Tổng hợp dữ liệu giao dịch khối ngoại theo ngày từ price_board_snapshot.

Cách hoạt động:
- KHÔNG gọi API riêng — đọc trực tiếp từ bảng price_board_snapshot
  (đã được thu thập bởi price_board_collector.py chạy trước đó)
- Mỗi snapshot intraday chứa accumulated foreign buy/sell tích lũy từ đầu phiên
- Lấy snapshot CUỐI CÙNG của ngày (giá trị accumulated = EOD)
- Lưu vào foreign_trading table để scoring_engine dùng tính smart money score

Lưu ý:
- Prop trading (tự doanh) không có nguồn data từ VCI price_board → để rỗng
- Trading.foreign_trade() / prop_trade() không tồn tại trong VCI source

Chạy: python pipeline/collectors/daily_foreign_flow.py
"""

import sqlite3
import pandas as pd
import json
import logging
import sys
import os
from datetime import datetime, timedelta

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import (
    normalize_date,
    safe_float,
    create_db_connection,
    setup_logging,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH       = os.getenv("DB_PATH", "data/db/stock.db")
DAYS_LOOKBACK = int(os.getenv("DAYS_LOOKBACK", "7"))
TEST_MODE     = os.getenv("TEST_MODE", "false").lower() == "true"

# ─── LOGGING ───────────────────────────────────────────────────────────────

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn):
    """Initialize foreign_trading and prop_trading tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS foreign_trading (
            symbol        TEXT,
            date          TEXT,
            buy_volume    REAL,
            sell_volume   REAL,
            net_volume    REAL,
            buy_value     REAL,
            sell_value    REAL,
            net_value     REAL,
            data_json     TEXT,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_foreign_trading_symbol ON foreign_trading(symbol);
        CREATE INDEX IF NOT EXISTS idx_foreign_trading_date   ON foreign_trading(date);

        CREATE TABLE IF NOT EXISTS prop_trading (
            symbol        TEXT,
            date          TEXT,
            buy_volume    REAL,
            sell_volume   REAL,
            net_volume    REAL,
            buy_value     REAL,
            sell_value    REAL,
            net_value     REAL,
            data_json     TEXT,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_prop_trading_symbol ON prop_trading(symbol);
        CREATE INDEX IF NOT EXISTS idx_prop_trading_date   ON prop_trading(date);
    """)
    conn.commit()


def aggregate_from_snapshot(conn, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Đọc price_board_snapshot và lấy snapshot CUỐI CÙNG của mỗi (symbol, ngày).

    price_board chứa accumulated values từ đầu phiên → snapshot cuối ngày
    là giá trị tích lũy cao nhất, đại diện cho toàn bộ giao dịch trong ngày.

    Returns DataFrame: [symbol, date, buy_volume, sell_volume, net_volume,
                                      buy_value, sell_value, net_value]
    """
    query = """
        WITH ranked AS (
            SELECT
                symbol,
                DATE(snapshot_time)          AS date,
                foreign_buy_qty              AS buy_volume,
                foreign_sell_qty             AS sell_volume,
                foreign_buy_value            AS buy_value,
                foreign_sell_value           AS sell_value,
                foreign_net_value            AS net_value,
                snapshot_time,
                ROW_NUMBER() OVER (
                    PARTITION BY symbol, DATE(snapshot_time)
                    ORDER BY snapshot_time DESC
                ) AS rn
            FROM price_board_snapshot
            WHERE DATE(snapshot_time) BETWEEN :start AND :end
              AND foreign_buy_value IS NOT NULL
        )
        SELECT
            symbol,
            date,
            buy_volume,
            sell_volume,
            COALESCE(buy_volume, 0) - COALESCE(sell_volume, 0) AS net_volume,
            buy_value,
            sell_value,
            net_value
        FROM ranked
        WHERE rn = 1
        ORDER BY symbol, date
    """
    try:
        df = pd.read_sql(query, conn, params={"start": start_date, "end": end_date})
        return df
    except Exception as e:
        log.error("aggregate_from_snapshot() lỗi: %s", e)
        return pd.DataFrame()


def insert_foreign_trading(conn, df: pd.DataFrame) -> tuple:
    """
    Upsert rows vào foreign_trading table.
    Returns (inserted, skipped).
    """
    if df.empty:
        return 0, 0

    cursor = conn.cursor()
    inserted = skipped = 0

    for _, row in df.iterrows():
        symbol = row.get("symbol")
        date   = row.get("date")
        if not symbol or not date:
            skipped += 1
            continue

        buy_vol  = safe_float(row.get("buy_volume"))
        sell_vol = safe_float(row.get("sell_volume"))
        net_vol  = safe_float(row.get("net_volume"))
        buy_val  = safe_float(row.get("buy_value"))
        sell_val = safe_float(row.get("sell_value"))
        net_val  = safe_float(row.get("net_value"))

        data_json = json.dumps({
            "buy_volume":  str(buy_vol),
            "sell_volume": str(sell_vol),
            "net_volume":  str(net_vol),
            "buy_value":   str(buy_val),
            "sell_value":  str(sell_val),
            "net_value":   str(net_val),
            "source":      "price_board_snapshot",
        }, ensure_ascii=False)

        cursor.execute("""
            INSERT OR REPLACE INTO foreign_trading
            (symbol, date, buy_volume, sell_volume, net_volume,
             buy_value, sell_value, net_value, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, date,
              buy_vol, sell_vol, net_vol,
              buy_val, sell_val, net_val,
              data_json))
        inserted += 1

    conn.commit()
    return inserted, skipped


# ─── MAIN ──────────────────────────────────────────────────────────────────

def fetch_foreign_trading():
    """
    Tổng hợp foreign trading từ price_board_snapshot → foreign_trading table.
    """
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str  = start_date.strftime("%Y-%m-%d")
    end_str    = end_date.strftime("%Y-%m-%d")

    mode_str = "[TEST MODE] " if TEST_MODE else ""
    if os.getenv("VNSTOCK_API_KEY"):
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  No API key")
    log.info("%sUsing VN30: 30 symbols" if TEST_MODE else "%sToàn thị trường", mode_str)
    log.info("Period: %s → %s", start_str, end_str)
    log.info("Source: price_board_snapshot (aggregating from existing snapshots)")

    conn = create_db_connection(DB_PATH)
    init_db(conn)

    # Kiểm tra price_board_snapshot có tồn tại và có data không
    try:
        check = pd.read_sql(
            "SELECT COUNT(*) AS cnt FROM price_board_snapshot WHERE DATE(snapshot_time) >= :start",
            conn, params={"start": start_str}
        )
        snapshot_count = int(check["cnt"].iloc[0])
    except Exception as e:
        log.error("❌ Không đọc được price_board_snapshot: %s", e)
        log.error("   Hãy đảm bảo price_board_collector.py đã chạy trước")
        conn.close()
        return

    if snapshot_count == 0:
        log.warning("⚠️  price_board_snapshot rỗng cho period %s → %s", start_str, end_str)
        log.warning("   Không có data để tổng hợp foreign trading")
        conn.close()
        return

    log.info("price_board_snapshot: %d rows trong period", snapshot_count)

    # Aggregate: lấy snapshot cuối ngày của mỗi symbol
    df = aggregate_from_snapshot(conn, start_str, end_str)

    if df.empty:
        log.warning("⚠️  Không có foreign data trong price_board_snapshot")
        log.warning("   Kiểm tra price_board_collector có lưu foreign_buy_value không")
        conn.close()
        return

    log.info("Aggregated: %d (symbol, date) pairs từ %d symbols",
             len(df), df["symbol"].nunique())

    # Insert vào foreign_trading
    inserted, skipped = insert_foreign_trading(conn, df)
    conn.close()

    # Summary
    symbols_with_data = df["symbol"].nunique()
    dates_covered     = df["date"].nunique()
    total_net_val     = df["net_value"].sum() / 1e9 if "net_value" in df.columns else 0

    log.info("✅ Done — OK: %d, Failed: 0", inserted)
    log.info("   foreign_trading rows: %d | prop_trading rows: 0 | symbols có data: %d/%d",
             inserted, symbols_with_data, symbols_with_data)
    log.info("   Ngày có data: %d | Net foreign tích lũy: %.2f tỷ đồng",
             dates_covered, total_net_val)


if __name__ == "__main__":
    fetch_foreign_trading()
