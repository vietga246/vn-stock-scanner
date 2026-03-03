"""inspect_db.py - Kiem tra data trong stock.db"""
import sqlite3, os, sys

DB_PATH = os.getenv('DB_PATH', 'data/db/stock.db')

def sep(title=''):
    print(f"\n{'='*70}\n  {title}\n{'='*70}")

def run(conn, sql):
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        print("  (empty)")
        return
    widths = [max(len(c), max(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)]
    fmt = '  ' + '  '.join(f'{{:<{w}}}' for w in widths)
    print(fmt.format(*cols))
    print('  ' + '  '.join('-'*w for w in widths))
    for row in rows:
        print(fmt.format(*[str(v) if v is not None else 'NULL' for v in row]))

if not os.path.exists(DB_PATH):
    print(f'ERROR: DB not found at {DB_PATH}'); sys.exit(1)

conn = sqlite3.connect(DB_PATH)

sep('ROW COUNTS')
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
for t in tables:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t:<35} {n:>8} rows')

sep('INDEXES')
rows = conn.execute(
    "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name"
).fetchall()
if rows:
    for r in rows:
        print(f'  {r[1]:<30} -> {r[0]}')
else:
    print('  (no indexes)')

sep('FINANCIALS_RATIO - VCB (5 quy moi nhat)')
run(conn, """
    SELECT symbol, year, quarter,
           ROUND(pe,2) as pe, ROUND(pb,2) as pb,
           ROUND(roe,2) as roe_pct, ROUND(roa,2) as roa_pct,
           ROUND(net_margin,2) as net_margin_pct,
           ROUND(debt_equity,2) as debt_eq,
           ROUND(current_ratio,2) as cur_ratio
    FROM financials_ratio WHERE symbol='VCB'
    ORDER BY year DESC, quarter DESC LIMIT 5
""")

sep('FINANCIALS_INCOME - FPT (5 quy moi nhat, don vi: ty dong)')
run(conn, """
    SELECT symbol, year, quarter,
           ROUND(revenue/1e9,0)       as revenue_ty,
           ROUND(gross_profit/1e9,0)  as gross_profit_ty,
           ROUND(net_profit/1e9,0)    as net_profit_ty,
           ROUND(revenue_growth,1)    as rev_growth_pct
    FROM financials_income WHERE symbol='FPT'
    ORDER BY year DESC, quarter DESC LIMIT 5
""")

sep('FINANCIALS_BALANCE - VIC (5 quy moi nhat, don vi: ty dong)')
run(conn, """
    SELECT symbol, year, quarter,
           ROUND(total_assets/1e9,0)  as assets_ty,
           ROUND(total_equity/1e9,0)  as equity_ty,
           ROUND(total_debt/1e9,0)    as debt_ty,
           ROUND(cash/1e9,0)          as cash_ty
    FROM financials_balance WHERE symbol='VIC'
    ORDER BY year DESC, quarter DESC LIMIT 5
""")

sep('FINANCIALS_CASHFLOW - VCB (5 quy moi nhat, don vi: ty dong)')
run(conn, """
    SELECT symbol, year, quarter,
           ROUND(cfo/1e9,0)   as cfo_ty,
           ROUND(cfi/1e9,0)   as cfi_ty,
           ROUND(cff/1e9,0)   as cff_ty,
           ROUND(capex/1e9,0) as capex_ty
    FROM financials_cashflow WHERE symbol='VCB'
    ORDER BY year DESC, quarter DESC LIMIT 5
""")

sep('NULL CHECK - financials_ratio (tong so NULL moi cot)')
run(conn, """
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN pe IS NULL THEN 1 ELSE 0 END)         as pe_null,
        SUM(CASE WHEN pb IS NULL THEN 1 ELSE 0 END)         as pb_null,
        SUM(CASE WHEN roe IS NULL THEN 1 ELSE 0 END)        as roe_null,
        SUM(CASE WHEN roa IS NULL THEN 1 ELSE 0 END)        as roa_null,
        SUM(CASE WHEN net_margin IS NULL THEN 1 ELSE 0 END) as net_margin_null,
        SUM(CASE WHEN debt_equity IS NULL THEN 1 ELSE 0 END) as debt_eq_null
    FROM financials_ratio
""")

sep('NULL CHECK - financials_income')
run(conn, """
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN revenue IS NULL THEN 1 ELSE 0 END)        as revenue_null,
        SUM(CASE WHEN gross_profit IS NULL THEN 1 ELSE 0 END)   as gross_profit_null,
        SUM(CASE WHEN net_profit IS NULL THEN 1 ELSE 0 END)     as net_profit_null,
        SUM(CASE WHEN revenue_growth IS NULL THEN 1 ELSE 0 END) as rev_growth_null
    FROM financials_income
""")

sep('FINANCIALS_META - 10 dong moi nhat')
run(conn, """
    SELECT symbol, updated_at FROM financials_meta
    ORDER BY updated_at DESC LIMIT 10
""")

sep('DB SIZE')
size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
print(f'  {DB_PATH}: {size_mb:.2f} MB')

conn.close()
print('\n' + '='*70)
print('  DONE')
print('='*70)
