# financials.py - normalized schema, no JSON, 5 years only
# 706 symbols x 20 quarters x 4 tables x ~150 bytes = ~8MB DB
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
import threading

DB_PATH              = os.getenv('DB_PATH', 'data/stock.db')
API_KEY              = os.getenv('VNSTOCK_API_KEY', '')
MAX_RPM              = 55
SKIP_IF_UPDATED_DAYS = 80
YEARS_HISTORY        = 5
TEST_MODE            = os.getenv('TEST_MODE', '').lower() in ('1', 'true', 'yes')
TEST_SYMBOLS         = ['VCB', 'FPT', 'VIC']   # chi dung khi TEST_MODE=true

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ===== FIELD MAPPINGS (vnstock -> normalized) =====

RATIO_MAP = {
    'priceToEarning':    'pe',
    'priceToBook':       'pb',
    'priceToSale':       'ps',
    'ValueBeforeEbitda': 'ev_ebitda',
    'roa':               'roa',
    'roe':               'roe',
    'roic':              'roic',
    'grossProfitMargin': 'gross_margin',
    'netProfitMargin':   'net_margin',
    'ebitdaOnRevenue':   'ebitda_margin',
    'debtOnEquity':      'debt_equity',
    'debtOnAsset':       'debt_asset',
    'currentPayment':    'current_ratio',
    'quickPayment':      'quick_ratio',
    'revenueGrowth':     'revenue_growth',
    'earningGrowth':     'earnings_growth',
}

INCOME_MAP = {
    'revenue':           'revenue',
    'grossProfit':       'gross_profit',
    'operationProfit':   'operating_profit',
    'ebit':              'ebit',
    'ebitda':            'ebitda',
    'shareHolderIncome': 'net_profit',
}

BALANCE_MAP = {
    'asset':             'total_assets',
    'equity':            'total_equity',
    'debt':              'total_debt',
    'cash':              'cash',
    'shortDebt':         'short_term_debt',
    'longDebt':          'long_term_debt',
    'bookValuePerShare': 'book_value_per_share',
}

CASHFLOW_MAP = {
    'fromSale':          'cfo',
    'fromInvesting':     'cfi',
    'fromFinancial':     'cff',
    'investCost':        'capex',
    'freeCashFlow':      'fcf',
}

# ===== RATE LIMITER =====

class SmartRateLimiter:
    def __init__(self, rpm):
        self.rpm      = rpm
        self.requests = deque()
        self.lock     = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                while self.requests and now - self.requests[0] > 60:
                    self.requests.popleft()
                if len(self.requests) < self.rpm:
                    self.requests.append(time.time())
                    return
                sleep_time = 60 - (now - self.requests[0]) + 0.1
            time.sleep(sleep_time)

    def reset(self):
        with self.lock:
            self.requests.clear()

limiter = SmartRateLimiter(MAX_RPM)

# ===== DATABASE =====

def create_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    conn.execute('PRAGMA busy_timeout=60000;')
    return conn

