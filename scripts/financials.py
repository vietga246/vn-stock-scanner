# financials.py - Lay bao cao tai chinh & chi so tai chinh

# HOSE + HNX only, type=STOCK, loai chung quyen

# ratio, income_statement, balance_sheet, cash_flow

# Incremental skip 80 ngay, ThreadPool 10 workers, SmartRateLimiter 60 RPM

# BUG FIX: upsert_ratio transpose + upsert_report dung yearReport field

from vnstock import Listing, Finance
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
import sqlite3
import pandas as pd
import logging
import sys
import os
import time
import re
import json
import threading

# ===== CONFIG =====

DB_PATH              = os.getenv(“DB_PATH”, “data/stock.db”)
API_KEY              = os.getenv(“VNSTOCK_API_KEY”, “”)
MAX_REQUEST_PER_MIN  = 60
MAX_WORKERS          = 10
MAX_RETRY            = 4
SKIP_IF_UPDATED_DAYS = 80

# ===== LOGGING =====

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s [%(levelname)s] %(message)s”,
handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(**name**)

# ===== SMART RATE LIMITER (thread-safe) =====

class SmartRateLimiter:
def **init**(self, rpm: int):
self.rpm        = rpm
self.soft_limit = int(rpm * 0.85)
self.window     = 60
self.requests   = deque()
self.lock       = threading.Lock()

```
def acquire(self):
    while True:
        with self.lock:
            now = time.time()
            while self.requests and now - self.requests[0] > self.window:
                self.requests.popleft()
            current = len(self.requests)
            if current >= self.rpm:
                sleep_time = self.window - (now - self.requests[0]) + 0.05
            elif current >= self.soft_limit:
                ratio      = (current - self.soft_limit) / (self.rpm - self.soft_limit)
                sleep_time = ratio * 0.8
            else:
                self.requests.append(time.time())
                return
        time.sleep(sleep_time)

def reset(self):
    with self.lock:
        self.requests.clear()
```

limiter = SmartRateLimiter(MAX_REQUEST_PER_MIN)

# ===== WAIT TIME PARSER =====

def extract_wait_time(msg: str, default: int = 65) -> int:
for pattern in [
r”ch\u1edd\s+(\d+)\s*gi”,
r”wait\s+(\d+)\s*second”,
r”retry\s*after\s*(\d+)”,
r”(\d+)\s*second”,
]:
m = re.search(pattern, msg.lower())
if m:
return int(m.group(1)) + 1
return default

# ===== DATABASE =====

def create_connection() -> sqlite3.Connection:
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute(“PRAGMA journal_mode=WAL;”)
conn.execute(“PRAGMA synchronous=NORMAL;”)
conn.execute(“PRAGMA temp_store=MEMORY;”)
conn.execute(“PRAGMA cache_size=-20000;”)
return conn

def init_db(conn: sqlite3.Connection):
conn.executescript(”””
CREATE TABLE IF NOT EXISTS financials_ratio (
symbol    TEXT,
period    TEXT,
year      INTEGER,
quarter   INTEGER,
data_json TEXT,
updated_at TEXT,
PRIMARY KEY (symbol, period, year, quarter)
);
CREATE TABLE IF NOT EXISTS financials_income (
symbol    TEXT,
period    TEXT,
year      INTEGER,
quarter   INTEGER,
data_json TEXT,
updated_at TEXT,
PRIMARY KEY (symbol, period, year, quarter)
);
CREATE TABLE IF NOT EXISTS financials_balance (
symbol    TEXT,
period    TEXT,
year      INTEGER,
quarter   INTEGER,
data_json TEXT,
updated_at TEXT,
PRIMARY KEY (symbol, period, year, quarter)
);
CREATE TABLE IF NOT EXISTS financials_cashflow (
symbol    TEXT,
period    TEXT,
year      INTEGER,
quarter   INTEGER,
data_json TEXT,
updated_at TEXT,
PRIMARY KEY (symbol, period, year, quarter)
);
CREATE TABLE IF NOT EXISTS financials_meta (
symbol     TEXT PRIMARY KEY,
updated_at TEXT
);
“””)
conn.commit()

# ===== UTILS =====

def should_skip(updated_at_map: dict, symbol: str) -> bool:
updated_at = updated_at_map.get(symbol)
if not updated_at:
return False
cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
return updated_at >= cutoff

def upsert_ratio(cursor: sqlite3.Cursor, symbol: str, df: pd.DataFrame):
# Finance.ratio() tra ve DataFrame WIDE: rows=metrics, cols=MultiIndex(year,quarter)
# Can TRANSPOSE de moi row = 1 period
now = datetime.now().isoformat()
df_T = df.T.copy()
records = []
for idx, row in df_T.iterrows():
if isinstance(idx, tuple):
year    = int(idx[0]) if idx[0] else 0
quarter = int(idx[1]) if len(idx) > 1 and idx[1] else 0
else:
idx_str = str(idx)
m = re.match(r”(\d{4})(?:Q(\d))?”, idx_str)
if m:
year    = int(m.group(1))
quarter = int(m.group(2)) if m.group(2) else 0
else:
year = quarter = 0
period   = “quarter” if quarter else “annual”
row_dict = {str(k): v for k, v in row.to_dict().items()}
row_dict[“symbol”]  = symbol
row_dict[“year”]    = year
row_dict[“quarter”] = quarter
records.append((
symbol, period, year, quarter,
json.dumps(row_dict, ensure_ascii=False, default=str),
now,
))
if records:
cursor.executemany(”””
INSERT OR REPLACE INTO financials_ratio
(symbol, period, year, quarter, data_json, updated_at)
VALUES (?, ?, ?, ?, ?, ?)
“””, records)
return len(records)

