"""
symbol.py — Lấy thông tin tổng quan (overview) của tất cả công ty niêm yết.
Chạy 1 lần/tuần để cập nhật P/E, ROE, market cap, v.v.
"""

from vnstock import Listing, Company
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
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "2.0"))


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS symbols (
            symbol           TEXT PRIMARY KEY,
            exchange         TEXT,
            industry         TEXT,
            company_type     TEXT,
            no_shareholders  INTEGER,
            foreign_percent  REAL,
            outstanding_share REAL,
            issue_share      REAL,
            charter_capital  REAL,
            market_cap       REAL,
            beta             REAL,
            pe               REAL,
            roe              REAL,
            delta_in_month   REAL,
            delta_in_year    REAL,
            short_name       TEXT,
            website          TEXT,
            industry_id      INTEGER,
            industry_id_v2   INTEGER,
            updated_at       TEXT
        );
    """)
    conn.commit()


def fetch_symbols():
    log.info("Lấy danh sách tất cả mã cổ phiếu...")
    listing = Listing()
    all_tickers = listing.all_symbols()
    all_tickers = all_tickers[all_tickers["exchange"].str.upper() != "UPCOM"]
    log.info(f"Tổng số mã: {len(all_tickers)}")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok, fail = 0, 0
    for _, row in all_tickers.iterrows():
        symbol = row["symbol"]
        try:
            company = Company(symbol=symbol, source='VCI')
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
                    __import__("datetime").datetime.now().isoformat(),
                ))
                conn.commit()
                ok += 1
                log.info(f"✅ {symbol}")
            else:
                log.warning(f"⚠️  {symbol} — không có dữ liệu")

        except Exception as e:
            log.warning(f"❌ {symbol} — {e}")
            fail += 1

        time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info(f"Hoàn tất — OK: {ok}, Lỗi: {fail}")


if __name__ == "__main__":
    fetch_symbols()
