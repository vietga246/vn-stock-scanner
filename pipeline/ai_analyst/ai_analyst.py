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
Bạn là nhà phân tích nghiên cứu vốn cổ phần cấp cao, chuyên về thị trường chứng khoán Việt Nam với 20 năm kinh nghiệm. Bạn thành thạo phân tích kỹ thuật ICT (Inner Circle Trader), dòng tiền tổ chức, phân tích cơ bản và định giá.

NHIỆM VỤ: Biên soạn báo cáo phân tích đầu tư toàn diện, khách quan, dựa trên dữ liệu được cung cấp.

QUY TẮC QUAN TRỌNG VỀ RECOMMENDATION:
Phải phân biệt rõ ràng 5 mức — TUYỆT ĐỐI KHÔNG để tất cả cổ phiếu cùng mức HOLD:

  STRONG_BUY: Composite ≥75 + structure BULLISH + actionable=YES + regime BULL/TRANSITION
  BUY:        Composite ≥65 + structure BULLISH + setup rõ ràng, ngay cả trong BEAR nếu RS mạnh
  HOLD:       Composite 50-65 HOẶC setup chưa đủ điều kiện mua/bán rõ ràng
  SELL:       Composite <50 HOẶC structure BEARISH + distribution + foreign bán ròng mạnh
  STRONG_SELL: Composite <40 + structure BEARISH + BOS bear + regime BEAR mạnh

ĐIỀU CHỈNH THEO BEAR MARKET (bull_weight ≤ 35%):
  - Nâng tiêu chuẩn BUY: cần thêm FVG bull HOẶC OB bull HOẶC wyckoff_spring
  - Cổ phiếu composite ≥70 nhưng structure BEARISH → HOLD, không phải BUY
  - Cổ phiếu structure BEARISH + distribution_score >60 → SELL dù composite cao
  - Ưu tiên RS vs sector: nếu cổ phiếu outperform ngành ≥10% trong BEAR → vẫn có thể BUY

ĐỌC KỸTRƯỚC KHI QUYẾT ĐỊNH:
  - signal_breakdown.regime phản ánh điểm của market regime (thấp = BEAR)
  - distribution_score > accumulation_score → áp lực bán ròng
  - flow_direction=outflow + foreign bán ròng → KHÔNG BUY dù score cao
  - breakout_imminent=YES → tăng 1 bậc recommendation nếu các yếu tố khác ủng hộ

Format output: JSON chính xác theo cấu trúc yêu cầu, không có text ngoài JSON.\
"""

ANALYSIS_PROMPT_TEMPLATE = """\
Phân tích cổ phiếu {symbol} với toàn bộ dữ liệu sau:

════════════════════════════════════════
MARKET CONTEXT — ĐỌC KỸ TRƯỚC KHI PHÂN TÍCH
════════════════════════════════════════
Regime: {regime} | bull_weight={bull_weight}% | strength={regime_strength}%
VN-Index: {vnindex} | 1D={vnindex_1d}% | 5D={vnindex_5d}% | 20D={vnindex_20d}%
Advance/Decline: {breadth_advance}% tăng | {bear_sectors}/25 ngành giảm
Foreign net 7D toàn thị trường: {market_foreign_net}B VND

⚠ HƯỚNG DẪN REGIME:
- Nếu BEAR (bull_weight≤35%): Chỉ BUY khi có FVG/OB/sweep rõ ràng + RS ngành tốt
- Nếu TRANSITION (35-60%): Cân nhắc từng case, ưu tiên actionable=YES
- Nếu BULL (>60%): Tiêu chuẩn bình thường

════════════════════════════════════════
1. THÔNG TIN & ĐIỂM SỐ
════════════════════════════════════════
Symbol: {symbol} | Tên: {name}
Ngành: {industry} | Exchange: {exchange} | Tier: {tier}
Rank: #{rank} / {total_symbols} (top {rank_pct}%)

Composite Score: {composite_score}/100
  ├ Fundamental:  {fundamental_score}/100
  ├ Smart Money:  {smart_money_score}/100
  ├ Momentum:     {momentum_score}/100
  └ Technical:    {technical_score}/100

