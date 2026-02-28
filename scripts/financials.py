# financials.py
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
import json
import threading

DB_PATH              = os.getenv('DB_PATH', 'data/stock.db')
API_KEY              = os.getenv('VNSTOCK_API_KEY', '')
MAX_REQUEST_PER_MIN  = 55
SKIP_IF_UPDATED_DAYS = 80
RATE_WINDOW          = 60

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


class SmartRateLimiter:
    def __init__(self, rpm):
        self.rpm      = rpm
        self.window   = RATE_WINDOW
        self.requests = deque()
        self.lock     = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                while self.requests and now - self.requests[0] > self.window:
                    self.requests.popleft()
                if len(self.requests) < self.rpm:
                    self.requests.append(time.time())
                    return
                sleep_time = self.window - (now - self.requests[0]) + 0.1
            time.sleep(sleep_time)

    def reset(self):
        with self.lock:
            self.requests.clear()


limiter = SmartRateLimiter(MAX_REQUEST_PER_MIN)


def extract_wait_time(msg, default=65):
    for pattern in [
        r'ch\u1edd\s+(\d+)\s*gi',
        r'wait\s+(\d+)\s*second',
        r'retry\s*after\s*(\d+)',
        r'(\d+)\s*second',
    ]:
        m = re.search(pattern, msg.lower())
        if m:
            return int(m.group(1)) + 2
    return default


def create_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    conn.execute('PRAGMA temp_store=MEMORY;')
    conn.execute('PRAGMA cache_size=-20000;')
    conn.execute('PRAGMA busy_timeout=60000;')
    return conn


_INIT_SQL = (
    'CREATE TABLE IF NOT EXISTS financials_ratio ('
    'symbol TEXT, period TEXT, year INTEGER, quarter INTEGER,'
    'data_json TEXT, updated_at TEXT,'
    'PRIMARY KEY (symbol, period, year, quarter));'
    'CREATE TABLE IF NOT EXISTS financials_income ('
    'symbol TEXT, period TEXT, year INTEGER, quarter INTEGER,'
    'data_json TEXT, updated_at TEXT,'
    'PRIMARY KEY (symbol, period, year, quarter));'
    'CREATE TABLE IF NOT EXISTS financials_balance ('
    'symbol TEXT, period TEXT, year INTEGER, quarter INTEGER,'
    'data_json TEXT, updated_at TEXT,'
    'PRIMARY KEY (symbol, period, year, quarter));'
    'CREATE TABLE IF NOT EXISTS financials_cashflow ('
    'symbol TEXT, period TEXT, year INTEGER, quarter INTEGER,'
    'data_json TEXT, updated_at TEXT,'
    'PRIMARY KEY (symbol, period, year, quarter));'
    'CREATE TABLE IF NOT EXISTS financials_meta ('
    'symbol TEXT PRIMARY KEY, updated_at TEXT);'
)


def init_db(conn):
    conn.executescript(_INIT_SQL)
    conn.commit()


def should_skip(updated_at_map, symbol):
    updated_at = updated_at_map.get(symbol)
    if not updated_at:
        return False
    cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
    return updated_at >= cutoff


def upsert_ratio(conn, symbol, df):
    now  = datetime.now().isoformat()
    df_T = df.T.copy()
    records = []
    for idx, row in df_T.iterrows():
        try:
            if isinstance(idx, tuple):
                year    = int(idx[0]) if idx[0] else 0
                quarter = int(idx[1]) if len(idx) > 1 and idx[1] else 0
            else:
                m = re.match(r'(\d{4})(?:Q(\d))?', str(idx))
                if m:
                    year    = int(m.group(1))
                    quarter = int(m.group(2)) if m.group(2) else 0
                else:
                    year = quarter = 0
        except (ValueError, TypeError):
            year = quarter = 0
        if year == 0:
            continue
        period   = 'quarter' if quarter else 'annual'
        row_dict = {str(k): v for k, v in row.to_dict().items()}
        row_dict['symbol']  = symbol
        row_dict['year']    = year
        row_dict['quarter'] = quarter
        records.append((
            symbol, period, year, quarter,
            json.dumps(row_dict, ensure_ascii=False, default=str), now,
        ))
    if records:
        conn.executemany(
            'INSERT OR REPLACE INTO financials_ratio '
            '(symbol, period, year, quarter, data_json, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            records
        )
    return len(records)


