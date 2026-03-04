"""
daily_foreign_flow.py — Foreign & Proprietary Trading Collector

Lấy dữ liệu giao dịch khối ngoại & tự doanh hàng ngày.
Chạy cùng daily_prices.py lúc 17:00 ICT.

Features:
- HOSE + HNX only, loại bỏ chứng quyền + trái phiếu
- Multi-threaded với 4 workers (staggered 1s)
- Thread-safe adaptive rate limiter
- Queue-based DB writes (tránh SQLite lock)
- TEST_MODE: chỉ chạy VN30 để test nhanh
"""

from vnstock import Listing, Trading
from datetime import datetime, timedelta
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from queue import Queue
import sqlite3
import pandas as pd
import json
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
DAYS_LOOKBACK       = int(os.getenv("DAYS_LOOKBACK", "7"))
MAX_REQUEST_PER_MIN = 60
MAX_RETRY           = 3
COMMIT_BATCH        = 20
NUM_WORKERS         = int(os.getenv("NUM_WORKERS", "4"))        # 4 workers parallel
TEST_MODE           = os.getenv("TEST_MODE", "false").lower() == "true"
WORKER_STAGGER_SEC  = int(os.getenv("WORKER_STAGGER_SEC", "1")) # 1s giữa các worker

# VN30 symbols for testing
VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

# ─── LOGGING ───────────────────────────────────────────────────────────────

log = setup_logging()

# ─── THREAD-SAFE RATE LIMITER ──────────────────────────────────────────────

class ThreadSafeRateLimiter:
    """Thread-safe rate limiter using sliding window."""
    
    def __init__(self, max_requests_per_min: int, safety_ratio: float = 0.85):
        self.max_rpm = int(max_requests_per_min * safety_ratio)
        self.window = 60.0  # 1 minute window
        self.requests = []
        self.lock = Lock()
    
    def acquire(self):
        """Wait if necessary, then record a request."""
        with self.lock:
            now = time.time()
            # Remove old requests outside window
            self.requests = [t for t in self.requests if now - t < self.window]
            
            if len(self.requests) >= self.max_rpm:
                # Need to wait
                oldest = self.requests[0]
                wait_time = self.window - (now - oldest) + 0.1
                if wait_time > 0:
                    log.debug("Rate limit: sleeping %.1fs", wait_time)
                    time.sleep(wait_time)
                    now = time.time()
                    self.requests = [t for t in self.requests if now - t < self.window]
            
            self.requests.append(now)
    
    def reset(self):
        """Reset after hitting rate limit error."""
        with self.lock:
            self.requests = []


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


def prepare_trading_rows(symbol: str, df: pd.DataFrame) -> list:
    """Prepare rows for insertion (thread-safe, no DB access)."""
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
    
    return rows


