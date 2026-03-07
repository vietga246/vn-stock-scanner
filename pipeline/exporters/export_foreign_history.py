"""
export_foreign_history.py — Export/Import foreign_trading history ra CSV

MỤC ĐÍCH:
  GitHub Actions cache có TTL 7 ngày → nếu expire, toàn bộ foreign_trading
  history bị mất → foreign_net_7d/30d về 0 hoặc sai.

  Script này:
  - EXPORT: Đọc foreign_trading table → data/exports/foreign_history.csv (commit Git)
  - IMPORT: Đọc foreign_history.csv → nạp lại vào DB (khi DB bị reset)

  foreign_history.csv được commit lên Git mỗi ngày cùng price_board.json
  → luôn có backup lịch sử, không bao giờ mất data.

CHẠY:
  # Export (sau khi collect xong):
  python pipeline/exporters/export_foreign_history.py export

  # Import (khi DB mới / cache miss):
  python pipeline/exporters/export_foreign_history.py import

  # Cả hai (export rồi verify):
  python pipeline/exporters/export_foreign_history.py both
"""

import sqlite3
import csv
import os
import sys
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import safe_float, create_db_connection, setup_logging

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH    = os.getenv("DB_PATH",    "data/db/stock.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")
CSV_PATH   = os.path.join(EXPORT_DIR, "foreign_history.csv")

# Giữ tối đa 60 ngày trong CSV (đủ để tính 30D + buffer)
MAX_DAYS   = int(os.getenv("FOREIGN_HISTORY_DAYS", "60"))

log = setup_logging()

CSV_COLUMNS = [
    "symbol", "date",
    "buy_volume", "sell_volume", "net_volume",
    "buy_value",  "sell_value",  "net_value",
]


# ─── EXPORT ────────────────────────────────────────────────────────────────

