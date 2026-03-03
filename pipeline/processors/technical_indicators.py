"""
technical_calc.py — Tính toán chỉ số kỹ thuật từ bảng stock_prices

Chỉ số được tính:
  - MA5, MA10, MA20, MA50 (Simple Moving Average)
  - EMA12, EMA26 (Exponential MA)
  - MACD, MACD_Signal, MACD_Hist
  - RSI(14)
  - Bollinger Bands (BB_Upper, BB_Middle, BB_Lower, BB_Width)
  - ATR(14) — Average True Range
  - Volume MA5, Volume Ratio (vol / vol_ma5)
  - Price momentum: price_change_1d, price_change_5d, price_change_20d (%)
  - Trend signal: trend_short (up/down/neutral dựa trên MA5 vs MA20)

Adaptive: tự động tính các chỉ số phù hợp với độ dài data có sẵn
  (ít nhất 5 ngày để có MA5, ít nhất 14 ngày để có RSI)

Chạy sau hose_daily.py trong GitHub Actions.
Output: table `technical_indicators` trong stock.db
"""

import sqlite3
import pandas as pd
import numpy as np
import logging
import sys
import os
from datetime import datetime

# ─── CONFIG ─────────────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")
MIN_DAYS_MA5   = 5
MIN_DAYS_MA20  = 20
MIN_DAYS_MA50  = 50
MIN_DAYS_RSI   = 14
MIN_DAYS_MACD  = 26
MIN_DAYS_BB    = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── DATABASE SETUP ─────────────────────────────────────────────────────────

def create_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA cache_size=-32000;")
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS technical_indicators (
            symbol          TEXT,
            date            TEXT,
            close           REAL,
            volume          REAL,

            -- Moving Averages
            ma5             REAL,
            ma10            REAL,
            ma20            REAL,
            ma50            REAL,
            ema12           REAL,
            ema26           REAL,

            -- MACD
            macd            REAL,
            macd_signal     REAL,
            macd_hist       REAL,

            -- RSI
            rsi14           REAL,

            -- Bollinger Bands
            bb_upper        REAL,
            bb_middle       REAL,
            bb_lower        REAL,
            bb_width        REAL,
            bb_pct          REAL,  -- % vị trí trong band (0=lower, 1=upper)

            -- ATR
            atr14           REAL,
            atr_pct         REAL,  -- atr / close * 100

            -- Volume
            vol_ma5         REAL,
            vol_ratio       REAL,  -- volume / vol_ma5

            -- Price Momentum (%)
            price_change_1d  REAL,
            price_change_5d  REAL,
            price_change_20d REAL,

            -- Trend Signal (1=uptrend, -1=downtrend, 0=neutral)
            trend_short     INTEGER,
            trend_medium    INTEGER,

            -- Price vs MAs
            pct_from_ma20   REAL,  -- (close - ma20) / ma20 * 100
            pct_from_ma50   REAL,

            updated_at      TEXT,
            PRIMARY KEY (symbol, date)
        );

        CREATE INDEX IF NOT EXISTS idx_tech_symbol ON technical_indicators(symbol);
        CREATE INDEX IF NOT EXISTS idx_tech_date   ON technical_indicators(date);
        CREATE INDEX IF NOT EXISTS idx_tech_rsi    ON technical_indicators(rsi14);
        CREATE INDEX IF NOT EXISTS idx_tech_trend  ON technical_indicators(trend_short);
    """)
    conn.commit()
    log.info("DB schema OK")


# ─── INDICATOR CALCULATIONS ─────────────────────────────────────────────────

def safe_val(v):
    """Convert numpy/float NaN → None cho SQLite."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else round(f, 6)  # NaN check
    except (TypeError, ValueError):
        return None


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    # Wilder smoothing = EMA với alpha=1/period
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr = pd.DataFrame({
        "hl":  high - low,
        "hc":  (high - prev_close).abs(),
        "lc":  (low  - prev_close).abs(),
    }).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr


