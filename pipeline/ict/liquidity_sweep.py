"""
ict/liquidity_sweep.py — Liquidity Sweep Detector

Detect các sự kiện giá "quét thanh khoản" (liquidity sweep):
  - Sweep trên Equal High → giá vượt EqH nhưng đóng cửa bên dưới
  - Sweep dưới Equal Low  → giá xuyên qua EqL nhưng đóng cửa bên trên
  - Stop Hunt: giá phá vỡ swing H/L rồi quay đầu trong cùng phiên

ICT framework: liquidity sweep = smart money thu thập lệnh stop-loss
của retail trước khi đi theo hướng ngược lại.

Output per symbol (dict):
  sweep_bull       : bool — vừa sweep dưới EqL rồi đóng trên (bullish setup)
  sweep_bear       : bool — vừa sweep trên EqH rồi đóng dưới (bearish setup)
  stop_hunt_bull   : bool — stop hunt dưới swing low, close recover
  stop_hunt_bear   : bool — stop hunt trên swing high, close reject
  sweep_price      : float — mức giá bị sweep
  sweep_age        : int — cách bar hiện tại bao nhiêu bars
  sweep_quality    : "HIGH"|"MEDIUM"|"LOW"
  signal_count     : int

Yêu cầu: ≥ 5 bars. Tốt nhất với ≥ 20 bars.

Chạy độc lập:
  python -m pipeline.ict.liquidity_sweep --symbol VCB
"""

import os, sys, logging
from typing import Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all
from pipeline.ict.market_structure import detect_swings, detect_equal_hl

log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

MIN_BARS        = 5       # tối thiểu để detect
EQ_TOLERANCE    = 0.003   # ±0.3% cho equal levels
SWEEP_LOOKBACK  = 5       # tìm sweep trong 5 bars gần nhất
RECOVER_THRESH  = 0.002   # cần close lại ≥ 0.2% so với swept level để confirm


# ─── CORE DETECTION ──────────────────────────────────────────────────────────

def _detect_sweep_of_eql(highs: np.ndarray, lows: np.ndarray,
                          closes: np.ndarray, eq_lows: list,
                          eq_highs: list) -> dict:
    """
    Detect sweep of equal highs/lows.

    Bullish sweep: bar i xuyên xuống dưới EqL (low < eq_level)
                   nhưng close[i] > eq_level (recover)
    Bearish sweep: bar i xuyên lên trên EqH (high > eq_level)
                   nhưng close[i] < eq_level (reject)
    """
    n = len(closes)
    result = {
        "sweep_bull": False, "sweep_bear": False,
        "sweep_price": None, "sweep_age": None,
    }

    if n < MIN_BARS:
        return result

    lookback_start = max(0, n - SWEEP_LOOKBACK)

    # Bullish sweep: sweep below Equal Low
    for ref_idx, eq_price in eq_lows:
        for i in range(lookback_start, n):
            if lows[i] < eq_price * (1 - EQ_TOLERANCE):  # xuyên xuống
                if closes[i] > eq_price:                   # nhưng close recover
                    age = n - 1 - i
                    if age < SWEEP_LOOKBACK:
                        result["sweep_bull"]  = True
                        result["sweep_price"] = float(eq_price)
                        result["sweep_age"]   = age
                        break
        if result["sweep_bull"]:
            break

    # Bearish sweep: sweep above Equal High
    for ref_idx, eq_price in eq_highs:
        for i in range(lookback_start, n):
            if highs[i] > eq_price * (1 + EQ_TOLERANCE):  # xuyên lên
                if closes[i] < eq_price:                    # nhưng close reject
                    age = n - 1 - i
                    if age < SWEEP_LOOKBACK:
                        result["sweep_bear"]  = True
                        result["sweep_price"] = float(eq_price)
                        result["sweep_age"]   = age
                        break
        if result["sweep_bear"]:
            break

    return result


