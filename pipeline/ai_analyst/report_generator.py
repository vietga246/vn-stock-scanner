"""
report_generator.py — Multi-format Report Generator

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

| # | Mã | Tên | Ngành | Score | Tier | ROE | PE | RSI |
|---|-----|-----|-------|-------|------|-----|-----|-----|
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

STOCK_DETAIL_MD = """# ${symbol} - ${name}

> **Ngành**: ${industry} | **Sàn**: ${exchange}

---

## 📊 Điểm số

| Metric | Score | Percentile |
|--------|-------|------------|
| **Composite** | ${composite_score} | Top ${rank_pct}% |
| Fundamental | ${fundamental_score} | - |
| Smart Money | ${smart_money_score} | - |
| Momentum | ${momentum_score} | - |
| Technical | ${technical_score} | - |

**Tier**: ${tier}

---

## 💰 Chỉ số tài chính

| Chỉ số | Giá trị | Đánh giá |
|--------|---------|----------|
| ROE | ${roe}% | ${roe_rating} |
| ROA | ${roa}% | ${roa_rating} |
| PE | ${pe}x | ${pe_rating} |
| Revenue Growth | ${revenue_growth}% | ${growth_rating} |
| Net Margin | ${net_margin}% | - |
| D/E | ${debt_equity} | ${de_rating} |

---

## 📈 Kỹ thuật

| Chỉ số | Giá trị | Signal |
|--------|---------|--------|
| RSI(14) | ${rsi14} | ${rsi_signal} |
| MACD | ${macd_hist} | ${macd_signal} |
| Trend (Short) | ${trend_short} | ${trend_signal} |
| Price 5D | ${price_5d}% | - |
| Price 20D | ${price_20d}% | - |
| Vol Ratio | ${vol_ratio}x | ${vol_signal} |

---

## 💸 Dòng tiền thông minh

| Metric | 7 ngày | 30 ngày |
|--------|--------|---------|
| Khối ngoại | ${foreign_7d}B | ${foreign_30d}B |
| Tự doanh | ${prop_7d}B | - |

**Nhận định**: ${smart_money_verdict}

---

*Cập nhật: ${updated_at}*
"""

HTML_WRAPPER = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${title}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.6; }
        table { border-collapse: collapse; width: 100%; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background: #f5f5f5; }
        tr:nth-child(even) { background: #fafafa; }
        h1 { color: #1a73e8; }
        h2 { color: #34a853; border-bottom: 2px solid #34a853; padding-bottom: 5px; }
        .tier-a { color: #00c853; font-weight: bold; }
        .tier-b { color: #2196f3; }
        .tier-c { color: #ff9800; }
        .tier-d { color: #f44336; }
        .positive { color: #00c853; }
        .negative { color: #f44336; }
        .warning { background: #fff3e0; padding: 10px; border-left: 4px solid #ff9800; margin: 10px 0; }
        code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
    </style>
</head>
<body>
${content}
</body>
</html>
"""

# ─── DATA LOADERS ──────────────────────────────────────────────────────────

def create_connection():
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


# ─── HELPER FUNCTIONS ──────────────────────────────────────────────────────

def safe_val(val, default="N/A", fmt=None):
    """Safely format a value."""
    if val is None or (isinstance(val, float) and val != val):
        return default
    if fmt:
        return fmt.format(val)
    return val


def get_rating(val, thresholds: Dict[str, tuple], default="Trung bình") -> str:
    """Get rating based on thresholds."""
    if val is None or (isinstance(val, float) and val != val):
        return default
    for rating, (low, high) in thresholds.items():
        if low <= val < high:
            return rating
    return default


def get_tier_class(tier: str) -> str:
    """Get CSS class for tier."""
    return f"tier-{tier.lower()}" if tier else ""


def get_rsi_signal(rsi: float) -> str:
    """Get RSI signal."""
    if rsi is None or rsi != rsi:
        return "N/A"
    if rsi > 70:
        return "🔴 Overbought"
    elif rsi < 30:
        return "🟢 Oversold"
    elif 40 <= rsi <= 60:
        return "⚪ Neutral"
    elif rsi > 60:
        return "🟡 Bullish"
    else:
        return "🟡 Bearish"