def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Nhận DataFrame có columns: date, open, high, low, close, volume
    Trả về DataFrame với tất cả chỉ số kỹ thuật.
    Adaptive: chỉ tính chỉ số khi đủ data.
    """
    n = len(df)
    c = df["close"]
    v = df["volume"]
    h = df["high"]
    l = df["low"]

    out = df[["date", "close", "volume"]].copy()

    # ── Moving Averages ──────────────────────────────────────
    out["ma5"]  = c.rolling(5,  min_periods=5).mean()  if n >= MIN_DAYS_MA5  else None
    out["ma10"] = c.rolling(10, min_periods=10).mean() if n >= 10            else None
    out["ma20"] = c.rolling(20, min_periods=MIN_DAYS_MA20).mean() if n >= MIN_DAYS_MA20 else None
    out["ma50"] = c.rolling(50, min_periods=MIN_DAYS_MA50).mean() if n >= MIN_DAYS_MA50 else None

    # ── EMA & MACD ───────────────────────────────────────────
    if n >= MIN_DAYS_MACD:
        ema12 = c.ewm(span=12, min_periods=12, adjust=False).mean()
        ema26 = c.ewm(span=26, min_periods=26, adjust=False).mean()
        macd  = ema12 - ema26
        signal = macd.ewm(span=9, min_periods=9, adjust=False).mean()
        out["ema12"]       = ema12
        out["ema26"]       = ema26
        out["macd"]        = macd
        out["macd_signal"] = signal
        out["macd_hist"]   = macd - signal
    else:
        for col in ["ema12", "ema26", "macd", "macd_signal", "macd_hist"]:
            out[col] = None

    # ── RSI ──────────────────────────────────────────────────
    out["rsi14"] = calc_rsi(c, 14) if n >= MIN_DAYS_RSI else None

    # ── Bollinger Bands ──────────────────────────────────────
    if n >= MIN_DAYS_BB:
        bb_mid   = c.rolling(20, min_periods=20).mean()
        bb_std   = c.rolling(20, min_periods=20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan) * 100
        # % B = (close - lower) / (upper - lower)
        bb_range = (bb_upper - bb_lower).replace(0, np.nan)
        bb_pct   = (c - bb_lower) / bb_range
        out["bb_upper"]  = bb_upper
        out["bb_middle"] = bb_mid
        out["bb_lower"]  = bb_lower
        out["bb_width"]  = bb_width
        out["bb_pct"]    = bb_pct
    else:
        for col in ["bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_pct"]:
            out[col] = None

    # ── ATR ──────────────────────────────────────────────────
    if n >= MIN_DAYS_RSI:
        atr = calc_atr(h, l, c, 14)
        out["atr14"]   = atr
        out["atr_pct"] = (atr / c.replace(0, np.nan) * 100)
    else:
        out["atr14"]   = None
        out["atr_pct"] = None

    # ── Volume ───────────────────────────────────────────────
    if n >= MIN_DAYS_MA5:
        vol_ma5 = v.rolling(5, min_periods=5).mean()
        out["vol_ma5"]   = vol_ma5
        out["vol_ratio"] = v / vol_ma5.replace(0, np.nan)
    else:
        out["vol_ma5"]   = None
        out["vol_ratio"] = None

    # ── Price Momentum ───────────────────────────────────────
    out["price_change_1d"]  = c.pct_change(1) * 100  if n >= 2  else None
    out["price_change_5d"]  = c.pct_change(5) * 100  if n >= 6  else None
    out["price_change_20d"] = c.pct_change(20) * 100 if n >= 21 else None

    # ── Trend Signals ────────────────────────────────────────
    # Short trend: MA5 vs MA20 (nếu đủ data, dùng price vs MA5)
    if "ma5" in out.columns and out["ma5"].notna().any():
        ma5_col = out["ma5"]
        if "ma20" in out.columns and out["ma20"].notna().any():
            out["trend_short"] = np.where(ma5_col > out["ma20"], 1,
                                 np.where(ma5_col < out["ma20"], -1, 0))
        else:
            out["trend_short"] = np.where(c > ma5_col, 1,
                                 np.where(c < ma5_col, -1, 0))
    else:
        out["trend_short"] = 0

    # Medium trend: MA20 vs MA50
    if "ma20" in out.columns and "ma50" in out.columns and \
       out["ma20"].notna().any() and out["ma50"].notna().any():
        out["trend_medium"] = np.where(out["ma20"] > out["ma50"], 1,
                              np.where(out["ma20"] < out["ma50"], -1, 0))
    else:
        out["trend_medium"] = 0

    # ── Price vs MAs ─────────────────────────────────────────
    if "ma20" in out.columns:
        out["pct_from_ma20"] = (c - out["ma20"]) / out["ma20"].replace(0, np.nan) * 100
    else:
        out["pct_from_ma20"] = None

    if "ma50" in out.columns:
        out["pct_from_ma50"] = (c - out["ma50"]) / out["ma50"].replace(0, np.nan) * 100
    else:
        out["pct_from_ma50"] = None

    out["updated_at"] = datetime.now().isoformat()

    return out


# ─── LOAD & SAVE ─────────────────────────────────────────────────────────────

def load_prices(conn) -> dict[str, pd.DataFrame]:
    """Load toàn bộ stock_prices, trả về dict {symbol: DataFrame}."""
    df = pd.read_sql(
        "SELECT symbol, date, open, high, low, close, volume FROM stock_prices ORDER BY symbol, date",
        conn,
    )
    if df.empty:
        return {}
    # Normalize date - strip timestamp, keep YYYY-MM-DD only
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["symbol", "date"]).drop_duplicates(subset=["symbol", "date"])
    result = {}
    for sym, grp in df.groupby("symbol"):
        result[sym] = grp.reset_index(drop=True)
    return result


COLUMNS_ORDER = [
    "symbol", "date", "close", "volume",
    "ma5", "ma10", "ma20", "ma50", "ema12", "ema26",
    "macd", "macd_signal", "macd_hist",
    "rsi14",
    "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_pct",
    "atr14", "atr_pct",
    "vol_ma5", "vol_ratio",
    "price_change_1d", "price_change_5d", "price_change_20d",
    "trend_short", "trend_medium",
    "pct_from_ma20", "pct_from_ma50",
    "updated_at",
]


def upsert_indicators(conn, symbol: str, indicators_df: pd.DataFrame, batch_rows: list):
    """Chuẩn bị rows để batch insert."""
    now = datetime.now().isoformat()
    for _, row in indicators_df.iterrows():
        record = [symbol]
        for col in COLUMNS_ORDER[1:]:  # skip 'symbol'
            if col == "date":
                # date is stored as string YYYY-MM-DD in our df
                val = row.get("date")
                if val is None or (hasattr(val, '__class__') and val.__class__.__name__ == 'NaTType'):
                    record.append(None)
                else:
                    record.append(str(val)[:10])  # ensure YYYY-MM-DD
            elif col in ("trend_short", "trend_medium"):
                val = row.get(col)
                try:
                    record.append(int(val) if val is not None and val == val else 0)
                except (TypeError, ValueError):
                    record.append(0)
            elif col == "updated_at":
                record.append(now)
            else:
                record.append(safe_val(row.get(col)))
        batch_rows.append(tuple(record))


def flush_batch(conn, batch_rows: list):
    if not batch_rows:
        return
    placeholders = ", ".join(["?"] * len(COLUMNS_ORDER))
    cols = ", ".join(COLUMNS_ORDER)
    conn.executemany(
        f"INSERT OR REPLACE INTO technical_indicators ({cols}) VALUES ({placeholders})",
        batch_rows,
    )
    conn.commit()
    batch_rows.clear()


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    conn = create_connection()
    init_db(conn)

    log.info("Loading price data...")
    prices = load_prices(conn)
    total  = len(prices)
    log.info("Loaded %d symbols", total)

    if not prices:
        log.warning("Không có data giá nào trong DB. Chạy hose_daily.py trước.")
        conn.close()
        return

    ok = skip = fail = 0
    batch_rows = []
    BATCH_SIZE = 50

    for i, (symbol, df_price) in enumerate(prices.items(), 1):
        try:
            if len(df_price) < MIN_DAYS_MA5:
                skip += 1
                continue
            indicators = calc_indicators(df_price)
            # Chỉ lưu row mới nhất (ngày cuối) để không bloat DB
            # Nếu muốn lưu toàn bộ lịch sử thì bỏ dòng filter này
            latest = indicators.tail(1)
            upsert_indicators(conn, symbol, latest, batch_rows)
            ok += 1

            if len(batch_rows) >= BATCH_SIZE:
                flush_batch(conn, batch_rows)
                log.info("  Flush batch %d/%d...", i, total)

        except Exception as e:
            log.warning("FAIL %s: %s", symbol, e)
            fail += 1

    flush_batch(conn, batch_rows)

    # Verify
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM technical_indicators")
    rows_in_db = cur.fetchone()[0]

    conn.close()
    log.info("✅ Done — OK: %d | Skip: %d | Fail: %d | DB rows: %d",
             ok, skip, fail, rows_in_db)


if __name__ == "__main__":
    run()
