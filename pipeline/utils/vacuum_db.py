"""vacuum_db.py - Compress SQLite database after updates.
Upload file nay len scripts/vacuum_db.py
"""
import sqlite3
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH = os.getenv('DB_PATH', 'data/db/stock.db')


def vacuum():
    if not os.path.exists(DB_PATH):
        log.warning('DB not found: %s', DB_PATH)
        return

    size_before = os.path.getsize(DB_PATH)
    log.info('DB size before: %.2f MB', size_before / 1024 / 1024)

    conn = sqlite3.connect(DB_PATH)
    conn.execute('VACUUM')
    conn.close()

    size_after = os.path.getsize(DB_PATH)
    log.info('DB size after:  %.2f MB', size_after / 1024 / 1024)
    log.info('Saved: %.2f MB (%.0f%%)',
             (size_before - size_after) / 1024 / 1024,
             (1 - size_after / size_before) * 100 if size_before else 0)


if __name__ == '__main__':
    vacuum()
