"""
daily_prices.py — Daily OHLCV Price Updater

Cập nhật giá OHLCV hàng ngày cho HOSE + HNX.
Chạy mỗi ngày lúc 17:00 ICT qua GitHub Actions.

Features:
- HOSE + HNX only, loại bỏ trái phiếu
- Adaptive rate limiter (sliding window)
- Auto-detect server wait time
- Batch commit for performance
- WAL mode enabled
"""

from vnstock import Listing, Quote
from datetime import datetime, timedelta
from tqdm import tqdm
import sqlite3
import pandas as pd
import logging
import sys
import os

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
DAYS_LOOKBACK       = int(os.getenv("DAYS_LOOKBACK", "7"))
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
    
    # Fallback to all_symbols
    df = listing.all_symbols()
    tickers = [t for t in df["symbol"].tolist() if not is_bond(t)]
    log.warning("Fallback: %d symbols", len(tickers))
    return tickers


# ─── MAIN ──────────────────────────────────────────────────────────────────

def update_daily():
    """Main function to update daily prices."""
    
    # Setup API key
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (20 req/min)")
    
    # Initialize
    limiter = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN, safety_ratio=0.9)
    tickers = get_tickers()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    log.info("Period: %s → %s", start_str, end_str)
    
    # Database connection
    conn = create_db_connection(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)
    
    # Stats
    ok = fail = skipped = 0
    batch_counter = 0
    
    for ticker in tqdm(tickers, desc="Daily update"):
        retry = 0
        success = False
        
        while retry < MAX_RETRY:
            try:
                limiter.acquire()
                
                quote = Quote(symbol=ticker, source="VCI")
                df = quote.history(start=start_str, end=end_str)
                
                if df is not None and not df.empty:
                    upsert_df(cursor, ticker, df)
                    batch_counter += 1
                    ok += 1
                else:
                    skipped += 1
                
                success = True
                break
                
            except SystemExit:
                # vnstock calls sys.exit() on rate limit
                wait = 65
                log.warning("[%s] SystemExit (rate limit) → sleep %ds (retry %d/%d)",
                           ticker, wait, retry + 1, MAX_RETRY)
                import time
                time.sleep(wait)
                limiter.reset()
                retry += 1
                
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["429", "rate limit", "giới hạn", "exceeded"]):
                    wait = extract_wait_time(str(e), default=65)
                    log.warning("[%s] Rate limit → sleep %ds (retry %d/%d)",
                               ticker, wait, retry + 1, MAX_RETRY)
                    import time
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
    update_daily()
