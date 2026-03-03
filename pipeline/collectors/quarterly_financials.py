# quarterly_financials.py - normalized schema, multi-worker, batch commit
# 728 symbols x 20 quarters x 4 tables x ~150 bytes = ~8MB DB
#
# ARCHITECTURE:
#   - 2 fetch workers (network I/O parallel) + staggered start 6s
#   - Shared GlobalRateController giữ tổng <= 60 RPM
#   - Batch commit mỗi COMMIT_BATCH symbols (giảm fsync ~20x)
#   - to_dict('records') thay iterrows() (~30-40% nhanh hơn)
#   - VACUUM chỉ chạy production + DB > 10MB
#   - Index trên pe/roe/revenue_growth cho scan

from vnstock import Listing, Finance
from datetime import datetime, timedelta
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3
import pandas as pd
import queue
import logging
import sys
import os
import time
import re
import threading

DB_PATH              = os.getenv('DB_PATH', 'data/db/stock.db')
API_KEY              = os.getenv('VNSTOCK_API_KEY', '')
MAX_RPM              = 60  # interval throttle: 60 RPM = 1s/req
SKIP_IF_UPDATED_DAYS = 80
YEARS_HISTORY        = 5
MAX_WORKERS          = 2      # 2 workers with staggered start
WORKER_STAGGER_SEC   = 6      # 6 giây giữa mỗi worker start
COMMIT_BATCH         = 25     # commit sau bao nhieu symbol
VACUUM_THRESHOLD_MB  = 10     # chi VACUUM neu DB > threshold
TEST_MODE            = os.getenv('TEST_MODE', '').lower() in ('1', 'true', 'yes')
TEST_SYMBOLS         = ['VCB', 'FPT', 'VIC']   # chi dung khi TEST_MODE=true

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ===== STDOUT CAPTURE - parse wait time tu vnstock rate limit message =====

class _WaitCapture:
    """Wrap sys.stdout, bat wait time tu message rate limit cua vnstock."""
    def __init__(self, real):
        self._real = real
    def write(self, s):
        self._real.write(s)
        m = re.search(r'Ch[oờ]\s*(\d+)\s*gi[aâ]y', s)
        if not m:
            m = re.search(r'wait\s+(?:for\s+)?(\d+)\s*s', s, re.I)
        if m:
            wait = int(m.group(1)) + 5
            try:
                limiter.set_server_wait(wait)
            except NameError:
                pass
    def flush(self):
        self._real.flush()
    def __getattr__(self, name):
        return getattr(self._real, name)

sys.stdout = _WaitCapture(sys.stdout)

# ===== FIELD MAPPINGS (vnstock -> normalized) =====

RATIO_MAP = {
    'Chỉ tiêu định giá_P/E':                              'pe',
    'Chỉ tiêu định giá_P/B':                              'pb',
    'Chỉ tiêu định giá_P/S':                              'ps',
    'Chỉ tiêu định giá_EV/EBITDA':                        'ev_ebitda',
    'Chỉ tiêu khả năng sinh lợi_ROA (%)':                 'roa',
    'Chỉ tiêu khả năng sinh lợi_ROE (%)':                 'roe',
    'Chỉ tiêu khả năng sinh lợi_ROIC (%)':                'roic',
    'Chỉ tiêu khả năng sinh lợi_Gross Profit Margin (%)': 'gross_margin',
    'Chỉ tiêu khả năng sinh lợi_Net Profit Margin (%)':   'net_margin',
    'Chỉ tiêu cơ cấu nguồn vốn_Debt/Equity':              'debt_equity',
    'Chỉ tiêu thanh khoản_Current Ratio':                  'current_ratio',
    'Chỉ tiêu thanh khoản_Quick Ratio':                    'quick_ratio',
}

INCOME_MAP = {
    'Revenue (Bn. VND)':              'revenue',
    'Gross Profit':                   'gross_profit',
    'Operating Profit/Loss':          'operating_profit',
    'Profit before tax':              'ebit',
    'Net Profit For the Year':        'net_profit',
    'Attributable to parent company': 'net_profit_parent',
    'Revenue YoY (%)':                'revenue_growth',
}

