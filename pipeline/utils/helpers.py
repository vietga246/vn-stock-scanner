"""
helpers.py — Shared Helper Functions

Centralized utilities used across all pipeline modules:
- Date normalization (consistent YYYY-MM-DD format)
- Safe type conversions (handle NaN, None, invalid values)
- Bond/warrant filtering
- Database connection factory
- Logging setup
"""

import sqlite3
import logging
import sys
import os
import re
import math
from datetime import datetime
from typing import Optional, Any, Union
import pandas as pd


# ════════════════════════════════════════════════════════════════════════════
# DATE HANDLING
# ════════════════════════════════════════════════════════════════════════════

def normalize_date(val: Any) -> Optional[str]:
    """
    Normalize any date value to YYYY-MM-DD string format.
    
    Handles:
    - datetime objects
    - pandas Timestamp
    - ISO strings with timestamp (2024-01-15T10:30:00)
    - Date strings (2024-01-15)
    - None/NaT
    
    Returns:
        YYYY-MM-DD string or None if invalid
        
    Examples:
        >>> normalize_date("2024-01-15T10:30:00")
        "2024-01-15"
        >>> normalize_date(datetime(2024, 1, 15))
        "2024-01-15"
        >>> normalize_date(None)
        None
    """
    if val is None:
        return None
    
    # Handle pandas NaT
    if pd.isna(val):
        return None
    
    # String: truncate to first 10 chars (YYYY-MM-DD)
    if isinstance(val, str):
        if len(val) >= 10:
            return val[:10]
        return val
    
    # datetime or Timestamp
    if hasattr(val, 'strftime'):
        return val.strftime("%Y-%m-%d")
    
    # Try pandas conversion as fallback
    try:
        return pd.to_datetime(val).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_date(val: Any) -> Optional[datetime]:
    """
    Parse any date value to datetime object.
    
    Returns:
        datetime object or None if invalid
    """
    if val is None or pd.isna(val):
        return None
    
    if isinstance(val, datetime):
        return val
    
    try:
        return pd.to_datetime(val).to_pydatetime()
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# SAFE TYPE CONVERSIONS
# ════════════════════════════════════════════════════════════════════════════

def safe_float(val: Any, decimals: Optional[int] = None) -> Optional[float]:
    """
    Safely convert value to float, handling NaN and invalid values.
    
    Args:
        val: Value to convert
        decimals: If provided, round to this many decimal places
        
    Returns:
        float value or None if invalid/NaN
        
    Examples:
        >>> safe_float("123.456", decimals=2)
        123.46
        >>> safe_float(float('nan'))
        None
        >>> safe_float(None)
        None
    """
    if val is None:
        return None
    
    try:
        f = float(val)
        # NaN check: NaN != NaN
        if f != f:
            return None
        # Infinity check
        if math.isinf(f):
            return None
        if decimals is not None:
            return round(f, decimals)
        return f
    except (TypeError, ValueError):
        return None


def safe_int(val: Any) -> Optional[int]:
    """
    Safely convert value to int, handling invalid values.
    
    Returns:
        int value or None if invalid
    """
    if val is None:
        return None
    
    try:
        f = float(val)
        if f != f or math.isinf(f):  # NaN or Inf
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def safe_pct(val: Any, decimals: int = 2) -> Optional[float]:
    """
    Convert ratio (0-1) to percentage (0-100), safely.
    
    Args:
        val: Ratio value (e.g., 0.15 for 15%)
        decimals: Decimal places for result
        
    Returns:
        Percentage value or None
        
    Examples:
        >>> safe_pct(0.1567)
        15.67
    """
    f = safe_float(val)
    if f is None:
        return None
    return round(f * 100, decimals)


def safe_bil(val: Any, decimals: int = 2) -> Optional[float]:
    """
    Convert raw VND to billions (tỷ đồng).
    
    Args:
        val: Value in VND
        decimals: Decimal places for result
        
    Returns:
        Value in billions or None
    """
    f = safe_float(val)
    if f is None:
        return None
    return round(f / 1e9, decimals)


# ════════════════════════════════════════════════════════════════════════════
# WAIT TIME PARSING
# ════════════════════════════════════════════════════════════════════════════

def extract_wait_time(error_message: str, default: int = 65) -> int:
    """
    Parse wait time from server rate limit error message.
    
    Handles both Vietnamese and English messages:
    - "Chờ 27 giây" / "Cho 27 giay"
    - "Wait 27 seconds"
    - "retry after 27"
    
    Args:
        error_message: Error message string
        default: Default wait time if parsing fails
        
    Returns:
        Wait time in seconds (parsed value + 1 buffer)
    """
    if not error_message:
        return default
    
    patterns = [
        r"[Cc]h[oờ]\s+(\d+)\s*gi[aâ]y?",   # Vietnamese
        r"[Ww]ait\s+(\d+)\s*second",         # English
        r"retry\s*after\s*(\d+)",            # Retry after
        r"(\d+)\s*second",                   # Fallback
    ]
    
    msg_lower = error_message.lower()
    for pattern in patterns:
        match = re.search(pattern, msg_lower)
        if match:
            return int(match.group(1)) + 1  # Add 1s buffer
    
    return default


# ════════════════════════════════════════════════════════════════════════════
# SYMBOL FILTERING
# ════════════════════════════════════════════════════════════════════════════

# Pattern for bond symbols: 2-4 letters followed by 4+ digits, total > 6 chars
# Examples: CACB2510, CVMM2520, VHM12345
BOND_PATTERN = re.compile(r'^[A-Z]{2,4}\d{4,}$')

