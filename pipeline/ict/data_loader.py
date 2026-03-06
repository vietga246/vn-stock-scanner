"""
ict/data_loader.py — ICT Pipeline Data Loader

Load và normalize tất cả JSON sources. Module duy nhất đọc file —
tất cả ICT modules khác nhận data từ ICTDataContext thay vì tự đọc.

Output (ICTDataContext):
  prices_df       : OHLCV per symbol (714 symbols × 18 bars hiện tại)
  screener_df     : composite scores + technical fields (706 symbols)
  price_board_df  : bid/ask + buy_pressure + foreign flow (705 symbols)
  sectors_df      : 25 ngành với metrics + rotation signal
  summary         : dict vnindex, top movers
  min_bars_df     : bar count + has_* flags per symbol

MIN_BARS thresholds:
  ≥ 3  bars → FVG, Order Block, Liquidity Sweep
  ≥ 5  bars → MA5, vol_ratio
  ≥ 8  bars → Market Structure (swing H/L)
  ≥14  bars → RSI14, ATR14
  ≥20  bars → Bollinger Bands, vol_MA20
  ≥28  bars → ADX14, trend_strength (Wilder smoothing)
  ≥50  bars → MA50

Chạy độc lập để debug:
  python -m pipeline.ict.data_loader
"""

import json, os, logging, sys
from datetime import datetime
from typing import Optional
import pandas as pd
import numpy as np

# ─── CONFIG ──────────────────────────────────────────────────────────────────

EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")

MIN_BARS_MAP = {
    "fvg":            3,
    "order_block":    3,
    "liq_sweep":      3,
    "ma5":            5,
    "vol_ratio":      5,
    "market_structure": 8,
    "rsi14":         14,
    "atr14":         14,
    "bb_width":      20,
    "vol_ma20":      20,
    "adx14":         28,
    "trend_strength":28,
    "ma50":          50,
}

log = logging.getLogger(__name__)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _sf(v, d=None):
    """safe_float: None/NaN/Inf → None"""
    if v is None: return None
    try:
        f = float(v)
        if not (f == f) or abs(f) == float("inf"): return None
        return round(f, d) if d is not None else f
    except: return None


def _load_json(filename: str) -> dict:
    path = os.path.join(EXPORT_DIR, filename)
    if not os.path.exists(path):
        log.warning("Không tìm thấy: %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Lỗi load %s: %s", filename, e)
        return {}


# ─── INDIVIDUAL LOADERS ──────────────────────────────────────────────────────

def load_prices() -> pd.DataFrame:
    """prices.json → DataFrame (symbol, date, open, high, low, close, volume)"""
    raw = _load_json("prices.json")
    if not raw.get("prices"):
        return pd.DataFrame()

    records = []
    for sym, data in raw["prices"].items():
        dates  = data.get("dates",  [])
        opens  = data.get("open",   [])
        highs  = data.get("high",   [])
        lows   = data.get("low",    [])
        closes = data.get("close",  [])
        vols   = data.get("volume", [])
        n = len(dates)
        for i in range(n):
            records.append({
                "symbol": sym,
                "date":   dates[i],
                "open":   _sf(opens[i]  if i < len(opens)  else None),
                "high":   _sf(highs[i]  if i < len(highs)  else None),
                "low":    _sf(lows[i]   if i < len(lows)   else None),
                "close":  _sf(closes[i] if i < len(closes) else None),
                "volume": _sf(vols[i]   if i < len(vols)   else None),
            })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    log.info("Prices: %d symbols, %d bars total", df["symbol"].nunique(), len(df))
    return df


def load_screener() -> pd.DataFrame:
    """screener.json → DataFrame (1 row per symbol)"""
    raw = _load_json("screener.json")
    stocks = raw.get("screener", [])
    if not stocks:
        return pd.DataFrame()
    df = pd.DataFrame(stocks)
    log.info("Screener: %d symbols, %d fields", len(df), len(df.columns))
    return df


def load_price_board() -> pd.DataFrame:
    """price_board.json → DataFrame với buy_pressure, bid/ask, foreign flow"""
    raw = _load_json("price_board.json")
    stocks = raw.get("stocks", [])
    if not stocks:
        return pd.DataFrame()
    df = pd.DataFrame(stocks)
    log.info("Price board: %d symbols", len(df))
    return df


def load_sectors() -> pd.DataFrame:
    """sectors.json → DataFrame (25 ngành)"""
    raw = _load_json("sectors.json")
    sectors = raw.get("sectors", [])
    rotation = raw.get("rotation_signal", {})
    if not sectors:
        return pd.DataFrame(), rotation
    df = pd.DataFrame(sectors)
    log.info("Sectors: %d industries", len(df))
    return df, rotation


def load_summary() -> dict:
    """summary.json → dict với vnindex + change fields"""
    raw = _load_json("summary.json")
    market = raw.get("market", {})
    result = {**raw, **market}
    # Đảm bảo các key luôn tồn tại (có thể None nếu Fix 3 chưa chạy)
    result.setdefault("vnindex_change_5d",  None)
    result.setdefault("vnindex_change_20d", None)
    return result


