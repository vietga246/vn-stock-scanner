"""
export_price_board.py — Export Price Board Snapshot ra JSON

Đọc snapshot mới nhất từ price_board_snapshot → data/exports/price_board.json

Output structure:
{
  "generated_at": "2026-03-06T15:45:00",
  "snapshot_time": "2026-03-06T14:45:12",
  "total_symbols": 706,
  "summary": {
    "total_foreign_net_qty": 12345678,
    "total_foreign_net_value_bn": 456.78,
    "avg_buy_pressure_pct": 52.3,
    "symbols_with_data": 704
  },
  "stocks": [
    {
      "symbol": "VCB",
      "exchange": "HOSE",
      "match_price": 89500,
      "price_change_pct": 1.23,
      "total_traded_qty": 1234567,
      "foreign_buy_qty": 500000,
      "foreign_sell_qty": 200000,
      "foreign_net_qty": 300000,
      "foreign_net_value_bn": 26.85,
      "foreign_room": 5000000,
      "bid1_price": 89400,
      "bid1_volume": 123400,
      "ask1_price": 89600,
      "ask1_volume": 98700,
      "buy_pressure_pct": 55.6
    }, ...
  ]
}

Chạy: python pipeline/exporters/export_price_board.py
"""

import sqlite3
import json
import os
import sys
import logging
from datetime import datetime

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import safe_float, setup_logging

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH    = os.getenv("DB_PATH",    "data/db/stock.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")
OUT_PATH   = os.path.join(EXPORT_DIR, "price_board.json")

log = setup_logging()

# ─── HELPERS ───────────────────────────────────────────────────────────────

def _sf(v, decimals=2):
    """safe_float với làm tròn."""
    r = safe_float(v)
    if r is None:
        return None
    return round(r, decimals)

def _pct_buy_pressure(bid_vol, ask_vol):
    """Tính áp lực mua từ bid/ask volume bậc 1."""
    b = safe_float(bid_vol)
    a = safe_float(ask_vol)
    if b is None or a is None or (b + a) == 0:
        return None
    return round(b * 100.0 / (b + a), 1)

# ─── MAIN ──────────────────────────────────────────────────────────────────

