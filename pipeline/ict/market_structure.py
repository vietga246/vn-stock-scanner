"""
ict/market_structure.py — Market Structure Analyzer

Phân tích cấu trúc thị trường theo ICT framework:
  1. Swing High / Swing Low detection (N-bar lookback)
  2. Market Structure: BULLISH (HH+HL) / BEARISH (LH+LL) / NEUTRAL
  3. Break of Structure (BOS): breakout theo hướng trend → continuation
  4. Change of Character (CHoCH): breakout ngược hướng → reversal
  5. Equal High / Equal Low (±0.3%): liquidity pools chưa bị sweep

Output per symbol (dict):
  structure       : "BULLISH" | "BEARISH" | "NEUTRAL"
  swing_highs     : list of (bar_idx, price)
  swing_lows      : list of (bar_idx, price)
  last_sh         : giá của swing high gần nhất
  last_sl         : giá của swing low gần nhất
  bos_bull        : bool — bullish BOS xảy ra ngày cuối
  bos_bear        : bool — bearish BOS
  choch_bull      : bool — CHoCH bullish (reversal signal)
  choch_bear      : bool — CHoCH bearish
  eq_highs        : list of (bar_idx, price) — equal highs (liquidity pools)
  eq_lows         : list of (bar_idx, price) — equal lows
  signal_count    : tổng số signals (BOS + CHoCH + EqH/L)
  quality         : "HIGH" | "MEDIUM" | "LOW" (dựa trên data depth)

Note về data depth:
  18 bars hiện tại → chỉ có 1-2 swing points → signal ít nhưng vẫn valid
  Sau Fix 1 (200 bars) → full accuracy

Chạy độc lập:
  python -m pipeline.ict.market_structure
  python -m pipeline.ict.market_structure --symbol VCB
"""

import os, sys, logging
from typing import Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all

log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

N_BAR_LOOKBACK  = 3      # Swing detection lookback (3=short-term)
EQ_TOLERANCE    = 0.003  # Equal H/L tolerance: ±0.3%
MIN_BARS_SWING  = 8      # Cần ≥8 bars cho swing detection đáng tin cậy
MIN_BARS_EQL    = 5      # Cần ≥5 bars cho Equal H/L


# ─── SWING DETECTION ─────────────────────────────────────────────────────────

def detect_swings(highs: np.ndarray, lows: np.ndarray,
                  n: int = N_BAR_LOOKBACK) -> tuple:
    """
    Detect swing highs và swing lows.

    Swing High[i]: high[i] > max(high[i-n:i]) AND high[i] > max(high[i+1:i+n+1])
    Swing Low[i] : low[i]  < min(low[i-n:i])  AND low[i]  < min(low[i+1:i+n+1])

    Returns:
        swing_highs: list of (idx, price)
        swing_lows : list of (idx, price)
    """
    length = len(highs)
    swing_highs = []
    swing_lows  = []

    for i in range(n, length - n):
        # Swing High
        left_h  = highs[max(0, i-n):i]
        right_h = highs[i+1:min(length, i+n+1)]
        if len(left_h) > 0 and len(right_h) > 0:
            if highs[i] > max(left_h) and highs[i] > max(right_h):
                swing_highs.append((i, float(highs[i])))

        # Swing Low
        left_l  = lows[max(0, i-n):i]
        right_l = lows[i+1:min(length, i+n+1)]
        if len(left_l) > 0 and len(right_l) > 0:
            if lows[i] < min(left_l) and lows[i] < min(right_l):
                swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


# ─── MARKET STRUCTURE ────────────────────────────────────────────────────────