def _detect_stop_hunt(highs: np.ndarray, lows: np.ndarray,
                      closes: np.ndarray,
                      swing_highs: list, swing_lows: list) -> dict:
    """
    Stop Hunt: giá phá vỡ swing level rồi đóng cửa ngược lại trong cùng ngày.

    Bull stop hunt: low[i] < last_swing_low nhưng close[i] > last_swing_low
    Bear stop hunt: high[i] > last_swing_high nhưng close[i] < last_swing_high
    """
    n = len(closes)
    result = {"stop_hunt_bull": False, "stop_hunt_bear": False,
              "stop_hunt_level": None}

    if n < MIN_BARS or (not swing_highs and not swing_lows):
        return result

    lookback_start = max(0, n - SWEEP_LOOKBACK)

    # Bull stop hunt
    if swing_lows:
        last_sl = swing_lows[-1][1]
        for i in range(lookback_start, n):
            if lows[i] < last_sl and closes[i] > last_sl:
                result["stop_hunt_bull"]  = True
                result["stop_hunt_level"] = float(last_sl)
                break

    # Bear stop hunt
    if swing_highs:
        last_sh = swing_highs[-1][1]
        for i in range(lookback_start, n):
            if highs[i] > last_sh and closes[i] < last_sh:
                result["stop_hunt_bear"]  = True
                result["stop_hunt_level"] = float(last_sh)
                break

    return result


def _sweep_quality(n_bars: int, sweep_age: Optional[int]) -> str:
    """Quality dựa trên data depth và freshness của sweep."""
    if n_bars >= 50 and sweep_age is not None and sweep_age <= 2:
        return "HIGH"
    elif n_bars >= 20 and sweep_age is not None and sweep_age <= 3:
        return "MEDIUM"
    return "LOW"


# ─── ANALYZE SINGLE SYMBOL ───────────────────────────────────────────────────

