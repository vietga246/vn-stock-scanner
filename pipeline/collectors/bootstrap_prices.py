"""
bootstrap_prices.py — Full History Price Loader

Tải toàn bộ lịch sử giá từ 2020 đến nay.
Chỉ chạy 1 lần khi setup, sau đó dùng daily_prices.py.

Features:
- HOSE + HNX only, loại bỏ trái phiếu
- True incremental (resume from last date)
- Adaptive rate limiter
- Batch commit for performance
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

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import (
    AdaptiveRateLimiter,
    normalize_date,
    safe_float,
    extract_wait_time,
    is_bond,
    create_db_connection,
    setup_logging,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH             = os.getenv("DB_PATH", "data/db/stock.db")
API_KEY             = os.getenv("VNSTOCK_API_KEY", "")
START_DATE          = "2020-01-01"  # Bootstrap from this date
MAX_REQUEST_PER_MIN = 60
MAX_RETRY           = 3
COMMIT_BATCH        = 20

# ─── LOGGING ───────────────────────────────────────────────────────────────

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn):
    """Initialize stock_prices table."""
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


def preload_last_dates(cursor) -> dict:
    """Get last date for each symbol to enable incremental loading."""
    cursor.execute("SELECT symbol, MAX(date) FROM stock_prices GROUP BY symbol")
    return {row[0]: row[1] for row in cursor.fetchall()}


def upsert_df(cursor, ticker: str, df: pd.DataFrame):
    """Insert or replace price data with normalized dates."""
    rows = []
    
    for row in df.itertuples(index=False):
        # Get date from 'time' or 'date' column
        raw_date = getattr(row, "time", None) or getattr(row, "date", None)
        date_str = normalize_date(raw_date)
        
        if not date_str:
            continue
            
        rows.append((
            ticker,
            date_str,
            safe_float(getattr(row, "open", 0)),
            safe_float(getattr(row, "high", 0)),
            safe_float(getattr(row, "low", 0)),
            safe_float(getattr(row, "close", 0)),
            safe_float(getattr(row, "volume", 0)),
        ))
    
    if rows:
        cursor.executemany("""
            INSERT OR REPLACE INTO stock_prices
            (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)


# ─── TICKERS ───────────────────────────────────────────────────────────────

def get_tickers() -> list:
    """Get HOSE + HNX symbols, excluding bonds and UPCOM."""
    listing = Listing()
    
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = df["symbol"].tolist()
            
            # Filter out bonds
            before = len(tickers)
            tickers = [t for t in tickers if not is_bond(t)]
            
            log.info("HOSE+HNX: %d symbols (excluded UPCOM + %d bonds)", 
                    len(tickers), before - len(tickers))
            return tickers
            
    except Exception as e:
        log.warning("symbols_by_exchange() failed: %s — using fallback", e)
    
    # Fallback
    df = listing.all_symbols()
    tickers = [t for t in df["symbol"].tolist() if not is_bond(t)]
    log.warning("Fallback: %d symbols", len(tickers))
    return tickers


# ─── MAIN ──────────────────────────────────────────────────────────────────

def fetch_all_history():
    """Main function to bootstrap full price history."""
    
    # Setup API key
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (20 req/min)")
    
    # Initialize
    limiter = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN, safety_ratio=0.9)
    tickers = get_tickers()
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # Database connection
    conn = create_db_connection(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)
    
    # Get existing data for incremental loading
    last_dates = preload_last_dates(cursor)
    log.info("Found existing data for %d symbols", len(last_dates))
    
    # Stats
    ok = fail = skipped = 0
    batch_counter = 0
    
    for ticker in tqdm(tickers, desc="Bootstrap prices"):
        
        # Determine start date (incremental)
        last_date = last_dates.get(ticker)
        if last_date:
            # Start from day after last date
            start_date = (
                datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        else:
            start_date = START_DATE
        
        # Skip if already up to date
        if start_date > end_date:
            skipped += 1
            continue
        
        retry = 0
        success = False
        
        while retry < MAX_RETRY:
            try:
                limiter.acquire()
                
                quote = Quote(symbol=ticker, source="VCI")
                df = quote.history(start=start_date, end=end_date)
                
                if df is not None and not df.empty:
                    upsert_df(cursor, ticker, df)
                    batch_counter += 1
                    ok += 1
                    log.debug("[%s] Loaded %d rows (%s → %s)", 
                             ticker, len(df), start_date, end_date)
                
                success = True
                break
                
            except SystemExit:
                # vnstock calls sys.exit() on rate limit
                wait = 65
                log.warning("[%s] SystemExit (rate limit) → sleep %ds (retry %d/%d)",
                           ticker, wait, retry + 1, MAX_RETRY)
                time.sleep(wait)
                limiter.reset()
                retry += 1
                
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["429", "rate limit", "giới hạn", "exceeded"]):
                    wait = extract_wait_time(str(e), default=65)
                    log.warning("[%s] Rate limit → sleep %ds (retry %d/%d)",
                               ticker, wait, retry + 1, MAX_RETRY)
                    time.sleep(wait)
                    limiter.reset()
                    retry += 1
                else:
                    log.warning("[%s] Error: %s", ticker, e)
                    fail += 1
                    break
        
        if not success and retry >= MAX_RETRY:
            log.warning("[%s] Max retries reached — skipping", ticker)
            fail += 1
        
        # Batch commit
        if batch_counter >= COMMIT_BATCH:
            conn.commit()
            batch_counter = 0
    
    # Final commit and close
    conn.commit()
    conn.close()
    
    log.info("✅ Done — OK: %d, Skipped: %d, Failed: %d", ok, skipped, fail)


if __name__ == "__main__":
    fetch_all_history()
