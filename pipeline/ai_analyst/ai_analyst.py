"""
ai_analyst.py — AI-Powered Stock Analysis Module (v3)

Đưa toàn bộ data vào AI để phân tích:
  - Screener: composite/sub-scores, technicals, fundamentals, foreign flow, FVG
  - ICT Signals: ict_score, alpha_score, setup_quality, signal_breakdown,
                 structure, confluences (FVG/OB/sweep/wyckoff), top_signals
  - Sector context: ngành đang acc/dist, RS vs sector, top stocks
  - Market regime: BULL/BEAR/TRANSITION, bull_weight, breadth, foreign net

Output: ai_analysis.json với cấu trúc phù hợp frontend.
Chạy sau workflow 2+3 (collect + process).
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, List, Any

# ─── CONFIG ────────────────────────────────────────────────────────────────

EXPORT_DIR     = os.getenv("EXPORT_DIR",    "data/exports")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TOP_N_STOCKS   = int(os.getenv("TOP_N_STOCKS", "10"))   # chỉ phân tích top 10
MAX_TOKENS     = int(os.getenv("MAX_TOKENS",   "2000"))

# ─── LOGGING ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── PROMPTS ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích chứng khoán Việt Nam với 20 năm kinh nghiệm, \
chuyên về phân tích kỹ thuật ICT (Inner Circle Trader), dòng tiền tổ chức, và cơ bản.

Nhiệm vụ: Phân tích cổ phiếu được cung cấp và đưa ra nhận định đầu tư toàn diện.

Nguyên tắc:
- Ngắn gọn, súc tích, đi thẳng trọng tâm
- Ưu tiên tín hiệu ICT (structure, FVG, OB, sweep) kết hợp dòng tiền
- Cân nhắc market regime (BULL/BEAR) — trong BEAR market, chỉ khuyến nghị BUY/STRONG_BUY khi có setup rõ ràng
- Cảnh báo rủi ro cụ thể
- KHÔNG đưa lời khuyên tài chính cụ thể

Format output: JSON chính xác theo cấu trúc yêu cầu, không có text ngoài JSON.\
"""

