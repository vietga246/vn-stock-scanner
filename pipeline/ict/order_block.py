"""
ict/order_block.py — Order Block Detector

Order Block = candle cuối cùng đi ngược chiều trước khi có BOS mạnh.
Đây là nơi smart money đặt lệnh — giá thường quay lại để "test" trước
khi tiếp tục theo hướng break.

ICT Definition:
  Bullish OB: bearish candle (close < open) ngay trước khi có impulse
              tăng mạnh (≥2 candles liên tiếp tăng, broke swing high)
  Bearish OB: bullish candle ngay trước khi có impulse giảm mạnh

Mitigation (OB bị "fill"):
  Bullish OB bị fill khi giá quay về test low của candle OB
  Bearish OB bị fill khi giá quay về test high của candle OB

Output per symbol (dict):
  ob_bull          : bool — có bullish OB chưa bị fill và giá đang near
  ob_bear          : bool — có bearish OB
  ob_bull_top      : float — top của bullish OB
  ob_bull_bottom   : float — bottom của bullish OB
  ob_bear_top      : float
  ob_bear_bottom   : float
  ob_bull_age      : int — bao nhiêu bars kể từ khi OB hình thành
  ob_bear_age      : int
  ob_bull_mitigated: bool — OB đã bị fill (giảm quality)
  ob_bear_mitigated: bool
  price_at_ob      : bool — giá hiện tại đang trong vùng OB (entry zone)
  signal_count     : int

Min bars: 5. Quality tốt nhất với ≥ 30 bars.

Chạy độc lập:
  python -m pipeline.ict.order_block --symbol FPT
"""

import os, sys, logging
from typing import Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all

log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

MIN_BARS         = 5
MIN_IMPULSE_BARS = 2     # cần ít nhất 2 bars mạnh sau OB
IMPULSE_THRESH   = 0.01  # mỗi impulse bar cần tăng/giảm ≥ 1%
OB_MAX_AGE       = 30    # OB cũ hơn 30 bars → bỏ qua
NEAR_OB_THRESH   = 0.02  # giá hiện tại trong ±2% so với OB = "near OB"


# ─── IMPULSE DETECTION ───────────────────────────────────────────────────────

def _is_bullish_impulse(opens: np.ndarray, closes: np.ndarray,
                        start_idx: int, min_bars: int = MIN_IMPULSE_BARS) -> bool:
    """Kiểm tra có ≥ min_bars tăng mạnh liên tiếp từ start_idx."""
    n = len(closes)
    count = 0
    for i in range(start_idx, min(start_idx + 4, n)):
        if closes[i] > opens[i] and (closes[i] - opens[i]) / opens[i] >= IMPULSE_THRESH:
            count += 1
        else:
            break
    return count >= min_bars


def _is_bearish_impulse(opens: np.ndarray, closes: np.ndarray,
                        start_idx: int, min_bars: int = MIN_IMPULSE_BARS) -> bool:
    """Kiểm tra có ≥ min_bars giảm mạnh liên tiếp từ start_idx."""
    n = len(closes)
    count = 0
    for i in range(start_idx, min(start_idx + 4, n)):
        if closes[i] < opens[i] and (opens[i] - closes[i]) / opens[i] >= IMPULSE_THRESH:
            count += 1
        else:
            break
    return count >= min_bars


# ─── ORDER BLOCK DETECTION ───────────────────────────────────────────────────

