/**
 * desk_analysis.ts — Prop Trading Desk Analysis Engine
 *
 * Phân tích theo cách một desk prop trading hoặc quỹ thực sự làm:
 *  1. Macro / Regime filter  — thị trường có phù hợp để long không?
 *  2. Market Structure       — trend, BOS, CHoCH, swing levels
 *  3. Smart Money / Flow     — khối ngoại, dòng tiền tổ chức, buy pressure
 *  4. Valuation & Fundamentals — PE, ROE, tăng trưởng, nợ vay
 *  5. Technical Momentum     — RSI, ADX, MACD, MA alignment
 *  6. ICT Confluences        — FVG, OB, Liquidity Sweep (nếu có)
 *  7. Entry / Risk Setup     — entry zone, stop loss, target, R:R
 */

import type {
  Stock,
  ICTSignal,
  DeskAnalysis,
  SignalGroup,
  SignalItem,
  SignalStrength,
  TradeAction,
  ConvictionLevel,
  TradeSetup,
} from './types';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pos(label: string, value: string, note?: string): SignalItem {
  return { label, value, status: 'positive', note };
}
function neg(label: string, value: string, note?: string): SignalItem {
  return { label, value, status: 'negative', note };
}
function neu(label: string, value: string, note?: string): SignalItem {
  return { label, value, status: 'neutral', note };
}
function warn(label: string, value: string, note?: string): SignalItem {
  return { label, value, status: 'warning', note };
}

function fmt(n: number | null | undefined, dec = 1): string {
  if (n == null) return '–';
  return n.toFixed(dec);
}
function fmtPct(n: number | null | undefined): string {
  if (n == null) return '–';
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}
function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '–';
  return new Intl.NumberFormat('vi-VN').format(Math.round(n));
}

function scoreToStrength(score: number): SignalStrength {
  if (score >= 72) return 'STRONG';
  if (score >= 58) return 'MODERATE';
  if (score >= 45) return 'NEUTRAL';
  if (score >= 32) return 'WEAK';
  return 'NEGATIVE';
}

// ─── Signal Group Builders ────────────────────────────────────────────────────

function buildRegimeGroup(stock: Stock, ict?: ICTSignal): SignalGroup {
  const signals: SignalItem[] = [];
  let score = 50;

  const bw = ict?.bull_weight;

  if (bw != null) {
    if (bw >= 0.7) {
      signals.push(pos('Market Regime', 'BULL', `Bull weight ${(bw * 100).toFixed(0)}%`));
      score += 20;
    } else if (bw >= 0.5) {
      signals.push(neu('Market Regime', 'RANGE / TRANSITION', `Bull weight ${(bw * 100).toFixed(0)}%`));
    } else {
      signals.push(neg('Market Regime', 'BEAR', `Bull weight ${(bw * 100).toFixed(0)}% — hạn chế long`));
      score -= 20;
    }
  } else {
    signals.push(neu('Market Regime', 'Không có dữ liệu ICT', 'Chạy ICT scanner để cập nhật'));
  }

  // Sector context
  if (stock.industry) {
    signals.push(neu('Sector', stock.industry));
  }

  // Price momentum vs market
  const p5d = stock.price_change_5d ?? stock.change_5d;
  const p20d = stock.price_change_20d ?? stock.change_20d;
  if (p5d != null && p20d != null) {
    const rs = (p5d > 0 && p20d > 0) ? 'Outperforming' : (p5d < 0 && p20d < 0) ? 'Underperforming' : 'Mixed';
    const rsScore = p5d + p20d;
    if (rsScore > 5) {
      signals.push(pos('Relative Strength', rs, `5D: ${fmtPct(p5d)} | 20D: ${fmtPct(p20d)}`));
      score += 10;
    } else if (rsScore < -5) {
      signals.push(neg('Relative Strength', rs, `5D: ${fmtPct(p5d)} | 20D: ${fmtPct(p20d)}`));
      score -= 10;
    } else {
      signals.push(neu('Relative Strength', rs, `5D: ${fmtPct(p5d)} | 20D: ${fmtPct(p20d)}`));
    }
  }

  return { id: 'regime', label: 'MACRO / REGIME', icon: '🌐', score: Math.min(100, Math.max(0, score)), strength: scoreToStrength(score), signals };
}

