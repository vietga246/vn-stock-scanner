"""
ict/alpha_scoring.py — ICT Alpha Scoring Engine

Tổng hợp tất cả signals từ các ICT modules thành:
  1. ICT Signal Score (0-100): độ mạnh của setup theo ICT framework
  2. ICT Confluence Count: số signals đồng thuận
  3. Trade Setup Quality: "A+" / "A" / "B" / "C" / "SKIP"
  4. Final Alpha Score: kết hợp ICT score + existing composite_score

Signal Weights (từ ICT_Indicator_Analysis_from_Claude.docx):
  Tier 1 Foundation (45%):
    Market Structure (BULLISH + BOS)  : 20%
    BOS / CHoCH                       : 15%
    Market Regime (bull_weight filter): 10%

  Tier 2 Confluence (34%):
    Fair Value Gap (fvg_bull + quality): 12%
    Order Block (unmitigated + price_at): 12%
    Liquidity Sweep (bull setup)        : 10%

  Tier 3 Confirmation (21%):
    Volume Spike / Accumulation         :  8%
    Relative Strength vs Sector         :  7%
    Institutional Flow (foreign + BP)   :  3%
    Trend Strength (ADX + trend_score)  :  3%

Global Filter:
  bull_weight từ market_regime nhân với toàn bộ score
  BEAR market → score tối đa ~30, chỉ long A+ setups

Output per symbol (dict):
  ict_score        : 0-100
  ict_confluence   : int (số signals 0-10+)
  setup_quality    : "A+" | "A" | "B" | "C" | "SKIP"
  alpha_score      : final score = weighted(ict_score, composite_score)
  signal_breakdown : dict chi tiết từng component
  top_signals      : list string mô tả signals chính
  actionable       : bool — đáng watch (quality A hoặc A+)

Chạy độc lập:
  python -m pipeline.ict.alpha_scoring
  python -m pipeline.ict.alpha_scoring --top 20
"""

import os, sys, logging
from typing import Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from pipeline.ict.data_loader      import ICTDataContext, load_all
from pipeline.ict.market_regime    import detect_regime
from pipeline.ict.sector_rotation  import analyze_sectors
from pipeline.ict.market_structure import analyze_symbol as ms_analyze
from pipeline.ict.institutional_flow import analyze_symbol as flow_analyze
from pipeline.ict.liquidity_sweep  import analyze_symbol as sweep_analyze
from pipeline.ict.order_block      import analyze_symbol as ob_analyze
from pipeline.ict.accumulation     import analyze_symbol as acc_analyze

log = logging.getLogger(__name__)

# ─── WEIGHTS ─────────────────────────────────────────────────────────────────

W = {
    # Tier 1 Foundation (45%)
    "market_structure": 0.20,
    "bos_choch":        0.15,
    "regime_filter":    0.10,
    # Tier 2 Confluence (34%)
    "fvg":              0.12,
    "order_block":      0.12,
    "liq_sweep":        0.10,
    # Tier 3 Confirmation (21%)
    "volume_acc":       0.08,
    "rs_sector":        0.07,
    "inst_flow":        0.03,
    "trend_strength":   0.03,
}

# Final alpha = ICT × ICT_WEIGHT + composite × COMP_WEIGHT
ICT_WEIGHT  = 0.45
COMP_WEIGHT = 0.55


# ─── COMPONENT SCORERS ───────────────────────────────────────────────────────

def _score_market_structure(ms: dict, bull_weight: float) -> tuple:
    """Score từ market_structure result. Returns (score 0-100, signals list)."""
    score   = 50.0
    signals = []

    struct = ms.get("structure", "NEUTRAL")
    if struct == "BULLISH":
        score += 30; signals.append("Bullish structure (HH+HL)")
    elif struct == "BEARISH":
        score -= 20

    if ms.get("bos_bull"):
        score += 20; signals.append("BOS bullish")
    if ms.get("choch_bull"):
        score += 25; signals.append("CHoCH bullish (reversal)")
    if ms.get("bos_bear"):
        score -= 15
    if ms.get("choch_bear"):
        score -= 20; signals.append("CHoCH bearish ⚠️")

    # Equal H/L pools
    if ms.get("eq_lows") and len(ms.get("eq_lows", [])) >= 2:
        signals.append("Equal Low pools (liquidity below)")
    if ms.get("eq_highs") and len(ms.get("eq_highs", [])) >= 2:
        signals.append("Equal High pools (liquidity above)")

    return float(np.clip(score * bull_weight + 50 * (1 - bull_weight), 0, 100)), signals


