"""
hose.py — Tải toàn bộ lịch sử giá từ năm 2000 đến nay cho tất cả mã cổ phiếu.
Chạy 1 lần duy nhất để khởi tạo database.
"""

from vnstock import Listing, Quote
from datetime import datetime
from tqdm import tqdm
import time
import sqlite3
import pandas as pd
import logging
import sys
import os

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/stock.db")
START_DATE = "2000-01-01"
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "1.5"))


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


def fetch_all_history():
    log.info("Lấy danh sách tất cả mã cổ phiếu...")
    listing  = Listing()
    tickers  = listing.all_symbols()["symbol"].tolist()
    log.info(f"Tổng số mã: {len(tickers)}")

    end_date = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok, fail = 0, 0
    for ticker in tqdm(tickers, desc="Tải lịch sử giá"):
        try:
            quote = Quote(symbol=ticker, source="VCI")
            df    = quote.history(start=START_DATE, end=end_date)
            if not df.empty:
                upsert_df(cursor, ticker, df)
                conn.commit()
                ok += 1
        except Exception as e:
            log.warning(f"[{ticker}] Lỗi: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info(f"Hoàn tất — OK: {ok}, Lỗi: {fail}")


if __name__ == "__main__":
    fetch_all_history()
