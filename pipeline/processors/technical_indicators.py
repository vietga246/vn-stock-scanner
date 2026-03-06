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
MIN_DAYS_ADX   = 28   # Wilder smoothing cần ≥28 bars để ổn định
MIN_DAYS_VOLMA20 = 20 # vol_MA20 baseline cho spike detection

# FVG quality filter thresholds
FVG_MIN_SIZE_PCT  = 0.5   # Gap tối thiểu 0.5% để loại micro-gaps
FVG_MAX_AGE_BARS  = 5     # FVG fresh ≤5 bars (stale FVG ít có giá trị)
FVG_MAX_FILL_PCT  = 50.0  # FVG còn ≥50% unfilled mới tính

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
            bb_pct          REAL,

            -- ATR
            atr14           REAL,
            atr_pct         REAL,

            -- ADX — Trend Strength (Wilder, period=14, can >= 28 bars)
            adx14           REAL,
            plus_di14       REAL,
            minus_di14      REAL,
            di_spread       REAL,

            -- Trend Strength Score (0-100 composite)
            trend_strength  REAL,

            -- Volume
            vol_ma5         REAL,
            vol_ma20        REAL,
            vol_ratio       REAL,

            -- Price Momentum (%)
            price_change_1d  REAL,
            price_change_5d  REAL,
            price_change_20d REAL,

            -- Trend Signal (1=uptrend, -1=downtrend, 0=neutral)
            trend_short     INTEGER,
            trend_medium    INTEGER,

            -- Price vs MAs
            pct_from_ma20   REAL,
            pct_from_ma50   REAL,

            -- FVG — Fair Value Gap (filtered: size>=0.5%, age<=5, fill<50%)
            fvg_bull        INTEGER,
            fvg_bear        INTEGER,
            fvg_bull_size   REAL,
            fvg_bear_size   REAL,
            fvg_bull_age    INTEGER,
            fvg_bear_age    INTEGER,
            fvg_bull_fill   REAL,
            fvg_bear_fill   REAL,

            updated_at      TEXT,
            PRIMARY KEY (symbol, date)
        );

        CREATE INDEX IF NOT EXISTS idx_tech_symbol ON technical_indicators(symbol);
        CREATE INDEX IF NOT EXISTS idx_tech_date   ON technical_indicators(date);
        CREATE INDEX IF NOT EXISTS idx_tech_rsi    ON technical_indicators(rsi14);
        CREATE INDEX IF NOT EXISTS idx_tech_trend  ON technical_indicators(trend_short);
        CREATE INDEX IF NOT EXISTS idx_tech_adx    ON technical_indicators(adx14);
        CREATE INDEX IF NOT EXISTS idx_tech_fvg    ON technical_indicators(fvg_bull, fvg_bear);
    """)
    conn.commit()

    # ── Migration: thêm columns mới vào bảng đã tồn tại ──────────────────────
    # SQLite không hỗ trợ IF NOT EXISTS cho ALTER TABLE ADD COLUMN,
    # nên phải kiểm tra PRAGMA table_info trước.
    _migrate_add_columns(conn)

    log.info("DB schema OK")


def _migrate_add_columns(conn):
    """
    Thêm columns mới vào technical_indicators nếu chưa có.
    Chạy mỗi lần nhưng chỉ thực sự ALTER khi cần — idempotent.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(technical_indicators)")
    existing = {row[1] for row in cur.fetchall()}

    # Danh sách (column_name, column_def) theo thứ tự thêm vào
    new_columns = [
        # ADX
        ("adx14",          "REAL"),
        ("plus_di14",       "REAL"),
        ("minus_di14",      "REAL"),
        ("di_spread",       "REAL"),
        # Trend Strength
        ("trend_strength",  "REAL"),
        # Volume baseline
        ("vol_ma20",        "REAL"),
        # Price vs MAs (có thể chưa có ở DB cũ)
        ("pct_from_ma20",   "REAL"),
        ("pct_from_ma50",   "REAL"),
        # FVG
        ("fvg_bull",        "INTEGER"),
        ("fvg_bear",        "INTEGER"),
        ("fvg_bull_size",   "REAL"),
        ("fvg_bear_size",   "REAL"),
        ("fvg_bull_age",    "INTEGER"),
        ("fvg_bear_age",    "INTEGER"),
        ("fvg_bull_fill",   "REAL"),
        ("fvg_bear_fill",   "REAL"),
    ]

    added = []
    for col, col_type in new_columns:
        if col not in existing:
            conn.execute(
                f"ALTER TABLE technical_indicators ADD COLUMN {col} {col_type}"
            )
            added.append(col)

    if added:
        conn.commit()
        log.info("Migration: thêm %d columns mới: %s", len(added), ", ".join(added))

    # Thêm indexes mới nếu chưa có (CREATE INDEX IF NOT EXISTS — an toàn)
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tech_adx "
            "ON technical_indicators(adx14)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tech_fvg "
            "ON technical_indicators(fvg_bull, fvg_bear)"
        )
        conn.commit()
    except Exception:
        pass  # index đã tồn tại hoặc columns chưa có → bỏ qua


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


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """
    ADX(14) + +DI14 + -DI14 theo phương pháp Wilder.
    Cần >= 28 bars để Wilder smoothing ổn định.

    Returns DataFrame với columns: adx14, plus_di14, minus_di14
    """
    # Directional Movement
    up_move   = high.diff()
    down_move = (-low).diff()  # low.shift(1) - low

    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=high.index)
    minus_dm_s = pd.Series(minus_dm, index=high.index)

    # Wilder smoothing
    atr = calc_atr(high, low, close, period)

    plus_dm_w  = plus_dm_s.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    minus_dm_w = minus_dm_s.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    # DI
    plus_di  = (plus_dm_w  / atr.replace(0, np.nan) * 100).fillna(0)
    minus_di = (minus_dm_w / atr.replace(0, np.nan) * 100).fillna(0)

    # DX → ADX
    di_sum  = (plus_di + minus_di).replace(0, np.nan)
    dx      = (plus_di - minus_di).abs() / di_sum * 100
    adx     = dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    return pd.DataFrame({
        "adx14":     adx.round(4),
        "plus_di14": plus_di.round(4),
        "minus_di14": minus_di.round(4),
    }, index=high.index)


