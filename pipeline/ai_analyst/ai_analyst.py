"""
ai_analyst.py — AI-Powered Stock Analysis Module

Tự động phân tích top picks bằng OpenAI/Claude API.
Tạo báo cáo phân tích chuyên sâu với reasoning.

Features:
- Load top stocks từ stock_scores
- Tạo prompt với context đầy đủ (Technical + Fundamental + Smart Money)
- Gọi AI API để phân tích
- Export analysis.json cho frontend

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
TOP_N_STOCKS = int(os.getenv("TOP_N_STOCKS", "10"))
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
Phân tích {n_stocks} cổ phiếu sau đây và đưa ra nhận định:

## DỮ LIỆU CỔ PHIẾU

{stock_data}

## DỮ LIỆU NGÀNH

{sector_data}

## YÊU CẦU PHÂN TÍCH

Trả về JSON với cấu trúc sau:

```json
{{
  "market_overview": {{
    "sentiment": "bullish|bearish|neutral",
    "summary": "Tóm tắt 2-3 câu về thị trường",
    "key_themes": ["Theme 1", "Theme 2"]
  }},
  "top_picks": [
    {{
      "symbol": "XXX",
      "recommendation": "strong_buy|buy|hold|sell|strong_sell",
      "target_score": 75,
      "reasoning": {{
        "fundamental": "Nhận định về cơ bản",
        "technical": "Nhận định về kỹ thuật",
        "smart_money": "Nhận định về dòng tiền"
      }},
      "catalysts": ["Catalyst 1", "Catalyst 2"],
      "risks": ["Risk 1", "Risk 2"],
      "time_horizon": "short|medium|long"
    }}
  ],
  "sector_rotation": {{
    "accumulating": ["Ngành 1", "Ngành 2"],
    "avoiding": ["Ngành 3"],
    "rationale": "Lý do cho rotation"
  }},
  "watchlist": [
    {{
      "symbol": "YYY",
      "reason": "Lý do theo dõi",
      "trigger": "Điều kiện để action"
    }}
  ]
}}
```

Lưu ý:
- Chỉ phân tích dựa trên data được cung cấp
- Ưu tiên cổ phiếu có composite_score cao + smart_money_score tốt
- Cảnh báo nếu RSI > 70 (overbought) hoặc < 30 (oversold)
- Xem xét xu hướng ngành trước khi đề xuất

Trả về CHÍNH XÁC JSON, không có text khác.
"""

DAILY_REPORT_PROMPT = """
Tạo báo cáo phân tích thị trường ngày {date} dựa trên data sau:

## TOP 10 CỔ PHIẾU THEO COMPOSITE SCORE

{top_stocks}

## PHÂN TÍCH NGÀNH

{sector_analysis}

## TÍN HIỆU KỸ THUẬT

{technical_signals}

---

Tạo báo cáo ngắn gọn (500-800 từ) theo format:

1. **Tổng quan thị trường** (2-3 câu)
2. **Top 3 cổ phiếu đáng chú ý** - mỗi cổ phiếu 3-4 câu giải thích
3. **Ngành nổi bật** - 2-3 câu về sector rotation
4. **Cảnh báo rủi ro** - 2-3 điểm cần lưu ý
5. **Kết luận** - 1-2 câu

Viết bằng tiếng Việt, chuyên nghiệp, dễ hiểu.
"""

# ─── DATA LOADERS ──────────────────────────────────────────────────────────

def create_connection():
    """Create database connection."""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def load_top_stocks(conn, limit: int = 10) -> pd.DataFrame:
    """Load top N stocks by composite score."""
    query = """
        SELECT 
            s.symbol,
            s.composite_score,
            s.fundamental_score,
            s.smart_money_score,
            s.momentum_score,
            s.technical_score,
            s.tier,
            s.rank_total,
            s.roe,
            s.roa,
            s.pe,
            s.revenue_growth,
            s.net_margin,
            s.debt_equity,
            s.rsi14,
            s.price_change_5d,
            s.price_change_20d,
            s.trend_short,
            s.foreign_net_7d,
            s.foreign_net_30d,
            s.vol_ratio,
            sym.organ_name,
            sym.industry_name
        FROM stock_scores s
        LEFT JOIN symbols sym ON s.symbol = sym.symbol
        WHERE s.composite_score IS NOT NULL
        ORDER BY s.composite_score DESC
        LIMIT ?
    """
    df = pd.read_sql(query, conn, params=(limit,))
    log.info("Loaded %d top stocks", len(df))
    return df


def load_sector_data(conn) -> pd.DataFrame:
    """Load sector analysis data."""
    try:
        df = pd.read_sql("""
            SELECT * FROM sector_scores
            ORDER BY avg_composite DESC
        """, conn)
        return df
    except Exception as e:
        log.warning("Could not load sector_scores: %s", e)
        return pd.DataFrame()


