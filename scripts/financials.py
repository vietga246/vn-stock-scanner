# financials.py - normalized schema, multi-worker, batch commit
# 706 symbols x 20 quarters x 4 tables x ~150 bytes = ~8MB DB
#
# ARCHITECTURE:
#   - 6 fetch workers (network I/O parallel) + 1 write thread (DB serial)
#   - Shared SmartRateLimiter giữ tổng <= 55 RPM
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

DB_PATH              = os.getenv('DB_PATH', 'data/stock.db')
API_KEY              = os.getenv('VNSTOCK_API_KEY', '')
MAX_RPM              = 40  # interval throttle: 60/40 = 1.5s/req, khong bao gio burst
SKIP_IF_UPDATED_DAYS = 80
YEARS_HISTORY        = 5
MAX_WORKERS          = 3      # 3 workers: 45RPM / 4req/symbol = ~11 symbols/phut
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

_last_wait_capture = [None]  # [0] = so giay can cho, None neu chua co

class _WaitCapture:
    """Wrap sys.stdout, bat wait time tu message rate limit cua vnstock."""
    def __init__(self, real):
        self._real = real
    def write(self, s):
        self._real.write(s)
        # Match "Cho 4 giay" hoac "Chờ 56 giây"
        m = re.search(r'Ch[oờ]\s*(\d+)\s*gi[aâ]y', s)
        if m:
            _last_wait_capture[0] = int(m.group(1)) + 2  # +2 buffer
    def flush(self):
        self._real.flush()
    def __getattr__(self, name):
        return getattr(self._real, name)

sys.stdout = _WaitCapture(sys.stdout)

# ===== FIELD MAPPINGS (vnstock -> normalized) =====

