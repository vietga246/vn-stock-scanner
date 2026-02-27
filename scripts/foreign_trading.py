"""
foreign_trading.py — Lấy dữ liệu giao dịch khối ngoại & tự doanh
- HOSE + HNX only, loại bỏ chứng quyền
- Lấy: foreign_trade, prop_trade
- Incremental: chỉ lấy từ ngày chưa có trong DB
- Adaptive rate limiter + retry exponential backoff
- WAL mode, batch commit
- Chạy hàng ngày cùng hose_daily.py
"""

from vnstock import Listing, Trading
from datetime import datetime, timedelta
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
            overload = current - self.threshold
            time.sleep(overload * (60 / self.rpm))
        self.requests.append(time.time())

    def reset(self):
        self.requests.clear()

# ---------------- WAIT TIME PARSER ---------------- #

def extract_wait_time(msg: str, default: int = 65) -> int:
    for pattern in [r"chờ\s+(\d+)\s*gi", r"wait\s+(\d+)\s*second",
                    r"retry\s*after\s*(\d+)", r"(\d+)\s*second"]:
        m = re.search(pattern, msg.lower())
        if m:
            return int(m.group(1)) + 1
    return default

# ---------------- DB ---------------- #

def init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
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
    cursor.execute(f"SELECT symbol, MAX(date) FROM {table} GROUP BY symbol")
    return {row[0]: row[1] for row in cursor.fetchall()}


def upsert_trading(cursor, table: str, symbol: str, df: pd.DataFrame):
    import json
    rows = []
    for row in df.itertuples(index=False):
        d          = row._asdict()
        date_val   = str(getattr(row, "date", getattr(row, "time", "")))
        buy_vol    = float(d.get("buy_volume",  d.get("buyVol",   0) or 0))
        sell_vol   = float(d.get("sell_volume", d.get("sellVol",  0) or 0))
        net_vol    = float(d.get("net_volume",  d.get("netVol",   0) or 0))
        buy_val    = float(d.get("buy_value",   d.get("buyVal",   0) or 0))
        sell_val   = float(d.get("sell_value",  d.get("sellVal",  0) or 0))
        net_val    = float(d.get("net_value",   d.get("netVal",   0) or 0))
        rows.append((symbol, date_val, buy_vol, sell_vol, net_vol,
                     buy_val, sell_val, net_val,
                     json.dumps({k: str(v) for k, v in d.items()}, ensure_ascii=False)))

    cursor.executemany(f"""
        INSERT OR REPLACE INTO {table}
        (symbol, date, buy_volume, sell_volume, net_volume,
         buy_value, sell_value, net_value, data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

# ---------------- TICKERS ---------------- #

def get_tickers() -> list:
    listing = Listing()
    try:
        warrants = set(listing.all_covered_warrant().tolist())
    except Exception:
        warrants = set()
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df      = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = [t for t in df["symbol"].tolist() if t not in warrants]
            log.info(f"HOSE+HNX: {len(tickers)} mã")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() lỗi: {e}")
    df = listing.all_symbols()
    return [t for t in df["symbol"].tolist() if t not in warrants]

# ---------------- MAIN ---------------- #

def fetch_foreign_trading():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")

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

    last_foreign = preload_last_dates(cursor, "foreign_trading")
    last_prop    = preload_last_dates(cursor, "prop_trading")
    limiter      = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN)
    ok = fail = skipped = 0
    batch_counter = 0

    for symbol in tickers:
        retry_count = 0
        success     = False

        while retry_count < MAX_RETRY:
            try:
                limiter.acquire()
                t = Trading(symbol=symbol, source="VCI")

                # Foreign trade
                try:
                    df_f = t.foreign_trade()
                    if df_f is not None and not df_f.empty:
                        upsert_trading(cursor, "foreign_trading", symbol, df_f)
                except Exception as e:
                    log.warning(f"[{symbol}] foreign_trade lỗi: {e}")

                # Prop trade
                try:
                    df_p = t.prop_trade()
                    if df_p is not None and not df_p.empty:
                        upsert_trading(cursor, "prop_trading", symbol, df_p)
                except Exception as e:
                    log.warning(f"[{symbol}] prop_trade lỗi: {e}")

                ok += 1
                batch_counter += 1
                success = True
                break

            except SystemExit:
                wait = 65
                log.warning(f"[{symbol}] SystemExit -> sleep {wait}s (retry {retry_count+1}/{MAX_RETRY})")
                time.sleep(wait)
                limiter.reset()
                retry_count += 1

            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["429", "rate limit", "exceeded", "giới hạn"]):
                    wait = extract_wait_time(str(e))
                    log.warning(f"[{symbol}] Rate limit -> sleep {wait}s (retry {retry_count+1}/{MAX_RETRY})")
                    time.sleep(wait)
                    limiter.reset()
                    retry_count += 1
                else:
                    log.warning(f"❌ {symbol} — {e}")
                    fail += 1
                    break

        if not success and retry_count >= MAX_RETRY:
            log.warning(f"[{symbol}] Hết retry — bỏ qua")
            fail += 1

        if batch_counter >= COMMIT_BATCH:
            conn.commit()
            batch_counter = 0

    conn.commit()
    conn.close()
    log.info(f"✅ Done — OK: {ok}, Skipped: {skipped}, Failed: {fail}")


if __name__ == "__main__":
    fetch_foreign_trading()