def export_price_board():
    if not os.path.exists(DB_PATH):
        log.error("❌ DB not found: %s", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Kiểm tra bảng tồn tại
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "price_board_snapshot" not in tables:
        log.warning("⚠️  Bảng price_board_snapshot chưa tồn tại — bỏ qua export")
        conn.close()
        return

    # Lấy snapshot_time mới nhất
    row = conn.execute(
        "SELECT MAX(snapshot_time) AS t FROM price_board_snapshot"
    ).fetchone()
    if not row or not row["t"]:
        log.warning("⚠️  Không có dữ liệu trong price_board_snapshot")
        conn.close()
        return

    latest_time = row["t"]
    log.info("📊 Snapshot mới nhất: %s", latest_time)

    # Đọc tất cả mã trong snapshot đó
    rows = conn.execute("""
        SELECT
            symbol, exchange, organ_name,
            match_price, open_price, highest_price, lowest_price, avg_price,
            price_change, price_change_pct,
            total_traded_qty, total_traded_value,
            foreign_buy_qty, foreign_sell_qty, foreign_net_qty,
            foreign_buy_value, foreign_sell_value, foreign_net_value,
            foreign_room,
            bid1_price, bid1_volume, ask1_price, ask1_volume,
            bid2_price, bid2_volume, ask2_price, ask2_volume,
            bid3_price, bid3_volume, ask3_price, ask3_volume
        FROM price_board_snapshot
        WHERE snapshot_time = ?
        ORDER BY symbol
    """, (latest_time,)).fetchall()

    log.info("✅ Đọc %d rows từ snapshot %s", len(rows), latest_time)
    conn.close()

    # ── Build stocks list ────────────────────────────────────────────────
    stocks = []
    total_fn_qty    = 0.0
    total_fn_val    = 0.0
    bp_list         = []
    symbols_with_data = 0

    for r in rows:
        fn_qty = safe_float(r["foreign_net_qty"])
        fn_val = safe_float(r["foreign_net_value"])
        bp     = _pct_buy_pressure(r["bid1_volume"], r["ask1_volume"])

        if fn_qty is not None:
            total_fn_qty += fn_qty
        if fn_val is not None:
            total_fn_val += fn_val
        if bp is not None:
            bp_list.append(bp)
        if r["match_price"] is not None:
            symbols_with_data += 1

        stocks.append({
            "symbol":               r["symbol"],
            "exchange":             r["exchange"],
            "organ_name":           r["organ_name"],

            # Giá
            "match_price":          _sf(r["match_price"], 0),
            "open_price":           _sf(r["open_price"],  0),
            "highest_price":        _sf(r["highest_price"], 0),
            "lowest_price":         _sf(r["lowest_price"],  0),
            "avg_price":            _sf(r["avg_price"],   0),
            "price_change":         _sf(r["price_change"], 0),
            "price_change_pct":     _sf(r["price_change_pct"], 2),

            # Thanh khoản
            "total_traded_qty":     _sf(r["total_traded_qty"],   0),
            "total_traded_value":   _sf(r["total_traded_value"], 0),

            # Khối ngoại
            "foreign_buy_qty":      _sf(r["foreign_buy_qty"],  0),
            "foreign_sell_qty":     _sf(r["foreign_sell_qty"], 0),
            "foreign_net_qty":      _sf(r["foreign_net_qty"],  0),
            "foreign_net_value_bn": _sf(fn_val / 1e9, 3) if fn_val is not None else None,
            "foreign_room":         _sf(r["foreign_room"], 0),

            # Bid/Ask 3 bậc
            "bid1_price":   _sf(r["bid1_price"], 0),
            "bid1_volume":  _sf(r["bid1_volume"], 0),
            "ask1_price":   _sf(r["ask1_price"], 0),
            "ask1_volume":  _sf(r["ask1_volume"], 0),
            "bid2_price":   _sf(r["bid2_price"], 0),
            "bid2_volume":  _sf(r["bid2_volume"], 0),
            "ask2_price":   _sf(r["ask2_price"], 0),
            "ask2_volume":  _sf(r["ask2_volume"], 0),
            "bid3_price":   _sf(r["bid3_price"], 0),
            "bid3_volume":  _sf(r["bid3_volume"], 0),
            "ask3_price":   _sf(r["ask3_price"], 0),
            "ask3_volume":  _sf(r["ask3_volume"], 0),

            # Derived
            "buy_pressure_pct": bp,
        })

    # ── Summary ──────────────────────────────────────────────────────────
    avg_bp = round(sum(bp_list) / len(bp_list), 1) if bp_list else None

    payload = {
        "generated_at":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "snapshot_time":  latest_time,
        "total_symbols":  len(stocks),
        "summary": {
            "symbols_with_price":        symbols_with_data,
            "total_foreign_net_qty":     round(total_fn_qty, 0),
            "total_foreign_net_value_bn": round(total_fn_val / 1e9, 2),
            "avg_buy_pressure_pct":      avg_bp,
        },
        "stocks": stocks,
    }

    # ── Write JSON ───────────────────────────────────────────────────────
    os.makedirs(EXPORT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    log.info("💾 Exported %d stocks → %s (%.1f KB)", len(stocks), OUT_PATH, size_kb)

    # ── Inspect log ─────────────────────────────────────────────────────
    _inspect(payload)


def _inspect(payload: dict):
    """In inspect log sau khi export."""
    sep = "=" * 65

    print(f"\n{sep}")
    print(f"  INSPECT — price_board.json")
    print(sep)
    print(f"  Snapshot time : {payload['snapshot_time']}")
    print(f"  Total symbols : {payload['total_symbols']}")
    s = payload["summary"]
    print(f"  With price    : {s['symbols_with_price']}")
    print(f"  Foreign net   : {s['total_foreign_net_value_bn']:+.2f} tỷ đồng")
    print(f"  Avg buy pres  : {s['avg_buy_pressure_pct']}%")

    stocks = payload["stocks"]

    # Top 5 khối ngoại mua ròng
    fn_sorted = sorted(
        [s for s in stocks if s.get("foreign_net_qty") is not None],
        key=lambda x: x["foreign_net_qty"], reverse=True
    )
    print(f"\n  TOP 5 — Khối ngoại MUA ròng:")
    print(f"  {'Symbol':<8} {'Sàn':<5} {'Giá':>9} {'Chg%':>6} {'Net(K)':>10} {'Val(tỷ)':>9}")
    print(f"  {'-'*8} {'-'*5} {'-'*9} {'-'*6} {'-'*10} {'-'*9}")
    for s in fn_sorted[:5]:
        nq = s['foreign_net_qty']
        print(f"  {s['symbol']:<8} {(s['exchange'] or ''):<5} "
              f"{(s['match_price'] or 0):>9,.0f} "
              f"{(s['price_change_pct'] or 0):>+6.2f} "
              f"{nq/1000:>10,.1f} "
              f"{(s['foreign_net_value_bn'] or 0):>+9.3f}")

    # Top 5 khối ngoại bán ròng
    print(f"\n  TOP 5 — Khối ngoại BÁN ròng:")
    print(f"  {'Symbol':<8} {'Sàn':<5} {'Giá':>9} {'Chg%':>6} {'Net(K)':>10} {'Val(tỷ)':>9}")
    print(f"  {'-'*8} {'-'*5} {'-'*9} {'-'*6} {'-'*10} {'-'*9}")
    for s in fn_sorted[-5:][::-1]:
        nq = s['foreign_net_qty']
        print(f"  {s['symbol']:<8} {(s['exchange'] or ''):<5} "
              f"{(s['match_price'] or 0):>9,.0f} "
              f"{(s['price_change_pct'] or 0):>+6.2f} "
              f"{nq/1000:>10,.1f} "
              f"{(s['foreign_net_value_bn'] or 0):>+9.3f}")

    # Top 5 buy pressure
    bp_sorted = sorted(
        [s for s in stocks if s.get("buy_pressure_pct") is not None],
        key=lambda x: x["buy_pressure_pct"], reverse=True
    )
    print(f"\n  TOP 5 — Áp lực MUA cao nhất (bid pressure):")
    print(f"  {'Symbol':<8} {'Giá':>9} {'Bid1':>9} {'Bid1Vol(K)':>11} {'Ask1':>9} {'BuyPres%':>9}")
    print(f"  {'-'*8} {'-'*9} {'-'*9} {'-'*11} {'-'*9} {'-'*9}")
    for s in bp_sorted[:5]:
        print(f"  {s['symbol']:<8} "
              f"{(s['match_price'] or 0):>9,.0f} "
              f"{(s['bid1_price'] or 0):>9,.0f} "
              f"{((s['bid1_volume'] or 0)/1000):>11,.1f} "
              f"{(s['ask1_price'] or 0):>9,.0f} "
              f"{s['buy_pressure_pct']:>9.1f}%")

    print(f"\n{sep}\n")


if __name__ == "__main__":
    export_price_board()
