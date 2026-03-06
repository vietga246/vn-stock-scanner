"""
sector_analysis.py — Sector Rotation & Money Flow Analysis

Phân tích dòng tiền theo ngành và tạo dữ liệu heatmap cho frontend.

Output:
  - data/exports/sectors.json
    {
      "generated_at": "...",
      "sectors": [
        {
          "name": "Ngân hàng",
          "symbol_count": 28,
          "avg_composite_score": 62.4,
          "avg_pe": 11.2,
          "avg_roe": 18.5,
          "avg_revenue_growth": 22.1,
          "foreign_net_7d": 1250.5,      -- tỷ đồng
          "foreign_net_30d": 4820.3,
          "tier_a_pct": 35.7,            -- % cổ phiếu tier A trong ngành
          "momentum_rank": 1,            -- rank ngành theo momentum
          "money_flow_rank": 2,          -- rank theo dòng tiền ngoại
          "top_stocks": ["VCB","BID","CTG"]  -- top 3 theo composite score
        }
      ],
      "rotation_signal": {
        "accumulating": ["Ngân hàng", "Bất động sản"],  -- dòng tiền đang vào
        "distributing": ["Thép", "Phân bón"],            -- dòng tiền đang ra
        "hot_sectors": ["Công nghệ", "Dược phẩm"]        -- momentum cao nhất
      }
    }

Chạy sau scoring.py trong GitHub Actions.
"""

import sqlite3
import pandas as pd
import numpy as np
import json
import os
import logging
import sys
from datetime import datetime

# ─── CONFIG ─────────────────────────────────────────────────────────────────

