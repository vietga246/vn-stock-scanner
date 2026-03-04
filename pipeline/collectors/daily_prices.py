"""
daily_prices.py — Daily OHLCV Price Updater (Multi-Worker)

Cập nhật giá OHLCV hàng ngày cho HOSE + HNX.
Chạy mỗi ngày lúc 17:00 ICT qua GitHub Actions.

Features:
- HOSE + HNX only, loại bỏ trái phiếu
- 3 workers chạy parallel, cách nhau 2s
- Global rate limiter (thread-safe)
- Auto-detect server wait time
- Batch commit for performance
- WAL mode enabled
- TEST_MODE: chỉ chạy VN30 để test nhanh
"""

from vnstock import Listing, Quote
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3
import pandas as pd
import threading
import logging
import time
import sys
import os
import re

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import (
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
MAX_WORKERS         = int(os.getenv("MAX_WORKERS", "3"))      # 3 workers parallel
WORKER_STAGGER_SEC  = float(os.getenv("WORKER_STAGGER", "1")) # 2s giữa các request
MAX_RETRY           = 3
COMMIT_BATCH        = 20
TEST_MODE           = os.getenv("TEST_MODE", "false").lower() == "true"

# VN30 symbols for testing
VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

# ─── LOGGING ───────────────────────────────────────────────────────────────

log = setup_logging()


# ─── RATE LIMITER (Thread-Safe) ────────────────────────────────────────────

class StaggeredRateLimiter:
    """
    Thread-safe rate limiter với khoảng cách cố định giữa các request.
    3 workers chạy parallel nhưng mỗi request cách nhau ít nhất STAGGER seconds.
    """
    
    def __init__(self, stagger_seconds: float = 2.0):
        self.stagger = stagger_seconds
        self.lock = threading.Lock()
        self.last_request = 0.0
        self.pause_until = 0.0
        self._server_wait = None
    
    def acquire(self):
        """Chờ đến khi có thể gửi request tiếp theo."""
        while True:
            with self.lock:
                now = time.time()
                
                # Đang trong cooldown period (rate limit từ server)
                if now < self.pause_until:
                    sleep_time = self.pause_until - now
                else:
                    # Tính thời điểm được phép request tiếp
                    next_allowed = self.last_request + self.stagger
                    if now >= next_allowed:
                        self.last_request = now
                        return
                    sleep_time = next_allowed - now
            
            # Sleep bên ngoài lock
            self._chunked_sleep(sleep_time)
    
    def _chunked_sleep(self, seconds: float, chunk: float = 10.0):
        """Sleep theo chunk để GitHub Actions không kill process."""
        remaining = seconds
        while remaining > 0:
            t = min(chunk, remaining)
            time.sleep(t)
            remaining -= t
    
    def set_server_wait(self, seconds: int):
        """Gọi khi detect wait time từ server."""
        with self.lock:
            self._server_wait = seconds
    
    def trigger_cooldown(self, fallback: int = 65) -> int:
        """Trigger global cooldown khi bị rate limit."""
        with self.lock:
            now = time.time()
            seconds = self._server_wait if self._server_wait else fallback
            new_pause = now + seconds
            
            if new_pause > self.pause_until:
                self.pause_until = new_pause
                self.last_request = new_pause
                log.info("Global cooldown: %ds", seconds)
            
            self._server_wait = None
            return seconds
    
    def reset(self):
        """Reset limiter state."""
        with self.lock:
            self.pause_until = 0.0
            self.last_request = 0.0
            self._server_wait = None


# Global limiter instance
limiter = StaggeredRateLimiter(WORKER_STAGGER_SEC)


# ─── STDOUT CAPTURE (detect server wait time) ──────────────────────────────

class WaitTimeCapture:
    """Capture stdout để detect wait time từ vnstock rate limit message."""
    
    def __init__(self, real_stdout):
        self._real = real_stdout
    
    def write(self, s):
        self._real.write(s)
        # Match "Chờ 56 giây" hoặc "Cho 4 giay"
        m = re.search(r'Ch[oờ]\s*(\d+)\s*gi[aâ]y', s)
        if m:
            wait = int(m.group(1)) + 5  # +5 buffer
            limiter.set_server_wait(wait)
    
    def flush(self):
        self._real.flush()
    
    def __getattr__(self, name):
        return getattr(self._real, name)


sys.stdout = WaitTimeCapture(sys.stdout)


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


# ─── TICKERS ───────────────────────────────────────────────────────────────

def get_tickers() -> list:
    """Get HOSE + HNX symbols, excluding bonds and UPCOM."""
    if TEST_MODE:
        log.info("[TEST MODE] Using VN30: %d symbols", len(VN30_SYMBOLS))
        return VN30_SYMBOLS.copy()
    
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


# ─── FETCH WORKER ──────────────────────────────────────────────────────────

def fetch_ticker(ticker: str, start_str: str, end_str: str) -> dict:
    """
    Fetch price data cho 1 ticker.
    Chạy trong worker thread, trả về dict với data hoặc error.
    """
    retry = 0
    
    while retry < MAX_RETRY:
        try:
            limiter.acquire()
            
            quote = Quote(symbol=ticker, source="VCI")
            df = quote.history(start=start_str, end=end_str)
            
            if df is not None and not df.empty:
                # Convert DataFrame to list of tuples
                rows = []
                for row in df.itertuples(index=False):
                    raw_date = getattr(row, "time", None) or getattr(row, "date", None)
                    date_str = normalize_date(raw_date)
                    
                    if date_str:
                        rows.append((
                            ticker,
                            date_str,
                            safe_float(getattr(row, "open", 0)),
                            safe_float(getattr(row, "high", 0)),
                            safe_float(getattr(row, "low", 0)),
                            safe_float(getattr(row, "close", 0)),
                            safe_float(getattr(row, "volume", 0)),
                        ))
                
                return {"symbol": ticker, "status": "ok", "rows": rows}
            else:
                return {"symbol": ticker, "status": "empty", "rows": []}
                
        except SystemExit:
            # vnstock calls sys.exit() on rate limit
            wait = limiter.trigger_cooldown(65)
            log.warning("[%s] SystemExit (rate limit) → cooldown %ds (retry %d/%d)",
                       ticker, wait, retry + 1, MAX_RETRY)
            time.sleep(wait)
            retry += 1
            
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["429", "rate limit", "giới hạn", "exceeded"]):
                wait = limiter.trigger_cooldown(extract_wait_time(str(e), default=65))
                log.warning("[%s] Rate limit → cooldown %ds (retry %d/%d)",
                           ticker, wait, retry + 1, MAX_RETRY)
                time.sleep(wait)
                retry += 1
            else:
                log.warning("[%s] Error: %s", ticker, e)
                return {"symbol": ticker, "status": "error", "error": str(e), "rows": []}
    
    return {"symbol": ticker, "status": "max_retry", "rows": []}