def analyze_symbol(prices_df: pd.DataFrame) -> dict:
    """
    Detect liquidity sweeps cho 1 symbol.

    Args:
        prices_df: DataFrame OHLCV sorted asc
    """
    empty = {
        "sweep_bull": False, "sweep_bear": False,
        "stop_hunt_bull": False, "stop_hunt_bear": False,
        "sweep_price": None, "sweep_age": None,
        "stop_hunt_level": None,
        "sweep_quality": "INSUFFICIENT_DATA",
        "signal_count": 0, "bar_count": 0,
    }

    if prices_df.empty or len(prices_df) < MIN_BARS:
        return empty

    df  = prices_df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    n   = len(df)
    if n < MIN_BARS:
        return empty

    hi  = df["high"].values.astype(float)
    lo  = df["low"].values.astype(float)
    cls = df["close"].values.astype(float)

    # Cần swing points và equal levels từ market_structure
    N = min(3, n // 3)  # adaptive lookback
    swing_highs, swing_lows = detect_swings(hi, lo, max(N, 2))
    eq_highs, eq_lows = detect_equal_hl(hi, lo)

    # Detect sweeps
    sweep_res     = _detect_sweep_of_eql(hi, lo, cls, eq_lows, eq_highs)
    stop_hunt_res = _detect_stop_hunt(hi, lo, cls, swing_highs, swing_lows)

    # Combine
    any_bull = sweep_res["sweep_bull"] or stop_hunt_res["stop_hunt_bull"]
    any_bear = sweep_res["sweep_bear"] or stop_hunt_res["stop_hunt_bear"]

    sweep_age  = sweep_res.get("sweep_age")
    sweep_price = sweep_res.get("sweep_price") or stop_hunt_res.get("stop_hunt_level")

    quality = _sweep_quality(n, sweep_age)

    sig = 0
    if sweep_res["sweep_bull"]:       sig += 2  # sweep of EqL = high quality
    if sweep_res["sweep_bear"]:       sig += 2
    if stop_hunt_res["stop_hunt_bull"]: sig += 1
    if stop_hunt_res["stop_hunt_bear"]: sig += 1

    return {
        "sweep_bull":      sweep_res["sweep_bull"],
        "sweep_bear":      sweep_res["sweep_bear"],
        "stop_hunt_bull":  stop_hunt_res["stop_hunt_bull"],
        "stop_hunt_bear":  stop_hunt_res["stop_hunt_bear"],
        "sweep_price":     sweep_price,
        "sweep_age":       sweep_age,
        "stop_hunt_level": stop_hunt_res.get("stop_hunt_level"),
        "eq_high_count":   len(eq_highs),
        "eq_low_count":    len(eq_lows),
        "sweep_quality":   quality,
        "signal_count":    sig,
        "bar_count":       n,
    }


# ─── BATCH ───────────────────────────────────────────────────────────────────

def analyze_all(ctx: ICTDataContext) -> dict:
    """Chạy liquidity sweep analysis cho tất cả symbols."""
    results = {}
    stats = {
        "sweep_bull": 0, "sweep_bear": 0,
        "stop_hunt_bull": 0, "stop_hunt_bear": 0,
        "insufficient": 0,
    }

    for sym in ctx.all_symbols:
        prices = ctx.get_prices(sym)
        r = analyze_symbol(prices)
        results[sym] = r

        if r["sweep_quality"] == "INSUFFICIENT_DATA": stats["insufficient"] += 1
        if r["sweep_bull"]:      stats["sweep_bull"]      += 1
        if r["sweep_bear"]:      stats["sweep_bear"]      += 1
        if r["stop_hunt_bull"]:  stats["stop_hunt_bull"]  += 1
        if r["stop_hunt_bear"]:  stats["stop_hunt_bear"]  += 1

    total = len(ctx.all_symbols)
    log.info("Liquidity Sweep — %d symbols: bull_sweep=%d, bear_sweep=%d, "
             "stop_hunt_bull=%d, stop_hunt_bear=%d, insufficient=%d",
             total, stats["sweep_bull"], stats["sweep_bear"],
             stats["stop_hunt_bull"], stats["stop_hunt_bear"], stats["insufficient"])

    return {"results": results, "stats": stats}


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    args = parser.parse_args()

    ctx = load_all()

    if args.symbol:
        sym = args.symbol.upper()
        r   = analyze_symbol(ctx.get_prices(sym))
        print(f"\n{'═'*45}")
        print(f"  {sym} — Liquidity Sweep")
        print(f"{'═'*45}")
        for k, v in r.items():
            print(f"  {k:<22}: {v}")
    else:
        out   = analyze_all(ctx)
        stats = out["stats"]
        total = len(ctx.all_symbols)

        print(f"\n{'═'*50}")
        print(f"  LIQUIDITY SWEEP — {total} symbols")
        print(f"{'═'*50}")
        print(f"  Sweep bull    : {stats['sweep_bull']:>4}")
        print(f"  Sweep bear    : {stats['sweep_bear']:>4}")
        print(f"  Stop hunt bull: {stats['stop_hunt_bull']:>4}")
        print(f"  Stop hunt bear: {stats['stop_hunt_bear']:>4}")

        results = out["results"]
        top = [(s, r) for s, r in results.items()
               if r["sweep_bull"] or r["stop_hunt_bull"]]
        top.sort(key=lambda x: x[1]["signal_count"], reverse=True)
        if top:
            print(f"\n  Top Bullish Sweep/Hunt signals:")
            print(f"  {'Sym':<6} {'SwBull':>6} {'Hunt':>6} {'Age':>4} {'Price':>8} {'Quality'}")
            for sym, r in top[:15]:
                scr = ctx.get_screener(sym)
                print(f"  {sym:<6} {'✓' if r['sweep_bull'] else '-':>6} "
                      f"{'✓' if r['stop_hunt_bull'] else '-':>6} "
                      f"{(r['sweep_age'] or '-'):>4} "
                      f"{(r['sweep_price'] or 0):>8.2f} "
                      f"{r['sweep_quality']}")
