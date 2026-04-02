"""
weekly_warning_status.py — Thu thập danh sách cổ phiếu cảnh báo/kiểm soát

Workflow riêng biệt:
1. Fetch từ nhiều nguồn API (VNDirect, TCBS, SSI, CafeF)
2. Merge và deduplicate
3. Export ra JSON file để view
4. Cập nhật vào database (nếu có)

Output: data/exports/warning_stocks.json
"""

import requests
import json
import sqlite3
import os
import sys
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional

# ════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")
CACHE_DIR = os.getenv("CACHE_DIR", "data/cache")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
}

# Timeout cho requests
REQUEST_TIMEOUT = 30

# ════════════════════════════════════════════════════════════════════════════
# PENALTY CONFIG (for reference in export)
# ════════════════════════════════════════════════════════════════════════════

WARNING_PENALTIES = {
    "control":     {"penalty": 0.50, "description": "Kiểm soát - Giao dịch hạn chế nghiêm trọng, chỉ khớp lệnh định kỳ"},
    "warning":     {"penalty": 0.30, "description": "Cảnh báo - Nguy cơ bị kiểm soát, thua lỗ liên tục"},
    "restriction": {"penalty": 0.15, "description": "Hạn chế - Điều kiện giao dịch đặc biệt"},
    "halt":        {"penalty": 0.60, "description": "Tạm ngừng giao dịch"},
    "delisting":   {"penalty": 0.70, "description": "Sắp hủy niêm yết"},
}

# ════════════════════════════════════════════════════════════════════════════
# FALLBACK LIST (khi tất cả API fail)
# ════════════════════════════════════════════════════════════════════════════

FALLBACK_WARNING_STOCKS = {
    # KIỂM SOÁT
    'FLC': 'control', 'ROS': 'control', 'HAI': 'control', 'AMD': 'control',
    'HVN': 'control', 'AGM': 'control', 'DRH': 'control', 'LGL': 'control',
    'CKG': 'control', 'TNT': 'control', 'HNG': 'control',
    # CẢNH BÁO
    'HQC': 'warning', 'DLG': 'warning', 'LDG': 'warning', 'QCG': 'warning',
    'TTF': 'warning', 'OGC': 'warning', 'TGG': 'warning', 'CEO': 'warning',
    'GAB': 'warning', 'HAG': 'warning', 'JVC': 'warning', 'HBC': 'warning',
    'NBB': 'warning', 'FIT': 'warning', 'TNI': 'warning', 'DAG': 'warning',
    'HHS': 'warning', 'C32': 'warning', 'PVX': 'warning',
    # HẠN CHẾ
    'NVL': 'restriction', 'PDR': 'restriction', 'DIG': 'restriction',
    'SCR': 'restriction', 'DXG': 'restriction', 'VIX': 'restriction',
    'KBC': 'restriction', 'CII': 'restriction',
}

# ════════════════════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# API FETCHERS
# ════════════════════════════════════════════════════════════════════════════

def fetch_from_vndirect() -> Dict[str, dict]:
    """
    Lấy từ VNDirect API.
    Trả về dict với thông tin chi tiết của từng mã.
    """
    result = {}
    try:
        url = "https://finfo-api.vndirect.com.vn/v4/stocks"
        params = {
            "q": "type:STOCK~status:LISTED",
            "size": 2000,
            "sort": "code"
        }
        
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        stocks = data.get("data", [])
        log.info(f"VNDirect: Fetched {len(stocks)} stocks")
        
        status_map = {
            "CONTROLLED": "control",
            "WARNING": "warning", 
            "RESTRICTED": "restriction",
            "HALT": "halt",
            "DELISTING": "delisting",
        }
        
        for stock in stocks:
            symbol = stock.get("code", "")
            control_status = str(stock.get("controlStatus", "")).upper()
            
            if control_status and control_status in status_map:
                result[symbol] = {
                    "status": status_map[control_status],
                    "name": stock.get("companyName", ""),
                    "exchange": stock.get("exchange", ""),
                    "source": "VNDirect",
                }
        
        log.info(f"VNDirect: Found {len(result)} warning/control stocks")
        return result
        
    except Exception as e:
        log.warning(f"VNDirect API failed: {e}")
        return {}