DB_PATH     = os.getenv("DB_PATH", "data/db/stock.db")
EXPORT_DIR  = os.getenv("EXPORT_DIR", "data/exports")
OUT_PATH    = os.path.join(EXPORT_DIR, "sectors.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def safe_float(v, decimals=2):
    """Convert to float, replacing NaN/Infinity with None for valid JSON."""
    if v is None:
        return None
    try:
        # Handle pandas NA
        import pandas as pd
        if pd.isna(v):
            return None
    except (ImportError, TypeError):
        pass
    try:
        # Handle numpy types
        import numpy as np
        if isinstance(v, (np.floating, np.integer)):
            if np.isnan(v) or np.isinf(v):
                return None
            v = float(v)
    except (ImportError, TypeError):
        pass
    try:
        f = float(v)
        # Check for NaN and Infinity (NaN != NaN is True)
        if f != f or f == float('inf') or f == float('-inf'):
            return None
        return round(f, decimals)
    except (TypeError, ValueError):
        return None


def safe_int(v):
    """Convert to int, handling NaN/None properly for valid JSON."""
    if v is None:
        return None
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (ImportError, TypeError):
        pass
    try:
        import numpy as np
        if isinstance(v, (np.floating, np.integer)):
            if np.isnan(v) or np.isinf(v):
                return None
    except (ImportError, TypeError):
        pass
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


# ─── DATA LOADERS ────────────────────────────────────────────────────────────

def load_scores(conn) -> pd.DataFrame:
    """Load stock_scores + sector_scores."""
    try:
        # First check which columns exist
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(stock_scores)")
        existing_cols = {r[1] for r in cur.fetchall()}

        base_cols = [
            "symbol", "composite_score", "fundamental_score",
            "smart_money_score", "momentum_score", "technical_score",
            "tier", "roe", "pe", "revenue_growth", "net_margin",
            "price_change_1d", "price_change_5d", "price_change_20d",
            "rsi14", "trend_short", "rank_total", "rank_pct",
            "debt_equity", "vol_ratio",
        ]
        optional_cols = ["foreign_net_7d", "foreign_net_30d"]
        # prop_net_7d removed: không có data từ VCI source

        select_cols = [c for c in base_cols if c in existing_cols]
        select_cols += [c for c in optional_cols if c in existing_cols]

        df = pd.read_sql(f"SELECT {', '.join(select_cols)} FROM stock_scores", conn)

        # Add missing optional columns as None
        for col in optional_cols:
            if col not in df.columns:
                df[col] = None

        log.info("Scores loaded: %d symbols", len(df))
        return df
    except Exception as e:
        log.error("Không load được stock_scores: %s (Chạy scoring.py trước)", e)
        return pd.DataFrame()


def load_symbols(conn) -> pd.DataFrame:
    """Load symbol → industry mapping."""
    # Thử từ DB trước
    try:
        df = pd.read_sql(
            "SELECT symbol, industry_name, industry_code, exchange, organ_name FROM symbols",
            conn
        )
        if not df.empty:
            return df
    except Exception:
        pass

    # Fallback JSON
    json_path = os.path.join(EXPORT_DIR, "symbols.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
        items = data.get("data", data) if isinstance(data, dict) else data
        df = pd.DataFrame(items)
        log.info("Symbols loaded from JSON: %d", len(df))
        return df
    log.warning("Không tìm thấy symbols data")
    return pd.DataFrame()


def load_foreign_flow_series(conn) -> pd.DataFrame:
    """
    Load foreign trading series 30 ngày để tính trend.
    Nếu rỗng trả về DataFrame rỗng.
    """
    try:
        df = pd.read_sql("""
            SELECT symbol, date, net_value AS foreign_net
            FROM foreign_trading
            WHERE date >= date('now', '-30 days')
            ORDER BY date
        """, conn)
        return df
    except Exception:
        return pd.DataFrame()


# ─── SECTOR ANALYSIS ─────────────────────────────────────────────────────────

def build_sector_data(scores_df: pd.DataFrame, symbols_df: pd.DataFrame,
                      foreign_series: pd.DataFrame) -> list:
    """
    Tổng hợp metrics theo ngành.
    Trả về list of dict, sorted by money_flow_rank.
    """
    if symbols_df.empty or scores_df.empty:
        return []

    # Normalize column names
    sym_df = symbols_df.copy()
    rename_map = {}
    for old, new in [("industryName", "industry_name"), ("organName", "organ_name")]:
        if old in sym_df.columns:
            rename_map[old] = new
    if rename_map:
        sym_df = sym_df.rename(columns=rename_map)

    if "industry_name" not in sym_df.columns:
        log.warning("Không có cột industry_name trong symbols")
        return []

    # Merge scores với industry
    merged = scores_df.merge(
        sym_df[["symbol", "industry_name"]].dropna(subset=["industry_name"]),
        on="symbol", how="inner"
    )
    if merged.empty:
        log.warning("Merge scores + symbols trống")
        return []

    log.info("Merged for sector analysis: %d rows, %d industries",
             len(merged), merged["industry_name"].nunique())

    # ── Aggregation per sector ────────────────────────────────────────────────
    agg_dict = {
        "symbol":              ("symbol", "count"),
        "avg_composite":       ("composite_score", "mean"),
        "avg_fundamental":     ("fundamental_score", "mean"),
        "avg_smart_money":     ("smart_money_score", "mean"),
        "avg_momentum":        ("momentum_score", "mean"),
        "avg_technical":       ("technical_score", "mean"),
        "avg_roe":             ("roe", "mean"),
        "avg_pe":              ("pe", "mean"),
        "avg_revenue_growth":  ("revenue_growth", "mean"),
        "avg_net_margin":      ("net_margin", "mean"),
        "avg_price_5d":        ("price_change_5d", "mean"),
        "avg_price_20d":       ("price_change_20d", "mean"),
    }

    sector = merged.groupby("industry_name").agg(**agg_dict).reset_index()
    sector.rename(columns={"symbol": "symbol_count"}, inplace=True)

    # Tier distribution
    tier_counts = merged.groupby(["industry_name", "tier"]).size().unstack(fill_value=0)
    for tier in ["A", "B", "C", "D", "F"]:
        if tier not in tier_counts.columns:
            tier_counts[tier] = 0
    sector = sector.merge(
        tier_counts[["A", "B", "C", "D", "F"]].rename(
            columns={t: f"tier_{t.lower()}_count" for t in ["A","B","C","D","F"]}
        ),
        left_on="industry_name", right_index=True, how="left"
    )
    sector["tier_a_pct"] = (sector["tier_a_count"] / sector["symbol_count"] * 100).round(1)

    # Foreign flow từ scores (đã aggregate)
    if "foreign_net_7d" in merged.columns:
        flow = merged.groupby("industry_name").agg(
            foreign_net_7d  = ("foreign_net_7d",  "sum"),
            foreign_net_30d = ("foreign_net_30d", "sum"),
            # prop_net_7d removed: không có data từ VCI source
        ).reset_index()
        sector = sector.merge(flow, on="industry_name", how="left")
    else:
        sector["foreign_net_7d"]  = None
        sector["foreign_net_30d"] = None

    # ── Rankings ─────────────────────────────────────────────────────────────
    sector["money_flow_rank"]  = sector["foreign_net_7d"].rank(ascending=False, na_option="bottom").astype(int)
    sector["composite_rank"]   = sector["avg_composite"].rank(ascending=False).astype(int)
    sector["momentum_rank"]    = sector["avg_momentum"].rank(ascending=False).astype(int)
    sector["fundamental_rank"] = sector["avg_fundamental"].rank(ascending=False).astype(int)

    # ── Top stocks per sector ────────────────────────────────────────────────
    top_stocks_map = (
        merged.sort_values("composite_score", ascending=False)
              .groupby("industry_name")
              .head(5)
              .groupby("industry_name")["symbol"]
              .apply(list)
              .to_dict()
    )

    # ── Assemble output ───────────────────────────────────────────────────────
    out = []
    for _, row in sector.sort_values("money_flow_rank").iterrows():
        name = row["industry_name"]
        out.append({
            "name":                name,
            "symbol_count":        safe_int(row["symbol_count"]),
            "avg_composite_score": safe_float(row["avg_composite"]),
            "avg_fundamental_score": safe_float(row["avg_fundamental"]),
            "avg_smart_money_score": safe_float(row["avg_smart_money"]),
            "avg_momentum_score":  safe_float(row["avg_momentum"]),
            "avg_technical_score": safe_float(row["avg_technical"]),
            "avg_roe":             safe_float(row.get("avg_roe")),
            "avg_pe":              safe_float(row.get("avg_pe")),
            "avg_revenue_growth":  safe_float(row.get("avg_revenue_growth")),
            "avg_net_margin":      safe_float(row.get("avg_net_margin")),
            "avg_price_5d":        safe_float(row.get("avg_price_5d")),
            "avg_price_20d":       safe_float(row.get("avg_price_20d")),
            "foreign_net_7d":      safe_float(row.get("foreign_net_7d"), 1),
            "foreign_net_30d":     safe_float(row.get("foreign_net_30d"), 1),
            # prop_net_7d removed: không có data từ VCI source
            "tier_a_pct":          safe_float(row.get("tier_a_pct")),
            "tier_a_count":        safe_int(row.get("tier_a_count", 0)),
            "tier_b_count":        safe_int(row.get("tier_b_count", 0)),
            "money_flow_rank":     safe_int(row["money_flow_rank"]),
            "composite_rank":      safe_int(row["composite_rank"]),
            "momentum_rank":       safe_int(row["momentum_rank"]),
            "fundamental_rank":    safe_int(row["fundamental_rank"]),
            "top_stocks":          top_stocks_map.get(name, [])[:5],
        })

    return out


def build_rotation_signal(sectors: list) -> dict:
    """
    Phát hiện sector rotation signal dựa trên money flow + momentum.
    Trả về dict với 3 nhóm: accumulating / distributing / hot
    """
    if not sectors:
        return {}

    n = len(sectors)

    # Accumulating: top 30% money flow VÀ positive net flow
    accumulating = [
        s["name"] for s in sectors
        if s.get("money_flow_rank") and s["money_flow_rank"] <= max(3, n * 0.3)
        and (s.get("foreign_net_7d") or 0) > 0
    ]

    # Distributing: bottom 30% money flow VÀ negative net flow
    distributing = [
        s["name"] for s in sectors
        if s.get("money_flow_rank") and s["money_flow_rank"] >= n - max(3, int(n * 0.3))
        and (s.get("foreign_net_7d") or 0) < 0
    ]

    # Hot sectors: top momentum (avg_price_5d cao nhất)
    hot_sorted = sorted(
        [s for s in sectors if s.get("avg_price_5d") is not None],
        key=lambda x: x["avg_price_5d"],
        reverse=True
    )
    hot = [s["name"] for s in hot_sorted[:3]]

    # Strong fundamentals: avg composite >= 60
    strong = [
        s["name"] for s in sorted(sectors, key=lambda x: x.get("avg_composite_score") or 0, reverse=True)
        if (s.get("avg_composite_score") or 0) >= 60
    ][:3]

    return {
        "accumulating":        accumulating[:5],
        "distributing":        distributing[:5],
        "hot_sectors":         hot,
        "strong_fundamentals": strong,
        "signal_date":         datetime.now().strftime("%Y-%m-%d"),
    }


# ─── EXPORT ─────────────────────────────────────────────────────────────────

def export_sectors(sectors: list, rotation: dict, meta: dict):
    """Ghi sectors.json ra EXPORT_DIR."""
    os.makedirs(EXPORT_DIR, exist_ok=True)

    output = {
        "generated_at":    datetime.utcnow().isoformat() + "Z",
        "total_sectors":   len(sectors),
        "meta":            meta,
        "sectors":         sectors,
        "rotation_signal": rotation,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_PATH) / 1024
    log.info("✅ Exported %d sectors → %s (%.1f KB)", len(sectors), OUT_PATH, size_kb)


# ─── ALSO UPDATE screener.json WITH SCORES ──────────────────────────────────

def export_screener(conn, scores_df: pd.DataFrame, symbols_df: pd.DataFrame):
    """
    Tạo screener.json: danh sách cổ phiếu với composite score + metadata.
    Kết hợp với prices.json để thêm history cho sparkline.
    """
    screener_path = os.path.join(EXPORT_DIR, "screener.json")

    # Load history từ prices.json
    price_data = {}
    prices_path = os.path.join(EXPORT_DIR, "prices.json")
    if os.path.exists(prices_path):
        with open(prices_path) as f:
            prices_json = json.load(f)
        for sym, data in prices_json.get("prices", {}).items():
            # Lấy 30 ngày gần nhất của close prices làm history
            close_prices = data.get("close", [])
            price_data[sym] = {
                "close":   close_prices[-1] if close_prices else None,
                "history": close_prices[-30:] if close_prices else [],
            }
        log.info("Loaded price history for %d symbols from prices.json", len(price_data))

    # Build symbols lookup
    sym_lookup = {}
    if not symbols_df.empty:
        for _, row in symbols_df.iterrows():
            sym_lookup[row["symbol"]] = {
                "name":         row.get("organ_name", ""),
                "industry":     row.get("industry_name", ""),
                "exchange":     row.get("exchange", ""),
            }

    rows = []
    for _, row in scores_df.iterrows():
        sym   = row["symbol"]
        price = price_data.get(sym, {})
        meta  = sym_lookup.get(sym, {})

        rows.append({
            "symbol":             sym,
            "name":               meta.get("name", ""),
            "industry":           meta.get("industry", ""),
            "exchange":           meta.get("exchange", ""),
            # Scores
            "composite_score":    safe_float(row.get("composite_score")),
            "fundamental_score":  safe_float(row.get("fundamental_score")),
            "smart_money_score":  safe_float(row.get("smart_money_score")),
            "momentum_score":     safe_float(row.get("momentum_score")),
            "technical_score":    safe_float(row.get("technical_score")),
            "tier":               row.get("tier"),
            "rank":               safe_int(row.get("rank_total")),
            "rank_pct":           safe_float(row.get("rank_pct")),
            # Financials
            "roe":                safe_float(row.get("roe")),
            "roa":                safe_float(row.get("roa")),
            "pe":                 safe_float(row.get("pe")),
            "revenue_growth":     safe_float(row.get("revenue_growth")),
            "net_margin":         safe_float(row.get("net_margin")),
            "debt_equity":        safe_float(row.get("debt_equity")),
            # Technical
            "rsi14":              safe_float(row.get("rsi14")),
            "price_change_1d":    safe_float(row.get("price_change_1d")),
            "price_change_5d":    safe_float(row.get("price_change_5d")),
            "price_change_20d":   safe_float(row.get("price_change_20d")),
            "trend_short":        safe_int(row.get("trend_short")),
            # Smart money
            "foreign_net_7d":     safe_float(row.get("foreign_net_7d"), 1),
            # History sparkline (từ prices.json)
            "history":            price.get("history", []),
            "data_completeness":  safe_float(row.get("data_completeness")),
        })

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total":        len(rows),
        "screener":     rows,
    }

    with open(screener_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(screener_path) / 1024
    log.info("✅ Exported screener → %s (%.1f KB)", screener_path, size_kb)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row

    log.info("=== Loading data ===")
    scores_df        = load_scores(conn)
    symbols_df       = load_symbols(conn)
    foreign_series   = load_foreign_flow_series(conn)

    if scores_df.empty:
        log.error("stock_scores rỗng. Chạy scoring.py trước.")
        conn.close()
        return

    log.info("=== Building sector analysis ===")
    sectors  = build_sector_data(scores_df, symbols_df, foreign_series)
    rotation = build_rotation_signal(sectors)

    # Meta stats
    meta = {
        "total_symbols":   len(scores_df),
        "scored_symbols":  int((scores_df["composite_score"] > 0).sum()),
        "has_smart_money": bool(scores_df["foreign_net_7d"].notna().any()),
        "has_technical":   bool(scores_df["rsi14"].notna().any()),
        "tier_distribution": scores_df["tier"].value_counts().to_dict(),
        "avg_composite":   safe_float(scores_df["composite_score"].mean()),
        "top_composite":   safe_float(scores_df["composite_score"].max()),
    }

    log.info("Sectors: %d | Rotation: %s", len(sectors), rotation)

    # Export
    log.info("=== Exporting ===")
    export_sectors(sectors, rotation, meta)
    export_screener(conn, scores_df, symbols_df)

    # Print rotation summary
    if rotation.get("accumulating"):
        log.info("📈 Ngành đang được tích lũy: %s", ", ".join(rotation["accumulating"]))
    if rotation.get("hot_sectors"):
        log.info("🔥 Ngành hot nhất: %s", ", ".join(rotation["hot_sectors"]))
    if rotation.get("distributing"):
        log.info("📉 Ngành đang bị phân phối: %s", ", ".join(rotation["distributing"]))

    conn.close()
    log.info("✅ Sector analysis done — %d sectors analyzed", len(sectors))


if __name__ == "__main__":
    run()