def upsert_report(cursor: sqlite3.Cursor, table: str, symbol: str, df: pd.DataFrame):
# income/balance/cashflow: moi row = 1 period
# Field nam: ‘yearReport’, field quy: ‘lengthReport’ (5=annual, 1-4=Q1-Q4)
now = datetime.now().isoformat()
records = []
for _, row in df.iterrows():
d = {str(k): v for k, v in row.to_dict().items()}
year   = int(d.get(“yearReport”,   d.get(“year”,    0)) or 0)
length = int(d.get(“lengthReport”, d.get(“quarter”, 0)) or 0)
if length == 5:
quarter = 0
period  = “annual”
else:
quarter = length
period  = “quarter”
d[“year”]    = year
d[“quarter”] = quarter
d[“symbol”]  = symbol
records.append((
symbol, period, year, quarter,
json.dumps(d, ensure_ascii=False, default=str),
now,
))
if records:
cursor.executemany(
f”INSERT OR REPLACE INTO {table} “
“(symbol, period, year, quarter, data_json, updated_at) “
“VALUES (?, ?, ?, ?, ?, ?)”,
records
)
return len(records)

# ===== TICKERS =====

def get_tickers() -> list:
listing = Listing()
try:
warrants = set(listing.all_covered_warrant().tolist())
except Exception:
warrants = set()
try:
df = listing.symbols_by_exchange()
if “exchange” in df.columns:
df = df[df[“exchange”].str.upper().isin([“HOSE”, “HNX”])]
if “type” in df.columns:
df = df[df[“type”].str.upper() == “STOCK”]
tickers = [t for t in df[“symbol”].tolist() if t not in warrants]
log.info(f”HOSE+HNX STOCK: {len(tickers)} ma”)
return tickers
except Exception as e:
log.warning(f”symbols_by_exchange() loi: {e}”)
df = listing.all_symbols()
return [t for t in df[“symbol”].tolist() if t not in warrants]

# ===== WORKER =====

def process_symbol(symbol: str, updated_at_map: dict) -> str:
if should_skip(updated_at_map, symbol):
return “skipped”
conn   = create_connection()
cursor = conn.cursor()
retry  = 0
while retry < MAX_RETRY:
try:
limiter.acquire()
f = Finance(symbol=symbol, source=“VCI”, period=“quarter”, get_all=True)
try:
df = f.ratio()
if df is not None and not df.empty:
upsert_ratio(cursor, symbol, df)
except Exception as e:
log.warning(f”[{symbol}] financials_ratio loi: {e}”)
for table, method in [
(“financials_income”,   f.income_statement),
(“financials_balance”,  f.balance_sheet),
(“financials_cashflow”, f.cash_flow),
]:
try:
df = method()
if df is not None and not df.empty:
upsert_report(cursor, table, symbol, df)
except Exception as e:
log.warning(f”[{symbol}] {table} loi: {e}”)
cursor.execute(
“INSERT OR REPLACE INTO financials_meta (symbol, updated_at) VALUES (?, ?)”,
(symbol, datetime.now().isoformat())
)
conn.commit()
conn.close()
log.info(f”OK {symbol}”)
return “ok”
except SystemExit:
log.warning(f”[{symbol}] SystemExit -> sleep 65s (retry {retry+1}/{MAX_RETRY})”)
time.sleep(65)
limiter.reset()
retry += 1
except Exception as e:
err = str(e).lower()
if any(x in err for x in [“429”, “rate limit”, “exceeded”, “gi\u1edbi h\u1ea1n”]):
wait = extract_wait_time(str(e))
log.warning(f”[{symbol}] Rate limit -> sleep {wait}s (retry {retry+1}/{MAX_RETRY})”)
time.sleep(wait)
limiter.reset()
else:
sleep_time = 2 ** retry
log.warning(f”[{symbol}] Loi: {e} -> retry {retry+1}/{MAX_RETRY} sau {sleep_time}s”)
time.sleep(sleep_time)
retry += 1
conn.close()
log.warning(f”FAIL {symbol}”)
return “fail”

# ===== MAIN =====

def fetch_financials():
if API_KEY:
os.environ[“VNSTOCK_API_KEY”] = API_KEY
log.info(“Using API key”)
else:
log.warning(“Guest mode”)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
conn = create_connection()
init_db(conn)
cursor = conn.cursor()
cursor.execute(“SELECT symbol, updated_at FROM financials_meta”)
updated_at_map = dict(cursor.fetchall())
conn.close()
tickers = get_tickers()
log.info(f”Bat dau lay tai chinh cho {len(tickers)} ma…”)
results = {“ok”: 0, “fail”: 0, “skipped”: 0}
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
futures = {executor.submit(process_symbol, s, updated_at_map): s for s in tickers}
for future in as_completed(futures):
try:
result = future.result()
except Exception as e:
log.warning(f”Future exception: {e}”)
result = “fail”
results[result] += 1
log.info(f”Done – OK: {results[‘ok’]} | Skipped: {results[‘skipped’]} | Failed: {results[‘fail’]}”)

if **name** == “**main**”:
fetch_financials()
