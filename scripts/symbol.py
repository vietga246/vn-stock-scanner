"""
symbol.py — High Performance Symbol Overview Fetcher (Adaptive + Production)

- HOSE + HNX only, loại bỏ trái phiếu
- True incremental (skip mã đã cập nhật trong 7 ngày)
- Adaptive sliding-window rate limiter (deque-based)
- Auto-detect server wait time (VI + EN)
- Catch SystemExit từ vnstock
- Thử VCI trước, fallback TCBS
- WAL mode enabled
"""

from vnstock import Listing, Company
from datetime import datetime, timedelta
from collections import deque
import sqlite3
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
SKIP_IF_UPDATED_DAYS = 7

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
            log.debug(f"[Limiter] Near limit ({current}/{self.rpm}) -> delay {dynamic_delay:.3f}s")
            time.sleep(dynamic_delay)

        self.requests.append(time.time())

    def reset(self):
        self.requests.clear()

# ---------------- WAIT TIME PARSER ---------------- #

def extract_wait_time(error_message: str, default: int = 60) -> int:
    """Parse thời gian chờ từ message lỗi của server (VI + EN)."""
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
    """Lọc mã trái phiếu dạng CACB2510, CVMM2520..."""
    return bool(BOND_PATTERN.match(symbol)) and len(symbol) > 6

# ---------------- DB ---------------- #

def init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS symbols (
            symbol            TEXT PRIMARY KEY,
            exchange          TEXT,
            industry          TEXT,
            company_type      TEXT,
            no_shareholders   INTEGER,
            foreign_percent   REAL,
            outstanding_share REAL,
            issue_share       REAL,
            charter_capital   REAL,
            market_cap        REAL,
            beta              REAL,
            pe                REAL,
            roe               REAL,
            delta_in_month    REAL,
            delta_in_year     REAL,
            short_name        TEXT,
            website           TEXT,
            industry_id       INTEGER,
            industry_id_v2    INTEGER,
            updated_at        TEXT
        );
    """)
    conn.commit()


def preload_updated_at(cursor) -> dict:
    cursor.execute("SELECT symbol, updated_at FROM symbols")
    return {row[0]: row[1] for row in cursor.fetchall()}


def should_skip(updated_at_map: dict, symbol: str) -> bool:
    updated_at = updated_at_map.get(symbol)
    if updated_at:
        cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
        return updated_at >= cutoff
    return False

# ---------------- TICKERS ---------------- #

def get_tickers() -> list:
    """Lấy danh sách mã HOSE + HNX, bỏ UPCOM và trái phiếu."""
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

def fetch_symbols():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (20 req/min)")

    limiter = AdaptiveRateLimiter(MAX_REQUEST_PER_MIN, safety_ratio=0.9)
    tickers = get_tickers()
    log.info(f"Bắt đầu lấy overview cho {len(tickers)} mã...")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    updated_at_map = preload_updated_at(cursor)
    ok = fail = skipped = 0

    for symbol in tickers:
        if should_skip(updated_at_map, symbol):
            skipped += 1
            continue

        retry   = 0
        success = False

        while retry < MAX_RETRY:
            try:
                limiter.acquire()

                company  = Company(symbol=symbol, source="VCI")
                overview = company.overview()

                if overview is not None and not overview.empty:
                    ov = overview.iloc[0].to_dict()
                    cursor.execute("""
                        INSERT OR REPLACE INTO symbols
                        (symbol, exchange, industry, company_type, no_shareholders,
                         foreign_percent, outstanding_share, issue_share, charter_capital,
                         market_cap, beta, pe, roe, delta_in_month, delta_in_year,
                         short_name, website, industry_id, industry_id_v2, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        symbol,
                        ov.get("exchange"),
                        ov.get("industry"),
                        ov.get("company_type"),
                        ov.get("no_shareholders"),
                        ov.get("foreign_percent"),
                        ov.get("outstanding_share"),
                        ov.get("issue_share"),
                        ov.get("charter_capital"),
                        ov.get("market_cap"),
                        ov.get("beta"),
                        ov.get("pe"),
                        ov.get("roe"),
                        ov.get("delta_in_month"),
                        ov.get("delta_in_year"),
                        ov.get("short_name"),
                        ov.get("website"),
                        ov.get("industry_id"),
                        ov.get("industry_id_v2"),
                        datetime.now().isoformat(),
                    ))
                    conn.commit()
                    ok += 1
                    log.info(f"✅ {symbol}")
                else:
                    log.warning(f"⚠️  {symbol} — không có dữ liệu")

                success = True
                break

            except SystemExit:
                wait = 65
                log.warning(f"[{symbol}] SystemExit (rate limit) -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                time.sleep(wait)
                limiter.reset()
                retry += 1

            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["429", "rate limit", "giới hạn", "exceeded"]):
                    wait = extract_wait_time(str(e), default=65)
                    log.warning(f"[{symbol}] Rate limit -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                    time.sleep(wait)
                    limiter.reset()
                    retry += 1
                else:
                    log.warning(f"❌ {symbol} — {e}")
                    fail += 1
                    break

        if not success and retry >= MAX_RETRY:
            log.warning(f"[{symbol}] Hết retry — bỏ qua")
            fail += 1

    conn.close()
    log.info(f"✅ Done — OK: {ok}, Skipped: {skipped}, Failed: {fail}")


if __name__ == "__main__":
    fetch_symbols()