def detect_order_blocks(opens: np.ndarray, highs: np.ndarray,
                        lows: np.ndarray, closes: np.ndarray) -> dict:
    """
    Tìm Order Blocks bullish và bearish.

    Returns:
        dict với bull_obs và bear_obs (list of dicts)
    """
    n = len(closes)
    bull_obs = []
    bear_obs = []

    if n < MIN_BARS:
        return {"bull_obs": [], "bear_obs": []}

    for i in range(1, n - MIN_IMPULSE_BARS):
        age = n - 1 - i
        if age > OB_MAX_AGE:
            continue

        # Bullish OB: bearish candle tại i, theo sau là bullish impulse
        if closes[i] < opens[i]:  # bearish candle
            if _is_bullish_impulse(opens, closes, i + 1):
                bull_obs.append({
                    "idx":    i,
                    "top":    float(opens[i]),   # top = open của bearish candle
                    "bottom": float(closes[i]),  # bottom = close
                    "high":   float(highs[i]),
                    "low":    float(lows[i]),
                    "age":    age,
                })

        # Bearish OB: bullish candle tại i, theo sau là bearish impulse
        if closes[i] > opens[i]:  # bullish candle
            if _is_bearish_impulse(opens, closes, i + 1):
                bear_obs.append({
                    "idx":    i,
                    "top":    float(closes[i]),  # top = close của bullish candle
                    "bottom": float(opens[i]),   # bottom = open
                    "high":   float(highs[i]),
                    "low":    float(lows[i]),
                    "age":    age,
                })

    return {"bull_obs": bull_obs, "bear_obs": bear_obs}


def _check_mitigation(ob: dict, highs: np.ndarray, lows: np.ndarray,
                      closes: np.ndarray, ob_type: str) -> bool:
    """
    Kiểm tra OB có bị mitigated (fill) chưa.
    Bullish OB fill: giá về test lại vùng OB (low đi vào bottom..top)
    Bearish OB fill: giá về test lại vùng OB (high đi vào bottom..top)
    """
    n    = len(closes)
    start = ob["idx"] + 1

    if ob_type == "bull":
        for i in range(start, n):
            if lows[i] <= ob["top"]:  # giá touch vào vùng OB
                return True
    else:  # bear
        for i in range(start, n):
            if highs[i] >= ob["bottom"]:
                return True
    return False


# ─── ANALYZE SINGLE SYMBOL ───────────────────────────────────────────────────

def analyze_symbol(prices_df: pd.DataFrame) -> dict:
    """Detect order blocks cho 1 symbol."""
    empty = {
        "ob_bull": False, "ob_bear": False,
        "ob_bull_top": None, "ob_bull_bottom": None,
        "ob_bear_top": None, "ob_bear_bottom": None,
        "ob_bull_age": None, "ob_bear_age": None,
        "ob_bull_mitigated": False, "ob_bear_mitigated": False,
        "price_at_ob": False,
        "signal_count": 0, "bar_count": 0,
        "quality": "INSUFFICIENT_DATA",
    }

    if prices_df.empty or len(prices_df) < MIN_BARS:
        return empty

    df = prices_df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    n  = len(df)
    if n < MIN_BARS:
        return empty

    op  = df["open"].values.astype(float)
    hi  = df["high"].values.astype(float)
    lo  = df["low"].values.astype(float)
    cls = df["close"].values.astype(float)

    quality = "HIGH" if n >= 50 else ("MEDIUM" if n >= 20 else "LOW")
    current_price = cls[-1]

    # Detect OBs
    obs = detect_order_blocks(op, hi, lo, cls)

    result = empty.copy()
    result["bar_count"] = n
    result["quality"]   = quality

    # ── Bullish OB: lấy OB gần nhất chưa bị fill ─────────────────────────
    for ob in sorted(obs["bull_obs"], key=lambda x: x["age"]):
        mitigated = _check_mitigation(ob, hi, lo, cls, "bull")
        result["ob_bull"]           = True
        result["ob_bull_top"]       = ob["top"]
        result["ob_bull_bottom"]    = ob["bottom"]
        result["ob_bull_age"]       = ob["age"]
        result["ob_bull_mitigated"] = mitigated
        break  # lấy OB trẻ nhất

    # ── Bearish OB ────────────────────────────────────────────────────────
    for ob in sorted(obs["bear_obs"], key=lambda x: x["age"]):
        mitigated = _check_mitigation(ob, hi, lo, cls, "bear")
        result["ob_bear"]           = True
        result["ob_bear_top"]       = ob["top"]
        result["ob_bear_bottom"]    = ob["bottom"]
        result["ob_bear_age"]       = ob["age"]
        result["ob_bear_mitigated"] = mitigated
        break

    # ── Price at OB (entry zone) ──────────────────────────────────────────
    if result["ob_bull_top"] and result["ob_bull_bottom"]:
        ob_mid   = (result["ob_bull_top"] + result["ob_bull_bottom"]) / 2
        near_bull = abs(current_price - ob_mid) / ob_mid < NEAR_OB_THRESH
        if near_bull:
            result["price_at_ob"] = True

    # ── Signal count ──────────────────────────────────────────────────────
    sig = 0
    if result["ob_bull"] and not result["ob_bull_mitigated"]: sig += 2
    if result["ob_bear"] and not result["ob_bear_mitigated"]: sig += 1
    if result["price_at_ob"]:  sig += 2  # price IN the OB = active setup
    result["signal_count"] = sig

    return result