def fetch_from_tcbs() -> Dict[str, dict]:
    """Lấy từ TCBS API."""
    result = {}
    try:
        url = "https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/all-listing"
        
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        stocks = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(stocks, list):
            stocks = []
            
        log.info(f"TCBS: Fetched {len(stocks)} stocks")
        
        for stock in stocks:
            symbol = stock.get("ticker", stock.get("symbol", ""))
            status = str(stock.get("status", "")).upper()
            
            mapped_status = None
            if status in ["H", "HALT"]:
                mapped_status = "halt"
            elif status in ["C", "CONTROLLED"]:
                mapped_status = "control"
            elif status in ["W", "WARNING"]:
                mapped_status = "warning"
            
            if mapped_status:
                result[symbol] = {
                    "status": mapped_status,
                    "name": stock.get("shortName", stock.get("organName", "")),
                    "exchange": stock.get("exchange", ""),
                    "source": "TCBS",
                }
        
        log.info(f"TCBS: Found {len(result)} warning/control stocks")
        return result
        
    except Exception as e:
        log.warning(f"TCBS API failed: {e}")
        return {}


def fetch_from_ssi() -> Dict[str, dict]:
    """Lấy từ SSI API."""
    result = {}
    try:
        url = "https://iboard.ssi.com.vn/dchart/api/1.1/defaultAllStocks"
        
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        stocks = data.get("data", [])
        log.info(f"SSI: Fetched {len(stocks)} stocks")
        
        for stock in stocks:
            symbol = stock.get("code", stock.get("symbol", ""))
            status = str(stock.get("status", stock.get("tradingStatus", ""))).upper()
            
            mapped_status = None
            if "HALT" in status:
                mapped_status = "halt"
            elif "CONTROL" in status:
                mapped_status = "control"
            elif "WARN" in status:
                mapped_status = "warning"
            
            if mapped_status:
                result[symbol] = {
                    "status": mapped_status,
                    "name": stock.get("stockName", ""),
                    "exchange": stock.get("exchange", ""),
                    "source": "SSI",
                }
        
        log.info(f"SSI: Found {len(result)} warning/control stocks")
        return result
        
    except Exception as e:
        log.warning(f"SSI API failed: {e}")
        return {}


