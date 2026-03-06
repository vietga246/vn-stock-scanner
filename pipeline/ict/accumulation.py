"""
ict/accumulation.py — Accumulation / Distribution Detector

Detect volume accumulation (smart money tích lũy) và distribution
(smart money phân phối) dựa trên:

  1. Volume Spike: volume hiện tại / vol_MA20 baseline
  2. Volume Trend: khối lượng tăng dần trong uptrend (tích lũy)
                   vs tăng trong downtrend (phân phối)
  3. Price-Volume Divergence: giá tăng nhưng volume giảm = bearish
                               giá giảm nhưng volume giảm = potential reversal
  4. Wyckoff Spring: giá drop mạnh kèm volume spike rồi recover nhanh
                     (smart money absorbing selling pressure)
  5. Narrow Range + Volume Compression (NR7/NR4):
     range thu hẹp + volume giảm = breakout sắp xảy ra

Output per symbol (dict):
  accumulation_score : 0-100 composite
  distribution_score : 0-100 composite
  vol_spike          : float — vol_ratio hiện tại (current/MA20)
  vol_trend          : "increasing"|"decreasing"|"flat"
  price_vol_diverge  : bool — giá tăng/volume giảm (bearish divergence)
  wyckoff_spring     : bool — potential spring setup
  nr7                : bool — Narrow Range 7 (7-bar range tightest)
  vol_compression    : bool — volume giảm ≥ 3 bars liên tiếp
  breakout_imminent  : bool — NR7 + vol_compression = breakout setup
  signal_count       : int

Yêu cầu: ≥ 10 bars. Tốt nhất ≥ 50 bars (có vol_MA20 chuẩn).

Chạy độc lập:
  python -m pipeline.ict.accumulation --symbol DCM
"""

import os, sys, logging
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pipeline.ict.data_loader import ICTDataContext, load_all

log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

MIN_BARS          = 10
VOL_SPIKE_THRESH  = 1.5    # vol_ratio ≥ 1.5x MA20 = spike
VOL_SPIKE_HIGH    = 2.5    # ≥ 2.5x = high spike
VOL_MA_PERIOD     = 20
VOL_MA_SHORT      = 5
NR_LOOKBACK       = 7      # NR7 lookback
SPRING_DROP_THRESH = 0.03  # ≥ 3% drop để qualify spring
SPRING_RECOVER    = 0.5    # recover ≥ 50% của drop


# ─── COMPONENT CALCULATORS ───────────────────────────────────────────────────

def _calc_vol_ratio(volumes: np.ndarray) -> float:
    """vol_ratio = current_vol / vol_MA20. Fallback to MA5 nếu ít bars."""
    n = len(volumes)
    if n < 3:
        return 1.0
    current = volumes[-1]
    period  = min(VOL_MA_PERIOD, n - 1)
    baseline = np.mean(volumes[-period - 1:-1])
    if baseline <= 0:
        return 1.0
    return float(current / baseline)


def _calc_vol_trend(volumes: np.ndarray, n_bars: int = 5) -> str:
    """Volume trend trong n_bars gần nhất."""
    if len(volumes) < n_bars + 1:
        return "flat"
    recent = volumes[-n_bars:]
    slope  = np.polyfit(range(n_bars), recent, 1)[0]
    mean_v = np.mean(recent)
    if mean_v <= 0:
        return "flat"
    rel_slope = slope / mean_v
    if   rel_slope >  0.03: return "increasing"
    elif rel_slope < -0.03: return "decreasing"
    return "flat"


def _price_vol_divergence(closes: np.ndarray, volumes: np.ndarray,
                          n_bars: int = 5) -> bool:
    """
    Bearish divergence: giá tăng nhưng volume giảm trong n_bars gần nhất.
    Thường xảy ra ở đỉnh trước khi reversal.
    """
    if len(closes) < n_bars + 1:
        return False
    price_up  = closes[-1] > closes[-n_bars]
    vol_trend = _calc_vol_trend(volumes, n_bars)
    return price_up and vol_trend == "decreasing"


def _detect_wyckoff_spring(highs: np.ndarray, lows: np.ndarray,
                           closes: np.ndarray, volumes: np.ndarray) -> bool:
    """
    Wyckoff Spring:
    1. Giá drop mạnh ≥ SPRING_DROP_THRESH trong 1-3 bars
    2. Kèm volume spike ≥ 1.5x
    3. Close recover ≥ 50% của drop trong vài bars sau
    """
    n = len(closes)
    if n < 5:
        return False

    vol_ratio = _calc_vol_ratio(volumes)

    # Tìm drop trong 3-5 bars gần nhất
    for lookback in range(2, min(6, n)):
        drop = (closes[-lookback] - lows[-1]) / closes[-lookback]
        if drop >= SPRING_DROP_THRESH:
            recover = (closes[-1] - lows[-1]) / max(closes[-lookback] - lows[-1], 0.001)
            if recover >= SPRING_RECOVER and vol_ratio >= 1.5:
                return True
    return False


