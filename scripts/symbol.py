"""
symbol.py — High Performance Symbol Overview Fetcher
- HOSE + HNX only
- True incremental (skip mã đã cập nhật trong 7 ngày)
- Rate-limit aware (60 req/min sliding window)
- WAL mode enabled
- Retry with exponential backoff
- source='VCI' (TCBS deprecated từ 15/12/2024)
"""

from vnstock import Listing, Company
from datetime import datetime, timedelta
import sqlite3
import logging
import sys
import os
import time

# ---------------- CONFIG ---------------- #

DB_PATH             = os.getenv("DB_PATH", "data/stock.db")
API_KEY             = os.getenv("VNSTOCK_API_KEY", "")
MAX_REQUEST_PER_MIN = 60
MAX_RETRY           = 3
SKIP_IF_UPDATED_DAYS = 7   # Skip nếu đã update trong vòng 7 ngày

# ---------------- LOGGING ---------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------- DB ---------------- #

def init_db(conn: sqlite3.Connection):
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
    """Load updated_at của tất cả mã vào dict 1 lần."""
    cursor.execute("SELECT symbol, updated_at FROM symbols")
    return {row[0]: row[1] for row in cursor.fetchall()}


def should_skip(updated_at_map: dict, symbol: str) -> bool:
    """Skip nếu đã cập nhật trong vòng SKIP_IF_UPDATED_DAYS ngày."""
    updated_at = updated_at_map.get(symbol)
    if updated_at:
        cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
        return updated_at >= cutoff
    return False

# ---------------- TICKERS ---------------- #

def get_tickers() -> list:
    """Lấy danh sách mã HOSE + HNX, bỏ UPCOM."""
    listing = Listing()
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = df["symbol"].tolist()
            log.info(f"HOSE+HNX: {len(tickers)} mã (đã bỏ UPCOM)")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() lỗi: {e} — fallback all_symbols()")

    df = listing.all_symbols()
    tickers = df["symbol"].tolist()
    log.warning(f"Fallback all_symbols(): {len(tickers)} mã (bao gồm UPCOM)")
    return tickers

# ---------------- MAIN ---------------- #

def fetch_symbols():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode (20 req/min)")

    tickers = get_tickers()
    log.info(f"Bắt đầu lấy overview cho {len(tickers)} mã...")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    updated_at_map = preload_updated_at(cursor)
    ok = fail = skipped = 0
    request_count = 0
    window_start  = time.time()

    for symbol in tickers:
        # Skip mã đã cập nhật gần đây
        if should_skip(updated_at_map, symbol):
            skipped += 1
            continue

        retry   = 0
        success = False

        while retry < MAX_RETRY:
            try:
                # Rate limit sliding window
                request_count += 1
                if request_count >= MAX_REQUEST_PER_MIN:
                    elapsed = time.time() - window_start
                    if elapsed < 60:
                        sleep_time = 60 - elapsed
                        log.info(f"Rate window full → sleep {sleep_time:.1f}s")
                        time.sleep(sleep_time)
                    window_start  = time.time()
                    request_count = 0

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

            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate limit" in err:
                    wait = 2 ** retry * 5  # 5s, 10s, 20s
                    log.warning(f"[{symbol}] Rate limit → sleep {wait}s (retry {retry+1}/{MAX_RETRY})")
                    time.sleep(wait)
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