def init_db(conn):
    # Drop tables neu schema cu (co cot data_json) de recreate normalized
    for table in ['financials_ratio', 'financials_income', 'financials_balance', 'financials_cashflow']:
        try:
            cols = [r[1] for r in conn.execute('PRAGMA table_info(' + table + ')').fetchall()]
            if 'data_json' in cols:
                conn.execute('DROP TABLE ' + table)
                conn.commit()
        except Exception:
            pass
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS financials_ratio (
            symbol TEXT, year INTEGER, quarter INTEGER,
            pe REAL, pb REAL, ps REAL, ev_ebitda REAL,
            roe REAL, roa REAL, roic REAL,
            gross_margin REAL, net_margin REAL, ebitda_margin REAL,
            debt_equity REAL, debt_asset REAL,
            current_ratio REAL, quick_ratio REAL,
            revenue_growth REAL, earnings_growth REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_income (
            symbol TEXT, year INTEGER, quarter INTEGER,
            revenue REAL, gross_profit REAL, operating_profit REAL,
            ebit REAL, ebitda REAL, net_profit REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_balance (
            symbol TEXT, year INTEGER, quarter INTEGER,
            total_assets REAL, total_equity REAL, total_debt REAL,
            cash REAL, short_term_debt REAL, long_term_debt REAL,
            book_value_per_share REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_cashflow (
            symbol TEXT, year INTEGER, quarter INTEGER,
            cfo REAL, cfi REAL, cff REAL, capex REAL, fcf REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_meta (
            symbol TEXT PRIMARY KEY, updated_at TEXT
        );
    ''')
    conn.commit()

# ===== HELPERS =====

def should_skip(updated_at_map, symbol):
    updated_at = updated_at_map.get(symbol)
    if not updated_at:
        return False
    cutoff = (datetime.now() - timedelta(days=SKIP_IF_UPDATED_DAYS)).isoformat()
    return updated_at >= cutoff

def safe_float(val):
    try:
        v = float(val)
        return None if (v != v) else v  # NaN check
    except (TypeError, ValueError):
        return None

def extract_wait_time(msg, default=65):
    m = re.search(r'(\d+)\s*(?:giay|second|s\b)', msg.lower())
    return int(m.group(1)) + 2 if m else default

def min_year():
    return datetime.now().year - YEARS_HISTORY

# ===== UPSERT FUNCTIONS =====

def upsert_ratio(conn, symbol, df):
    now = datetime.now().isoformat()
    cutoff = min_year()
    df_T = df.T.copy()
    records = []
    for idx, row in df_T.iterrows():
        try:
            if isinstance(idx, tuple):
                year    = int(idx[0]) if idx[0] else 0
                quarter = int(idx[1]) if len(idx) > 1 and idx[1] else 0
            else:
                m = re.match(r'(\d{4})(?:Q(\d))?', str(idx))
                year    = int(m.group(1)) if m else 0
                quarter = int(m.group(2)) if m and m.group(2) else 0
        except (ValueError, TypeError):
            year = quarter = 0
        if year < cutoff:
            continue
        d = {str(k): v for k, v in row.to_dict().items()}
        rec = [symbol, year, quarter]
        for src, _ in RATIO_MAP.items():
            rec.append(safe_float(d.get(src)))
        rec.append(now)
        records.append(tuple(rec))
    if records:
        cols = ', '.join(RATIO_MAP.values())
        placeholders = ', '.join(['?'] * (3 + len(RATIO_MAP) + 1))
        conn.executemany(
            'INSERT OR REPLACE INTO financials_ratio '
            '(symbol, year, quarter, ' + cols + ', updated_at) '
            'VALUES (' + placeholders + ')',
            records
        )
    return len(records)

def upsert_report(conn, table, field_map, symbol, df):
    now = datetime.now().isoformat()
    cutoff = min_year()
    records = []
    for _, row in df.iterrows():
        d      = {str(k): v for k, v in row.to_dict().items()}
        year   = int(d.get('yearReport',   d.get('year',    0)) or 0)
        length = int(d.get('lengthReport', d.get('quarter', 0)) or 0)
        quarter = 0 if length == 5 else length
        if year < cutoff:
            continue
        rec = [symbol, year, quarter]
        for src, _ in field_map.items():
            rec.append(safe_float(d.get(src)))
        rec.append(now)
        records.append(tuple(rec))
    if records:
        cols = ', '.join(field_map.values())
        placeholders = ', '.join(['?'] * (3 + len(field_map) + 1))
        conn.executemany(
            'INSERT OR REPLACE INTO ' + table +
            ' (symbol, year, quarter, ' + cols + ', updated_at) '
            'VALUES (' + placeholders + ')',
            records
        )
    return len(records)

# ===== TICKERS =====

def get_tickers():
    if TEST_MODE:
        log.info('[TEST MODE] Chi lay %d ma: %s', len(TEST_SYMBOLS), TEST_SYMBOLS)
        return TEST_SYMBOLS
    from vnstock import Listing
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

# ===== FETCH + SAVE =====

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
            log.warning('[%s] Rate limit -> sleep %ds (retry %d/4)', symbol, wait, retry+1)
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
                t = 2 ** retry
                log.warning('[%s] Loi: %s -> retry %d/4 sau %ds', symbol, e, retry+1, t)
                time.sleep(t)
            retry += 1
    return None

def save_symbol(conn, symbol, data):
    try:
        if 'ratio' in data:
            upsert_ratio(conn, symbol, data['ratio'])
        if 'income' in data:
            upsert_report(conn, 'financials_income', INCOME_MAP, symbol, data['income'])
        if 'balance' in data:
            upsert_report(conn, 'financials_balance', BALANCE_MAP, symbol, data['balance'])
        if 'cashflow' in data:
            upsert_report(conn, 'financials_cashflow', CASHFLOW_MAP, symbol, data['cashflow'])
        conn.execute(
            'INSERT OR REPLACE INTO financials_meta (symbol, updated_at) VALUES (?, ?)',
            (symbol, datetime.now().isoformat())
        )
        conn.commit()
        return True
    except Exception as e:
        log.warning('[%s] Save loi: %s', symbol, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False

# ===== MAIN =====

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
    log.info('Todo: %d | Skip: %d | Cutoff: %d nam tro lai', len(todo), skipped, YEARS_HISTORY)

    ok = fail = 0
    for i, symbol in enumerate(todo):
        data = fetch_symbol(symbol)
        if data is None:
            fail += 1
            log.warning('FAIL %s (%d/%d)', symbol, i+1, len(todo))
        else:
            if save_symbol(conn, symbol, data):
                ok += 1
                log.info('OK %s (%d/%d)', symbol, i+1, len(todo))
            else:
                fail += 1

    # VACUUM de compact DB sau khi write
    log.info('VACUUM DB...')
    conn.execute('VACUUM;')
    conn.close()
    log.info('Done -- OK: %d | Skipped: %d | Failed: %d', ok, skipped, fail)

if __name__ == '__main__':
    fetch_financials()