════════════════════════════════════════
2. PHÂN TÍCH ICT — SIGNAL CHẤT LƯỢNG NHẤT
════════════════════════════════════════
ICT Score: {ict_score}/100 | Alpha Score: {alpha_score}/100
Setup Quality: {setup_quality} | Confluences: {ict_confluence} | Actionable: {actionable}

Market Structure: {structure}
  BOS Bull={bos_bull} | BOS Bear={bos_bear} | CHoCH Bull={choch_bull} | CHoCH Bear={choch_bear}
  Last S/H: {last_sh} | Last S/L: {last_sl}
  Equal Highs: {eq_high_count} | Equal Lows: {eq_low_count}

Confluences:
  FVG Bull: {fvg_bull} (size={fvg_bull_size}%, filled={fvg_bull_fill}%, age={fvg_bull_age}d)
  Order Block Bull: {ob_bull} | Giá tại OB: {ob_price_at} | Đã mitigate: {ob_mitigated}
  Liq Sweep Bull: {sweep_bull} | Stop Hunt: {stop_hunt_bull}
  Wyckoff Spring: {wyckoff_spring} | Smart Money: {smart_money}
  Breakout Imminent: {breakout_imminent}

Signal Breakdown (0-100):
{signal_breakdown_text}

Top Signals:
{top_signals_text}

════════════════════════════════════════
3. KỸ THUẬT
════════════════════════════════════════
RSI(14): {rsi14} | ADX: {adx14} (+DI={plus_di} / -DI={minus_di} / Spread={di_spread})
Trend: {trend_short} | Strength: {trend_strength}%
BB Width: {bb_width}% | ATR: {atr_pct}% | MACD Hist: {macd_hist}
Vol Ratio: {vol_ratio}x | Vol Trend: {vol_trend}
% from MA20: {pct_from_ma20}% | % from MA50: {pct_from_ma50}%
Price: 1D={price_1d}% | 5D={price_5d}% | 20D={price_20d}%

════════════════════════════════════════
4. DÒNG TIỀN & TÍCH LŨY
════════════════════════════════════════
Accumulation Score: {accumulation_score}/100
Distribution Score: {distribution_score}/100
→ Nếu distribution > accumulation: áp lực bán ròng — cẩn thận BUY
Vol Spike: {vol_spike}x | Flow: {flow_direction} | Flow Trend: {flow_trend}
Buy Pressure: {buy_pressure_pct}% | Inst Flow Score: {inst_flow_score}/100
Foreign 7D: {foreign_net_7d}B | 30D: {foreign_net_30d}B VND

════════════════════════════════════════
5. CƠ BẢN
════════════════════════════════════════
ROE: {roe}% | ROA: {roa}% | P/E: {pe}x
Net Margin: {net_margin}% | Rev Growth: {revenue_growth}% | D/E: {debt_equity}

════════════════════════════════════════
6. NGÀNH: {industry}
════════════════════════════════════════
Avg Composite: {sector_avg_composite}/100 | Momentum 5D: {sector_momentum}%
Foreign 7D ngành: {sector_foreign_7d}B | Status: {sector_status} | Money Flow Rank: #{sector_money_rank}
Top stocks: {sector_top_stocks}