ANALYSIS_PROMPT_TEMPLATE = """\
Phân tích cổ phiếu {symbol} với toàn bộ dữ liệu sau:

## MARKET CONTEXT
- Regime: {regime} (bull_weight={bull_weight}%, strength={regime_strength}%)
- VN-Index: {vnindex} | 1D={vnindex_1d}% | 5D={vnindex_5d}% | 20D={vnindex_20d}%
- Breadth: Advance {breadth_advance}% | Bear sectors {bear_sectors}/25
- Foreign net 7D tổng thị trường: {market_foreign_net}B VND

## THÔNG TIN CỔ PHIẾU
- Symbol: {symbol} | Tên: {name}
- Ngành: {industry} | Exchange: {exchange} | Tier: {tier}
- Rank: #{rank} / {total_symbols} (top {rank_pct}%)

## ĐIỂM SỐ TỔNG HỢP
- Composite Score: {composite_score}/100
- Fundamental:    {fundamental_score}/100
- Smart Money:    {smart_money_score}/100
- Momentum:       {momentum_score}/100
- Technical:      {technical_score}/100

## ICT ANALYSIS
- ICT Score: {ict_score}/100 | Alpha Score: {alpha_score}/100
- Setup Quality: {setup_quality} | Confluences: {ict_confluence} signals
- Actionable: {actionable}
- Market Structure: {structure}
  + BOS Bull={bos_bull} | BOS Bear={bos_bear} | CHoCH Bull={choch_bull} | CHoCH Bear={choch_bear}
  + Last S/H: {last_sh} / Last S/L: {last_sl}
  + Equal Highs: {eq_high_count} | Equal Lows: {eq_low_count}

ICT Confluences:
  + Fair Value Gap Bull: {fvg_bull} (size={fvg_bull_size}%, filled={fvg_bull_fill}%, age={fvg_bull_age}d)
  + Order Block Bull: {ob_bull} | Price at OB: {ob_price_at} | Mitigated: {ob_mitigated}
  + Liquidity Sweep Bull: {sweep_bull} | Stop Hunt: {stop_hunt_bull}
  + Wyckoff Spring: {wyckoff_spring} | Smart Money: {smart_money}
  + Breakout Imminent: {breakout_imminent}

Signal Breakdown (0-100):
{signal_breakdown_text}

Top ICT Signals:
{top_signals_text}

## TECHNICALS
- RSI(14): {rsi14} | ADX(14): {adx14}
- +DI={plus_di} / -DI={minus_di} | DI Spread: {di_spread}
- Trend Short: {trend_short} | Trend Strength: {trend_strength}%
- BB Width: {bb_width}% | ATR(14): {atr_pct}%
- Vol Ratio vs avg: {vol_ratio}x | Vol Trend: {vol_trend}
- MACD Hist: {macd_hist}
- % from MA20: {pct_from_ma20}% | % from MA50: {pct_from_ma50}%
- Price 1D: {price_1d}% | 5D: {price_5d}% | 20D: {price_20d}%

## VOLUME & FLOW (ICT)
- Accumulation Score: {accumulation_score}/100
- Distribution Score: {distribution_score}/100
- Vol Spike: {vol_spike}x | Flow Direction: {flow_direction} | Flow Trend: {flow_trend}
- Buy Pressure: {buy_pressure_pct}%
- Inst Flow Score: {inst_flow_score}/100

## FUNDAMENTALS
- ROE: {roe}% | ROA: {roa}%
- P/E: {pe}x | Net Margin: {net_margin}%
- Revenue Growth: {revenue_growth}% | Debt/Equity: {debt_equity}

## FOREIGN FLOW
- 7D: {foreign_net_7d}B VND | 30D: {foreign_net_30d}B VND

## SECTOR: {industry}
- Avg Composite: {sector_avg_composite}/100 | Momentum 5D: {sector_momentum}%
- Foreign 7D tổng ngành: {sector_foreign_7d}B VND
- Status: {sector_status} | Money Flow Rank: #{sector_money_rank}
- Top stocks ngành: {sector_top_stocks}

## YÊU CẦU OUTPUT

Trả về JSON với cấu trúc sau (không có text ngoài JSON):
{{
  "recommendation": "STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL",
  "summary": "Tóm tắt 2-3 câu: setup hiện tại + lý do chính",
  "highlights": [
    {{"text": "Điểm tích cực cụ thể 1", "type": "positive"}},
    {{"text": "Điểm tích cực cụ thể 2", "type": "positive"}}
  ],
  "risks": [
    {{"text": "Rủi ro cụ thể 1", "type": "negative"}},
    {{"text": "Cảnh báo 1", "type": "warning"}}
  ],
  "fundamental_view": "Nhận định cơ bản 1 câu",
  "technical_view": "Nhận định kỹ thuật ICT 1 câu (đề cập structure/FVG/OB nếu có)",
  "flow_view": "Nhận định dòng tiền 1 câu (foreign + inst flow)"
}}
"""

# ─── DATA LOADERS ──────────────────────────────────────────────────────────

def load_screener() -> Dict[str, Dict]:
    path = os.path.join(EXPORT_DIR, "screener.json")
    if not os.path.exists(path):
        log.warning("screener.json not found")
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {s["symbol"]: s for s in data.get("screener", [])}


