"""
export_prices.py — Export Price History to JSON for Frontend

Export giá OHLCV từ stock_prices table ra file prices.json.
Frontend sẽ dùng để hiển thị biểu đồ giá 30 ngày.

Output format:
{
  "generated_at": "2024-01-01T00:00:00Z",
  "total": 700,
  "prices": {
    "VCB": {
      "dates": ["2024-01-01", "2024-01-02", ...],
      "open": [50.0, 51.0, ...],
      "high": [52.0, 53.0, ...],
      "low": [49.0, 50.0, ...],
      "close": [51.0, 52.0, ...],
      "volume": [1000000, 1200000, ...]
    },
    ...
  }
}

Chạy sau daily_prices.py trong GitHub Actions workflow.
"""

import sqlite3
import json
import os
import logging
import sys
from datetime import datetime
from collections import defaultdict

# ─── CONFIG ─────────────────────────────────────────────────────────────────

DB_PATH     = os.getenv("DB_PATH", "data/db/stock.db")
EXPORT_DIR  = os.getenv("EXPORT_DIR", "data/exports")
OUT_PATH    = os.path.join(EXPORT_DIR, "prices.json")
DAYS_LIMIT  = int(os.getenv("PRICE_DAYS_LIMIT", "30"))  # Export last N days

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── HELPERS ────────────────────────────────────────────────────────────────

def safe_float(v, decimals=2):
    """Convert to float, handling NaN/None for valid JSON."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return round(f, decimals)
    except (TypeError, ValueError):
        return None


def safe_int(v):
    """Convert to int, handling NaN/None."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


# ─── MAIN ───────────────────────────────────────────────────────────────────

def export_prices():
    """Export price history from SQLite to JSON."""
    
    if not os.path.exists(DB_PATH):
        log.error("Database not found: %s", DB_PATH)
        return
    
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    
    # Check if table exists
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='stock_prices'
    """)
    if not cursor.fetchone():
        log.warning("Table stock_prices not found. Run daily_prices.py first.")
        conn.close()
        # Create empty prices.json
        output = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total": 0,
            "prices": {}
        }
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
        log.info("Created empty prices.json")
        return
    
    # Get last N days of prices for each symbol
    log.info("Fetching last %d days of prices...", DAYS_LIMIT)
    
    query = f"""
        SELECT symbol, date, open, high, low, close, volume
        FROM stock_prices
        WHERE date >= date('now', '-{DAYS_LIMIT} days')
        ORDER BY symbol, date ASC
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    log.info("Fetched %d price records", len(rows))
    
    # Group by symbol
    prices = defaultdict(lambda: {
        "dates": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": []
    })
    
    for row in rows:
        symbol = row["symbol"]
        prices[symbol]["dates"].append(row["date"])
        prices[symbol]["open"].append(safe_float(row["open"]))
        prices[symbol]["high"].append(safe_float(row["high"]))
        prices[symbol]["low"].append(safe_float(row["low"]))
        prices[symbol]["close"].append(safe_float(row["close"]))
        prices[symbol]["volume"].append(safe_int(row["volume"]))
    
    # Convert defaultdict to regular dict
    prices_dict = dict(prices)
    
    # Build output
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total": len(prices_dict),
        "days": DAYS_LIMIT,
        "prices": prices_dict
    }
    
    # Write to file
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
    
    size_kb = os.path.getsize(OUT_PATH) / 1024
    log.info("✅ Exported %d symbols → %s (%.1f KB)", len(prices_dict), OUT_PATH, size_kb)
    
    # Sample output
    if prices_dict:
        sample_sym = list(prices_dict.keys())[0]
        sample = prices_dict[sample_sym]
        log.info("Sample [%s]: %d days, last close = %s", 
                 sample_sym, len(sample["dates"]), 
                 sample["close"][-1] if sample["close"] else "N/A")
    
    conn.close()


if __name__ == "__main__":
    export_prices()
