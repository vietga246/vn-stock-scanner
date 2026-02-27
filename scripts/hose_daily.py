"""
hose_daily.py — Cập nhật giá hàng ngày (incremental).
Chạy mỗi ngày lúc 17:00 ICT qua GitHub Actions.
"""

from vnstock import Listing, Quote
from datetime import datetime, timedelta
from tqdm import tqdm
import time
import sqlite3
import pandas as pd
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH        = os.getenv("DB_PATH", "data/stock.db")
DAYS_LOOKBACK  = int(os.getenv("DAYS_LOOKBACK", "7"))   # buffer để không bỏ sót ngày
SLEEP_BETWEEN  = float(os.getenv("SLEEP_BETWEEN", "1.5"))


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock_prices (
            symbol  TEXT,
            date    TEXT,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  REAL,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_stock_prices_symbol ON stock_prices(symbol);
        CREATE INDEX IF NOT EXISTS idx_stock_prices_date   ON stock_prices(date);
    """)
    conn.commit()


def upsert_df(cursor: sqlite3.Cursor, ticker: str, df: pd.DataFrame):
    rows = [
        (
            ticker,
            str(row.get("time", "")),
            float(row.get("open", 0) or 0),
            float(row.get("high", 0) or 0),
            float(row.get("low",  0) or 0),
            float(row.get("close",0) or 0),
            int(row.get("volume", 0) or 0),
        )
        for _, row in df.iterrows()
    ]
    cursor.executemany(
        """INSERT OR REPLACE INTO stock_prices
           (symbol, date, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def update_daily():
    log.info("Bắt đầu cập nhật giá hàng ngày...")
    listing = Listing()
    all_symbols = listing.all_symbols()
    log.info(f"Các cột có sẵn: {all_symbols.columns.tolist()}")
    if "exchange" in all_symbols.columns:
        all_symbols = all_symbols[all_symbols["exchange"].str.upper() != "UPCOM"]
    elif "comGroupCode" in all_symbols.columns:
        all_symbols = all_symbols[all_symbols["comGroupCode"].str.upper() != "UPCOM"]
    tickers = all_symbols["symbol"].tolist()
    log.info(f"Tổng số mã: {len(tickers)}")

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str  = start_date.strftime("%Y-%m-%d")
    end_str    = end_date.strftime("%Y-%m-%d")
    log.info(f"Khoảng thời gian: {start_str} → {end_str}")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok, fail, skipped = 0, 0, 0
    for ticker in tqdm(tickers, desc="Cập nhật giá"):
        try:
            quote = Quote(symbol=ticker, source="VCI")
            df    = quote.history(start=start_str, end=end_str)
            if not df.empty:
                upsert_df(cursor, ticker, df)
                conn.commit()
                ok += 1
            else:
                skipped += 1
        except Exception as e:
            log.warning(f"[{ticker}] Lỗi: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info(f"Hoàn tất — OK: {ok}, Bỏ qua: {skipped}, Lỗi: {fail}")


if __name__ == "__main__":
    update_daily()