def export_to_csv() -> int:
    """
    Đọc foreign_trading từ DB → ghi ra CSV.
    Chỉ giữ MAX_DAYS ngày gần nhất.
    Returns số rows exported.
    """
    if not os.path.exists(DB_PATH):
        log.error("❌ DB not found: %s", DB_PATH)
        return 0

    conn = create_db_connection(DB_PATH)

    # Kiểm tra bảng tồn tại
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "foreign_trading" not in tables:
        log.warning("⚠️  foreign_trading table chưa tồn tại — bỏ qua export")
        conn.close()
        return 0

    cutoff = (datetime.now() - timedelta(days=MAX_DAYS)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT symbol, date,
               buy_volume, sell_volume, net_volume,
               buy_value,  sell_value,  net_value
        FROM foreign_trading
        WHERE date >= ?
        ORDER BY date ASC, symbol ASC
    """, (cutoff,)).fetchall()

    conn.close()

    if not rows:
        log.warning("⚠️  foreign_trading rỗng — không có gì để export")
        return 0

    os.makedirs(EXPORT_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)

    days_count = len(set(r[1] for r in rows))
    syms_count = len(set(r[0] for r in rows))
    size_kb    = os.path.getsize(CSV_PATH) / 1024

    log.info("✅ EXPORT xong: %d rows | %d ngày | %d symbols → %s (%.1f KB)",
             len(rows), days_count, syms_count, CSV_PATH, size_kb)

    _log_status(rows)
    return len(rows)


# ─── IMPORT ────────────────────────────────────────────────────────────────

def import_from_csv() -> int:
    """
    Đọc foreign_history.csv → nạp vào foreign_trading table trong DB.

    Dùng INSERT OR REPLACE (không phải IGNORE) vì:
    - CSV luôn là snapshot mới nhất từ lần Workflow 2 chạy gần nhất
    - Nếu DB có data mid-session (e.g. -300B) nhưng CSV đã có ATC (-578B),
      cần overwrite để đảm bảo data chính xác
    - Idempotent: chạy nhiều lần với cùng CSV → cùng kết quả

    Returns số rows imported (replaced).
    """
    if not os.path.exists(CSV_PATH):
        log.warning("⚠️  %s không tồn tại — bỏ qua import", CSV_PATH)
        return 0

    if not os.path.exists(DB_PATH):
        log.error("❌ DB not found: %s — cần chạy bootstrap trước", DB_PATH)
        return 0

    # Đọc CSV
    rows = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        log.warning("⚠️  foreign_history.csv rỗng")
        return 0

    conn = create_db_connection(DB_PATH)

    # Tạo bảng nếu chưa có (mirror của daily_foreign_flow.py)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS foreign_trading (
            symbol        TEXT,
            date          TEXT,
            buy_volume    REAL,
            sell_volume   REAL,
            net_volume    REAL,
            buy_value     REAL,
            sell_value    REAL,
            net_value     REAL,
            data_json     TEXT,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_foreign_trading_symbol ON foreign_trading(symbol);
        CREATE INDEX IF NOT EXISTS idx_foreign_trading_date   ON foreign_trading(date);
    """)
    conn.commit()

    # Load existing buy_value cho ngày trong CSV để so sánh (dùng cho smart merge ngày hôm nay)
    today = datetime.now().strftime("%Y-%m-%d")
    csv_dates = list(set(r["date"] for r in rows if r.get("date")))
    placeholders = ",".join("?" * len(csv_dates))
    existing_map = {}  # (symbol, date) → buy_value hiện tại trong DB
    if csv_dates:
        for db_row in conn.execute(
            f"SELECT symbol, date, buy_value FROM foreign_trading WHERE date IN ({placeholders})",
            csv_dates
        ).fetchall():
            existing_map[(db_row[0], db_row[1])] = db_row[2] or 0.0

    cursor = conn.cursor()
    imported = replaced = skipped = ignored = 0

    for row in rows:
        symbol = row.get("symbol", "").strip()
        date   = row.get("date", "").strip()
        if not symbol or not date:
            skipped += 1
            continue

        buy_vol  = safe_float(row.get("buy_volume"))
        sell_vol = safe_float(row.get("sell_volume"))
        net_vol  = safe_float(row.get("net_volume"))
        buy_val  = safe_float(row.get("buy_value"))
        sell_val = safe_float(row.get("sell_value"))
        net_val  = safe_float(row.get("net_value"))

        key = (symbol, date)

        # Smart merge logic:
        # - Ngày CŨ (< today): CSV là backup khi cache miss → INSERT OR REPLACE
        #   (giá trị cuối ngày không thay đổi, nếu DB đã có = CSV → no-op thực tế)
        # - Ngày HÔM NAY: price_board accumulated tăng dần trong phiên
        #   → Chỉ replace nếu CSV có buy_value LỚN HƠN DB (tức snapshot muộn hơn)
        #   → Bảo vệ: DB đã có ATC (lớn hơn) mà CSV là mid-session (nhỏ hơn) → không overwrite
        if date == today and key in existing_map:
            db_buy  = existing_map[key]
            csv_buy = buy_val or 0.0
            if csv_buy <= db_buy:
                ignored += 1
                continue

        cursor.execute("""
            INSERT OR REPLACE INTO foreign_trading
            (symbol, date, buy_volume, sell_volume, net_volume,
             buy_value, sell_value, net_value, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, date, buy_vol, sell_vol, net_vol,
              buy_val, sell_val, net_val,
              '{"source":"foreign_history_csv"}'))
        if key in existing_map:
            replaced += 1
        else:
            imported += 1

    conn.commit()
    conn.close()

    days_count = len(set(r["date"] for r in rows))
    log.info("✅ IMPORT xong: %d new | %d replaced | %d ignored (DB newer) | %d skipped | %d ngày",
             imported, replaced, ignored, skipped, days_count)

    return imported + replaced


# ─── STATUS ────────────────────────────────────────────────────────────────

def _log_status(rows):
    """In status report sau export."""
    if not rows:
        return

    dates   = sorted(set(r[1] for r in rows))
    symbols = len(set(r[0] for r in rows))
    today   = datetime.now().strftime("%Y-%m-%d")

    # Đếm trong 7D và 30D window
    cutoff_7d  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    cutoff_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    days_7d    = len([d for d in dates if d >= cutoff_7d])
    days_30d   = len([d for d in dates if d >= cutoff_30d])

    log.info("─── Foreign Trading Status ───────────────────────")
    log.info("  Tổng ngày lưu trữ : %d ngày (%s → %s)",
             len(dates), dates[0], dates[-1])
    log.info("  Symbols có data   : %d", symbols)
    log.info("  7D window  : %d/7  phiên  → %s",
             days_7d,  "✅ ĐỦ" if days_7d >= 7  else f"⏳ thiếu {7-days_7d}")
    log.info("  30D window : %d/30 phiên  → %s",
             days_30d, "✅ ĐỦ" if days_30d >= 30 else f"⏳ thiếu {30-days_30d}")

    if days_7d < 7:
        eta = datetime.now() + timedelta(days=(7 - days_7d) * 7 // 5)
        log.info("  📅 ETA 7D  : %s", eta.strftime("%Y-%m-%d"))
    if days_30d < 30:
        eta = datetime.now() + timedelta(days=(30 - days_30d) * 7 // 5)
        log.info("  📅 ETA 30D : %s", eta.strftime("%Y-%m-%d"))
    log.info("──────────────────────────────────────────────────")


def check_status():
    """Chỉ kiểm tra status, không export/import."""
    if not os.path.exists(CSV_PATH):
        log.info("foreign_history.csv: KHÔNG TỒN TẠI")
        return

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    _log_status([(r["symbol"], r["date"], 0, 0, 0, 0, 0,
                  safe_float(r.get("net_value"))) for r in rows])


# ─── MAIN ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "export"

    if mode == "export":
        export_to_csv()
    elif mode == "import":
        import_from_csv()
    elif mode == "both":
        export_to_csv()
        import_from_csv()
    elif mode == "status":
        check_status()
    else:
        log.error("Usage: export_foreign_history.py [export|import|both|status]")
        sys.exit(1)