BALANCE_MAP = {
    'TOTAL ASSETS (Bn. VND)':                'total_assets',
    "OWNER'S EQUITY(Bn.VND)":               'total_equity',
    'LIABILITIES (Bn. VND)':                'total_debt',
    'Cash and cash equivalents (Bn. VND)':  'cash',
    'Short-term borrowings (Bn. VND)':      'short_term_debt',
    'Long-term borrowings (Bn. VND)':       'long_term_debt',
}

CASHFLOW_MAP = {
    'Net cash inflows/outflows from operating activities': 'cfo',
    'Net Cash Flows from Investing Activities':            'cfi',
    'Cash flows from financial activities':                'cff',
    'Purchase of fixed assets':                            'capex',
}

# ===== RATE LIMITER (thread-safe, shared across workers) =====

class GlobalRateController:
    """
    Interval-based throttle: 1 request moi min_interval giay.
    Khong bao gio burst. Co global cooldown khi server bao rate limit.
    """
    def __init__(self, rpm):
        self.min_interval = 60.0 / rpm
        self.lock         = threading.Lock()
        self.last_call    = 0.0
        self.pause_until  = 0.0
        self._server_wait = None

    def acquire(self, worker_id=None):
        while True:
            with self.lock:
                now = time.time()
                if now < self.pause_until:
                    sleep_time = self.pause_until - now
                else:
                    next_allowed = self.last_call + self.min_interval
                    if now >= next_allowed:
                        self.last_call = now
                        if self._server_wait and now > self.pause_until:
                            self._server_wait = None
                        return
                    sleep_time = next_allowed - now
            _slept = 0
            while _slept < sleep_time:
                chunk = min(10, sleep_time - _slept)
                time.sleep(chunk)
                _slept += chunk
                if _slept < sleep_time:
                    prefix = f'[W{worker_id}] ' if worker_id is not None else ''
                    log.info('%sRate limiter: cho them %.0fs...', prefix, sleep_time - _slept)
                    sys.stdout.flush()

    def set_server_wait(self, seconds):
        with self.lock:
            self._server_wait = seconds

    def trigger_cooldown(self, fallback=65):
        with self.lock:
            now = time.time()
            seconds = self._server_wait if self._server_wait else fallback
            new_pause = now + seconds
            if new_pause > self.pause_until:
                self.pause_until = new_pause
                self.last_call   = new_pause
                log.info('Global cooldown: %ds (server wait)', seconds)
                sys.stdout.flush()
            else:
                seconds = max(1, int(self.pause_until - now))
            return seconds

    def reset(self):
        with self.lock:
            self.pause_until  = 0.0
            self.last_call    = 0.0
            self._server_wait = None

limiter = GlobalRateController(MAX_RPM)

# ===== DATABASE =====

def create_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    conn.execute('PRAGMA busy_timeout=60000;')
    return conn

