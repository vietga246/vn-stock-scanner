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
    """Lấy VN-Index từ vnstock."""
    try:
        quote = Quote(symbol="VNINDEX", source="VCI")
        df = quote.history(start="2026-01-01", end=datetime.now().strftime("%Y-%m-%d"))
        
        if df is not None and len(df) >= 2:
            # Lấy 2 ngày cuối
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            close = safe_float(latest.get("close", latest.get("Close")))
            prev_close = safe_float(prev.get("close", prev.get("Close")))
            
            if close and prev_close:
                change = ((close - prev_close) / prev_close) * 100
                log.info("VN-Index: %.2f (%.2f%%)", close, change)
                return {
                    "vnindex": round(close, 2),
                    "vnindex_change": round(change, 2),
                }
    except Exception as e:
        log.warning("Không lấy được VN-Index: %s", e)
    
    return {
        "vnindex": None,
        "vnindex_change": None,
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