def fetch_from_cafef() -> Dict[str, dict]:
    """Scrape từ CafeF."""
    result = {}
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning("BeautifulSoup not installed, skipping CafeF")
        return {}
    
    try:
        pages = [
            ("https://cafef.vn/co-phieu-bi-kiem-soat.chn", "control"),
            ("https://cafef.vn/co-phieu-bi-canh-bao.chn", "warning"),
        ]
        
        for url, status in pages:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'lxml')
                
                text = soup.get_text()
                symbols = re.findall(r'\b([A-Z]{3})\b', text)
                
                for sym in set(symbols):
                    if sym.isalpha() and sym not in result:
                        result[sym] = {
                            "status": status,
                            "name": "",
                            "exchange": "",
                            "source": "CafeF",
                        }
            except Exception as e:
                log.warning(f"CafeF page {url} failed: {e}")
                continue
        
        log.info(f"CafeF: Found {len(result)} warning/control stocks")
        return result
        
    except Exception as e:
        log.warning(f"CafeF scraper failed: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════════════
# MAIN AGGREGATOR
# ════════════════════════════════════════════════════════════════════════════

def fetch_all_warning_stocks() -> Dict[str, dict]:
    """
    Tổng hợp từ tất cả nguồn.
    Priority: VNDirect > TCBS > SSI > CafeF > Fallback
    """
    result = {}
    sources_used = []
    
    # Try each source
    sources = [
        ("VNDirect", fetch_from_vndirect),
        ("TCBS", fetch_from_tcbs),
        ("SSI", fetch_from_ssi),
        ("CafeF", fetch_from_cafef),
    ]
    
    for name, fetcher in sources:
        try:
            data = fetcher()
            if data:
                count = 0
                for sym, info in data.items():
                    if sym not in result:
                        result[sym] = info
                        count += 1
                if count > 0:
                    sources_used.append(f"{name}({count})")
        except Exception as e:
            log.warning(f"Source {name} failed: {e}")
    
    # Fallback if no data
    if not result:
        log.warning("All APIs failed, using fallback list")
        for sym, status in FALLBACK_WARNING_STOCKS.items():
            result[sym] = {
                "status": status,
                "name": "",
                "exchange": "",
                "source": "Fallback",
            }
        sources_used.append(f"Fallback({len(FALLBACK_WARNING_STOCKS)})")
    else:
        # Merge với fallback để đảm bảo không thiếu
        for sym, status in FALLBACK_WARNING_STOCKS.items():
            if sym not in result:
                result[sym] = {
                    "status": status,
                    "name": "",
                    "exchange": "",
                    "source": "Fallback",
                }
    
    log.info(f"Total: {len(result)} warning stocks from {', '.join(sources_used)}")
    return result, sources_used


# ════════════════════════════════════════════════════════════════════════════
# EXPORT FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def export_to_json(data: Dict[str, dict], sources: List[str]) -> str:
    """Export ra file JSON đẹp để view."""
    
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Group by status
    by_status = {}
    for sym, info in data.items():
        status = info["status"]
        if status not in by_status:
            by_status[status] = []
        by_status[status].append({
            "symbol": sym,
            "name": info.get("name", ""),
            "exchange": info.get("exchange", ""),
            "source": info.get("source", ""),
        })
    
    # Sort each group by symbol
    for status in by_status:
        by_status[status] = sorted(by_status[status], key=lambda x: x["symbol"])
    
    # Build output
    output = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": sources,
        "total": len(data),
        "summary": {
            status: {
                "count": len(stocks),
                "penalty": f"-{int(WARNING_PENALTIES.get(status, {}).get('penalty', 0) * 100)}%",
                "description": WARNING_PENALTIES.get(status, {}).get('description', ''),
            }
            for status, stocks in by_status.items()
        },
        "stocks": by_status,
    }
    
    # Write file
    output_path = os.path.join(EXPORT_DIR, "warning_stocks.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log.info(f"✅ Exported to {output_path}")
    return output_path


def update_database(data: Dict[str, dict]) -> int:
    """Cập nhật warning_status vào database symbols table."""
    
    if not os.path.exists(DB_PATH):
        log.warning(f"Database not found: {DB_PATH}")
        return 0
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        
        # Check if warning_status column exists
        cursor.execute("PRAGMA table_info(symbols)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "warning_status" not in columns:
            log.info("Adding warning_status column to symbols table")
            cursor.execute("ALTER TABLE symbols ADD COLUMN warning_status TEXT DEFAULT 'normal'")
        
        # Reset all to normal first
        cursor.execute("UPDATE symbols SET warning_status = 'normal'")
        
        # Update warning stocks
        updated = 0
        for sym, info in data.items():
            cursor.execute(
                "UPDATE symbols SET warning_status = ? WHERE symbol = ?",
                (info["status"], sym)
            )
            if cursor.rowcount > 0:
                updated += 1
        
        conn.commit()
        conn.close()
        
        log.info(f"✅ Updated {updated} symbols in database")
        return updated
        
    except Exception as e:
        log.error(f"Database update failed: {e}")
        return 0


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def run():
    """Main entry point."""
    log.info("="*60)
    log.info("🔍 WEEKLY WARNING STATUS COLLECTOR")
    log.info("="*60)
    
    # Fetch data
    log.info("\n📡 Fetching from APIs...")
    data, sources = fetch_all_warning_stocks()
    
    # Summary
    by_status = {}
    for sym, info in data.items():
        status = info["status"]
        by_status[status] = by_status.get(status, 0) + 1
    
    log.info("\n📊 Summary:")
    for status in ['control', 'warning', 'restriction', 'halt', 'delisting']:
        if status in by_status:
            penalty = WARNING_PENALTIES.get(status, {}).get('penalty', 0)
            log.info(f"   {status.upper():12} : {by_status[status]:3} stocks (penalty: -{int(penalty*100)}%)")
    
    # Export JSON
    log.info("\n💾 Exporting...")
    json_path = export_to_json(data, sources)
    
    # Update database
    log.info("\n🗄️  Updating database...")
    updated = update_database(data)
    
    # Final summary
    log.info("\n" + "="*60)
    log.info("✅ COMPLETED")
    log.info(f"   Total warning stocks: {len(data)}")
    log.info(f"   Export file: {json_path}")
    log.info(f"   Database updated: {updated} symbols")
    log.info("="*60)


if __name__ == "__main__":
    run()