def get_trend_signal(trend: int) -> str:
    """Get trend signal."""
    if trend == 1:
        return "🟢 Uptrend"
    elif trend == -1:
        return "🔴 Downtrend"
    else:
        return "⚪ Sideways"


# ─── REPORT GENERATORS ─────────────────────────────────────────────────────

def generate_daily_report(scores_df: pd.DataFrame, sectors_df: pd.DataFrame) -> str:
    """Generate daily market report in Markdown."""
    
    now = datetime.now()
    
    # Stats
    total = len(scores_df)
    tier_counts = scores_df['tier'].value_counts().to_dict()
    avg_score = scores_df['composite_score'].mean()
    
    # Top stocks table
    top_rows = []
    for i, (_, row) in enumerate(scores_df.head(10).iterrows(), 1):
        top_rows.append(
            f"| {i} | {row['symbol']} | {safe_val(row.get('organ_name'), '')[:20]} | "
            f"{safe_val(row.get('industry_name'), '')[:15]} | "
            f"**{safe_val(row['composite_score'], fmt='{:.1f}')}** | {row['tier']} | "
            f"{safe_val(row['roe'], fmt='{:.1f}')}% | "
            f"{safe_val(row['pe'], fmt='{:.1f}')}x | "
            f"{safe_val(row['rsi14'], fmt='{:.0f}')} |"
        )
    
    # Sectors
    acc_sectors = []
    dist_sectors = []
    if not sectors_df.empty:
        for _, row in sectors_df.iterrows():
            name = row.get('industry_name', row.get('name', ''))
            foreign = row.get('total_foreign_7d', row.get('foreign_net_7d', 0)) or 0
            if foreign > 0:
                acc_sectors.append(f"- **{name}**: +{foreign:.1f}B VND")
            elif foreign < 0:
                dist_sectors.append(f"- **{name}**: {foreign:.1f}B VND")
    
    # Technical signals
    rsi_vals = scores_df['rsi14'].dropna()
    overbought = (rsi_vals > 70).sum()
    oversold = (rsi_vals < 30).sum()
    
    trend_vals = scores_df['trend_short'].dropna()
    uptrend = (trend_vals == 1).sum()
    downtrend = (trend_vals == -1).sum()
    
    # Top movers
    gainers_df = scores_df.nlargest(5, 'price_change_5d')
    losers_df = scores_df.nsmallest(5, 'price_change_5d')
    
    gainers_list = []
    for _, row in gainers_df.iterrows():
        gainers_list.append(f"- {row['symbol']}: +{safe_val(row['price_change_5d'], fmt='{:.1f}')}%")
    
    losers_list = []
    for _, row in losers_df.iterrows():
        losers_list.append(f"- {row['symbol']}: {safe_val(row['price_change_5d'], fmt='{:.1f}')}%")
    
    # Warnings
    warnings = []
    if overbought > 10:
        warnings.append(f"⚠️ {overbought} cổ phiếu RSI > 70 - thị trường có thể điều chỉnh")
    if oversold > 10:
        warnings.append(f"📢 {oversold} cổ phiếu RSI < 30 - có thể là cơ hội mua")
    if downtrend > uptrend * 1.5:
        warnings.append("⚠️ Số cổ phiếu downtrend nhiều hơn uptrend - cẩn trọng")
    if not warnings:
        warnings.append("✅ Không có cảnh báo đặc biệt")
    
    # Fill template
    template = Template(DAILY_REPORT_MD)
    report = template.substitute(
        date=now.strftime("%d/%m/%Y"),
        time=now.strftime("%H:%M"),
        total_stocks=total,
        tier_a=tier_counts.get('A', 0),
        tier_b=tier_counts.get('B', 0),
        tier_c=tier_counts.get('C', 0),
        avg_score=f"{avg_score:.1f}",
        top_stocks_table="\n".join(top_rows),
        accumulating_sectors="\n".join(acc_sectors[:5]) if acc_sectors else "- Không có",
        distributing_sectors="\n".join(dist_sectors[:5]) if dist_sectors else "- Không có",
        overbought_count=overbought,
        oversold_count=oversold,
        uptrend_count=uptrend,
        downtrend_count=downtrend,
        top_gainers="\n".join(gainers_list),
        top_losers="\n".join(losers_list),
        warnings="\n".join(warnings),
    )
    
    return report


