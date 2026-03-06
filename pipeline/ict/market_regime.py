"""
ict/market_regime.py — Market Regime Detector

Xác định trạng thái VNINDEX: BULL / BEAR / RANGE / TRANSITION
Dùng làm global filter — trong BEAR, giảm 50-70% weight bullish signals.

Output (regime_result dict):
  regime          : "BULL" | "BEAR" | "RANGE" | "TRANSITION"
  regime_strength : 0-100
  bull_weight     : 0.3-1.0 (nhân với bullish signal weights)
  components      : dict sub-scores

bull_weight theo regime:
  BULL       → 1.0  (full weight)
  TRANSITION → 0.7
  RANGE      → 0.5
  BEAR       → 0.3

Chạy độc lập:
  python -m pipeline.ict.market_regime
"""

import os, sys, logging
from typing import Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all

log = logging.getLogger(__name__)

BULL_WEIGHTS = {"BULL": 1.0, "TRANSITION": 0.7, "RANGE": 0.5, "BEAR": 0.3}


# ─── COMPONENT SCORERS ───────────────────────────────────────────────────────

def _score_vnindex(change_5d: Optional[float], change_20d: Optional[float]) -> dict:
    """Score VNINDEX momentum (0-100)."""
    if change_5d is None and change_20d is None:
        return {"score": 50.0, "signal": "neutral", "detail": "no data"}

    score = 50.0
    detail = []

    if change_5d is not None:
        # ±3% = ±20pts, ±1% = ±8pts
        if   change_5d >=  3.0: score += 20; detail.append(f"5d=+{change_5d:.1f}%")
        elif change_5d >=  1.0: score += 8;  detail.append(f"5d=+{change_5d:.1f}%")
        elif change_5d <= -3.0: score -= 20; detail.append(f"5d={change_5d:.1f}%")
        elif change_5d <= -1.0: score -= 8;  detail.append(f"5d={change_5d:.1f}%")

    if change_20d is not None:
        if   change_20d >=  5.0: score += 15; detail.append(f"20d=+{change_20d:.1f}%")
        elif change_20d >=  2.0: score += 7
        elif change_20d <= -5.0: score -= 15; detail.append(f"20d={change_20d:.1f}%")
        elif change_20d <= -2.0: score -= 7

    score = float(np.clip(score, 0, 100))
    return {
        "score":  score,
        "signal": "bull" if score >= 60 else ("bear" if score <= 40 else "neutral"),
        "detail": ", ".join(detail) if detail else "flat",
    }


def _score_breadth(screener_df: pd.DataFrame) -> dict:
    """% stocks tăng hôm nay (0-100)."""
    if screener_df.empty or "price_change_1d" not in screener_df.columns:
        return {"score": 50.0, "advance_pct": None, "signal": "neutral"}

    ch = screener_df["price_change_1d"].dropna()
    if len(ch) == 0:
        return {"score": 50.0, "advance_pct": None, "signal": "neutral"}

    adv_pct = float((ch > 0).sum() / len(ch) * 100)
    # 30%→0, 50%→50, 70%→100
    score = float(np.clip((adv_pct - 30) / 40 * 100, 0, 100))
    return {
        "score":       round(score, 1),
        "advance_pct": round(adv_pct, 1),
        "advance":     int((ch > 0).sum()),
        "decline":     int((ch < 0).sum()),
        "total":       int(len(ch)),
        "signal":      "bull" if adv_pct >= 55 else ("bear" if adv_pct <= 45 else "neutral"),
    }


def _score_sector_breadth(sectors_df: pd.DataFrame) -> dict:
    """% ngành có momentum dương."""
    if sectors_df.empty or "avg_price_5d" not in sectors_df.columns:
        return {"score": 50.0, "bull_sectors": 0, "bear_sectors": 0}

    ch     = sectors_df["avg_price_5d"].dropna()
    bull_s = int((ch > 0).sum())
    bear_s = int((ch < 0).sum())
    score  = float(np.clip(bull_s / max(len(ch), 1) * 100, 0, 100))
    return {
        "score":         round(score, 1),
        "bull_sectors":  bull_s,
        "bear_sectors":  bear_s,
        "total_sectors": int(len(ch)),
    }


def _score_foreign(screener_df: pd.DataFrame) -> dict:
    """Net foreign flow 7d toàn thị trường."""
    if screener_df.empty or "foreign_net_7d" not in screener_df.columns:
        return {"score": 50.0, "net_total_bn": None, "signal": "neutral"}

    flows = screener_df["foreign_net_7d"].dropna()
    if len(flows) == 0:
        return {"score": 50.0, "net_total_bn": None, "signal": "neutral"}

    net = float(flows.sum())
    # ±1000 tỷ = ±25pts
    score = float(np.clip(50 + net / 1000 * 25, 0, 100))
    return {
        "score":        round(score, 1),
        "net_total_bn": round(net, 1),
        "signal":       "bull" if net > 200 else ("bear" if net < -200 else "neutral"),
    }


