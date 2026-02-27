"""
hose_daily.py — Cập nhật giá hàng ngày (incremental).
- Chỉ lấy HOSE + HNX (bỏ UPCOM)
- Chạy mỗi ngày lúc 17:00 ICT qua GitHub Actions
- Retry tự động khi bị rate limit
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

DB_PATH       = os.getenv("DB_PATH", "data/stock.db")
DAYS_LOOKBACK = int(os.getenv("DAYS_LOOKBACK", "7"))
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "3"))
API_KEY       = os.getenv("VNSTOCK_API_KEY", "")
MAX_RETRY     = 3


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


def get_tickers():
    """Lấy danh sách mã chỉ HOSE + HNX, bỏ UPCOM."""
    listing = Listing()
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = df["symbol"].tolist()
            log.info(f"HOSE+HNX: {len(tickers)} mã (đã bỏ UPCOM)")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() thất bại: {e} — dùng all_symbols()")

    # Fallback
    df = listing.all_symbols()
    tickers = df["symbol"].tolist()
    log.warning(f"Dùng all_symbols(): {len(tickers)} mã (bao gồm cả UPCOM)")
    return tickers


def update_daily():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Sử dụng API key từ environment")
    else:
        log.warning("⚠️  Không có API key — dùng gói Guest (20 req/phút)")

    tickers    = get_tickers()
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
        retry = 0
        while retry < MAX_RETRY:
            try:
                quote = Quote(symbol=ticker, source="VCI")
                df    = quote.history(start=start_str, end=end_str)
                if not df.empty:
                    upsert_df(cursor, ticker, df)
                    conn.commit()
                    ok += 1
                else:
                    skipped += 1
                break

            except Exception as e:
                err = str(e)
                if "Rate Limit" in err or "rate limit" in err.lower() or "429" in err:
                    wait = 60
                    log.warning(f"[{ticker}] Rate limit — chờ {wait}s (lần {retry+1}/{MAX_RETRY})...")
                    time.sleep(wait)
                    retry += 1
                else:
                    log.warning(f"[{ticker}] Lỗi: {e}")
                    fail += 1
                    break

        time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info(f"Hoàn tất — OK: {ok}, Bỏ qua: {skipped}, Lỗi: {fail}")


if __name__ == "__main__":
    update_daily()