function buildStructureGroup(stock: Stock, ict?: ICTSignal): SignalGroup {
  const signals: SignalItem[] = [];
  let score = 50;

  if (ict) {
    // Structure
    if (ict.structure === 'BULLISH') {
      signals.push(pos('Market Structure', '↑ BULLISH', 'Higher Highs + Higher Lows'));
      score += 20;
    } else if (ict.structure === 'BEARISH') {
      signals.push(neg('Market Structure', '↓ BEARISH', 'Lower Highs + Lower Lows'));
      score -= 20;
    } else {
      signals.push(neu('Market Structure', '— NEUTRAL / CONSOLIDATION'));
    }

    // BOS / CHoCH
    if (ict.choch_bull) {
      signals.push(pos('CHoCH', 'Bullish Change of Character ✓', 'Reversal confirmation — high conviction'));
      score += 20;
    } else if (ict.bos_bull) {
      signals.push(pos('BOS', 'Bullish Break of Structure ✓', 'Continuation signal'));
      score += 12;
    } else if (ict.choch_bear) {
      signals.push(neg('CHoCH', 'Bearish Change of Character ⚠️', 'Trend reversal signal'));
      score -= 20;
    } else if (ict.bos_bear) {
      signals.push(neg('BOS', 'Bearish Break of Structure', 'Downtrend continuation'));
      score -= 12;
    } else {
      signals.push(neu('BOS / CHoCH', 'Chưa có tín hiệu breakout'));
    }

    // Key levels
    if (ict.last_sh != null) signals.push(neu('Swing High', fmtPrice(ict.last_sh), 'Vùng kháng cự gần nhất'));
    if (ict.last_sl != null) signals.push(neu('Swing Low', fmtPrice(ict.last_sl), 'Vùng hỗ trợ gần nhất / SL reference'));

    // Equal levels (liquidity pools)
    if (ict.eq_high_count >= 2) signals.push(warn('Equal Highs', `${ict.eq_high_count} levels`, 'Liquidity pool phía trên — cẩn thận stop hunt'));
    if (ict.eq_low_count >= 2) signals.push(pos('Equal Lows', `${ict.eq_low_count} levels`, 'Liquidity pool phía dưới — potential sweep & reverse'));
  } else {
    // Fallback từ trend_short
    const trend = stock.trend_short;
    if (trend === 1) { signals.push(pos('Xu hướng', 'Uptrend')); score += 15; }
    else if (trend === -1) { signals.push(neg('Xu hướng', 'Downtrend')); score -= 15; }
    else { signals.push(neu('Xu hướng', 'Sideways')); }

    const adx = stock.adx14;
    if (adx != null) {
      if (adx >= 30) { signals.push(pos('ADX', `${fmt(adx, 0)} — Trend mạnh`)); score += 10; }
      else if (adx >= 20) { signals.push(neu('ADX', `${fmt(adx, 0)} — Trend vừa`)); }
      else { signals.push(warn('ADX', `${fmt(adx, 0)} — Choppy / không có trend`)); score -= 5; }
    }
  }

  return { id: 'structure', label: 'MARKET STRUCTURE', icon: '📐', score: Math.min(100, Math.max(0, score)), strength: scoreToStrength(score), signals };
}