# ─── REGIME CLASSIFIER ───────────────────────────────────────────────────────

def _classify(composite: float, change_5d: Optional[float],
              advance_pct: Optional[float]) -> tuple:
    """(regime, strength) từ composite score + supporting signals."""
    if   composite >= 65: regime, strength = "BULL",       min(100, 50 + (composite-65)/35*50)
    elif composite >= 52: regime, strength = "TRANSITION", 40 + (composite-52)/13*20
    elif composite >= 38: regime, strength = "RANGE",      max(20, 50 - abs(composite-50)*1.5)
    else:                 regime, strength = "BEAR",       min(100, 50 + (38-composite)/38*50)

    # Tăng confidence nếu momentum + breadth đồng thuận
    if change_5d is not None and advance_pct is not None:
        if change_5d > 3 and advance_pct > 60 and regime in ("BULL","TRANSITION"):
            regime = "BULL"; strength = min(100, strength + 15)
        elif change_5d < -3 and advance_pct < 40 and regime in ("BEAR","TRANSITION"):
            regime = "BEAR"; strength = min(100, strength + 15)

    return regime, round(float(strength), 1)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def detect_regime(ctx: ICTDataContext) -> dict:
    """
    Detect market regime từ ICTDataContext.

    Returns dict với:
      regime, regime_strength, bull_weight, composite_score,
      vnindex/change fields, components, breadth_advance_pct
    """
    s   = ctx.summary
    scr = ctx.screener_df
    sec = ctx.sectors_df

    c1d  = s.get("vnindex_change") or s.get("vnindex_change_1d")
    c5d  = s.get("vnindex_change_5d")
    c20d = s.get("vnindex_change_20d")

    mom    = _score_vnindex(c5d, c20d)
    bread  = _score_breadth(scr)
    sbread = _score_sector_breadth(sec)
    flow   = _score_foreign(scr)

    # Weighted composite: momentum 40%, breadth 30%, sector 20%, foreign 10%
    composite = (mom["score"] * 0.40 + bread["score"] * 0.30 +
                 sbread["score"] * 0.20 + flow["score"] * 0.10)

    regime, strength = _classify(composite, c5d, bread.get("advance_pct"))
    bull_weight      = BULL_WEIGHTS[regime]

    result = {
        "regime":           regime,
        "regime_strength":  strength,
        "bull_weight":      bull_weight,
        "composite_score":  round(composite, 1),
        "vnindex":          s.get("vnindex"),
        "vnindex_change_1d":c1d,
        "vnindex_change_5d":c5d,
        "vnindex_change_20d":c20d,
        "breadth_advance_pct": bread.get("advance_pct"),
        "bull_sectors":     sbread.get("bull_sectors"),
        "bear_sectors":     sbread.get("bear_sectors"),
        "foreign_net_total_bn": flow.get("net_total_bn"),
        "components": {
            "vnindex_momentum": mom,
            "market_breadth":   bread,
            "sector_breadth":   sbread,
            "foreign_flow":     flow,
        },
    }

    log.info("Regime: %s (strength=%.0f, bull_weight=%.1f) | VNINDEX: %s (5d: %s%%) | Breadth: %s%%",
             regime, strength, bull_weight,
             s.get("vnindex"), c5d, bread.get("advance_pct"))
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ctx = load_all()
    r   = detect_regime(ctx)

    print(f"\n{'═'*52}")
    print(f"  REGIME        : {r['regime']}")
    print(f"  Strength      : {r['regime_strength']}")
    bw = r['bull_weight']
    bw_label = 'full' if bw == 1.0 else f'giảm còn {bw*100:.0f}%'
    print(f"  Bull weight   : {bw}  ({bw_label})")
    print(f"  Composite     : {r['composite_score']}")
    print(f"  VNINDEX       : {r['vnindex']} | 1d={r['vnindex_change_1d']}% | 5d={r['vnindex_change_5d']}%")
    print(f"  Breadth       : {r['breadth_advance_pct']}% advance")
    print(f"  Sectors       : {r['bull_sectors']} bull / {r['bear_sectors']} bear")
    print(f"  Foreign net   : {r['foreign_net_total_bn']} tỷ đồng")
    print(f"{'═'*52}")
    for name, comp in r["components"].items():
        print(f"  {name:<22}: score={comp.get('score','?'):>5.1f}  signal={comp.get('signal','-')}")
