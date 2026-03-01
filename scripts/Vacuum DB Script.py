import sqlite3
import os

db = os.getenv('DB_PATH', 'data/stock.db')
if not os.path.exists(db):
    print('DB not found, skip vacuum')
else:
    size_before = os.path.getsize(db) / 1024 / 1024
    conn = sqlite3.connect(db)
    conn.execute('VACUUM;')
    conn.close()
    size_after = os.path.getsize(db) / 1024 / 1024
    print('DB size: %.1fMB -> %.1fMB' % (size_before, size_after))