function buildFlowGroup(stock: Stock, ict?: ICTSignal): SignalGroup {
  const signals: SignalItem[] = [];
  let score = stock.smart_money_score ?? 50;

  const nn7d = stock.foreign_net_7d ?? 0;
  const nn30d = stock.foreign_net_30d ?? 0;

  // Foreign net
  if (nn7d > 50) {
    signals.push(pos('Khối ngoại 7D', `+${nn7d.toFixed(1)}B`, nn30d > 0 ? `30D: +${nn30d.toFixed(1)}B — tích lũy bền vững` : undefined));
  } else if (nn7d > 0) {
    signals.push(neu('Khối ngoại 7D', `+${nn7d.toFixed(1)}B`, 'Mua nhỏ, chờ xác nhận'));
  } else if (nn7d < -50) {
    signals.push(neg('Khối ngoại 7D', `${nn7d.toFixed(1)}B`, nn30d < 0 ? `30D: ${nn30d.toFixed(1)}B — phân phối liên tục` : 'Cần theo dõi'));
  } else if (nn7d < 0) {
    signals.push(warn('Khối ngoại 7D', `${nn7d.toFixed(1)}B`, 'Bán nhỏ, chưa đáng ngại'));
  } else {
    signals.push(neu('Khối ngoại 7D', '–', 'Trung lập'));
  }

  // 30D trend
  if (nn30d > 0 && nn7d > 0) {
    signals.push(pos('Flow Trend', 'Mua ròng liên tục 30D', `+${nn30d.toFixed(1)}B`));
  } else if (nn30d < 0 && nn7d < 0) {
    signals.push(neg('Flow Trend', 'Bán ròng liên tục 30D', `${nn30d.toFixed(1)}B`));
  } else if (nn30d !== 0) {
    signals.push(neu('Flow Trend', 'Mixed 30D', `30D: ${fmtPct((nn30d / Math.abs(nn30d || 1)) * 10)}`));
  }

  // ICT flow data
  if (ict) {
    if (ict.smart_money) {
      signals.push(pos('Smart Money', 'Confluence confirmed 💎', 'Foreign + Buy Pressure đồng thuận'));
      score = Math.min(100, score + 15);
    }
    if (ict.flow_direction === 'in') {
      signals.push(pos('Inst. Flow Direction', '▲ INFLOW', ict.flow_trend === 'accelerating' ? 'Đang tăng tốc' : 'Steady'));
    } else if (ict.flow_direction === 'out') {
      signals.push(neg('Inst. Flow Direction', '▼ OUTFLOW', 'Smart money rút'));
      score = Math.max(0, score - 10);
    }
    if (ict.buy_pressure_pct != null) {
      const bp = ict.buy_pressure_pct;
      if (bp >= 60) signals.push(pos('Buy Pressure', `${fmt(bp, 0)}%`, 'Bên mua áp đảo'));
      else if (bp <= 40) signals.push(neg('Buy Pressure', `${fmt(bp, 0)}%`, 'Bên bán áp đảo'));
      else signals.push(neu('Buy Pressure', `${fmt(bp, 0)}%`, 'Cân bằng'));
    }
  }

  return { id: 'flow', label: 'SMART MONEY / FLOW', icon: '💰', score: Math.min(100, Math.max(0, score)), strength: scoreToStrength(score), signals };
}

