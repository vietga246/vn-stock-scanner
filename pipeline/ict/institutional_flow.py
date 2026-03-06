"""
ict/institutional_flow.py — Institutional Flow Analyzer

Tính composite institutional flow score từ:
  1. Foreign net flow 7d/30d (từ screener.json)
  2. Buy pressure % từ price_board.json (bid vs ask)
  3. Bid/ask ratio (3 levels)
  4. Foreign flow direction trend

Output per symbol (dict):
  inst_flow_score : 0-100 composite
  flow_direction  : "in" | "out" | "neutral"
  foreign_net_7d  : tỷ đồng
  foreign_net_30d : tỷ đồng
  buy_pressure    : 0-100 (% bid volume trong bid+ask)
  bid_ask_ratio   : bid1_vol / ask1_vol
  flow_trend      : "accelerating" | "decelerating" | "steady"
  smart_money_conf: bool — foreign + buy_pressure đồng thuận
  signal_count    : số signals bullish

Cách dùng:
  from pipeline.ict.institutional_flow import analyze_all
  results = analyze_all(ctx)

Chạy độc lập:
  python -m pipeline.ict.institutional_flow
  python -m pipeline.ict.institutional_flow --symbol FPT
"""

import os, sys, logging
from typing import Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all

log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

# Ngưỡng foreign net (tỷ đồng) để classify
FLOW_STRONG_IN    =  5.0   # ≥ 5 tỷ/7d = strong buy
FLOW_IN           =  1.0   # ≥ 1 tỷ/7d = buy
FLOW_OUT          = -1.0   # ≤ -1 tỷ/7d = sell
FLOW_STRONG_OUT   = -5.0   # ≤ -5 tỷ/7d = strong sell

# Buy pressure ngưỡng
BP_BULLISH  = 55.0   # ≥55% = buyers dominating
BP_BEARISH  = 45.0   # ≤45% = sellers dominating


# ─── COMPONENT SCORERS ───────────────────────────────────────────────────────

def _score_foreign_flow(net_7d: Optional[float],
                        net_30d: Optional[float]) -> dict:
    """
    Score foreign flow (0-100).
    7d: weight 60%, 30d: weight 40%.
    Chuẩn hóa relative to cap — ±20 tỷ = ±25pts.
    """
    if net_7d is None and net_30d is None:
        return {"score": 50.0, "signal": "neutral", "detail": "no data"}

    score  = 50.0
    detail = []

    if net_7d is not None:
        if   net_7d >= FLOW_STRONG_IN:  score += 25; detail.append(f"7d=+{net_7d:.1f}tỷ")
        elif net_7d >= FLOW_IN:         score += 12; detail.append(f"7d=+{net_7d:.1f}tỷ")
        elif net_7d <= FLOW_STRONG_OUT: score -= 25; detail.append(f"7d={net_7d:.1f}tỷ")
        elif net_7d <= FLOW_OUT:        score -= 12; detail.append(f"7d={net_7d:.1f}tỷ")

    if net_30d is not None:
        if   net_30d >=  20.0: score += 15; detail.append(f"30d=+{net_30d:.1f}tỷ")
        elif net_30d >=   5.0: score += 8
        elif net_30d <= -20.0: score -= 15; detail.append(f"30d={net_30d:.1f}tỷ")
        elif net_30d <=  -5.0: score -= 8

    # Flow trend: 7d > 30d/4 = accelerating
    trend = "steady"
    if net_7d is not None and net_30d is not None and net_30d != 0:
        weekly_equiv = net_30d / 4
        if net_7d > weekly_equiv * 1.5:   trend = "accelerating"
        elif net_7d < weekly_equiv * 0.5: trend = "decelerating"

    score = float(np.clip(score, 0, 100))
    return {
        "score":  score,
        "signal": "in" if score >= 60 else ("out" if score <= 40 else "neutral"),
        "trend":  trend,
        "detail": ", ".join(detail) if detail else "neutral",
    }


