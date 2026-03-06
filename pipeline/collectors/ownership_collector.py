"""
ownership_collector.py — Shareholders & Ownership Structure Collector

Thu thập cơ cấu cổ đông cho HOSE + HNX:
  - Tỷ lệ sở hữu: nhà nước, nước ngoài, tổ chức, cá nhân
  - Top shareholders và % sở hữu
  - Foreign ownership room còn lại
  - Cập nhật cột free_float_pct trong bảng symbols

Features:
- HOSE + HNX only, loại bond/warrant
- Skip symbol đã cập nhật trong SKIP_DAYS ngày
- AdaptiveRateLimiter 60 RPM
- TEST_MODE: chỉ chạy VN30
- Inspect log sau khi collect

Chạy:
    python pipeline/collectors/ownership_collector.py
    TEST_MODE=true python pipeline/collectors/ownership_collector.py
"""

from vnstock import Listing, Company
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import json
import logging
import sys
import os
import time

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import (
    AdaptiveRateLimiter,
    safe_float,
    is_stock,
    create_db_connection,
    setup_logging,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH         = os.getenv("DB_PATH", "data/db/stock.db")
API_KEY         = os.getenv("VNSTOCK_API_KEY", "")
SKIP_DAYS       = int(os.getenv("SKIP_DAYS", "30"))          # skip nếu đã cập nhật
MAX_RPM         = 40                                           # conservative
MAX_RETRY       = 2
COMMIT_BATCH    = 20
TEST_MODE       = os.getenv("TEST_MODE", "false").lower() == "true"

VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        -- Bảng cổ đông chính
        CREATE TABLE IF NOT EXISTS shareholders (
            symbol          TEXT,
            holder_name     TEXT,
            holder_type     TEXT,   -- 'state'|'foreign'|'institution'|'individual'|'other'
            shares          REAL,
            pct_ownership   REAL,
            updated_at      TEXT,
            PRIMARY KEY (symbol, holder_name)
        );

        CREATE INDEX IF NOT EXISTS idx_shareholders_symbol
            ON shareholders(symbol);
        CREATE INDEX IF NOT EXISTS idx_shareholders_pct
            ON shareholders(pct_ownership DESC);

        -- Bảng ownership summary (1 row / symbol)
        CREATE TABLE IF NOT EXISTS ownership_summary (
            symbol              TEXT PRIMARY KEY,
            state_pct           REAL,   -- % nhà nước
            foreign_pct         REAL,   -- % nước ngoài hiện tại
            foreign_room_pct    REAL,   -- % room ngoại còn lại
            institution_pct     REAL,   -- % tổ chức trong nước
            individual_pct      REAL,   -- % cá nhân
            free_float_pct      REAL,   -- % free float (ước tính)
            top1_holder         TEXT,
            top1_pct            REAL,
            total_holders       INTEGER,
            updated_at          TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ownership_summary_state
            ON ownership_summary(state_pct);
        CREATE INDEX IF NOT EXISTS idx_ownership_summary_float
            ON ownership_summary(free_float_pct);
    """)

    # Thêm cột free_float_pct vào symbols nếu chưa có
    cols = [r[1] for r in conn.execute("PRAGMA table_info(symbols)").fetchall()]
    if "free_float_pct" not in cols:
        conn.execute("ALTER TABLE symbols ADD COLUMN free_float_pct REAL")
        log.info("✅ Đã thêm cột free_float_pct vào bảng symbols")

    conn.commit()
    log.info("✅ DB initialized — shareholders + ownership_summary OK")


def get_skip_set(conn: sqlite3.Connection) -> set:
    """Lấy tập symbol đã cập nhật trong SKIP_DAYS ngày — bỏ qua."""
    cutoff = (datetime.now() - timedelta(days=SKIP_DAYS)).isoformat()
    rows = conn.execute("""
        SELECT symbol FROM ownership_summary
        WHERE updated_at >= ?
    """, (cutoff,)).fetchall()
    return {r[0] for r in rows}


# ─── FETCH ─────────────────────────────────────────────────────────────────

def classify_holder(name: str) -> str:
    """Phân loại cổ đông theo tên."""
    if not name:
        return "other"
    n = name.upper()
    # Nhà nước / SCIC / Bộ
    if any(k in n for k in ["NHÀ NƯỚC", "SCIC", "BỘ ", "SỞ ", "UBND", "CHÍNH PHỦ", "STATE"]):
        return "state"
    # Nước ngoài
    if any(k in n for k in ["FOREIGN", "FUND", "ASSET MANAGEMENT", "INVESTMENT",
                              "CAPITAL", "PARTNERS", "DRAGON", "VIETNAM HOLDING",
                              "AMERSIAN", "LIMITED", "LTD", "PTE", "KOREA", "JAPAN",
                              "SINGAPORE", "HONGKONG", "CAYMAN", "OFFSHORE"]):
        return "foreign"
    # Tổ chức trong nước
    if any(k in n for k in ["CÔNG TY", "CTY", "BANK", "NGÂN HÀNG", "BẢO HIỂM",
                              "CHỨNG KHOÁN", "QUẢN LÝ QUỸ", "CỔ PHẦN", "TNHH",
                              "CORPORATION", "CORP", "CO.,", "JSC", "JSB"]):
        return "institution"
    return "individual"


def fetch_shareholders(symbol: str) -> tuple[list, dict]:
    """
    Lấy danh sách cổ đông từ Company.shareholders().
    Trả về (list_of_holder_dicts, summary_dict).
    """
    try:
        company = Company(symbol=symbol, source="VCI")
        df = company.shareholders()

        if df is None or df.empty:
            return [], {}

        # Chuẩn hóa column names (vnstock có thể dùng nhiều tên khác nhau)
        df.columns = [c.lower().strip() for c in df.columns]

        # Map các tên cột có thể có
        name_col  = next((c for c in df.columns if "name" in c or "holder" in c or "ten" in c), None)
        share_col = next((c for c in df.columns if "share" in c or "co_phieu" in c or "volume" in c), None)
        pct_col   = next((c for c in df.columns if "pct" in c or "percent" in c or "ratio" in c or "%" in c or "ty_le" in c), None)

        if not name_col and not pct_col:
            log.debug("[%s] Không nhận ra cột shareholders: %s", symbol, list(df.columns))
            return [], {}

        holders = []
        state_pct = foreign_pct = institution_pct = individual_pct = 0.0

        for _, row in df.iterrows():
            name  = str(row.get(name_col,  "") or "").strip() if name_col else ""
            pct   = safe_float(row.get(pct_col,  None)) if pct_col  else None
            shares = safe_float(row.get(share_col, None)) if share_col else None

            if pct and pct > 1:      # nếu API trả về % dưới dạng 45.3 thay vì 0.453
                pct = pct / 100.0

            htype = classify_holder(name)

            holders.append({
                "symbol":        symbol,
                "holder_name":   name or f"Unknown_{len(holders)}",
                "holder_type":   htype,
                "shares":        shares,
                "pct_ownership": pct,
                "updated_at":    datetime.now().isoformat(),
            })

            p = pct or 0
            if htype == "state":       state_pct       += p
            elif htype == "foreign":   foreign_pct     += p
            elif htype == "institution": institution_pct += p
            elif htype == "individual":  individual_pct  += p

        # Ước tính free float = 1 - state_pct - locked_shares_pct
        # Đơn giản: 1 - max(state_pct, 0)
        free_float_pct = max(0.0, 1.0 - state_pct)

        # Top holder
        top = sorted(holders, key=lambda h: h["pct_ownership"] or 0, reverse=True)
        top1 = top[0] if top else {}

        summary = {
            "symbol":           symbol,
            "state_pct":        round(state_pct, 4),
            "foreign_pct":      round(foreign_pct, 4),
            "foreign_room_pct": None,   # sẽ cập nhật từ price_board nếu có
            "institution_pct":  round(institution_pct, 4),
            "individual_pct":   round(individual_pct, 4),
            "free_float_pct":   round(free_float_pct, 4),
            "top1_holder":      top1.get("holder_name"),
            "top1_pct":         top1.get("pct_ownership"),
            "total_holders":    len(holders),
            "updated_at":       datetime.now().isoformat(),
        }

        return holders, summary

    except Exception as e:
        # Company API có thể chưa hỗ trợ hoặc symbol không có data
        log.debug("[%s] shareholders() failed: %s", symbol, e)
        return [], {}


# ─── INSPECT ───────────────────────────────────────────────────────────────

def inspect(conn: sqlite3.Connection):
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  INSPECT — shareholders + ownership_summary")
    print(sep)

    # Tổng quan
    total_sym = conn.execute("SELECT COUNT(DISTINCT symbol) FROM ownership_summary").fetchone()[0]
    total_hol = conn.execute("SELECT COUNT(*) FROM shareholders").fetchone()[0]
    print(f"  Symbols với ownership data : {total_sym}")
    print(f"  Tổng cổ đông records       : {total_hol}")

    # Phân phối state ownership
    rows = conn.execute("""
        SELECT
            SUM(CASE WHEN state_pct >= 0.50 THEN 1 ELSE 0 END) AS majority_state,
            SUM(CASE WHEN state_pct BETWEEN 0.20 AND 0.499 THEN 1 ELSE 0 END) AS minority_state,
            SUM(CASE WHEN state_pct < 0.20 AND state_pct > 0 THEN 1 ELSE 0 END) AS small_state,
            SUM(CASE WHEN state_pct = 0 OR state_pct IS NULL THEN 1 ELSE 0 END) AS no_state
        FROM ownership_summary
    """).fetchone()
    if rows:
        print(f"\n  Phân bổ sở hữu nhà nước:")
        print(f"  Đa số (≥50%)    : {rows[0]} symbols")
        print(f"  Thiểu số (20-50%): {rows[1]} symbols")
        print(f"  Nhỏ (<20%)      : {rows[2]} symbols")
        print(f"  Không có         : {rows[3]} symbols")

    # Top 10 free float thấp nhất (tính thanh khoản bị hạn chế)
    low_float = conn.execute("""
        SELECT symbol, ROUND(state_pct*100,1) as state_pct,
               ROUND(free_float_pct*100,1) as float_pct,
               top1_holder, ROUND(top1_pct*100,1) as top1_pct
        FROM ownership_summary
        WHERE free_float_pct IS NOT NULL AND free_float_pct < 0.5
        ORDER BY free_float_pct ASC
        LIMIT 10
    """).fetchall()
    if low_float:
        print(f"\n  Top symbols FREE FLOAT thấp (<50% — rủi ro thanh khoản):")
        print(f"  {'Symbol':<8} {'State%':>8} {'Float%':>8} {'Top1 Holder':<35} {'Top1%':>6}")
        print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*35} {'-'*6}")
        for r in low_float:
            top1 = (r[3] or "")[:34]
            print(f"  {r[0]:<8} {r[1]:>8.1f} {r[2]:>8.1f} {top1:<35} {(r[4] or 0):>6.1f}")

    # Sample ownership_summary
    sample = conn.execute("""
        SELECT symbol, ROUND(state_pct*100,1), ROUND(foreign_pct*100,1),
               ROUND(institution_pct*100,1), ROUND(free_float_pct*100,1),
               total_holders, updated_at
        FROM ownership_summary
        ORDER BY updated_at DESC
        LIMIT 8
    """).fetchall()
    if sample:
        print(f"\n  Sample ownership_summary (8 mới nhất):")
        print(f"  {'Symbol':<8} {'State%':>7} {'Foreign%':>9} {'Inst%':>7} {'Float%':>7} {'Holders':>8} {'Updated':<20}")
        print(f"  {'-'*8} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*8} {'-'*20}")
        for r in sample:
            print(f"  {r[0]:<8} {r[1]:>7.1f} {r[2]:>9.1f} {r[3]:>7.1f} {r[4]:>7.1f} {r[5]:>8} {r[6][:19]:<20}")

    print(f"\n{sep}\n")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def collect_ownership():
    if API_KEY:
        os.environ["VNSTOCK_API_KEY"] = API_KEY
        log.info("✅ Using API key")
    else:
        log.warning("⚠️  Guest mode")

    log.info("─" * 60)
    log.info("🏢 Ownership Collector")
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

    ok = skipped_err = skipped_empty = batch_count = 0

    for i, symbol in enumerate(todo, 1):
        limiter.acquire()

        for attempt in range(MAX_RETRY):
            holders, summary = fetch_shareholders(symbol)
            break   # không retry vì lỗi thường là "không hỗ trợ"

        if not summary:
            skipped_empty += 1
            if i % 50 == 0:
                log.info("Progress: %d/%d | ok=%d empty=%d", i, len(todo), ok, skipped_empty)
            continue

        # Insert holders
        for h in holders:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO shareholders
                        (symbol, holder_name, holder_type, shares, pct_ownership, updated_at)
                    VALUES
                        (:symbol, :holder_name, :holder_type, :shares, :pct_ownership, :updated_at)
                """, h)
            except Exception as e:
                log.debug("[%s] holder insert error: %s", symbol, e)

        # Insert summary
        conn.execute("""
            INSERT OR REPLACE INTO ownership_summary
                (symbol, state_pct, foreign_pct, foreign_room_pct,
                 institution_pct, individual_pct, free_float_pct,
                 top1_holder, top1_pct, total_holders, updated_at)
            VALUES
                (:symbol, :state_pct, :foreign_pct, :foreign_room_pct,
                 :institution_pct, :individual_pct, :free_float_pct,
                 :top1_holder, :top1_pct, :total_holders, :updated_at)
        """, summary)

        # Sync free_float_pct vào bảng symbols
        conn.execute("""
            UPDATE symbols SET free_float_pct = ?
            WHERE symbol = ?
        """, (summary["free_float_pct"], symbol))

        ok += 1
        batch_count += 1

        if batch_count >= COMMIT_BATCH:
            conn.commit()
            batch_count = 0

        if i % 20 == 0:
            log.info("Progress: %d/%d | ok=%d empty=%d", i, len(todo), ok, skipped_empty)

    conn.commit()

    log.info("─" * 60)
    log.info("💾 OK: %d | Empty (no data): %d | Error: %d",
             ok, skipped_empty, skipped_err)
    log.info("─" * 60)

    inspect(conn)
    conn.close()


if __name__ == "__main__":
    collect_ownership()
