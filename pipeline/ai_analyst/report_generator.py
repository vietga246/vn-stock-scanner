"""
report_generator.py — Multi-format Report Generator (v2)

Tạo báo cáo phân tích ở nhiều định dạng:
- Markdown (cho GitHub, web)
- HTML (cho email, web)
- JSON (cho API, frontend)

Các loại báo cáo:
- Daily: Tóm tắt thị trường hàng ngày
- Weekly: Phân tích chuyên sâu hàng tuần
- Stock Detail: Chi tiết từng cổ phiếu
"""

import sqlite3
import pandas as pd
import json
import os
import logging
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from string import Template

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── TEMPLATES ─────────────────────────────────────────────────────────────

DAILY_REPORT_MD = """# 📊 Báo cáo thị trường - ${date}

> Cập nhật lúc ${time} ICT

---

## 📈 Tổng quan thị trường

| Chỉ số | Giá trị |
|--------|---------|
| Tổng số cổ phiếu | ${total_stocks} |
| Tier A (≥70 điểm) | ${tier_a} |
| Tier B (55-69) | ${tier_b} |
| Tier C (40-54) | ${tier_c} |
| Score TB | ${avg_score} |

---

## 🏆 Top 10 Composite Score

| # | Mã | Tên | Ngành | Score | Tier | Khuyến nghị |
|---|-----|-----|-------|-------|------|-------------|
${top_stocks_table}

---

## 🔥 Ngành nổi bật

### Dòng tiền vào mạnh nhất
${accumulating_sectors}

### Dòng tiền ra
${distributing_sectors}

---

## 📊 Tín hiệu kỹ thuật

- **RSI Overbought (>70)**: ${overbought_count} cổ phiếu
- **RSI Oversold (<30)**: ${oversold_count} cổ phiếu
- **Uptrend**: ${uptrend_count} | **Downtrend**: ${downtrend_count}

### Top Gainers (5D)
${top_gainers}

### Top Losers (5D)
${top_losers}

---

## ⚠️ Cảnh báo

${warnings}

---

*Báo cáo được tạo tự động bởi VN Stock Scanner. Không phải lời khuyên đầu tư.*
"""

