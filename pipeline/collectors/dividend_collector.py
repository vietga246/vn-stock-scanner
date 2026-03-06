"""
dividend_collector.py — Dividend History Collector

Thu thập lịch sử chia cổ tức (tiền mặt + cổ phiếu) cho HOSE + HNX.

Features:
- Lưu vào bảng dividends (symbol, ex_date, cash_div, stock_div_ratio, ...)
- Skip symbol đã cập nhật trong SKIP_DAYS ngày
- Tính dividend_yield TTM (trailing 12 months) → lưu vào symbols.dividend_yield
- AdaptiveRateLimiter 40 RPM
- TEST_MODE: chỉ chạy VN30
- Inspect log sau khi collect

Chạy:
    python pipeline/collectors/dividend_collector.py
    TEST_MODE=true python pipeline/collectors/dividend_collector.py
"""

from vnstock import Listing, Company
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import logging
import sys
import os
import time

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import (
    AdaptiveRateLimiter,
    normalize_date,
    safe_float,
    safe_int,
    is_stock,
    create_db_connection,
    setup_logging,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH      = os.getenv("DB_PATH",          "data/db/stock.db")
API_KEY      = os.getenv("VNSTOCK_API_KEY",  "")
SKIP_DAYS    = int(os.getenv("SKIP_DAYS",    "30"))
MAX_RPM      = 40
MAX_RETRY    = 2
COMMIT_BATCH = 20
TEST_MODE    = os.getenv("TEST_MODE", "false").lower() == "true"

VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dividends (
            symbol          TEXT,
            ex_date         TEXT,       -- ngày giao dịch không hưởng quyền (YYYY-MM-DD)
            record_date     TEXT,       -- ngày chốt danh sách
            payment_date    TEXT,       -- ngày thanh toán
            cash_div        REAL,       -- cổ tức tiền mặt (VND/cp)
            stock_div_ratio REAL,       -- tỷ lệ cổ phiếu thưởng (0.1 = 10%)
            issue_price     REAL,       -- giá phát hành (nếu có)
            year            INTEGER,
            period_type     TEXT,       -- 'annual'|'interim'|'special'
            updated_at      TEXT,
            PRIMARY KEY (symbol, ex_date)
        );

        CREATE INDEX IF NOT EXISTS idx_dividends_symbol
            ON dividends(symbol);
        CREATE INDEX IF NOT EXISTS idx_dividends_exdate
            ON dividends(ex_date DESC);
        CREATE INDEX IF NOT EXISTS idx_dividends_year
            ON dividends(year DESC);
    """)

    # Thêm cột dividend_yield vào symbols nếu chưa có
    cols = [r[1] for r in conn.execute("PRAGMA table_info(symbols)").fetchall()]
    if "dividend_yield" not in cols:
        conn.execute("ALTER TABLE symbols ADD COLUMN dividend_yield REAL")
        log.info("✅ Đã thêm cột dividend_yield vào bảng symbols")

    conn.commit()
    log.info("✅ DB initialized — bảng dividends OK")


def get_skip_set(conn: sqlite3.Connection) -> set:
    """Lấy symbols đã cập nhật dividend trong SKIP_DAYS ngày."""
    cutoff = (datetime.now() - timedelta(days=SKIP_DAYS)).isoformat()
    rows = conn.execute("""
        SELECT DISTINCT symbol FROM dividends
        WHERE updated_at >= ?
    """, (cutoff,)).fetchall()
    return {r[0] for r in rows}


# ─── PARSE ─────────────────────────────────────────────────────────────────

def _classify_period(year: int | None, description: str | None) -> str:
    """Phân loại loại cổ tức: annual / interim / special."""
    if not description:
        return "annual"
    d = str(description).lower()
    if any(k in d for k in ["interim", "tạm ứng", "giữa kỳ", "q1", "q2", "q3", "quý"]):
        return "interim"
    if any(k in d for k in ["special", "đặc biệt", "bất thường"]):
        return "special"
    return "annual"


def parse_dividend_row(symbol: str, row: dict) -> dict | None:
    """
    Chuyển 1 row từ Company.dividends() DataFrame thành dict để INSERT.
    vnstock có thể trả về nhiều tên cột khác nhau.
    """
    # Chuẩn hóa keys
    d = {k.lower().strip(): v for k, v in row.items()}

    # ex_date — bắt buộc
    raw_ex = (d.get("ex_date") or d.get("exercise_date") or
              d.get("ex_rights_date") or d.get("exdate") or
              d.get("ngay_gdkhq") or d.get("date"))
    ex_date = normalize_date(raw_ex)
    if not ex_date:
        return None

    # cash_div
    cash_raw = (d.get("cash_dividend") or d.get("cash_div") or
                d.get("dividend") or d.get("tien_mat") or
                d.get("cash_dividends_per_share") or d.get("value"))
    cash_div = safe_float(cash_raw)

    # stock_div_ratio
    stock_raw = (d.get("stock_dividend") or d.get("stock_div") or
                 d.get("stock_ratio") or d.get("co_phieu_thuong") or
                 d.get("bonus_share_ratio"))
    stock_div = safe_float(stock_raw)
    if stock_div and stock_div > 1:     # nếu API trả về % (10 thay vì 0.1)
        stock_div = stock_div / 100.0

    # Lọc bỏ row không có dữ liệu thực
    if cash_div is None and stock_div is None:
        return None

    # year
    year_raw = d.get("year") or d.get("nam")
    year = safe_int(year_raw)
    if not year and ex_date:
        try:
            year = int(ex_date[:4])
        except Exception:
            pass

    return {
        "symbol":          symbol,
        "ex_date":         ex_date,
        "record_date":     normalize_date(d.get("record_date") or d.get("ngay_chot_ds")),
        "payment_date":    normalize_date(d.get("payment_date") or d.get("ngay_thanh_toan")),
        "cash_div":        cash_div,
        "stock_div_ratio": stock_div,
        "issue_price":     safe_float(d.get("issue_price") or d.get("gia_phat_hanh")),
        "year":            year,
        "period_type":     _classify_period(year, str(d.get("description", ""))),
        "updated_at":      datetime.now().isoformat(),
    }


# ─── FETCH ─────────────────────────────────────────────────────────────────

def fetch_dividends(symbol: str) -> list[dict]:
    """Lấy lịch sử cổ tức từ Company.dividends()."""
    try:
        company = Company(symbol=symbol, source="VCI")
        df = company.dividends()

        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            parsed = parse_dividend_row(symbol, row.to_dict())
            if parsed:
                results.append(parsed)

        log.debug("[%s] Fetched %d dividend records", symbol, len(results))
        return results

    except Exception as e:
        log.debug("[%s] dividends() failed: %s", symbol, e)
        return []


# ─── CALC DIVIDEND YIELD ───────────────────────────────────────────────────

def compute_ttm_yield(conn: sqlite3.Connection, symbol: str) -> float | None:
    """
    Tính dividend yield TTM (trailing 12 months):
    Tổng cash_div trong 12 tháng qua / giá đóng cửa gần nhất.
    """
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    row = conn.execute("""
        SELECT SUM(cash_div) FROM dividends
        WHERE symbol = ? AND ex_date >= ? AND cash_div IS NOT NULL
    """, (symbol, one_year_ago)).fetchone()

    total_cash = safe_float(row[0]) if row else None
    if not total_cash:
        return None

    # Lấy giá đóng cửa gần nhất
    price_row = conn.execute("""
        SELECT close FROM stock_prices
        WHERE symbol = ? ORDER BY date DESC LIMIT 1
    """, (symbol,)).fetchone()

    if not price_row or not price_row[0]:
        return None

    price = safe_float(price_row[0])
    if not price or price == 0:
        return None

    yield_pct = total_cash / price * 100
    return round(yield_pct, 2)


# ─── INSPECT ───────────────────────────────────────────────────────────────

def inspect(conn: sqlite3.Connection):
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  INSPECT — dividends")
    print(sep)

    # Tổng quan
    total_sym = conn.execute("SELECT COUNT(DISTINCT symbol) FROM dividends").fetchone()[0]
    total_rec = conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0]
    print(f"  Symbols có lịch sử cổ tức : {total_sym}")
    print(f"  Tổng dividend records      : {total_rec}")

    # Thống kê theo năm
    by_year = conn.execute("""
        SELECT year,
               COUNT(DISTINCT symbol) AS symbols,
               COUNT(*) AS events,
               ROUND(AVG(cash_div), 0) AS avg_cash_div,
               SUM(CASE WHEN stock_div_ratio > 0 THEN 1 ELSE 0 END) AS stock_div_count
        FROM dividends
        WHERE year IS NOT NULL
        GROUP BY year
        ORDER BY year DESC
        LIMIT 6
    """).fetchall()
    if by_year:
        print(f"\n  Thống kê theo năm:")
        print(f"  {'Year':>6} {'Symbols':>8} {'Events':>8} {'Avg Cash':>10} {'Stock Div':>10}")
        print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*10} {'-'*10}")
        for r in by_year:
            print(f"  {(r[0] or 0):>6} {r[1]:>8} {r[2]:>8} {(r[3] or 0):>10,.0f} {r[4]:>10}")

    # Top 10 cổ tức tiền mặt cao nhất (mới nhất)
    top_div = conn.execute("""
        SELECT d.symbol, s.organ_name,
               d.ex_date, d.cash_div, d.stock_div_ratio, d.year
        FROM dividends d
        LEFT JOIN symbols s ON d.symbol = s.symbol
        WHERE d.cash_div IS NOT NULL
          AND d.ex_date >= date('now', '-2 years')
        ORDER BY d.cash_div DESC
        LIMIT 10
    """).fetchall()
    if top_div:
        print(f"\n  Top 10 — Cổ tức tiền mặt cao nhất (2 năm gần nhất):")
        print(f"  {'Symbol':<8} {'Tên công ty':<30} {'Ex-date':<12} {'Cash/cp':>10} {'Stock%':>7} {'Year':>5}")
        print(f"  {'-'*8} {'-'*30} {'-'*12} {'-'*10} {'-'*7} {'-'*5}")
        for r in top_div:
            name = (r[1] or "")[:29]
            stock_pct = f"{r[4]*100:.1f}%" if r[4] else "-"
            print(f"  {r[0]:<8} {name:<30} {r[2]:<12} {r[3]:>10,.0f} {stock_pct:>7} {(r[5] or 0):>5}")

    # Symbols có dividend_yield > 5%
    high_yield = conn.execute("""
        SELECT s.symbol, s.organ_name, ROUND(s.dividend_yield, 2) AS dy
        FROM symbols s
        WHERE s.dividend_yield >= 5
        ORDER BY s.dividend_yield DESC
        LIMIT 10
    """).fetchall()
    if high_yield:
        print(f"\n  Symbols Dividend Yield ≥ 5% (TTM):")
        print(f"  {'Symbol':<8} {'Tên công ty':<35} {'Yield%':>8}")
        print(f"  {'-'*8} {'-'*35} {'-'*8}")
        for r in high_yield:
            print(f"  {r[0]:<8} {(r[1] or '')[:34]:<35} {r[2]:>8.2f}%")

    print(f"\n{sep}\n")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def collect_dividends():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")

    log.info("─" * 60)
    log.info("💰 Dividend Collector")
    log.info("   TEST_MODE: %s | SKIP_DAYS: %d", TEST_MODE, SKIP_DAYS)
    log.info("─" * 60)

    # Lấy danh sách symbols
    if TEST_MODE:
        symbols = VN30_SYMBOLS.copy()
        log.info("[TEST MODE] VN30: %d symbols", len(symbols))
    else:
        try:
            listing = Listing()
            df = listing.symbols_by_exchange()
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            symbols = [t for t in df["symbol"].tolist() if is_stock(t)]
            log.info("Loaded %d symbols (HOSE+HNX)", len(symbols))
        except Exception as e:
            log.error("Không lấy được symbols: %s — fallback VN30", e)
            symbols = VN30_SYMBOLS.copy()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = create_db_connection(DB_PATH)
    init_db(conn)

    # Skip set
    skip_set = get_skip_set(conn)
    todo = [s for s in symbols if s not in skip_set]
    log.info("Cần fetch: %d | Đã có (skip): %d", len(todo), len(symbols) - len(todo))

    limiter = AdaptiveRateLimiter(rpm=MAX_RPM)

    ok = skipped_empty = batch_count = yield_updated = 0

    for i, symbol in enumerate(todo, 1):
        limiter.acquire()

        records = fetch_dividends(symbol)

        if not records:
            skipped_empty += 1
            if i % 50 == 0:
                log.info("Progress: %d/%d | ok=%d empty=%d", i, len(todo), ok, skipped_empty)
            continue

        # Insert records
        inserted = 0
        for rec in records:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO dividends
                        (symbol, ex_date, record_date, payment_date,
                         cash_div, stock_div_ratio, issue_price,
                         year, period_type, updated_at)
                    VALUES
                        (:symbol, :ex_date, :record_date, :payment_date,
                         :cash_div, :stock_div_ratio, :issue_price,
                         :year, :period_type, :updated_at)
                """, rec)
                inserted += 1
            except Exception as e:
                log.debug("[%s] insert error: %s", symbol, e)

        # Tính và cập nhật dividend_yield TTM
        dy = compute_ttm_yield(conn, symbol)
        if dy is not None:
            conn.execute(
                "UPDATE symbols SET dividend_yield = ? WHERE symbol = ?",
                (dy, symbol)
            )
            yield_updated += 1

        ok += 1
        batch_count += 1
        if batch_count >= COMMIT_BATCH:
            conn.commit()
            batch_count = 0

        if i % 20 == 0:
            log.info("Progress: %d/%d | ok=%d empty=%d yield_updated=%d",
                     i, len(todo), ok, skipped_empty, yield_updated)

    conn.commit()

    log.info("─" * 60)
    log.info("💾 OK: %d | Empty: %d | Yield updated: %d",
             ok, skipped_empty, yield_updated)
    log.info("─" * 60)

    inspect(conn)
    conn.close()


if __name__ == "__main__":
    collect_dividends()