def _score_fvg(screener: dict, bull_weight: float) -> tuple:
    """Score từ FVG data trong screener."""
    score   = 50.0
    signals = []

    fvg_bull = screener.get("fvg_bull")
    fvg_bear = screener.get("fvg_bear")
    fvg_bull_size = screener.get("fvg_bull_size") or 0
    fvg_bull_age  = screener.get("fvg_bull_age")
    fvg_bull_fill = screener.get("fvg_bull_fill") or 100

    if fvg_bull:
        # Quality: size lớn + trẻ + chưa bị fill nhiều
        quality = 0
        if fvg_bull_size and fvg_bull_size >= 1.0: quality += 1
        if fvg_bull_age  is not None and fvg_bull_age <= 3: quality += 1
        if fvg_bull_fill <= 30: quality += 1

        if   quality == 3: score += 35; signals.append(f"FVG bull HIGH (size={fvg_bull_size:.1f}%, age={fvg_bull_age})")
        elif quality == 2: score += 22; signals.append(f"FVG bull MEDIUM")
        else:              score += 10; signals.append("FVG bull LOW")

    if fvg_bear:
        score -= 10  # bearish FVG = overhead resistance

    return float(np.clip(score * bull_weight + 50 * (1 - bull_weight), 0, 100)), signals


def _score_order_block(ob: dict, bull_weight: float) -> tuple:
    """Score từ order block result."""
    score   = 50.0
    signals = []

    if ob.get("ob_bull") and not ob.get("ob_bull_mitigated"):
        score += 25; signals.append(f"Bullish OB unmitigated (age={ob.get('ob_bull_age')})")
        if ob.get("price_at_ob"):
            score += 20; signals.append("Price AT bullish OB → entry zone! 🎯")

    if ob.get("ob_bear") and not ob.get("ob_bear_mitigated"):
        score -= 10; signals.append("Bearish OB above (resistance)")

    return float(np.clip(score * bull_weight + 50 * (1 - bull_weight), 0, 100)), signals


def _score_liquidity_sweep(sweep: dict, bull_weight: float) -> tuple:
    """Score từ liquidity sweep result."""
    score   = 50.0
    signals = []

    if sweep.get("sweep_bull"):
        score += 30; signals.append(f"Bullish sweep of EqL (age={sweep.get('sweep_age')})")
    if sweep.get("stop_hunt_bull"):
        score += 20; signals.append("Stop hunt bull (retail stops cleared)")
    if sweep.get("sweep_bear"):
        score -= 20; signals.append("Bearish sweep of EqH ⚠️")
    if sweep.get("stop_hunt_bear"):
        score -= 15

    return float(np.clip(score * bull_weight + 50 * (1 - bull_weight), 0, 100)), signals


def _score_volume_acc(acc: dict) -> tuple:
    """Score từ accumulation result."""
    signals = []
    score   = acc.get("accumulation_score", 50.0)

    if acc.get("wyckoff_spring"):
        signals.append("Wyckoff Spring detected! 💧")
    if acc.get("breakout_imminent"):
        signals.append("NR7 + vol compression → breakout imminent")
    if acc.get("vol_spike", 1) >= 2.5:
        signals.append(f"Vol spike {acc.get('vol_spike',0):.1f}x")

    return score, signals