════════════════════════════════════════
YÊU CẦU OUTPUT — BÁO CÁO ĐẦU TƯ
════════════════════════════════════════
Trả về JSON sau (KHÔNG có text ngoài JSON):
{{
  "recommendation": "STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL",

  "executive_summary": "2-3 câu tóm tắt luận điểm đầu tư: setup + lý do chính + verdict",

  "highlights": [
    {{"text": "Điểm tích cực cụ thể với số liệu", "type": "positive"}},
    {{"text": "Điểm tích cực 2", "type": "positive"}},
    {{"text": "Điểm tích cực 3", "type": "positive"}}
  ],
  "risks": [
    {{"text": "Rủi ro cụ thể với số liệu", "type": "negative"}},
    {{"text": "Cảnh báo cụ thể", "type": "warning"}},
    {{"text": "Rủi ro hệ thống nếu có", "type": "warning"}}
  ],

  "sections": {{
    "ict_analysis": "Phân tích ICT 2 câu: structure + confluences + actionable hay không",
    "technical_view": "Kỹ thuật 1 câu: ADX/RSI/trend + vị trí giá vs MA",
    "flow_analysis": "Dòng tiền 1 câu: acc vs dist score + foreign + inst flow",
    "fundamental_view": "Cơ bản 1 câu: ROE/PE/growth + điểm mạnh/yếu",
    "sector_context": "Ngành 1 câu: status + RS + money flow rank",
    "regime_impact": "Tác động regime 1 câu: BEAR/BULL ảnh hưởng thế nào đến setup này"
  }},

  "price_levels": {{
    "support": "Vùng hỗ trợ dựa trên ICT (last_sl hoặc OB/FVG nếu có)",
    "resistance": "Vùng kháng cự dựa trên ICT (last_sh hoặc equal highs nếu có)",
    "stop_loss_note": "Gợi ý stop loss ngắn gọn (dưới SL gần nhất hoặc OB)"
  }}
}}
"""

# ─── REPORT PROMPT ─────────────────────────────────────────────────────────

REPORT_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích đầu tư chứng khoán Việt Nam với 20 năm kinh nghiệm.
Viết báo cáo phân tích đầu tư TOÀN DIỆN bằng tiếng Việt, có chiều sâu thực sự.
Dùng dữ liệu cụ thể để lập luận, không viết chung chung.
Output: văn bản Markdown thuần túy (không phải JSON)."""

