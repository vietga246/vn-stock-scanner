"""
export_json.py — Export SQLite → data/stocks.json
Chạy sau financials.py trong GitHub Actions.
Output: data/stocks.json (committed to repo, served as static asset)
"""

import sqlite3, json, os, math
from datetime import datetime

DB_PATH  = os.environ.get("DB_PATH", "data/db/stock.db")
OUT_PATH = os.environ.get("OUT_PATH", "data/exports/stocks.json")

def safe(v):
    """None + NaN → None cho JSON."""
    if v is None: return None
    try:
        return None if math.isnan(float(v)) else round(float(v), 4)
    except Exception:
        return None

def pct(v):
    """Ratio column (0-1) -> percent (0-100), rounded 2dp."""
    v = safe(v)
    return round(v * 100, 2) if v is not None else None

def bil(v):
    """Raw VND -> ty dong (chia 1e9), rounded 2dp."""
    v = safe(v)
    return round(v / 1e9, 2) if v is not None else None

# Columns can convert theo tung table trong details
INCOME_BIL  = {"revenue","gross_profit","operating_profit","ebit",
                "net_profit","net_profit_parent"}
INCOME_PCT  = {"revenue_growth"}
BALANCE_BIL = {"total_assets","total_equity","total_debt","cash",
                "short_term_debt","long_term_debt"}
CASHFLOW_BIL= {"cfo","cfi","cff","capex"}
RATIO_PCT   = {"roe","roa","roic","gross_margin","net_margin"}