# Pattern for futures: starts with FU (VN30 futures, etc.)
# Examples: FUEMAVND, FUEKIV30, FUCTVGF4, FUEFCV50, FUETCC50
FUTURES_PATTERN = re.compile(r'^FU[A-Z0-9]+$')

# Pattern for covered warrants: ends with digits after stock code
# Examples: CACB2401, CHPG2318, CFPT2401
WARRANT_PATTERN = re.compile(r'^C[A-Z]{2,3}\d{4}$')


def is_bond(symbol: str) -> bool:
    """
    Check if symbol is a bond (trái phiếu).
    
    Bond symbols typically have format: 2-4 letters + 4+ digits
    Examples: CACB2510, CVMM2520
    
    Args:
        symbol: Stock symbol to check
        
    Returns:
        True if symbol appears to be a bond
    """
    if not symbol or len(symbol) <= 6:
        return False
    return bool(BOND_PATTERN.match(symbol))


def is_derivative(symbol: str) -> bool:
    """
    Check if symbol is a derivative (futures, covered warrant).
    
    Futures patterns:
    - FUE...: Futures VN30 (e.g., FUEMAVND, FUEKIV30)
    - FUC...: Futures contracts (e.g., FUCTVGF4)
    - FUE...: ETF futures (e.g., FUEFCV50, FUETCC50)
    
    Covered warrant patterns:
    - C + stock code + 4 digits (e.g., CHPG2318)
    
    Args:
        symbol: Stock symbol to check
        
    Returns:
        True if symbol is a derivative (not a regular stock)
    """
    if not symbol:
        return False
    
    # Check futures (starts with FU)
    if FUTURES_PATTERN.match(symbol):
        return True
    
    # Check covered warrants (C + code + digits)
    if WARRANT_PATTERN.match(symbol):
        return True
    
    return False


def is_stock(symbol: str) -> bool:
    """
    Check if symbol is a regular stock (not bond, futures, ETF, or warrant).

    Valid Vietnamese stock codes:
    - HOSE: exactly 3 uppercase letters (e.g. FPT, VCB, HPG)
    - HNX:  3 chars starting with a letter, may contain digits (e.g. S99, D2D, VC3, PC1)

    Excluded:
    - Covered warrants: C + 2-3 letters + 4 digits, total 7-8 chars (e.g. CHPG2401)
    - Futures: start with FU (e.g. FUEMAVND, FUEKIV30)
    - ETFs: start with E1 or similar (e.g. E1VFVN30)
    - Bonds: 2-4 letters + 4+ digits, total > 6 chars (e.g. CACB2510001)

    Args:
        symbol: Stock symbol to check

    Returns:
        True if symbol is a regular stock
    """
    if not symbol:
        return False

    # Must be exactly 3 characters, starting with a letter, rest alphanumeric
    if not re.match(r'^[A-Z][A-Z0-9]{2}$', symbol):
        return False

    return True


def filter_stocks(symbols: list, warrants: set = None) -> list:
    """
    Filter list of symbols to keep only stocks.
    
    Removes:
    - Bonds (detected by pattern)
    - Covered warrants (if warrant list provided)
    
    Args:
        symbols: List of all symbols
        warrants: Optional set of warrant symbols to exclude
        
    Returns:
        Filtered list of stock symbols
    """
    warrants = warrants or set()
    return [
        s for s in symbols
        if not is_bond(s) and s not in warrants
    ]


# ════════════════════════════════════════════════════════════════════════════
# DATABASE UTILITIES
# ════════════════════════════════════════════════════════════════════════════

def create_db_connection(
    db_path: str = None,
    timeout: int = 60,
    enable_wal: bool = True,
    cache_size_mb: int = 32,
) -> sqlite3.Connection:
    """
    Create optimized SQLite connection.
    
    Args:
        db_path: Path to database file (default: from DB_PATH env)
        timeout: Connection timeout in seconds
        enable_wal: Enable WAL journal mode
        cache_size_mb: Cache size in megabytes
        
    Returns:
        Configured sqlite3.Connection
    """
    if db_path is None:
        db_path = os.getenv("DB_PATH", "data/db/stock.db")
    
    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path, timeout=timeout)
    
    # Performance optimizations
    if enable_wal:
        conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(f"PRAGMA busy_timeout={timeout * 1000};")
    conn.execute(f"PRAGMA cache_size=-{cache_size_mb * 1024};")  # Negative = KB
    conn.execute("PRAGMA temp_store=MEMORY;")
    
    return conn


# ════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ════════════════════════════════════════════════════════════════════════════

def setup_logging(
    level: int = logging.INFO,
    format_str: str = "%(asctime)s [%(levelname)s] %(message)s",
) -> logging.Logger:
    """
    Setup consistent logging configuration.
    
    Args:
        level: Logging level (default: INFO)
        format_str: Log message format
        
    Returns:
        Configured logger
    """
    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# PANDAS HELPERS
# ════════════════════════════════════════════════════════════════════════════

def df_to_records(df: pd.DataFrame, date_col: str = "date") -> list:
    """
    Convert DataFrame to list of dicts with normalized dates.
    
    Faster than iterrows() and ensures consistent date format.
    
    Args:
        df: DataFrame to convert
        date_col: Name of date column to normalize
        
    Returns:
        List of dictionaries
    """
    records = df.to_dict("records")
    
    if date_col in df.columns:
        for record in records:
            record[date_col] = normalize_date(record.get(date_col))
    
    return records
