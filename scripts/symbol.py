"""
symbol.py — Lấy thông tin tổng quan (overview) của tất cả công ty niêm yết.
- Chỉ lấy HOSE + HNX (bỏ UPCOM)
- Skip mã đã được cập nhật trong vòng 7 ngày (resume-safe)
- Chạy 1 lần/tuần để cập nhật P/E, ROE, market cap, v.v.
"""

from vnstock import Listing, Company
from datetime import datetime, timedelta
import sqlite3
import time
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH       = os.getenv("DB_PATH", "data/stock.db")
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "3"))
API_KEY       = os.getenv("VNSTOCK_API_KEY", "")
MAX_RETRY     = 3


def init_db(conn: sqlite3.Connection):
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


def get_tickers():
    """Lấy danh sách mã chỉ HOSE + HNX, bỏ UPCOM."""
    listing = Listing()
    try:
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = df["symbol"].tolist()
            log.info(f"HOSE+HNX: {len(tickers)} mã (đã bỏ UPCOM)")
            return tickers
    except Exception as e:
        log.warning(f"symbols_by_exchange() thất bại: {e} — dùng all_symbols()")

    # Fallback
    df = listing.all_symbols()
    tickers = df["symbol"].tolist()
    log.warning(f"Dùng all_symbols(): {len(tickers)} mã (bao gồm cả UPCOM)")
    return tickers


def should_skip(cursor: sqlite3.Cursor, symbol: str) -> bool:
    """Skip nếu đã cập nhật trong vòng 7 ngày."""
    cursor.execute("SELECT updated_at FROM symbols WHERE symbol=?", (symbol,))
    row = cursor.fetchone()
    if row and row[0]:
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        if row[0] >= cutoff:
            return True
    return False


def fetch_symbols():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Sử dụng API key từ environment")
    else:
        log.warning("⚠️  Không có API key — dùng gói Guest (20 req/phút)")

    tickers = get_tickers()
    log.info(f"Bắt đầu lấy overview cho {len(tickers)} mã...")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok, fail, skipped = 0, 0, 0

    for symbol in tickers:
        # Skip mã đã cập nhật gần đây
        if should_skip(cursor, symbol):
            skipped += 1
            continue

        retry = 0
        while retry < MAX_RETRY:
            try:
                company  = Company(symbol=symbol, source="VCI")
                overview = company.overview()

                if not overview.empty:
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
                break

            except Exception as e:
                err = str(e)
                if "Rate Limit" in err or "rate limit" in err.lower() or "429" in err:
                    wait = 60
                    log.warning(f"[{symbol}] Rate limit — chờ {wait}s (lần {retry+1}/{MAX_RETRY})...")
                    time.sleep(wait)
                    retry += 1
                else:
                    log.warning(f"❌ {symbol} — {e}")
                    fail += 1
                    break

        time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info(f"Hoàn tất — OK: {ok}, Bỏ qua: {skipped}, Lỗi: {fail}")


if __name__ == "__main__":
    fetch_symbols()