def load_technical_signals(conn) -> Dict[str, Any]:
    """Load aggregate technical signals."""
    try:
        # RSI distribution
        rsi_query = """
            SELECT 
                SUM(CASE WHEN rsi14 > 70 THEN 1 ELSE 0 END) as overbought,
                SUM(CASE WHEN rsi14 < 30 THEN 1 ELSE 0 END) as oversold,
                SUM(CASE WHEN rsi14 BETWEEN 30 AND 70 THEN 1 ELSE 0 END) as neutral,
                AVG(rsi14) as avg_rsi
            FROM stock_scores
            WHERE rsi14 IS NOT NULL
        """
        rsi = pd.read_sql(rsi_query, conn).iloc[0].to_dict()
        
        # Trend distribution
        trend_query = """
            SELECT 
                SUM(CASE WHEN trend_short = 1 THEN 1 ELSE 0 END) as uptrend,
                SUM(CASE WHEN trend_short = -1 THEN 1 ELSE 0 END) as downtrend,
                SUM(CASE WHEN trend_short = 0 THEN 1 ELSE 0 END) as sideways
            FROM stock_scores
            WHERE trend_short IS NOT NULL
        """
        trend = pd.read_sql(trend_query, conn).iloc[0].to_dict()
        
        # Top movers
        movers_query = """
            SELECT symbol, price_change_5d, price_change_20d
            FROM stock_scores
            WHERE price_change_5d IS NOT NULL
            ORDER BY price_change_5d DESC
            LIMIT 5
        """
        top_gainers = pd.read_sql(movers_query, conn).to_dict('records')
        
        return {
            "rsi": rsi,
            "trend": trend,
            "top_gainers": top_gainers,
        }
    except Exception as e:
        log.warning("Could not load technical signals: %s", e)
        return {}


# ─── DATA FORMATTERS ───────────────────────────────────────────────────────

def format_stock_for_prompt(row: pd.Series) -> str:
    """Format a single stock row for prompt."""
    return f"""
### {row['symbol']} - {row.get('organ_name', 'N/A')} ({row.get('industry_name', 'N/A')})
- **Composite Score**: {row['composite_score']:.1f} (Tier {row['tier']}, Rank #{row['rank_total']})
- **Sub-scores**: Fundamental {row['fundamental_score']:.1f} | Smart Money {row['smart_money_score']:.1f} | Momentum {row['momentum_score']:.1f} | Technical {row['technical_score']:.1f}
- **Fundamentals**: ROE {row['roe']:.1f}% | ROA {row['roa']:.1f}% | PE {row['pe']:.1f}x | Revenue Growth {row['revenue_growth']:.1f}%
- **Technical**: RSI {row['rsi14']:.1f} | 5D Change {row['price_change_5d']:.1f}% | 20D Change {row['price_change_20d']:.1f}% | Trend {'↑' if row['trend_short'] == 1 else '↓' if row['trend_short'] == -1 else '→'}
- **Smart Money**: Foreign Net 7D {row['foreign_net_7d']:.1f}B | Foreign Net 30D {row['foreign_net_30d']:.1f}B | Vol Ratio {row['vol_ratio']:.2f}x
"""


def format_stocks_for_prompt(df: pd.DataFrame) -> str:
    """Format all stocks for prompt."""
    formatted = []
    for _, row in df.iterrows():
        # Handle NaN values
        row_filled = row.fillna(0)
        formatted.append(format_stock_for_prompt(row_filled))
    return "\n".join(formatted)


def format_sectors_for_prompt(df: pd.DataFrame) -> str:
    """Format sector data for prompt."""
    if df.empty:
        return "Không có dữ liệu ngành."
    
    lines = ["| Ngành | Score | Foreign 7D | Momentum Rank |"]
    lines.append("|-------|-------|------------|---------------|")
    
    for _, row in df.head(10).iterrows():
        name = row.get('industry_name', row.get('name', 'N/A'))
        score = row.get('avg_composite', row.get('avg_composite_score', 0))
        foreign = row.get('total_foreign_7d', row.get('foreign_net_7d', 0)) or 0
        momentum = row.get('momentum_rank', 'N/A')
        lines.append(f"| {name} | {score:.1f} | {foreign:.1f}B | {momentum} |")
    
    return "\n".join(lines)


