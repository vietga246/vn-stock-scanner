"""
inspect_price_board.py — Kiểm tra dữ liệu bảng giá trong stock.db

Chạy:
    python pipeline/utils/inspect_price_board.py
    DB_PATH=data/db/stock.db python pipeline/utils/inspect_price_board.py
"""
import sqlite3
import os
import sys

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")

# ─── HELPERS ───────────────────────────────────────────────────────────────

def sep(title=""):
    print(f"\n{'='*70}\n  {title}\n{'='*70}")

def run(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        print("  (empty)")
        return
    widths = [max(len(c), max(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*cols))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*[str(v) if v is not None else "NULL" for v in row]))

# ─── GUARD ─────────────────────────────────────────────────────────────────

if not os.path.exists(DB_PATH):
    print(f"ERROR: DB not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)

# Kiểm tra bảng tồn tại
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]

if "price_board_snapshot" not in tables:
    print(f"\n⚠️  Bảng 'price_board_snapshot' chưa tồn tại trong {DB_PATH}")
    print("   → Hãy chạy price_board_collector.py trước.\n")
    conn.close()
    sys.exit(0)

# ─── 1. ROW COUNT & SNAPSHOT TIMES ─────────────────────────────────────────

sep("1. TỔNG QUAN — Số rows & snapshot gần nhất")
run(conn, """
    SELECT
        COUNT(*)                                        AS total_rows,
        COUNT(DISTINCT symbol)                          AS unique_symbols,
        COUNT(DISTINCT snapshot_time)                   AS total_snapshots,
        MIN(snapshot_time)                              AS oldest_snapshot,
        MAX(snapshot_time)                              AS latest_snapshot
    FROM price_board_snapshot
""")

sep("2. SNAPSHOT GẦN NHẤT — Phân bổ theo sàn")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        COALESCE(exchange, 'N/A')   AS exchange,
        COUNT(*)                    AS symbols,
        SUM(CASE WHEN match_price IS NOT NULL THEN 1 ELSE 0 END)          AS has_price,
        SUM(CASE WHEN foreign_buy_qty IS NOT NULL THEN 1 ELSE 0 END)      AS has_foreign,
        SUM(CASE WHEN bid1_price IS NOT NULL THEN 1 ELSE 0 END)           AS has_bid_ask
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
    GROUP BY exchange
    ORDER BY symbols DESC
""")

sep("3. TOP 10 — Khối ngoại MUA ròng nhiều nhất (snapshot mới nhất)")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        symbol,
        exchange,
        ROUND(match_price, 2)                           AS gia_khop,
        ROUND(price_change_pct, 2)                      AS thay_doi_pct,
        ROUND(foreign_buy_qty  / 1e3, 1)                AS kn_mua_k,
        ROUND(foreign_sell_qty / 1e3, 1)                AS kl_ban_k,
        ROUND(foreign_net_qty  / 1e3, 1)                AS kl_rong_k,
        ROUND(foreign_net_value / 1e9, 2)               AS gt_rong_ty
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
      AND foreign_net_qty IS NOT NULL
      AND foreign_net_qty > 0
    ORDER BY foreign_net_qty DESC
    LIMIT 10
""")

sep("4. TOP 10 — Khối ngoại BÁN ròng nhiều nhất (snapshot mới nhất)")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        symbol,
        exchange,
        ROUND(match_price, 2)                           AS gia_khop,
        ROUND(price_change_pct, 2)                      AS thay_doi_pct,
        ROUND(foreign_buy_qty  / 1e3, 1)                AS kl_mua_k,
        ROUND(foreign_sell_qty / 1e3, 1)                AS kl_ban_k,
        ROUND(foreign_net_qty  / 1e3, 1)                AS kl_rong_k,
        ROUND(foreign_net_value / 1e9, 2)               AS gt_rong_ty
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
      AND foreign_net_qty IS NOT NULL
      AND foreign_net_qty < 0
    ORDER BY foreign_net_qty ASC
    LIMIT 10
""")

sep("5. BID/ASK — 5 mã có áp lực mua lớn nhất (bid1_volume)")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        symbol,
        ROUND(match_price, 2)           AS gia_khop,
        ROUND(bid1_price, 2)            AS bid1,
        ROUND(bid1_volume / 1e3, 1)     AS bid1_vol_k,
        ROUND(ask1_price, 2)            AS ask1,
        ROUND(ask1_volume / 1e3, 1)     AS ask1_vol_k,
        ROUND(
            CASE WHEN (bid1_volume + ask1_volume) > 0
                 THEN bid1_volume * 100.0 / (bid1_volume + ask1_volume)
                 ELSE NULL END
        , 1)                            AS buy_pressure_pct
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
      AND bid1_volume IS NOT NULL
      AND ask1_volume IS NOT NULL
    ORDER BY bid1_volume DESC
    LIMIT 10
""")

sep("6. THANH KHOẢN CAO — Top 10 theo tổng giá trị giao dịch")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        symbol,
        exchange,
        ROUND(match_price, 2)                       AS gia_khop,
        ROUND(price_change_pct, 2)                  AS pct_change,
        ROUND(total_traded_qty / 1e6, 2)            AS klgd_trieu,
        ROUND(total_traded_value / 1e9, 1)          AS gtgd_ty
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
      AND total_traded_value IS NOT NULL
    ORDER BY total_traded_value DESC
    LIMIT 10
""")

sep("7. NULL CHECK — Tỷ lệ NULL các cột quan trọng (snapshot mới nhất)")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        COUNT(*)                                                            AS total,
        SUM(CASE WHEN match_price IS NULL     THEN 1 ELSE 0 END)           AS match_price_null,
        SUM(CASE WHEN total_traded_qty IS NULL THEN 1 ELSE 0 END)          AS ttq_null,
        SUM(CASE WHEN foreign_buy_qty IS NULL  THEN 1 ELSE 0 END)          AS fbuy_null,
        SUM(CASE WHEN foreign_net_qty IS NULL  THEN 1 ELSE 0 END)          AS fnet_null,
        SUM(CASE WHEN foreign_room IS NULL     THEN 1 ELSE 0 END)          AS froom_null,
        SUM(CASE WHEN bid1_price IS NULL       THEN 1 ELSE 0 END)          AS bid1_null,
        SUM(CASE WHEN ask1_price IS NULL       THEN 1 ELSE 0 END)          AS ask1_null
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
""")

sep("8. SAMPLE — 5 dòng mẫu (snapshot mới nhất)")
run(conn, """
    WITH latest AS (
        SELECT MAX(snapshot_time) AS t FROM price_board_snapshot
    )
    SELECT
        symbol, exchange, snapshot_time,
        ROUND(match_price, 2)           AS price,
        ROUND(price_change_pct, 2)      AS chg_pct,
        ROUND(foreign_net_qty/1e3, 1)   AS fnet_k,
        ROUND(bid1_price, 2)            AS bid1,
        ROUND(ask1_price, 2)            AS ask1
    FROM price_board_snapshot, latest
    WHERE snapshot_time = latest.t
    LIMIT 5
""")

sep("9. DB SIZE")
size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
print(f"  {DB_PATH}: {size_mb:.2f} MB")

conn.close()
print("\n" + "=" * 70)
print("  DONE — inspect_price_board.py")
print("=" * 70)
