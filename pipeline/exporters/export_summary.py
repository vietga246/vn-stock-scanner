"""
export_summary.py — Export Market Summary (VN-Index + Top Movers)

Tạo summary.json chứa:
- VN-Index value và % change
- Top gainers/losers
- Most active stocks
- Top foreign buy/sell
"""

import json
import logging
import os
import sys
from datetime import datetime

# Import từ vnstock
from vnstock import Quote

# Import shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils import safe_float, setup_logging

# ─── CONFIG ────────────────────────────────────────────────────────────────

EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")
DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")

log = setup_logging()

# ─── VN-INDEX ──────────────────────────────────────────────────────────────

def get_vnindex() -> dict:
    """
    Lấy VN-Index từ vnstock.
    Tính change_1d, change_5d, change_20d để RS vs Market calculation chính xác.
    """
    try:
        quote = Quote(symbol="VNINDEX", source="VCI")
        # Lấy đủ 30 ngày để có change_5d và change_20d
        start_date = (datetime.now() - __import__("datetime").timedelta(days=60)).strftime("%Y-%m-%d")
        df = quote.history(start=start_date, end=datetime.now().strftime("%Y-%m-%d"))

        if df is not None and len(df) >= 2:
            # Normalize column names (vnstock trả về lowercase hoặc Title case)
            df.columns = [c.lower() for c in df.columns]
            close_col = "close" if "close" in df.columns else df.columns[3]
            closes = df[close_col].dropna().values

            latest_close = safe_float(closes[-1])
            prev_close   = safe_float(closes[-2]) if len(closes) >= 2 else None

            change_1d  = None
            change_5d  = None
            change_20d = None

            if latest_close and prev_close and prev_close != 0:
                change_1d = round((latest_close - prev_close) / prev_close * 100, 2)
            if latest_close and len(closes) >= 6:
                c5 = safe_float(closes[-6])
                if c5 and c5 != 0:
                    change_5d = round((latest_close - c5) / c5 * 100, 2)
            if latest_close and len(closes) >= 21:
                c20 = safe_float(closes[-21])
                if c20 and c20 != 0:
                    change_20d = round((latest_close - c20) / c20 * 100, 2)

            log.info("VN-Index: %.2f | 1d: %s%% | 5d: %s%% | 20d: %s%%",
                     latest_close or 0, change_1d, change_5d, change_20d)

            return {
                "vnindex":            round(latest_close, 2) if latest_close else None,
                "vnindex_change":     change_1d,   # backward-compat alias
                "vnindex_change_1d":  change_1d,
                "vnindex_change_5d":  change_5d,   # NEW — dùng cho RS vs Market
                "vnindex_change_20d": change_20d,  # NEW — dùng cho RS vs Market
            }
    except Exception as e:
        log.warning("Không lấy được VN-Index: %s", e)

    return {
        "vnindex":            None,
        "vnindex_change":     None,
        "vnindex_change_1d":  None,
        "vnindex_change_5d":  None,
        "vnindex_change_20d": None,
    }


# ─── TOP MOVERS ────────────────────────────────────────────────────────────

def get_top_movers(screener_path: str) -> dict:
    """Lấy top gainers/losers từ screener.json."""
    result = {
        "top_gainers": [],
        "top_losers": [],
        "most_active": [],
        "foreign_buy": [],
        "foreign_sell": [],
    }
    
    try:
        if not os.path.exists(screener_path):
            return result
        
        with open(screener_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        stocks = data.get("screener", [])
        
        # Filter stocks with valid price change data
        with_change = [s for s in stocks if s.get("price_change_1d") is not None]
        
        # Sort by 1D change
        sorted_by_change = sorted(with_change, key=lambda x: x.get("price_change_1d", 0), reverse=True)
        result["top_gainers"] = [
            {"symbol": s["symbol"], "change": s.get("price_change_1d")} 
            for s in sorted_by_change[:10]
        ]
        result["top_losers"] = [
            {"symbol": s["symbol"], "change": s.get("price_change_1d")} 
            for s in sorted_by_change[-10:][::-1]
        ]
        
        # Sort by volume (most active)
        with_volume = [s for s in stocks if s.get("volume") is not None and s.get("volume", 0) > 0]
        sorted_by_volume = sorted(with_volume, key=lambda x: x.get("volume", 0), reverse=True)
        result["most_active"] = [
            {"symbol": s["symbol"], "volume": s.get("volume")} 
            for s in sorted_by_volume[:10]
        ]
        
        # Sort by foreign net (buy/sell)
        with_foreign = [s for s in stocks if s.get("foreign_net_7d") is not None]
        sorted_by_foreign = sorted(with_foreign, key=lambda x: x.get("foreign_net_7d", 0), reverse=True)
        result["foreign_buy"] = [
            {"symbol": s["symbol"], "net": s.get("foreign_net_7d")} 
            for s in sorted_by_foreign[:10] if s.get("foreign_net_7d", 0) > 0
        ]
        result["foreign_sell"] = [
            {"symbol": s["symbol"], "net": s.get("foreign_net_7d")} 
            for s in sorted_by_foreign[-10:][::-1] if s.get("foreign_net_7d", 0) < 0
        ]
        
    except Exception as e:
        log.warning("Không lấy được top movers: %s", e)
    
    return result


# ─── MAIN ──────────────────────────────────────────────────────────────────

def export_summary():
    """Export summary.json."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Get VN-Index
    market = get_vnindex()
    
    # Get top movers from screener.json
    screener_path = os.path.join(EXPORT_DIR, "screener.json")
    movers = get_top_movers(screener_path)
    
    # Build summary
    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "market": market,
        **movers,
    }
    
    # Write to file
    output_path = os.path.join(EXPORT_DIR, "summary.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, separators=(",", ":"))
    
    log.info("✅ Exported summary.json")
    log.info("   VN-Index: %s (change: %s%%)", 
             market.get("vnindex"), market.get("vnindex_change"))


if __name__ == "__main__":
    export_summary()