def format_technical_for_prompt(signals: Dict) -> str:
    """Format technical signals for prompt."""
    if not signals:
        return "Không có dữ liệu kỹ thuật."
    
    rsi = signals.get('rsi', {})
    trend = signals.get('trend', {})
    
    lines = [
        f"**RSI Distribution**: Overbought (>70): {rsi.get('overbought', 0)} | Oversold (<30): {rsi.get('oversold', 0)} | Neutral: {rsi.get('neutral', 0)}",
        f"**Average RSI**: {rsi.get('avg_rsi', 50):.1f}",
        f"**Trend Distribution**: Uptrend: {trend.get('uptrend', 0)} | Downtrend: {trend.get('downtrend', 0)} | Sideways: {trend.get('sideways', 0)}",
    ]
    
    gainers = signals.get('top_gainers', [])
    if gainers:
        lines.append("\n**Top 5 Gainers (5D)**:")
        for g in gainers:
            lines.append(f"  - {g['symbol']}: +{g['price_change_5d']:.1f}%")
    
    return "\n".join(lines)


# ─── AI API CLIENTS ────────────────────────────────────────────────────────

def call_openai(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> Optional[str]:
    """Call OpenAI API."""
    try:
        import openai
        
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=MAX_TOKENS,
            temperature=0.7,
        )
        
        return response.choices[0].message.content
        
    except ImportError:
        log.error("openai package not installed. Run: pip install openai")
        return None
    except Exception as e:
        log.error("OpenAI API error: %s", e)
        return None