def batch_insert(cursor, table: str, rows: list):
    """Insert rows into table."""
    if rows:
        cursor.executemany(f"""
            INSERT OR REPLACE INTO {table}
            (symbol, date, buy_volume, sell_volume, net_volume,
             buy_value, sell_value, net_value, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)


# ─── TICKERS ───────────────────────────────────────────────────────────────

def get_tickers() -> list:
    """Get HOSE + HNX symbols, excluding warrants and bonds.
    
    In TEST_MODE, returns only VN30 symbols.
    """
    # TEST MODE: Only VN30
    if TEST_MODE:
        log.info("[TEST MODE] Using VN30: %d symbols", len(VN30_SYMBOLS))
        return VN30_SYMBOLS.copy()
    
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
            all_symbols = df["symbol"].tolist()
            
            # Filter out warrants AND bonds
            before = len(all_symbols)
            tickers = [t for t in all_symbols if t not in warrants and not is_bond(t)]
            
            excluded_warrants = len([t for t in all_symbols if t in warrants])
            excluded_bonds = before - excluded_warrants - len(tickers)
            
            log.info("HOSE+HNX: %d symbols (excluded %d warrants + %d bonds)", 
                    len(tickers), excluded_warrants, excluded_bonds)
            return tickers
    except Exception as e:
        log.warning("symbols_by_exchange() failed: %s", e)
    
    # Fallback
    df = listing.all_symbols()
    return [t for t in df["symbol"].tolist() if t not in warrants and not is_bond(t)]


# ─── WORKER FUNCTION ───────────────────────────────────────────────────────

def fetch_symbol_data(symbol: str, limiter: ThreadSafeRateLimiter) -> dict:
    """
    Fetch foreign and prop trading data for a single symbol.
    Returns dict with results (thread-safe, no DB writes).
    """
    result = {
        'symbol': symbol,
        'status': 'ok',
        'foreign_rows': [],
        'prop_rows': [],
        'error': None
    }
    
    retry = 0
    while retry < MAX_RETRY:
        try:
            limiter.acquire()
            t = Trading(symbol=symbol, source="VCI")
            
            # Foreign trading
            try:
                df_f = t.foreign_trade()
                if df_f is not None and not df_f.empty:
                    result['foreign_rows'] = prepare_trading_rows(symbol, df_f)
            except Exception as e:
                log.debug("[%s] foreign_trade error: %s", symbol, e)
            
            # Proprietary trading
            try:
                df_p = t.prop_trade()
                if df_p is not None and not df_p.empty:
                    result['prop_rows'] = prepare_trading_rows(symbol, df_p)
            except Exception as e:
                log.debug("[%s] prop_trade error: %s", symbol, e)
            
            return result
            
        except SystemExit:
            wait = 65
            log.warning("[%s] SystemExit → sleep %ds (retry %d/%d)",
                       symbol, wait, retry + 1, MAX_RETRY)
            time.sleep(wait)
            limiter.reset()
            retry += 1
            
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["429", "rate limit", "exceeded", "giới hạn"]):
                wait = extract_wait_time(str(e))
                log.warning("[%s] Rate limit → sleep %ds (retry %d/%d)",
                           symbol, wait, retry + 1, MAX_RETRY)
                time.sleep(wait)
                limiter.reset()
                retry += 1
            else:
                log.warning("❌ %s — %s", symbol, e)
                result['status'] = 'failed'
                result['error'] = str(e)
                return result
    
    # Max retries reached
    log.warning("[%s] Max retries reached — skipping", symbol)
    result['status'] = 'failed'
    result['error'] = 'max_retries'
    return result


# ─── MAIN ──────────────────────────────────────────────────────────────────

def fetch_foreign_trading():
    """Main function to fetch foreign and prop trading data with multi-threading."""
    
    # Setup API key
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")
    
    # Initialize
    tickers = get_tickers()
    limiter = ThreadSafeRateLimiter(MAX_REQUEST_PER_MIN, safety_ratio=0.85)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    log.info("Period: %s → %s", start_str, end_str)
    
    mode_str = "[TEST MODE] " if TEST_MODE else ""
    log.info("%sWorkers: %d | Rate limit: %d RPM | Stagger: %ds", 
             mode_str, NUM_WORKERS, MAX_REQUEST_PER_MIN, WORKER_STAGGER_SEC)
    
    # Database connection (main thread only)
    conn = create_db_connection(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)
    
    # Split tickers into chunks for each worker
    num_workers = min(NUM_WORKERS, len(tickers))
    chunk_size = len(tickers) // num_workers + 1
    ticker_chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    
    log.info("Split %d symbols into %d chunks", len(tickers), len(ticker_chunks))
    
    # Stats
    ok = fail = 0
    batch_counter = 0
    
    def worker_task(worker_id: int, symbols: list):
        """Worker task with staggered start."""
        # Stagger start
        if worker_id > 0:
            wait_time = worker_id * WORKER_STAGGER_SEC
            log.info("Worker %d: waiting %ds before start...", worker_id, wait_time)
            time.sleep(wait_time)
        
        log.info("Worker %d: starting with %d symbols", worker_id, len(symbols))
        
        results = []
        for i, symbol in enumerate(symbols, 1):
            result = fetch_symbol_data(symbol, limiter)
            results.append(result)
            
            # Log progress every symbol
            status = "✓" if result['status'] == 'ok' else "✗"
            log.info("Worker %d: [%d/%d] %s %s", 
                    worker_id, i, len(symbols), symbol, status)
        
        log.info("Worker %d: completed", worker_id)
        return results
    
    # Process with thread pool
    all_results = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit tasks with worker IDs
        futures = {
            executor.submit(worker_task, i, chunk): i 
            for i, chunk in enumerate(ticker_chunks)
        }
        
        # Process results as workers complete
        for future in as_completed(futures):
            worker_id = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                log.error("Worker %d error: %s", worker_id, e)
    
    # Write all results to DB (single thread)
    log.info("Writing %d results to database...", len(all_results))
    
    for result in all_results:
        if result['status'] == 'ok':
            if result['foreign_rows']:
                batch_insert(cursor, "foreign_trading", result['foreign_rows'])
            if result['prop_rows']:
                batch_insert(cursor, "prop_trading", result['prop_rows'])
            ok += 1
            batch_counter += 1
        else:
            fail += 1
        
        # Batch commit
        if batch_counter >= COMMIT_BATCH:
            conn.commit()
            batch_counter = 0
    
    # Final commit and close
    conn.commit()
    conn.close()
    
    log.info("✅ Done — OK: %d, Failed: %d", ok, fail)


if __name__ == "__main__":
    fetch_foreign_trading()
