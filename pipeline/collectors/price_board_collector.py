"""
price_board_collector.py — Real-time Price Board Collector

Lấy dữ liệu bảng giá real-time từ VCI thông qua Trading.price_board().
Snapshot toàn thị trường trong 1 lần gọi API duy nhất (batch call).

Features:
- Lấy dữ liệu tất cả mã HOSE + HNX trong 1 batch call (không loop từng mã)
- Lưu vào bảng price_board_snapshot (SQLite) với timestamp
- Lưu dữ liệu khối ngoại real-time: foreign_buy_qty, foreign_sell_qty, foreign_room
- Lưu bid/ask 3 bậc: áp lực mua/bán tức thời
- TEST_MODE: chỉ dùng VN30

Chạy: python pipeline/collectors/price_board_collector.py
       TEST_MODE=true python pipeline/collectors/price_board_collector.py
"""

from vnstock import Listing, Trading
from datetime import datetime
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
    safe_float,
    safe_int,
    is_stock,
    create_db_connection,
    setup_logging,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH   = os.getenv("DB_PATH", "data/db/stock.db")
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

# VN30 cho TEST_MODE
VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

# ─── LOGGING ───────────────────────────────────────────────────────────────

log = setup_logging()

# ─── DATABASE ──────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    """Tạo bảng price_board_snapshot nếu chưa có."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_board_snapshot (
            symbol              TEXT,
            snapshot_time       TEXT,

            -- Thông tin niêm yết
            exchange            TEXT,
            stock_type          TEXT,
            organ_name          TEXT,

            -- Giá & khối lượng khớp lệnh
            match_price         REAL,
            match_qty           REAL,
            open_price          REAL,
            highest_price       REAL,
            lowest_price        REAL,
            avg_price           REAL,
            total_traded_qty    REAL,
            total_traded_value  REAL,
            price_change        REAL,
            price_change_pct    REAL,

            -- Khối ngoại (foreign trading real-time)
            foreign_buy_qty     REAL,
            foreign_sell_qty    REAL,
            foreign_net_qty     REAL,
            foreign_buy_value   REAL,
            foreign_sell_value  REAL,
            foreign_net_value   REAL,
            foreign_room        REAL,

            -- Bid/Ask bậc 1 (tốt nhất)
            bid1_price          REAL,
            bid1_volume         REAL,
            ask1_price          REAL,
            ask1_volume         REAL,

            -- Bid/Ask bậc 2
            bid2_price          REAL,
            bid2_volume         REAL,
            ask2_price          REAL,
            ask2_volume         REAL,

            -- Bid/Ask bậc 3
            bid3_price          REAL,
            bid3_volume         REAL,
            ask3_price          REAL,
            ask3_volume         REAL,

            -- Raw JSON để debug
            raw_json            TEXT,

            PRIMARY KEY (symbol, snapshot_time)
        );

        CREATE INDEX IF NOT EXISTS idx_pb_symbol
            ON price_board_snapshot(symbol);
        CREATE INDEX IF NOT EXISTS idx_pb_time
            ON price_board_snapshot(snapshot_time);
        CREATE INDEX IF NOT EXISTS idx_pb_exchange
            ON price_board_snapshot(exchange);
    """)
    conn.commit()
    log.info("✅ Database initialized")


# ─── TICKERS ───────────────────────────────────────────────────────────────

def get_tickers() -> list:
    """
    Lấy danh sách mã HOSE + HNX (chỉ cổ phiếu thường, loại bond/warrant).
    TEST_MODE trả về VN30.
    """
    if TEST_MODE:
        log.info("[TEST MODE] Using VN30: %d symbols", len(VN30_SYMBOLS))
        return VN30_SYMBOLS.copy()

    try:
        listing = Listing()
        df = listing.symbols_by_exchange()
        if "exchange" in df.columns:
            df = df[df["exchange"].str.upper().isin(["HOSE", "HNX"])]
            tickers = [t for t in df["symbol"].tolist() if is_stock(t)]
            log.info("Loaded %d symbols from HOSE + HNX", len(tickers))
            return tickers
    except Exception as e:
        log.warning("symbols_by_exchange() failed: %s — fallback to VN30", e)

    return VN30_SYMBOLS.copy()


# ─── PARSE RAW ROW ─────────────────────────────────────────────────────────

def _get(row: dict, *keys, default=None):
    """Lấy giá trị đầu tiên tìm được trong dict theo danh sách keys."""
    for k in keys:
        if k in row:
            return row[k]
    return default


def parse_row(row: dict, snapshot_time: str) -> dict:
    """
    Chuyển 1 row từ price_board DataFrame thành dict để INSERT.

    vnstock flatten_columns=True trả về single underscore: listing_symbol
    MultiIndex (flatten_columns không hỗ trợ) trả về tuple → join thành: listing__symbol
    → Mỗi field thử cả 2 dạng để tương thích.
    """
    # Flatten tuple keys nếu DataFrame vẫn có MultiIndex
    flat = {}
    for k, v in row.items():
        if isinstance(k, tuple):
            # MultiIndex: ('listing', 'symbol') → 'listing__symbol'
            flat["__".join(str(x) for x in k)] = v
        else:
            flat[k] = v

    # Helper: thử nhiều tên cột, ưu tiên theo thứ tự
    def g(*keys, default=None):
        return _get(flat, *keys, default=default)

    # ── Symbol ─────────────────────────────────────────────────────────────
    # flatten_columns=True  → 'listing_symbol'  (single underscore)
    # MultiIndex fallback   → 'listing__symbol' (double underscore)
    symbol = g("listing_symbol", "listing__symbol",
               "match_symbol",   "match__symbol",
               "symbol")

    # ── Foreign trading ────────────────────────────────────────────────────
    # API returns 'volume' not 'qty' for foreign trading
    f_buy_qty  = safe_float(g("match_foreign_buy_volume",  "match__foreign_buy_volume",
                               "match_foreign_buy_qty",    "match__foreign_buy_qty",
                               "match_buyForeignQty",      "match__buyForeignQty"))
    f_sell_qty = safe_float(g("match_foreign_sell_volume", "match__foreign_sell_volume",
                               "match_foreign_sell_qty",   "match__foreign_sell_qty",
                               "match_sellForeignQty",     "match__sellForeignQty"))
    f_net_qty  = None
    if f_buy_qty is not None and f_sell_qty is not None:
        f_net_qty = f_buy_qty - f_sell_qty

    f_buy_val  = safe_float(g("match_foreign_buy_value",   "match__foreign_buy_value",
                               "match_buy_foreign_value",  "match__buy_foreign_value",
                               "match_buyForeignValue",    "match__buyForeignValue"))
    f_sell_val = safe_float(g("match_foreign_sell_value",  "match__foreign_sell_value",
                               "match_sell_foreign_value", "match__sell_foreign_value",
                               "match_sellForeignValue",   "match__sellForeignValue"))
    f_net_val  = None
    if f_buy_val is not None and f_sell_val is not None:
        f_net_val = f_buy_val - f_sell_val

    # ── Price change ───────────────────────────────────────────────────────
    match_price = safe_float(g("match_match_price", "match__match_price",
                                "match_matchPrice",  "match__matchPrice"))
    ref_price   = safe_float(g("listing_ref_price",     "listing__ref_price",
                                "match_reference_price", "match__reference_price",
                                "listing_refPrice",      "listing__refPrice"))
    price_change = None
    price_change_pct = None
    if match_price is not None and ref_price and ref_price != 0:
        price_change = match_price - ref_price
        price_change_pct = round(price_change / ref_price * 100, 2)

    return {
        "symbol":             symbol,
        "snapshot_time":      snapshot_time,

        # Listing
        "exchange":           g("listing_exchange",          "listing__exchange",
                                "listing_board",             "listing__board"),
        "stock_type":         g("listing_stock_type",        "listing__stock_type",
                                "listing_stockType",         "listing__stockType"),
        "organ_name":         g("listing_organ_name",        "listing__organ_name",
                                "listing_organName",         "listing__organName"),

        # Match
        "match_price":        match_price,
        "match_qty":          safe_float(g("match_match_vol",          "match__match_vol",
                                           "match_match_qty",          "match__match_qty",
                                           "match_matchQty",           "match__matchQty")),
        "open_price":         safe_float(g("match_open_price",         "match__open_price",
                                           "match_openPrice",          "match__openPrice")),
        "highest_price":      safe_float(g("match_highest",            "match__highest")),
        "lowest_price":       safe_float(g("match_lowest",             "match__lowest")),
        "avg_price":          safe_float(g("match_avg_match_price",     "match__avg_match_price",
                                           "match_avg_price",          "match__avg_price",
                                           "match_avgPrice",           "match__avgPrice")),
        "total_traded_qty":   safe_float(g("match_accumulated_volume",  "match__accumulated_volume",
                                           "match_total_traded_qty",   "match__total_traded_qty",
                                           "match_totalTradedQty",     "match__totalTradedQty")),
        "total_traded_value": safe_float(g("match_accumulated_value",  "match__accumulated_value",
                                           "match_total_traded_value", "match__total_traded_value",
                                           "match_totalTradedValue",   "match__totalTradedValue")),
        "price_change":       price_change,
        "price_change_pct":   price_change_pct,

        # Foreign
        "foreign_buy_qty":    f_buy_qty,
        "foreign_sell_qty":   f_sell_qty,
        "foreign_net_qty":    f_net_qty,
        "foreign_buy_value":  f_buy_val,
        "foreign_sell_value": f_sell_val,
        "foreign_net_value":  f_net_val,
        "foreign_room":       safe_float(g("match_current_room",       "match__current_room",
                                           "listing_foreign_room",     "listing__foreign_room",
                                           "listing_foreignRoom",      "listing__foreignRoom")),

        # Bid/Ask
        "bid1_price":  safe_float(g("bid_ask_bid_1_price",  "bid_ask__bid_1_price")),
        "bid1_volume": safe_float(g("bid_ask_bid_1_volume", "bid_ask__bid_1_volume")),
        "ask1_price":  safe_float(g("bid_ask_ask_1_price",  "bid_ask__ask_1_price")),
        "ask1_volume": safe_float(g("bid_ask_ask_1_volume", "bid_ask__ask_1_volume")),
        "bid2_price":  safe_float(g("bid_ask_bid_2_price",  "bid_ask__bid_2_price")),
        "bid2_volume": safe_float(g("bid_ask_bid_2_volume", "bid_ask__bid_2_volume")),
        "ask2_price":  safe_float(g("bid_ask_ask_2_price",  "bid_ask__ask_2_price")),
        "ask2_volume": safe_float(g("bid_ask_ask_2_volume", "bid_ask__ask_2_volume")),
        "bid3_price":  safe_float(g("bid_ask_bid_3_price",  "bid_ask__bid_3_price")),
        "bid3_volume": safe_float(g("bid_ask_bid_3_volume", "bid_ask__bid_3_volume")),
        "ask3_price":  safe_float(g("bid_ask_ask_3_price",  "bid_ask__ask_3_price")),
        "ask3_volume": safe_float(g("bid_ask_ask_3_volume", "bid_ask__ask_3_volume")),

        # Raw JSON
        "raw_json": json.dumps(
            {str(k): str(v) for k, v in row.items()},
            ensure_ascii=False
        ),
    }


# ─── INSERT ────────────────────────────────────────────────────────────────

INSERT_SQL = """
    INSERT OR REPLACE INTO price_board_snapshot (
        symbol, snapshot_time,
        exchange, stock_type, organ_name,
        match_price, match_qty, open_price, highest_price, lowest_price,
        avg_price, total_traded_qty, total_traded_value,
        price_change, price_change_pct,
        foreign_buy_qty, foreign_sell_qty, foreign_net_qty,
        foreign_buy_value, foreign_sell_value, foreign_net_value, foreign_room,
        bid1_price, bid1_volume, ask1_price, ask1_volume,
        bid2_price, bid2_volume, ask2_price, ask2_volume,
        bid3_price, bid3_volume, ask3_price, ask3_volume,
        raw_json
    ) VALUES (
        :symbol, :snapshot_time,
        :exchange, :stock_type, :organ_name,
        :match_price, :match_qty, :open_price, :highest_price, :lowest_price,
        :avg_price, :total_traded_qty, :total_traded_value,
        :price_change, :price_change_pct,
        :foreign_buy_qty, :foreign_sell_qty, :foreign_net_qty,
        :foreign_buy_value, :foreign_sell_value, :foreign_net_value, :foreign_room,
        :bid1_price, :bid1_volume, :ask1_price, :ask1_volume,
        :bid2_price, :bid2_volume, :ask2_price, :ask2_volume,
        :bid3_price, :bid3_volume, :ask3_price, :ask3_volume,
        :raw_json
    )