# ─── BATCH ───────────────────────────────────────────────────────────────────

def analyze_all(ctx: ICTDataContext) -> dict:
    """Chạy order block analysis cho tất cả symbols."""
    results = {}
    stats = {
        "ob_bull": 0, "ob_bear": 0,
        "price_at_ob": 0, "unmitigated_bull": 0,
        "insufficient": 0,
    }

    for sym in ctx.all_symbols:
        prices = ctx.get_prices(sym)
        r = analyze_symbol(prices)
        results[sym] = r

        if r["quality"] == "INSUFFICIENT_DATA": stats["insufficient"] += 1
        if r["ob_bull"]:  stats["ob_bull"]  += 1
        if r["ob_bear"]:  stats["ob_bear"]  += 1
        if r["price_at_ob"]: stats["price_at_ob"] += 1
        if r["ob_bull"] and not r["ob_bull_mitigated"]:
            stats["unmitigated_bull"] += 1

    total = len(ctx.all_symbols)
    log.info("Order Block — %d symbols: bull=%d (unmitigated=%d), "
             "bear=%d, price_at_ob=%d, insufficient=%d",
             total, stats["ob_bull"], stats["unmitigated_bull"],
             stats["ob_bear"], stats["price_at_ob"], stats["insufficient"])

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
        print(f"\n{'═'*48}")
        print(f"  {sym} — Order Block")
        print(f"{'═'*48}")
        for k, v in r.items():
            print(f"  {k:<24}: {v}")
    else:
        out   = analyze_all(ctx)
        stats = out["stats"]
        total = len(ctx.all_symbols)

        print(f"\n{'═'*52}")
        print(f"  ORDER BLOCK — {total} symbols")
        print(f"{'═'*52}")
        print(f"  Bullish OB        : {stats['ob_bull']:>4}")
        print(f"  Unmitigated bull  : {stats['unmitigated_bull']:>4}")
        print(f"  Bearish OB        : {stats['ob_bear']:>4}")
        print(f"  Price at OB (entry): {stats['price_at_ob']:>4}")

        results = out["results"]
        top = [(s, r) for s, r in results.items()
               if r["ob_bull"] and not r["ob_bull_mitigated"] and r["price_at_ob"]]
        top.sort(key=lambda x: x[1]["signal_count"], reverse=True)
        if top:
            print(f"\n  Best setups (unmitigated bull OB + price at OB):")
            print(f"  {'Sym':<6} {'OB_top':>8} {'OB_bot':>8} {'Age':>4} {'Score'}")
            for sym, r in top[:10]:
                scr = ctx.get_screener(sym)
                print(f"  {sym:<6} {r['ob_bull_top']:>8.2f} "
                      f"{r['ob_bull_bottom']:>8.2f} "
                      f"{r['ob_bull_age']:>4} "
                      f"{scr.get('composite_score', '?')}")