# ─── MAIN ──────────────────────────────────────────────────────────────────

def update_daily():
    """Main function to update daily prices with multi-worker."""
    
    # Setup API key
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (rate limited)")
    
    # Get tickers
    tickers = get_tickers()
    
    # Date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_LOOKBACK)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    log.info("Period: %s → %s", start_str, end_str)
    
    mode_str = "[TEST MODE] " if TEST_MODE else ""
    log.info("%sTotal symbols: %d", mode_str, len(tickers))
    log.info("Workers: %d | Stagger: %.1fs | Batch commit: %d", 
             MAX_WORKERS, WORKER_STAGGER_SEC, COMMIT_BATCH)
    
    # Database connection (main thread only for writes)
    conn = create_db_connection(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)
    
    # Split tickers into chunks for each worker
    num_workers = min(MAX_WORKERS, len(tickers))
    chunk_size = len(tickers) // num_workers + 1
    ticker_chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    
    log.info("Split %d symbols into %d chunks", len(tickers), len(ticker_chunks))
    
    # Stats (thread-safe)
    stats_lock = threading.Lock()
    stats = {"ok": 0, "fail": 0, "skipped": 0}
    results_queue = []
    
    def worker_task(worker_id: int, symbols: list):
        """Worker task with staggered start and detailed logging."""
        # Stagger start
        if worker_id > 0:
            wait_time = worker_id * WORKER_STAGGER_SEC
            log.info("Worker %d: waiting %.1fs before start...", worker_id, wait_time)
            time.sleep(wait_time)
        
        log.info("Worker %d: starting with %d symbols", worker_id, len(symbols))
        
        worker_results = []
        for i, symbol in enumerate(symbols, 1):
            result = fetch_ticker(symbol, start_str, end_str)
            worker_results.append(result)
            
            # Log progress for each symbol
            status_icon = "✓" if result['status'] == 'ok' else ("○" if result['status'] == 'empty' else "✗")
            log.info("Worker %d: [%d/%d] %s %s", worker_id, i, len(symbols), symbol, status_icon)
        
        log.info("Worker %d: completed", worker_id)
        return worker_results
    
    # Process with thread pool
    all_results = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(worker_task, i, chunk): i 
            for i, chunk in enumerate(ticker_chunks)
        }
        
        for future in as_completed(futures):
            worker_id = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                log.error("Worker %d error: %s", worker_id, e)
    
    # Write all results to DB (single thread)
    log.info("Writing %d results to database...", len(all_results))
    batch_counter = 0
    
    for result in all_results:
        status = result.get("status")
        rows = result.get("rows", [])
        symbol = result.get("symbol")
        
        if status == "ok" and rows:
            cursor.executemany("""
                INSERT OR REPLACE INTO stock_prices
                (symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)
            stats["ok"] += 1
            batch_counter += 1
        elif status == "empty":
            stats["skipped"] += 1
        else:
            stats["fail"] += 1
        
        # Batch commit
        if batch_counter >= COMMIT_BATCH:
            conn.commit()
            batch_counter = 0
    
    # Final commit and close
    conn.commit()
    conn.close()
    
    log.info("✅ Done — OK: %d, Skipped: %d, Failed: %d", 
             stats["ok"], stats["skipped"], stats["fail"])


if __name__ == "__main__":
    update_daily()