def calc_fvg(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fair Value Gap (FVG / Imbalance) detection với quality filter.

    Bullish FVG : high[i-1] < low[i+1]  → gap lên, demand imbalance
    Bearish FVG : low[i-1]  > high[i+1] → gap xuống, supply imbalance

    Quality filter (bắt buộc để giảm từ raw 74% xuống ~32%):
      - size  >= FVG_MIN_SIZE_PCT (0.5%) : loại micro-gaps
      - age   <= FVG_MAX_AGE_BARS (5)    : FVG fresh > stale
      - fill  <  FVG_MAX_FILL_PCT (50%)  : còn phần lớn unfilled

    Returns DataFrame với fvg_bull, fvg_bear và metadata cho FVG gần nhất.
    """
    n = len(df)
    if n < 3:
        empty_cols = ["fvg_bull", "fvg_bear", "fvg_bull_size", "fvg_bear_size",
                      "fvg_bull_age", "fvg_bear_age", "fvg_bull_fill", "fvg_bear_fill"]
        result = pd.DataFrame(index=df.index)
        for col in empty_cols:
            result[col] = None
        return result

    hi  = df["high"].values
    lo  = df["low"].values
    cls = df["close"].values

    fvg_bull_list = []  # (bar_idx, top, bottom)
    fvg_bear_list = []  # (bar_idx, top, bottom)

    # Detect all FVGs in history
    for i in range(1, n - 1):
        # Bullish FVG: high[i-1] < low[i+1]
        if hi[i-1] < lo[i+1]:
            gap_bottom = hi[i-1]
            gap_top    = lo[i+1]
            size_pct   = (gap_top - gap_bottom) / gap_bottom * 100 if gap_bottom > 0 else 0
            if size_pct >= FVG_MIN_SIZE_PCT:
                fvg_bull_list.append((i, gap_top, gap_bottom))

        # Bearish FVG: low[i-1] > high[i+1]
        if lo[i-1] > hi[i+1]:
            gap_top    = lo[i-1]
            gap_bottom = hi[i+1]
            size_pct   = (gap_top - gap_bottom) / gap_bottom * 100 if gap_bottom > 0 else 0
            if size_pct >= FVG_MIN_SIZE_PCT:
                fvg_bear_list.append((i, gap_top, gap_bottom))

    last_bar = n - 1

    def find_best_fvg(fvg_list, is_bull: bool):
        """Tìm FVG gần nhất còn active (chưa bị fill > 50%)."""
        best = None
        for (bar_idx, gap_top, gap_bottom) in reversed(fvg_list):
            age = last_bar - bar_idx
            if age > FVG_MAX_AGE_BARS:
                break  # đã sort theo thứ tự, không cần tiếp

            gap_size = gap_top - gap_bottom
            if gap_size <= 0:
                continue

            # Tính fill: xem price sau FVG có penetrate vào gap không
            fill_pct = 0.0
            prices_after = cls[bar_idx + 1: last_bar + 1]
            if len(prices_after) > 0:
                if is_bull:
                    # Bullish FVG fill: price đi xuống vào gap
                    min_after = min(prices_after)
                    if min_after < gap_top:
                        penetration = min(gap_top - min_after, gap_size)
                        fill_pct = penetration / gap_size * 100
                else:
                    # Bearish FVG fill: price đi lên vào gap
                    max_after = max(prices_after)
                    if max_after > gap_bottom:
                        penetration = min(max_after - gap_bottom, gap_size)
                        fill_pct = penetration / gap_size * 100

            if fill_pct < FVG_MAX_FILL_PCT:
                size_pct = (gap_top - gap_bottom) / gap_bottom * 100 if gap_bottom > 0 else 0
                best = {
                    "size":  round(size_pct, 4),
                    "age":   age,
                    "fill":  round(fill_pct, 2),
                }
                break  # lấy FVG gần nhất đạt tiêu chuẩn
        return best

    best_bull = find_best_fvg(fvg_bull_list, is_bull=True)
    best_bear = find_best_fvg(fvg_bear_list, is_bull=False)

    result = pd.DataFrame(index=df.index)
    result["fvg_bull"]      = 0
    result["fvg_bear"]      = 0
    result["fvg_bull_size"] = None
    result["fvg_bear_size"] = None
    result["fvg_bull_age"]  = None
    result["fvg_bear_age"]  = None
    result["fvg_bull_fill"] = None
    result["fvg_bear_fill"] = None

    if best_bull:
        result.iloc[-1, result.columns.get_loc("fvg_bull")]      = 1
        result.iloc[-1, result.columns.get_loc("fvg_bull_size")] = best_bull["size"]
        result.iloc[-1, result.columns.get_loc("fvg_bull_age")]  = best_bull["age"]
        result.iloc[-1, result.columns.get_loc("fvg_bull_fill")] = best_bull["fill"]

    if best_bear:
        result.iloc[-1, result.columns.get_loc("fvg_bear")]      = 1
        result.iloc[-1, result.columns.get_loc("fvg_bear_size")] = best_bear["size"]
        result.iloc[-1, result.columns.get_loc("fvg_bear_age")]  = best_bear["age"]
        result.iloc[-1, result.columns.get_loc("fvg_bear_fill")] = best_bear["fill"]

    return result


def calc_trend_strength(c: pd.Series, ma5, ma20, ma50, adx_series: pd.Series,
                        ema12: pd.Series, n: int) -> pd.Series:
    """
    Trend Strength Score (0-100) — Composite 4 thành phần:
      A. ADX(14) component     [40%]: ADX>25=trending, >40=strong, >60=extreme
      B. MA alignment          [30%]: price > MA5 > MA20 > MA50 = full 30pts
      C. EMA slope             [15%]: rate of change EMA12 10 bars
      D. HH/HL frequency       [15%]: % ngày close > close_prev trong 10 bars

    Cần >= 10 bars. ADX cần >= 28 bars (dùng 0 nếu thiếu).
    """
    if n < 10:
        return pd.Series(None, index=c.index)

    # A. ADX component (40%)
    if adx_series is not None and adx_series.notna().any():
        score_a = adx_series.clip(0, 60) / 60 * 40
    else:
        score_a = pd.Series(0.0, index=c.index)

    # B. MA alignment (30%) — count how many MAs are stacked correctly
    score_b = pd.Series(0.0, index=c.index)
    if ma5 is not None and ma5.notna().any():
        score_b += np.where(c > ma5, 10, 0)
        if ma20 is not None and ma20.notna().any():
            score_b += np.where(ma5 > ma20, 10, 0)
            if ma50 is not None and ma50.notna().any():
                score_b += np.where(ma20 > ma50, 10, 0)

    # C. EMA slope (15%) — (EMA[-1] - EMA[-10]) / EMA[-10] * 100
    score_c = pd.Series(7.5, index=c.index)  # neutral default
    if ema12 is not None and ema12.notna().any():
        ema_10ago = ema12.shift(10)
        slope_pct = (ema12 - ema_10ago) / ema_10ago.replace(0, np.nan) * 100
        score_c = slope_pct.clip(-5, 5) / 5 * 15 + 7.5  # -5%→0, 0%→7.5, +5%→15
        score_c = score_c.fillna(7.5)

    # D. HH/HL frequency (15%) — rolling 10-bar close-over-close count
    hhhl = (c > c.shift(1)).rolling(10, min_periods=5).mean().fillna(0.5)
    score_d = hhhl * 15

    trend_str = (score_a + score_b + score_c + score_d).clip(0, 100).round(2)
    return trend_str


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
        out["vol_ma5"] = vol_ma5
    else:
        out["vol_ma5"] = None
        vol_ma5 = None

    if n >= MIN_DAYS_VOLMA20:
        vol_ma20 = v.rolling(20, min_periods=20).mean()
        out["vol_ma20"] = vol_ma20
        # vol_ratio dùng MA20 làm baseline chuẩn khi có đủ data
        out["vol_ratio"] = v / vol_ma20.replace(0, np.nan)
    else:
        out["vol_ma20"] = None
        # Fallback về MA5 khi chưa đủ 20 bars
        if vol_ma5 is not None:
            out["vol_ratio"] = v / vol_ma5.replace(0, np.nan)
        else:
            out["vol_ratio"] = None

    # ── ADX — Directional Index ──────────────────────────────
    if n >= MIN_DAYS_ADX:
        adx_df = calc_adx(h, l, c, 14)
        out["adx14"]      = adx_df["adx14"]
        out["plus_di14"]  = adx_df["plus_di14"]
        out["minus_di14"] = adx_df["minus_di14"]
        out["di_spread"]  = (adx_df["plus_di14"] - adx_df["minus_di14"]).round(4)
        adx_series_for_ts = adx_df["adx14"]
    else:
        out["adx14"]      = None
        out["plus_di14"]  = None
        out["minus_di14"] = None
        out["di_spread"]  = None
        adx_series_for_ts = None

    # ── FVG — Fair Value Gap (filtered) ──────────────────────
    fvg_df = calc_fvg(df)
    for col in ["fvg_bull", "fvg_bear", "fvg_bull_size", "fvg_bear_size",
                "fvg_bull_age", "fvg_bear_age", "fvg_bull_fill", "fvg_bear_fill"]:
        out[col] = fvg_df[col]

    # ── Trend Strength Score ──────────────────────────────────
    ma5_col  = out.get("ma5")  if "ma5"  in out.columns else None
    ma20_col = out.get("ma20") if "ma20" in out.columns else None
    ma50_col = out.get("ma50") if "ma50" in out.columns else None
    ema12_col = out.get("ema12") if "ema12" in out.columns else None
    out["trend_strength"] = calc_trend_strength(
        c, ma5_col, ma20_col, ma50_col, adx_series_for_ts, ema12_col, n
    )

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
    # Moving Averages
    "ma5", "ma10", "ma20", "ma50", "ema12", "ema26",
    # MACD
    "macd", "macd_signal", "macd_hist",
    # RSI
    "rsi14",
    # Bollinger Bands
    "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_pct",
    # ATR
    "atr14", "atr_pct",
    # ADX — Trend Strength
    "adx14", "plus_di14", "minus_di14", "di_spread",
    # Trend Strength Score (composite 0-100)
    "trend_strength",
    # Volume (vol_ma20 = baseline chuẩn sau PRICE_DAYS_LIMIT=200)
    "vol_ma5", "vol_ma20", "vol_ratio",
    # Price Momentum
    "price_change_1d", "price_change_5d", "price_change_20d",
    # Trend Signal
    "trend_short", "trend_medium",
    # Price vs MAs
    "pct_from_ma20", "pct_from_ma50",
    # FVG — Fair Value Gap (filtered quality)
    "fvg_bull", "fvg_bear",
    "fvg_bull_size", "fvg_bear_size",
    "fvg_bull_age", "fvg_bear_age",
    "fvg_bull_fill", "fvg_bear_fill",
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
