"""
insider_deals.py — Lấy dữ liệu giao dịch nội bộ (insider deals)
- HOSE + HNX only, loại bỏ chứng quyền
- Skip mã đã cập nhật trong 7 ngày
- Adaptive rate limiter + retry exponential backoff
- WAL mode, batch commit
- Chạy hàng tuần cùng symbol.py
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

# tenacity là dependency của vnstock — import để catch RetryError đúng cách
try:
    from tenacity import RetryError as TenacityRetryError
except ImportError:
    TenacityRetryError = None

# ---------------- CONFIG ---------------- #

DB_PATH              = os.getenv("DB_PATH", "data/db/stock.db")
API_KEY              = os.getenv("VNSTOCK_API_KEY", "")
MAX_REQUEST_PER_MIN  = 60
MAX_RETRY            = 3
COMMIT_BATCH         = 20
SKIP_IF_UPDATED_DAYS = 7
TEST_MODE            = os.getenv("TEST_MODE", "false").lower() == "true"

VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

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
        CREATE TABLE IF NOT EXISTS insider_deals (
            symbol          TEXT,
            deal_announce_date TEXT,
            deal_action     TEXT,
            deal_quantity   REAL,
            deal_price      REAL,
            deal_ratio      REAL,
            trader_name     TEXT,
            trader_position TEXT,
            data_json       TEXT,
            PRIMARY KEY (symbol, deal_announce_date, trader_name, deal_action)
        );
        CREATE INDEX IF NOT EXISTS idx_insider_symbol ON insider_deals(symbol);
        CREATE INDEX IF NOT EXISTS idx_insider_date   ON insider_deals(deal_announce_date);

        CREATE TABLE IF NOT EXISTS insider_meta (
            symbol     TEXT PRIMARY KEY,
            updated_at TEXT
        );
    """)
    conn.commit()


def preload_updated_at(cursor) -> dict:
    cursor.execute("SELECT symbol, updated_at FROM insider_meta")
    return {row[0]: row[1] for row in cursor.fetchall()}


def should_skip(updated_at_map: dict, symbol: str) -> bool:
    updated_at = updated_at_map.get(symbol)
    if updated_at:
        cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
        return updated_at >= cutoff
    return False


def upsert_insider(cursor, symbol: str, df: pd.DataFrame):
    import json
    rows = []
    for row in df.itertuples(index=False):
        d = row._asdict()
        rows.append((
            symbol,
            str(d.get("deal_announce_date", d.get("announceDate", ""))),
            str(d.get("deal_action",        d.get("action",       ""))),
            float(d.get("deal_quantity",    d.get("quantity",      0) or 0)),
            float(d.get("deal_price",       d.get("price",         0) or 0)),
            float(d.get("deal_ratio",       d.get("ratio",         0) or 0)),
            str(d.get("trader_name",        d.get("traderName",    ""))),
            str(d.get("trader_position",    d.get("position",      ""))),
            json.dumps({k: str(v) for k, v in d.items()}, ensure_ascii=False),
        ))

    cursor.executemany("""
        INSERT OR REPLACE INTO insider_deals
        (symbol, deal_announce_date, deal_action, deal_quantity, deal_price,
         deal_ratio, trader_name, trader_position, data_json)
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

def fetch_insider_deals():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")

    tickers = get_tickers()
    if TEST_MODE:
        tickers = [t for t in tickers if t in VN30_SYMBOLS]
        log.info(f"[TEST MODE] Giới hạn VN30: {len(tickers)} mã")
    log.info(f"Bắt đầu lấy insider deals cho {len(tickers)} mã...")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    updated_at_map = preload_updated_at(cursor)
    limiter        = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN)
    ok = fail = skipped = 0
    batch_counter = 0

    for symbol in tickers:
        if should_skip(updated_at_map, symbol):
            skipped += 1
            continue

        retry_count = 0
        success     = False

        while retry_count < MAX_RETRY:
            try:
                limiter.acquire()
                t  = Trading(symbol=symbol, source="VCI")
                df = t.insider_deal()

                if df is not None and not df.empty:
                    upsert_insider(cursor, symbol, df)

                # Ghi meta
                cursor.execute("""
                    INSERT OR REPLACE INTO insider_meta (symbol, updated_at)
                    VALUES (?, ?)
                """, (symbol, datetime.now().isoformat()))

                ok += 1
                batch_counter += 1
                success = True
                log.info(f"✅ {symbol} — {len(df) if df is not None else 0} deals")
                break

            except SystemExit:
                wait = 65
                log.warning(f"[{symbol}] SystemExit -> sleep {wait}s (retry {retry_count+1}/{MAX_RETRY})")
                time.sleep(wait)
                limiter.reset()
                retry_count += 1

            except NotImplementedError:
                # bare NotImplementedError (không qua tenacity)
                log.warning(f"⚠️  {symbol} — insider_deal() không được hỗ trợ, bỏ qua")
                fail += 1
                break

            except Exception as e:
                # Kiểm tra tenacity.RetryError bọc NotImplementedError
                is_retry_not_implemented = (
                    (TenacityRetryError and isinstance(e, TenacityRetryError)) or
                    "RetryError" in type(e).__name__
                ) and "NotImplementedError" in str(e)

                if is_retry_not_implemented:
                    log.warning(f"⚠️  {symbol} — insider_deal() không được hỗ trợ (RetryError/NotImplementedError), bỏ qua")
                    fail += 1
                    break

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
    fetch_insider_deals()