"""


# ─── MAIN ──────────────────────────────────────────────────────────────────

def collect_price_board():
    """
    Snapshot bảng giá toàn thị trường → lưu vào SQLite.
    1 batch API call duy nhất cho tất cả mã.
    """
    tickers = get_tickers()
    snapshot_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    log.info("─" * 60)
    log.info("📡 Price Board Snapshot — %s", snapshot_time)
    log.info("   Symbols: %d | TEST_MODE: %s", len(tickers), TEST_MODE)
    log.info("─" * 60)

    # ── Gọi API (1 batch call) ────────────────────────────────────────────
    t_api_start = time.time()
    try:
        trader = Trading(symbol=tickers[0], source="VCI", show_log=False)
        # flatten_columns=True được hỗ trợ từ vnstock >= 3.x
        # Nếu version cũ không hỗ trợ, parse_row() tự handle MultiIndex columns
        try:
            df = trader.price_board(symbols_list=tickers, flatten_columns=True)
        except TypeError:
            log.warning("flatten_columns not supported — fetching without it")
            df = trader.price_board(symbols_list=tickers)
        elapsed = time.time() - t_api_start
        log.info("✅ API responded in %.1fs — %d rows", elapsed, len(df))
        # Log toàn bộ column names để verify mapping
        all_cols = list(df.columns)
        log.info("📋 DataFrame columns (%d total): %s", len(all_cols), all_cols)
    except Exception as e:
        log.error("❌ price_board() failed: %s", e)
        raise

    if df is None or df.empty:
        log.warning("⚠️  Empty DataFrame returned from API")
        return

    # ── Parse & Insert ────────────────────────────────────────────────────
    conn = create_db_connection(DB_PATH)
    init_db(conn)
    cursor = conn.cursor()

    rows_inserted = 0
    rows_skipped  = 0

    for _, raw_row in df.iterrows():
        try:
            parsed = parse_row(raw_row.to_dict(), snapshot_time)
            if not parsed.get("symbol"):
                if rows_skipped == 0:
                    # Log keys của row đầu tiên bị skip để debug
                    row_dict = raw_row.to_dict()
                    log.warning("⚠️  symbol=None on first row. Available keys: %s",
                                list(row_dict.keys())[:15])
                rows_skipped += 1
                continue
            cursor.execute(INSERT_SQL, parsed)
            rows_inserted += 1
        except Exception as e:
            log.warning("Parse error for row: %s", e)
            rows_skipped += 1

    conn.commit()
    conn.close()

    log.info("─" * 60)
    log.info("💾 Inserted: %d rows | Skipped: %d", rows_inserted, rows_skipped)
    log.info("   DB: %s", DB_PATH)
    log.info("─" * 60)


if __name__ == "__main__":
    collect_price_board()
