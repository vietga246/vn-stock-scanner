"""
hose_daily.py — High Performance Daily Updater (Adaptive + Production)

- HOSE + HNX only, loại bỏ trái phiếu
- Adaptive sliding-window rate limiter (deque-based)
- Auto-detect server wait time (VI + EN)
- Catch SystemExit từ vnstock
- Batch commit every 20 tickers
- WAL mode enabled
- Chạy mỗi ngày lúc 17:00 ICT qua GitHub Actions
"""

from vnstock import Listing, Quote
from datetime import datetime, timedelta
from tqdm import tqdm
from collections import deque
import sqlite3
import pandas as pd
import logging
import sys
import os
import time
import re

# ---------------- CONFIG ---------------- #

DB_PATH             = os.getenv("DB_PATH", "data/stock.db")
API_KEY             = os.getenv("VNSTOCK_API_KEY", "")
DAYS_LOOKBACK       = int(os.getenv("DAYS_LOOKBACK", "7"))
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

# ---------------- ADAPTIVE RATE LIMITER ---------------- #

class AdaptiveRateLimiter:
    def __init__(self, rpm: int, safety_ratio: float = 0.9):
        self.rpm       = rpm
        self.threshold = int(rpm * safety_ratio)
        self.window    = 60
        self.requests  = deque()

    def acquire(self):
        now = time.time()

        while self.requests and now - self.requests[0] > self.window:
            self.requests.popleft()

        current = len(self.requests)

        if current >= self.rpm:
            sleep_time = self.window - (now - self.requests[0]) + 0.1
            log.info(f"[Limiter] Hard limit -> sleep {sleep_time:.2f}s")
            time.sleep(sleep_time)
            return self.acquire()

        if current >= self.threshold:
            overload      = current - self.threshold
            dynamic_delay = overload * (60 / self.rpm)
            time.sleep(dynamic_delay)

        self.requests.append(time.time())

    def reset(self):
        self.requests.clear()

# ---------------- WAIT TIME PARSER ---------------- #

def extract_wait_time(error_message: str, default: int = 60) -> int:
    if not error_message:
        return default

    patterns = [
        r"chờ\s+(\d+)\s*gi",
        r"wait\s+(\d+)\s*second",
        r"retry\s*after\s*(\d+)",
        r"(\d+)\s*second",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_message.lower())
        if match:
            return int(match.group(1)) + 1

    return default

# ---------------- BOND FILTER ---------------- #

BOND_PATTERN = re.compile(r'^[A-Z]{2,4}\d{4,}$')

def is_bond(symbol: str) -> bool:
    return bool(BOND_PATTERN.match(symbol)) and len(symbol) > 6

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


def upsert_df(cursor, ticker: str, df: pd.DataFrame):
    rows = [
        (
            ticker,
            str(getattr(row, "time",   getattr(row, "date", ""))),
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

# ---------------- TICKERS ---------------- #

def get_tickers() -> list:
    listing = Listing()
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df      = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = df["symbol"].tolist()
            before  = len(tickers)
            tickers = [t for t in tickers if not is_bond(t)]
            log.info(f"HOSE+HNX: {len(tickers)} mã (bỏ UPCOM + {before - len(tickers)} trái phiếu)")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() lỗi: {e} — fallback all_symbols()")

    df      = listing.all_symbols()
    tickers = [t for t in df["symbol"].tolist() if not is_bond(t)]
    log.warning(f"Fallback: {len(tickers)} mã")
    return tickers

# ---------------- MAIN ---------------- #

def update_daily():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (20 req/min)")

    limiter    = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN, safety_ratio=0.9)
    tickers    = get_tickers()
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str  = start_date.strftime("%Y-%m-%d")
    end_str    = end_date.strftime("%Y-%m-%d")
    log.info(f"Period: {start_str} -> {end_str}")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok = fail = skipped = 0
    batch_counter = 0

    for ticker in tqdm(tickers, desc="Daily update"):
        retry   = 0
        success = False

        while retry < MAX_RETRY:
            try:
                limiter.acquire()

                quote = Quote(symbol=ticker, source="VCI")
                df    = quote.history(start=start_str, end=end_str)

                if df is not None and not df.empty:
                    upsert_df(cursor, ticker, df)
                    batch_counter += 1
                    ok += 1
                else:
                    skipped += 1

                success = True
                break

            except SystemExit:
                wait = 65
                log.warning(f"[{ticker}] SystemExit (rate limit) -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                time.sleep(wait)
                limiter.reset()
                retry += 1

            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["429", "rate limit", "giới hạn", "exceeded"]):
                    wait = extract_wait_time(str(e), default=65)
                    log.warning(f"[{ticker}] Rate limit -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                    time.sleep(wait)
                    limiter.reset()
                    retry += 1
                else:
                    log.warning(f"[{ticker}] Error: {e}")
                    fail += 1
                    break

        if not success and retry >= MAX_RETRY:
            log.warning(f"[{ticker}] Hết retry — bỏ qua")
            fail += 1

        if batch_counter >= COMMIT_BATCH:
            conn.commit()
            batch_counter = 0

    conn.commit()
    conn.close()
    log.info(f"✅ Done — OK: {ok}, Skipped: {skipped}, Failed: {fail}")


if __name__ == "__main__":
    update_daily()
