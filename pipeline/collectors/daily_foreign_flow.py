"""
daily_foreign_flow.py — Foreign & Proprietary Trading Collector

Lấy dữ liệu giao dịch khối ngoại & tự doanh hàng ngày.
Chạy cùng daily_prices.py lúc 17:00 ICT.

Features:
- HOSE + HNX only, loại bỏ chứng quyền
- Adaptive rate limiter
- Incremental update (chỉ lấy từ ngày chưa có)
- Batch commit for performance
"""

from vnstock import Listing, Trading
from datetime import datetime, timedelta
from tqdm import tqdm
import sqlite3
import pandas as pd
import json
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
    """Initialize trading tables."""
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


def preload_last_dates(cursor, table: str) -> dict:
    """Get last date for each symbol in table."""
    cursor.execute(f"SELECT symbol, MAX(date) FROM {table} GROUP BY symbol")
    return {row[0]: row[1] for row in cursor.fetchall()}


def upsert_trading(cursor, table: str, symbol: str, df: pd.DataFrame):
    """Insert or replace trading data with normalized dates."""
    rows = []
    
    for row in df.itertuples(index=False):
        d = row._asdict()
        
        # Normalize date
        raw_date = d.get("date") or d.get("time")
        date_str = normalize_date(raw_date)
        
        if not date_str:
            continue
        
        # Extract values with multiple possible column names
        buy_vol  = safe_float(d.get("buy_volume",  d.get("buyVol", 0)))
        sell_vol = safe_float(d.get("sell_volume", d.get("sellVol", 0)))
        net_vol  = safe_float(d.get("net_volume",  d.get("netVol", 0)))
        buy_val  = safe_float(d.get("buy_value",   d.get("buyVal", 0)))
        sell_val = safe_float(d.get("sell_value",  d.get("sellVal", 0)))
        net_val  = safe_float(d.get("net_value",   d.get("netVal", 0)))
        
        # Store raw data as JSON for debugging
        data_json = json.dumps(
            {k: str(v) for k, v in d.items()},
            ensure_ascii=False
        )
        
        rows.append((
            symbol, date_str,
            buy_vol, sell_vol, net_vol,
            buy_val, sell_val, net_val,
            data_json
        ))
    
    if rows:
        cursor.executemany(f"""
            INSERT OR REPLACE INTO {table}
            (symbol, date, buy_volume, sell_volume, net_volume,
             buy_value, sell_value, net_value, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)


# ─── TICKERS ───────────────────────────────────────────────────────────────

def get_tickers() -> list:
    """Get HOSE + HNX symbols, excluding warrants."""
    listing = Listing()
    
    # Get warrant list
    try:
        warrants = set(listing.all_covered_warrant().tolist())
    except Exception:
        warrants = set()
    
    # Get exchange symbols
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = [t for t in df["symbol"].tolist() if t not in warrants]
            log.info("HOSE+HNX: %d symbols (excluded %d warrants)", 
                    len(tickers), len(warrants))
            return tickers
    except Exception as e:
        log.warning("symbols_by_exchange() failed: %s", e)
    
    # Fallback
    df = listing.all_symbols()
    return [t for t in df["symbol"].tolist() if t not in warrants]


# ─── MAIN ──────────────────────────────────────────────────────────────────

def fetch_foreign_trading():
    """Main function to fetch foreign and prop trading data."""
    
    # Setup API key
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")
    
    # Initialize
    tickers = get_tickers()
    limiter = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN, safety_ratio=0.9)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    log.info("Period: %s → %s", start_str, end_str)
    
    # Database connection
    conn = create_db_connection(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)
    
    # Preload existing dates for incremental update
    last_foreign = preload_last_dates(cursor, "foreign_trading")
    last_prop = preload_last_dates(cursor, "prop_trading")
    
    # Stats
    ok = fail = skipped = 0
    batch_counter = 0
    
    for symbol in tqdm(tickers, desc="Foreign trading"):
        retry = 0
        success = False
        
        while retry < MAX_RETRY:
            try:
                limiter.acquire()
                t = Trading(symbol=symbol, source="VCI")
                
                # Foreign trading
                try:
                    df_f = t.foreign_trade()
                    if df_f is not None and not df_f.empty:
                        upsert_trading(cursor, "foreign_trading", symbol, df_f)
                except Exception as e:
                    log.debug("[%s] foreign_trade error: %s", symbol, e)
                
                # Proprietary trading
                try:
                    df_p = t.prop_trade()
                    if df_p is not None and not df_p.empty:
                        upsert_trading(cursor, "prop_trading", symbol, df_p)
                except Exception as e:
                    log.debug("[%s] prop_trade error: %s", symbol, e)
                
                ok += 1
                batch_counter += 1
                success = True
                break
                
            except SystemExit:
                wait = 65
                log.warning("[%s] SystemExit → sleep %ds (retry %d/%d)",
                           symbol, wait, retry + 1, MAX_RETRY)
                import time
                time.sleep(wait)
                limiter.reset()
                retry += 1
                
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["429", "rate limit", "exceeded", "giới hạn"]):
                    wait = extract_wait_time(str(e))
                    log.warning("[%s] Rate limit → sleep %ds (retry %d/%d)",
                               symbol, wait, retry + 1, MAX_RETRY)
                    import time
                    time.sleep(wait)
                    limiter.reset()
                    retry += 1
                else:
                    log.warning("❌ %s — %s", symbol, e)
                    fail += 1
                    break
        
        if not success and retry >= MAX_RETRY:
            log.warning("[%s] Max retries reached — skipping", symbol)
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
    fetch_foreign_trading()
