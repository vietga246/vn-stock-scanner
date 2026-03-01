"""inspect_db.py - Kiem tra nhanh data trong stock.db
Chay: python scripts/inspect_db.py
"""
import sqlite3
import os
import sys

DB_PATH = os.getenv('DB_PATH', 'data/stock.db')

def sep(title=''):
    print('\n' + '='*60)
    if title:
        print(f'  {title}')
        print('='*60)

def run(conn, sql):
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    widths = [max(len(c), max((len(str(r[i])) for r in rows), default=0)) for i, c in enumerate(cols)]
    fmt = '  ' + '  '.join(f'{{:<{w}}}' for w in widths)
    print(fmt.format(*cols))
    print('  ' + '  '.join('-'*w for w in widths))
    for row in rows:
        print(fmt.format(*[str(v) if v is not None else 'NULL' for v in row]))
    return rows

if not os.path.exists(DB_PATH):
    print(f'ERROR: DB not found at {DB_PATH}')
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)

sep('ROW COUNTS')
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]
for t in tables:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t:<35} {n:>8} rows')

sep('FINANCIALS_META - 10 dong moi nhat')
try:
    run(conn, """
        SELECT symbol, updated_at
        FROM financials_meta
        ORDER BY updated_at DESC
        LIMIT 10
    """)
except Exception as e:
    print(f'  Loi: {e}')

sep('FINANCIALS_RATIO - mau VCB')
try:
    run(conn, """
        SELECT symbol, year, quarter, pe, pb, roe, roa, net_margin, revenue_growth
        FROM financials_ratio
        WHERE symbol='VCB'
        ORDER BY year DESC, quarter DESC
        LIMIT 8
    """)
except Exception as e:
    print(f'  Loi: {e}')

sep('FINANCIALS_INCOME - mau FPT')
try:
    run(conn, """
        SELECT symbol, year, quarter, revenue, gross_profit, net_profit
        FROM financials_income
        WHERE symbol='FPT'
        ORDER BY year DESC, quarter DESC
        LIMIT 8
    """)
except Exception as e:
    print(f'  Loi: {e}')

sep('FINANCIALS_BALANCE - mau VIC')
try:
    run(conn, """
        SELECT symbol, year, quarter, total_assets, total_equity, total_debt, cash
        FROM financials_balance
        WHERE symbol='VIC'
        ORDER BY year DESC, quarter DESC
        LIMIT 8
    """)
except Exception as e:
    print(f'  Loi: {e}')

sep('FINANCIALS_CASHFLOW - mau VCB')
try:
    run(conn, """
        SELECT symbol, year, quarter, cfo, cfi, cff, fcf
        FROM financials_cashflow
        WHERE symbol='VCB'
        ORDER BY year DESC, quarter DESC
        LIMIT 8
    """)
except Exception as e:
    print(f'  Loi: {e}')

sep('STOCK_PRICES - 5 dong moi nhat')
try:
    run(conn, """
        SELECT symbol, date, open, high, low, close, volume
        FROM stock_prices
        ORDER BY date DESC, symbol
        LIMIT 5
    """)
except Exception as e:
    print(f'  Loi: {e}')

sep('DB SIZE')
size = os.path.getsize(DB_PATH)
print(f'  {DB_PATH}: {size/1024/1024:.2f} MB')

conn.close()
print('\n' + '='*60)
print('  DONE')
print('='*60)