# Ratio: MultiIndex columns -> flatten: ('Chỉ tiêu định giá', 'P/E') -> 'Chỉ tiêu định giá_P/E'
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

    Fix burst-after-cooldown: acquire() luon update last_call truoc khi return,
    dam bao worker ke tiep phai doi du min_interval, ke ca sau cooldown.
    3 workers wake up dong thoi nhung chi 1 worker pass gate moi 1.5s.
    """
    def __init__(self, rpm):
        self.min_interval = 60.0 / rpm   # 40 RPM = 1.5s/req
        self.lock         = threading.Lock()
        self.last_call    = 0.0
        self.pause_until  = 0.0

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                # Dang trong global cooldown
                if now < self.pause_until:
                    sleep_time = self.pause_until - now
                else:
                    # Tinh thoi diem som nhat co the gui request tiep theo
                    next_allowed = self.last_call + self.min_interval
                    if now >= next_allowed:
                        # Slot trong: cap phat ngay, update last_call de worker
                        # ke tiep phai doi min_interval (tranh burst dong thoi)
                        self.last_call = now
                        return
                    sleep_time = next_allowed - now
            # Chunked sleep de GitHub Actions khong kill process
            _slept = 0
            while _slept < sleep_time:
                chunk = min(10, sleep_time - _slept)
                time.sleep(chunk)
                _slept += chunk
                if _slept < sleep_time:
                    log.info('Rate limiter: cho them %.0fs...', sleep_time - _slept)
                    sys.stdout.flush()

    def trigger_cooldown(self, seconds):
        """
        Tat ca worker deu phai cho. Sau cooldown, last_call = pause_until
        de worker dau tien phai doi them min_interval, tranh burst ngay.
        """
        with self.lock:
            new_pause = max(self.pause_until, time.time() + seconds)
            if new_pause > self.pause_until:  # chi log khi thay doi
                self.pause_until = new_pause
                # Dat last_call = pause_until: worker dau tien wake up phai
                # doi them 1.5s, worker thu 2 doi 3s, thu 3 doi 4.5s -> stagger
                self.last_call = new_pause
                log.info('Global cooldown: %ds (tat ca worker dung lai, stagger sau do)',
                         seconds)
                sys.stdout.flush()

    def reset(self):
        with self.lock:
            self.pause_until = 0.0
            self.last_call   = 0.0

limiter = GlobalRateController(MAX_RPM)

# ===== DATABASE =====

def create_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    conn.execute('PRAGMA busy_timeout=60000;')
    conn.execute('PRAGMA cache_size=-32000;')   # 32MB cache
    conn.execute('PRAGMA temp_store=MEMORY;')   # sort/index dung RAM
    conn.execute('PRAGMA mmap_size=268435456;') # 256MB mmap (phu hop GitHub runner ~7GB RAM)
    return conn

def init_db(conn):
    # Drop tables neu schema thay doi: kiem tra cac cot bat buoc cua schema moi
    # Neu thieu bat ky cot nao -> drop va recreate
    REQUIRED = {
        'financials_ratio':    {'pe', 'pb', 'roe', 'roa', 'net_margin', 'debt_equity'},
        'financials_income':   {'revenue', 'gross_profit', 'net_profit', 'revenue_growth'},
        'financials_balance':  {'total_assets', 'total_equity', 'total_debt', 'cash'},
        'financials_cashflow': {'cfo', 'cfi', 'cff', 'capex'},
    }
    for table, required_cols in REQUIRED.items():
        try:
            cols = {r[1] for r in conn.execute('PRAGMA table_info(' + table + ')').fetchall()}
            if cols and not required_cols.issubset(cols):
                missing = required_cols - cols
                conn.execute('DROP TABLE ' + table)
                conn.commit()
                log.info('Schema moi: dropped %s (thieu: %s)', table, missing)
        except Exception:
            pass

    conn.executescript('''
        CREATE TABLE IF NOT EXISTS financials_ratio (
            symbol TEXT, year INTEGER, quarter INTEGER,
            pe REAL, pb REAL, ps REAL, ev_ebitda REAL,
            roe REAL, roa REAL, roic REAL,
            gross_margin REAL, net_margin REAL,
            debt_equity REAL,
            current_ratio REAL, quick_ratio REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_income (
            symbol TEXT, year INTEGER, quarter INTEGER,
            revenue REAL, gross_profit REAL, operating_profit REAL,
            ebit REAL, net_profit REAL, net_profit_parent REAL,
            revenue_growth REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_balance (
            symbol TEXT, year INTEGER, quarter INTEGER,
            total_assets REAL, total_equity REAL, total_debt REAL,
            cash REAL, short_term_debt REAL, long_term_debt REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_cashflow (
            symbol TEXT, year INTEGER, quarter INTEGER,
            cfo REAL, cfi REAL, cff REAL, capex REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS financials_meta (
            symbol TEXT PRIMARY KEY, updated_at TEXT
        );

        -- TỐI ƯU CẤP 5: index cho scan nhanh
        CREATE INDEX IF NOT EXISTS idx_ratio_pe             ON financials_ratio(pe);
        CREATE INDEX IF NOT EXISTS idx_ratio_roe            ON financials_ratio(roe);
        CREATE INDEX IF NOT EXISTS idx_ratio_roa            ON financials_ratio(roa);
        CREATE INDEX IF NOT EXISTS idx_income_revenue_growth ON financials_income(revenue_growth);
        CREATE INDEX IF NOT EXISTS idx_ratio_year_quarter   ON financials_ratio(year, quarter);
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

# ===== UPSERT FUNCTIONS (dùng to_dict records thay iterrows) =====

def upsert_ratio(conn, symbol, df):
    now    = datetime.now().isoformat()
    cutoff = min_year()
    # Flatten MultiIndex: ('Category', 'Name') -> 'Category_Name'
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = ['_'.join(str(c) for c in col).strip('_') for col in df.columns]
    records = []
    cols_sql      = ', '.join(RATIO_MAP.values())
    placeholders  = ', '.join(['?'] * (3 + len(RATIO_MAP) + 1))
    # TỐI ƯU CẤP 3: to_dict('records') nhanh hơn iterrows ~35%
    for d in df.to_dict('records'):
        try:
            year    = int(d.get('Meta_yearReport',   0) or 0)
            length  = int(d.get('Meta_lengthReport', 0) or 0)
        except (ValueError, TypeError):
            year = length = 0
        quarter = 0 if length == 5 else length
        if year < cutoff:
            continue
        rec = [symbol, year, quarter] + [safe_float(d.get(src)) for src in RATIO_MAP] + [now]
        records.append(tuple(rec))
    if records:
        conn.executemany(
            'INSERT OR REPLACE INTO financials_ratio '
            '(symbol, year, quarter, ' + cols_sql + ', updated_at) '
            'VALUES (' + placeholders + ')',
            records
        )
    return len(records)

def upsert_report(conn, table, field_map, symbol, df):
    now    = datetime.now().isoformat()
    cutoff = min_year()
    records = []
    cols_sql     = ', '.join(field_map.values())
    placeholders = ', '.join(['?'] * (3 + len(field_map) + 1))
    # TỐI ƯU CẤP 3: to_dict('records')
    for d in df.to_dict('records'):
        try:
            year   = int(d.get('yearReport',   d.get('year',    0)) or 0)
            length = int(d.get('lengthReport', d.get('quarter', 0)) or 0)
        except (ValueError, TypeError):
            year = length = 0
        quarter = 0 if length == 5 else length
        if year < cutoff:
            continue
        rec = [symbol, year, quarter] + [safe_float(d.get(src)) for src in field_map] + [now]
        records.append(tuple(rec))
    if records:
        conn.executemany(
            'INSERT OR REPLACE INTO ' + table +
            ' (symbol, year, quarter, ' + cols_sql + ', updated_at) '
            'VALUES (' + placeholders + ')',
            records
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

def _chunked_sleep(seconds, chunk=10):
    """Sleep theo chunk de GitHub Actions khong kill process vi khong co output."""
    remaining = seconds
    while remaining > 0:
        t = min(chunk, remaining)
        time.sleep(t)
        remaining -= t
        if remaining > 0:
            log.info('  ... cho them %.0fs', remaining)
            sys.stdout.flush()

def fetch_symbol(symbol):
    """Fetch data từ API - chạy song song trong ThreadPoolExecutor."""
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
            # vnstock in message truoc khi raise SystemExit.
            # Lay wait time tu _stdout_capture neu co, fallback = 65s
            wait = _last_wait_capture[0] if _last_wait_capture[0] else 65
            _last_wait_capture[0] = None  # reset
            log.warning('[%s] Rate limit -> global cooldown %ds (retry %d/4)', symbol, wait, retry+1)
            limiter.trigger_cooldown(wait)
            _chunked_sleep(wait)
            retry += 1
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ['429', 'rate limit', 'exceeded', 'giới hạn']):
                wait = extract_wait_time(str(e))
                log.warning('[%s] Rate limit -> global cooldown %ds (retry %d/4)', symbol, wait, retry+1)
                limiter.trigger_cooldown(wait)
                _chunked_sleep(wait)
            else:
                t = 2 ** retry
                log.warning('[%s] Loi: %s -> retry %d/4 sau %ds', symbol, e, retry+1, t)
                time.sleep(t)
            retry += 1
    return None

# ===== SAVE (chạy trong write thread duy nhất) =====

def save_symbol(conn, symbol, data):
    """Write vào DB - chỉ gọi từ write thread để tránh locked."""
    try:
        if 'ratio' in data:
            upsert_ratio(conn, symbol, data['ratio'])
        if 'income' in data:
            upsert_report(conn, 'financials_income',   INCOME_MAP,   symbol, data['income'])
        if 'balance' in data:
            upsert_report(conn, 'financials_balance',  BALANCE_MAP,  symbol, data['balance'])
        if 'cashflow' in data:
            upsert_report(conn, 'financials_cashflow', CASHFLOW_MAP, symbol, data['cashflow'])
        conn.execute(
            'INSERT OR REPLACE INTO financials_meta (symbol, updated_at) VALUES (?, ?)',
            (symbol, datetime.now().isoformat())
        )
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
    log.info('Todo: %d | Skip: %d | Cutoff: %d nam tro lai', len(todo), skipped, YEARS_HISTORY)

    if not todo:
        log.info('Khong co gi can update.')
        conn.close()
        return

    ok = fail = 0
    total = len(todo)

    # TỐI ƯU CẤP 1: fetch parallel (network I/O), write serial (DB)
    # TỐI ƯU CẤP 2: batch commit mỗi COMMIT_BATCH symbols
    workers = min(MAX_WORKERS, total) if not TEST_MODE else 1
    log.info('Workers: %d | Batch commit: %d', workers, COMMIT_BATCH)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Submit tất cả jobs
        future_to_symbol = {executor.submit(fetch_symbol, s): s for s in todo}
        done_count = 0

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            done_count += 1
            try:
                data = future.result()
            except Exception as e:
                log.warning('FAIL %s (%d/%d) exception: %s', symbol, done_count, total, e)
                fail += 1
                continue

            if data is None:
                fail += 1
                log.warning('FAIL %s (%d/%d)', symbol, done_count, total)
            else:
                if save_symbol(conn, symbol, data):
                    ok += 1
                    log.info('OK %s (%d/%d)', symbol, done_count, total)
                else:
                    fail += 1

            # TỐI ƯU CẤP 2: batch commit
            if done_count % COMMIT_BATCH == 0:
                conn.commit()
                log.info('--- Commit batch (%d/%d) ---', done_count, total)

    # Final commit
    conn.commit()

    # TỐI ƯU CẤP 4: VACUUM chỉ khi production + DB đủ lớn
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
    log.info('Done -- OK: %d | Skipped: %d | Failed: %d', ok, skipped, fail)

if __name__ == '__main__':
    fetch_financials()
