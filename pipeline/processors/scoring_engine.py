"""
scoring.py — Composite Scoring Engine cho VN Stock Scanner

Tính điểm tổng hợp (0–100) cho từng cổ phiếu dựa trên 4 trụ cột:

  A. Fundamental Score  (35%): PE, ROE, ROA, revenue growth, net margin, D/E
  B. Smart Money Score  (30%): Net foreign flow, prop trading, insider deals
  C. Momentum Score     (20%): Price momentum 5d/20d, volume surge, RS vs market
  D. Technical Score    (15%): RSI, MACD signal, Bollinger position, trend

Scoring method: percentile rank trong universe (loại bỏ outliers)
  → Mỗi chỉ số được rank từ 0–100 theo phân phối thực tế của thị trường
  → Tránh bị lệch vì outliers (HGM ROE=116% sẽ không kéo toàn bộ thang điểm)

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
from datetime import datetime

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")

# Trọng số các trụ cột
WEIGHTS = {
    "fundamental": 0.35,
    "smart_money": 0.30,
    "momentum":    0.20,
    "technical":   0.15,
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
    "foreign_net_7d_score":  0.40,
    "foreign_net_30d_score": 0.30,
    "prop_net_7d_score":     0.30,
}

MOMENTUM_WEIGHTS = {
    "price_5d_score":    0.30,
    "price_20d_score":   0.35,
    "vol_surge_score":   0.20,
    "rs_vs_market_score": 0.15,
}

TECHNICAL_WEIGHTS = {
    "rsi_score":     0.35,
    "macd_score":    0.35,
    "trend_score":   0.30,
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

            -- Component Scores (0–100)
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
            prop_net_7d_score     REAL,

            price_5d_score      REAL,
            price_20d_score     REAL,
            vol_surge_score     REAL,
            rs_vs_market_score  REAL,

            rsi_score           REAL,
            macd_score          REAL,
            trend_score         REAL,

            -- Raw values (for display/debug)
            roe                 REAL,
            roa                 REAL,
            pe                  REAL,
            revenue_growth      REAL,
            net_margin          REAL,
            debt_equity         REAL,
            price_change_5d     REAL,
            price_change_20d    REAL,
            vol_ratio           REAL,
            rsi14               REAL,
            macd_hist           REAL,
            trend_short         INTEGER,

            -- Ranking
            rank_total          INTEGER,
            rank_pct            REAL,    -- percentile (100 = best)
            tier                TEXT,    -- A/B/C/D/F

            -- Metadata
            data_completeness   REAL,    -- % chỉ số có data (0–1)
            scored_at           TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scores_composite ON stock_scores(composite_score DESC);
        CREATE INDEX IF NOT EXISTS idx_scores_tier      ON stock_scores(tier);
        CREATE INDEX IF NOT EXISTS idx_scores_fundamental ON stock_scores(fundamental_score DESC);
        CREATE INDEX IF NOT EXISTS idx_scores_smart_money ON stock_scores(smart_money_score DESC);
    """)
    conn.commit()
    log.info("stock_scores table OK")


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
    Tổng hợp dòng tiền thông minh.
    Nếu foreign_trading rỗng (chưa có data), trả về DataFrame rỗng.
    """
    # Foreign flow 7 ngày
    foreign_7d = pd.read_sql("""
        SELECT symbol,
               SUM(net_value) AS foreign_net_7d,
               SUM(buy_value) AS foreign_buy_7d,
               SUM(sell_value) AS foreign_sell_7d
        FROM foreign_trading
        WHERE date >= date('now', '-7 days')
        GROUP BY symbol
    """, conn)

    # Foreign flow 30 ngày
    foreign_30d = pd.read_sql("""
        SELECT symbol, SUM(net_value) AS foreign_net_30d
        FROM foreign_trading
        WHERE date >= date('now', '-30 days')
        GROUP BY symbol
    """, conn)

    # Prop trading 7 ngày
    prop_7d = pd.read_sql("""
        SELECT symbol, SUM(net_value) AS prop_net_7d
        FROM prop_trading
        WHERE date >= date('now', '-7 days')
        GROUP BY symbol
    """, conn)

    if foreign_7d.empty and foreign_30d.empty and prop_7d.empty:
        log.warning("Smart money data rỗng (chưa chạy foreign_trading.py)")
        return pd.DataFrame(columns=["symbol", "foreign_net_7d", "foreign_net_30d", "prop_net_7d"])

    result = foreign_7d.merge(foreign_30d, on="symbol", how="outer")
    result = result.merge(prop_7d, on="symbol", how="outer")
    log.info("Smart money loaded: %d symbols", len(result))
    return result


def load_momentum(conn) -> pd.DataFrame:
    """Lấy momentum từ technical_indicators (latest) + tính RS vs market."""
    tech = pd.read_sql("""
        SELECT symbol, date, close, price_change_5d, price_change_20d,
               vol_ratio, rsi14, macd, macd_signal, macd_hist,
               trend_short, trend_medium, pct_from_ma20, pct_from_ma50
        FROM technical_indicators
        WHERE (symbol, date) IN (
            SELECT symbol, MAX(date) FROM technical_indicators GROUP BY symbol
        )
    """, conn)

    if tech.empty:
        log.warning("Technical indicators rỗng (chưa chạy technical_calc.py)")
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
    """Merge và tính Smart Money Score."""
    if smart_df.empty:
        for col in ["smart_money_score", "foreign_net_7d_score",
                    "foreign_net_30d_score", "prop_net_7d_score"]:
            df[col] = 50.0  # neutral khi không có data
        df["foreign_net_7d"]  = None
        df["foreign_net_30d"] = None
        df["prop_net_7d"]     = None
        return df

    df = df.merge(smart_df[["symbol", "foreign_net_7d", "foreign_net_30d", "prop_net_7d"]],
                  on="symbol", how="left")

    df["foreign_net_7d_score"]  = percentile_rank(df.get("foreign_net_7d",  pd.Series()))
    df["foreign_net_30d_score"] = percentile_rank(df.get("foreign_net_30d", pd.Series()))
    df["prop_net_7d_score"]     = percentile_rank(df.get("prop_net_7d",     pd.Series()))

    df["smart_money_score"] = (
        df["foreign_net_7d_score"]  * SMART_MONEY_WEIGHTS["foreign_net_7d_score"] +
        df["foreign_net_30d_score"] * SMART_MONEY_WEIGHTS["foreign_net_30d_score"] +
        df["prop_net_7d_score"]     * SMART_MONEY_WEIGHTS["prop_net_7d_score"]
    )

    return df


def score_momentum_technical(df: pd.DataFrame, tech_df: pd.DataFrame) -> pd.DataFrame:
    """Merge và tính Momentum + Technical Score."""
    if tech_df.empty:
        for col in ["momentum_score", "technical_score",
                    "price_5d_score", "price_20d_score", "vol_surge_score",
                    "rs_vs_market_score", "rsi_score", "macd_score", "trend_score"]:
            df[col] = 50.0  # neutral
        for col in ["price_change_5d", "price_change_20d", "vol_ratio",
                    "rsi14", "macd_hist", "trend_short"]:
            df[col] = None
        return df

    merge_cols = ["symbol", "price_change_5d", "price_change_20d", "vol_ratio",
                  "rs_vs_market", "rsi14", "macd", "macd_signal", "macd_hist",
                  "trend_short", "trend_medium"]
    merge_cols = [c for c in merge_cols if c in tech_df.columns]
    df = df.merge(tech_df[merge_cols], on="symbol", how="left")

    # Momentum sub-scores
    df["price_5d_score"]     = percentile_rank(df["price_change_5d"])
    df["price_20d_score"]    = percentile_rank(df["price_change_20d"])
    df["vol_surge_score"]    = percentile_rank(df["vol_ratio"])
    df["rs_vs_market_score"] = percentile_rank(df.get("rs_vs_market", pd.Series()))

    df["momentum_score"] = (
        df["price_5d_score"]     * MOMENTUM_WEIGHTS["price_5d_score"] +
        df["price_20d_score"]    * MOMENTUM_WEIGHTS["price_20d_score"] +
        df["vol_surge_score"]    * MOMENTUM_WEIGHTS["vol_surge_score"] +
        df["rs_vs_market_score"] * MOMENTUM_WEIGHTS["rs_vs_market_score"]
    )

    # Technical sub-scores
    # RSI: optimal range 40–65 (không overbought/oversold)
    rsi = df["rsi14"].fillna(50)
    rsi_score = pd.Series(100.0, index=df.index)
    # RSI < 30: oversold (rủi ro tiếp tục giảm) → 20–50 points
    rsi_score = np.where(rsi < 30, 20 + rsi * 1.0,
                # RSI 30-40: recovering → 50-70
                np.where(rsi < 40, 50 + (rsi - 30) * 2.0,
                # RSI 40-65: healthy zone → 70-100
                np.where(rsi < 65, 70 + (rsi - 40) * 1.2,
                # RSI 65-80: caution → 70-40
                np.where(rsi < 80, 70 - (rsi - 65) * 2.0,
                # RSI >= 80: overbought → 0-40
                20.0))))
    df["rsi_score"] = pd.Series(rsi_score, index=df.index).clip(0, 100)

    # MACD: histogram dương và tăng = tốt
    macd_hist = df.get("macd_hist", pd.Series(0.0, index=df.index)).fillna(0)
    df["macd_score"] = percentile_rank(macd_hist)

    # Trend: -1/0/1 → 10/50/90
    trend = df.get("trend_short", pd.Series(0, index=df.index)).fillna(0)
    df["trend_score"] = trend.map({1: 80.0, 0: 50.0, -1: 20.0}).fillna(50.0)

    df["technical_score"] = (
        df["rsi_score"]   * TECHNICAL_WEIGHTS["rsi_score"] +
        df["macd_score"]  * TECHNICAL_WEIGHTS["macd_score"] +
        df["trend_score"] * TECHNICAL_WEIGHTS["trend_score"]
    )

    return df


def calc_composite(df: pd.DataFrame) -> pd.DataFrame:
    """Tính composite score, rank, tier."""
    df = df.copy()

    df["composite_score"] = (
        df["fundamental_score"] * WEIGHTS["fundamental"] +
        df["smart_money_score"] * WEIGHTS["smart_money"] +
        df["momentum_score"]    * WEIGHTS["momentum"] +
        df["technical_score"]   * WEIGHTS["technical"]
    ).round(2)

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
    "fundamental_score", "smart_money_score", "momentum_score",
    "technical_score", "composite_score",
    "roe_score", "roa_score", "revenue_growth_score", "net_margin_score",
    "pe_score", "debt_equity_score",
    "foreign_net_7d_score", "foreign_net_30d_score", "prop_net_7d_score",
    "price_5d_score", "price_20d_score", "vol_surge_score", "rs_vs_market_score",
    "rsi_score", "macd_score", "trend_score",
    "roe", "roa", "pe", "revenue_growth", "net_margin", "debt_equity",
    "price_change_5d", "price_change_20d", "vol_ratio",
    "rsi14", "macd_hist", "trend_short",
    "rank_total", "rank_pct", "tier",
    "data_completeness",
]


def save_scores(conn, df: pd.DataFrame):
    now = datetime.now().isoformat()
    df  = df.copy()
    df["scored_at"] = now

    rows = []
    for _, row in df.iterrows():
        record = {}
        for col in OUTPUT_COLS:
            val = row.get(col)
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
    out_df.to_sql("stock_scores", conn, if_exists="replace", index=False)
    conn.commit()
    log.info("Saved %d rows to stock_scores", len(out_df))


# ─── SYMBOLS LOADER ─────────────────────────────────────────────────────────

def load_symbols(conn) -> pd.DataFrame:
    """Load symbols table nếu có, hoặc từ JSON export."""
    try:
        df = pd.read_sql("SELECT symbol, industry_name, exchange FROM symbols", conn)
        if not df.empty:
            return df
    except Exception:
        pass

    # Fallback: đọc từ JSON export
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
            log.info("Symbols loaded from JSON: %d", len(df))
            return df[["symbol", "industry_name", "exchange"]] if "industry_name" in df.columns else df[["symbol"]]

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

    # Composite
    df = calc_composite(df)
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
    log.info("Top 10 composite:")
    top10 = df[["symbol", "composite_score", "tier", "rank_total",
                "roe", "pe", "revenue_growth"]].head(10)
    for _, r in top10.iterrows():
        log.info("  #%d %s — Score: %.1f (%s) | ROE: %s | PE: %s | RevGrowth: %s",
                 r["rank_total"], r["symbol"], r["composite_score"], r["tier"],
                 f"{r['roe']:.1f}%" if r["roe"] else "N/A",
                 f"{r['pe']:.1f}x" if r["pe"] else "N/A",
                 f"{r['revenue_growth']:.1f}%" if r["revenue_growth"] else "N/A")

    conn.close()
    log.info("✅ Scoring done — %d symbols scored", len(df))


if __name__ == "__main__":
    run()
