"""
migrate_db.py — One-time DB Migration

Thêm các columns mới vào DB cũ (từ trước Quick Fixes) mà không cần
xóa data hay re-run bootstrap.

Columns được thêm vào technical_indicators:
  adx14, plus_di14, minus_di14, di_spread
  trend_strength, vol_ma20
  pct_from_ma20, pct_from_ma50
  fvg_bull, fvg_bear, fvg_bull_size, fvg_bear_size
  fvg_bull_age, fvg_bear_age, fvg_bull_fill, fvg_bear_fill

Columns được thêm vào stock_scores:
  roa, vol_ma20, pct_from_ma20, pct_from_ma50
  adx14, plus_di14, minus_di14, di_spread, trend_strength
  bb_width, atr14, atr_pct, macd_hist
  fvg_bull, fvg_bear, fvg_bull/bear size/age/fill

Script idempotent — chạy nhiều lần không bị lỗi.
Sau khi migrate, workflow 3 sẽ tự điền giá trị vào khi chạy.

Chạy:
  python pipeline/utils/migrate_db.py
"""

import sqlite3
import os
import sys
import logging

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def get_existing_columns(conn, table: str) -> set:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def migrate_technical_indicators(conn):
    """ALTER TABLE technical_indicators ADD COLUMN cho các columns mới."""
    existing = get_existing_columns(conn, "technical_indicators")

    new_cols = [
        ("adx14",          "REAL"),
        ("plus_di14",      "REAL"),
        ("minus_di14",     "REAL"),
        ("di_spread",      "REAL"),
        ("trend_strength", "REAL"),
        ("vol_ma20",       "REAL"),
        ("pct_from_ma20",  "REAL"),
        ("pct_from_ma50",  "REAL"),
        ("fvg_bull",       "INTEGER DEFAULT 0"),
        ("fvg_bear",       "INTEGER DEFAULT 0"),
        ("fvg_bull_size",  "REAL"),
        ("fvg_bear_size",  "REAL"),
        ("fvg_bull_age",   "INTEGER"),
        ("fvg_bear_age",   "INTEGER"),
        ("fvg_bull_fill",  "REAL"),
        ("fvg_bear_fill",  "REAL"),
    ]

    added = []
    skipped = []
    for col, col_type in new_cols:
        if col not in existing:
            try:
                conn.execute(
                    f"ALTER TABLE technical_indicators ADD COLUMN {col} {col_type}"
                )
                added.append(col)
            except sqlite3.OperationalError as e:
                log.warning("  Không thêm được %s: %s", col, e)
        else:
            skipped.append(col)

    conn.commit()

    if added:
        log.info("technical_indicators: thêm %d columns mới: %s",
                 len(added), ", ".join(added))
    if skipped:
        log.info("technical_indicators: %d columns đã tồn tại (skip): %s",
                 len(skipped), ", ".join(skipped))

    # Thêm indexes mới
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_tech_adx ON technical_indicators(adx14)",
        "CREATE INDEX IF NOT EXISTS idx_tech_fvg ON technical_indicators(fvg_bull, fvg_bear)",
        "CREATE INDEX IF NOT EXISTS idx_tech_trend_str ON technical_indicators(trend_strength)",
    ]:
        try:
            conn.execute(idx_sql)
        except Exception:
            pass
    conn.commit()
    log.info("technical_indicators: indexes OK")


def migrate_stock_scores(conn):
    """ALTER TABLE stock_scores ADD COLUMN cho các columns mới."""
    existing = get_existing_columns(conn, "stock_scores")

    new_cols = [
        ("roa",            "REAL"),
        ("vol_ma20",       "REAL"),
        ("pct_from_ma20",  "REAL"),
        ("pct_from_ma50",  "REAL"),
        ("adx14",          "REAL"),
        ("plus_di14",      "REAL"),
        ("minus_di14",     "REAL"),
        ("di_spread",      "REAL"),
        ("trend_strength", "REAL"),
        ("bb_width",       "REAL"),
        ("atr14",          "REAL"),
        ("atr_pct",        "REAL"),
        ("macd_hist",      "REAL"),
        ("fvg_bull",       "INTEGER DEFAULT 0"),
        ("fvg_bear",       "INTEGER DEFAULT 0"),
        ("fvg_bull_size",  "REAL"),
        ("fvg_bear_size",  "REAL"),
        ("fvg_bull_age",   "INTEGER"),
        ("fvg_bear_age",   "INTEGER"),
        ("fvg_bull_fill",  "REAL"),
        ("fvg_bear_fill",  "REAL"),
    ]

    added = []
    skipped = []
    for col, col_type in new_cols:
        if col not in existing:
            try:
                conn.execute(
                    f"ALTER TABLE stock_scores ADD COLUMN {col} {col_type}"
                )
                added.append(col)
            except sqlite3.OperationalError as e:
                log.warning("  Không thêm được %s: %s", col, e)
        else:
            skipped.append(col)

    conn.commit()

    if added:
        log.info("stock_scores: thêm %d columns mới: %s",
                 len(added), ", ".join(added))
    if skipped:
        log.info("stock_scores: %d columns đã tồn tại (skip): %s",
                 len(skipped), ", ".join(skipped))


def run():
    if not os.path.exists(DB_PATH):
        log.error("DB không tồn tại: %s", DB_PATH)
        sys.exit(1)

    log.info("═" * 50)
    log.info("  DB Migration — %s", DB_PATH)
    log.info("═" * 50)

    conn = sqlite3.connect(DB_PATH, timeout=60)

    # Kiểm tra bảng tồn tại
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    log.info("Tables hiện có: %s", sorted(tables))

    if "technical_indicators" in tables:
        migrate_technical_indicators(conn)
    else:
        log.warning("technical_indicators chưa tồn tại — bỏ qua (chạy workflow 3 trước)")

    if "stock_scores" in tables:
        migrate_stock_scores(conn)
    else:
        log.warning("stock_scores chưa tồn tại — bỏ qua")

    # Verify
    log.info("─" * 50)
    log.info("Verification:")
    for table in ["technical_indicators", "stock_scores"]:
        if table in tables:
            cols = get_existing_columns(conn, table)
            new_expected = ["adx14", "trend_strength", "vol_ma20", "fvg_bull"]
            for c in new_expected:
                status = "✅" if c in cols else "❌ MISSING"
                log.info("  %s.%-20s %s", table, c, status)

    conn.close()
    log.info("═" * 50)
    log.info("Migration hoàn tất. Chạy workflow 3 để điền giá trị mới.")


if __name__ == "__main__":
    run()
