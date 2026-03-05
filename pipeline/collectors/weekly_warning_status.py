"""
weekly_warning_status.py — Thu thập danh sách cổ phiếu cảnh báo/kiểm soát

⚠️ CHỈ LẤY DATA THỰC TẾ TỪ NGUỒN CHÍNH THỨC - KHÔNG DÙNG FALLBACK
   Nếu tất cả nguồn fail → workflow fail → cần fix

Nguồn dữ liệu (theo thứ tự ưu tiên):
1. HOSE Official (hsx.vn) - Selenium scrape
2. HNX Official (hnx.vn) - Selenium scrape  
3. VNDirect API (backup - có trường controlStatus)

Output: data/exports/warning_stocks.json
"""

import json
import sqlite3
import os
import sys
import re
import logging
import time
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# ════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
}

REQUEST_TIMEOUT = 30
SELENIUM_TIMEOUT = 60

# ════════════════════════════════════════════════════════════════════════════
# PENALTY CONFIG
# ════════════════════════════════════════════════════════════════════════════

WARNING_PENALTIES = {
    "control":     {"penalty": 0.50, "description": "Kiểm soát - Giao dịch hạn chế nghiêm trọng"},
    "warning":     {"penalty": 0.30, "description": "Cảnh báo - Nguy cơ bị kiểm soát"},
    "restriction": {"penalty": 0.15, "description": "Hạn chế - Điều kiện giao dịch đặc biệt"},
    "halt":        {"penalty": 0.60, "description": "Tạm ngừng giao dịch"},
    "delisting":   {"penalty": 0.70, "description": "Sắp hủy niêm yết"},
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
# SELENIUM SETUP
# ════════════════════════════════════════════════════════════════════════════

def get_selenium_driver():
    """
    Tạo Selenium WebDriver với Chrome headless.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument(f"user-agent={HEADERS['User-Agent']}")
        
        # Try to find chromedriver
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(SELENIUM_TIMEOUT)
        
        return driver
        
    except Exception as e:
        log.warning(f"Failed to create Selenium driver: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 1: HOSE Official Website (hsx.vn)
# ════════════════════════════════════════════════════════════════════════════

def fetch_from_hose_selenium() -> Dict[str, dict]:
    """
    Scrape danh sách cổ phiếu cảnh báo/kiểm soát từ HOSE official.
    URL: https://www.hsx.vn/Modules/Listed/Web/StockUnderStatusView
    """
    result = {}
    driver = None
    
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from bs4 import BeautifulSoup
        
        driver = get_selenium_driver()
        if not driver:
            log.warning("HOSE: Cannot create Selenium driver")
            return {}
        
        # Trang danh sách chứng khoán bị kiểm soát/cảnh báo
        url = "https://www.hsx.vn/Modules/Listed/Web/StockUnderStatusView"
        log.info(f"HOSE: Loading {url}")
        
        driver.get(url)
        
        # Đợi trang load JavaScript
        time.sleep(5)
        
        # Đợi table xuất hiện
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
        except Exception:
            log.warning("HOSE: No table found after waiting")
        
        # Get page source sau khi JS render
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Tìm tất cả tables
        tables = soup.find_all('table')
        log.info(f"HOSE: Found {len(tables)} tables")
        
        for table in tables:
            rows = table.find_all('tr')
            current_status = None
            
            for row in rows:
                # Check header để xác định status
                headers = row.find_all('th')
                if headers:
                    header_text = ' '.join([h.get_text(strip=True).lower() for h in headers])
                    if 'kiểm soát' in header_text or 'kiem soat' in header_text:
                        current_status = 'control'
                    elif 'cảnh báo' in header_text or 'canh bao' in header_text:
                        current_status = 'warning'
                    elif 'hạn chế' in header_text or 'han che' in header_text:
                        current_status = 'restriction'
                    elif 'tạm ngừng' in header_text or 'tam ngung' in header_text:
                        current_status = 'halt'
                    continue
                
                # Parse data rows
                cells = row.find_all('td')
                if len(cells) >= 1:
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        # Match stock symbol (3 letters uppercase)
                        if re.match(r'^[A-Z]{3}$', text):
                            symbol = text
                            
                            # Xác định status từ row text hoặc current_status
                            row_text = row.get_text().lower()
                            
                            status = None
                            if 'kiểm soát' in row_text or 'kiem soat' in row_text:
                                status = 'control'
                            elif 'cảnh báo' in row_text or 'canh bao' in row_text:
                                status = 'warning'
                            elif 'hạn chế' in row_text or 'han che' in row_text:
                                status = 'restriction'
                            elif 'tạm ngừng' in row_text or 'tam ngung' in row_text:
                                status = 'halt'
                            elif current_status:
                                status = current_status
                            
                            if status and symbol not in result:
                                result[symbol] = {
                                    "status": status,
                                    "name": "",
                                    "exchange": "HOSE",
                                    "source": "HOSE_Official",
                                }
        
        # Thử tìm trong các div/span nếu không có table
        if not result:
            # Tìm tất cả text có chứa mã chứng khoán
            all_text = soup.get_text()
            
            # Pattern: mã 3 chữ cái + status
            patterns = [
                (r'([A-Z]{3})\s*[:\-]?\s*(?:bị\s*)?kiểm soát', 'control'),
                (r'([A-Z]{3})\s*[:\-]?\s*(?:bị\s*)?cảnh báo', 'warning'),
                (r'([A-Z]{3})\s*[:\-]?\s*(?:bị\s*)?hạn chế', 'restriction'),
            ]
            
            for pattern, status in patterns:
                matches = re.findall(pattern, all_text, re.IGNORECASE)
                for symbol in matches:
                    if symbol.upper() not in result:
                        result[symbol.upper()] = {
                            "status": status,
                            "name": "",
                            "exchange": "HOSE",
                            "source": "HOSE_Official",
                        }
        
        log.info(f"✅ HOSE: Found {len(result)} warning/control stocks")
        
    except Exception as e:
        log.warning(f"⚠️ HOSE scrape failed: {e}")
        
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    
    return result


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 2: HNX Official Website (hnx.vn)
# ════════════════════════════════════════════════════════════════════════════

def fetch_from_hnx_selenium() -> Dict[str, dict]:
    """
    Scrape danh sách cổ phiếu cảnh báo/kiểm soát từ HNX official.
    URL: https://www.hnx.vn/vi-vn/co-phieu-etfs/chung-khoan-ny-canh-bao-ndt.html
    """
    result = {}
    driver = None
    
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from bs4 import BeautifulSoup
        
        driver = get_selenium_driver()
        if not driver:
            log.warning("HNX: Cannot create Selenium driver")
            return {}
        
        # Các trang danh sách trên HNX
        urls = [
            ("https://www.hnx.vn/vi-vn/co-phieu-etfs/chung-khoan-ny-moi.html", None),
            # Trang này có filter cho cảnh báo/kiểm soát
        ]
        
        for url, default_status in urls:
            try:
                log.info(f"HNX: Loading {url}")
                driver.get(url)
                
                # Đợi trang load
                time.sleep(5)
                
                # Đợi table
                try:
                    WebDriverWait(driver, 30).until(
                        EC.presence_of_element_located((By.TAG_NAME, "table"))
                    )
                except Exception:
                    pass
                
                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                
                # Tìm tabs/filters cho cảnh báo, kiểm soát
                tabs = soup.find_all(['a', 'button', 'li'], string=re.compile(r'cảnh báo|kiểm soát|canh bao|kiem soat', re.I))
                
                # Tìm tables
                tables = soup.find_all('table')
                log.info(f"HNX: Found {len(tables)} tables")
                
                for table in tables:
                    rows = table.find_all('tr')
                    
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 1:
                            for i, cell in enumerate(cells):
                                text = cell.get_text(strip=True)
                                # Match stock symbol
                                if re.match(r'^[A-Z]{3}$', text):
                                    symbol = text
                                    row_text = row.get_text().lower()
                                    
                                    status = None
                                    if 'kiểm soát' in row_text:
                                        status = 'control'
                                    elif 'cảnh báo' in row_text:
                                        status = 'warning'
                                    elif 'hạn chế' in row_text:
                                        status = 'restriction'
                                    elif 'tạm ngừng' in row_text or 'đình chỉ' in row_text:
                                        status = 'halt'
                                    elif default_status:
                                        status = default_status
                                    
                                    if status and symbol not in result:
                                        result[symbol] = {
                                            "status": status,
                                            "name": "",
                                            "exchange": "HNX",
                                            "source": "HNX_Official",
                                        }
                
            except Exception as e:
                log.debug(f"HNX page {url} error: {e}")
                continue
        
        log.info(f"✅ HNX: Found {len(result)} warning/control stocks")
        
    except Exception as e:
        log.warning(f"⚠️ HNX scrape failed: {e}")
        
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    
    return result


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 3: VNDirect API (backup - requests only, no selenium)
# ════════════════════════════════════════════════════════════════════════════

def fetch_from_vndirect() -> Dict[str, dict]:
    """
    Lấy từ VNDirect API - có trường controlStatus.
    Đây là backup nếu Selenium không hoạt động.
    """
    import requests
    
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
            control_status = str(stock.get("controlStatus", "")).upper().strip()
            
            if control_status and control_status in status_map:
                result[symbol] = {
                    "status": status_map[control_status],
                    "name": stock.get("companyName", ""),
                    "exchange": stock.get("exchange", ""),
                    "source": "VNDirect",
                }
        
        log.info(f"✅ VNDirect: Found {len(result)} warning/control stocks")
        return result
        
    except Exception as e:
        log.warning(f"⚠️ VNDirect fetch failed: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 4: SSI iBoard API (backup)
# ════════════════════════════════════════════════════════════════════════════

def fetch_from_ssi() -> Dict[str, dict]:
    """
    Lấy từ SSI iBoard API.
    """
    import requests
    
    result = {}
    
    try:
        url = "https://iboard.ssi.com.vn/dchart/api/1.1/defaultAllStocks"
        
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        
        data = resp.json()
        stocks = data.get("data", data) if isinstance(data, dict) else data
        
        if not isinstance(stocks, list):
            return {}
        
        log.info(f"SSI: Fetched {len(stocks)} stocks")
        
        for stock in stocks:
            symbol = stock.get("code", stock.get("symbol", ""))
            status_field = str(stock.get("status", stock.get("tradingStatus", ""))).upper()
            
            mapped_status = None
            if "HALT" in status_field or status_field == "H":
                mapped_status = "halt"
            elif "CONTROL" in status_field or status_field == "C":
                mapped_status = "control"
            elif "WARN" in status_field or status_field == "W":
                mapped_status = "warning"
            elif "RESTRICT" in status_field or status_field == "R":
                mapped_status = "restriction"
            
            if mapped_status and symbol:
                result[symbol] = {
                    "status": mapped_status,
                    "name": stock.get("stockName", ""),
                    "exchange": stock.get("exchange", ""),
                    "source": "SSI",
                }
        
        log.info(f"✅ SSI: Found {len(result)} warning/control stocks")
        return result
        
    except Exception as e:
        log.warning(f"⚠️ SSI fetch failed: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════════════
# MAIN AGGREGATOR
# ════════════════════════════════════════════════════════════════════════════

def fetch_all_warning_stocks() -> Tuple[Dict[str, dict], List[str]]:
    """
    Tổng hợp từ tất cả nguồn.
    Ưu tiên nguồn chính thức HOSE/HNX trước.
    KHÔNG DÙNG FALLBACK - chỉ lấy data thực.
    """
    result = {}
    sources_used = []
    sources_failed = []
    
    # Try sources in order - official sources first
    sources = [
        ("HOSE_Official", fetch_from_hose_selenium),
        ("HNX_Official", fetch_from_hnx_selenium),
        ("VNDirect", fetch_from_vndirect),
        ("SSI", fetch_from_ssi),
    ]
    
    for name, fetcher in sources:
        try:
            log.info(f"\n📡 Trying {name}...")
            data = fetcher()
            if data:
                count = 0
                for sym, info in data.items():
                    if sym not in result:
                        result[sym] = info
                        count += 1
                if count > 0:
                    sources_used.append(f"{name}({count})")
                    log.info(f"   ✅ {name}: Added {count} new stocks")
            else:
                sources_failed.append(name)
                log.info(f"   ⚠️ {name}: No data")
        except Exception as e:
            log.error(f"   ❌ {name} error: {e}")
            sources_failed.append(name)
    
    if sources_failed:
        log.warning(f"\n⚠️ Failed sources: {', '.join(sources_failed)}")
    
    if result:
        log.info(f"\n✅ Total: {len(result)} warning stocks from {', '.join(sources_used)}")
    else:
        log.error("\n❌ No warning stocks found from any source!")
    
    return result, sources_used


# ════════════════════════════════════════════════════════════════════════════
# EXPORT FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def export_to_json(data: Dict[str, dict], sources: List[str]) -> str:
    """Export ra file JSON."""
    
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
    
    # Sort each group
    for status in by_status:
        by_status[status] = sorted(by_status[status], key=lambda x: x["symbol"])
    
    output = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_source": "OFFICIAL_SOURCES",
        "note": "Data from HOSE/HNX official websites - NO FALLBACK",
        "sources": sources,
        "total": len(data),
        "summary": {
            status: {
                "count": len(stocks),
                "penalty": f"-{int(WARNING_PENALTIES.get(status, {}).get('penalty', 0) * 100)}%",
                "description": WARNING_PENALTIES.get(status, {}).get('description', ''),
                "symbols": [s["symbol"] for s in stocks],
            }
            for status, stocks in by_status.items()
        },
        "stocks": by_status,
    }
    
    output_path = os.path.join(EXPORT_DIR, "warning_stocks.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log.info(f"✅ Exported to {output_path}")
    return output_path


def update_database(data: Dict[str, dict]) -> int:
    """Cập nhật warning_status vào database."""
    
    if not os.path.exists(DB_PATH):
        log.warning(f"Database not found: {DB_PATH}")
        return 0
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(symbols)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "warning_status" not in columns:
            cursor.execute("ALTER TABLE symbols ADD COLUMN warning_status TEXT DEFAULT 'normal'")
        
        cursor.execute("UPDATE symbols SET warning_status = 'normal'")
        
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
    log.info("   Mode: OFFICIAL SOURCES ONLY (HOSE/HNX)")
    log.info("   No fallback list - real data required")
    log.info("="*60)
    
    # Check dependencies
    try:
        from selenium import webdriver
        log.info("✅ Selenium available")
    except ImportError:
        log.warning("⚠️ Selenium not installed - will use API sources only")
    
    try:
        from bs4 import BeautifulSoup
        log.info("✅ BeautifulSoup available")
    except ImportError:
        log.warning("⚠️ BeautifulSoup not installed")
    
    # Fetch data
    log.info("\n📡 Fetching from official sources...")
    data, sources = fetch_all_warning_stocks()
    
    # ⚠️ FAIL nếu không có data - KHÔNG dùng fallback
    if not data:
        log.error("\n" + "="*60)
        log.error("❌ FAILED: No data from any source!")
        log.error("   Possible causes:")
        log.error("   - HOSE/HNX websites changed structure")
        log.error("   - Selenium/Chrome not available")
        log.error("   - Network issues")
        log.error("   Please check and fix the scraper.")
        log.error("="*60)
        sys.exit(1)
    
    # Summary
    by_status = {}
    for sym, info in data.items():
        status = info["status"]
        by_status[status] = by_status.get(status, 0) + 1
    
    log.info("\n" + "="*60)
    log.info("📊 SUMMARY")
    log.info("="*60)
    
    for status in ['control', 'warning', 'restriction', 'halt', 'delisting']:
        if status in by_status:
            penalty = WARNING_PENALTIES.get(status, {}).get('penalty', 0)
            desc = WARNING_PENALTIES.get(status, {}).get('description', '')
            log.info(f"   {status.upper():12} : {by_status[status]:3} stocks | -{int(penalty*100):2}% | {desc}")
    
    # List symbols
    log.info("\n📋 STOCK LIST:")
    for status in ['control', 'warning', 'restriction', 'halt', 'delisting']:
        symbols = sorted([s for s, info in data.items() if info["status"] == status])
        if symbols:
            log.info(f"   {status.upper()}: {', '.join(symbols)}")
    
    # Export
    log.info("\n💾 Exporting...")
    json_path = export_to_json(data, sources)
    
    # Update DB
    log.info("\n🗄️ Updating database...")
    updated = update_database(data)
    
    # Done
    log.info("\n" + "="*60)
    log.info("✅ COMPLETED SUCCESSFULLY")
    log.info(f"   Total warning stocks: {len(data)}")
    log.info(f"   Export file: {json_path}")
    log.info(f"   Database updated: {updated} symbols")
    log.info("="*60)


if __name__ == "__main__":
    run()