def _detect_nr7(highs: np.ndarray, lows: np.ndarray) -> bool:
    """
    NR7: range của bar hiện tại là nhỏ nhất trong 7 bars gần nhất.
    Dấu hiệu volatility compression → breakout sắp xảy ra.
    """
    n = len(highs)
    if n < NR_LOOKBACK:
        return False
    ranges    = highs[-NR_LOOKBACK:] - lows[-NR_LOOKBACK:]
    curr_range = ranges[-1]
    return bool(curr_range == min(ranges))


def _vol_compression(volumes: np.ndarray, n_bars: int = 3) -> bool:
    """Volume giảm dần ≥ n_bars liên tiếp."""
    if len(volumes) < n_bars + 1:
        return False
    recent = volumes[-n_bars - 1:]
    for i in range(1, len(recent)):
        if recent[i] >= recent[i - 1]:
            return False
    return True


# ─── ACCUMULATION / DISTRIBUTION SCORE ──────────────────────────────────────

def _calc_accumulation_score(closes: np.ndarray, volumes: np.ndarray,
                              vol_ratio: float, vol_trend: str,
                              wyckoff_spring: bool, nr7: bool,
                              vol_comp: bool) -> float:
    """
    Accumulation score (0-100):
    - Volume spike khi giá tăng: bullish
    - Vol trend increasing + price up: bullish
    - Wyckoff spring: high conviction bullish
    - NR7 + vol compression: pre-breakout
    """
    n = len(closes)
    if n < 3:
        return 50.0

    score = 50.0
    price_up_1d = closes[-1] > closes[-2] if n >= 2 else False
    price_up_5d = closes[-1] > closes[-5] if n >= 5 else False

    # Vol spike khi giá tăng
    if vol_ratio >= VOL_SPIKE_HIGH and price_up_1d: score += 20
    elif vol_ratio >= VOL_SPIKE_THRESH and price_up_1d: score += 10

    # Volume trend aligned with price
    if vol_trend == "increasing" and price_up_5d: score += 10
    elif vol_trend == "decreasing" and not price_up_5d: score += 5  # quiet pullback

    # Wyckoff spring = strong accumulation signal
    if wyckoff_spring: score += 20

    # Pre-breakout setup
    if nr7 and vol_comp: score += 10
    elif nr7 or vol_comp: score += 5

    return float(np.clip(score, 0, 100))


def _calc_distribution_score(closes: np.ndarray, volumes: np.ndarray,
                              vol_ratio: float, vol_trend: str,
                              diverge: bool) -> float:
    """Distribution score (0-100)."""
    n = len(closes)
    if n < 3:
        return 50.0

    score = 50.0
    price_up_1d = closes[-1] > closes[-2] if n >= 2 else False

    # Vol spike khi giá giảm = distribution
    if vol_ratio >= VOL_SPIKE_HIGH and not price_up_1d: score += 20
    elif vol_ratio >= VOL_SPIKE_THRESH and not price_up_1d: score += 10

    # Price-volume divergence = distribution signal
    if diverge: score += 15

    # Volume increasing while price falling
    if vol_trend == "increasing" and n >= 5 and closes[-1] < closes[-5]: score += 10

    return float(np.clip(score, 0, 100))


# ─── ANALYZE SINGLE SYMBOL ───────────────────────────────────────────────────

