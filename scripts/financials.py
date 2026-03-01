import sqlite3
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import requests

DB_PATH = "data/stock.db"
MAX_WORKERS = 8
RPM_LIMIT = 60
SAFE_ZONE = 55  # bắt đầu giảm tốc khi vượt 55 rpm
REQUEST_WINDOW = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("VCI-Financials")

# =========================
# Adaptive Rate Limiter
# =========================

class AdaptiveRateLimiter:
    def __init__(self, rpm):
        self.rpm = rpm
        self.lock = threading.Lock()
        self.timestamps = []

    def wait(self):
        while True:
            with self.lock:
                now = time.time()
                self.timestamps = [t for t in self.timestamps if now - t < REQUEST_WINDOW]
                current_rpm = len(self.timestamps)

                if current_rpm < self.rpm:
                    if current_rpm >= SAFE_ZONE:
                        time.sleep(0.3)
                    self.timestamps.append(now)
                    return
            time.sleep(0.05)

rate_limiter = AdaptiveRateLimiter(RPM_LIMIT)

# =========================
# DB SCHEMA
# =========================

RATIO_MAP = {
    "PE": "pe",
    "PB": "pb",
    "ROE": "roe",
    "ROA": "roa",
}

INCOME_MAP = {
    "Revenue": "revenue",
    "NetProfit": "net_profit",
    "RevenueGrowth": "revenue_growth"
}

def table_columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

def needs_recreate(conn, table, expected_cols):
    cols = table_columns(conn, table)
    if not cols:
        return False
    return not expected_cols.issubset(cols)

def init_db(conn):
    schema_map = {
        "financials_ratio": set(
            ["symbol", "year", "quarter"] +
            list(RATIO_MAP.values()) +
            ["updated_at"]
        ),
        "financials_income": set(
            ["symbol", "year", "quarter"] +
            list(INCOME_MAP.values()) +
            ["updated_at"]
        )
    }

    for table, expected_cols in schema_map.items():
        if needs_recreate(conn, table, expected_cols):
            log.info("Schema mismatch -> drop table %s", table)
            conn.execute(f"DROP TABLE IF EXISTS {table}")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS financials_ratio (
            symbol TEXT,
            year INTEGER,
            quarter INTEGER,
            pe REAL,
            pb REAL,
            roe REAL,
            roa REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_income (
            symbol TEXT,
            year INTEGER,
            quarter INTEGER,
            revenue REAL,
            net_profit REAL,
            revenue_growth REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_meta (
            symbol TEXT PRIMARY KEY,
            updated_at TEXT
        );
    """)
    conn.commit()

# =========================
# VCI FETCH
# =========================

def fetch_vci_financials(symbol):
    rate_limiter.wait()
    url = f"https://api-finfo.vcbs.com.vn/financial/{symbol}"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        log.warning("Fetch error %s: %s", symbol, e)
    return None

# =========================
# UPSERT LOGIC
# =========================

def upsert_ratio(conn, symbol, year, quarter, data):
    conn.execute("""
        INSERT OR REPLACE INTO financials_ratio
        (symbol, year, quarter, pe, pb, roe, roa, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, year, quarter,
        data.get("pe"),
        data.get("pb"),
        data.get("roe"),
        data.get("roa"),
        datetime.utcnow().isoformat()
    ))

def upsert_income(conn, symbol, year, quarter, data):
    conn.execute("""
        INSERT OR REPLACE INTO financials_income
        (symbol, year, quarter, revenue, net_profit, revenue_growth, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, year, quarter,
        data.get("revenue"),
        data.get("net_profit"),
        data.get("revenue_growth"),
        datetime.utcnow().isoformat()
    ))

# =========================
# PROCESS SYMBOL
# =========================

def process_symbol(symbol):
    conn = sqlite3.connect(DB_PATH)
    data = fetch_vci_financials(symbol)
    if not data:
        log.warning("No data for %s", symbol)
        return

    try:
        for record in data.get("ratio", []):
            upsert_ratio(conn, symbol, record["year"], record["quarter"], record)

        for record in data.get("income", []):
            upsert_income(conn, symbol, record["year"], record["quarter"], record)

        conn.execute("""
            INSERT OR REPLACE INTO financials_meta
            (symbol, updated_at)
            VALUES (?, ?)
        """, (symbol, datetime.utcnow().isoformat()))

        conn.commit()
        log.info("Updated %s", symbol)

    except Exception as e:
        log.error("Error processing %s: %s", symbol, e)
    finally:
        conn.close()

# =========================
# MAIN RUNNER
# =========================

def run(symbols):
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    conn.close()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_symbol, s) for s in symbols]
        for f in as_completed(futures):
            f.result()

if __name__ == "__main__":
    symbols = ["HPG", "NLG", "VIC"]  # test
    run(symbols)
