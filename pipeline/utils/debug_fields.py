"""debug_fields.py - In ra ten cot thuc te tu vnstock API de check field mapping
Upload len scripts/debug_fields.py roi chay qua workflow debug_fields.yml
"""
import os, sys, json
from vnstock import Finance
import pandas as pd

API_KEY = os.getenv('VNSTOCK_API_KEY', '')
if API_KEY:
    os.environ['VNSTOCK_API_KEY'] = API_KEY
    print("Using API key")

def flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ['_'.join(str(c) for c in col).strip('_') for col in df.columns]
    return df

def sep(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

symbol = 'FPT'
print(f"Kiem tra symbol: {symbol}")
f = Finance(symbol=symbol, source='VCI', period='quarter', get_all=True)

# --- ratio ---
sep("ratio()")
try:
    df = f.ratio()
    if df is None or df.empty:
        print("  EMPTY")
    else:
        print(f"  Shape: {df.shape}")
        print(f"  Index type: {type(df.index)}")
        print(f"  Index[:3]: {list(df.index[:3])}")
        print(f"  Columns: {list(df.columns)}")
        print(f"  Sample row (transposed):")
        df_T = df.T
        print(df_T.head(3).to_string())
except Exception as e:
    print(f"  ERROR: {e}")

# --- income_statement ---
sep("income_statement()")
try:
    df = flatten(f.income_statement())
    if df is None or df.empty:
        print("  EMPTY")
    else:
        print(f"  Shape: {df.shape}")
        print(f"  Columns: {list(df.columns)}")
        print(f"\n  Sample (3 rows):")
        print(df.head(3).to_string())
except Exception as e:
    print(f"  ERROR: {e}")

# --- balance_sheet ---
sep("balance_sheet()")
try:
    df = flatten(f.balance_sheet())
    if df is None or df.empty:
        print("  EMPTY")
    else:
        print(f"  Shape: {df.shape}")
        print(f"  Columns: {list(df.columns)}")
        print(f"\n  Sample (3 rows):")
        print(df.head(3).to_string())
except Exception as e:
    print(f"  ERROR: {e}")

# --- cash_flow ---
sep("cash_flow()")
try:
    df = flatten(f.cash_flow())
    if df is None or df.empty:
        print("  EMPTY")
    else:
        print(f"  Shape: {df.shape}")
        print(f"  Columns: {list(df.columns)}")
        print(f"\n  Sample (3 rows):")
        print(df.head(3).to_string())
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "="*60)
print("  DONE")
print("="*60)