def upsert_report(conn, table, symbol, df):
    now = datetime.now().isoformat()
    records = []
    for _, row in df.iterrows():
        d      = {str(k): v for k, v in row.to_dict().items()}
        year   = int(d.get('yearReport',   d.get('year',    0)) or 0)
        length = int(d.get('lengthReport', d.get('quarter', 0)) or 0)
        if length == 5:
            quarter = 0
            period  = 'annual'
        else:
            quarter = length
            period  = 'quarter'
        d['year']    = year
        d['quarter'] = quarter
        d['symbol']  = symbol
        records.append((
            symbol, period, year, quarter,
            json.dumps(d, ensure_ascii=False, default=str), now,
        ))
    if records:
        sql = (
            'INSERT OR REPLACE INTO ' + table +
            ' (symbol, period, year, quarter, data_json, updated_at)'
            ' VALUES (?, ?, ?, ?, ?, ?)'
        )
        conn.executemany(sql, records)
    return len(records)


def get_tickers():
    listing = Listing()
    try:
        warrants = set(listing.all_covered_warrant().tolist())
    except Exception:
        warrants = set()
    try:
        df = listing.symbols_by_exchange()
        if 'exchange' in df.columns:
            df = df[df['exchange'].str.upper().isin(['HOSE', 'HNX'])]
            if 'type' in df.columns:
                df = df[df['type'].str.upper() == 'STOCK']
            tickers = [t for t in df['symbol'].tolist() if t not in warrants]
            log.info('HOSE+HNX STOCK: %d ma', len(tickers))
            return tickers
    except Exception as e:
        log.warning('symbols_by_exchange() loi: %s', e)
    df = listing.all_symbols()
    return [t for t in df['symbol'].tolist() if t not in warrants]


def fetch_symbol(symbol):
    retry = 0
    while retry < 4:
        try:
            limiter.acquire()
            f = Finance(symbol=symbol, source='VCI', period='quarter', get_all=True)
            result = {}
            try:
                df = f.ratio()
                if df is not None and not df.empty:
                    result['ratio'] = df
            except Exception as e:
                log.warning('[%s] ratio loi: %s', symbol, e)
            for key, method in [
                ('income',   f.income_statement),
                ('balance',  f.balance_sheet),
                ('cashflow', f.cash_flow),
            ]:
                try:
                    df = method()
                    if df is not None and not df.empty:
                        result[key] = df
                except Exception as e:
                    log.warning('[%s] %s loi: %s', symbol, key, e)
            return result
        except SystemExit:
            wait = 65
            log.warning('[%s] SystemExit -> sleep %ds (retry %d/4)', symbol, wait, retry+1)
            time.sleep(wait)
            limiter.reset()
            retry += 1
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ['429', 'rate limit', 'exceeded', 'gi\u1edbi h\u1ea1n']):
                wait = extract_wait_time(str(e))
                log.warning('[%s] Rate limit -> sleep %ds (retry %d/4)', symbol, wait, retry+1)
                time.sleep(wait)
                limiter.reset()
            else:
                sleep_time = 2 ** retry
                log.warning('[%s] Loi: %s -> retry %d/4 sau %ds', symbol, e, retry+1, sleep_time)
                time.sleep(sleep_time)
            retry += 1
    return None


def save_symbol(conn, symbol, data):
    try:
        if 'ratio' in data:
            upsert_ratio(conn, symbol, data['ratio'])
        for key, table in [
            ('income',   'financials_income'),
            ('balance',  'financials_balance'),
            ('cashflow', 'financials_cashflow'),
        ]:
            if key in data:
                upsert_report(conn, table, symbol, data[key])
        conn.execute(
            'INSERT OR REPLACE INTO financials_meta (symbol, updated_at) VALUES (?, ?)',
            (symbol, datetime.now().isoformat())
        )
        conn.commit()
        return True
    except Exception as e:
        log.warning('[%s] Save loi: %s', symbol, e)
        conn.rollback()
        return False


def fetch_financials():
    if API_KEY:
        os.environ['VNSTOCK_API_KEY'] = API_KEY
        log.info('Using API key')
    else:
        log.warning('Guest mode')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = create_connection()
    init_db(conn)
    cursor = conn.cursor()
    cursor.execute('SELECT symbol, updated_at FROM financials_meta')
    updated_at_map = dict(cursor.fetchall())

    tickers = get_tickers()
    todo    = [s for s in tickers if not should_skip(updated_at_map, s)]
    skipped = len(tickers) - len(todo)
    log.info('Bat dau: %d ma (skip %d da co data)', len(todo), skipped)

    ok = fail = 0
    for i, symbol in enumerate(todo):
        data = fetch_symbol(symbol)
        if data is None:
            fail += 1
            log.warning('FAIL %s', symbol)
        else:
            if save_symbol(conn, symbol, data):
                ok += 1
                log.info('OK %s (%d/%d)', symbol, i+1, len(todo))
            else:
                fail += 1

    conn.close()
    log.info('Done -- OK: %d | Skipped: %d | Failed: %d', ok, skipped, fail)


if __name__ == '__main__':
    fetch_financials()