def init_db(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS financials_meta (
            symbol TEXT PRIMARY KEY,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS financials_ratio (
            symbol TEXT, year INT, quarter INT,
            pe REAL, pb REAL, ps REAL, ev_ebitda REAL,
            roa REAL, roe REAL, roic REAL,
            gross_margin REAL, net_margin REAL,
            debt_equity REAL, current_ratio REAL, quick_ratio REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_income (
            symbol TEXT, year INT, quarter INT,
            revenue REAL, gross_profit REAL, operating_profit REAL,
            ebit REAL, net_profit REAL, net_profit_parent REAL,
            revenue_growth REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_balance (
            symbol TEXT, year INT, quarter INT,
            total_assets REAL, total_equity REAL, total_debt REAL,
            cash REAL, short_term_debt REAL, long_term_debt REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_cashflow (
            symbol TEXT, year INT, quarter INT,
            cfo REAL, cfi REAL, cff REAL, capex REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE INDEX IF NOT EXISTS idx_ratio_pe ON financials_ratio(pe);
        CREATE INDEX IF NOT EXISTS idx_ratio_roe ON financials_ratio(roe);
        CREATE INDEX IF NOT EXISTS idx_income_growth ON financials_income(revenue_growth);
    ''')
    conn.commit()

def should_skip(updated_at_map, symbol):
    if symbol not in updated_at_map:
        return False
    try:
        dt = datetime.fromisoformat(updated_at_map[symbol])
        return (datetime.now() - dt).days < SKIP_IF_UPDATED_DAYS
    except Exception:
        return False

def extract_wait_time(msg):
    m = re.search(r'(\d+)\s*gi[aâ]y', msg, re.I)
    if m:
        return int(m.group(1)) + 5
    m = re.search(r'(\d+)\s*s', msg, re.I)
    if m:
        return int(m.group(1)) + 5
    return 65

# ===== UPSERT FUNCTIONS =====

def parse_quarter(col_name):
    m = re.search(r'Q(\d)\s*(\d{4})', col_name)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r'(\d{4})\s*Q(\d)', col_name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d{4})', col_name)
    if m:
        return int(m.group(1)), 0
    return None, None

def upsert_ratio(conn, symbol, df):
    if df is None or df.empty:
        return 0
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ['_'.join(str(c) for c in col).strip() for col in df.columns.values]
    df = df.T
    df.index.name = 'quarter_col'
    df = df.reset_index()

    cutoff = datetime.now().year - YEARS_HISTORY
    records = []
    now = datetime.now().isoformat()

    for rec in df.to_dict('records'):
        qcol = rec.get('quarter_col', '')
        year, qtr = parse_quarter(str(qcol))
        if year is None or year < cutoff:
            continue
        row = {'symbol': symbol, 'year': year, 'quarter': qtr, 'updated_at': now}
        for src, dst in RATIO_MAP.items():
            val = rec.get(src)
            row[dst] = None if val is None or (isinstance(val, float) and val != val) else val
        records.append(tuple(row.values()))

    if records:
        conn.executemany(
            '''INSERT OR REPLACE INTO financials_ratio
               (symbol, year, quarter, pe, pb, ps, ev_ebitda,
                roa, roe, roic, gross_margin, net_margin,
                debt_equity, current_ratio, quick_ratio, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            records
        )
    return len(records)

def upsert_report(conn, table, field_map, symbol, df):
    if df is None or df.empty:
        return 0
    cutoff = datetime.now().year - YEARS_HISTORY
    now = datetime.now().isoformat()
    records = []

    quarter_cols = [c for c in df.columns if re.search(r'Q\d|20\d\d', str(c))]

    for qcol in quarter_cols:
        year, qtr = parse_quarter(str(qcol))
        if year is None or year < cutoff:
            continue
        row_dict = {'symbol': symbol, 'year': year, 'quarter': qtr}
        for src, dst in field_map.items():
            matches = df[df.index.astype(str).str.contains(src, case=False, na=False)]
            if not matches.empty:
                val = matches[qcol].iloc[0]
                row_dict[dst] = None if val is None or (isinstance(val, float) and val != val) else val
            else:
                row_dict[dst] = None
        row_dict['updated_at'] = now
        records.append(row_dict)

    if records:
        cols = [k for k in records[0].keys() if k not in ('symbol', 'year', 'quarter', 'updated_at')]
        cols_sql = ', '.join(cols)
        placeholders = ', '.join(['?'] * (4 + len(cols)))
        for rec in records:
            vals = [rec['symbol'], rec['year'], rec['quarter']]
            vals.extend(rec[c] for c in cols)
            vals.append(rec['updated_at'])
            conn.execute(
                f'INSERT OR REPLACE INTO {table} (symbol, year, quarter, {cols_sql}, updated_at) VALUES ({placeholders})',
                vals
            )
    return len(records)

# ===== TICKERS =====

def get_tickers():
    if TEST_MODE:
        log.info('[TEST MODE] Chi lay %d ma: %s', len(TEST_SYMBOLS), TEST_SYMBOLS)
        return TEST_SYMBOLS
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

# ===== FETCH (chạy trong worker thread) =====

def _chunked_sleep(seconds, chunk=10, worker_id=None):
    remaining = seconds
    prefix = f'[W{worker_id}] ' if worker_id is not None else ''
    while remaining > 0:
        t = min(chunk, remaining)
        time.sleep(t)
        remaining -= t
        if remaining > 0:
            log.info('%s... cho them %.0fs', prefix, remaining)
            sys.stdout.flush()

def fetch_symbol(symbol, worker_id=None):
    prefix = f'[W{worker_id}] ' if worker_id is not None else ''
    retry = 0
    while retry < 4:
        try:
            limiter.acquire(worker_id)
            log.info('%sFETCH %s - Dang goi API...', prefix, symbol)
            f = Finance(symbol=symbol, source='VCI', period='quarter', get_all=True)
            result = {}
            
            try:
                df = f.ratio()
                if df is not None and not df.empty:
                    result['ratio'] = df
                    log.info('%s  %s ratio: %d records', prefix, symbol, len(df))
            except Exception as e:
                log.warning('%s  %s ratio loi: %s', prefix, symbol, e)
            
            for key, method in [
                ('income',   f.income_statement),
                ('balance',  f.balance_sheet),
                ('cashflow', f.cash_flow),
            ]:
                try:
                    df = method()
                    if df is not None and not df.empty:
                        result[key] = df
                        log.info('%s  %s %s: %d records', prefix, symbol, key, len(df))
                except Exception as e:
                    log.warning('%s  %s %s loi: %s', prefix, symbol, key, e)
            
            tables_ok = len(result)
            log.info('%sFETCH %s DONE - %d/4 tables', prefix, symbol, tables_ok)
            return result
            
        except SystemExit:
            wait = limiter.trigger_cooldown(fallback=65)
            log.warning('%s%s Rate limit -> global cooldown %ds (retry %d/4)', prefix, symbol, wait, retry+1)
            _chunked_sleep(wait, worker_id=worker_id)
            retry += 1
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ['429', 'rate limit', 'exceeded', 'giới hạn']):
                wait = limiter.trigger_cooldown(fallback=extract_wait_time(str(e)))
                log.warning('%s%s Rate limit -> global cooldown %ds (retry %d/4)', prefix, symbol, wait, retry+1)
                _chunked_sleep(wait, worker_id=worker_id)
            else:
                t = 2 ** retry
                log.warning('%s%s Loi: %s -> retry %d/4 sau %ds', prefix, symbol, e, retry+1, t)
                time.sleep(t)
            retry += 1
    
    log.error('%sFETCH %s FAILED sau 4 retries', prefix, symbol)
    return None

# ===== SAVE =====

def save_symbol(conn, symbol, data, worker_id=None):
    prefix = f'[W{worker_id}] ' if worker_id is not None else ''
    try:
        saved = 0
        if 'ratio' in data:
            n = upsert_ratio(conn, symbol, data['ratio'])
            saved += n
        if 'income' in data:
            n = upsert_report(conn, 'financials_income', INCOME_MAP, symbol, data['income'])
            saved += n
        if 'balance' in data:
            n = upsert_report(conn, 'financials_balance', BALANCE_MAP, symbol, data['balance'])
            saved += n
        if 'cashflow' in data:
            n = upsert_report(conn, 'financials_cashflow', CASHFLOW_MAP, symbol, data['cashflow'])
            saved += n
        conn.execute(
            'INSERT OR REPLACE INTO financials_meta (symbol, updated_at) VALUES (?, ?)',
            (symbol, datetime.now().isoformat())
        )
        log.info('%sSAVE %s - %d quarters saved to DB', prefix, symbol, saved)
        return True
    except Exception as e:
        log.warning('%sSAVE %s loi: %s', prefix, symbol, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False

# ===== WORKER WRAPPER với Staggered Start =====

def worker_fetch(symbol, worker_id, start_delay):
    if start_delay > 0:
        log.info('[W%d] Staggered start: doi %ds truoc khi bat dau...', worker_id, start_delay)
        time.sleep(start_delay)
        log.info('[W%d] Bat dau lam viec!', worker_id)
    
    return fetch_symbol(symbol, worker_id)

# ===== MAIN =====

def fetch_financials():
    log.info('=' * 60)
    log.info('QUARTERLY FINANCIALS COLLECTOR')
    log.info('=' * 60)
    
    if API_KEY:
        os.environ['VNSTOCK_API_KEY'] = API_KEY
        log.info('Using API key')
    else:
        log.warning('Guest mode (no API key)')
    
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else '.', exist_ok=True)

    conn = create_connection()
    init_db(conn)
    updated_at_map = dict(conn.execute('SELECT symbol, updated_at FROM financials_meta').fetchall())

    tickers = get_tickers()
    if TEST_MODE:
        todo    = tickers
        skipped = 0
        log.info('[TEST MODE] Buoc qua kiem tra skip, luon fetch lai')
    else:
        todo    = [s for s in tickers if not should_skip(updated_at_map, s)]
        skipped = len(tickers) - len(todo)
    
    log.info('-' * 40)
    log.info('Todo: %d | Skip: %d | Cutoff: %d nam', len(todo), skipped, YEARS_HISTORY)
    log.info('-' * 40)

    if not todo:
        log.info('Khong co gi can update.')
        conn.close()
        return

    ok = fail = 0
    total = len(todo)

    workers = min(MAX_WORKERS, total) if not TEST_MODE else 1
    log.info('Config: %d workers | Stagger: %ds | Batch commit: %d', workers, WORKER_STAGGER_SEC, COMMIT_BATCH)
    log.info('Rate limit: %d RPM (%.1fs/request)', MAX_RPM, 60.0/MAX_RPM)
    log.info('=' * 60)

    worker_counter = [0]
    worker_lock = threading.Lock()
    worker_start_times = {}

    def get_worker_id_and_delay():
        with worker_lock:
            wid = worker_counter[0] % workers
            if wid not in worker_start_times:
                delay = wid * WORKER_STAGGER_SEC
                worker_start_times[wid] = True
            else:
                delay = 0
            worker_counter[0] += 1
            return wid, delay

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for symbol in todo:
            wid, delay = get_worker_id_and_delay()
            future = executor.submit(worker_fetch, symbol, wid, delay)
            futures[future] = (symbol, wid)
        
        done_count = 0
        
        for future in as_completed(futures):
            symbol, wid = futures[future]
            done_count += 1
            prefix = f'[W{wid}] '
            
            try:
                data = future.result()
            except Exception as e:
                log.error('%sFAIL %s (%d/%d) exception: %s', prefix, symbol, done_count, total, e)
                fail += 1
                continue

            if data is None:
                fail += 1
                log.warning('%sFAIL %s (%d/%d)', prefix, symbol, done_count, total)
            else:
                if save_symbol(conn, symbol, data, wid):
                    ok += 1
                    log.info('%sOK %s (%d/%d)', prefix, symbol, done_count, total)
                else:
                    fail += 1

            if done_count % COMMIT_BATCH == 0:
                conn.commit()
                log.info('--- COMMIT batch (%d/%d) ---', done_count, total)
                sys.stdout.flush()

    conn.commit()
    log.info('--- FINAL COMMIT ---')

    if not TEST_MODE:
        db_size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
        if db_size_mb > VACUUM_THRESHOLD_MB:
            log.info('VACUUM DB (%.1f MB > %d MB threshold)...', db_size_mb, VACUUM_THRESHOLD_MB)
            conn.execute('VACUUM;')
        else:
            log.info('Skip VACUUM (DB %.1f MB < %d MB threshold)', db_size_mb, VACUUM_THRESHOLD_MB)
    else:
        log.info('[TEST MODE] Skip VACUUM')

    conn.close()
    
    log.info('=' * 60)
    log.info('SUMMARY: OK=%d | Skipped=%d | Failed=%d', ok, skipped, fail)
    log.info('=' * 60)

if __name__ == '__main__':
    fetch_financials()
