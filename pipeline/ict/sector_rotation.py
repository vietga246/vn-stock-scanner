"""
ict/sector_rotation.py — Sector Rotation Detector

Tính RS ranking cho 25 ngành và detect rotation:
  - Ngành nào đang được tích lũy (dòng tiền vào)
  - Ngành nào đang phân phối (dòng tiền ra)
  - Ngành nào đang dẫn dắt thị trường
  - Detect rotation 3-5 ngày trước khi rõ ràng

Output (sector_rotation_result dict):
  sectors          : list các ngành với RS scores
  leading          : top 5 ngành dẫn dắt
  lagging          : bottom 5 ngành yếu nhất
  rotating_in      : ngành có RS improving (5d tốt hơn 20d)
  rotating_out     : ngành có RS deteriorating
  accumulating     : từ existing rotation_signal trong sectors.json
  distributing     : từ existing rotation_signal
  symbol_sector_map: dict symbol → sector_rs_rank (dùng cho alpha_scoring)

Chạy độc lập:
  python -m pipeline.ict.sector_rotation
"""

import os, sys, logging
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all

log = logging.getLogger(__name__)


# ─── RS CALCULATION ──────────────────────────────────────────────────────────

def _calc_sector_rs(sectors_df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính RS score cho từng ngành so với median market.

    RS 5d  = avg_price_5d của ngành − median(avg_price_5d toàn thị trường)
    RS 20d = avg_price_20d của ngành − median(avg_price_20d)
    RS slope = RS_5d − RS_20d  (positive = improving)
    """
    df = sectors_df.copy()

    if "avg_price_5d" in df.columns:
        median_5d = df["avg_price_5d"].median()
        df["rs_5d"] = df["avg_price_5d"] - median_5d
        df["rs_5d_pct"] = df["avg_price_5d"]  # giữ lại % absolute
    else:
        df["rs_5d"]     = 0.0
        df["rs_5d_pct"] = None

    if "avg_price_20d" in df.columns:
        median_20d = df["avg_price_20d"].median()
        df["rs_20d"] = df["avg_price_20d"] - median_20d
    else:
        df["rs_20d"] = 0.0

    # RS slope: improving nếu dương
    df["rs_slope"] = df["rs_5d"] - df["rs_20d"]

    # RS rank: 1 = tốt nhất
    df["rs_rank"] = df["rs_5d"].rank(ascending=False, method="min").astype(int)

    # Money flow score: foreign + composite score
    flow_cols = []
    if "foreign_net_7d" in df.columns:
        flow_cols.append(df["foreign_net_7d"].fillna(0))
    if "avg_momentum_score" in df.columns:
        flow_cols.append(df["avg_momentum_score"].fillna(50) - 50)

    if flow_cols:
        # Normalize mỗi component về -1/+1 rồi average
        flow_norm = pd.concat(flow_cols, axis=1)
        for col in flow_norm.columns:
            std = flow_norm[col].std()
            if std and std > 0:
                flow_norm[col] = flow_norm[col] / (std * 3)  # clip vào ±1
        df["flow_score"] = flow_norm.mean(axis=1).clip(-1, 1)
    else:
        df["flow_score"] = 0.0

    return df


def _detect_rotation(df: pd.DataFrame, existing_rotation: dict) -> dict:
    """
    Detect rotation signal:
      - rotating_in  : RS slope > 0 và rs_rank ≤ 10 → improving leader
      - rotating_out : RS slope < 0 và rs_rank ≤ 10 → deteriorating leader
      - breakout_candidate: RS rank ≤ 5 + flow_score > 0.3
    """
    if df.empty:
        return {"rotating_in": [], "rotating_out": [], "breakout_candidate": []}

    rotating_in  = df[(df["rs_slope"] > 0.5) & (df["rs_rank"] <= 12)]["name"].tolist()
    rotating_out = df[(df["rs_slope"] < -0.5) & (df["rs_rank"] <= 12)]["name"].tolist()
    breakout     = df[(df["rs_rank"] <= 5) & (df.get("flow_score", pd.Series(0, index=df.index)) > 0.3)]["name"].tolist()

    return {
        "rotating_in":        rotating_in,
        "rotating_out":       rotating_out,
        "breakout_candidate": breakout,
        # Lấy existing signal từ sectors.json (đã tính)
        "accumulating": existing_rotation.get("accumulating", []),
        "distributing": existing_rotation.get("distributing", []),
        "hot_sectors":  existing_rotation.get("hot_sectors", []),
    }


# ─── SYMBOL→SECTOR MAPPING ───────────────────────────────────────────────────

def build_symbol_sector_map(screener_df: pd.DataFrame,
                            sectors_rs_df: pd.DataFrame) -> dict:
    """
    Tạo dict symbol → dict với sector_name, sector_rs_rank, sector_rs_5d.
    Dùng bởi alpha_scoring.py để tính RS vs sector.
    """
    if screener_df.empty or "industry" not in screener_df.columns:
        return {}

    # Build sector lookup: name → rs info
    if not sectors_rs_df.empty and "name" in sectors_rs_df.columns:
        sector_info = {
            row["name"]: {
                "rs_rank":  row.get("rs_rank"),
                "rs_5d":    row.get("rs_5d"),
                "rs_slope": row.get("rs_slope"),
                "avg_price_5d": row.get("avg_price_5d"),
            }
            for _, row in sectors_rs_df.iterrows()
        }
    else:
        sector_info = {}

    result = {}
    for _, row in screener_df.iterrows():
        sym    = row["symbol"]
        sector = row.get("industry", "")
        info   = sector_info.get(sector, {})
        result[sym] = {
            "sector":          sector,
            "sector_rs_rank":  info.get("rs_rank"),
            "sector_rs_5d":    info.get("rs_5d"),
            "sector_rs_slope": info.get("rs_slope"),
            "sector_avg_5d":   info.get("avg_price_5d"),
        }

    return result


# ─── MAIN ────────────────────────────────────────────────────────────────────

def analyze_sectors(ctx: ICTDataContext) -> dict:
    """
    Phân tích sector rotation từ ICTDataContext.

    Returns dict với sectors list, rotation signals, symbol→sector map.
    """
    sectors_df = ctx.sectors_df
    rotation   = ctx.rotation
    screener_df = ctx.screener_df

    if sectors_df.empty:
        log.warning("Sectors data rỗng")
        return {"sectors": [], "rotation": {}, "symbol_sector_map": {}}

    # Tính RS scores
    sectors_rs = _calc_sector_rs(sectors_df)

    # Sort by RS rank
    sectors_sorted = sectors_rs.sort_values("rs_rank", ascending=True)

    # Detect rotation
    rot_signals = _detect_rotation(sectors_sorted, rotation)

    # Symbol → sector mapping
    sym_map = build_symbol_sector_map(screener_df, sectors_rs)

    # Build output list
    sectors_out = []
    for _, row in sectors_sorted.iterrows():
        sectors_out.append({
            "name":            row.get("name"),
            "rs_rank":         int(row.get("rs_rank", 0)),
            "rs_5d":           round(float(row.get("rs_5d", 0)), 2),
            "rs_20d":          round(float(row.get("rs_20d", 0)), 2) if "rs_20d" in row else None,
            "rs_slope":        round(float(row.get("rs_slope", 0)), 2),
            "avg_price_5d":    row.get("avg_price_5d"),
            "avg_price_20d":   row.get("avg_price_20d"),
            "flow_score":      round(float(row.get("flow_score", 0)), 3),
            "foreign_net_7d":  row.get("foreign_net_7d"),
            "symbol_count":    row.get("symbol_count"),
            "avg_composite":   row.get("avg_composite_score"),
            "momentum_rank":   row.get("momentum_rank"),
            "money_flow_rank": row.get("money_flow_rank"),
        })

    leading = [s["name"] for s in sectors_out[:5]]
    lagging = [s["name"] for s in sectors_out[-5:]]

    result = {
        "sectors":           sectors_out,
        "leading":           leading,
        "lagging":           lagging,
        "rotating_in":       rot_signals["rotating_in"],
        "rotating_out":      rot_signals["rotating_out"],
        "breakout_candidate":rot_signals["breakout_candidate"],
        "accumulating":      rot_signals["accumulating"],
        "distributing":      rot_signals["distributing"],
        "hot_sectors":       rot_signals["hot_sectors"],
        "symbol_sector_map": sym_map,
        "total_sectors":     len(sectors_out),
    }

    log.info("Sectors: %d | Leading: %s", len(sectors_out), ", ".join(leading[:3]))
    log.info("Rotating IN : %s", rot_signals["rotating_in"][:3])
    log.info("Accumulating: %s", rot_signals["accumulating"][:3])
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ctx = load_all()
    r   = analyze_sectors(ctx)

    print(f"\n{'═'*55}")
    print(f"  SECTOR ROTATION — {r['total_sectors']} sectors")
    print(f"{'═'*55}")
    print(f"  Leading    : {r['leading']}")
    print(f"  Lagging    : {r['lagging']}")
    print(f"  Rotating IN: {r['rotating_in']}")
    print(f"  Accumulating (existing): {r['accumulating']}")
    print(f"  Hot sectors: {r['hot_sectors']}")
    print(f"\n  {'Rank':<4} {'Sector':<28} {'RS_5d':>6} {'RS_slope':>8} {'Flow':>6}")
    print(f"  {'─'*54}")
    for s in r["sectors"][:10]:
        print(f"  #{s['rs_rank']:<3} {str(s['name']):<28} {s['rs_5d']:>+6.2f} {s['rs_slope']:>+8.2f} {s['flow_score']:>+6.3f}")