REPORT_PROMPT_TEMPLATE = """Dựa trên dữ liệu đầy đủ dưới đây, hãy viết báo cáo phân tích đầu tư hoàn chỉnh cho cổ phiếu {symbol}:

PHÂN TÍCH AI (sơ bộ đã có):
  Khuyến nghị: {recommendation}
  Tóm tắt: {executive_summary}
  ICT: {ict_analysis}
  Kỹ thuật: {technical_view}
  Dòng tiền: {flow_analysis}
  Cơ bản: {fundamental_view}
  Ngành: {sector_context}
  Regime: {regime_impact}

DỮ LIỆU:
  Tên: {name} | Ngành: {industry} | Tier: {tier}
  Regime: {regime} | bull_weight={bull_weight}%
  Giá: {price} | 1D={price_1d}% 5D={price_5d}% 20D={price_20d}%
  Điểm: Tổng={composite} Cơbản={fundamental} SmartMoney={smart_money} Momentum={momentum} Kỹthuật={technical}
  PE={pe} ROE={roe}% ROA={roa}% BienRong={net_margin}% TT.DT={revenue_growth}% D/E={debt_equity}
  RSI={rsi} ADX={adx} FVG={fvg} OB={ob} Structure={structure}
  Khối ngoại: 7D={foreign_7d}B 30D={foreign_30d}B

---
Viết báo cáo đầy đủ BẰNG TIẾNG VIỆT theo đúng 8 phần. Phân tích THỰC CHẤT, dùng số liệu cụ thể:

# BÁO CÁO PHÂN TÍCH ĐẦU TƯ: {symbol}

## 1. TÓM TẮT ĐIỀU HÀNH
Tổng quan hoạt động kinh doanh của {name}. Luận điểm đầu tư 2-3 câu: {recommendation} ở mức giá {price} vì lý do gì? Catalyst chính và rủi ro lớn nhất.

## 2. HIỆU QUẢ TÀI CHÍNH & TÌNH HÌNH TÀI CHÍNH
### 2.1 Phân tích Báo cáo Thu nhập
Phân tích xu hướng doanh thu, biên lợi nhuận gộp/hoạt động/ròng. Dùng số cụ thể: ROE={roe}%, ROA={roa}%, biên ròng={net_margin}%, tăng trưởng={revenue_growth}%.
### 2.2 Phân tích Bảng Cân đối Kế toán
D/E={debt_equity} — mức nợ này có rủi ro không? Thanh khoản, vị thế tiền mặt. Bảng cân đối mạnh hay yếu?
### 2.3 Phân tích Dòng tiền
Dựa trên dữ liệu dòng tiền — CFO, CAPEX, FCF. Công ty có liên tục dương FCF không?

## 3. ĐỊNH GIÁ
### 3.1 Phân tích Bội số
PE={pe}x so với lịch sử 5 năm và trung bình ngành {industry}. So sánh với 3 đối thủ cạnh tranh trực tiếp.
### 3.2 Kết luận Định giá
Ở mức giá {price}: định giá quá cao / thấp / hợp lý? Lý giải cụ thể.

## 4. MÔ HÌNH KINH DOANH & HÀO KINH TẾ
### 4.1 Phân khúc Kinh doanh
Các mảng kinh doanh cốt lõi của {name} và đóng góp doanh thu tương ứng.
### 4.2 Lợi thế Cạnh tranh
Nguồn lợi thế cạnh tranh: thương hiệu, chi phí, quy mô, mạng lưới, giấy phép? Độ bền của hào kinh tế.

## 5. CHIẾN LƯỢC TĂNG TRƯỞNG & TRIỂN VỌNG
### 5.1 Động lực Tăng trưởng
Catalyst kỳ vọng: mảng kinh doanh mới, mở rộng thị trường, xu hướng ngành {industry}.
### 5.2 Cơ hội Thị trường
TAM ngành {industry} tại Việt Nam và tiềm năng tăng thị phần của {symbol}.

## 6. QUẢN LÝ & QUẢN TRỊ
### 6.1 Lãnh đạo
CEO và ban điều hành {name} — nhiệm kỳ, thành tích nổi bật.
### 6.2 Phân bổ Vốn
Chính sách cổ tức, mua lại cổ phiếu, M&A. Hiệu quả phân bổ vốn qua ROE={roe}%.
### 6.3 Sở hữu Nội bộ
Tỷ lệ cổ đông nội bộ và cổ đông lớn nắm giữ {symbol}.

## 7. PHÂN TÍCH RỦI RO
### 7.1 Rủi ro Đặc thù
3 rủi ro nội tại cụ thể của {symbol} (không phải rủi ro chung).
### 7.2 Rủi ro Hệ thống
3 rủi ro vĩ mô/thị trường ảnh hưởng trực tiếp, bao gồm tác động của regime {regime} (bull={bull_weight}%).

## 8. KHUYẾN NGHỊ CUỐI CÙNG
Tổng hợp toàn bộ phân tích → Xếp hạng **{recommendation}** với lý luận cụ thể: cân bằng cơ hội vs rủi ro ở mức giá {price}.

---
*Báo cáo được tạo tự động bởi VN Stock Scanner AI · Chỉ mang tính tham khảo, không phải khuyến nghị đầu tư chính thức.*
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
        roe=_fmt((screener.get("roe") or 0)*100, 2),
        roa=_fmt((screener.get("roa") or 0)*100, 2),
        pe=_fmt(screener.get("pe"), 1),
        net_margin=_fmt((screener.get("net_margin") or 0)*100, 2),
        revenue_growth=_fmt((screener.get("revenue_growth") or 0)*100, 2),
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



def call_ai_report(prompt: str) -> Optional[str]:
    """Gen báo cáo chi tiết dạng Markdown — không dùng json_object mode."""
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
    except ImportError:
        return None
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=4096,
            # Không dùng response_format json_object — output là markdown text
        )
        return response.choices[0].message.content
    except Exception as e:
        log.warning("⚠️  call_ai_report lỗi: %s", e)
        return None


def build_report_prompt(symbol: str, parsed: Dict, screener: Dict, ict: Dict, regime: Dict) -> str:
    """Build prompt cho báo cáo chi tiết dựa trên kết quả phân tích đã có."""
    sections = parsed.get("sections") or {}
    return REPORT_PROMPT_TEMPLATE.format(
        symbol=symbol,
        name=screener.get("name", symbol),
        industry=screener.get("industry", "N/A"),
        tier=screener.get("tier", "N/A"),
        regime=regime.get("regime", "UNKNOWN"),
        bull_weight=_fmt((regime.get("bull_weight") or 0) * 100, 0),
        price=_fmt(screener.get("close") or screener.get("price"), 1),
        price_1d=_fmt(screener.get("price_change_1d"), 2),
        price_5d=_fmt(screener.get("price_change_5d"), 2),
        price_20d=_fmt(screener.get("price_change_20d"), 2),
        composite=_fmt(screener.get("composite_score"), 1),
        fundamental=_fmt(screener.get("fundamental_score"), 1),
        smart_money=_fmt(screener.get("smart_money_score"), 1),
        momentum=_fmt(screener.get("momentum_score"), 1),
        technical=_fmt(screener.get("technical_score"), 1),
        pe=_fmt(screener.get("pe"), 1),
        roe=_fmt((screener.get("roe") or 0)*100, 2),
        roa=_fmt((screener.get("roa") or 0)*100, 2),
        net_margin=_fmt((screener.get("net_margin") or 0)*100, 2),
        revenue_growth=_fmt((screener.get("revenue_growth") or 0)*100, 2),
        debt_equity=_fmt(screener.get("debt_equity"), 2),
        rsi=_fmt(screener.get("rsi14"), 1),
        adx=_fmt(screener.get("adx14"), 1),
        fvg=_bool(ict.get("fvg_bull")),
        ob=_bool(ict.get("ob_bull")),
        structure=ict.get("structure", "N/A"),
        foreign_7d=_fmt(screener.get("foreign_net_7d"), 1),
        foreign_30d=_fmt(screener.get("foreign_net_30d"), 1),
        recommendation=parsed.get("recommendation", "HOLD"),
        executive_summary=parsed.get("executive_summary") or parsed.get("summary", ""),
        ict_analysis=sections.get("ict_analysis", ""),
        technical_view=sections.get("technical_view", ""),
        flow_analysis=sections.get("flow_analysis", ""),
        fundamental_view=sections.get("fundamental_view", ""),
        sector_context=sections.get("sector_context", ""),
        regime_impact=sections.get("regime_impact", ""),
    )


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
        fundamental_view = f"Cơ bản vững (score={f_score:.0f}" + (f", ROE={roe*100:.1f}%" if roe > 0.10 else "") + ")"
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
                        # Normalize new structure → backward-compat with frontend
                        # Map executive_summary → summary if needed
                        if "executive_summary" in parsed and "summary" not in parsed:
                            parsed["summary"] = parsed["executive_summary"]
                        # Flatten sections → top-level for frontend
                        if "sections" in parsed:
                            secs = parsed["sections"]
                            if "fundamental_view" not in parsed:
                                parsed["fundamental_view"] = secs.get("fundamental_view", "")
                            if "technical_view" not in parsed:
                                parsed["technical_view"] = secs.get("ict_analysis", "") + " " + secs.get("technical_view", "")
                            if "flow_view" not in parsed:
                                parsed["flow_view"] = secs.get("flow_analysis", "")
                            parsed["regime_impact"]   = secs.get("regime_impact", "")
                            parsed["sector_context"]  = secs.get("sector_context", "")
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

        # ── Gen detailed_report (markdown 8 phần) cho mọi stock có AI ──────
        # Chỉ gen khi có OPENAI_API_KEY và result đến từ AI (không phải rule-based)
        if use_ai and result.get("recommendation") and "rule_based" not in result.get("_source", ""):
            try:
                report_prompt = build_report_prompt(sym, result, s, ic, regime)
                detailed = call_ai_report(report_prompt)
                if detailed:
                    result["detailed_report"] = detailed
                    log.info("   ✅ %s: detailed_report generated (%d chars)", sym, len(detailed))
                else:
                    log.warning("   ⚠️  %s: detailed_report skipped (no output)", sym)
            except Exception as e:
                log.warning("   ⚠️  %s: detailed_report error: %s", sym, e)

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
