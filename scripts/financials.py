"""
financials.py — Lấy báo cáo tài chính & chỉ số tài chính (PE, ROE, ROA...)
- HOSE + HNX only, loại bỏ chứng quyền
- Lấy: ratio, income_statement, balance_sheet, cash_flow
- True incremental: skip mã đã cập nhật trong vòng 80 ngày (~1 quý)
- Adaptive rate limiter + retry exponential backoff
- WAL mode, batch commit
"""

from vnstock import Listing, Finance
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

DB_PATH              = os.getenv("DB_PATH", "data/stock.db")
API_KEY              = os.getenv("VNSTOCK_API_KEY", "")
MAX_REQUEST_PER_MIN  = 60
MAX_RETRY            = 3
COMMIT_BATCH         = 10
SKIP_IF_UPDATED_DAYS = 80   # ~1 quý

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
        CREATE TABLE IF NOT EXISTS financials_ratio (
            symbol   TEXT,
            period   TEXT,
            year     INTEGER,
            quarter  INTEGER,
            data_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (symbol, period, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_income (
            symbol   TEXT,
            period   TEXT,
            year     INTEGER,
            quarter  INTEGER,
            data_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (symbol, period, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_balance (
            symbol   TEXT,
            period   TEXT,
            year     INTEGER,
            quarter  INTEGER,
            data_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (symbol, period, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_cashflow (
            symbol   TEXT,
            period   TEXT,
            year     INTEGER,
            quarter  INTEGER,
            data_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (symbol, period, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_meta (
            symbol     TEXT PRIMARY KEY,
            updated_at TEXT
        );
    """)
    conn.commit()


def preload_updated_at(cursor) -> dict:
    cursor.execute("SELECT symbol, updated_at FROM financials_meta")
    return {row[0]: row[1] for row in cursor.fetchall()}


def should_skip(updated_at_map: dict, symbol: str) -> bool:
    updated_at = updated_at_map.get(symbol)
    if updated_at:
        cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
        return updated_at >= cutoff
    return False


def flatten_df(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns thành string, ví dụ ('PE', 'Q1') -> 'PE_Q1'."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
    else:
        df.columns = [str(c) for c in df.columns]
    return df


def upsert_financial(cursor, table: str, symbol: str, df: pd.DataFrame):
    """Lưu từng dòng của DataFrame tài chính vào DB dưới dạng JSON."""
    import json

    # Flatten MultiIndex columns trước khi xử lý
    df = flatten_df(df.copy())

    for _, row in df.iterrows():
        d = row.to_dict()
        # Normalize key về string (phòng trường hợp còn sót tuple)
        d = {str(k): v for k, v in d.items()}

        year    = int(d.get("year",    d.get("Năm",    0) or 0))
        quarter = int(d.get("quarter", d.get("Quý",    0) or 0))
        period  = "quarter" if quarter else "annual"
        cursor.execute(f"""
            INSERT OR REPLACE INTO {table}
            (symbol, period, year, quarter, data_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (symbol, period, year, quarter,
              json.dumps(d, ensure_ascii=False, default=str),
              datetime.now().isoformat()))

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
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            # Lọc thêm: chỉ giữ type == STOCK, bỏ ETF, BOND, FUND
            if "type" in df.columns:
                df = df[df["type"].str.upper() == "STOCK"]
            tickers = [t for t in df["symbol"].tolist() if t not in warrants]
            log.info(f"HOSE+HNX: {len(tickers)} mã")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() lỗi: {e}")
    df = listing.all_symbols()
    return [t for t in df["symbol"].tolist() if t not in warrants]

# ---------------- MAIN ---------------- #

def fetch_financials():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")

    tickers = get_tickers()
    log.info(f"Bắt đầu lấy tài chính cho {len(tickers)} mã...")

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
                f = Finance(symbol=symbol, source="VCI", period="quarter", get_all=True)

                # Lấy 4 loại báo cáo
                for table, method in [
                    ("financials_ratio",    f.ratio),
                    ("financials_income",   f.income_statement),
                    ("financials_balance",  f.balance_sheet),
                    ("financials_cashflow", f.cash_flow),
                ]:
                    try:
                        df = method()
                        if df is not None and not df.empty:
                            upsert_financial(cursor, table, symbol, df)
                    except Exception as e:
                        log.warning(f"[{symbol}] {table} lỗi: {e}")

                # Ghi meta
                cursor.execute("""
                    INSERT OR REPLACE INTO financials_meta (symbol, updated_at)
                    VALUES (?, ?)
                """, (symbol, datetime.now().isoformat()))

                ok += 1
                batch_counter += 1
                success = True
                log.info(f"✅ {symbol}")
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
    fetch_financials()