def load_ict_signals():
    path = os.path.join(EXPORT_DIR, "ict_signals.json")
    if not os.path.exists(path):
        log.warning("ict_signals.json not found")
        return {}, {}, {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    sig_map = {s["symbol"]: s for s in data.get("signals", [])}
    return sig_map, data.get("regime", {}), data.get("market_stats", {})


def load_sectors() -> Dict[str, Dict]:
    path = os.path.join(EXPORT_DIR, "sectors.json")
    if not os.path.exists(path):
        log.warning("sectors.json not found")
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for s in data.get("sectors", []):
        name = s.get("name") or s.get("industry_name", "")
        if name:
            result[name] = s
    return result


def get_top_symbols(screener: Dict[str, Dict], ict_map: Dict[str, Dict], limit: int) -> List[str]:
    candidates = []
    for sym, s in screener.items():
        ict = ict_map.get(sym, {})
        candidates.append({
            "symbol":          sym,
            "composite_score": s.get("composite_score") or 0,
            "alpha_score":     ict.get("alpha_score") or 0,
            "actionable":      ict.get("actionable", False),
        })
    candidates.sort(
        key=lambda x: (x["actionable"], x["composite_score"], x["alpha_score"]),
        reverse=True,
    )
    return [c["symbol"] for c in candidates[:limit]]


# ─── PROMPT BUILDER ────────────────────────────────────────────────────────

def _fmt(v, decimals=2, default="N/A") -> str:
    if v is None:
        return default
    try:
        return f"{float(v):.{decimals}f}"
    except Exception:
        return str(v)


def _bool(v) -> str:
    if v is None:
        return "N/A"
    return "YES" if bool(v) else "no"


def build_prompt(symbol, screener, ict, sector, regime, market_stats, total_symbols) -> str:
    sb = ict.get("signal_breakdown") or {}
    sb_lines = "\n".join(
        f"  + {k.replace('_', ' ').title()}: {_fmt(v, 0)}/100"
        for k, v in sb.items()
    ) if sb else "  (N/A)"

    ts = ict.get("top_signals") or []
    ts_text = "\n".join(f"  + {s}" for s in ts) if ts else "  (none)"

    s_foreign = float(sector.get("foreign_net_7d") or 0)
    s_comp    = float(sector.get("avg_composite_score") or 50)
    if s_foreign > 20 and s_comp > 55:
        sector_status = "ACCUMULATING"
    elif s_foreign < -20 and s_comp < 50:
        sector_status = "DISTRIBUTING"
    else:
        sector_status = "NEUTRAL"

    ts_val = screener.get("trend_short")
    trend_short_label = "Up" if ts_val == 1 else "Down" if ts_val == -1 else "Sideways"

    rank = screener.get("rank") or 0
    rank_pct = screener.get("rank_pct") or (
        round((1 - rank / max(total_symbols, 1)) * 100, 1) if rank else 0
    )

    return ANALYSIS_PROMPT_TEMPLATE.format(
        regime=regime.get("regime", "UNKNOWN"),
        bull_weight=_fmt((regime.get("bull_weight") or 0) * 100, 0),
        regime_strength=_fmt(regime.get("regime_strength"), 0),
        vnindex=_fmt(regime.get("vnindex"), 2),
        vnindex_1d=_fmt(regime.get("vnindex_change_1d"), 2),
        vnindex_5d=_fmt(regime.get("vnindex_change_5d"), 2),
        vnindex_20d=_fmt(regime.get("vnindex_change_20d"), 2),
        breadth_advance=_fmt(regime.get("breadth_advance_pct"), 1),
        bear_sectors=regime.get("bear_sectors", "N/A"),
        market_foreign_net=_fmt(regime.get("foreign_net_total_bn"), 1),
        symbol=symbol,
        name=screener.get("name", symbol),
        industry=screener.get("industry", "N/A"),
        exchange=screener.get("exchange", "N/A"),
        tier=screener.get("tier", "N/A"),
        rank=rank,
        total_symbols=total_symbols,
        rank_pct=_fmt(rank_pct, 1),
        composite_score=_fmt(screener.get("composite_score"), 1),
        fundamental_score=_fmt(screener.get("fundamental_score"), 1),
        smart_money_score=_fmt(screener.get("smart_money_score"), 1),
        momentum_score=_fmt(screener.get("momentum_score"), 1),
        technical_score=_fmt(screener.get("technical_score"), 1),
        ict_score=_fmt(ict.get("ict_score"), 1),
        alpha_score=_fmt(ict.get("alpha_score"), 1),
        setup_quality=ict.get("setup_quality", "N/A"),
        ict_confluence=ict.get("ict_confluence", 0),
        actionable=_bool(ict.get("actionable")),
        structure=ict.get("structure", "N/A"),
        bos_bull=_bool(ict.get("bos_bull")),
        bos_bear=_bool(ict.get("bos_bear")),
        choch_bull=_bool(ict.get("choch_bull")),
        choch_bear=_bool(ict.get("choch_bear")),
        last_sh=_fmt(ict.get("last_sh"), 1),
        last_sl=_fmt(ict.get("last_sl"), 1),
        eq_high_count=ict.get("eq_high_count", 0),
        eq_low_count=ict.get("eq_low_count", 0),
        fvg_bull=_bool(ict.get("fvg_bull")),
        fvg_bull_size=_fmt(screener.get("fvg_bull_size"), 2),
        fvg_bull_fill=_fmt(screener.get("fvg_bull_fill"), 1),
        fvg_bull_age=screener.get("fvg_bull_age", "N/A"),
        ob_bull=_bool(ict.get("ob_bull")),
        ob_price_at=_bool(ict.get("ob_price_at")),
        ob_mitigated=_bool(ict.get("ob_mitigated")),
        sweep_bull=_bool(ict.get("sweep_bull")),
        stop_hunt_bull=_bool(ict.get("stop_hunt_bull")),
        wyckoff_spring=_bool(ict.get("wyckoff_spring")),
        smart_money=_bool(ict.get("smart_money")),
        breakout_imminent=_bool(ict.get("breakout_imminent")),
        signal_breakdown_text=sb_lines,
        top_signals_text=ts_text,
        rsi14=_fmt(screener.get("rsi14"), 1),
        adx14=_fmt(screener.get("adx14"), 1),
        plus_di=_fmt(screener.get("plus_di14"), 1),
        minus_di=_fmt(screener.get("minus_di14"), 1),
        di_spread=_fmt(screener.get("di_spread"), 1),
        trend_short=trend_short_label,
        trend_strength=_fmt(screener.get("trend_strength"), 1),
        bb_width=_fmt(screener.get("bb_width"), 1),
        atr_pct=_fmt(screener.get("atr_pct"), 2),
        vol_ratio=_fmt(screener.get("vol_ratio"), 2),
        vol_trend=ict.get("vol_trend", "N/A"),
        macd_hist=_fmt(screener.get("macd_hist"), 4),
        pct_from_ma20=_fmt(screener.get("pct_from_ma20"), 1),
        pct_from_ma50=_fmt(screener.get("pct_from_ma50"), 1),
        price_1d=_fmt(screener.get("price_change_1d"), 2),
        price_5d=_fmt(screener.get("price_change_5d"), 2),
        price_20d=_fmt(screener.get("price_change_20d"), 2),
        accumulation_score=_fmt(ict.get("accumulation_score"), 1),
        distribution_score=_fmt(ict.get("distribution_score"), 1),
        vol_spike=_fmt(ict.get("vol_spike"), 2),
        flow_direction=ict.get("flow_direction", "N/A"),
        flow_trend=ict.get("flow_trend", "N/A"),
        buy_pressure_pct=_fmt(ict.get("buy_pressure_pct"), 1),
        inst_flow_score=_fmt(ict.get("inst_flow_score"), 1),
        roe=_fmt(screener.get("roe"), 2),
        roa=_fmt(screener.get("roa"), 2),
        pe=_fmt(screener.get("pe"), 1),
        net_margin=_fmt(screener.get("net_margin"), 2),
        revenue_growth=_fmt(screener.get("revenue_growth"), 2),
        debt_equity=_fmt(screener.get("debt_equity"), 2),
        foreign_net_7d=_fmt(screener.get("foreign_net_7d"), 1),
        foreign_net_30d=_fmt(screener.get("foreign_net_30d"), 1),
        sector_avg_composite=_fmt(sector.get("avg_composite_score"), 1),
        sector_momentum=_fmt(sector.get("avg_price_5d"), 2),
        sector_foreign_7d=_fmt(sector.get("foreign_net_7d"), 1),
        sector_status=sector_status,
        sector_money_rank=sector.get("money_flow_rank", "N/A"),
        sector_top_stocks=", ".join(sector.get("top_stocks") or [])[:80] or "N/A",
    )


# ─── AI CALLER ─────────────────────────────────────────────────────────────

def call_ai(prompt: str) -> Optional[str]:
    """Gọi OpenAI GPT-4o. Log warning rõ nếu không chạy được."""

    if not OPENAI_API_KEY:
        log.warning("⚠️  OPENAI_API_KEY chưa được cấu hình — bỏ qua AI, dùng rule-based")
        return None

    try:
        import openai
    except ImportError:
        log.warning("⚠️  Package 'openai' chưa được cài — chạy: pip install openai")
        return None

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    except Exception as e:
        log.warning("⚠️  OpenAI API lỗi: %s — fallback sang rule-based", e)
        return None


def parse_ai_response(response: str) -> Optional[Dict]:
    try:
        cleaned = response.strip()
        for fence in ("```json", "```"):
            if cleaned.startswith(fence):
                cleaned = cleaned[len(fence):]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())
    except json.JSONDecodeError as e:
        log.warning("Parse failed: %s | %s...", e, response[:100])
        return None