def export():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── Latest quarter per symbol ─────────────────────────────────────────
    cur.execute("""
        SELECT symbol, MAX(year*10 + quarter) AS yq, year, quarter
        FROM financials_ratio
        GROUP BY symbol
    """)
    latest = {r["symbol"]: (r["year"], r["quarter"]) for r in cur.fetchall()}

    # ── Screener rows (latest quarter ratios + income) ────────────────────
    placeholders = ",".join("?" * len(latest))
    symbols      = list(latest.keys())

    # Ratio latest
    cur.execute(f"""
        SELECT r.*
        FROM financials_ratio r
        JOIN (
            SELECT symbol, MAX(year*10+quarter) AS yq
            FROM financials_ratio GROUP BY symbol
        ) mx ON r.symbol=mx.symbol AND r.year*10+r.quarter=mx.yq
        WHERE r.symbol IN ({placeholders})
    """, symbols)
    ratios = {r["symbol"]: dict(r) for r in cur.fetchall()}

    # Income latest
    cur.execute(f"""
        SELECT i.*
        FROM financials_income i
        JOIN (
            SELECT symbol, MAX(year*10+quarter) AS yq
            FROM financials_income GROUP BY symbol
        ) mx ON i.symbol=mx.symbol AND i.year*10+i.quarter=mx.yq
        WHERE i.symbol IN ({placeholders})
    """, symbols)
    incomes = {r["symbol"]: dict(r) for r in cur.fetchall()}

    # Meta (updated_at)
    cur.execute("SELECT symbol, updated_at FROM financials_meta")
    metas = {r["symbol"]: r["updated_at"] for r in cur.fetchall()}

    # ── Historical series (last 8 quarters) per symbol ────────────────────
    cur.execute(f"""
        SELECT r.symbol, r.year, r.quarter,
               r.roe, r.roa, r.net_margin,
               i.revenue, i.net_profit, i.revenue_growth
        FROM financials_ratio r
        LEFT JOIN financials_income i
            ON r.symbol=i.symbol AND r.year=i.year AND r.quarter=i.quarter
        WHERE r.symbol IN ({placeholders})
        ORDER BY r.symbol, r.year, r.quarter
    """, symbols)

    history = {}
    for row in cur.fetchall():
        s = row["symbol"]
        if s not in history:
            history[s] = []
        history[s].append({
            "year":    row["year"],
            "quarter": row["quarter"],
            "roe":     pct(row["roe"]),
            "roa":     pct(row["roa"]),
            "net_margin": pct(row["net_margin"]),
            "revenue":    bil(row["revenue"]),
            "net_profit": bil(row["net_profit"]),
            "revenue_growth": pct(row["revenue_growth"]),
        })
    # Keep last 8 quarters
    for s in history:
        history[s] = history[s][-8:]

    # ── Balance + Cashflow latest ─────────────────────────────────────────
    cur.execute(f"""
        SELECT b.*
        FROM financials_balance b
        JOIN (
            SELECT symbol, MAX(year*10+quarter) AS yq
            FROM financials_balance GROUP BY symbol
        ) mx ON b.symbol=mx.symbol AND b.year*10+b.quarter=mx.yq
        WHERE b.symbol IN ({placeholders})
    """, symbols)
    balances = {r["symbol"]: dict(r) for r in cur.fetchall()}

    cur.execute(f"""
        SELECT c.*
        FROM financials_cashflow c
        JOIN (
            SELECT symbol, MAX(year*10+quarter) AS yq
            FROM financials_cashflow GROUP BY symbol
        ) mx ON c.symbol=mx.symbol AND c.year*10+c.quarter=mx.yq
        WHERE c.symbol IN ({placeholders})
    """, symbols)
    cashflows = {r["symbol"]: dict(r) for r in cur.fetchall()}

    # ── Full quarterly tables for detail page ────────────────────────────
    cur.execute(f"""
        SELECT * FROM financials_ratio
        WHERE symbol IN ({placeholders})
        ORDER BY symbol, year DESC, quarter DESC
    """, symbols)
    all_ratios = {}
    for r in cur.fetchall():
        s = r["symbol"]
        if s not in all_ratios: all_ratios[s] = []
        all_ratios[s].append(dict(r))

    cur.execute(f"""
        SELECT * FROM financials_income
        WHERE symbol IN ({placeholders})
        ORDER BY symbol, year DESC, quarter DESC
    """, symbols)
    all_incomes = {}
    for r in cur.fetchall():
        s = r["symbol"]
        if s not in all_incomes: all_incomes[s] = []
        all_incomes[s].append(dict(r))

    cur.execute(f"""
        SELECT * FROM financials_balance
        WHERE symbol IN ({placeholders})
        ORDER BY symbol, year DESC, quarter DESC
    """, symbols)
    all_balances = {}
    for r in cur.fetchall():
        s = r["symbol"]
        if s not in all_balances: all_balances[s] = []
        all_balances[s].append(dict(r))

    cur.execute(f"""
        SELECT * FROM financials_cashflow
        WHERE symbol IN ({placeholders})
        ORDER BY symbol, year DESC, quarter DESC
    """, symbols)
    all_cashflows = {}
    for r in cur.fetchall():
        s = r["symbol"]
        if s not in all_cashflows: all_cashflows[s] = []
        all_cashflows[s].append(dict(r))

    conn.close()

    # ── Assemble output ───────────────────────────────────────────────────
    screener = []
    details  = {}

    for sym in symbols:
        r  = ratios.get(sym, {})
        i  = incomes.get(sym, {})
        b  = balances.get(sym, {})
        cf = cashflows.get(sym, {})
        yr, qr = latest.get(sym, (None, None))

        row = {
            "symbol":   sym,
            "year":     yr,
            "quarter":  qr,
            "updated_at": metas.get(sym),
            # Valuation
            "pe":  safe(r.get("pe")),
            "pb":  safe(r.get("pb")),
            "ps":  safe(r.get("ps")),
            "ev_ebitda": safe(r.get("ev_ebitda")),
            # Profitability
            "roe": pct(r.get("roe")),
            "roa": pct(r.get("roa")),
            "roic": pct(r.get("roic")),
            "gross_margin": pct(r.get("gross_margin")),
            "net_margin":   pct(r.get("net_margin")),
            # Leverage
            "debt_equity":   safe(r.get("debt_equity")),
            "current_ratio": safe(r.get("current_ratio")),
            # Income
            "revenue":        bil(i.get("revenue")),
            "net_profit":     bil(i.get("net_profit")),
            "revenue_growth": pct(i.get("revenue_growth")),
            # Balance snapshot
            "total_assets":  bil(b.get("total_assets")),
            "total_equity":  bil(b.get("total_equity")),
            "cash":          bil(b.get("cash")),
            # Cashflow
            "cfo":   bil(cf.get("cfo")),
            "capex": bil(cf.get("capex")),
            # History sparkline
            "history": history.get(sym, []),
        }
        screener.append(row)

        # Detail: full quarterly data - apply dung converter tung table
        def clean_income(rows):
            out = []
            for row in (rows or []):
                cleaned = {}
                for k, v in row.items():
                    if k == "updated_at": continue
                    if k in INCOME_BIL:  cleaned[k] = bil(v)
                    elif k in INCOME_PCT: cleaned[k] = pct(v)
                    elif isinstance(v, float): cleaned[k] = safe(v)
                    else: cleaned[k] = v
                out.append(cleaned)
            return out

        def clean_balance(rows):
            out = []
            for row in (rows or []):
                cleaned = {}
                for k, v in row.items():
                    if k == "updated_at": continue
                    if k in BALANCE_BIL: cleaned[k] = bil(v)
                    elif isinstance(v, float): cleaned[k] = safe(v)
                    else: cleaned[k] = v
                out.append(cleaned)
            return out

        def clean_cashflow(rows):
            out = []
            for row in (rows or []):
                cleaned = {}
                for k, v in row.items():
                    if k == "updated_at": continue
                    if k in CASHFLOW_BIL: cleaned[k] = bil(v)
                    elif isinstance(v, float): cleaned[k] = safe(v)
                    else: cleaned[k] = v
                out.append(cleaned)
            return out

        def clean_ratio(rows):
            out = []
            for row in (rows or []):
                cleaned = {}
                for k, v in row.items():
                    if k == "updated_at": continue
                    if k in RATIO_PCT: cleaned[k] = pct(v)
                    elif isinstance(v, float): cleaned[k] = safe(v)
                    else: cleaned[k] = v
                out.append(cleaned)
            return out

        details[sym] = {
            "ratio":    clean_ratio(all_ratios.get(sym)),
            "income":   clean_income(all_incomes.get(sym)),
            "balance":  clean_balance(all_balances.get(sym)),
            "cashflow": clean_cashflow(all_cashflows.get(sym)),
        }

    # Sort screener by ROE desc (nulls last)
    screener.sort(key=lambda x: x["roe"] if x["roe"] is not None else -999, reverse=True)

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total":        len(screener),
        "screener":     screener,
        "details":      details,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = os.path.getsize(OUT_PATH) / 1024 / 1024
    print(f"✅ Exported {len(screener)} symbols → {OUT_PATH} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    export()
