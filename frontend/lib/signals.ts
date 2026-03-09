/**
 * signals.ts — Single source of truth cho tất cả signal/recommendation logic
 *
 * Được dùng bởi:
 *   - Dashboard (SignalBadge)
 *   - StockModal (AnalysisTab header badge + analysis.ts recommendation)
 *   - desk_analysis.ts (buildTradeSetup action)
 *
 * Logic duy nhất:
 *   effectiveScore = avgGroupScore × bull_weight + composite × (1 - bull_weight)
 *   Nếu không có ICT data → bull_weight = 0.5 (neutral market)
 *   BEAR override: bull_weight ≤ 0.3 → HOLD hoặc AVOID
 */

import type { Stock, ICTSignal, TradeAction, ConvictionLevel, SignalGroup } from './types';

// ─── Core Signal Types ────────────────────────────────────────────────────────

export type SignalLabel =
  | 'STRONG BUY'
  | 'BUY'
  | 'ACCUMULATE'
  | 'HOLD'
  | 'REDUCE'
  | 'SELL'
  | 'AVOID';

export interface SignalConfig {
  label: SignalLabel;
  action: TradeAction;          // matches TradeAction in types.ts
  color: string;
  bg: string;
  border: string;
  conviction: ConvictionLevel;
}

// ─── Signal Thresholds (single source) ───────────────────────────────────────

const THRESHOLDS = {
  STRONG_BUY:  75,
  BUY:         65,
  ACCUMULATE:  58,
  HOLD:        48,
  REDUCE:      38,
  // below 38 → SELL (or AVOID in BEAR)
} as const;

// ─── Visual Config Map ────────────────────────────────────────────────────────

export const SIGNAL_CONFIG: Record<TradeAction, Omit<SignalConfig, 'action' | 'conviction'>> = {
  STRONG_BUY: { label: 'STRONG BUY', color: '#00ff88', bg: '#00ff8820', border: '#00ff8850' },
  BUY:        { label: 'BUY',        color: '#00ff88', bg: '#00ff8814', border: '#00ff8838' },
  ACCUMULATE: { label: 'ACCUMULATE', color: '#00d4ff', bg: '#00d4ff14', border: '#00d4ff38' },
  HOLD:       { label: 'HOLD',       color: '#ffcc00', bg: '#ffcc0014', border: '#ffcc0040' },
  REDUCE:     { label: 'REDUCE',     color: '#ff9500', bg: '#ff950014', border: '#ff950040' },
  SELL:       { label: 'SELL',       color: '#ff3366', bg: '#ff336614', border: '#ff336640' },
  AVOID:      { label: 'AVOID',      color: '#ff3366', bg: '#ff336614', border: '#ff336640' },
};

// ─── Core Signal Engine ───────────────────────────────────────────────────────

/**
 * Tính signal từ stock + optional ICT data.
 * v3: Dynamic thresholds theo bull_weight + Super Combo path + Mean Reversion path
 *
 * Backtest findings baked in:
 *   - Trend+ADX>25+RSI<35: win 72.7% 20D, avg +9.79% → STRONG_BUY path riêng
 *   - Crash -15%/20D: bounce avg +1.79% 10D → Mean Reversion override (SHORT TERM)
 *   - MA20 cross standalone: -0.45% 20D → không được thưởng điểm
 *   - BEAR regime: tăng thresholds để khó đạt BUY hơn
 */
