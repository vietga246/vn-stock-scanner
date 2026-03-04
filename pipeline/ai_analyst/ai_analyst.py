"""
ai_analyst.py — AI-Powered Stock Analysis Module (v2)

Output format phù hợp với frontend design:
- ai_analysis.json với cấu trúc analyses[symbol] chứa recommendation, summary, highlights, risks

Features:
- Load top stocks từ stock_scores
- Tạo prompt với context đầy đủ (Technical + Fundamental + Smart Money)
- Gọi AI API để phân tích (hoặc fallback rule-based)
- Export ai_analysis.json cho frontend

Chạy sau scoring_engine.py và sector_analysis.py.
"""

import sqlite3
import pandas as pd
import json
import os
import logging
import sys
from datetime import datetime
from typing import Optional, Dict, List, Any

# ─── CONFIG ────────────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/db/stock.db")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")  # "openai" or "anthropic"
TOP_N_STOCKS = int(os.getenv("TOP_N_STOCKS", "50"))  # Increased for frontend
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2000"))

# ─── LOGGING ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── PROMPT TEMPLATES ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là một chuyên gia phân tích chứng khoán Việt Nam với 20 năm kinh nghiệm.
Nhiệm vụ: Phân tích các cổ phiếu được đề xuất và đưa ra nhận định đầu tư.

Phong cách phân tích:
- Ngắn gọn, súc tích, đi thẳng vào trọng tâm
- Sử dụng ngôn ngữ chuyên nghiệp nhưng dễ hiểu
- Đưa ra lý do cụ thể cho mỗi nhận định
- Cảnh báo rủi ro rõ ràng
- Không đưa ra lời khuyên tài chính cụ thể, chỉ phân tích

Format output: JSON với cấu trúc được chỉ định."""

ANALYSIS_PROMPT_TEMPLATE = """
Phân tích cổ phiếu {symbol} với dữ liệu sau:

## DỮ LIỆU CỔ PHIẾU

- Symbol: {symbol}
- Tên: {name}
- Ngành: {industry}
- Composite Score: {composite_score}/100 (Tier {tier})
- Fundamental Score: {fundamental_score}/100
- Smart Money Score: {smart_money_score}/100
- Momentum Score: {momentum_score}/100
- Technical Score: {technical_score}/100

Chỉ số tài chính:
- ROE: {roe}%
- ROA: {roa}%
- P/E: {pe}x
- Revenue Growth: {revenue_growth}%
- Net Margin: {net_margin}%
- Debt/Equity: {debt_equity}

Kỹ thuật:
- RSI(14): {rsi14}
- Trend Short: {trend_short}
- Price Change 5D: {price_change_5d}%
- Price Change 20D: {price_change_20d}%

Dòng tiền:
- Khối ngoại 7D: {foreign_net_7d}B VND
- Khối ngoại 30D: {foreign_net_30d}B VND

Ngành {industry}: {sector_status}

## YÊU CẦU

Trả về JSON với cấu trúc:
{{
  "recommendation": "STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL",
  "summary": "Tóm tắt 2-3 câu về cổ phiếu",
  "highlights": [
    {{"text": "Điểm tích cực 1", "type": "positive"}},
    {{"text": "Điểm tích cực 2", "type": "positive"}}
  ],
  "risks": [
    {{"text": "Rủi ro 1", "type": "negative"}},
    {{"text": "Cảnh báo 1", "type": "warning"}}
  ],
  "fundamental_view": "Nhận định về cơ bản (1 câu)",
  "technical_view": "Nhận định về kỹ thuật (1 câu)",
  "flow_view": "Nhận định về dòng tiền (1 câu)"
}}

