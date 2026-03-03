"""
symbol.py — Symbol Info Fetcher (Production)

- HOSE + HNX only
- Lọc chứng quyền chính xác bằng Listing.all_covered_warrant()
- Kết hợp symbols_by_exchange() + symbols_by_industries()
- Không dùng Company.overview() vì VCI không hỗ trợ
- WAL mode enabled
"""

from vnstock import Listing
from datetime import datetime
import sqlite3
import logging
import sys
import os

# ---------------- CONFIG ---------------- #

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")
API_KEY = os.getenv("VNSTOCK_API_KEY", "")

# ---------------- LOGGING ---------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------- DB ---------------- #

def init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS symbols (
            symbol       TEXT PRIMARY KEY,
            organ_name   TEXT,
            en_organ_name TEXT,
            exchange     TEXT,
            type         TEXT,
            industry_code TEXT,
            industry_name TEXT,
            updated_at   TEXT
        );
    """)
    conn.commit()

# ---------------- MAIN ---------------- #

def fetch_symbols():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")

    listing = Listing()

    # 1. Lấy danh sách chứng quyền để lọc bỏ
    log.info("Lấy danh sách chứng quyền...")
    try:
        warrants = set(listing.all_covered_warrant().tolist())
        log.info(f"Chứng quyền: {len(warrants)} mã")
    except Exception as e:
        log.warning(f"Không lấy được danh sách chứng quyền: {e} — dùng filter regex")
        warrants = set()

    # 2. Lấy danh sách mã HOSE + HNX
    log.info("Lấy danh sách mã HOSE+HNX...")
    df_exchange = listing.symbols_by_exchange()
    df_exchange = df_exchange[df_exchange["exchange"].str.upper().isin(["HOSE", "HNX"])]
    df_exchange = df_exchange[~df_exchange["symbol"].isin(warrants)]
    log.info(f"HOSE+HNX sau lọc chứng quyền: {len(df_exchange)} mã")

    # 3. Lấy thông tin ngành
    log.info("Lấy thông tin ngành...")
    try:
        df_industry = listing.symbols_by_industries()
        industry_map = dict(zip(
            df_industry["symbol"],
            zip(df_industry["industry_code"], df_industry["industry_name"])
        ))
        log.info(f"Ngành: {len(industry_map)} mã")
    except Exception as e:
        log.warning(f"Không lấy được ngành: {e}")
        industry_map = {}

    # 4. Ghi vào DB
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    init_db(conn)

    ok = 0
    for _, row in df_exchange.iterrows():
        symbol        = row["symbol"]
        industry_info = industry_map.get(symbol, (None, None))

        cursor.execute("""
            INSERT OR REPLACE INTO symbols
            (symbol, organ_name, en_organ_name, exchange, type,
             industry_code, industry_name, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            row.get("organ_name"),
            row.get("en_organ_name"),
            row.get("exchange"),
            row.get("type"),
            industry_info[0],
            industry_info[1],
            datetime.now().isoformat(),
        ))
        ok += 1

    conn.commit()
    conn.close()
    log.info(f"✅ Done — Đã lưu {ok} mã vào DB")


if __name__ == "__main__":
    fetch_symbols()
