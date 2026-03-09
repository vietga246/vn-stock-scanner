#!/usr/bin/env python3
"""
AI Analyst - Generate analysis for VN Stock Scanner frontend
Output: ai_analysis.json với cấu trúc phù hợp cho frontend design

Cấu trúc output:
{
    "generated_at": "2024-01-01T10:00:00Z",
    "model": "rule-based" | "gpt-4" | "claude-3",
    "analyses": {
        "VCB": {
            "symbol": "VCB",
            "recommendation": "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL",
            "summary": "Nhận định tổng quan...",
            "highlights": [
                {"text": "Điểm tích cực 1", "type": "positive"},
                {"text": "Điểm tích cực 2", "type": "positive"}
            ],
            "risks": [
                {"text": "Rủi ro 1", "type": "negative"},
                {"text": "Cảnh báo 1", "type": "warning"}
            ],
            "fundamental_view": "Phân tích cơ bản...",
            "technical_view": "Phân tích kỹ thuật...",
            "flow_view": "Phân tích dòng tiền...",
            "target_price": 100000,
            "stop_loss": 85000
        }
    }
}
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from typing import Optional

# ============ Configuration ============

DB_PATH = os.environ.get("DB_PATH", "data/db/stock.db")
EXPORT_DIR = os.environ.get("EXPORT_DIR", "data/exports")
TOP_N_STOCKS = int(os.environ.get("TOP_N_STOCKS", "50"))

# AI Provider config
AI_PROVIDER = os.environ.get("AI_PROVIDER", "").lower()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ============ Database Functions ============

def get_db_connection():
    """Get database connection"""
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def get_top_stocks(limit: int = 50) -> list:
    """Get top stocks by composite score from screener"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
    SELECT 
        ss.symbol,
        s.short_name as name,
        s.industry,
        s.exchange,
        ss.composite_score,
        ss.fundamental_score,
        ss.smart_money_score,
        ss.momentum_score,
        ss.technical_score,
        ss.tier,
        ss.rank,
        -- Fundamentals
        fr.roe,
        fr.roa,
        fr.pe,
        fr.pb,
        fr.revenue_growth,
        fr.net_margin,
        fr.debt_equity,
        -- Technical
        ti.rsi14,
        ti.trend_short,
        ti.trend_medium,
        ti.macd_signal,
        -- Price changes
        ti.close,
        ti.change_1d,
        ti.change_5d,
        ti.change_20d,
        -- Smart money
        COALESCE(
            (SELECT SUM(net_value) FROM foreign_trading 
             WHERE symbol = ss.symbol 
             AND date >= date('now', '-7 days')), 0
        ) / 1e9 as foreign_net_7d,
        COALESCE(
            (SELECT SUM(net_value) FROM foreign_trading 
             WHERE symbol = ss.symbol 
             AND date >= date('now', '-30 days')), 0
        ) / 1e9 as foreign_net_30d
    FROM stock_scores ss
    LEFT JOIN symbols s ON ss.symbol = s.symbol
    LEFT JOIN (
        SELECT * FROM financials_ratio 
        WHERE (symbol, period) IN (
            SELECT symbol, MAX(period) FROM financials_ratio GROUP BY symbol
        )
    ) fr ON ss.symbol = fr.symbol
    LEFT JOIN (
        SELECT * FROM technical_indicators 
        WHERE (symbol, date) IN (
            SELECT symbol, MAX(date) FROM technical_indicators GROUP BY symbol
        )
    ) ti ON ss.symbol = ti.symbol
    WHERE ss.composite_score IS NOT NULL
    ORDER BY ss.composite_score DESC
    LIMIT ?
    """
    
    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_sector_status() -> dict:
    """Get sector accumulating/distributing status"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
    SELECT 
        s.industry,
        SUM(CASE WHEN ft.net_value > 0 THEN ft.net_value ELSE 0 END) / 1e9 as buy_value,
        SUM(CASE WHEN ft.net_value < 0 THEN ft.net_value ELSE 0 END) / 1e9 as sell_value,
        SUM(ft.net_value) / 1e9 as net_value
    FROM foreign_trading ft
    JOIN symbols s ON ft.symbol = s.symbol
    WHERE ft.date >= date('now', '-7 days')
    GROUP BY s.industry
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    result = {}
    for row in rows:
        industry = row['industry']
        net = row['net_value'] or 0
        if net > 10:
            result[industry] = 'accumulating'
        elif net < -10:
            result[industry] = 'distributing'
        else:
            result[industry] = 'neutral'
    
    return result


