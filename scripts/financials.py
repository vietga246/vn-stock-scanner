import os
import time
import logging
import sqlite3
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from vnstock import Stock

# =============================
# CONFIG
# =============================

DB_PATH = "data/financials.db"
MAX_WORKERS = 5
MAX_RPM = 55          # giữ dưới 60 để an toàn
SLOWDOWN_THRESHOLD = 50
RETRY = 3
YEARS_LIMIT = 10      # chỉ lấy 10 năm gần nhất

# =============================
# LOGGING
# =============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# =============================
# RATE LIMITER
# =============================

class AdaptiveRateLimiter:
    def __init__(self, max_rpm, slowdown_threshold):
        self.max_rpm = max_rpm
        self.slowdown_threshold = slowdown_threshold
        self.calls = []
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60]

            if len(self.calls) >= self.max_rpm:
                sleep_time = 60 - (now - self.calls[0])
                logging.info(f"Rate limit hit → sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
                return self.wait()

            if len(self.calls) >= self.slowdown_threshold:
                logging.info("Approaching limit → slowing down")
                time.sleep(0.5)

            self.calls.append(time.time())

rate_limiter = AdaptiveRateLimiter(MAX_RPM, SLOWDOWN_THRESHOLD)

# =============================
# DATABASE
# =============================

def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS income_statement (
            symbol TEXT,
            year INTEGER,
            revenue REAL,
            net_profit REAL,
            PRIMARY KEY(symbol, year)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS financial_ratio (
            symbol TEXT,
            year INTEGER,
            roe REAL,
            roa REAL,
            eps REAL,
            PRIMARY KEY(symbol, year)
        )
    """)

    conn.commit()
    conn.close()

def get_latest_year(symbol, table):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(year) FROM {table} WHERE symbol=?", (symbol,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

# =============================
# FETCH DATA FROM VCI
# =============================

def fetch_financials(symbol):
    for attempt in range(RETRY):
        try:
            rate_limiter.wait()

            stock = Stock(symbol=symbol, source="VCI")

            income = stock.finance.income_statement()
            ratio = stock.finance.ratio()

            return income, ratio

        except Exception as e:
            logging.warning(f"{symbol} retry {attempt+1}: {e}")
            time.sleep(1)

    logging.error(f"{symbol} failed after {RETRY} retries")
    return None, None

# =============================
# PROCESS + SAVE
# =============================

def process_symbol(symbol):
    logging.info(f"Processing {symbol}")

    income_df, ratio_df = fetch_financials(symbol)

    if income_df is None:
        return

    current_year = datetime.now().year
    cutoff_year = current_year - YEARS_LIMIT

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ---- Income Statement ----
    if not income_df.empty:
        income_df = income_df[income_df["year"] >= cutoff_year]

        latest_year = get_latest_year(symbol, "income_statement")

        for _, row in income_df.iterrows():
            year = int(row["year"])

            if latest_year and year <= latest_year:
                continue

            cur.execute("""
                INSERT OR REPLACE INTO income_statement
                VALUES (?, ?, ?, ?)
            """, (
                symbol,
                year,
                row.get("revenue"),
                row.get("net_profit"),
            ))

    # ---- Ratio ----
    if not ratio_df.empty:
        ratio_df = ratio_df[ratio_df["year"] >= cutoff_year]

        latest_year = get_latest_year(symbol, "financial_ratio")

        for _, row in ratio_df.iterrows():
            year = int(row["year"])

            if latest_year and year <= latest_year:
                continue

            cur.execute("""
                INSERT OR REPLACE INTO financial_ratio
                VALUES (?, ?, ?, ?, ?)
            """, (
                symbol,
                year,
                row.get("roe"),
                row.get("roa"),
                row.get("eps"),
            ))

    conn.commit()
    conn.close()

    logging.info(f"{symbol} done")

# =============================
# MAIN
# =============================

def run(symbols):
    init_db()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_symbol, s) for s in symbols]

        for future in as_completed(futures):
            future.result()

    logging.info("All symbols completed")


if __name__ == "__main__":
    symbols = ["HPG"]  # test trước 1 mã
    run(symbols)
