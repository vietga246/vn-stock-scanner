# reset_financials_meta.py
# Chay script nay 1 lan de xoa cache financials_meta
# Sau do chay lai quarterly_financials workflow
import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'data/stock.db')

conn = sqlite3.connect(DB_PATH)
conn.execute('DELETE FROM financials_meta')
conn.commit()
count = conn.execute('SELECT changes()').fetchone()[0]
print('Deleted %d rows from financials_meta' % count)

# Also show current data counts
for table in ['financials_ratio', 'financials_income', 'financials_balance', 'financials_cashflow']:
    try:
        n = conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
        syms = conn.execute('SELECT COUNT(DISTINCT symbol) FROM ' + table).fetchone()[0]
        print('%s: %d rows, %d symbols' % (table, n, syms))
    except Exception as e:
        print('%s: %s' % (table, e))
conn.close()