def generate_stock_detail(row: pd.Series) -> str:
    """Generate detailed report for a single stock."""
    
    # Ratings
    roe_rating = get_rating(row.get('roe'), {
        "Xuất sắc": (20, 100),
        "Tốt": (15, 20),
        "Khá": (10, 15),
        "Yếu": (0, 10),
    })
    
    roa_rating = get_rating(row.get('roa'), {
        "Xuất sắc": (15, 100),
        "Tốt": (10, 15),
        "Khá": (5, 10),
        "Yếu": (0, 5),
    })
    
    pe_val = row.get('pe', 0) or 0
    pe_rating = "Rẻ" if pe_val < 10 else "Hợp lý" if pe_val < 15 else "Cao" if pe_val < 25 else "Đắt"
    
    growth_rating = get_rating(row.get('revenue_growth'), {
        "Tăng mạnh": (20, 200),
        "Tăng": (10, 20),
        "Ổn định": (0, 10),
        "Giảm": (-100, 0),
    })
    
    de_val = row.get('debt_equity', 0) or 0
    de_rating = "Thấp" if de_val < 0.5 else "Trung bình" if de_val < 1.5 else "Cao"
    
    # Smart money verdict
    foreign_7d = row.get('foreign_net_7d', 0) or 0
    foreign_30d = row.get('foreign_net_30d', 0) or 0
    
    if foreign_7d > 0 and foreign_30d > 0:
        sm_verdict = "🟢 Khối ngoại đang tích cực mua ròng"
    elif foreign_7d < 0 and foreign_30d < 0:
        sm_verdict = "🔴 Khối ngoại đang bán ròng"
    elif foreign_7d > 0:
        sm_verdict = "🟡 Khối ngoại bắt đầu mua lại"
    elif foreign_7d < 0:
        sm_verdict = "🟡 Khối ngoại đang giảm mua"
    else:
        sm_verdict = "⚪ Khối ngoại trung lập"
    
    # Volume signal
    vol_ratio = row.get('vol_ratio', 1) or 1
    vol_signal = "🔥 Đột biến" if vol_ratio > 2 else "📈 Tăng" if vol_ratio > 1.3 else "📉 Giảm" if vol_ratio < 0.7 else "⚪ Bình thường"
    
    template = Template(STOCK_DETAIL_MD)
    return template.substitute(
        symbol=row['symbol'],
        name=safe_val(row.get('organ_name'), row['symbol']),
        industry=safe_val(row.get('industry_name'), 'N/A'),
        exchange=safe_val(row.get('exchange'), 'N/A'),
        composite_score=f"{safe_val(row['composite_score'], 0):.1f}",
        rank_pct=f"{safe_val(row.get('rank_pct'), 50):.0f}",
        fundamental_score=f"{safe_val(row.get('fundamental_score'), 50):.1f}",
        smart_money_score=f"{safe_val(row.get('smart_money_score'), 50):.1f}",
        momentum_score=f"{safe_val(row.get('momentum_score'), 50):.1f}",
        technical_score=f"{safe_val(row.get('technical_score'), 50):.1f}",
        tier=row.get('tier', 'N/A'),
        roe=f"{safe_val(row.get('roe'), 0):.1f}",
        roe_rating=roe_rating,
        roa=f"{safe_val(row.get('roa'), 0):.1f}",
        roa_rating=roa_rating,
        pe=f"{safe_val(row.get('pe'), 0):.1f}",
        pe_rating=pe_rating,
        revenue_growth=f"{safe_val(row.get('revenue_growth'), 0):.1f}",
        growth_rating=growth_rating,
        net_margin=f"{safe_val(row.get('net_margin'), 0):.1f}",
        debt_equity=f"{safe_val(row.get('debt_equity'), 0):.2f}",
        de_rating=de_rating,
        rsi14=f"{safe_val(row.get('rsi14'), 50):.0f}",
        rsi_signal=get_rsi_signal(row.get('rsi14')),
        macd_hist=f"{safe_val(row.get('macd_hist'), 0):.4f}",
        macd_signal="🟢 Bullish" if (row.get('macd_hist') or 0) > 0 else "🔴 Bearish",
        trend_short="↑ Up" if row.get('trend_short') == 1 else "↓ Down" if row.get('trend_short') == -1 else "→ Side",
        trend_signal=get_trend_signal(row.get('trend_short')),
        price_5d=f"{safe_val(row.get('price_change_5d'), 0):.1f}",
        price_20d=f"{safe_val(row.get('price_change_20d'), 0):.1f}",
        vol_ratio=f"{vol_ratio:.2f}",
        vol_signal=vol_signal,
        foreign_7d=f"{foreign_7d:.1f}",
        foreign_30d=f"{foreign_30d:.1f}",
        prop_7d=f"{safe_val(row.get('prop_net_7d'), 0):.1f}",
        smart_money_verdict=sm_verdict,
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def markdown_to_html(md_content: str, title: str = "Report") -> str:
    """Convert markdown to HTML (basic conversion)."""
    import re
    
    html = md_content
    
    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    
    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    
    # Tables (basic)
    lines = html.split('\n')
    in_table = False
    new_lines = []
    
    for line in lines:
        if line.strip().startswith('|'):
            if not in_table:
                new_lines.append('<table>')
                in_table = True
            
            if '---' in line:
                continue
            
            cells = [c.strip() for c in line.split('|')[1:-1]]
            tag = 'th' if new_lines[-1] == '<table>' else 'td'
            row = '<tr>' + ''.join(f'<{tag}>{c}</{tag}>' for c in cells) + '</tr>'
            new_lines.append(row)
        else:
            if in_table:
                new_lines.append('</table>')
                in_table = False
            new_lines.append(line)
    
    if in_table:
        new_lines.append('</table>')
    
    html = '\n'.join(new_lines)
    
    # Lists
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    
    # Blockquotes
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    
    # Paragraphs
    html = re.sub(r'\n\n', '</p><p>', html)
    html = f'<p>{html}</p>'
    
    # Wrap in HTML template
    template = Template(HTML_WRAPPER)
    return template.substitute(title=title, content=html)


# ─── EXPORT FUNCTIONS ──────────────────────────────────────────────────────

def export_reports(scores_df: pd.DataFrame, sectors_df: pd.DataFrame):
    """Export all reports."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Daily report
    daily_md = generate_daily_report(scores_df, sectors_df)
    
    md_path = os.path.join(EXPORT_DIR, "daily_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(daily_md)
    log.info("✅ Exported %s", md_path)
    
    html_path = os.path.join(EXPORT_DIR, "daily_report.html")
    daily_html = markdown_to_html(daily_md, "Báo cáo thị trường")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(daily_html)
    log.info("✅ Exported %s", html_path)
    
    # Top stock details
    details_dir = os.path.join(EXPORT_DIR, "stocks")
    os.makedirs(details_dir, exist_ok=True)
    
    for _, row in scores_df.head(20).iterrows():
        symbol = row['symbol']
        detail_md = generate_stock_detail(row)
        
        detail_path = os.path.join(details_dir, f"{symbol}.md")
        with open(detail_path, "w", encoding="utf-8") as f:
            f.write(detail_md)
    
    log.info("✅ Exported %d stock details", min(20, len(scores_df)))


# ─── MAIN ──────────────────────────────────────────────────────────────────

def run():
    """Main function to generate reports."""
    log.info("=== Report Generator ===")
    
    conn = create_connection()
    scores_df = load_all_scores(conn)
    sectors_df = load_sector_scores(conn)
    conn.close()
    
    if scores_df.empty:
        log.error("No data available. Run scoring_engine.py first.")
        return
    
    log.info("Loaded %d stocks", len(scores_df))
    
    export_reports(scores_df, sectors_df)
    
    log.info("✅ Report generation completed")


if __name__ == "__main__":
    run()