def _score_buy_pressure(buy_pressure_pct: Optional[float],
                        bid1_vol: Optional[float],
                        ask1_vol: Optional[float]) -> dict:
    """
    Score áp lực mua từ bid/ask data (0-100).
    buy_pressure_pct = bid_total / (bid_total + ask_total) * 100
    """
    if buy_pressure_pct is None and bid1_vol is None:
        return {"score": 50.0, "signal": "neutral", "bid_ask_ratio": None}

    score = 50.0

    # Buy pressure %
    if buy_pressure_pct is not None:
        # 45%→30pts, 50%→50pts, 55%→70pts, 60%→85pts
        score = float(np.clip((buy_pressure_pct - 30) / 40 * 100, 0, 100))

    # Bid/ask ratio bậc 1 (confirm)
    ba_ratio = None
    if bid1_vol is not None and ask1_vol is not None and ask1_vol > 0:
        ba_ratio = float(bid1_vol / ask1_vol)
        # Ratio > 2 = strong buy pressure (thêm 5pts)
        if ba_ratio > 2.0:   score = min(100, score + 8)
        elif ba_ratio < 0.5: score = max(0, score - 8)

    return {
        "score":         round(float(score), 1),
        "signal":        "bull" if buy_pressure_pct and buy_pressure_pct >= BP_BULLISH
                         else ("bear" if buy_pressure_pct and buy_pressure_pct <= BP_BEARISH
                               else "neutral"),
        "buy_pressure_pct": buy_pressure_pct,
        "bid_ask_ratio": round(ba_ratio, 3) if ba_ratio is not None else None,
    }


# ─── SMART MONEY CONFLUENCE ───────────────────────────────────────────────────

def _smart_money_confluence(foreign_score: float, bp_score: float,
                            net_7d: Optional[float]) -> bool:
    """
    Smart money confirmation: foreign IN + high buy pressure đồng thuận.
    Đây là signal chất lượng cao nhất trong institutional flow.
    """
    foreign_bullish = foreign_score >= 62
    bp_bullish      = bp_score >= 60
    net_positive    = net_7d is not None and net_7d > 0

    return foreign_bullish and bp_bullish and net_positive


# ─── ANALYZE SINGLE SYMBOL ───────────────────────────────────────────────────

def analyze_symbol(screener: dict, board: dict) -> dict:
    """
    Tính institutional flow score cho 1 symbol.

    Args:
        screener: dict từ ctx.get_screener(sym)
        board   : dict từ ctx.get_board(sym)
    """
    # Extract foreign flow
    net_7d  = screener.get("foreign_net_7d")
    net_30d = screener.get("foreign_net_30d")

    # Extract buy pressure
    bp_pct    = board.get("buy_pressure_pct")
    bid1_vol  = board.get("bid1_volume")
    ask1_vol  = board.get("ask1_volume")

    # Score components
    f_result = _score_foreign_flow(net_7d, net_30d)
    b_result = _score_buy_pressure(bp_pct, bid1_vol, ask1_vol)

    # Weighted composite: foreign 60%, buy_pressure 40%
    # (foreign flow là institutional money thực sự, buy_pressure là proxy)
    has_foreign = net_7d is not None or net_30d is not None
    has_bp      = bp_pct is not None

    if has_foreign and has_bp:
        composite = f_result["score"] * 0.60 + b_result["score"] * 0.40
    elif has_foreign:
        composite = f_result["score"]
    elif has_bp:
        composite = b_result["score"]
    else:
        composite = 50.0

    composite = float(np.clip(composite, 0, 100))

    # Flow direction
    if   composite >= 62: direction = "in"
    elif composite <= 38: direction = "out"
    else:                 direction = "neutral"

    # Smart money confirmation
    smart_money = _smart_money_confluence(f_result["score"], b_result["score"], net_7d)

    # Signal count
    sig = 0
    if direction == "in":           sig += 1
    if smart_money:                 sig += 1
    if f_result.get("trend") == "accelerating" and direction == "in": sig += 1
    if b_result.get("signal") == "bull":  sig += 1

    return {
        "inst_flow_score":  round(composite, 1),
        "flow_direction":   direction,
        "smart_money_conf": smart_money,
        "foreign_net_7d":   net_7d,
        "foreign_net_30d":  net_30d,
        "buy_pressure_pct": bp_pct,
        "bid_ask_ratio":    b_result.get("bid_ask_ratio"),
        "flow_trend":       f_result.get("trend", "steady"),
        "foreign_score":    round(f_result["score"], 1),
        "bp_score":         round(b_result["score"], 1),
        "signal_count":     sig,
        # Details
        "foreign_detail":   f_result.get("detail"),
        "has_foreign_data": has_foreign,
        "has_bp_data":      has_bp,
    }