# ─── RULE-BASED FALLBACK ───────────────────────────────────────────────────

def generate_rule_based(symbol, screener, ict, sector, regime) -> Dict:
    def g(d, key, default=0):
        v = d.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except Exception:
            return default

    score      = g(screener, "composite_score", 50)
    ict_score  = g(ict,      "ict_score", 50)
    alpha      = g(ict,      "alpha_score", 50)
    f_score    = g(screener, "fundamental_score", 50)
    s_score    = g(screener, "smart_money_score", 50)
    m_score    = g(screener, "momentum_score", 50)
    t_score    = g(screener, "technical_score", 50)
    rsi        = g(screener, "rsi14", 50)
    adx        = g(screener, "adx14", 20)
    nn7d       = g(screener, "foreign_net_7d", 0)
    c20d       = g(screener, "price_change_20d", 0)
    ma20_pct   = g(screener, "pct_from_ma20", 0)
    de         = g(screener, "debt_equity", 0)
    roe        = g(screener, "roe", 0)
    pe         = g(screener, "pe", 0)
    rev_growth = g(screener, "revenue_growth", 0)

    bull_weight = float(regime.get("bull_weight") or 0.5)
    is_bear     = bull_weight <= 0.35
    structure   = ict.get("structure", "NEUTRAL")
    actionable  = bool(ict.get("actionable"))

    # ── Recommendation ──
    eff = score * (0.7 if is_bear else 1.0)
    if   eff >= 75 and not is_bear:                          rec = "STRONG_BUY"
    elif eff >= 68 and structure == "BULLISH" and actionable: rec = "BUY"
    elif eff >= 58:                                           rec = "HOLD"
    elif eff >= 45:                                           rec = "SELL"
    else:                                                     rec = "STRONG_SELL"

    highlights, risks = [], []

    # ICT
    if structure == "BULLISH":
        highlights.append({"text": f"Market structure BULLISH (ICT score {ict_score:.0f})", "type": "positive"})
    elif structure == "BEARISH":
        risks.append({"text": "Market structure BEARISH — LH/LL pattern", "type": "negative"})
    if ict.get("fvg_bull"):
        highlights.append({"text": f"FVG Bull active ({g(screener,'fvg_bull_size',0):.1f}%) — demand zone intact", "type": "positive"})
    if ict.get("sweep_bull") or ict.get("stop_hunt_bull"):
        highlights.append({"text": "Liquidity sweep bull xong — tiềm năng reversal", "type": "positive"})
    if ict.get("wyckoff_spring"):
        highlights.append({"text": "Wyckoff Spring — tín hiệu tích lũy tổ chức", "type": "positive"})
    if ict.get("breakout_imminent"):
        highlights.append({"text": "Breakout imminent — sắp bứt phá kháng cự", "type": "positive"})

    # Technicals
    if adx >= 30 and t_score >= 65:
        highlights.append({"text": f"ADX={adx:.0f} — trending market mạnh", "type": "positive"})
    if rsi > 75:
        risks.append({"text": f"RSI={rsi:.0f} — quá mua, cẩn thận pullback", "type": "warning"})
    if ma20_pct > 20:
        risks.append({"text": f"Giá cách MA20 +{ma20_pct:.0f}% — extended, rủi ro điều chỉnh", "type": "warning"})

    # Momentum
    if c20d > 15:
        highlights.append({"text": f"Tăng {c20d:.1f}% / 20 phiên — uptrend mạnh", "type": "positive"})
    elif c20d < -15:
        risks.append({"text": f"Giảm {abs(c20d):.1f}% / 20 phiên — downtrend", "type": "negative"})

    # Foreign
    if nn7d > 50:
        highlights.append({"text": f"Khối ngoại mua ròng +{nn7d:.0f}B (7D)", "type": "positive"})
    elif nn7d < -50:
        risks.append({"text": f"Khối ngoại bán ròng {nn7d:.0f}B (7D)", "type": "negative"})

    # Sector
    s_foreign = float(sector.get("foreign_net_7d") or 0)
    s_comp    = float(sector.get("avg_composite_score") or 50)
    if s_foreign > 20 and s_comp > 55:
        highlights.append({"text": f"Ngành {screener.get('industry','')} đang được tích lũy", "type": "positive"})
    elif s_foreign < -20:
        risks.append({"text": f"Ngành {screener.get('industry','')} đang bị phân phối", "type": "negative"})

    # Fundamentals
    if f_score >= 70:
        fundamental_view = f"Cơ bản vững (score={f_score:.0f}" + (f", ROE={roe:.1f}%" if roe > 10 else "") + ")"
    elif f_score >= 50:
        fundamental_view = f"Cơ bản ổn định (score={f_score:.0f})"
    else:
        fundamental_view = f"Cơ bản yếu (score={f_score:.0f}" + (f", D/E={de:.1f}" if de > 1.5 else "") + ")"
        risks.append({"text": f"Fundamental Score {f_score:.0f} — cần cải thiện", "type": "negative"})

    # Bear warning
    if is_bear:
        risks.append({"text": f"BEAR market (bull={bull_weight*100:.0f}%) — risk management chặt", "type": "warning"})

    technical_view = (
        f"Structure {structure}, ICT {ict_score:.0f}/alpha {alpha:.0f}, ADX={adx:.0f}"
        + (" + FVG bull" if ict.get("fvg_bull") else "")
        + (" + sweep" if ict.get("sweep_bull") else "")
    )
    flow_view = (
        f"NN 7D: {nn7d:+.0f}B, flow {ict.get('flow_direction','neutral')}, "
        f"inst_flow_score={g(ict,'inst_flow_score',50):.0f}"
    )
    summary = (
        f"{symbol} score={score:.1f} (rank #{screener.get('rank','?')}/{len(screener)}), "
        f"structure {structure}, ICT {ict_score:.0f}. "
        f"Regime {regime.get('regime','?')} → {rec.replace('_',' ')}."
    )

    return {
        "symbol":           symbol,
        "recommendation":   rec,
        "summary":          summary,
        "highlights":       highlights[:5],
        "risks":            risks[:4],
        "fundamental_view": fundamental_view,
        "technical_view":   technical_view,
        "flow_view":        flow_view,
    }