export function computeSignal(
  composite: number,
  bullWeight: number = 0.5,
  groups?: SignalGroup[],
  foreignNet7d?: number,
  stock?: Stock,              // v3: cần thêm raw indicators cho special paths
): SignalConfig {

  // Effective score: blend group analysis + composite, weighted by market regime
  const avgScore = groups && groups.length > 0
    ? groups.reduce((s, g) => s + g.score, 0) / groups.length
    : composite;

  const effectiveScore = avgScore * bullWeight + composite * (1 - bullWeight);

  // ── v3: Dynamic thresholds theo regime ────────────────────────────────────
  // BEAR (bw≤0.3): tăng threshold BUY +5 để khó đạt hơn (market không ủng hộ)
  // BULL (bw≥0.65): giảm threshold BUY -3 để dễ trigger hơn
  const regimeShift = bullWeight <= 0.3 ? 5 : bullWeight >= 0.65 ? -3 : 0;
  const T = {
    STRONG_BUY:  THRESHOLDS.STRONG_BUY  + regimeShift,
    BUY:         THRESHOLDS.BUY         + regimeShift,
    ACCUMULATE:  THRESHOLDS.ACCUMULATE  + regimeShift,
    HOLD:        THRESHOLDS.HOLD,       // HOLD threshold không thay đổi
    REDUCE:      THRESHOLDS.REDUCE,
  };

  // ── v3: Super Combo path — Trend+ADX>25+RSI<35 ───────────────────────────
  // Backtest: win 72.7% 20D, avg +9.79% fwd10D (strongest edge in dataset)
  // Chỉ kích hoạt khi KHÔNG phải BEAR extreme (bullWeight > 0.25)
  if (stock && bullWeight > 0.25) {
    const rsi   = stock.rsi14 ?? 50;
    const adx   = stock.adx14 ?? 0;
    const trend = stock.trend_short ?? 0;
    if (trend === 1 && adx > 25 && rsi < 35) {
      const conviction: ConvictionLevel = adx > 35 && rsi < 30 ? 'HIGH' : 'MEDIUM';
      if (bullWeight >= 0.5) {
        const cfg = SIGNAL_CONFIG['STRONG_BUY'];
        return { ...cfg, action: 'STRONG_BUY', conviction };
      } else {
        // BEAR-ish but not extreme: BUY with lower conviction
        const cfg = SIGNAL_CONFIG['BUY'];
        return { ...cfg, action: 'BUY', conviction: 'LOW' };
      }
    }
  }

  // ── v3: Mean Reversion path — crash bounce (SHORT TERM) ──────────────────
  // Backtest: crash -15%/20D → bounce avg +1.79% 10D, +8% vs bench (5-10D)
  // Override chỉ cho SHORT TERM signal — không dùng cho position sizing
  // Không override nếu đang ở BEAR extreme (sẽ tiếp tục giảm 20D)
  if (stock && bullWeight > 0.3) {
    const p20d = stock.price_change_20d ?? stock.change_20d ?? 0;
    const rsi  = stock.rsi14 ?? 50;
    if (p20d < -15 && rsi < 40) {
      const cfg = SIGNAL_CONFIG['ACCUMULATE'];
      return {
        ...cfg,
        action: 'ACCUMULATE',
        conviction: p20d < -20 && rsi < 35 ? 'MEDIUM' : 'LOW',
        label: 'ACCUMULATE',
      };
    }
  }

  // ── Standard path ─────────────────────────────────────────────────────────
  let action: TradeAction;
  let conviction: ConvictionLevel;

  if (bullWeight <= 0.3) {
    // BEAR market: tất cả signals đều bị giảm bậc
    if (effectiveScore >= T.BUY) {
      action = 'HOLD';
    } else if (effectiveScore >= T.HOLD) {
      action = 'REDUCE';
    } else {
      action = 'SELL';
    }
    conviction = 'LOW';
  } else if (effectiveScore >= T.STRONG_BUY) {
    action = 'STRONG_BUY'; conviction = 'HIGH';
  } else if (effectiveScore >= T.BUY) {
    action = 'BUY'; conviction = 'HIGH';
  } else if (effectiveScore >= T.ACCUMULATE) {
    action = 'ACCUMULATE'; conviction = 'MEDIUM';
  } else if (effectiveScore >= T.HOLD) {
    action = 'HOLD'; conviction = 'LOW';
  } else if (effectiveScore >= T.REDUCE) {
    action = 'REDUCE'; conviction = 'MEDIUM';
  } else {
    action = 'SELL'; conviction = 'HIGH';
  }

  // Foreign flow boost: ACCUMULATE → BUY nếu khối ngoại mua mạnh và gần ngưỡng
  if (
    action === 'ACCUMULATE' &&
    (foreignNet7d ?? 0) > 100 &&
    effectiveScore >= 62
  ) {
    action = 'BUY';
    conviction = 'MEDIUM';
  }

  const cfg = SIGNAL_CONFIG[action];
  return { ...cfg, action, conviction };
}

/**
 * Convenience wrapper — nhận thẳng Stock + ICTSignal objects
 */
export function getStockSignal(
  stock: Stock,
  ict?: ICTSignal | null,
  groups?: SignalGroup[],
): SignalConfig {
  const composite = stock.composite_score ?? 50;
  const bullWeight = ict?.bull_weight ?? 0.5;
  const foreignNet7d = stock.foreign_net_7d;
  return computeSignal(composite, bullWeight, groups, foreignNet7d, stock);
}

/**
 * Map TradeAction → AIAnalysis recommendation
 * (để đồng bộ với analysis.ts getRecommendationDisplay)
 */
export function actionToRecommendation(
  action: TradeAction,
): 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' {
  switch (action) {
    case 'STRONG_BUY':  return 'STRONG_BUY';
    case 'BUY':         return 'BUY';
    case 'ACCUMULATE':  return 'BUY';    // ACCUMULATE hiển thị như BUY trong analysis tab
    case 'HOLD':        return 'HOLD';
    case 'REDUCE':      return 'SELL';
    case 'SELL':        return 'SELL';
    case 'AVOID':       return 'STRONG_SELL';
  }
}