function buildFundamentalsGroup(stock: Stock): SignalGroup {
  const signals: SignalItem[] = [];
  let score = stock.fundamental_score ?? 50;

  // Valuation
  const pe = stock.pe;
  if (pe != null && pe > 0) {
    if (pe < 10) signals.push(pos('P/E', `${fmt(pe)}x`, 'Định giá rất rẻ'));
    else if (pe < 18) signals.push(pos('P/E', `${fmt(pe)}x`, 'Định giá hợp lý'));
    else if (pe < 30) signals.push(neu('P/E', `${fmt(pe)}x`, 'Trên trung bình — cần tăng trưởng tốt'));
    else signals.push(warn('P/E', `${fmt(pe)}x`, 'Định giá cao, rủi ro kỳ vọng'));
  }

  // Profitability — data stored as decimal (0.18 = 18%), convert to pct
  const roePct = stock.roe != null ? (stock.roe > 1 ? stock.roe : stock.roe * 100) : null;
  if (roePct != null) {
    if (roePct >= 20) signals.push(pos('ROE', `${fmt(roePct)}%`, 'Sinh lời vốn chủ xuất sắc'));
    else if (roePct >= 12) signals.push(pos('ROE', `${fmt(roePct)}%`, 'Tốt'));
    else if (roePct >= 5) signals.push(neu('ROE', `${fmt(roePct)}%`, 'Trung bình ngành'));
    else signals.push(neg('ROE', `${fmt(roePct)}%`, 'Hiệu quả sử dụng vốn thấp'));
  }

  const roaPct = stock.roa != null ? (stock.roa > 1 ? stock.roa : stock.roa * 100) : null;
  if (roaPct != null) {
    if (roaPct >= 10) signals.push(pos('ROA', `${fmt(roaPct)}%`, 'Asset productivity cao'));
    else if (roaPct >= 4) signals.push(neu('ROA', `${fmt(roaPct)}%`));
    else signals.push(neg('ROA', `${fmt(roaPct)}%`, 'Tài sản tạo ra ít lợi nhuận'));
  }

  // Growth — decimal (0.15 = 15%)
  const revGrowthPct = stock.revenue_growth != null ? (Math.abs(stock.revenue_growth) > 1 ? stock.revenue_growth : stock.revenue_growth * 100) : null;
  if (revGrowthPct != null) {
    if (revGrowthPct >= 20) signals.push(pos('Rev Growth', `+${fmt(revGrowthPct)}%`, 'Tăng trưởng cao'));
    else if (revGrowthPct >= 5) signals.push(neu('Rev Growth', `+${fmt(revGrowthPct)}%`));
    else if (revGrowthPct < 0) signals.push(neg('Rev Growth', `${fmt(revGrowthPct)}%`, 'Doanh thu sụt giảm'));
    else signals.push(neu('Rev Growth', `+${fmt(revGrowthPct)}%`, 'Tăng trưởng chậm'));
  }

  // Net Margin — decimal (0.1 = 10%)
  const marginPct = stock.net_margin != null ? (stock.net_margin > 1 ? stock.net_margin : stock.net_margin * 100) : null;
  if (marginPct != null) {
    if (marginPct >= 20) signals.push(pos('Net Margin', `${fmt(marginPct)}%`, 'Biên lợi nhuận cao'));
    else if (marginPct >= 8) signals.push(neu('Net Margin', `${fmt(marginPct)}%`));
    else if (marginPct > 0) signals.push(warn('Net Margin', `${fmt(marginPct)}%`, 'Biên mỏng'));
    else signals.push(neg('Net Margin', `${fmt(marginPct)}%`, 'Lỗ'));
  }

  // Leverage — D/E thường là ratio, giữ nguyên
  const de = stock.debt_equity;
  if (de != null) {
    if (de < 0.5) signals.push(pos('D/E', `${fmt(de)}x`, 'Bảng cân đối lành mạnh'));
    else if (de < 1.5) signals.push(neu('D/E', `${fmt(de)}x`));
    else if (de < 3) signals.push(warn('D/E', `${fmt(de)}x`, 'Đòn bẩy cao'));
    else signals.push(neg('D/E', `${fmt(de)}x`, 'Rủi ro tài chính — nợ vay lớn'));
  }

  return { id: 'fundamentals', label: 'VALUATION & FUNDAMENTALS', icon: '📊', score: Math.min(100, Math.max(0, score)), strength: scoreToStrength(score), signals };
}