HTML_REPORT = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VN Stock Scanner - Daily Report ${date}</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #05080a;
            color: #e8edf2;
            padding: 20px;
            max-width: 900px;
            margin: 0 auto;
            line-height: 1.6;
        }
        h1 { color: #00d4ff; margin-bottom: 10px; font-size: 24px; }
        h2 { color: #a855f7; margin: 25px 0 15px; font-size: 18px; border-bottom: 1px solid #1e2832; padding-bottom: 8px; }
        h3 { color: #00ff88; margin: 15px 0 10px; font-size: 14px; }
        .meta { color: #4a5a6a; font-size: 13px; margin-bottom: 20px; }
        table { 
            border-collapse: collapse; 
            width: 100%; 
            margin: 15px 0;
            background: #0a0f14;
            border: 1px solid #1e2832;
            border-radius: 8px;
            overflow: hidden;
        }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #1e2832; }
        th { background: #0f1519; color: #4a5a6a; font-size: 11px; text-transform: uppercase; }
        td { font-size: 13px; }
        tr:hover { background: rgba(0,212,255,0.05); }
        .tier-A { color: #00ff88; font-weight: bold; }
        .tier-B { color: #00d4ff; }
        .tier-C { color: #8b99a8; }
        .tier-D { color: #ffcc00; }
        .tier-F { color: #ff3366; }
        .rec-STRONG_BUY, .rec-BUY { color: #00ff88; }
        .rec-HOLD { color: #ffcc00; }
        .rec-SELL, .rec-STRONG_SELL { color: #ff3366; }
        .positive { color: #00ff88; }
        .negative { color: #ff3366; }
        .warning { 
            background: rgba(255,204,0,0.1); 
            padding: 12px 15px; 
            border-left: 3px solid #ffcc00; 
            margin: 10px 0;
            border-radius: 0 8px 8px 0;
            font-size: 13px;
        }
        .card {
            background: #0a0f14;
            border: 1px solid #1e2832;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        .stat-item {
            background: #0a0f14;
            border: 1px solid #1e2832;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }
        .stat-value { font-size: 20px; font-weight: bold; color: #00d4ff; }
        .stat-label { font-size: 11px; color: #4a5a6a; margin-top: 4px; }
        ul { margin: 10px 0; padding-left: 20px; }
        li { margin: 5px 0; font-size: 13px; }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #1e2832;
            color: #4a5a6a;
            font-size: 11px;
            text-align: center;
        }
    </style>
</head>
<body>
    <h1>📊 VN Stock Scanner - Daily Report</h1>
    <div class="meta">
        <p>Ngày: ${date} | Cập nhật: ${time} ICT</p>
    </div>
    
    <h2>📈 Tổng quan thị trường</h2>
    <div class="stats-grid">
        <div class="stat-item">
            <div class="stat-value">${total_stocks}</div>
            <div class="stat-label">Tổng cổ phiếu</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" style="color: #00ff88">${tier_a}</div>
            <div class="stat-label">Tier A (≥70)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" style="color: #00d4ff">${tier_b}</div>
            <div class="stat-label">Tier B (55-69)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${avg_score}</div>
            <div class="stat-label">Score TB</div>
        </div>
    </div>
    
    <h2>🏆 Top 10 Composite Score</h2>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Mã</th>
                <th>Tên</th>
                <th>Ngành</th>
                <th>Score</th>
                <th>Tier</th>
                <th>Khuyến nghị</th>
            </tr>
        </thead>
        <tbody>
${top_stocks_html}
        </tbody>
    </table>
    
    <h2>🔥 Phân tích ngành</h2>
    <div class="card">
        <h3>📈 Đang tích lũy</h3>
        <ul class="positive">
${accumulating_html}
        </ul>
        
        <h3 style="margin-top: 15px;">📉 Đang phân phối</h3>
        <ul class="negative">
${distributing_html}
        </ul>
    </div>
    
    <h2>📊 Tín hiệu kỹ thuật</h2>
    <div class="stats-grid">
        <div class="stat-item">
            <div class="stat-value negative">${overbought_count}</div>
            <div class="stat-label">RSI > 70 (Quá mua)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value positive">${oversold_count}</div>
            <div class="stat-label">RSI < 30 (Quá bán)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value positive">${uptrend_count}</div>
            <div class="stat-label">Uptrend</div>
        </div>
        <div class="stat-item">
            <div class="stat-value negative">${downtrend_count}</div>
            <div class="stat-label">Downtrend</div>
        </div>
    </div>
    
    <h2>⚠️ Cảnh báo</h2>
${warnings_html}
    
    <div class="footer">
        <p>Báo cáo được tạo tự động bởi VN Stock Scanner</p>
        <p>⚠️ Không phải lời khuyên đầu tư. Chỉ mang tính tham khảo.</p>
    </div>
</body>
</html>
"""

# ─── DATA LOADERS ──────────────────────────────────────────────────────────

def create_connection():
    if not os.path.exists(DB_PATH):
        log.error("Database not found: %s", DB_PATH)
        return None
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def load_all_scores(conn) -> pd.DataFrame:
    """Load all stock scores with symbol info."""
    return pd.read_sql("""
        SELECT 
            s.*,
            sym.organ_name,
            sym.industry_name,
            sym.exchange
        FROM stock_scores s
        LEFT JOIN symbols sym ON s.symbol = sym.symbol
        WHERE s.composite_score IS NOT NULL
        ORDER BY s.composite_score DESC
    """, conn)


def load_sector_scores(conn) -> pd.DataFrame:
    """Load sector scores."""
    try:
        return pd.read_sql("SELECT * FROM sector_scores ORDER BY avg_composite DESC", conn)
    except:
        return pd.DataFrame()


def load_ai_analysis() -> Dict:
    """Load AI analysis from JSON."""
    path = os.path.join(EXPORT_DIR, "ai_analysis.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


# ─── HELPER FUNCTIONS ──────────────────────────────────────────────────────

def safe_val(val, default="N/A", fmt=None):
    """Safely format a value."""
    if val is None or (isinstance(val, float) and val != val):
        return default
    if fmt:
        return fmt.format(val)
    return val


def get_recommendation(score: float) -> str:
    """Get recommendation from score."""
    if score >= 75:
        return "STRONG_BUY"
    elif score >= 65:
        return "BUY"
    elif score >= 55:
        return "HOLD"
    elif score >= 45:
        return "SELL"
    else:
        return "STRONG_SELL"


def get_recommendation_text(rec: str) -> str:
    """Get Vietnamese recommendation text."""
    mapping = {
        "STRONG_BUY": "Mua mạnh",
        "BUY": "Mua",
        "HOLD": "Giữ",
        "SELL": "Bán",
        "STRONG_SELL": "Bán mạnh",
    }
    return mapping.get(rec, rec)


# ─── REPORT GENERATORS ─────────────────────────────────────────────────────

def generate_daily_report(scores_df: pd.DataFrame, sectors_df: pd.DataFrame, ai_analysis: Dict) -> tuple:
    """Generate daily report in both MD and HTML formats."""
    
    now = datetime.now()
    
    # Basic stats
    total = len(scores_df)
    tier_counts = scores_df['tier'].value_counts().to_dict()
    avg_score = scores_df['composite_score'].mean()
    
    # Top stocks table
    top_rows_md = []
    top_rows_html = []
    analyses = ai_analysis.get('analyses', {})
    
    for i, (_, row) in enumerate(scores_df.head(10).iterrows()):
        symbol = row['symbol']
        score = safe_val(row['composite_score'], 0, '{:.1f}')
        tier = safe_val(row.get('tier'), 'N/A')
        name = safe_val(row.get('organ_name'), symbol)[:20]
        industry = safe_val(row.get('industry_name'), 'N/A')[:15]
        
        # Get recommendation from AI analysis or calculate
        if symbol in analyses:
            rec = analyses[symbol].get('recommendation', 'HOLD')
        else:
            rec = get_recommendation(row['composite_score'] or 0)
        
        rec_text = get_recommendation_text(rec)
        
        # Markdown row
        top_rows_md.append(f"| {i+1} | {symbol} | {name} | {industry} | {score} | {tier} | {rec_text} |")
        
        # HTML row
        top_rows_html.append(f"""            <tr>
                <td>{i+1}</td>
                <td><strong>{symbol}</strong></td>
                <td>{name}</td>
                <td>{industry}</td>
                <td>{score}</td>
                <td class="tier-{tier}">{tier}</td>
                <td class="rec-{rec}">{rec_text}</td>
            </tr>""")
    
    # Sector analysis
    acc_sectors_md = []
    acc_sectors_html = []
    dist_sectors_md = []
    dist_sectors_html = []
    
    if not sectors_df.empty:
        for _, row in sectors_df.iterrows():
            name = row.get('industry_name', row.get('name', ''))
            foreign = row.get('total_foreign_7d', row.get('foreign_net_7d', 0)) or 0
            score = row.get('avg_composite', row.get('avg_composite_score', 0)) or 0
            
            if foreign > 0:
                acc_sectors_md.append(f"- **{name}**: +{foreign:.1f}B VND (Score: {score:.1f})")
                acc_sectors_html.append(f"<li><strong>{name}</strong>: +{foreign:.1f}B VND (Score: {score:.1f})</li>")
            elif foreign < 0:
                dist_sectors_md.append(f"- **{name}**: {foreign:.1f}B VND (Score: {score:.1f})")
                dist_sectors_html.append(f"<li><strong>{name}</strong>: {foreign:.1f}B VND (Score: {score:.1f})</li>")
    
    # Technical signals
    rsi_vals = scores_df['rsi14'].dropna() if 'rsi14' in scores_df.columns else pd.Series([50])
    overbought = (rsi_vals > 70).sum()
    oversold = (rsi_vals < 30).sum()
    
    trend_vals = scores_df['trend_short'].dropna() if 'trend_short' in scores_df.columns else pd.Series([0])
    uptrend = (trend_vals == 1).sum()
    downtrend = (trend_vals == -1).sum()
    
    # Top movers
    gainers_md = []
    losers_md = []
    
    if 'price_change_5d' in scores_df.columns:
        gainers_df = scores_df.nlargest(5, 'price_change_5d')
        losers_df = scores_df.nsmallest(5, 'price_change_5d')
        
        for _, row in gainers_df.iterrows():
            gainers_md.append(f"- {row['symbol']}: +{safe_val(row['price_change_5d'], 0, '{:.1f}')}%")
        
        for _, row in losers_df.iterrows():
            losers_md.append(f"- {row['symbol']}: {safe_val(row['price_change_5d'], 0, '{:.1f}')}%")
    
    # Warnings
    warnings_md = []
    warnings_html = []
    
    if overbought > 10:
        msg = f"⚠️ {overbought} cổ phiếu RSI > 70 - thị trường có thể điều chỉnh"
        warnings_md.append(msg)
        warnings_html.append(f'<div class="warning">{msg}</div>')
    if oversold > 10:
        msg = f"📢 {oversold} cổ phiếu RSI < 30 - có thể là cơ hội mua"
        warnings_md.append(msg)
        warnings_html.append(f'<div class="warning">{msg}</div>')
    if downtrend > uptrend * 1.5:
        msg = "⚠️ Số cổ phiếu downtrend nhiều hơn uptrend - cẩn trọng"
        warnings_md.append(msg)
        warnings_html.append(f'<div class="warning">{msg}</div>')
    if not warnings_md:
        warnings_md.append("✅ Không có cảnh báo đặc biệt")
        warnings_html.append('<div class="warning" style="border-color: #00ff88; background: rgba(0,255,136,0.1);">✅ Không có cảnh báo đặc biệt</div>')
    
    # Generate Markdown
    md_report = Template(DAILY_REPORT_MD).substitute(
        date=now.strftime("%d/%m/%Y"),
        time=now.strftime("%H:%M"),
        total_stocks=total,
        tier_a=tier_counts.get('A', 0),
        tier_b=tier_counts.get('B', 0),
        tier_c=tier_counts.get('C', 0),
        avg_score=f"{avg_score:.1f}",
        top_stocks_table="\n".join(top_rows_md),
        accumulating_sectors="\n".join(acc_sectors_md[:5]) if acc_sectors_md else "- Không có",
        distributing_sectors="\n".join(dist_sectors_md[:5]) if dist_sectors_md else "- Không có",
        overbought_count=overbought,
        oversold_count=oversold,
        uptrend_count=uptrend,
        downtrend_count=downtrend,
        top_gainers="\n".join(gainers_md) if gainers_md else "- Không có dữ liệu",
        top_losers="\n".join(losers_md) if losers_md else "- Không có dữ liệu",
        warnings="\n".join(warnings_md),
    )
    
    # Generate HTML
    html_report = Template(HTML_REPORT).substitute(
        date=now.strftime("%d/%m/%Y"),
        time=now.strftime("%H:%M"),
        total_stocks=total,
        tier_a=tier_counts.get('A', 0),
        tier_b=tier_counts.get('B', 0),
        tier_c=tier_counts.get('C', 0),
        avg_score=f"{avg_score:.1f}",
        top_stocks_html="\n".join(top_rows_html),
        accumulating_html="\n".join(acc_sectors_html[:5]) if acc_sectors_html else "<li>Không có</li>",
        distributing_html="\n".join(dist_sectors_html[:5]) if dist_sectors_html else "<li>Không có</li>",
        overbought_count=overbought,
        oversold_count=oversold,
        uptrend_count=uptrend,
        downtrend_count=downtrend,
        warnings_html="\n".join(warnings_html),
    )
    
    return md_report, html_report


# ─── EXPORT FUNCTIONS ──────────────────────────────────────────────────────

def export_reports(scores_df: pd.DataFrame, sectors_df: pd.DataFrame):
    """Export all reports."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Load AI analysis
    ai_analysis = load_ai_analysis()
    
    # Generate daily reports
    md_report, html_report = generate_daily_report(scores_df, sectors_df, ai_analysis)
    
    # Save Markdown
    md_path = os.path.join(EXPORT_DIR, "daily_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    log.info("✅ Exported %s", md_path)
    
    # Save HTML
    html_path = os.path.join(EXPORT_DIR, "daily_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_report)
    log.info("✅ Exported %s", html_path)


# ─── MAIN ──────────────────────────────────────────────────────────────────

def run():
    """Main function to generate reports."""
    log.info("=" * 60)
    log.info("📝 REPORT GENERATOR — VN Stock Scanner")
    log.info("=" * 60)
    
    conn = create_connection()
    if conn is None:
        log.error("Cannot connect to database")
        return
    
    scores_df = load_all_scores(conn)
    sectors_df = load_sector_scores(conn)
    conn.close()
    
    if scores_df.empty:
        log.error("No data available. Run scoring_engine.py first.")
        return
    
    log.info("📊 Loaded %d stocks", len(scores_df))
    
    export_reports(scores_df, sectors_df)
    
    log.info("")
    log.info("✅ Report generation completed")


if __name__ == "__main__":
    run()