def analyze_symbol(prices_df: pd.DataFrame) -> dict:
    """Accumulation/Distribution analysis cho 1 symbol."""
    empty = {
        "accumulation_score": 50.0, "distribution_score": 50.0,
        "vol_spike": 1.0, "vol_trend": "flat",
        "price_vol_diverge": False, "wyckoff_spring": False,
        "nr7": False, "vol_compression": False, "breakout_imminent": False,
        "signal_count": 0, "bar_count": 0, "quality": "INSUFFICIENT_DATA",
    }

    if prices_df.empty or len(prices_df) < MIN_BARS:
        return empty

    df = prices_df.dropna(subset=["close", "volume"]).reset_index(drop=True)
    n  = len(df)
    if n < MIN_BARS:
        return empty

    hi  = df["high"].values.astype(float)
    lo  = df["low"].values.astype(float)
    cls = df["close"].values.astype(float)
    vol = df["volume"].values.astype(float)

    quality = "HIGH" if n >= 50 else ("MEDIUM" if n >= 20 else "LOW")

    # Compute components
    vol_ratio   = _calc_vol_ratio(vol)
    vol_trend   = _calc_vol_trend(vol)
    diverge     = _price_vol_divergence(cls, vol)
    spring      = _detect_wyckoff_spring(hi, lo, cls, vol)
    nr7         = _detect_nr7(hi, lo)
    vol_comp    = _vol_compression(vol)
    imminent    = nr7 and vol_comp

    acc_score   = _calc_accumulation_score(cls, vol, vol_ratio, vol_trend,
                                            spring, nr7, vol_comp)
    dist_score  = _calc_distribution_score(cls, vol, vol_ratio, vol_trend, diverge)

    # Signal count (bullish bias)
    sig = 0
    if acc_score >= 70:  sig += 2
    elif acc_score >= 60: sig += 1
    if spring:           sig += 2
    if imminent:         sig += 1
    if not diverge and acc_score > dist_score: sig += 1

    return {
        "accumulation_score":  round(acc_score, 1),
        "distribution_score":  round(dist_score, 1),
        "vol_spike":           round(vol_ratio, 2),
        "vol_trend":           vol_trend,
        "price_vol_diverge":   diverge,
        "wyckoff_spring":      spring,
        "nr7":                 nr7,
        "vol_compression":     vol_comp,
        "breakout_imminent":   imminent,
        "signal_count":        sig,
        "bar_count":           n,
        "quality":             quality,
    }


# ─── BATCH ───────────────────────────────────────────────────────────────────

def analyze_all(ctx: ICTDataContext) -> dict:
    """Chạy accumulation analysis cho tất cả symbols."""
    results = {}
    stats = {
        "accumulating": 0, "distributing": 0, "neutral": 0,
        "wyckoff_spring": 0, "breakout_imminent": 0, "insufficient": 0,
    }

    for sym in ctx.all_symbols:
        prices = ctx.get_prices(sym)
        r = analyze_symbol(prices)
        results[sym] = r

        if r["quality"] == "INSUFFICIENT_DATA": stats["insufficient"] += 1
        elif r["accumulation_score"] >= 60:     stats["accumulating"]  += 1
        elif r["distribution_score"] >= 60:     stats["distributing"]  += 1
        else:                                   stats["neutral"]       += 1
        if r["wyckoff_spring"]:   stats["wyckoff_spring"]   += 1
        if r["breakout_imminent"]: stats["breakout_imminent"] += 1

    total = len(ctx.all_symbols)
    log.info("Accumulation — %d symbols: acc=%d, dist=%d, spring=%d, "
             "breakout_imminent=%d, insufficient=%d",
             total, stats["accumulating"], stats["distributing"],
             stats["wyckoff_spring"], stats["breakout_imminent"],
             stats["insufficient"])

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
        print(f"  {sym} — Accumulation / Distribution")
        print(f"{'═'*48}")
        for k, v in r.items():
            print(f"  {k:<24}: {v}")
    else:
        out   = analyze_all(ctx)
        stats = out["stats"]
        total = len(ctx.all_symbols)

        print(f"\n{'═'*52}")
        print(f"  ACCUMULATION / DISTRIBUTION — {total} symbols")
        print(f"{'═'*52}")
        print(f"  Accumulating      : {stats['accumulating']:>4}")
        print(f"  Distributing      : {stats['distributing']:>4}")
        print(f"  Wyckoff Spring    : {stats['wyckoff_spring']:>4}")
        print(f"  Breakout Imminent : {stats['breakout_imminent']:>4}")

        results = out["results"]
        top = [(s, r) for s, r in results.items()
               if r["accumulation_score"] >= 65 or r["wyckoff_spring"]]
        top.sort(key=lambda x: (x[1]["wyckoff_spring"],
                                x[1]["accumulation_score"]), reverse=True)
        if top:
            print(f"\n  Top Accumulation signals:")
            print(f"  {'Sym':<6} {'AccScore':>8} {'VolRatio':>8} {'Spring':>7} {'Immin':>6}")
            for sym, r in top[:15]:
                print(f"  {sym:<6} {r['accumulation_score']:>8.1f} "
                      f"{r['vol_spike']:>8.2f}x "
                      f"{'✓' if r['wyckoff_spring'] else '-':>7} "
                      f"{'✓' if r['breakout_imminent'] else '-':>6}")
