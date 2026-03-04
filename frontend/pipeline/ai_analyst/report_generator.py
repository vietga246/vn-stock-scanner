#!/usr/bin/env python3
"""
Report Generator - Create reports from AI analysis
Generates: daily_report.md, daily_report.html
"""

import os
import json
from datetime import datetime

EXPORT_DIR = os.environ.get("EXPORT_DIR", "data/exports")


def load_analysis():
    """Load AI analysis from JSON"""
    path = os.path.join(EXPORT_DIR, "ai_analysis.json")
    if not os.path.exists(path):
        print(f"❌ ai_analysis.json not found")
        return None
    
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_screener():
    """Load screener data"""
    path = os.path.join(EXPORT_DIR, "screener.json")
    if not os.path.exists(path):
        return None
    
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_markdown_report(data: dict, screener: dict = None) -> str:
    """Generate Markdown report"""
    
    analyses = data.get('analyses', {})
    generated_at = data.get('generated_at', '')
    model = data.get('model', 'rule-based')
    
    # Group by recommendation
    groups = {
        'STRONG_BUY': [],
        'BUY': [],
        'HOLD': [],
        'SELL': [],
        'STRONG_SELL': []
    }
    
    for symbol, analysis in analyses.items():
        rec = analysis.get('recommendation', 'HOLD')
        if rec in groups:
            groups[rec].append((symbol, analysis))
    
    # Sort each group by score (from screener if available)
    screener_data = {}
    if screener:
        for s in screener.get('screener', []):
            screener_data[s['symbol']] = s
    
    for rec in groups:
        groups[rec].sort(
            key=lambda x: screener_data.get(x[0], {}).get('composite_score', 0),
            reverse=True
        )
    
    # Build report
    lines = [
        f"# 📊 VN Stock Scanner - Daily Report",
        f"",
        f"**Ngày:** {datetime.fromisoformat(generated_at.replace('Z', '')).strftime('%d/%m/%Y %H:%M')} UTC",
        f"",
        f"**Model:** {model}",
        f"",
        f"**Tổng số cổ phiếu phân tích:** {len(analyses)}",
        f"",
        f"---",
        f""
    ]
    
    # Summary
    lines.extend([
        f"## 📋 Tóm tắt",
        f"",
        f"| Khuyến nghị | Số lượng |",
        f"|-------------|----------|"
    ])
    
    for rec, items in groups.items():
        emoji = {
            'STRONG_BUY': '🟢',
            'BUY': '🔵', 
            'HOLD': '🟡',
            'SELL': '🟠',
            'STRONG_SELL': '🔴'
        }.get(rec, '')
        lines.append(f"| {emoji} {rec} | {len(items)} |")
    
    lines.extend([f"", f"---", f""])
    
    # Top picks
    if groups['STRONG_BUY'] or groups['BUY']:
        lines.extend([
            f"## 🎯 Top Picks (Strong Buy & Buy)",
            f""
        ])
        
        top_picks = groups['STRONG_BUY'][:5] + groups['BUY'][:5]
        for symbol, analysis in top_picks[:10]:
            score = screener_data.get(symbol, {}).get('composite_score', 0)
            lines.extend([
                f"### {symbol} - Score: {score:.1f}",
                f"",
                f"**Khuyến nghị:** {analysis['recommendation']}",
                f"",
                f"{analysis.get('summary', '')}",
                f"",
                f"**Điểm tích cực:**"
            ])
            for h in analysis.get('highlights', [])[:3]:
                lines.append(f"- ✅ {h['text']}")
            
            if analysis.get('risks'):
                lines.append(f"")
                lines.append(f"**Rủi ro:**")
                for r in analysis.get('risks', [])[:2]:
                    lines.append(f"- ⚠️ {r['text']}")
            
            lines.extend([f"", f"---", f""])
    
    # Avoid list
    if groups['SELL'] or groups['STRONG_SELL']:
        lines.extend([
            f"## ⚠️ Cần tránh (Sell & Strong Sell)",
            f""
        ])
        
        avoid = groups['STRONG_SELL'][:3] + groups['SELL'][:3]
        for symbol, analysis in avoid[:5]:
            score = screener_data.get(symbol, {}).get('composite_score', 0)
            lines.append(f"- **{symbol}** (Score: {score:.1f}) - {analysis.get('recommendation')}")
        
        lines.extend([f"", f"---", f""])
    
    # Footer
    lines.extend([
        f"## 📝 Lưu ý",
        f"",
        f"- Đây là phân tích tự động, chỉ mang tính tham khảo",
        f"- Không phải khuyến nghị đầu tư",
        f"- Luôn tự nghiên cứu kỹ trước khi ra quyết định",
        f"",
        f"---",
        f"",
        f"*Powered by VN Stock Scanner*"
    ])
    
    return '\n'.join(lines)