Trả về CHÍNH XÁC JSON, không có text khác.
"""

# ─── DATA LOADERS ──────────────────────────────────────────────────────────

def create_connection():
    """Create database connection."""
    if not os.path.exists(DB_PATH):
        log.error("Database not found: %s", DB_PATH)
        return None
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def get_available_columns(conn, table: str) -> set:
    """Get available columns in a table."""
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cursor.fetchall()}
    except Exception as e:
        log.warning("Could not get columns for %s: %s", table, e)
        return set()


def load_top_stocks(conn, limit: int = 50) -> pd.DataFrame:
    """Load top N stocks by composite score - dynamically adapt to available columns."""
    
    available = get_available_columns(conn, "stock_scores")
    log.info("Available columns in stock_scores: %d", len(available))
    
    # Core columns
    core_cols = [
        "symbol", "composite_score", "fundamental_score", 
        "smart_money_score", "momentum_score", "technical_score",
        "tier", "rank_total"
    ]
    
    # Optional columns
    optional_cols = [
        "roe", "roa", "pe", "revenue_growth", "net_margin", "debt_equity",
        "rsi14", "price_change_5d", "price_change_20d", "trend_short",
        "foreign_net_7d", "foreign_net_30d", "vol_ratio"
    ]
    
    # Build SELECT clause
    select_cols = []
    for col in core_cols:
        if col in available:
            select_cols.append(f"s.{col}")
    
    for col in optional_cols:
        if col in available:
            select_cols.append(f"s.{col}")
    
    if not select_cols:
        log.error("No columns available in stock_scores!")
        return pd.DataFrame()
    
    query = f"""
        SELECT 
            {', '.join(select_cols)},
            sym.organ_name,
            sym.industry_name,
            sym.exchange
        FROM stock_scores s
        LEFT JOIN symbols sym ON s.symbol = sym.symbol
        WHERE s.composite_score IS NOT NULL
        ORDER BY s.composite_score DESC
        LIMIT ?
    """
    
    df = pd.read_sql(query, conn, params=(limit,))
    log.info("Loaded %d top stocks", len(df))
    return df


def load_sector_status(conn) -> Dict[str, str]:
    """Load sector accumulating/distributing status."""
    try:
        df = pd.read_sql("""
            SELECT 
                industry_name,
                total_foreign_7d,
                avg_composite
            FROM sector_scores
        """, conn)
        
        result = {}
        for _, row in df.iterrows():
            industry = row['industry_name']
            foreign = row.get('total_foreign_7d', 0) or 0
            score = row.get('avg_composite', 50) or 50
            
            if foreign > 10 and score > 55:
                result[industry] = 'accumulating'
            elif foreign < -10 and score < 50:
                result[industry] = 'distributing'
            else:
                result[industry] = 'neutral'
        
        return result
    except Exception as e:
        log.warning("Could not load sector status: %s", e)
        return {}


# ─── AI FUNCTIONS ──────────────────────────────────────────────────────────

def call_ai(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> Optional[str]:
    """Call AI API (OpenAI or Anthropic)."""
    
    if AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            log.error("Anthropic API error: %s", e)
            return None
    
    elif OPENAI_API_KEY:
        try:
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        except Exception as e:
            log.error("OpenAI API error: %s", e)
            return None
    
    return None


def parse_ai_response(response: str) -> Optional[Dict]:
    """Parse JSON from AI response."""
    try:
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        return json.loads(cleaned.strip())
    except json.JSONDecodeError as e:
        log.warning("Failed to parse AI response: %s", e)
        return None


# ─── RULE-BASED ANALYSIS ───────────────────────────────────────────────────

def generate_rule_based_analysis(row: pd.Series, sector_status: Dict[str, str]) -> Dict:
    """Generate analysis using rule-based logic (fallback when no AI)."""
    
    def safe_get(col, default=0):
        val = row.get(col, default)
        return default if pd.isna(val) else val
    
    symbol = row['symbol']
    score = safe_get('composite_score', 50)
    f_score = safe_get('fundamental_score', 50)
    s_score = safe_get('smart_money_score', 50)
    m_score = safe_get('momentum_score', 50)
    t_score = safe_get('technical_score', 50)
    tier = safe_get('tier', 'C')
    industry = safe_get('industry_name', '')
    
    # ─── Recommendation ───
    if score >= 75:
        recommendation = "STRONG_BUY"
        summary = f"{symbol} đang có điểm số xuất sắc ({score:.1f}) với tất cả các chỉ báo đều tích cực. Cổ phiếu thuộc nhóm chất lượng cao, đây là thời điểm tốt để tích lũy."
    elif score >= 65:
        recommendation = "BUY"
        summary = f"{symbol} có điểm số tốt ({score:.1f}) với nhiều yếu tố hỗ trợ. Có thể xem xét mua vào khi giá điều chỉnh về vùng hỗ trợ."
    elif score >= 55:
        recommendation = "HOLD"
        summary = f"{symbol} đang trong vùng trung tính ({score:.1f}). Nên giữ nếu đã có vị thế và chờ tín hiệu rõ ràng hơn trước khi hành động."
    elif score >= 45:
        recommendation = "SELL"
        summary = f"{symbol} có nhiều chỉ báo tiêu cực ({score:.1f}). Nên cân nhắc chốt lời hoặc cắt lỗ để bảo toàn vốn."
    else:
        recommendation = "STRONG_SELL"
        summary = f"{symbol} đang trong xu hướng giảm mạnh ({score:.1f}) với nhiều rủi ro. Khuyến nghị thoát hàng và chờ cơ hội tốt hơn."
    
    highlights = []
    risks = []
    
    # ─── Fundamental Analysis ───
    roe = safe_get('roe', 0)
    roa = safe_get('roa', 0)
    pe = safe_get('pe', 0)
    revenue_growth = safe_get('revenue_growth', 0)
    debt_equity = safe_get('debt_equity', 0)
    
    if f_score >= 75:
        fundamental_view = "Nền tảng tài chính vững chắc với các chỉ số cơ bản ấn tượng."
        highlights.append({"text": f"Điểm cơ bản {f_score:.0f}/100 - Tài chính lành mạnh", "type": "positive"})
        if roe > 15:
            highlights.append({"text": f"ROE {roe:.1f}% - Sinh lời trên vốn cao", "type": "positive"})
        if 0 < pe < 15:
            highlights.append({"text": f"P/E {pe:.1f} - Định giá hấp dẫn", "type": "positive"})
        if revenue_growth > 20:
            highlights.append({"text": f"Tăng trưởng doanh thu {revenue_growth:.1f}% - Tăng mạnh", "type": "positive"})
    elif f_score >= 55:
        fundamental_view = "Tài chính ổn định, các chỉ số trong ngưỡng chấp nhận được."
        highlights.append({"text": f"Điểm cơ bản {f_score:.0f}/100 - Tài chính ổn định", "type": "neutral"})
    else:
        fundamental_view = "Nền tảng tài chính cần được cải thiện, theo dõi khả năng trả nợ."
        risks.append({"text": f"Điểm cơ bản {f_score:.0f}/100 - Tài chính cần cải thiện", "type": "negative"})
        if debt_equity > 2:
            risks.append({"text": f"D/E {debt_equity:.1f} - Đòn bẩy tài chính cao", "type": "negative"})
        if pe > 25 and pe > 0:
            risks.append({"text": f"P/E {pe:.1f} - Định giá cao", "type": "warning"})
    
    # ─── Smart Money Analysis ───
    nn7d = safe_get('foreign_net_7d', 0)
    nn30d = safe_get('foreign_net_30d', 0)
    
    if s_score >= 70 and nn7d > 0:
        flow_view = "Dòng tiền lớn đang tích lũy mạnh, khối ngoại mua ròng liên tục."
        highlights.append({"text": f"Khối ngoại mua ròng +{nn7d:.1f}B trong 7 ngày", "type": "positive"})
        if nn30d > nn7d * 3:
            highlights.append({"text": f"Tích lũy bền vững: +{nn30d:.1f}B trong 30 ngày", "type": "positive"})
    elif s_score >= 55:
        flow_view = "Dòng tiền ổn định, không có dấu hiệu phân phối lớn."
    else:
        flow_view = "Dòng tiền đang rút ra, khối ngoại bán ròng."
        if nn7d < -5:
            risks.append({"text": f"Khối ngoại bán ròng {nn7d:.1f}B trong 7 ngày", "type": "negative"})
    
    # ─── Momentum Analysis ───
    change_5d = safe_get('price_change_5d', 0)
    change_20d = safe_get('price_change_20d', 0)
    
    if m_score >= 70:
        highlights.append({"text": "Momentum mạnh - Đà tăng tích cực", "type": "positive"})
        if change_20d > 10:
            highlights.append({"text": f"Tăng {change_20d:.1f}% trong 20 phiên - Uptrend mạnh", "type": "positive"})
    elif m_score < 45:
        risks.append({"text": "Momentum yếu - Đà tăng suy giảm", "type": "negative"})
        if change_20d < -10:
            risks.append({"text": f"Giảm {abs(change_20d):.1f}% trong 20 phiên - Downtrend", "type": "negative"})
    
    # ─── Technical Analysis ───
    rsi = safe_get('rsi14', 50)
    trend = safe_get('trend_short', 0)
    
    if t_score >= 70:
        technical_view = "Kỹ thuật tích cực, giá trên các đường MA, xu hướng tăng rõ ràng."
        highlights.append({"text": "Tín hiệu kỹ thuật tích cực", "type": "positive"})
        if 50 <= rsi <= 70:
            highlights.append({"text": f"RSI {rsi:.0f} - Vùng tăng bền vững", "type": "positive"})
    elif t_score >= 55:
        technical_view = "Kỹ thuật trung tính, đang tích lũy trong biên độ hẹp."
        if rsi > 70:
            risks.append({"text": f"RSI {rsi:.0f} - Vùng quá mua, cẩn thận điều chỉnh", "type": "warning"})
    else:
        technical_view = "Kỹ thuật tiêu cực, giá dưới MA, momentum giảm."
        risks.append({"text": "Tín hiệu kỹ thuật tiêu cực", "type": "negative"})
        if rsi < 30:
            highlights.append({"text": f"RSI {rsi:.0f} - Quá bán, có thể rebound", "type": "neutral"})
    
    # ─── Sector Analysis ───
    status = sector_status.get(industry, 'neutral')
    if status == 'accumulating':
        highlights.append({"text": f"Ngành {industry} đang được tích lũy", "type": "positive"})
    elif status == 'distributing':
        risks.append({"text": f"Ngành {industry} đang bị phân phối", "type": "negative"})
    
    # ─── Tier Analysis ───
    if tier == 'A':
        highlights.append({"text": "Tier A - Cổ phiếu chất lượng cao, thanh khoản tốt", "type": "positive"})
    elif tier in ['D', 'F']:
        risks.append({"text": f"Tier {tier} - Cần theo dõi chặt chẽ, rủi ro cao", "type": "warning"})
    
    return {
        "symbol": symbol,
        "recommendation": recommendation,
        "summary": summary,
        "highlights": highlights[:5],  # Limit to 5
        "risks": risks[:4],  # Limit to 4
        "fundamental_view": fundamental_view,
        "technical_view": technical_view,
        "flow_view": flow_view,
    }


def analyze_single_stock_with_ai(row: pd.Series, sector_status: Dict[str, str]) -> Optional[Dict]:
    """Analyze single stock with AI API."""
    
    def safe_get(col, default=0):
        val = row.get(col, default)
        return default if pd.isna(val) else val
    
    industry = safe_get('industry_name', '')
    status = sector_status.get(industry, 'neutral')
    status_text = "đang được tích lũy" if status == 'accumulating' else "đang bị phân phối" if status == 'distributing' else "trung lập"
    
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        symbol=row['symbol'],
        name=safe_get('organ_name', row['symbol']),
        industry=industry,
        composite_score=f"{safe_get('composite_score', 50):.1f}",
        tier=safe_get('tier', 'C'),
        fundamental_score=f"{safe_get('fundamental_score', 50):.1f}",
        smart_money_score=f"{safe_get('smart_money_score', 50):.1f}",
        momentum_score=f"{safe_get('momentum_score', 50):.1f}",
        technical_score=f"{safe_get('technical_score', 50):.1f}",
        roe=f"{safe_get('roe', 0):.1f}",
        roa=f"{safe_get('roa', 0):.1f}",
        pe=f"{safe_get('pe', 0):.1f}",
        revenue_growth=f"{safe_get('revenue_growth', 0):.1f}",
        net_margin=f"{safe_get('net_margin', 0):.1f}",
        debt_equity=f"{safe_get('debt_equity', 0):.2f}",
        rsi14=f"{safe_get('rsi14', 50):.0f}",
        trend_short="↑ Up" if safe_get('trend_short', 0) == 1 else "↓ Down" if safe_get('trend_short', 0) == -1 else "→ Side",
        price_change_5d=f"{safe_get('price_change_5d', 0):.1f}",
        price_change_20d=f"{safe_get('price_change_20d', 0):.1f}",
        foreign_net_7d=f"{safe_get('foreign_net_7d', 0):.1f}",
        foreign_net_30d=f"{safe_get('foreign_net_30d', 0):.1f}",
        sector_status=status_text,
    )
    
    response = call_ai(prompt)
    if response:
        result = parse_ai_response(response)
        if result:
            result['symbol'] = row['symbol']
            return result
    
    return None


# ─── EXPORT FUNCTIONS ──────────────────────────────────────────────────────

def export_analysis(analyses: Dict[str, Dict], model: str):
    """Export analysis to ai_analysis.json for frontend."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Summary statistics
    rec_counts = {}
    for a in analyses.values():
        rec = a.get('recommendation', 'HOLD')
        rec_counts[rec] = rec_counts.get(rec, 0) + 1
    
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model": model,
        "total_analyzed": len(analyses),
        "summary": {
            "STRONG_BUY": rec_counts.get('STRONG_BUY', 0),
            "BUY": rec_counts.get('BUY', 0),
            "HOLD": rec_counts.get('HOLD', 0),
            "SELL": rec_counts.get('SELL', 0),
            "STRONG_SELL": rec_counts.get('STRONG_SELL', 0),
        },
        "analyses": analyses,
    }
    
    out_path = os.path.join(EXPORT_DIR, "ai_analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log.info("✅ Exported → %s", out_path)
    log.info("   Model: %s", model)
    log.info("   Total: %d stocks", len(analyses))
    log.info("   Summary: %s", rec_counts)


# ─── MAIN ──────────────────────────────────────────────────────────────────

def run():
    """Main function to run AI analysis."""
    log.info("=" * 60)
    log.info("🤖 AI ANALYST — VN Stock Scanner")
    log.info("=" * 60)
    
    # Load data
    conn = create_connection()
    if conn is None:
        log.error("Cannot connect to database")
        return
    
    stocks_df = load_top_stocks(conn, limit=TOP_N_STOCKS)
    sector_status = load_sector_status(conn)
    conn.close()
    
    if stocks_df.empty:
        log.error("No stock data available. Run scoring_engine.py first.")
        return
    
    log.info("📊 Loaded %d stocks", len(stocks_df))
    log.info("📈 Sector status: %d accumulating, %d distributing",
             sum(1 for v in sector_status.values() if v == 'accumulating'),
             sum(1 for v in sector_status.values() if v == 'distributing'))
    
    # Generate analyses
    analyses = {}
    model_used = "rule-based"
    use_ai = bool(OPENAI_API_KEY or ANTHROPIC_API_KEY)
    
    if use_ai:
        model_used = f"ai-{AI_PROVIDER}"
        log.info("🤖 Using AI provider: %s", AI_PROVIDER)
    else:
        log.info("📋 Using rule-based analysis (no AI API key)")
    
    log.info("🔍 Generating analyses...")
    
    for i, (_, row) in enumerate(stocks_df.iterrows()):
        symbol = row['symbol']
        
        # Try AI first if available (only for top 10 to save API calls)
        if use_ai and i < 10:
            ai_result = analyze_single_stock_with_ai(row, sector_status)
            if ai_result:
                analyses[symbol] = ai_result
                continue
        
        # Fallback to rule-based
        analyses[symbol] = generate_rule_based_analysis(row, sector_status)
        
        if (i + 1) % 10 == 0:
            log.info("   Processed %d/%d stocks", i + 1, len(stocks_df))
    
    # Export
    export_analysis(analyses, model_used)
    
    # Summary
    log.info("")
    log.info("📋 Top 5 recommendations:")
    for symbol, analysis in list(analyses.items())[:5]:
        log.info("   %s: %s", symbol, analysis.get('recommendation', 'N/A'))
    
    log.info("")
    log.info("✅ AI Analyst completed")


if __name__ == "__main__":
    run()