function buildTechnicalGroup(stock: Stock, ict?: ICTSignal): SignalGroup {
  const signals: SignalItem[] = [];
  let score = stock.technical_score ?? 50;

  // ADX — Trend strength
  const adx = stock.adx14;
  if (adx != null) {
    if (adx >= 30) { signals.push(pos('ADX', `${fmt(adx, 0)}`, 'Trend mạnh — momentum rõ ràng')); score = Math.min(100, score + 8); }
    else if (adx >= 20) { signals.push(neu('ADX', `${fmt(adx, 0)}`, 'Trend vừa')); }
    else { signals.push(warn('ADX', `${fmt(adx, 0)}`, 'Thị trường đang choppy / sideway')); score = Math.max(0, score - 5); }
  }

  // RSI
  const rsi = stock.rsi14;
  if (rsi != null) {
    if (rsi > 75) { signals.push(warn('RSI', `${fmt(rsi, 0)}`, 'Vùng quá mua — cẩn thận correction')); }
    else if (rsi >= 55 && rsi <= 75) { signals.push(pos('RSI', `${fmt(rsi, 0)}`, 'Momentum tăng bền vững')); }
    else if (rsi >= 40 && rsi < 55) { signals.push(neu('RSI', `${fmt(rsi, 0)}`, 'Trung tính')); }
    else if (rsi >= 25) { signals.push(warn('RSI', `${fmt(rsi, 0)}`, 'Momentum yếu')); score = Math.max(0, score - 5); }
    else { signals.push(pos('RSI', `${fmt(rsi, 0)}`, 'Oversold — potential bounce setup')); }
  }

  // MA alignment (trend_short/trend_strength)
  const ts = stock.trend_strength;
  if (ts != null) {
    if (ts >= 70) { signals.push(pos('MA Alignment', `${fmt(ts, 0)}/100`, 'Giá trên tất cả MA — uptrend rõ')); }
    else if (ts >= 50) { signals.push(neu('MA Alignment', `${fmt(ts, 0)}/100`, 'Trên MA ngắn hạn')); }
    else { signals.push(neg('MA Alignment', `${fmt(ts, 0)}/100`, 'Dưới MA — bearish alignment')); }
  }

  // Distance from MA
  const pma20 = stock.pct_from_ma20;
  if (pma20 != null) {
    if (pma20 > 10) signals.push(warn('Từ MA20', `+${fmt(pma20)}%`, 'Giá cao quá MA20 — overextended'));
    else if (pma20 >= 0) signals.push(pos('Từ MA20', `+${fmt(pma20)}%`, 'Trên MA20'));
    else if (pma20 >= -5) signals.push(warn('Từ MA20', `${fmt(pma20)}%`, 'Vừa rơi dưới MA20'));
    else signals.push(neg('Từ MA20', `${fmt(pma20)}%`, 'Xa dưới MA20'));
  }

  // FVG
  if (ict?.fvg_bull) {
    signals.push(pos('Fair Value Gap', 'Bullish FVG active', ict.sweep_price ? `Gap level ~${fmtPrice(ict.sweep_price)}` : 'Vùng imbalance chưa fill'));
    score = Math.min(100, score + 8);
  }
  if (stock.fvg_bull && !ict) {
    signals.push(pos('Fair Value Gap', 'Bullish FVG active'));
    score = Math.min(100, score + 6);
  }

  // Momentum score fallback
  const mom = stock.momentum_score;
  if (mom != null && adx == null && rsi == null) {
    if (mom >= 70) signals.push(pos('Momentum', `${fmt(mom, 0)}/100`));
    else if (mom >= 45) signals.push(neu('Momentum', `${fmt(mom, 0)}/100`));
    else signals.push(neg('Momentum', `${fmt(mom, 0)}/100`));
  }

  return { id: 'technical', label: 'TECHNICAL MOMENTUM', icon: '📈', score: Math.min(100, Math.max(0, score)), strength: scoreToStrength(score), signals };
}

function buildICTGroup(ict: ICTSignal): SignalGroup {
  const signals: SignalItem[] = [];
  let score = ict.ict_score;

  // Order Block
  if (ict.ob_bull && !ict.ob_mitigated) {
    if (ict.ob_price_at) {
      signals.push(pos('Order Block', `Price AT OB 🎯`, `Top: ${fmtPrice(ict.ob_bull_top)} | Bot: ${fmtPrice(ict.ob_bull_bottom)} — Entry zone active`));
      score = Math.min(100, score + 10);
    } else {
      signals.push(pos('Order Block', 'Bullish OB unmitigated', `${fmtPrice(ict.ob_bull_top)} – ${fmtPrice(ict.ob_bull_bottom)} | Age: ${ict.ob_bull_age}b`));
    }
  } else if (ict.ob_bull && ict.ob_mitigated) {
    signals.push(neu('Order Block', 'OB đã bị mitigated', 'Tìm OB mới'));
  } else {
    signals.push(neu('Order Block', 'Chưa phát hiện OB', ''));
  }

  // Liquidity Sweep
  if (ict.sweep_bull) {
    signals.push(pos('Liq Sweep', `Swept EqL — Bullish`, ict.sweep_age != null ? `${ict.sweep_age} bars trước` : undefined));
    score = Math.min(100, score + 8);
  } else if (ict.stop_hunt_bull) {
    signals.push(pos('Stop Hunt', 'Retail stops cleared ✓', 'Smart money đã sweep stop loss'));
    score = Math.min(100, score + 6);
  } else {
    signals.push(neu('Liquidity', 'Chưa có sweep', 'Chờ sweep trước khi entry'));
  }

  // Accumulation
  if (ict.wyckoff_spring) {
    signals.push(pos('Wyckoff Spring', 'Detected 💧', 'Smart money absorbing selling pressure'));
    score = Math.min(100, score + 12);
  }

  if (ict.accumulation_score >= 65) {
    signals.push(pos('Accumulation', `Score: ${fmt(ict.accumulation_score, 0)}/100`, ict.vol_spike >= 1.5 ? `Vol spike ${fmt(ict.vol_spike, 1)}x` : undefined));
  } else if (ict.distribution_score >= 65) {
    signals.push(neg('Distribution', `Score: ${fmt(ict.distribution_score, 0)}/100`, 'Dấu hiệu phân phối'));
    score = Math.max(0, score - 10);
  }

  if (ict.breakout_imminent) {
    signals.push(pos('Breakout Setup', 'NR7 + Vol compression', 'Volatility compression — explosive move incoming'));
    score = Math.min(100, score + 6);
  }

  if (ict.vol_spike >= 2) {
    signals.push(pos('Volume Spike', `${fmt(ict.vol_spike, 1)}x MA20`, 'Bất thường volume'));
  }

  return { id: 'ict', label: 'ICT CONFLUENCES', icon: '🧠', score: Math.min(100, Math.max(0, score)), strength: scoreToStrength(score), signals };
}

