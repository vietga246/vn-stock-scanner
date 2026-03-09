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
 * Đây là hàm duy nhất quyết định action — tất cả UI import từ đây.
 *
 * @param composite   composite_score của stock (0-100)
 * @param bullWeight  bull_weight từ ICT regime (0-1). Default 0.5 nếu không có ICT.
 * @param groups      SignalGroup[] từ desk_analysis (optional — dùng để tính avgScore)
 * @param foreignNet7d  foreign_net_7d tính bằng tỷ VNĐ (optional — dùng cho boost rule)
 */
export function computeSignal(
  composite: number,
  bullWeight: number = 0.5,
  groups?: SignalGroup[],
  foreignNet7d?: number,
): SignalConfig {

  // Effective score: blend group analysis + composite, weighted by market regime
  const avgScore = groups && groups.length > 0
    ? groups.reduce((s, g) => s + g.score, 0) / groups.length
    : composite; // fallback: chỉ dùng composite khi không có groups

  const effectiveScore = avgScore * bullWeight + composite * (1 - bullWeight);

  // Action decision
  let action: TradeAction;
  let conviction: ConvictionLevel;

  if (bullWeight <= 0.3) {
    // BEAR market — phân loại rõ hơn thay vì chỉ HOLD/AVOID
    if (effectiveScore >= THRESHOLDS.BUY) {
      action = 'HOLD';          // composite tốt nhưng không mua trong BEAR
    } else if (effectiveScore >= THRESHOLDS.HOLD) {
      action = 'REDUCE';        // dưới ngưỡng mua → giảm vị thế
    } else {
      action = 'SELL';          // yếu + BEAR market → thoát
    }
    conviction = 'LOW';
  } else if (effectiveScore >= THRESHOLDS.STRONG_BUY) {
    action = 'STRONG_BUY'; conviction = 'HIGH';
  } else if (effectiveScore >= THRESHOLDS.BUY) {
    action = 'BUY'; conviction = 'HIGH';
  } else if (effectiveScore >= THRESHOLDS.ACCUMULATE) {
    action = 'ACCUMULATE'; conviction = 'MEDIUM';
  } else if (effectiveScore >= THRESHOLDS.HOLD) {
    action = 'HOLD'; conviction = 'LOW';
  } else if (effectiveScore >= THRESHOLDS.REDUCE) {
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
  return computeSignal(composite, bullWeight, groups, foreignNet7d);
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
