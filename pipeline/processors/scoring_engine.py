"""
scoring.py — Composite Scoring Engine cho VN Stock Scanner

Tính điểm tổng hợp (0–100) cho từng cổ phiếu dựa trên 4 trụ cột:

  A. Fundamental Score  (35%): PE, ROE, ROA, revenue growth, net margin, D/E
  B. Smart Money Score  (30%): Net foreign flow 7d + 30d
                               (prop trading và insider deals không có data từ VCI source)
  C. Momentum Score     (15%): Price momentum 5d/20d, volume surge, RS vs market
                               [Giảm từ 20% → 15%: backtest cho thấy momentum cao có
                                edge âm (-0.88%) do đặc tính mean reversion của VNSTOCK]
  D. Technical Score    (20%): RSI oversold/trend/ADX — tăng từ 15% vì backtest xác nhận
                               RSI<35 edge +1.02%, Trend+ADX>30 edge +1.54%

Scoring method: percentile rank trong universe (loại bỏ outliers)
  → Mỗi chỉ số được rank từ 0–100 theo phân phối thực tế của thị trường
  → Tránh bị lệch vì outliers (HGM ROE=116% sẽ không kéo toàn bộ thang điểm)

Backtest findings (33,055 observations, Aug 2025–Mar 2026, walk-forward):
  ✅ RSI < 35 oversold:            edge +1.02% fwd20D, p=0.0001
  ✅ Trend UP (P>MA20>MA50):       edge +0.77% fwd20D, p=0.0000
  ✅ Combo Trend+ADX>30+RSI<70:    edge +1.54% fwd20D, p=0.0000
  ✅ ADX Very Strong (>50):        edge +0.62% fwd20D, p=0.021
  ❌ MACD Histogram Positive:      edge -0.67% fwd20D (CONTRARIAN)
  ❌ Momentum Strong (>10% 20D):   edge -0.88% fwd20D (mean reversion)

Output:
  - Table `stock_scores` trong stock.db
  - Includes: từng component score + composite + rank + tier (A/B/C/D/F)
  - Mỗi symbol chỉ có 1 row (latest score)
"""

import sqlite3
import pandas as pd
import numpy as np
import logging
import sys
import os
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'utils'))
from trading_calendar import trading_date_cutoff, get_trading_date_list_sql

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")

# Trọng số các trụ cột
# v2: Momentum giảm 20→15%, Technical tăng 15→20%
# Lý do: backtest 33k obs — momentum cao có edge âm (-0.88%), RSI/Trend có edge dương mạnh
WEIGHTS = {
    "fundamental": 0.35,
    "smart_money": 0.30,
    "momentum":    0.15,   # ↓ từ 0.20 — momentum mạnh có edge âm trên VNSTOCK
    "technical":   0.20,   # ↑ từ 0.15 — RSI oversold & trend có edge dương có ý nghĩa
}

# ════════════════════════════════════════════════════════════════════════════
# PENALTY CHO CỔ PHIẾU CẢNH BÁO/KIỂM SOÁT
# Cổ phiếu trong diện cảnh báo/kiểm soát sẽ bị trừ điểm composite
# ════════════════════════════════════════════════════════════════════════════
WARNING_PENALTIES = {
    "control":     0.50,  # Kiểm soát: trừ 50% điểm (điểm max = 50)
    "warning":     0.30,  # Cảnh báo: trừ 30% điểm (điểm max = 70)
    "restriction": 0.15,  # Hạn chế: trừ 15% điểm (điểm max = 85)
    "delisting":   0.70,  # Sắp hủy niêm yết: trừ 70% (điểm max = 30)
    "normal":      0.00,  # Bình thường: không trừ
}

# Trọng số các chỉ số trong từng trụ cột
FUNDAMENTAL_WEIGHTS = {
    "roe_score":             0.25,
    "roa_score":             0.15,
    "revenue_growth_score":  0.20,
    "net_margin_score":      0.15,
    "pe_score":              0.15,  # inverted (PE thấp = tốt)
    "debt_equity_score":     0.10,  # inverted (D/E thấp = tốt)
}

SMART_MONEY_WEIGHTS = {
    # prop_trading không có data từ VCI source → chỉ dùng foreign flow
    # 0.30 (prop) được redistribute: foreign_7d +0.20, foreign_30d +0.10
    "foreign_net_7d_score":  0.60,
    "foreign_net_30d_score": 0.40,
}

MOMENTUM_WEIGHTS = {
    # v2: giảm trọng số price_20d vì momentum mạnh (>10%) có edge âm (-0.88%)
    # RS vs market giữ nguyên — relative strength có giá trị hơn absolute momentum
    "price_5d_score":     0.25,   # ↓ từ 0.30
    "price_20d_score":    0.25,   # ↓ từ 0.35 — cẩn thận momentum kéo dài
    "vol_surge_score":    0.25,   # ↑ từ 0.20 — volume confirmation quan trọng hơn
    "rs_vs_market_score": 0.25,   # ↑ từ 0.15 — relative strength tốt hơn absolute
}