# ─── BATCH ANALYSIS ──────────────────────────────────────────────────────────

def analyze_all(ctx: ICTDataContext) -> dict:
    """
    Chạy institutional flow analysis cho tất cả symbols.

    Returns:
        dict symbol → analysis result + summary stats
    """
    results = {}
    stats = {
        "flow_in": 0, "flow_out": 0, "flow_neutral": 0,
        "smart_money_conf": 0, "no_data": 0,
    }

    for sym in ctx.all_symbols:
        screener = ctx.get_screener(sym)
        board    = ctx.get_board(sym)
        r = analyze_symbol(screener, board)
        results[sym] = r

        if not r["has_foreign_data"] and not r["has_bp_data"]:
            stats["no_data"] += 1
        elif r["flow_direction"] == "in":  stats["flow_in"]      += 1
        elif r["flow_direction"] == "out": stats["flow_out"]      += 1
        else:                               stats["flow_neutral"]  += 1
        if r["smart_money_conf"]: stats["smart_money_conf"] += 1

    total = len(ctx.all_symbols)
    log.info("Institutional Flow — %d symbols:", total)
    log.info("  Flow IN : %d (%.1f%%) | OUT: %d | Neutral: %d | No data: %d",
             stats["flow_in"], stats["flow_in"]/max(total,1)*100,
             stats["flow_out"], stats["flow_neutral"], stats["no_data"])
    log.info("  Smart money confluence: %d symbols", stats["smart_money_conf"])

    return {"results": results, "stats": stats}


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    args = parser.parse_args()

    ctx = load_all()

    if args.symbol:
        sym = args.symbol.upper()
        r   = analyze_symbol(ctx.get_screener(sym), ctx.get_board(sym))
        print(f"\n{'═'*50}")
        print(f"  {sym} — Institutional Flow")
        print(f"{'═'*50}")
        for k, v in r.items():
            print(f"  {k:<22}: {v}")
    else:
        output = analyze_all(ctx)
        stats  = output["stats"]
        total  = len(ctx.all_symbols)

        print(f"\n{'═'*55}")
        print(f"  INSTITUTIONAL FLOW — {total} symbols")
        print(f"{'═'*55}")
        print(f"  Flow IN      : {stats['flow_in']:>4} ({stats['flow_in']/max(total,1)*100:.1f}%)")
        print(f"  Flow OUT     : {stats['flow_out']:>4}")
        print(f"  Neutral      : {stats['flow_neutral']:>4}")
        print(f"  Smart money  : {stats['smart_money_conf']:>4} (foreign + buy_pressure đồng thuận)")

        # Top smart money + flow in
        results = output["results"]
        top = [(sym, r) for sym, r in results.items()
               if r["smart_money_conf"] or r["flow_direction"] == "in"]
        top.sort(key=lambda x: x[1]["inst_flow_score"], reverse=True)

        print(f"\n  Top Institutional Flow IN:")
        print(f"  {'Symbol':<7} {'Score':>5} {'Dir':<8} {'Smart':>5} {'Net7d':>8} {'BP%':>6} {'Trend'}")
        print(f"  {'─'*55}")
        for sym, r in top[:15]:
            print(f"  {sym:<7} {r['inst_flow_score']:>5.1f} "
                  f"{r['flow_direction']:<8} "
                  f"{'✓' if r['smart_money_conf'] else ' ':>5} "
                  f"{(r['foreign_net_7d'] or 0):>+8.1f} "
                  f"{(r['buy_pressure_pct'] or 0):>6.1f} "
                  f"{r['flow_trend']}")