def _score_rs_sector(screener: dict, sector_map: dict, sym: str) -> tuple:
    """
    Relative Strength vs Sector.
    RS = price_change_5d của stock − avg_price_5d của sector.
    """
    score   = 50.0
    signals = []

    price_5d = screener.get("price_change_5d")
    sec_info = sector_map.get(sym, {})
    sec_5d   = sec_info.get("sector_avg_5d")

    if price_5d is not None and sec_5d is not None:
        rs = float(price_5d) - float(sec_5d)
        if   rs >=  5: score += 30; signals.append(f"RS vs sector: +{rs:.1f}%")
        elif rs >=  2: score += 18; signals.append(f"RS vs sector: +{rs:.1f}%")
        elif rs >=  0: score += 8
        elif rs >= -2: score -= 5
        elif rs >= -5: score -= 15
        else:          score -= 25; signals.append(f"RS vs sector: {rs:.1f}% ⚠️")

    # Sector RS rank
    sec_rank = sec_info.get("sector_rs_rank")
    if sec_rank is not None:
        if   sec_rank <= 5:  score += 15; signals.append(f"Sector rank #{sec_rank} (leader)")
        elif sec_rank <= 10: score += 8
        elif sec_rank >= 20: score -= 10; signals.append(f"Sector rank #{sec_rank} (laggard)")

    return float(np.clip(score, 0, 100)), signals


def _score_inst_flow(flow: dict, bull_weight: float) -> tuple:
    """Score từ institutional flow."""
    signals = []
    score   = flow.get("inst_flow_score", 50.0)
    if flow.get("smart_money_conf"):
        signals.append("Smart money confluence (foreign + buy pressure)")
    if flow.get("flow_trend") == "accelerating" and flow.get("flow_direction") == "in":
        signals.append("Foreign flow accelerating")
    return float(np.clip(score * bull_weight + 50 * (1 - bull_weight), 0, 100)), signals


def _score_trend_strength(screener: dict) -> tuple:
    """Score từ ADX + trend_strength trong screener."""
    signals = []
    adx14    = screener.get("adx14")
    trend_s  = screener.get("trend_strength")
    rsi14    = screener.get("rsi14")

    if adx14 is None and trend_s is None:
        return 50.0, signals

    score = 50.0
    if adx14 is not None:
        if   adx14 >= 30: score += 20; signals.append(f"ADX={adx14:.0f} (strong trend)")
        elif adx14 >= 20: score += 10
        elif adx14 <  15: score -= 10  # no trend, choppy

    if trend_s is not None:
        score += (float(trend_s) - 50) * 0.3  # trend_strength 0-100 → ±15pts

    if rsi14 is not None:
        rsi = float(rsi14)
        if   40 <= rsi <= 60: pass          # neutral
        elif 60 <  rsi <= 75: score += 8    # bullish momentum, not overbought
        elif rsi > 75:        score -= 5    # overbought
        elif 25 <= rsi < 40:  score -= 5    # bearish momentum
        elif rsi < 25:        score -= 10   # oversold

    return float(np.clip(score, 0, 100)), signals


# ─── QUALITY CLASSIFIER ──────────────────────────────────────────────────────

def classify_setup(ict_score: float, confluence: int,
                   bull_weight: float) -> str:
    """
    A+ : ict_score ≥ 75 + confluence ≥ 4 + bull_weight ≥ 0.7
    A  : ict_score ≥ 65 + confluence ≥ 3
    B  : ict_score ≥ 55 + confluence ≥ 2
    C  : ict_score ≥ 45
    SKIP: ict_score < 45 hoặc BEAR market với score < 60
    """
    if bull_weight <= 0.3 and ict_score < 70:  # BEAR market filter
        return "SKIP"
    if ict_score >= 75 and confluence >= 4 and bull_weight >= 0.7:
        return "A+"
    if ict_score >= 65 and confluence >= 3:
        return "A"
    if ict_score >= 55 and confluence >= 2:
        return "B"
    if ict_score >= 45:
        return "C"
    return "SKIP"


# ─── MAIN SCORE FUNCTION ─────────────────────────────────────────────────────