# ============ Rule-Based Analysis ============

def generate_rule_based_analysis(stock: dict, sector_status: dict) -> dict:
    """Generate analysis using rule-based logic"""
    
    symbol = stock['symbol']
    score = stock['composite_score'] or 0
    f_score = stock['fundamental_score'] or 50
    s_score = stock['smart_money_score'] or 50
    m_score = stock['momentum_score'] or 50
    t_score = stock['technical_score'] or 50
    
    analysis = {
        "symbol": symbol,
        "recommendation": "HOLD",
        "summary": "",
        "highlights": [],
        "risks": [],
        "fundamental_view": "",
        "technical_view": "",
        "flow_view": "",
        "target_price": None,
        "stop_loss": None
    }
    
    # ============ Recommendation ============
    if score >= 75:
        analysis["recommendation"] = "STRONG_BUY"
        analysis["summary"] = f"{symbol} đang có điểm số xuất sắc ({score:.1f}) với tất cả các chỉ báo đều tích cực. Cổ phiếu thuộc nhóm chất lượng cao, đây là thời điểm tốt để tích lũy."
    elif score >= 65:
        analysis["recommendation"] = "BUY"
        analysis["summary"] = f"{symbol} có điểm số tốt ({score:.1f}) với nhiều yếu tố hỗ trợ. Có thể xem xét mua vào khi giá điều chỉnh về vùng hỗ trợ."
    elif score >= 55:
        analysis["recommendation"] = "HOLD"
        analysis["summary"] = f"{symbol} đang trong vùng trung tính ({score:.1f}). Nên giữ nếu đã có vị thế và chờ tín hiệu rõ ràng hơn trước khi hành động."
    elif score >= 45:
        analysis["recommendation"] = "SELL"
        analysis["summary"] = f"{symbol} có nhiều chỉ báo tiêu cực ({score:.1f}). Nên cân nhắc chốt lời hoặc cắt lỗ để bảo toàn vốn."
    else:
        analysis["recommendation"] = "STRONG_SELL"
        analysis["summary"] = f"{symbol} đang trong xu hướng giảm mạnh ({score:.1f}) với nhiều rủi ro. Khuyến nghị thoát hàng và chờ cơ hội tốt hơn."
    
    # ============ Fundamental Analysis ============
    roe = stock.get('roe') or 0
    pe = stock.get('pe') or 0
    debt_equity = stock.get('debt_equity') or 0
    revenue_growth = stock.get('revenue_growth') or 0
    
    if f_score >= 75:
        analysis["fundamental_view"] = "Nền tảng tài chính vững chắc với các chỉ số cơ bản ấn tượng."
        analysis["highlights"].append({
            "text": f"Điểm cơ bản {f_score:.0f}/100 - Tài chính lành mạnh",
            "type": "positive"
        })
        if roe > 0.15:
            analysis["highlights"].append({
                "text": f"ROE {roe*100:.1f}% - Sinh lời trên vốn cao",
                "type": "positive"
            })
        if 0 < pe < 15:
            analysis["highlights"].append({
                "text": f"P/E {pe:.1f} - Định giá hấp dẫn",
                "type": "positive"
            })
    elif f_score >= 55:
        analysis["fundamental_view"] = "Tài chính ổn định, các chỉ số trong ngưỡng chấp nhận được."
        analysis["highlights"].append({
            "text": f"Điểm cơ bản {f_score:.0f}/100 - Tài chính ổn định",
            "type": "neutral"
        })
    else:
        analysis["fundamental_view"] = "Nền tảng tài chính cần được cải thiện, theo dõi khả năng trả nợ."
        analysis["risks"].append({
            "text": f"Điểm cơ bản {f_score:.0f}/100 - Tài chính cần cải thiện",
            "type": "negative"
        })
        if debt_equity > 2:
            analysis["risks"].append({
                "text": f"D/E {debt_equity:.1f} - Đòn bẩy tài chính cao",
                "type": "negative"
            })
    
    # ============ Smart Money Flow ============
    nn7d = stock.get('foreign_net_7d') or 0
    nn30d = stock.get('foreign_net_30d') or 0
    
    if s_score >= 70 and nn7d > 0:
        analysis["flow_view"] = "Dòng tiền lớn đang tích lũy mạnh, khối ngoại mua ròng liên tục."
        analysis["highlights"].append({
            "text": f"Khối ngoại mua ròng +{nn7d:.1f}B trong 7 ngày",
            "type": "positive"
        })
        if nn30d > nn7d * 3:
            analysis["highlights"].append({
                "text": f"Tích lũy bền vững: +{nn30d:.1f}B trong 30 ngày",
                "type": "positive"
            })
    elif s_score >= 55:
        analysis["flow_view"] = "Dòng tiền ổn định, không có dấu hiệu phân phối lớn."
    else:
        analysis["flow_view"] = "Dòng tiền đang rút ra, khối ngoại bán ròng."
        if nn7d < -5:
            analysis["risks"].append({
                "text": f"Khối ngoại bán ròng {nn7d:.1f}B trong 7 ngày",
                "type": "negative"
            })
    
    # ============ Momentum ============
    change_5d = stock.get('change_5d') or 0
    change_20d = stock.get('change_20d') or 0
    
    if m_score >= 70:
        analysis["highlights"].append({
            "text": "Momentum mạnh - Đà tăng tích cực",
            "type": "positive"
        })
        if change_20d > 10:
            analysis["highlights"].append({
                "text": f"Tăng {change_20d:.1f}% trong 20 phiên - Uptrend mạnh",
                "type": "positive"
            })
    elif m_score < 45:
        analysis["risks"].append({
            "text": "Momentum yếu - Đà tăng suy giảm",
            "type": "negative"
        })
        if change_20d < -10:
            analysis["risks"].append({
                "text": f"Giảm {abs(change_20d):.1f}% trong 20 phiên - Downtrend",
                "type": "negative"
            })
    
    # ============ Technical ============
    rsi = stock.get('rsi14') or 50
    trend = stock.get('trend_short') or 0
    
    if t_score >= 70:
        analysis["technical_view"] = "Kỹ thuật tích cực, giá trên các đường MA, xu hướng tăng rõ ràng."
        analysis["highlights"].append({
            "text": "Tín hiệu kỹ thuật tích cực",
            "type": "positive"
        })
        if 50 <= rsi <= 70:
            analysis["highlights"].append({
                "text": f"RSI {rsi:.0f} - Vùng tăng bền vững",
                "type": "positive"
            })
    elif t_score >= 55:
        analysis["technical_view"] = "Kỹ thuật trung tính, đang tích lũy trong biên độ hẹp."
        if rsi > 70:
            analysis["risks"].append({
                "text": f"RSI {rsi:.0f} - Vùng quá mua, cẩn thận điều chỉnh",
                "type": "warning"
            })
    else:
        analysis["technical_view"] = "Kỹ thuật tiêu cực, giá dưới MA, momentum giảm."
        analysis["risks"].append({
            "text": "Tín hiệu kỹ thuật tiêu cực",
            "type": "negative"
        })
        if rsi < 30:
            analysis["highlights"].append({
                "text": f"RSI {rsi:.0f} - Quá bán, có thể rebound",
                "type": "neutral"
            })
    
    # ============ Sector ============
    industry = stock.get('industry', '')
    status = sector_status.get(industry, 'neutral')
    
    if status == 'accumulating':
        analysis["highlights"].append({
            "text": f"Ngành {industry} đang được tích lũy",
            "type": "positive"
        })
    elif status == 'distributing':
        analysis["risks"].append({
            "text": f"Ngành {industry} đang bị phân phối",
            "type": "negative"
        })
    
    # ============ Tier ============
    tier = stock.get('tier', 'C')
    if tier == 'A':
        analysis["highlights"].append({
            "text": "Tier A - Cổ phiếu chất lượng cao, thanh khoản tốt",
            "type": "positive"
        })
    elif tier in ['D', 'F']:
        analysis["risks"].append({
            "text": f"Tier {tier} - Cần theo dõi chặt chẽ, rủi ro cao",
            "type": "warning"
        })
    
    # ============ Target Price & Stop Loss ============
    close = stock.get('close') or 0
    if close > 0:
        if analysis["recommendation"] in ["STRONG_BUY", "BUY"]:
            analysis["target_price"] = round(close * 1.15, -2)  # +15%
            analysis["stop_loss"] = round(close * 0.93, -2)     # -7%
        elif analysis["recommendation"] == "HOLD":
            analysis["target_price"] = round(close * 1.08, -2)  # +8%
            analysis["stop_loss"] = round(close * 0.95, -2)     # -5%
    
    return analysis