def generate_html_report(data: dict, screener: dict = None) -> str:
    """Generate HTML report"""
    
    analyses = data.get('analyses', {})
    generated_at = data.get('generated_at', '')
    model = data.get('model', 'rule-based')
    
    # Group by recommendation
    groups = {
        'STRONG_BUY': [],
        'BUY': [],
        'HOLD': [],
        'SELL': [],
        'STRONG_SELL': []
    }
    
    for symbol, analysis in analyses.items():
        rec = analysis.get('recommendation', 'HOLD')
        if rec in groups:
            groups[rec].append((symbol, analysis))
    
    # Get screener data
    screener_data = {}
    if screener:
        for s in screener.get('screener', []):
            screener_data[s['symbol']] = s
    
    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VN Stock Scanner - Daily Report</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #05080a;
            color: #e8edf2;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
        }}
        h1 {{ color: #00d4ff; margin-bottom: 10px; }}
        h2 {{ color: #a855f7; margin: 20px 0 10px; }}
        h3 {{ color: #00ff88; margin: 15px 0 8px; }}
        .meta {{ color: #4a5a6a; font-size: 14px; margin-bottom: 20px; }}
        .summary {{ 
            background: #0a0f14;
            border: 1px solid #1e2832;
            border-radius: 8px;
            padding: 15px;
            margin: 15px 0;
        }}
        .summary table {{ width: 100%; border-collapse: collapse; }}
        .summary td, .summary th {{ 
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #1e2832;
        }}
        .card {{
            background: #0a0f14;
            border: 1px solid #1e2832;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
        }}
        .rec-STRONG_BUY {{ border-left: 3px solid #00ff88; }}
        .rec-BUY {{ border-left: 3px solid #00d4ff; }}
        .rec-HOLD {{ border-left: 3px solid #ffcc00; }}
        .rec-SELL {{ border-left: 3px solid #ff9900; }}
        .rec-STRONG_SELL {{ border-left: 3px solid #ff3366; }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }}
        .badge-STRONG_BUY {{ background: #00ff8820; color: #00ff88; }}
        .badge-BUY {{ background: #00d4ff20; color: #00d4ff; }}
        .badge-HOLD {{ background: #ffcc0020; color: #ffcc00; }}
        .badge-SELL {{ background: #ff990020; color: #ff9900; }}
        .badge-STRONG_SELL {{ background: #ff336620; color: #ff3366; }}
        .highlight {{ color: #00ff88; }}
        .risk {{ color: #ff3366; }}
        ul {{ margin: 10px 0; padding-left: 20px; }}
        li {{ margin: 5px 0; }}
        .footer {{ 
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #1e2832;
            color: #4a5a6a;
            font-size: 12px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <h1>📊 VN Stock Scanner - Daily Report</h1>
    <div class="meta">
        <p>Ngày: {datetime.fromisoformat(generated_at.replace('Z', '')).strftime('%d/%m/%Y %H:%M')} UTC</p>
        <p>Model: {model} | Tổng số: {len(analyses)} cổ phiếu</p>
    </div>
    
    <h2>📋 Tóm tắt</h2>
    <div class="summary">
        <table>
            <tr><th>Khuyến nghị</th><th>Số lượng</th></tr>
            <tr><td>🟢 STRONG BUY</td><td>{len(groups['STRONG_BUY'])}</td></tr>
            <tr><td>🔵 BUY</td><td>{len(groups['BUY'])}</td></tr>
            <tr><td>🟡 HOLD</td><td>{len(groups['HOLD'])}</td></tr>
            <tr><td>🟠 SELL</td><td>{len(groups['SELL'])}</td></tr>
            <tr><td>🔴 STRONG SELL</td><td>{len(groups['STRONG_SELL'])}</td></tr>
        </table>
    </div>
"""
    
    # Top picks
    if groups['STRONG_BUY'] or groups['BUY']:
        html += f"\n<h2>🎯 Top Picks</h2>\n"
        
        top_picks = groups['STRONG_BUY'][:5] + groups['BUY'][:5]
        for symbol, analysis in top_picks[:8]:
            score = screener_data.get(symbol, {}).get('composite_score', 0)
            rec = analysis['recommendation']
            
            html += f"""
    <div class="card rec-{rec}">
        <h3>{symbol} <span class="badge badge-{rec}">{rec}</span></h3>
        <p style="color: #8b99a8; font-size: 14px;">Score: {score:.1f}/100</p>
        <p style="margin: 10px 0;">{analysis.get('summary', '')}</p>
        <p class="highlight"><strong>Điểm tích cực:</strong></p>
        <ul>
"""
            for h in analysis.get('highlights', [])[:3]:
                html += f"            <li class='highlight'>{h['text']}</li>\n"
            
            html += "        </ul>\n"
            
            if analysis.get('risks'):
                html += "        <p class='risk'><strong>Rủi ro:</strong></p>\n        <ul>\n"
                for r in analysis.get('risks', [])[:2]:
                    html += f"            <li class='risk'>{r['text']}</li>\n"
                html += "        </ul>\n"
            
            html += "    </div>\n"
    
    html += """
    <div class="footer">
        <p>⚠️ Đây là phân tích tự động, chỉ mang tính tham khảo, không phải khuyến nghị đầu tư.</p>
        <p>Powered by VN Stock Scanner</p>
    </div>
</body>
</html>
"""
    
    return html


def main():
    print("=" * 60)
    print("📝 REPORT GENERATOR")
    print("=" * 60)
    
    # Load data
    print("\n📊 Loading data...")
    analysis_data = load_analysis()
    if not analysis_data:
        print("❌ No analysis data found. Run ai_analyst.py first.")
        return
    
    screener_data = load_screener()
    
    # Generate Markdown
    print("\n📝 Generating Markdown report...")
    md_content = generate_markdown_report(analysis_data, screener_data)
    md_path = os.path.join(EXPORT_DIR, "daily_report.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"   Saved: {md_path}")
    
    # Generate HTML
    print("\n🌐 Generating HTML report...")
    html_content = generate_html_report(analysis_data, screener_data)
    html_path = os.path.join(EXPORT_DIR, "daily_report.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"   Saved: {html_path}")
    
    print("\n✅ Reports generated successfully!")


if __name__ == "__main__":
    main()
