def table_columns(conn, table):
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    except Exception:
        return set()


def needs_recreate(conn, table, expected_cols):
    cols = table_columns(conn, table)
    if not cols:
        return False
    # Nếu thiếu bất kỳ cột nào → phải recreate
    return not expected_cols.issubset(cols)


def init_db(conn):
    schema_map = {
        'financials_ratio': set(
            ['symbol', 'year', 'quarter'] +
            list(RATIO_MAP.values()) +
            ['updated_at']
        ),
        'financials_income': set(
            ['symbol', 'year', 'quarter'] +
            list(INCOME_MAP.values()) +
            ['updated_at']
        ),
        'financials_balance': set(
            ['symbol', 'year', 'quarter'] +
            list(BALANCE_MAP.values()) +
            ['updated_at']
        ),
        'financials_cashflow': set(
            ['symbol', 'year', 'quarter'] +
            list(CASHFLOW_MAP.values()) +
            ['updated_at']
        ),
    }

    for table, expected_cols in schema_map.items():
        if needs_recreate(conn, table, expected_cols):
            log.info("Schema mismatch -> drop table %s", table)
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()

    conn.executescript('''
        CREATE TABLE IF NOT EXISTS financials_ratio (
            symbol TEXT, year INTEGER, quarter INTEGER,
            pe REAL, pb REAL, ps REAL, ev_ebitda REAL,
            roe REAL, roa REAL, roic REAL,
            gross_margin REAL, net_margin REAL,
            debt_equity REAL,
            current_ratio REAL, quick_ratio REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_income (
            symbol TEXT, year INTEGER, quarter INTEGER,
            revenue REAL, gross_profit REAL, operating_profit REAL,
            ebit REAL, net_profit REAL, net_profit_parent REAL,
            revenue_growth REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_balance (
            symbol TEXT, year INTEGER, quarter INTEGER,
            total_assets REAL, total_equity REAL, total_debt REAL,
            cash REAL, short_term_debt REAL, long_term_debt REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_cashflow (
            symbol TEXT, year INTEGER, quarter INTEGER,
            cfo REAL, cfi REAL, cff REAL, capex REAL,
            updated_at TEXT,
            PRIMARY KEY (symbol, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS financials_meta (
            symbol TEXT PRIMARY KEY,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ratio_pe
            ON financials_ratio(pe);

        CREATE INDEX IF NOT EXISTS idx_ratio_roe
            ON financials_ratio(roe);

        CREATE INDEX IF NOT EXISTS idx_ratio_roa
            ON financials_ratio(roa);

        CREATE INDEX IF NOT EXISTS idx_income_revenue_growth
            ON financials_income(revenue_growth);

        CREATE INDEX IF NOT EXISTS idx_ratio_year_quarter
            ON financials_ratio(year, quarter);
    ''')
    conn.commit()