def call_anthropic(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> Optional[str]:
    """Call Anthropic Claude API."""
    try:
        import anthropic
        
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.content[0].text
        
    except ImportError:
        log.error("anthropic package not installed. Run: pip install anthropic")
        return None
    except Exception as e:
        log.error("Anthropic API error: %s", e)
        return None


def call_ai(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> Optional[str]:
    """Call AI API based on provider setting."""
    if AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
        log.info("Using Anthropic Claude API")
        return call_anthropic(prompt, system_prompt)
    elif OPENAI_API_KEY:
        log.info("Using OpenAI API")
        return call_openai(prompt, system_prompt)
    else:
        log.error("No API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        return None


# ─── ANALYSIS FUNCTIONS ────────────────────────────────────────────────────

def analyze_stocks(stocks_df: pd.DataFrame, sectors_df: pd.DataFrame) -> Optional[Dict]:
    """Run AI analysis on top stocks."""
    
    # Format data for prompt
    stock_data = format_stocks_for_prompt(stocks_df)
    sector_data = format_sectors_for_prompt(sectors_df)
    
    # Build prompt
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        n_stocks=len(stocks_df),
        stock_data=stock_data,
        sector_data=sector_data,
    )
    
    log.info("Calling AI for stock analysis...")
    response = call_ai(prompt)
    
    if not response:
        return None
    
    # Parse JSON response
    try:
        # Clean response (remove markdown code blocks if present)
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        analysis = json.loads(cleaned.strip())
        return analysis
        
    except json.JSONDecodeError as e:
        log.error("Failed to parse AI response as JSON: %s", e)
        log.debug("Raw response: %s", response[:500])
        return {"raw_response": response, "parse_error": str(e)}


def generate_daily_report(
    stocks_df: pd.DataFrame,
    sectors_df: pd.DataFrame,
    signals: Dict,
) -> Optional[str]:
    """Generate daily market report."""
    
    prompt = DAILY_REPORT_PROMPT.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        top_stocks=format_stocks_for_prompt(stocks_df.head(10)),
        sector_analysis=format_sectors_for_prompt(sectors_df),
        technical_signals=format_technical_for_prompt(signals),
    )
    
    log.info("Generating daily report...")
    report = call_ai(prompt, system_prompt="Bạn là chuyên gia phân tích chứng khoán. Viết báo cáo chuyên nghiệp, ngắn gọn.")
    
    return report


# ─── EXPORT FUNCTIONS ──────────────────────────────────────────────────────

def export_analysis(analysis: Dict, report: Optional[str] = None):
    """Export analysis to JSON file."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "ai_provider": AI_PROVIDER if (OPENAI_API_KEY or ANTHROPIC_API_KEY) else "none",
        "analysis": analysis,
    }
    
    if report:
        output["daily_report"] = report
    
    out_path = os.path.join(EXPORT_DIR, "ai_analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log.info("✅ Exported analysis → %s", out_path)
    
    # Also export markdown report if available
    if report:
        report_path = os.path.join(EXPORT_DIR, "daily_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Báo cáo thị trường - {datetime.now().strftime('%Y-%m-%d')}\n\n")
            f.write(report)
        log.info("✅ Exported report → %s", report_path)


def create_fallback_analysis(stocks_df: pd.DataFrame, sectors_df: pd.DataFrame) -> Dict:
    """Create rule-based analysis when AI is not available."""
    log.info("Creating fallback analysis (no AI API)")
    
    top_picks = []
    for _, row in stocks_df.head(5).iterrows():
        row = row.fillna(0)
        
        # Determine recommendation based on scores
        score = row['composite_score']
        if score >= 70:
            rec = "strong_buy"
        elif score >= 60:
            rec = "buy"
        elif score >= 50:
            rec = "hold"
        elif score >= 40:
            rec = "sell"
        else:
            rec = "strong_sell"
        
        # Identify risks
        risks = []
        if row['rsi14'] > 70:
            risks.append("RSI cao (>70) - có thể điều chỉnh ngắn hạn")
        if row['pe'] > 20:
            risks.append(f"PE cao ({row['pe']:.1f}x) - định giá đắt")
        if row['debt_equity'] > 1.5:
            risks.append(f"Nợ cao (D/E: {row['debt_equity']:.1f})")
        if row['foreign_net_7d'] < 0:
            risks.append("Khối ngoại đang bán ròng")
        
        # Identify catalysts
        catalysts = []
        if row['revenue_growth'] > 20:
            catalysts.append(f"Tăng trưởng doanh thu mạnh ({row['revenue_growth']:.1f}%)")
        if row['roe'] > 15:
            catalysts.append(f"ROE cao ({row['roe']:.1f}%)")
        if row['foreign_net_7d'] > 0:
            catalysts.append("Khối ngoại đang mua ròng")
        if row['trend_short'] == 1:
            catalysts.append("Xu hướng ngắn hạn tăng")
        
        top_picks.append({
            "symbol": row['symbol'],
            "name": row.get('organ_name', ''),
            "industry": row.get('industry_name', ''),
            "recommendation": rec,
            "composite_score": round(row['composite_score'], 1),
            "reasoning": {
                "fundamental": f"ROE {row['roe']:.1f}%, PE {row['pe']:.1f}x, Growth {row['revenue_growth']:.1f}%",
                "technical": f"RSI {row['rsi14']:.1f}, Trend {'↑' if row['trend_short']==1 else '↓' if row['trend_short']==-1 else '→'}",
                "smart_money": f"Foreign 7D: {row['foreign_net_7d']:.1f}B VND",
            },
            "catalysts": catalysts if catalysts else ["Đánh giá composite tốt"],
            "risks": risks if risks else ["Không có rủi ro đáng kể"],
        })
    
    # Sector analysis
    accumulating = []
    avoiding = []
    
    if not sectors_df.empty:
        for _, row in sectors_df.iterrows():
            name = row.get('industry_name', row.get('name', ''))
            foreign = row.get('total_foreign_7d', row.get('foreign_net_7d', 0)) or 0
            score = row.get('avg_composite', row.get('avg_composite_score', 0)) or 0
            
            if foreign > 0 and score > 55:
                accumulating.append(name)
            elif foreign < 0 and score < 45:
                avoiding.append(name)
    
    return {
        "market_overview": {
            "sentiment": "neutral",
            "summary": f"Phân tích dựa trên {len(stocks_df)} cổ phiếu hàng đầu theo composite score.",
            "key_themes": ["Dựa trên scoring engine", "Không có AI analysis"],
        },
        "top_picks": top_picks,
        "sector_rotation": {
            "accumulating": accumulating[:3],
            "avoiding": avoiding[:3],
            "rationale": "Dựa trên dòng tiền khối ngoại và composite score ngành",
        },
        "watchlist": [],
        "disclaimer": "Phân tích tự động bằng rule-based, không có AI. Chỉ mang tính tham khảo.",
    }


# ─── MAIN ──────────────────────────────────────────────────────────────────

def run():
    """Main function to run AI analysis."""
    log.info("=== AI Analyst Module ===")
    
    # Load data
    conn = create_connection()
    
    stocks_df = load_top_stocks(conn, limit=TOP_N_STOCKS)
    sectors_df = load_sector_data(conn)
    signals = load_technical_signals(conn)
    
    conn.close()
    
    if stocks_df.empty:
        log.error("No stock data available. Run scoring_engine.py first.")
        return
    
    log.info("Loaded %d stocks, %d sectors", len(stocks_df), len(sectors_df))
    
    # Run analysis
    if OPENAI_API_KEY or ANTHROPIC_API_KEY:
        analysis = analyze_stocks(stocks_df, sectors_df)
        report = generate_daily_report(stocks_df, sectors_df, signals)
    else:
        log.warning("No AI API key configured. Using fallback analysis.")
        analysis = create_fallback_analysis(stocks_df, sectors_df)
        report = None
    
    if analysis is None:
        log.warning("AI analysis failed. Using fallback.")
        analysis = create_fallback_analysis(stocks_df, sectors_df)
    
    # Export
    export_analysis(analysis, report)
    
    # Summary
    if "top_picks" in analysis:
        log.info("Top picks:")
        for pick in analysis["top_picks"][:3]:
            log.info("  %s (%s): %s", 
                    pick.get("symbol"),
                    pick.get("recommendation", "N/A"),
                    pick.get("reasoning", {}).get("fundamental", "")[:50])
    
    log.info("✅ AI Analyst completed")


if __name__ == "__main__":
    run()