TECHNICAL_WEIGHTS = {
    # v2: Bỏ MACD (edge -0.67%), thêm ADX bucket score
    # RSI oversold edge +1.02% (p=0.0001) → tăng trọng số
    # Trend UP edge +0.77% (p=0.0000) → giữ nguyên cao
    # ADX >50 edge +0.62% (p=0.021) → thêm mới
    "rsi_score":   0.40,   # ↑ từ 0.35 — RSI oversold là signal tốt nhất
    "trend_score": 0.35,   # ↑ từ 0.30 — Trend UP có ý nghĩa thống kê mạnh
    "adx_score":   0.25,   # NEW — thay MACD (0.35 → 0): ADX >50 edge +0.62%
    # macd_score: LOẠI BỎ — edge -0.67% fwd20D, contrarian signal trên VNSTOCK
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── DATABASE ───────────────────────────────────────────────────────────────

def create_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock_scores (
            symbol              TEXT PRIMARY KEY,

            -- Component Scores (0-100)
            fundamental_score   REAL,
            smart_money_score   REAL,
            momentum_score      REAL,
            technical_score     REAL,
            composite_score     REAL,

            -- Sub-scores
            roe_score           REAL,
            roa_score           REAL,
            revenue_growth_score REAL,
            net_margin_score    REAL,
            pe_score            REAL,
            debt_equity_score   REAL,
            foreign_net_7d_score  REAL,
            foreign_net_30d_score REAL,
            price_5d_score      REAL,
            price_20d_score     REAL,
            vol_surge_score     REAL,
            rs_vs_market_score  REAL,
            rsi_score           REAL,
            macd_score          REAL,   -- deprecated: weight=0, kept for backward compat
            adx_score           REAL,   -- NEW v2: bucket score ADX >50 edge +0.62%
            trend_score         REAL,

            -- Fundamental raw values
            roe                 REAL,
            roa                 REAL,
            pe                  REAL,
            revenue_growth      REAL,
            net_margin          REAL,
            debt_equity         REAL,

            -- Price momentum
            price_change_1d     REAL,
            price_change_5d     REAL,
            price_change_20d    REAL,

            -- Technical core
            vol_ratio           REAL,
            vol_ma20            REAL,
            rsi14               REAL,
            macd_hist           REAL,
            trend_short         INTEGER,
            pct_from_ma20       REAL,
            pct_from_ma50       REAL,

            -- ADX + Trend Strength (NEW)
            adx14               REAL,
            plus_di14           REAL,
            minus_di14          REAL,
            di_spread           REAL,
            trend_strength      REAL,

            -- Volatility (NEW — previously calculated but not stored in scores)
            bb_width            REAL,
            atr14               REAL,
            atr_pct             REAL,

            -- FVG signals (NEW)
            fvg_bull            INTEGER,
            fvg_bear            INTEGER,
            fvg_bull_size       REAL,
            fvg_bear_size       REAL,
            fvg_bull_age        INTEGER,
            fvg_bear_age        INTEGER,
            fvg_bull_fill       REAL,
            fvg_bear_fill       REAL,

            -- Smart money raw values (ty dong)
            foreign_net_7d      REAL,
            foreign_net_30d     REAL,

            -- Ranking
            rank_total          INTEGER,
            rank_pct            REAL,
            tier                TEXT,

            -- Metadata
            data_completeness   REAL,
            scored_at           TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scores_composite ON stock_scores(composite_score DESC);
        CREATE INDEX IF NOT EXISTS idx_scores_tier      ON stock_scores(tier);
        CREATE INDEX IF NOT EXISTS idx_scores_fundamental ON stock_scores(fundamental_score DESC);
        CREATE INDEX IF NOT EXISTS idx_scores_smart_money ON stock_scores(smart_money_score DESC);
        -- v3: mean_reversion_score (crash bounce edge)
        -- ALTER handled in _migrate

    """)
    conn.commit()
    _migrate_stock_scores(conn)
    log.info("stock_scores table OK")


def _migrate_stock_scores(conn):
    """Thêm columns mới vào stock_scores nếu chưa có — idempotent, safe."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(stock_scores)")
    existing = {row[1] for row in cur.fetchall()}

    new_columns = [
        ("roa",             "REAL"),
        ("vol_ma20",        "REAL"),
        ("pct_from_ma20",   "REAL"),
        ("pct_from_ma50",   "REAL"),
        ("adx14",           "REAL"),
        ("plus_di14",       "REAL"),
        ("minus_di14",      "REAL"),
        ("di_spread",       "REAL"),
        ("trend_strength",  "REAL"),
        ("bb_width",        "REAL"),
        ("atr14",           "REAL"),
        ("atr_pct",         "REAL"),
        ("macd_hist",       "REAL"),
        ("fvg_bull",        "INTEGER"),
        ("fvg_bear",        "INTEGER"),
        ("fvg_bull_size",   "REAL"),
        ("fvg_bear_size",   "REAL"),
        ("fvg_bull_age",    "INTEGER"),
        ("fvg_bear_age",    "INTEGER"),
        ("fvg_bull_fill",   "REAL"),
        ("fvg_bear_fill",   "REAL"),
        ("adx_score",       "REAL"),   # v2: NEW — thay MACD trong technical score
        ("mean_reversion_score", "REAL"), # v3: crash bounce edge +1.79% fwd10D
        ("regime_adj_score",     "REAL"), # v3: composite × regime_multiplier
    ]

    added = []
    for col, col_type in new_columns:
        if col not in existing:
            conn.execute(f"ALTER TABLE stock_scores ADD COLUMN {col} {col_type}")
            added.append(col)

    if added:
        conn.commit()
        log.info("Migration stock_scores: thêm %d columns mới: %s",
                 len(added), ", ".join(added))


# ─── DATA LOADING ────────────────────────────────────────────────────────────

def load_fundamentals(conn) -> pd.DataFrame:
    """Lấy chỉ số tài chính mới nhất của từng symbol."""
    df = pd.read_sql("""
        SELECT r.symbol, r.roe, r.roa, r.pe, r.net_margin, r.debt_equity,
               r.current_ratio, r.pb, r.ev_ebitda,
               i.revenue_growth, i.revenue, i.net_profit,
               b.total_assets, b.total_equity, b.cash,
               cf.cfo, cf.capex
        FROM financials_ratio r
        LEFT JOIN financials_income i
            ON r.symbol = i.symbol AND r.year = i.year AND r.quarter = i.quarter
        LEFT JOIN financials_balance b
            ON r.symbol = b.symbol AND r.year = b.year AND r.quarter = b.quarter
        LEFT JOIN financials_cashflow cf
            ON r.symbol = cf.symbol AND r.year = cf.year AND r.quarter = cf.quarter
        JOIN (
            SELECT symbol, MAX(year*10+quarter) AS yq
            FROM financials_ratio GROUP BY symbol
        ) mx ON r.symbol = mx.symbol AND r.year*10+r.quarter = mx.yq
        WHERE r.roe IS NOT NULL OR r.pe IS NOT NULL
    """, conn)
    log.info("Fundamentals loaded: %d symbols", len(df))
    return df


def load_smart_money(conn) -> pd.DataFrame:
    """
    Tổng hợp dòng tiền nước ngoài (foreign flow).

    Dùng trading_calendar để chỉ tính ngày giao dịch thực tế:
    7D = 7 phiên GD gần nhất, 30D = 30 phiên GD gần nhất.
    Loại trừ T7, CN và ngày lễ VN → kết quả chính xác hơn.
    """
    today = date.today()
    cutoff_7d  = trading_date_cutoff(7,  today)
    cutoff_30d = trading_date_cutoff(30, today)

    log.info("Foreign flow cutoffs: 7D=%s | 30D=%s", cutoff_7d, cutoff_30d)

    # Foreign flow 7 phiên GD
    foreign_7d = pd.read_sql(f"""
        SELECT symbol,
               SUM(net_value) AS foreign_net_7d,
               SUM(buy_value) AS foreign_buy_7d,
               SUM(sell_value) AS foreign_sell_7d
        FROM foreign_trading
        WHERE date >= '{cutoff_7d}'
        GROUP BY symbol
    """, conn)

    # Foreign flow 30 phiên GD
    foreign_30d = pd.read_sql(f"""
        SELECT symbol, SUM(net_value) AS foreign_net_30d
        FROM foreign_trading
        WHERE date >= '{cutoff_30d}'
        GROUP BY symbol
    """, conn)

    if foreign_7d.empty and foreign_30d.empty:
        log.warning("Smart money data rỗng (chưa chạy daily_foreign_flow.py hoặc API trả về empty)")
        return pd.DataFrame(columns=["symbol", "foreign_net_7d", "foreign_net_30d"])

    result = foreign_7d.merge(foreign_30d, on="symbol", how="outer")
    log.info("Smart money loaded: %d symbols", len(result))
    return result


def load_momentum(conn) -> pd.DataFrame:
    """
    Lấy momentum + technical indicators mới nhất của từng symbol.
    Bao gồm các fields mới: adx14, trend_strength, bb_width, fvg_*, vol_ma20.
    Dùng PRAGMA để kiểm tra columns available (backward-compatible với DB cũ).
    """
    # Kiểm tra columns tồn tại để backward-compatible
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(technical_indicators)")
    existing = {r[1] for r in cur.fetchall()}

    base_select = """symbol, date, close, price_change_1d, price_change_5d, price_change_20d,
               vol_ratio, rsi14, macd, macd_signal, macd_hist,
               trend_short, trend_medium, pct_from_ma20, pct_from_ma50"""

    # Thêm các fields mới nếu đã có trong DB
    new_fields = [
        "adx14", "plus_di14", "minus_di14", "di_spread", "trend_strength",
        "vol_ma20", "bb_width", "atr14", "atr_pct",
        "fvg_bull", "fvg_bear", "fvg_bull_size", "fvg_bear_size",
        "fvg_bull_age", "fvg_bear_age", "fvg_bull_fill", "fvg_bear_fill",
    ]
    extra = ", ".join(f for f in new_fields if f in existing)
    select_clause = base_select + (f", {extra}" if extra else "")

    tech = pd.read_sql(f"""
        SELECT {select_clause}
        FROM technical_indicators
        WHERE (symbol, date) IN (
            SELECT symbol, MAX(date) FROM technical_indicators GROUP BY symbol
        )
    """, conn)

    if tech.empty:
        log.warning("Technical indicators rỗng (chưa chạy technical_indicators.py)")
        return tech

    # RS vs market: (price_change_5d - median_5d) / std_5d
    median_5d = tech["price_change_5d"].median()
    std_5d    = tech["price_change_5d"].std()
    if std_5d and std_5d > 0:
        tech["rs_vs_market"] = (tech["price_change_5d"] - median_5d) / std_5d
    else:
        tech["rs_vs_market"] = 0.0

    log.info("Momentum/Technical loaded: %d symbols", len(tech))
    return tech


# ─── SCORING FUNCTIONS ──────────────────────────────────────────────────────

def percentile_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """
    Chuyển một series thành percentile rank (0–100).
    ascending=True:  giá trị cao → điểm cao (dùng cho ROE, growth...)
    ascending=False: giá trị thấp → điểm cao (dùng cho PE, D/E...)
    Xử lý NaN: NaN → 0 (không có data = điểm thấp nhất)
    Clip outliers tại 2 std trước khi rank (tránh HGM kéo toàn bộ thang)
    """
    valid = series.dropna()
    if len(valid) == 0:
        return pd.Series(0.0, index=series.index)

    # Clip outliers tại p2 – p98
    lo, hi = valid.quantile(0.02), valid.quantile(0.98)
    if lo == hi:
        return pd.Series(50.0, index=series.index).where(series.notna(), 0.0)

    clipped = series.clip(lower=lo, upper=hi)

    if ascending:
        rank = (clipped - lo) / (hi - lo) * 100
    else:
        rank = (hi - clipped) / (hi - lo) * 100

    # NaN → 0
    return rank.fillna(0.0).clip(0, 100)


def score_fundamentals(df: pd.DataFrame) -> pd.DataFrame:
    """Tính Fundamental Score từ df có các cột financials."""
    df = df.copy()

    df["roe_score"]            = percentile_rank(df["roe"])
    df["roa_score"]            = percentile_rank(df["roa"])
    df["revenue_growth_score"] = percentile_rank(df["revenue_growth"])
    df["net_margin_score"]     = percentile_rank(df["net_margin"])
    df["pe_score"]             = percentile_rank(df["pe"], ascending=False)       # thấp = tốt
    df["debt_equity_score"]    = percentile_rank(df["debt_equity"], ascending=False)  # thấp = tốt

    # PE = 0 hoặc âm thường là bất thường → gán điểm trung bình 50
    mask_pe_zero = (df["pe"].isna()) | (df["pe"] <= 0)
    df.loc[mask_pe_zero, "pe_score"] = 50.0

    df["fundamental_score"] = (
        df["roe_score"]            * FUNDAMENTAL_WEIGHTS["roe_score"] +
        df["roa_score"]            * FUNDAMENTAL_WEIGHTS["roa_score"] +
        df["revenue_growth_score"] * FUNDAMENTAL_WEIGHTS["revenue_growth_score"] +
        df["net_margin_score"]     * FUNDAMENTAL_WEIGHTS["net_margin_score"] +
        df["pe_score"]             * FUNDAMENTAL_WEIGHTS["pe_score"] +
        df["debt_equity_score"]    * FUNDAMENTAL_WEIGHTS["debt_equity_score"]
    )

    return df


def score_smart_money(df: pd.DataFrame, smart_df: pd.DataFrame) -> pd.DataFrame:
    """Merge và tính Smart Money Score (chỉ foreign flow — prop/insider không có data VCI)."""
    if smart_df.empty:
        for col in ["smart_money_score", "foreign_net_7d_score", "foreign_net_30d_score"]:
            df[col] = 50.0  # neutral khi không có data
        df["foreign_net_7d"]  = None
        df["foreign_net_30d"] = None
        return df

    df = df.merge(smart_df[["symbol", "foreign_net_7d", "foreign_net_30d"]],
                  on="symbol", how="left")

    df["foreign_net_7d_score"]  = percentile_rank(df.get("foreign_net_7d",  pd.Series()))
    df["foreign_net_30d_score"] = percentile_rank(df.get("foreign_net_30d", pd.Series()))

    df["smart_money_score"] = (
        df["foreign_net_7d_score"]  * SMART_MONEY_WEIGHTS["foreign_net_7d_score"] +
        df["foreign_net_30d_score"] * SMART_MONEY_WEIGHTS["foreign_net_30d_score"]
    )

    return df


def score_momentum_technical(df: pd.DataFrame, tech_df: pd.DataFrame) -> pd.DataFrame:
    """Merge và tính Momentum + Technical Score.

    v2 changes (backtest-driven):
    - Momentum: penalize extreme momentum (>15% 20D) — mean reversion trên VNSTOCK
    - RSI: tăng điểm mạnh hơn cho oversold zone (< 35), curve theo backtest buckets
    - MACD: LOẠI BỎ — edge -0.67% fwd20D, bị thay bằng ADX score
    - ADX: thêm mới — chỉ bucket >50 mới thực sự có edge (+0.62%)
    - Combo bonus: Trend+ADX>30+RSI<70 — edge +1.54% fwd20D
    """
    if tech_df.empty:
        for col in ["momentum_score", "technical_score",
                    "price_5d_score", "price_20d_score", "vol_surge_score",
                    "rs_vs_market_score", "rsi_score", "macd_score", "trend_score",
                    "adx_score"]:
            df[col] = 50.0  # neutral
        for col in ["price_change_1d", "price_change_5d", "price_change_20d", "vol_ratio",
                    "rsi14", "macd_hist", "trend_short"]:
            df[col] = None
        return df

    # Dùng tất cả fields available trong tech_df (backward-compatible)
    passthrough_cols = [
        "symbol", "price_change_1d", "price_change_5d", "price_change_20d",
        "vol_ratio", "vol_ma20",
        "rs_vs_market", "rsi14", "macd", "macd_signal", "macd_hist",
        "trend_short", "trend_medium", "pct_from_ma20", "pct_from_ma50",
        # NEW technical fields
        "adx14", "plus_di14", "minus_di14", "di_spread", "trend_strength",
        "bb_width", "atr14", "atr_pct",
        "fvg_bull", "fvg_bear", "fvg_bull_size", "fvg_bear_size",
        "fvg_bull_age", "fvg_bear_age", "fvg_bull_fill", "fvg_bear_fill",
    ]
    merge_cols = [c for c in passthrough_cols if c in tech_df.columns]
    df = df.merge(tech_df[merge_cols], on="symbol", how="left")

    # ── MOMENTUM SUB-SCORES ──────────────────────────────────────────────────
    # price_5d: percentile rank bình thường
    df["price_5d_score"] = percentile_rank(df["price_change_5d"])

    # price_20d: v2 — penalize extreme momentum (>15%) vì mean reversion VNSTOCK
    # Backtest: mom >10% → edge -0.88%; mom <-20% → bounce +2.73% (short-term)
    p20d = df["price_change_20d"].fillna(0)
    p20d_base = percentile_rank(df["price_change_20d"])
    # Capping: cổ phiếu tăng >15% trong 20D bị cap điểm tối đa ở 60 (không thưởng thêm)
    # Cổ phiếu tăng >25% bị penalize xuống 40 (mean reversion risk cao)
    p20d_score = p20d_base.copy()
    p20d_score = np.where(p20d > 25, p20d_base.clip(0, 40),   # extreme momentum → penalty
                 np.where(p20d > 15, p20d_base.clip(0, 60),   # strong momentum → cap
                 p20d_score))
    df["price_20d_score"] = pd.Series(p20d_score, index=df.index).clip(0, 100)

    df["vol_surge_score"]    = percentile_rank(df["vol_ratio"])
    df["rs_vs_market_score"] = percentile_rank(df.get("rs_vs_market", pd.Series()))

    df["momentum_score"] = (
        df["price_5d_score"]     * MOMENTUM_WEIGHTS["price_5d_score"] +
        df["price_20d_score"]    * MOMENTUM_WEIGHTS["price_20d_score"] +
        df["vol_surge_score"]    * MOMENTUM_WEIGHTS["vol_surge_score"] +
        df["rs_vs_market_score"] * MOMENTUM_WEIGHTS["rs_vs_market_score"]
    )

    # ── TECHNICAL SUB-SCORES ─────────────────────────────────────────────────

    # RSI SCORE v2 — calibrated theo backtest buckets:
    # RSI 0-25:  +2.26% fwd20D → điểm 90–100 (strong buy signal)
    # RSI 25-35: +0.71% fwd20D → điểm 75–90
    # RSI 35-45: -0.18% fwd20D → điểm 55–70
    # RSI 45-65: neutral       → điểm 40–55
    # RSI 65-75: +0.11% fwd20D → điểm 30–40 (overbought, nhẹ thôi)
    # RSI 75+:   -0.53% fwd20D → điểm 10–30 (overbought penalty)
    rsi = df["rsi14"].fillna(50)
    rsi_score = np.where(rsi < 25,  90 + (25 - rsi) * 0.4,          # 0–25:  90–100
                np.where(rsi < 35,  75 + (35 - rsi) * 1.5,          # 25–35: 75–90
                np.where(rsi < 45,  55 + (45 - rsi) * 2.0,          # 35–45: 55–75
                np.where(rsi < 65,  40 + (65 - rsi) * 0.75,         # 45–65: 40–55
                np.where(rsi < 75,  30 - (rsi - 65) * 1.0,          # 65–75: 20–30
                         10.0)))))                                    # 75+:   10
    df["rsi_score"] = pd.Series(rsi_score, index=df.index).clip(0, 100)

    # MACD SCORE: giữ lại field để backward-compat với DB/export nhưng weight=0
    # Không dùng trong technical_score nữa (edge -0.67%)
    macd_hist = df.get("macd_hist", pd.Series(0.0, index=df.index)).fillna(0)
    df["macd_score"] = percentile_rank(macd_hist)  # vẫn tính nhưng không dùng trong formula

    # TREND SCORE: P>MA20>MA50 — edge +0.77% (p=0.0000)
    # v2: tăng spread giữa trend=1 và trend=-1 để phân biệt rõ hơn
    trend = df.get("trend_short", pd.Series(0, index=df.index)).fillna(0)
    df["trend_score"] = trend.map({1: 85.0, 0: 50.0, -1: 15.0}).fillna(50.0)

    # ADX SCORE v2 (NEW — thay MACD):
    # Backtest: ADX >50 edge +0.62% (p=0.021); ADX <20 no edge; ADX linear IC ≈ 0
    # → Dùng bucket scoring thay vì linear percentile rank
    # ADX 0-15:   weak trend    → 30
    # ADX 15-25:  developing    → 45
    # ADX 25-35:  moderate      → 60
    # ADX 35-50:  strong        → 70
    # ADX >50:    very strong   → 90  ← có ý nghĩa thống kê p=0.021
    adx = df.get("adx14", pd.Series(np.nan, index=df.index)).fillna(20)
    adx_score = np.where(adx > 50, 90.0,
                np.where(adx > 35, 70.0,
                np.where(adx > 25, 60.0,
                np.where(adx > 15, 45.0,
                         30.0))))
    df["adx_score"] = pd.Series(adx_score, index=df.index)

    # TECHNICAL SCORE (không có MACD)
    df["technical_score"] = (
        df["rsi_score"]   * TECHNICAL_WEIGHTS["rsi_score"] +
        df["trend_score"] * TECHNICAL_WEIGHTS["trend_score"] +
        df["adx_score"]   * TECHNICAL_WEIGHTS["adx_score"]
    )

    # ── COMBO BONUS v3 ───────────────────────────────────────────────────────
    # Backtest: Trend+ADX>30+RSI<70 → edge +1.54% fwd20D (p=0.0000)
    # Backtest: Trend+ADX>25+RSI<35 → edge +9.79% fwd10D, win 72.7% (n=11)
    # v3: tăng bonus từ +5 lên +8 để reflect edge thực tế mạnh hơn

    # Combo 1: Trend + ADX>30 + RSI không overbought
    combo_mask = (trend == 1) & (adx > 30) & (rsi < 70)
    df.loc[combo_mask, "technical_score"] = (
        df.loc[combo_mask, "technical_score"] + 8.0
    ).clip(0, 100)

    # Combo 2 (Super Combo): Trend + ADX>25 + RSI oversold (<35)
    # Edge: win 72.7% fwd20D, avg +9.79% fwd10D — setup tiềm năng nhất
    super_combo_mask = (trend == 1) & (adx > 25) & (rsi < 35)
    df.loc[super_combo_mask, "technical_score"] = (
        df.loc[super_combo_mask, "technical_score"] + 15.0
    ).clip(0, 100)

    # ── MEAN REVERSION SCORE (v3 NEW) ────────────────────────────────────────
    # Backtest: crash -15% (20D) → bounce +1.13% avg 10D, win 49% (+8% vs bench)
    # Backtest: crash -20% (20D) → bounce +1.79% avg 10D, win 49% (+8% vs bench)
    # Lưu ý: bounce là SHORT TERM (5-10D), không phải trend đổi chiều
    # → Mean Reversion Score dùng cho SHORT TERM signal, không cho composite dài hạn
    p20d_val = df["price_change_20d"].fillna(0)
    rsi_vals  = df["rsi14"].fillna(50)

    # MR Score: cao khi giá giảm mạnh + RSI oversold → bounce potential
    # Thấp khi giá giảm vừa (không đủ oversold để bounce)
    mr_score = np.where(
        (p20d_val < -20) & (rsi_vals < 35),  90.0,  # Crash + RSI oversold: bounce mạnh
        np.where(
        (p20d_val < -15) & (rsi_vals < 40),  75.0,  # Crash + RSI low: bounce moderate
        np.where(
        (p20d_val < -10) & (rsi_vals < 45),  60.0,  # Pullback + oversold: watch
        np.where(
        p20d_val > 15,                         20.0,  # Overbought momentum: mean rev risk
        np.where(
        p20d_val > 25,                         10.0,  # Extreme overbought: high risk
                                               50.0   # Neutral
    )))))
    df["mean_reversion_score"] = pd.Series(mr_score, index=df.index).clip(0, 100)

    return df


def calc_composite(df: pd.DataFrame, symbols_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Tính composite score, rank, tier.
    Áp dụng penalty cho cổ phiếu trong diện cảnh báo/kiểm soát.
    """
    df = df.copy()

    # Base composite score (chưa có penalty)
    df["composite_score_raw"] = (
        df["fundamental_score"] * WEIGHTS["fundamental"] +
        df["smart_money_score"] * WEIGHTS["smart_money"] +
        df["momentum_score"]    * WEIGHTS["momentum"] +
        df["technical_score"]   * WEIGHTS["technical"]
    ).round(2)
    
    # Merge warning_status từ symbols_df
    df["warning_status"] = "normal"
    if symbols_df is not None and not symbols_df.empty and "warning_status" in symbols_df.columns:
        warning_map = dict(zip(symbols_df["symbol"], symbols_df["warning_status"]))
        df["warning_status"] = df["symbol"].map(warning_map).fillna("normal")
    
    # Áp dụng penalty cho cổ phiếu cảnh báo
    def apply_penalty(row):
        raw_score = row["composite_score_raw"]
        status = row["warning_status"]
        penalty = WARNING_PENALTIES.get(status, 0)
        
        if penalty > 0:
            # Trừ % điểm theo penalty
            penalized = raw_score * (1 - penalty)
            return round(penalized, 2)
        return raw_score
    
    df["composite_score"] = df.apply(apply_penalty, axis=1)
    
    # Log warning stocks
    warning_stocks = df[df["warning_status"] != "normal"]
    if len(warning_stocks) > 0:
        log.info("Cổ phiếu có penalty:")
        for status in ["control", "warning", "restriction", "delisting"]:
            subset = warning_stocks[warning_stocks["warning_status"] == status]
            if len(subset) > 0:
                penalty_pct = WARNING_PENALTIES.get(status, 0) * 100
                symbols_list = subset["symbol"].head(10).tolist()
                log.info("  %s (-%d%%): %s%s", 
                        status.upper(), int(penalty_pct),
                        ", ".join(symbols_list),
                        "..." if len(subset) > 10 else "")

    # ── REGIME ADJUSTED SCORE (v3) ──────────────────────────────────────────
    # Backtest key finding: composite score không context-aware theo regime
    # DGC score=69 trong BEAR = kém hơn score=55 trong BULL về forward return
    # regime_adj_score = composite_score × regime_multiplier
    # Dùng cho sorting/ranking trong BEAR market để phân biệt tốt hơn
    # (composite_score giữ nguyên cho backward compat)
    # Lấy bull_weight từ ICT nếu có, nếu không thì default 0.5
    # Note: scoring_engine không có ICT data → dùng proxy từ market breadth
    # Tạm thời: regime_adj_score = composite (ICT sẽ override khi export)
    df["regime_adj_score"] = df["composite_score_raw"].round(2)

    # Rank (1 = best)
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df["rank_total"] = df.index + 1
    n = len(df)
    df["rank_pct"] = ((n - df["rank_total"]) / (n - 1) * 100).round(1) if n > 1 else 100.0

    # Tier A/B/C/D/F
    def assign_tier(score):
        if score >= 70:   return "A"
        elif score >= 55: return "B"
        elif score >= 40: return "C"
        elif score >= 25: return "D"
        else:             return "F"

    df["tier"] = df["composite_score"].apply(assign_tier)

    # Data completeness (tỷ lệ chỉ số có giá trị)
    key_cols = ["roe", "roa", "pe", "revenue_growth", "net_margin",
                "debt_equity", "price_change_5d", "rsi14"]
    key_cols = [c for c in key_cols if c in df.columns]
    df["data_completeness"] = df[key_cols].notna().mean(axis=1).round(2)

    return df


# ─── SECTOR AGGREGATION ─────────────────────────────────────────────────────

def calc_sector_scores(scores_df: pd.DataFrame, symbols_df: pd.DataFrame, conn) -> pd.DataFrame:
    """
    Tổng hợp điểm số theo ngành từ stock_scores + symbols data.
    Tạo table sector_scores.
    """
    if symbols_df.empty:
        log.warning("Không có symbols data để tính sector scores")
        return pd.DataFrame()

    # Merge scores với industry
    merged = scores_df.merge(
        symbols_df[["symbol", "industry_name", "exchange"]],
        on="symbol", how="left"
    )

    sector = merged.groupby("industry_name").agg(
        symbol_count         = ("symbol", "count"),
        avg_composite        = ("composite_score", "mean"),
        avg_fundamental      = ("fundamental_score", "mean"),
        avg_smart_money      = ("smart_money_score", "mean"),
        avg_momentum         = ("momentum_score", "mean"),
        avg_technical        = ("technical_score", "mean"),
        avg_roe              = ("roe", "mean"),
        avg_pe               = ("pe", "mean"),
        avg_revenue_growth   = ("revenue_growth", "mean"),
        tier_a_count         = ("tier", lambda x: (x == "A").sum()),
        tier_b_count         = ("tier", lambda x: (x == "B").sum()),
    ).reset_index()

    # Foreign flow per sector
    if "foreign_net_7d" in merged.columns:
        sector_flow = merged.groupby("industry_name").agg(
            total_foreign_7d  = ("foreign_net_7d",  "sum"),
            total_foreign_30d = ("foreign_net_30d", "sum"),
        ).reset_index()
        sector = sector.merge(sector_flow, on="industry_name", how="left")
        sector["foreign_net_7d_rank"] = sector["total_foreign_7d"].rank(ascending=False).fillna(999).astype(int)
    else:
        sector["total_foreign_7d"]    = None
        sector["total_foreign_30d"]   = None
        sector["foreign_net_7d_rank"] = None

    sector["scored_at"] = datetime.now().isoformat()

    # Round floats
    float_cols = [c for c in sector.columns if sector[c].dtype == float]
    sector[float_cols] = sector[float_cols].round(2)

    # Save to DB
    conn.execute("DROP TABLE IF EXISTS sector_scores")
    conn.commit()

    sector.to_sql("sector_scores", conn, if_exists="replace", index=False)
    conn.commit()
    log.info("Sector scores saved: %d sectors", len(sector))

    return sector


# ─── SAVE SCORES ────────────────────────────────────────────────────────────

OUTPUT_COLS = [
    "symbol",
    # Component scores
    "fundamental_score", "smart_money_score", "momentum_score",
    "technical_score", "composite_score",
    # Sub-scores
    "roe_score", "roa_score", "revenue_growth_score", "net_margin_score",
    "pe_score", "debt_equity_score",
    "foreign_net_7d_score", "foreign_net_30d_score",
    "price_5d_score", "price_20d_score", "vol_surge_score", "rs_vs_market_score",
    "rsi_score", "macd_score", "adx_score", "trend_score",
    # Fundamental raw values
    "roe", "roa", "pe", "revenue_growth", "net_margin", "debt_equity",
    # Price momentum
    "price_change_1d", "price_change_5d", "price_change_20d",
    # Technical — core
    "vol_ratio", "vol_ma20", "rsi14", "macd_hist", "trend_short",
    "pct_from_ma20", "pct_from_ma50",
    # Technical — NEW: ADX + trend strength
    "adx14", "plus_di14", "minus_di14", "di_spread", "trend_strength",
    # Technical — NEW: volatility
    "bb_width", "atr14", "atr_pct",
    # Technical — NEW: FVG signals
    "fvg_bull", "fvg_bear",
    "fvg_bull_size", "fvg_bear_size",
    "fvg_bull_age", "fvg_bear_age",
    "fvg_bull_fill", "fvg_bear_fill",
    # Smart money raw values
    "foreign_net_7d", "foreign_net_30d",
    # Ranking
    "rank_total", "rank_pct", "tier",
    "data_completeness",
    # v3 NEW scores
    "mean_reversion_score",   # crash bounce edge — short-term signal
    "regime_adj_score",       # composite × regime_multiplier (ICT-adjusted)
]


def _scalar(val):
    """Ép kiểu về scalar – phòng khi val là Series/ndarray do merge duplicate columns."""
    if isinstance(val, pd.Series):
        return val.iloc[0] if len(val) > 0 else None
    if isinstance(val, np.ndarray):
        return val.flat[0] if val.size > 0 else None
    return val


def save_scores(conn, df: pd.DataFrame):
    now = datetime.now().isoformat()
    df  = df.copy()
    df["scored_at"] = now

    rows = []
    for _, row in df.iterrows():
        record = {}
        for col in OUTPUT_COLS:
            val = _scalar(row.get(col))
            if col in ("trend_short", "rank_total"):
                try:
                    record[col] = int(val) if val is not None and val == val else None
                except (TypeError, ValueError):
                    record[col] = None
            elif isinstance(val, (float, np.floating)):
                record[col] = None if (val != val) else round(float(val), 4)
            else:
                record[col] = val
        record["scored_at"] = now
        rows.append(record)

    # Upsert via temp DataFrame
    out_df = pd.DataFrame(rows)
    # Final safety pass: flatten any remaining non-scalar cells
    for col in out_df.columns:
        if out_df[col].dtype == object:
            out_df[col] = out_df[col].apply(
                lambda x: x.iloc[0] if isinstance(x, pd.Series) and len(x) > 0
                else (x.flat[0] if isinstance(x, np.ndarray) and x.size > 0 else x)
            )
    out_df.to_sql("stock_scores", conn, if_exists="replace", index=False)
    conn.commit()
    log.info("Saved %d rows to stock_scores", len(out_df))


# ─── SYMBOLS LOADER ─────────────────────────────────────────────────────────

def load_symbols(conn) -> pd.DataFrame:
    """Load symbols table nếu có, hoặc từ JSON export."""
    try:
        # Kiểm tra cột tồn tại trước khi query (warning_status có thể chưa có)
        cursor = conn.execute("PRAGMA table_info(symbols)")
        cols_in_db = {row[1] for row in cursor.fetchall()}
        if cols_in_db:
            select_cols = ["symbol", "industry_name", "exchange"]
            if "warning_status" in cols_in_db:
                select_cols.append("warning_status")
            df = pd.read_sql(f"SELECT {', '.join(select_cols)} FROM symbols", conn)
            if not df.empty:
                if "warning_status" not in df.columns:
                    df["warning_status"] = "normal"
                else:
                    df["warning_status"] = df["warning_status"].fillna("normal")
                log.info("Symbols loaded from DB: %d", len(df))
                return df
    except Exception as e:
        log.warning("load_symbols DB error: %s", e)

    # Fallback: đọc từ JSON export (không có warning_status)
    import json
    json_path = os.path.join(os.path.dirname(DB_PATH), "exports", "symbols.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
        items = data.get("data", data) if isinstance(data, dict) else data
        df = pd.DataFrame(items)
        if "symbol" in df.columns:
            rename = {}
            if "industry_name" not in df.columns and "industryName" in df.columns:
                rename["industryName"] = "industry_name"
            if rename:
                df = df.rename(columns=rename)
            # Add default warning_status
            if "warning_status" not in df.columns:
                df["warning_status"] = "normal"
            log.info("Symbols loaded from JSON: %d", len(df))
            cols = ["symbol", "industry_name", "exchange", "warning_status"]
            cols = [c for c in cols if c in df.columns]
            return df[cols]

    log.warning("Không tìm thấy symbols data")
    return pd.DataFrame()


# ─── MAIN ───────────────────────────────────────────────────────────────────

def run():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    conn = create_connection()
    init_db(conn)

    log.info("=== Loading data ===")
    fundamental_df = load_fundamentals(conn)
    smart_money_df = load_smart_money(conn)
    momentum_df    = load_momentum(conn)
    symbols_df     = load_symbols(conn)

    if fundamental_df.empty:
        log.error("Không có fundamental data. Chạy financials.py trước.")
        conn.close()
        return

    log.info("=== Scoring ===")
    df = fundamental_df.copy()

    # A. Fundamental Score
    df = score_fundamentals(df)
    log.info("  Fundamental: done (%d symbols)", len(df))

    # B. Smart Money Score
    df = score_smart_money(df, smart_money_df)
    log.info("  Smart Money: done")

    # C. Momentum + D. Technical Score
    df = score_momentum_technical(df, momentum_df)
    log.info("  Momentum + Technical: done")

    # Composite (với warning penalty)
    df = calc_composite(df, symbols_df)
    log.info("  Composite: done")

    # Save
    log.info("=== Saving ===")
    save_scores(conn, df)

    # Sector scores
    if not symbols_df.empty:
        calc_sector_scores(df, symbols_df, conn)

    # Summary stats
    tiers = df["tier"].value_counts().to_dict()
    log.info("Tier distribution: %s", tiers)
    
    # Log warning stocks in top rankings
    warning_in_top = df[df["warning_status"] != "normal"].head(20)
    if len(warning_in_top) > 0:
        log.info("⚠️  Cổ phiếu cảnh báo trong top 20:")
        for _, r in warning_in_top.iterrows():
            log.info("  #%d %s (%s) — Score: %.1f (raw: %.1f)",
                     r["rank_total"], r["symbol"], r["warning_status"],
                     r["composite_score"], r.get("composite_score_raw", r["composite_score"]))
    
    log.info("Top 10 composite:")
    top10 = df[["symbol", "composite_score", "tier", "rank_total",
                "roe", "pe", "revenue_growth", "warning_status"]].head(10)
    for _, r in top10.iterrows():
        warning_flag = f" ⚠️{r['warning_status']}" if r.get("warning_status", "normal") != "normal" else ""
        log.info("  #%d %s%s — Score: %.1f (%s) | ROE: %s | PE: %s | RevGrowth: %s",
                 r["rank_total"], r["symbol"], warning_flag, r["composite_score"], r["tier"],
                 f"{r['roe']*100:.1f}%" if r["roe"] else "N/A",
                 f"{r['pe']:.1f}x" if r["pe"] else "N/A",
                 f"{r['revenue_growth']*100:.1f}%" if r["revenue_growth"] else "N/A")

    conn.close()
    log.info("✅ Scoring done — %d symbols scored", len(df))


if __name__ == "__main__":
    run()