# ============ AI-Powered Analysis (Optional) ============

def generate_ai_analysis(stock: dict, sector_status: dict) -> Optional[dict]:
    """Generate analysis using AI (OpenAI or Anthropic)"""
    
    if not AI_PROVIDER:
        return None
    
    prompt = f"""
    Phân tích cổ phiếu {stock['symbol']} - {stock.get('name', '')} (Ngành: {stock.get('industry', '')})
    
    Dữ liệu:
    - Composite Score: {stock.get('composite_score', 0):.1f}/100
    - Fundamental: {stock.get('fundamental_score', 0):.1f}/100
    - Smart Money: {stock.get('smart_money_score', 0):.1f}/100  
    - Momentum: {stock.get('momentum_score', 0):.1f}/100
    - Technical: {stock.get('technical_score', 0):.1f}/100
    - Tier: {stock.get('tier', 'C')}
    - ROE: {(stock.get('roe') or 0)*100:.1f}%
    - P/E: {stock.get('pe', 0):.1f}
    - RSI: {stock.get('rsi14', 50):.0f}
    - Khối ngoại 7D: {stock.get('foreign_net_7d', 0):.1f}B
    - Biến động 20D: {stock.get('change_20d', 0):.1f}%
    
    Hãy đưa ra phân tích ngắn gọn bằng tiếng Việt với:
    1. Khuyến nghị: STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    2. Tóm tắt 2-3 câu
    3. 2-3 điểm tích cực
    4. 2-3 rủi ro cần lưu ý
    5. Nhận định cơ bản, kỹ thuật, dòng tiền (mỗi phần 1 câu)
    
    Trả về JSON format.
    """
    
    try:
        if AI_PROVIDER == "openai" and OPENAI_API_KEY:
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            return json.loads(response.choices[0].message.content)
            
        elif AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            # Parse JSON from response
            text = response.content[0].text
            # Find JSON in response
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
                
    except Exception as e:
        print(f"⚠️ AI analysis failed for {stock['symbol']}: {e}")
    
    return None