// ─── Trade Setup Builder ──────────────────────────────────────────────────────

function buildTradeSetup(
  stock: Stock,
  groups: SignalGroup[],
  ict?: ICTSignal
): TradeSetup {
  const price = stock.close || stock.price || 0;
  const composite = stock.composite_score ?? 50;

  // Aggregate group scores
  const avgScore = groups.reduce((s, g) => s + g.score, 0) / groups.length;
  const bullWeight = ict?.bull_weight ?? 0.5;
  const effectiveScore = avgScore * bullWeight + composite * (1 - bullWeight);

  // Action
  let action: TradeAction;
  let conviction: ConvictionLevel;
  if (bullWeight <= 0.3) {
    action = effectiveScore >= 65 ? 'HOLD' : 'AVOID';
    conviction = 'LOW';
  } else if (effectiveScore >= 75) {
    action = 'STRONG_BUY'; conviction = 'HIGH';
  } else if (effectiveScore >= 65) {
    action = 'BUY'; conviction = 'HIGH';
  } else if (effectiveScore >= 58) {
    action = 'ACCUMULATE'; conviction = 'MEDIUM';
  } else if (effectiveScore >= 48) {
    action = 'HOLD'; conviction = 'LOW';
  } else if (effectiveScore >= 38) {
    action = 'REDUCE'; conviction = 'MEDIUM';
  } else {
    action = bullWeight <= 0.3 ? 'AVOID' : 'SELL'; conviction = 'HIGH';
  }

  // Entry zone
  let entry_zone: string | undefined;
  let stop_loss: string | undefined;
  let target_1: string | undefined;
  let target_2: string | undefined;
  let risk_reward: string | undefined;

  if (price > 0 && (action === 'BUY' || action === 'STRONG_BUY' || action === 'ACCUMULATE')) {
    // Entry: current price or OB zone
    if (ict?.ob_price_at && ict.ob_bull_bottom && ict.ob_bull_top) {
      entry_zone = `${fmtPrice(ict.ob_bull_bottom)} – ${fmtPrice(ict.ob_bull_top)} (OB zone)`;
    } else {
      const lo = price * 0.99, hi = price * 1.01;
      entry_zone = `${fmtPrice(lo)} – ${fmtPrice(hi)}`;
    }

    // Stop: swing low or -4%
    const slPct = ict?.last_sl ? (price - ict.last_sl) / price : 0.04;
    const sl = ict?.last_sl ?? price * 0.96;
    stop_loss = `${fmtPrice(sl)} (${(slPct * 100).toFixed(1)}%)`;

    // Targets
    const riskAmt = price - sl;
    const t1 = price + riskAmt * 2;
    const t2 = price + riskAmt * 3.5;
    target_1 = `${fmtPrice(t1)} (+${((t1 / price - 1) * 100).toFixed(1)}%)`;
    target_2 = `${fmtPrice(t2)} (+${((t2 / price - 1) * 100).toFixed(1)}%)`;
    risk_reward = `1 : ${(riskAmt > 0 ? (riskAmt * 2 / riskAmt).toFixed(1) : '–')}`;

    // R:R = T1 / stop distance
    if (riskAmt > 0) {
      const rr = ((t1 - price) / (price - sl));
      risk_reward = `1 : ${rr.toFixed(1)}`;
    }
  }

  // Time horizon
  const adx = stock.adx14 ?? 0;
  const time_horizon = adx >= 25
    ? 'Swing 5–15 phiên (trend đang rõ)'
    : 'Swing 3–7 phiên hoặc chờ breakout';

  // Invalidation
  let invalidation: string | undefined;
  if (ict?.last_sl) {
    invalidation = `Đóng cửa dưới ${fmtPrice(ict.last_sl)} kèm volume cao`;
  } else if (price > 0) {
    invalidation = `Đóng cửa dưới ${fmtPrice(price * 0.95)} (-5%) và volume tăng`;
  }

  return { action, conviction, entry_zone, stop_loss, target_1, target_2, risk_reward, time_horizon, invalidation };
}

