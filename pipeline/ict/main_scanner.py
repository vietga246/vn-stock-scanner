"""
ict/main_scanner.py — ICT Pipeline Orchestrator

Chạy toàn bộ ICT pipeline theo thứ tự dependency và export kết quả.

Pipeline order:
  1. data_loader      → ICTDataContext
  2. market_regime    → regime + bull_weight
  3. sector_rotation  → RS ranks + symbol_sector_map
  4. market_structure → swing H/L, BOS, CHoCH per symbol
  5. institutional_flow → foreign flow + buy_pressure per symbol
  6. liquidity_sweep  → sweep + stop_hunt per symbol
  7. order_block      → OB detection per symbol
  8. accumulation     → vol patterns per symbol
  9. alpha_scoring    → final ICT score + quality grade

Output: ict_signals.json (export sang data/exports/)

Schema ict_signals.json:
  {
    "generated_at": "...",
    "regime": { regime, bull_weight, vnindex... },
    "sector_rotation": { leading, lagging, rotating_in... },
    "market_stats": { breadth, total_bullish_structure... },
    "signals": [              ← sorted by alpha_score desc
      {
        "symbol": "VCB",
        "alpha_score": 72.5,
        "ict_score": 68.3,
        "ict_rank": 1,
        "setup_quality": "A",
        "ict_confluence": 5,
        "actionable": true,
        "top_signals": [...],
        "signal_breakdown": {...},
        // Pass-through fields (từ screener)
        "composite_score", "industry", "tier",
        "rsi14", "adx14", "fvg_bull", "trend_strength",
        "price_change_1d", "price_change_5d",
        "foreign_net_7d",
        // ICT-specific
        "structure": "BULLISH",
        "bos_bull": false, "choch_bull": false,
        "ob_bull": false, "ob_price_at": false,
        "sweep_bull": false, "stop_hunt_bull": false,
        "accumulation_score": 62.0,
        "vol_spike": 1.8,
        "wyckoff_spring": false,
        "inst_flow_score": 71.0,
        "smart_money": false
      }
    ]
  }

Chạy:
  python pipeline/ict/main_scanner.py
  python pipeline/ict/main_scanner.py --quality A --top 30
"""

import os, sys, json, logging
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from pipeline.ict.data_loader       import load_all, ICTDataContext
from pipeline.ict.market_regime     import detect_regime
from pipeline.ict.sector_rotation   import analyze_sectors
from pipeline.ict.market_structure  import analyze_symbol as ms_sym
from pipeline.ict.institutional_flow import analyze_symbol as flow_sym
from pipeline.ict.liquidity_sweep   import analyze_symbol as sweep_sym
from pipeline.ict.order_block       import analyze_symbol as ob_sym
from pipeline.ict.accumulation      import analyze_symbol as acc_sym
from pipeline.ict.alpha_scoring     import score_symbol, classify_setup

EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")
OUT_FILE   = os.path.join(EXPORT_DIR, "ict_signals.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── MARKET STATS ─────────────────────────────────────────────────────────────

def _build_market_stats(ms_results: dict, acc_results: dict,
                        flow_results: dict) -> dict:
    """Tổng hợp market-wide stats từ tất cả symbols."""
    total = len(ms_results)
    if total == 0:
        return {}

    bullish = sum(1 for r in ms_results.values() if r.get("structure") == "BULLISH")
    bearish = sum(1 for r in ms_results.values() if r.get("structure") == "BEARISH")
    bos_bull = sum(1 for r in ms_results.values() if r.get("bos_bull"))
    bos_bear = sum(1 for r in ms_results.values() if r.get("bos_bear"))
    choch_bull = sum(1 for r in ms_results.values() if r.get("choch_bull"))

    acc_count = sum(1 for r in acc_results.values()
                    if r.get("accumulation_score", 0) >= 60)
    spring_count = sum(1 for r in acc_results.values() if r.get("wyckoff_spring"))

    flow_in = sum(1 for r in flow_results.values()
                  if r.get("flow_direction") == "in")
    smart_money = sum(1 for r in flow_results.values()
                      if r.get("smart_money_conf"))

    return {
        "total_symbols":      total,
        "bullish_structure":  bullish,
        "bearish_structure":  bearish,
        "bullish_pct":        round(bullish / total * 100, 1),
        "bos_bull":           bos_bull,
        "bos_bear":           bos_bear,
        "choch_bull":         choch_bull,
        "accumulating":       acc_count,
        "wyckoff_spring":     spring_count,
        "flow_in":            flow_in,
        "smart_money_conf":   smart_money,
    }


# ─── BUILD SIGNAL RECORD ──────────────────────────────────────────────────────

def _build_signal(sym: str, alpha_result: dict,
                  ms: dict, flow: dict, sweep: dict,
                  ob: dict, acc: dict) -> dict:
    """Merge tất cả module outputs thành 1 signal record."""
    r = dict(alpha_result)   # copy from alpha_scoring output

    # Thêm ICT-specific fields từ sub-modules
    r["structure"]       = ms.get("structure", "NEUTRAL")
    r["bos_bull"]        = ms.get("bos_bull", False)
    r["bos_bear"]        = ms.get("bos_bear", False)
    r["choch_bull"]      = ms.get("choch_bull", False)
    r["choch_bear"]      = ms.get("choch_bear", False)
    r["last_sh"]         = ms.get("last_sh")
    r["last_sl"]         = ms.get("last_sl")
    r["eq_high_count"]   = len(ms.get("eq_highs", []))
    r["eq_low_count"]    = len(ms.get("eq_lows", []))

    r["ob_bull"]         = ob.get("ob_bull", False)
    r["ob_bull_top"]     = ob.get("ob_bull_top")
    r["ob_bull_bottom"]  = ob.get("ob_bull_bottom")
    r["ob_price_at"]     = ob.get("price_at_ob", False)
    r["ob_mitigated"]    = ob.get("ob_bull_mitigated", True)

    r["sweep_bull"]      = sweep.get("sweep_bull", False)
    r["stop_hunt_bull"]  = sweep.get("stop_hunt_bull", False)
    r["sweep_price"]     = sweep.get("sweep_price")

    r["accumulation_score"] = acc.get("accumulation_score", 50.0)
    r["distribution_score"] = acc.get("distribution_score", 50.0)
    r["vol_spike"]       = acc.get("vol_spike", 1.0)
    r["vol_trend"]       = acc.get("vol_trend", "flat")
    r["wyckoff_spring"]  = acc.get("wyckoff_spring", False)
    r["nr7"]             = acc.get("nr7", False)
    r["breakout_imminent"] = acc.get("breakout_imminent", False)

    r["inst_flow_score"] = flow.get("inst_flow_score", 50.0)
    r["flow_direction"]  = flow.get("flow_direction", "neutral")
    r["smart_money"]     = flow.get("smart_money_conf", False)
    r["buy_pressure_pct"]= flow.get("buy_pressure_pct")
    r["flow_trend"]      = flow.get("flow_trend", "steady")

    return r


# ─── MAIN SCANNER ─────────────────────────────────────────────────────────────

def run_scanner(export_dir: str = None) -> dict:
    """
    Chạy full ICT pipeline và export ict_signals.json.

    Returns:
        output dict (same as written to JSON)
    """
    global EXPORT_DIR, OUT_FILE
    if export_dir:
        EXPORT_DIR = export_dir
        OUT_FILE   = os.path.join(EXPORT_DIR, "ict_signals.json")

    t0 = datetime.now()
    log.info("═" * 60)
    log.info("  ICT Main Scanner — starting")
    log.info("  EXPORT_DIR: %s", EXPORT_DIR)
    log.info("═" * 60)

    # ── Step 1: Load data ────────────────────────────────────────
    ctx = load_all(EXPORT_DIR)
    symbols = ctx.all_symbols
    log.info("Step 1 done — %d symbols loaded", len(symbols))

    # ── Step 2: Market Regime ────────────────────────────────────
    regime = detect_regime(ctx)
    log.info("Step 2 done — Regime: %s (bull_weight=%.1f)",
             regime["regime"], regime["bull_weight"])

    # ── Step 3: Sector Rotation ──────────────────────────────────
    sec_result  = analyze_sectors(ctx)
    sector_map  = sec_result.get("symbol_sector_map", {})
    log.info("Step 3 done — %d sectors, leading: %s",
             sec_result.get("total_sectors", 0),
             ", ".join(sec_result.get("leading", [])[:3]))

    # ── Steps 4-8: Per-symbol analysis ──────────────────────────
    log.info("Steps 4-8: running per-symbol analysis (%d symbols)...",
             len(symbols))

    ms_results   = {}
    flow_results = {}
    sweep_results= {}
    ob_results   = {}
    acc_results  = {}

    for sym in symbols:
        prices   = ctx.get_prices(sym)
        screener = ctx.get_screener(sym)
        board    = ctx.get_board(sym)

        ms_results[sym]    = ms_sym(prices)
        flow_results[sym]  = flow_sym(screener, board)
        sweep_results[sym] = sweep_sym(prices)
        ob_results[sym]    = ob_sym(prices)
        acc_results[sym]   = acc_sym(prices)

    log.info("Steps 4-8 done")

    # ── Step 9: Alpha Scoring ────────────────────────────────────
    log.info("Step 9: alpha scoring...")

    all_signals = []
    quality_stats = {"A+": 0, "A": 0, "B": 0, "C": 0, "SKIP": 0}

    for sym in symbols:
        try:
            alpha = score_symbol(sym, ctx, regime, sector_map)
            signal = _build_signal(
                sym, alpha,
                ms_results[sym],
                flow_results[sym],
                sweep_results[sym],
                ob_results[sym],
                acc_results[sym],
            )
            all_signals.append(signal)
            q = signal.get("setup_quality", "SKIP")
            quality_stats[q] = quality_stats.get(q, 0) + 1
        except Exception as e:
            log.debug("Error scoring %s: %s", sym, e)

    # Sort by alpha_score desc, add rank
    all_signals.sort(key=lambda x: x.get("alpha_score", 0), reverse=True)
    for i, s in enumerate(all_signals, 1):
        s["ict_rank"] = i

    log.info("Step 9 done — A+:%d A:%d B:%d C:%d SKIP:%d",
             quality_stats["A+"], quality_stats["A"],
             quality_stats["B"], quality_stats["C"], quality_stats["SKIP"])

    # ── Build output ──────────────────────────────────────────────
    market_stats = _build_market_stats(ms_results, acc_results, flow_results)
    elapsed = (datetime.now() - t0).total_seconds()

    output = {
        "generated_at":    datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "total_symbols":   len(all_signals),
        "actionable_count": quality_stats["A+"] + quality_stats["A"],
        "regime":          regime,
        "sector_rotation": {
            "leading":           sec_result.get("leading", []),
            "lagging":           sec_result.get("lagging", []),
            "rotating_in":       sec_result.get("rotating_in", []),
            "rotating_out":      sec_result.get("rotating_out", []),
            "accumulating":      sec_result.get("accumulating", []),
            "distributing":      sec_result.get("distributing", []),
            "hot_sectors":       sec_result.get("hot_sectors", []),
            "breakout_candidate":sec_result.get("breakout_candidate", []),
        },
        "market_stats":    market_stats,
        "quality_distribution": quality_stats,
        "signals":         all_signals,
    }

    # ── Export JSON ───────────────────────────────────────────────
    os.makedirs(EXPORT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    file_kb = os.path.getsize(OUT_FILE) / 1024
    log.info("═" * 60)
    log.info("  ✅ ICT Scanner done in %.1fs", elapsed)
    log.info("  Exported %d signals → %s (%.1f KB)",
             len(all_signals), OUT_FILE, file_kb)
    log.info("  Actionable (A/A+): %d symbols",
             quality_stats["A+"] + quality_stats["A"])
    log.info("═" * 60)

    return output


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top",     type=int, default=20)
    parser.add_argument("--quality", default=None, help="A+, A, B, C")
    parser.add_argument("--export-dir", default=None)
    args = parser.parse_args()

    result = run_scanner(args.export_dir)

    signals = result["signals"]
    regime  = result["regime"]
    stats   = result["quality_distribution"]
    mkt     = result["market_stats"]
    sec     = result["sector_rotation"]

    # Filter
    if args.quality:
        signals = [s for s in signals if s.get("setup_quality") == args.quality]

    print(f"\n{'═'*65}")
    print(f"  ICT SCANNER RESULTS")
    print(f"{'═'*65}")
    print(f"  Market Regime : {regime['regime']} (strength={regime['regime_strength']:.0f})")
    print(f"  Bull Weight   : {regime['bull_weight']}  "
          f"VNINDEX: {regime.get('vnindex')} | 5d: {regime.get('vnindex_change_5d')}%")
    print(f"  Breadth       : {regime.get('breadth_advance_pct')}% advance")
    print()
    print(f"  Market Structure:")
    print(f"    Bullish: {mkt.get('bullish_structure',0)} ({mkt.get('bullish_pct',0):.1f}%)")
    print(f"    BOS bull: {mkt.get('bos_bull',0)} | CHoCH bull: {mkt.get('choch_bull',0)}")
    print(f"    Accumulating: {mkt.get('accumulating',0)} | Spring: {mkt.get('wyckoff_spring',0)}")
    print(f"    Smart Money: {mkt.get('smart_money_conf',0)} symbols")
    print()
    print(f"  Quality: A+={stats['A+']} A={stats['A']} B={stats['B']} "
          f"C={stats['C']} SKIP={stats['SKIP']}")
    print(f"  Actionable: {result['actionable_count']}")
    print()
    print(f"  Sector Leaders : {', '.join(sec.get('leading',[])[:4])}")
    print(f"  Accumulating   : {', '.join(sec.get('accumulating',[])[:3])}")
    print()
    print(f"  {'#':<4} {'Sym':<6} {'Alpha':>6} {'ICT':>6} {'Q':<4} "
          f"{'Conf':>4} {'Structure':<10} {'Signals'[:25]}")
    print(f"  {'─'*63}")

    for s in signals[:args.top]:
        top_sig = s.get("top_signals", [""])
        first_sig = top_sig[0][:25] if top_sig else ""
        print(f"  #{s['ict_rank']:<3} {s['symbol']:<6} "
              f"{s.get('alpha_score',0):>6.1f} "
              f"{s.get('ict_score',0):>6.1f} "
              f"{s.get('setup_quality','?'):<4} "
              f"{s.get('ict_confluence',0):>4} "
              f"{s.get('structure','?'):<10} "
              f"{first_sig}")