def score_symbol(sym: str, ctx: ICTDataContext,
                 regime: dict, sector_map: dict) -> dict:
    """
    Tính full ICT alpha score cho 1 symbol.
    Gọi tất cả sub-modules và aggregate.
    """
    prices   = ctx.get_prices(sym)
    screener = ctx.get_screener(sym)
    board    = ctx.get_board(sym)
    bull_w   = regime.get("bull_weight", 0.5)

    # Run all modules
    ms     = ms_analyze(prices)
    flow   = flow_analyze(screener, board)
    sweep  = sweep_analyze(prices)
    ob     = ob_analyze(prices)
    acc    = acc_analyze(prices)

    # Score each component
    ms_score,   ms_sigs   = _score_market_structure(ms, bull_w)
    fvg_score,  fvg_sigs  = _score_fvg(screener, bull_w)
    ob_score,   ob_sigs   = _score_order_block(ob, bull_w)
    sw_score,   sw_sigs   = _score_liquidity_sweep(sweep, bull_w)
    acc_score_, acc_sigs  = _score_volume_acc(acc)
    rs_score,   rs_sigs   = _score_rs_sector(screener, sector_map, sym)
    fl_score,   fl_sigs   = _score_inst_flow(flow, bull_w)
    tr_score,   tr_sigs   = _score_trend_strength(screener)

    # BOS/CHoCH component (subset of market structure)
    bos_score = 50.0
    if ms.get("bos_bull"):   bos_score = 80
    if ms.get("choch_bull"): bos_score = 90
    if ms.get("bos_bear"):   bos_score = 30
    if ms.get("choch_bear"): bos_score = 20

    # Regime filter component
    regime_score = bull_w * 100  # 30/50/70/100

    # Weighted ICT score
    ict_score = (
        ms_score    * W["market_structure"] +
        bos_score   * W["bos_choch"]        +
        regime_score* W["regime_filter"]    +
        fvg_score   * W["fvg"]              +
        ob_score    * W["order_block"]      +
        sw_score    * W["liq_sweep"]        +
        acc_score_  * W["volume_acc"]       +
        rs_score    * W["rs_sector"]        +
        fl_score    * W["inst_flow"]        +
        tr_score    * W["trend_strength"]
    )
    ict_score = float(np.clip(ict_score, 0, 100))

    # Confluence count
    sigs = ms_sigs + fvg_sigs + ob_sigs + sw_sigs + acc_sigs + rs_sigs + fl_sigs + tr_sigs
    bull_sigs = [s for s in sigs if "⚠️" not in s]
    confluence = len(bull_sigs)

    # Setup quality
    quality = classify_setup(ict_score, confluence, bull_w)

    # Final alpha score: blend ICT với existing composite
    comp_score = screener.get("composite_score") or 50.0
    alpha_score = ict_score * ICT_WEIGHT + float(comp_score) * COMP_WEIGHT
    alpha_score = float(np.clip(alpha_score, 0, 100))

    return {
        "symbol":       sym,
        "ict_score":    round(ict_score, 1),
        "ict_confluence": confluence,
        "setup_quality": quality,
        "alpha_score":  round(alpha_score, 1),
        "composite_score": comp_score,
        "bull_weight":  bull_w,
        "actionable":   quality in ("A+", "A"),
        "signal_breakdown": {
            "market_structure": round(ms_score, 1),
            "bos_choch":        round(bos_score, 1),
            "regime":           round(regime_score, 1),
            "fvg":              round(fvg_score, 1),
            "order_block":      round(ob_score, 1),
            "liq_sweep":        round(sw_score, 1),
            "volume_acc":       round(acc_score_, 1),
            "rs_sector":        round(rs_score, 1),
            "inst_flow":        round(fl_score, 1),
            "trend_strength":   round(tr_score, 1),
        },
        "top_signals":   sigs[:6],  # top 6 signals
        # Pass-through context
        "industry":      screener.get("industry", ""),
        "tier":          screener.get("tier", ""),
        "rsi14":         screener.get("rsi14"),
        "adx14":         screener.get("adx14"),
        "fvg_bull":      screener.get("fvg_bull"),
        "trend_strength":screener.get("trend_strength"),
    }


# ─── BATCH SCORING ───────────────────────────────────────────────────────────

