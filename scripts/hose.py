"""
hose.py — High Performance Bootstrap Engine
- HOSE + HNX only
- True incremental (resume from last date)
- Rate-limit aware (60 req/min sliding window)
- Batch commit every 20 tickers
- WAL mode enabled
- Retry with exponential backoff
"""

from vnstock import Listing, Quote
from datetime import datetime, timedelta
from tqdm import tqdm
import sqlite3
import pandas as pd
import logging
import sys
import os
import time

# ---------------- CONFIG ---------------- #

DB_PATH             = os.getenv("DB_PATH", "data/stock.db")
API_KEY             = os.getenv("VNSTOCK_API_KEY", "")
START_DATE          = "2000-01-01"
MAX_REQUEST_PER_MIN = 60
MAX_RETRY           = 3
COMMIT_BATCH        = 20

# ---------------- LOGGING ---------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------- DB ---------------- #

def init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
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


def preload_last_dates(cursor):
    cursor.execute("SELECT symbol, MAX(date) FROM stock_prices GROUP BY symbol")
    return {row[0]: row[1] for row in cursor.fetchall()}


def upsert_df(cursor, ticker, df):
    rows = [
        (
            ticker,
            str(getattr(row, "time", getattr(row, "date", ""))),
            float(getattr(row, "open",   0) or 0),
            float(getattr(row, "high",   0) or 0),
            float(getattr(row, "low",    0) or 0),
            float(getattr(row, "close",  0) or 0),
            int(getattr(row,   "volume", 0) or 0),
        )
        for row in df.itertuples(index=False)
    ]
    cursor.executemany("""
        INSERT OR REPLACE INTO stock_prices
        (symbol, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)


def get_tickers():
    listing = Listing()
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = df["symbol"].tolist()
            log.info(f"HOSE+HNX: {len(tickers)} ma")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() loi: {e} — fallback all_symbols()")
    df = listing.all_symbols()
    return df["symbol"].tolist()


def rate_limit_check(request_count, window_start):
    request_count += 1
    if request_count >= MAX_REQUEST_PER_MIN:
        elapsed = time.time() - window_start
        if elapsed < 60:
            sleep_time = 60 - elapsed
            log.info(f"Rate window full -> sleep {sleep_time:.1f}s")
            time.sleep(sleep_time)
        return 0, time.time()
    return request_count, window_start


def fetch_all_history():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("Using API key")
    else:
        log.warning("Guest mode (20 req/min)")

    tickers  = get_tickers()
    end_date = datetime.now().strftime("%Y-%m-%d")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    last_dates    = preload_last_dates(cursor)
    ok = fail = skipped = 0
    request_count = 0
    window_start  = time.time()
    batch_counter = 0

    for ticker in tqdm(tickers, desc="Bootstrap prices"):

        last_date = last_dates.get(ticker)
        if last_date:
            start_date = (
                datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        else:
            start_date = START_DATE

        if start_date > end_date:
            skipped += 1
            continue

        retry   = 0
        success = False

        while retry < MAX_RETRY:
            try:
                request_count, window_start = rate_limit_check(request_count, window_start)
                quote = Quote(symbol=ticker, source="VCI")
                df    = quote.history(start=start_date, end=end_date)
                if df is not None and not df.empty:
                    upsert_df(cursor, ticker, df)
                    batch_counter += 1
                    ok += 1
                success = True
                break

            except SystemExit:
                wait = 2 ** retry * 10
                log.warning(f"[{ticker}] SystemExit rate limit -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                time.sleep(wait)
                retry += 1

            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate limit" in err or "exceeded" in err:
                    wait = 2 ** retry * 10
                    log.warning(f"[{ticker}] Rate limit -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                    time.sleep(wait)
                    retry += 1
                else:
                    log.warning(f"[{ticker}] Error: {e}")
                    fail += 1
                    break

        if not success and retry >= MAX_RETRY:
            log.warning(f"[{ticker}] Het retry — bo qua")
            fail += 1

        if batch_counter >= COMMIT_BATCH:
            conn.commit()
            batch_counter = 0

    conn.commit()
    conn.close()
    log.info(f"Done — OK: {ok}, Skipped: {skipped}, Failed: {fail}")


if __name__ == "__main__":
    fetch_all_history()