// ─── Narrative Builder ────────────────────────────────────────────────────────

function buildNarrative(
  stock: Stock,
  groups: SignalGroup[],
  setup: TradeSetup,
  ict?: ICTSignal
): { headline: string; narrative: string; catalysts: string[]; key_risks: string[] } {
  const sym = stock.symbol;
  const bw = ict?.bull_weight;
  const structureGroup = groups.find(g => g.id === 'structure');
  const flowGroup = groups.find(g => g.id === 'flow');

  // Headline
  const actionText: Record<string, string> = {
    STRONG_BUY: 'Setup mạnh — Long với conviction cao',
    BUY: 'Setup tốt — Long khi price vào zone',
    ACCUMULATE: 'Tích lũy dần — Giai đoạn xây dựng vị thế',
    HOLD: 'Giữ vị thế — Chưa có trigger rõ ràng',
    REDUCE: 'Giảm tỷ trọng — Dấu hiệu suy yếu',
    SELL: 'Thoát hàng — Điều kiện không thuận lợi',
    AVOID: bw != null && bw <= 0.3 ? 'BEAR Market — Ưu tiên phòng thủ, không long' : 'Tránh — Tín hiệu tiêu cực',
  };
  const headline = `${sym}: ${actionText[setup.action] ?? setup.action}`;

  // Narrative
  const parts: string[] = [];
  if (bw != null && bw <= 0.3) {
    parts.push(`Thị trường đang trong pha BEAR (bull weight ${(bw * 100).toFixed(0)}%), áp lực bán chiếm ưu thế.`);
  } else if (bw != null && bw >= 0.7) {
    parts.push(`Market đang trong pha BULL (bull weight ${(bw * 100).toFixed(0)}%), môi trường thuận lợi cho long.`);
  }

  if (structureGroup && structureGroup.strength !== 'NEUTRAL') {
    const struct = ict?.structure === 'BULLISH' ? 'cấu trúc giá đang bullish (HH/HL)' : ict?.structure === 'BEARISH' ? 'cấu trúc giá bearish (LL/LH)' : 'cấu trúc giá chưa rõ xu hướng';
    parts.push(`${sym} có ${struct}${ict?.bos_bull ? ', vừa có BOS bullish' : ''}${ict?.choch_bull ? ', CHoCH bullish xác nhận reversal' : ''}.`);
  }

  if (flowGroup && flowGroup.score >= 60) {
    const nn = stock.foreign_net_7d ?? 0;
    if (nn > 0) parts.push(`Dòng tiền ngoại tích cực với +${nn.toFixed(1)}B trong 7 ngày${ict?.smart_money ? ', smart money confluence xác nhận' : ''}.`);
  } else if (flowGroup && flowGroup.score <= 40) {
    parts.push(`Dòng tiền đang tiêu cực, cần thận trọng.`);
  }

  const narrative = parts.slice(0, 3).join(' ') || `${sym} đang trong giai đoạn quan sát. Chờ tín hiệu xác nhận rõ ràng hơn trước khi hành động.`;

  // Catalysts
  const catalysts: string[] = [];
  if (ict?.ob_price_at) catalysts.push('Giá đang tại vùng Order Block — entry zone đang active');
  if (ict?.wyckoff_spring) catalysts.push('Wyckoff Spring — smart money hấp thụ áp lực bán');
  if (ict?.sweep_bull) catalysts.push('Vừa sweep liquidity dưới EqL — bullish reversal setup');
  if (ict?.breakout_imminent) catalysts.push('NR7 + volume compression — breakout sắp xảy ra');
  if ((stock.foreign_net_7d ?? 0) > 50) catalysts.push(`Khối ngoại mua ròng mạnh +${(stock.foreign_net_7d ?? 0).toFixed(1)}B`);
  if (stock.rsi14 != null && stock.rsi14 < 30) catalysts.push(`RSI ${stock.rsi14.toFixed(0)} — vùng oversold, tiềm năng bounce`);
  if (stock.revenue_growth != null && stock.revenue_growth > 0.15) catalysts.push(`Tăng trưởng doanh thu +${(stock.revenue_growth > 1 ? stock.revenue_growth : stock.revenue_growth * 100).toFixed(0)}%`);

  // Risks
  const key_risks: string[] = [];
  if (bw != null && bw <= 0.3) key_risks.push('BEAR market — xác suất false breakout cao');
  if (ict?.eq_high_count && ict.eq_high_count >= 2) key_risks.push(`${ict.eq_high_count} Equal Highs phía trên — liquidity pool, nguy cơ stop hunt`);
  if (stock.debt_equity != null && stock.debt_equity > 2) key_risks.push(`D/E ${stock.debt_equity.toFixed(1)}x — đòn bẩy tài chính cao`);
  if (stock.rsi14 != null && stock.rsi14 > 70) key_risks.push(`RSI ${stock.rsi14.toFixed(0)} — vùng overbought, cẩn thận pullback`);
  if ((stock.foreign_net_7d ?? 0) < -50) key_risks.push(`Khối ngoại bán ròng ${(stock.foreign_net_7d ?? 0).toFixed(1)}B`);
  if (ict?.bos_bear) key_risks.push('BOS bearish — xu hướng giảm đang được xác nhận');

  return { headline, narrative, catalysts, key_risks };
}