def build_min_bars_flags(prices_df: pd.DataFrame) -> pd.DataFrame:
    """Tính bar_count và has_* flags per symbol"""
    if prices_df.empty:
        return pd.DataFrame()
    counts = prices_df.groupby("symbol").size().reset_index(name="bar_count")
    for flag, min_n in MIN_BARS_MAP.items():
        counts[f"has_{flag}"] = counts["bar_count"] >= min_n
    return counts


# ─── DATA CONTEXT ─────────────────────────────────────────────────────────────

class ICTDataContext:
    """
    Container cho tất cả data sources. Tạo một lần qua load_all(),
    truyền vào mọi ICT module.

    Usage:
        ctx = load_all()
        prices = ctx.get_prices("VCB")    # DataFrame OHLCV
        scr    = ctx.get_screener("VCB")  # dict scores/indicators
        board  = ctx.get_board("VCB")     # dict bid/ask/buy_pressure
    """

    def __init__(self):
        self.prices_df      = pd.DataFrame()
        self.screener_df    = pd.DataFrame()
        self.price_board_df = pd.DataFrame()
        self.sectors_df     = pd.DataFrame()
        self.rotation       = {}
        self.summary        = {}
        self.min_bars_df    = pd.DataFrame()
        self.generated_at   = datetime.now().isoformat()
        self._scr_map: dict = {}
        self._board_map: dict = {}
        self._bar_map: dict  = {}

    def _build_lookups(self):
        if not self.screener_df.empty:
            self._scr_map = {r["symbol"]: r
                             for r in self.screener_df.to_dict("records")}
        if not self.price_board_df.empty:
            self._board_map = {r["symbol"]: r
                               for r in self.price_board_df.to_dict("records")}
        if not self.min_bars_df.empty:
            self._bar_map = {r["symbol"]: r
                             for r in self.min_bars_df.to_dict("records")}

    def get_prices(self, symbol: str) -> pd.DataFrame:
        """OHLCV DataFrame cho 1 symbol, sorted asc."""
        if self.prices_df.empty:
            return pd.DataFrame()
        mask = self.prices_df["symbol"] == symbol
        return self.prices_df[mask].sort_values("date").reset_index(drop=True)

    def get_screener(self, symbol: str) -> dict:
        return self._scr_map.get(symbol, {})

    def get_board(self, symbol: str) -> dict:
        return self._board_map.get(symbol, {})

    def bar_count(self, symbol: str) -> int:
        r = self._bar_map.get(symbol, {})
        return int(r.get("bar_count", 0))

    def has_bars(self, symbol: str, indicator: str) -> bool:
        r = self._bar_map.get(symbol, {})
        return bool(r.get(f"has_{indicator}", False))

    @property
    def all_symbols(self) -> list:
        return self.screener_df["symbol"].tolist() if not self.screener_df.empty else []

    def stats(self) -> dict:
        return {
            "screener_symbols":  len(self.screener_df),
            "price_symbols":     self.prices_df["symbol"].nunique() if not self.prices_df.empty else 0,
            "avg_bars":          round(self.min_bars_df["bar_count"].mean(), 1) if not self.min_bars_df.empty else 0,
            "symbols_adx_ready": int(self.min_bars_df["has_adx14"].sum()) if not self.min_bars_df.empty and "has_adx14" in self.min_bars_df else 0,
            "price_board":       len(self.price_board_df),
            "sectors":           len(self.sectors_df),
            "vnindex":           self.summary.get("vnindex"),
            "vnindex_5d":        self.summary.get("vnindex_change_5d"),
        }


def load_all(export_dir: str = None) -> ICTDataContext:
    """
    Load tất cả sources → ICTDataContext.

    Args:
        export_dir: override EXPORT_DIR env var
    """
    global EXPORT_DIR
    if export_dir:
        EXPORT_DIR = export_dir

    log.info("─── ICT Data Loader ─── EXPORT_DIR=%s", EXPORT_DIR)

    ctx = ICTDataContext()
    ctx.prices_df       = load_prices()
    ctx.screener_df     = load_screener()
    ctx.price_board_df  = load_price_board()
    ctx.sectors_df, ctx.rotation = load_sectors()
    ctx.summary         = load_summary()
    ctx.min_bars_df     = build_min_bars_flags(ctx.prices_df)
    ctx._build_lookups()

    s = ctx.stats()
    log.info("Loaded: %d screener | %d prices (avg %.0f bars) | %d board | %d sectors",
             s["screener_symbols"], s["price_symbols"], s["avg_bars"],
             s["price_board"], s["sectors"])
    log.info("ADX-ready: %d symbols | VNINDEX: %s (5d: %s%%)",
             s["symbols_adx_ready"], s["vnindex"], s["vnindex_5d"])
    return ctx


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ctx = load_all()
    print("\n=== ICTDataContext ===")
    for k, v in ctx.stats().items():
        print(f"  {k:<22}: {v}")

    # Sample
    for sym in ["VCB", "FPT", "HPG", "DCM"]:
        df = ctx.get_prices(sym)
        if not df.empty:
            scr = ctx.get_screener(sym)
            print(f"\n  [{sym}] {len(df)} bars | RSI={scr.get('rsi14')} "
                  f"| ADX={scr.get('adx14')} | FVG_bull={scr.get('fvg_bull')}")
            print(df.tail(3)[["date","open","high","low","close","volume"]].to_string(index=False))
            break
