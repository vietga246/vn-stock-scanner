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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH       = os.getenv("DB_PATH", "data/stock.db")
START_DATE    = "2000-01-01"
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "3"))
API_KEY       = os.getenv("VNSTOCK_API_KEY", "")


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
            float(row.get("open",   0) or 0),
            float(row.get("high",   0) or 0),
            float(row.get("low",    0) or 0),
            float(row.get("close",  0) or 0),
            int(row.get("volume",   0) or 0),
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
    # Set API key nếu có
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Sử dụng API key từ environment")
    else:
        log.warning("⚠️  Không có API key — dùng gói Guest (giới hạn 20 req/phút)")

    log.info("Lấy danh sách tất cả mã cổ phiếu...")
    listing = Listing()
    all_symbols = listing.all_symbols()
    all_symbols = all_symbols[all_symbols["exchange"].str.upper() != "UPCOM"]
    tickers = all_symbols["symbol"].tolist()
    log.info(f"Tổng số mã: {len(tickers)}")

    end_date = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok, fail = 0, 0
    for ticker in tqdm(tickers, desc="Tải lịch sử giá"):
        retry = 0
        while retry < 3:
            try:
                quote = Quote(symbol=ticker, source="VCI")
                df    = quote.history(start=START_DATE, end=end_date)
                if not df.empty:
                    upsert_df(cursor, ticker, df)
                    conn.commit()
                    ok += 1
                break  # thành công, thoát vòng retry

            except Exception as e:
                err = str(e)
                if "Rate Limit" in err or "rate limit" in err.lower() or "429" in err:
                    wait = 60
                    log.warning(f"[{ticker}] Rate limit — chờ {wait}s rồi thử lại...")
                    time.sleep(wait)
                    retry += 1
                else:
                    log.warning(f"[{ticker}] Lỗi: {e}")
                    fail += 1
                    break

        time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info(f"Hoàn tất — OK: {ok}, Lỗi: {fail}")


if __name__ == "__main__":
    fetch_all_history()