# ============ Main ============

def main():
    print("=" * 60)
    print("🤖 AI ANALYST - VN Stock Scanner")
    print("=" * 60)
    
    # Get data
    print(f"\n📊 Loading top {TOP_N_STOCKS} stocks...")
    stocks = get_top_stocks(TOP_N_STOCKS)
    print(f"   Found {len(stocks)} stocks")
    
    print("\n📈 Loading sector status...")
    sector_status = get_sector_status()
    print(f"   Accumulating: {sum(1 for v in sector_status.values() if v == 'accumulating')}")
    print(f"   Distributing: {sum(1 for v in sector_status.values() if v == 'distributing')}")
    
    # Generate analyses
    print(f"\n🔍 Generating analyses...")
    
    model_used = "rule-based"
    analyses = {}
    
    for i, stock in enumerate(stocks):
        symbol = stock['symbol']
        
        # Try AI first if configured
        ai_analysis = None
        if AI_PROVIDER and (OPENAI_API_KEY or ANTHROPIC_API_KEY):
            ai_analysis = generate_ai_analysis(stock, sector_status)
            if ai_analysis:
                model_used = f"ai-{AI_PROVIDER}"
        
        # Fallback to rule-based
        if ai_analysis:
            # Merge AI analysis with rule-based structure
            rule_analysis = generate_rule_based_analysis(stock, sector_status)
            analyses[symbol] = {**rule_analysis, **ai_analysis}
        else:
            analyses[symbol] = generate_rule_based_analysis(stock, sector_status)
        
        if (i + 1) % 10 == 0:
            print(f"   Processed {i + 1}/{len(stocks)} stocks")
    
    # Build output
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model": model_used,
        "total_analyzed": len(analyses),
        "analyses": analyses
    }
    
    # Save to file
    os.makedirs(EXPORT_DIR, exist_ok=True)
    output_path = os.path.join(EXPORT_DIR, "ai_analysis.json")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Saved to {output_path}")
    print(f"   Model: {model_used}")
    print(f"   Analyzed: {len(analyses)} stocks")
    
    # Summary
    rec_counts = {}
    for a in analyses.values():
        rec = a.get('recommendation', 'HOLD')
        rec_counts[rec] = rec_counts.get(rec, 0) + 1
    
    print(f"\n📋 Recommendation Summary:")
    for rec, count in sorted(rec_counts.items()):
        print(f"   {rec}: {count}")


if __name__ == "__main__":
    main()