# ─── EXPORT ────────────────────────────────────────────────────────────────

def export_analysis(analyses: Dict[str, Dict], model: str) -> None:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    rec_counts: Dict[str, int] = {}
    for a in analyses.values():
        r = a.get("recommendation", "HOLD")
        rec_counts[r] = rec_counts.get(r, 0) + 1

    output = {
        "generated_at":   datetime.utcnow().isoformat() + "Z",
        "model":          model,
        "total_analyzed": len(analyses),
        "summary": {
            "STRONG_BUY":  rec_counts.get("STRONG_BUY", 0),
            "BUY":         rec_counts.get("BUY", 0),
            "HOLD":        rec_counts.get("HOLD", 0),
            "SELL":        rec_counts.get("SELL", 0),
            "STRONG_SELL": rec_counts.get("STRONG_SELL", 0),
        },
        "analyses": analyses,
    }

    out_path = os.path.join(EXPORT_DIR, "ai_analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info("✅ Exported %d analyses → %s (model=%s)", len(analyses), out_path, model)
    log.info("   Distribution: %s", rec_counts)


# ─── MAIN ──────────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=" * 60)
    log.info("🤖 AI ANALYST v3 — Full Data Context")
    log.info("=" * 60)

    screener_map             = load_screener()
    ict_map, regime, mstats  = load_ict_signals()
    sector_map               = load_sectors()

    if not screener_map:
        log.error("No screener data. Run workflows 2+3 first.")
        return

    total = len(screener_map)
    log.info("📊 Screener=%d | ICT=%d | Sectors=%d | Regime=%s (bull=%.0f%%)",
             total, len(ict_map), len(sector_map),
             regime.get("regime","?"), (regime.get("bull_weight") or 0) * 100)

    top_syms  = get_top_symbols(screener_map, ict_map, TOP_N_STOCKS)
    use_ai    = bool(OPENAI_API_KEY)
    model_str = "gpt-4o" if use_ai else "rule-based-v3"

    if use_ai:
        log.info("🤖 OpenAI GPT-4o | phân tích %d stocks", len(top_syms))
    else:
        log.warning("⚠️  Không có OPENAI_API_KEY — toàn bộ %d stocks dùng rule-based", len(top_syms))

    analyses: Dict[str, Dict] = {}
    ai_ok = rb_ok = 0

    for i, sym in enumerate(top_syms):
        s  = screener_map.get(sym, {})
        ic = ict_map.get(sym, {})
        sc = sector_map.get(s.get("industry", ""), {})

        result = None

        if use_ai:
            try:
                prompt = build_prompt(sym, s, ic, sc, regime, mstats, total)
                raw = call_ai(prompt)
                if raw:
                    parsed = parse_ai_response(raw)
                    if parsed:
                        parsed["symbol"] = sym
                        result = parsed
                        ai_ok += 1
                    else:
                        log.warning("⚠️  %s: parse JSON thất bại — fallback rule-based", sym)
                else:
                    log.warning("⚠️  %s: AI không trả về kết quả — fallback rule-based", sym)
            except Exception as e:
                log.warning("⚠️  %s: AI exception [%s] — fallback rule-based", sym, e)

        if result is None:
            result = generate_rule_based(sym, s, ic, sc, regime)
            rb_ok += 1

        analyses[sym] = result

        if (i + 1) % 10 == 0:
            log.info("   [%d/%d] ai=%d rule=%d", i + 1, len(top_syms), ai_ok, rb_ok)

    export_analysis(analyses, model_str)

    log.info("")
    log.info("📋 Top 5:")
    for sym in top_syms[:5]:
        log.info("   %s → %s", sym, analyses[sym].get("recommendation", "?"))
    log.info("✅ Done — AI=%d Rule-based=%d", ai_ok, rb_ok)


if __name__ == "__main__":
    run()