// ─── Main Export ─────────────────────────────────────────────────────────────

export function generateDeskAnalysis(
  stock: Stock,
  ict?: ICTSignal,
  sectorStatus?: 'accumulating' | 'distributing' | 'neutral'
): DeskAnalysis {
  const groups: SignalGroup[] = [
    buildRegimeGroup(stock, ict),
    buildStructureGroup(stock, ict),
    buildFlowGroup(stock, ict),
    buildFundamentalsGroup(stock),
    buildTechnicalGroup(stock, ict),
  ];

  // Chỉ thêm ICT group nếu có data
  if (ict) {
    groups.push(buildICTGroup(ict));
  }

  // Sector status
  const flowGroup = groups.find(g => g.id === 'flow');
  if (flowGroup && sectorStatus === 'accumulating') {
    flowGroup.signals.push(pos('Sector Status', `${stock.industry} đang Accumulating`, 'Ngành đang được tích lũy'));
    flowGroup.score = Math.min(100, flowGroup.score + 5);
  } else if (flowGroup && sectorStatus === 'distributing') {
    flowGroup.signals.push(neg('Sector Status', `${stock.industry} đang Distributing`, 'Cẩn thận — ngành bị phân phối'));
    flowGroup.score = Math.max(0, flowGroup.score - 5);
  }

  // Recalculate strength after adjustments
  groups.forEach(g => { g.strength = scoreToStrength(g.score); });

  const setup = buildTradeSetup(stock, groups, ict);
  const { headline, narrative, catalysts, key_risks } = buildNarrative(stock, groups, setup, ict);

  return {
    symbol: stock.symbol,
    generated_at: new Date().toISOString(),
    headline,
    narrative,
    setup,
    signal_groups: groups,
    key_risks,
    catalysts,
  };
}