def score_all(ctx: ICTDataContext) -> dict:
    """
    Score tất cả symbols và trả về ranked list.

    Returns:
        dict với:
          scores    : list of score dicts, sorted by alpha_score desc
          regime    : market regime dict
          stats     : distribution của setup quality
    """
    regime     = detect_regime(ctx)
    sec_result = analyze_sectors(ctx)
    sector_map = sec_result.get("symbol_sector_map", {})

    log.info("Alpha Scoring — Market: %s (bull_weight=%.1f)",
             regime["regime"], regime["bull_weight"])

    scores = []
    stats  = {"A+": 0, "A": 0, "B": 0, "C": 0, "SKIP": 0}

    for sym in ctx.all_symbols:
        try:
            r = score_symbol(sym, ctx, regime, sector_map)
            scores.append(r)
            stats[r["setup_quality"]] = stats.get(r["setup_quality"], 0) + 1
        except Exception as e:
            log.debug("Error scoring %s: %s", sym, e)

    # Sort by alpha_score desc
    scores.sort(key=lambda x: x["alpha_score"], reverse=True)

    # Add rank
    for i, s in enumerate(scores, 1):
        s["ict_rank"] = i

    total = len(scores)
    log.info("Alpha Scoring done — %d symbols scored", total)
    log.info("  A+: %d | A: %d | B: %d | C: %d | SKIP: %d",
             stats["A+"], stats["A"], stats["B"], stats["C"], stats["SKIP"])
    log.info("  Actionable (A/A+): %d", stats["A+"] + stats["A"])

    return {"scores": scores, "regime": regime, "stats": stats,
            "sector_rotation": sec_result}


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--top",    type=int, default=20)
    parser.add_argument("--quality", default=None,
                        help="Filter by quality: A+, A, B, C")
    args = parser.parse_args()

    ctx = load_all()

    if args.symbol:
        sym    = args.symbol.upper()
        regime = detect_regime(ctx)
        sec    = analyze_sectors(ctx)
        r      = score_symbol(sym, ctx, regime, sec["symbol_sector_map"])

        print(f"\n{'═'*55}")
        print(f"  {sym} — ICT Alpha Score")
        print(f"{'═'*55}")
        print(f"  ICT Score      : {r['ict_score']}")
        print(f"  Confluence     : {r['ict_confluence']} signals")
        print(f"  Setup Quality  : {r['setup_quality']}")
        print(f"  Alpha Score    : {r['alpha_score']}")
        print(f"  Composite Score: {r['composite_score']}")
        print(f"  Bull Weight    : {r['bull_weight']}")
        print(f"\n  Signal Breakdown:")
        for k, v in r["signal_breakdown"].items():
            print(f"    {k:<20}: {v:.1f}")
        print(f"\n  Top Signals:")
        for sig in r["top_signals"]:
            print(f"    • {sig}")
    else:
        result = score_all(ctx)
        scores = result["scores"]
        regime = result["regime"]
        stats  = result["stats"]

        # Filter
        if args.quality:
            scores = [s for s in scores if s["setup_quality"] == args.quality]

        print(f"\n{'═'*65}")
        print(f"  ICT ALPHA SCORES — Top {args.top}")
        print(f"  Market: {regime['regime']} | Bull weight: {regime['bull_weight']}")
        print(f"  A+:{stats['A+']} A:{stats['A']} B:{stats['B']} C:{stats['C']} SKIP:{stats['SKIP']}")
        print(f"{'═'*65}")
        print(f"  {'#':<4} {'Sym':<6} {'Alpha':>6} {'ICT':>6} {'Conf':>5} {'Q':<4} "
              f"{'ADX':>5} {'FVG':>4} {'Industry'}")
        print(f"  {'─'*63}")

        for r in scores[:args.top]:
            print(f"  #{r['ict_rank']:<3} {r['symbol']:<6} "
                  f"{r['alpha_score']:>6.1f} "
                  f"{r['ict_score']:>6.1f} "
                  f"{r['ict_confluence']:>5} "
                  f"{r['setup_quality']:<4} "
                  f"{(r['adx14'] or 0):>5.0f} "
                  f"{'✓' if r['fvg_bull'] else '-':>4} "
                  f"{r['industry'][:20]}")