def classify_structure(swing_highs: list, swing_lows: list) -> str:
    """
    BULLISH: Higher Highs + Higher Lows (HH + HL)
    BEARISH: Lower Highs + Lower Lows (LH + LL)
    NEUTRAL: mixed
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "NEUTRAL"

    # Lấy 2 swing gần nhất
    sh1, sh2 = swing_highs[-2][1], swing_highs[-1][1]
    sl1, sl2 = swing_lows[-2][1], swing_lows[-1][1]

    hh = sh2 > sh1   # Higher High
    hl = sl2 > sl1   # Higher Low
    lh = sh2 < sh1   # Lower High
    ll = sl2 < sl1   # Lower Low

    if hh and hl:  return "BULLISH"
    if lh and ll:  return "BEARISH"
    return "NEUTRAL"


# ─── BOS / CHoCH ─────────────────────────────────────────────────────────────

def detect_bos_choch(closes: np.ndarray, swing_highs: list, swing_lows: list,
                     structure: str) -> dict:
    """
    BOS  (Break of Structure): close phá vỡ swing level theo hướng trend → continuation
    CHoCH (Change of Character): close phá vỡ swing level ngược hướng → reversal

    Chỉ nhìn vào bar cuối cùng (close[-1]).
    """
    result = {
        "bos_bull":   False,
        "bos_bear":   False,
        "choch_bull": False,
        "choch_bear": False,
        "bos_level":  None,
        "choch_level":None,
    }

    if len(closes) < 2:
        return result

    last_close = float(closes[-1])

    # Lấy swing levels gần nhất
    last_sh = swing_highs[-1][1] if swing_highs else None
    last_sl = swing_lows[-1][1]  if swing_lows  else None

    if last_sh is None or last_sl is None:
        return result

    # BOS theo hướng structure
    if structure == "BULLISH":
        if last_close > last_sh:
            result["bos_bull"]  = True
            result["bos_level"] = last_sh
        elif last_close < last_sl:
            result["choch_bear"]   = True
            result["choch_level"]  = last_sl
    elif structure == "BEARISH":
        if last_close < last_sl:
            result["bos_bear"]  = True
            result["bos_level"] = last_sl
        elif last_close > last_sh:
            result["choch_bull"]  = True
            result["choch_level"] = last_sh
    else:  # NEUTRAL — treat either breakout as potential BOS
        if last_close > last_sh:
            result["bos_bull"]  = True
            result["bos_level"] = last_sh
        elif last_close < last_sl:
            result["bos_bear"]  = True
            result["bos_level"] = last_sl

    return result


# ─── EQUAL HIGH / LOW ────────────────────────────────────────────────────────

def detect_equal_hl(highs: np.ndarray, lows: np.ndarray,
                    tolerance: float = EQ_TOLERANCE) -> tuple:
    """
    Equal High/Low: các mức giá bằng nhau ±tolerance% = liquidity pools.
    Chỉ so sánh các bars gần đây (≤10 bars lookback).

    Returns:
        eq_highs: list of (idx, price)
        eq_lows : list of (idx, price)
    """
    n = len(highs)
    if n < 3:
        return [], []

    eq_highs = []
    eq_lows  = []
    lookback = min(10, n - 1)

    for i in range(n - lookback, n):
        for j in range(i + 1, n):
            hi, hj = float(highs[i]), float(highs[j])
            if hj > 0 and abs(hi - hj) / hj < tolerance:
                eq_highs.append((j, hj))
            li, lj = float(lows[i]), float(lows[j])
            if lj > 0 and abs(li - lj) / lj < tolerance:
                eq_lows.append((j, lj))

    # Deduplicate (giữ unique levels)
    seen_h = set()
    unique_eq_highs = []
    for idx, price in eq_highs:
        key = round(price, 2)
        if key not in seen_h:
            seen_h.add(key)
            unique_eq_highs.append((idx, price))

    seen_l = set()
    unique_eq_lows = []
    for idx, price in eq_lows:
        key = round(price, 2)
        if key not in seen_l:
            seen_l.add(key)
            unique_eq_lows.append((idx, price))

    return unique_eq_highs, unique_eq_lows


# ─── ANALYZE SINGLE SYMBOL ───────────────────────────────────────────────────

def analyze_symbol(prices_df: pd.DataFrame) -> dict:
    """
    Phân tích market structure cho 1 symbol.

    Args:
        prices_df: DataFrame với columns open/high/low/close/volume, sorted asc

    Returns:
        dict với đầy đủ structure analysis
    """
    empty = {
        "structure": "NEUTRAL", "quality": "INSUFFICIENT_DATA",
        "swing_highs": [], "swing_lows": [],
        "last_sh": None, "last_sl": None,
        "bos_bull": False, "bos_bear": False,
        "choch_bull": False, "choch_bear": False,
        "bos_level": None, "choch_level": None,
        "eq_highs": [], "eq_lows": [],
        "bar_count": 0, "signal_count": 0,
    }

    if prices_df.empty or len(prices_df) < 3:
        return empty

    df  = prices_df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    n   = len(df)
    result = empty.copy()
    result["bar_count"] = n

    hi  = df["high"].values.astype(float)
    lo  = df["low"].values.astype(float)
    cls = df["close"].values.astype(float)

    # Quality flag
    if   n >= 50:  result["quality"] = "HIGH"
    elif n >= 20:  result["quality"] = "MEDIUM"
    elif n >= 8:   result["quality"] = "LOW"
    else:          result["quality"] = "INSUFFICIENT_DATA"

    # ── Swing detection ─────────────────────────────────────
    if n >= MIN_BARS_SWING:
        swing_highs, swing_lows = detect_swings(hi, lo, N_BAR_LOOKBACK)
        result["swing_highs"] = swing_highs
        result["swing_lows"]  = swing_lows
        result["last_sh"]     = swing_highs[-1][1] if swing_highs else None
        result["last_sl"]     = swing_lows[-1][1]  if swing_lows  else None

        # ── Structure classification ─────────────────────────
        result["structure"] = classify_structure(swing_highs, swing_lows)

        # ── BOS / CHoCH ──────────────────────────────────────
        bos = detect_bos_choch(cls, swing_highs, swing_lows, result["structure"])
        result.update(bos)

    # ── Equal H/L (liquidity pools) ─────────────────────────
    if n >= MIN_BARS_EQL:
        eq_h, eq_l = detect_equal_hl(hi, lo, EQ_TOLERANCE)
        result["eq_highs"] = eq_h
        result["eq_lows"]  = eq_l

    # ── Signal count ─────────────────────────────────────────
    sig = 0
    if result["bos_bull"]   or result["bos_bear"]:   sig += 2  # BOS = high quality
    if result["choch_bull"] or result["choch_bear"]:  sig += 2  # CHoCH = very high quality
    if result["eq_highs"]:  sig += 1
    if result["eq_lows"]:   sig += 1
    if result["structure"] != "NEUTRAL": sig += 1
    result["signal_count"] = sig

    return result


# ─── BATCH ANALYSIS ──────────────────────────────────────────────────────────

def analyze_all(ctx: ICTDataContext) -> dict:
    """
    Chạy market structure analysis cho tất cả symbols.

    Returns:
        dict symbol → analysis result
        + summary stats
    """
    results = {}
    stats = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0,
             "bos_bull": 0, "bos_bear": 0, "choch_bull": 0, "choch_bear": 0,
             "eq_highs": 0, "eq_lows": 0, "insufficient": 0}

    for sym in ctx.all_symbols:
        prices = ctx.get_prices(sym)
        r = analyze_symbol(prices)
        results[sym] = r

        if r["quality"] == "INSUFFICIENT_DATA":
            stats["insufficient"] += 1
            continue

        stats[r["structure"]] += 1
        if r["bos_bull"]:   stats["bos_bull"]   += 1
        if r["bos_bear"]:   stats["bos_bear"]   += 1
        if r["choch_bull"]: stats["choch_bull"]  += 1
        if r["choch_bear"]: stats["choch_bear"]  += 1
        if r["eq_highs"]:   stats["eq_highs"]    += 1
        if r["eq_lows"]:    stats["eq_lows"]     += 1

    total = len(ctx.all_symbols)
    log.info("Market Structure — %d symbols:", total)
    log.info("  BULLISH: %d (%.1f%%) | BEARISH: %d | NEUTRAL: %d | Insufficient: %d",
             stats["BULLISH"], stats["BULLISH"]/max(total,1)*100,
             stats["BEARISH"], stats["NEUTRAL"], stats["insufficient"])
    log.info("  BOS bull: %d | BOS bear: %d | CHoCH bull: %d | CHoCH bear: %d",
             stats["bos_bull"], stats["bos_bear"], stats["choch_bull"], stats["choch_bear"])
    log.info("  Equal High pools: %d | Equal Low pools: %d",
             stats["eq_highs"], stats["eq_lows"])

    return {"results": results, "stats": stats}


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="Analyze specific symbol")
    args = parser.parse_args()

    ctx = load_all()

    if args.symbol:
        sym = args.symbol.upper()
        prices = ctx.get_prices(sym)
        if prices.empty:
            print(f"Không tìm thấy prices cho {sym}")
        else:
            r = analyze_symbol(prices)
            print(f"\n{'═'*50}")
            print(f"  {sym} — Market Structure")
            print(f"{'═'*50}")
            print(f"  Bars        : {r['bar_count']} ({r['quality']})")
            print(f"  Structure   : {r['structure']}")
            print(f"  Last SH     : {r['last_sh']}")
            print(f"  Last SL     : {r['last_sl']}")
            print(f"  BOS Bull    : {r['bos_bull']}  level={r['bos_level']}")
            print(f"  BOS Bear    : {r['bos_bear']}")
            print(f"  CHoCH Bull  : {r['choch_bull']}  level={r['choch_level']}")
            print(f"  CHoCH Bear  : {r['choch_bear']}")
            print(f"  Equal Highs : {len(r['eq_highs'])} pools")
            print(f"  Equal Lows  : {len(r['eq_lows'])} pools")
            print(f"  Signal count: {r['signal_count']}")
    else:
        output = analyze_all(ctx)
        stats  = output["stats"]
        total  = len(ctx.all_symbols)

        print(f"\n{'═'*55}")
        print(f"  MARKET STRUCTURE — {total} symbols")
        print(f"{'═'*55}")
        print(f"  BULLISH  : {stats['BULLISH']:>4} ({stats['BULLISH']/max(total,1)*100:.1f}%)")
        print(f"  BEARISH  : {stats['BEARISH']:>4} ({stats['BEARISH']/max(total,1)*100:.1f}%)")
        print(f"  NEUTRAL  : {stats['NEUTRAL']:>4}")
        print(f"  BOS bull : {stats['bos_bull']:>4} | BOS bear: {stats['bos_bear']}")
        print(f"  CHoCH ↑  : {stats['choch_bull']:>4} | CHoCH ↓ : {stats['choch_bear']}")
        print(f"  EqH pools: {stats['eq_highs']:>4} | EqL pools: {stats['eq_lows']}")

        # Top BOS + CHoCH signals
        results = output["results"]
        top = [(sym, r) for sym, r in results.items()
               if r.get("bos_bull") or r.get("choch_bull")]
        top.sort(key=lambda x: x[1]["signal_count"], reverse=True)
        if top:
            print(f"\n  Top BOS/CHoCH Bull signals:")
            for sym, r in top[:10]:
                scr = ctx.get_screener(sym)
                print(f"  {sym:<6} struct={r['structure']:<8} "
                      f"BOS={'Y' if r['bos_bull'] else 'N'} "
                      f"CHoCH={'Y' if r['choch_bull'] else 'N'} "
                      f"score={scr.get('composite_score','?')}")
