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
 * v5: 493,695 obs backtest (Oct 2022 – Mar 2026) findings:
 *   - Panic Bottom (drop>10% MA20 + RSI<30): win 65.8%, edge +4.26%, Sharpe 0.320
 *   - Crash -20% + RSI<35: win 63.2%, edge +4.44%
 *   - BB %B < 0: win 58.6%, edge +1.11% (best single indicator by win rate)
 *   - RSI < 30: win 52.9%, edge +1.49%
 *   - RSI > 80: win 43.2%, edge -0.34%
 *   - MACD Cross Up: edge -0.47% — CONTRARIAN on VNSTOCK
 *   - Momentum >15%: edge +0.06% (p>0.1) — NO EDGE
 *   - Price > MA200: edge -1.50% — bullish filter is a TRAP
 */
export function computeSignal(
  composite: number,
  bullWeight: number = 0.5,
  groups?: SignalGroup[],
  foreignNet7d?: number,
  stock?: Stock,
): SignalConfig {

  const avgScore = groups && groups.length > 0
    ? groups.reduce((s, g) => s + g.score, 0) / groups.length
    : composite;
  const effectiveScore = avgScore * bullWeight + composite * (1 - bullWeight);

  // Dynamic thresholds theo regime
  const regimeShift = bullWeight <= 0.3 ? 5 : bullWeight >= 0.65 ? -3 : 0;
  const T = {
    STRONG_BUY:  THRESHOLDS.STRONG_BUY  + regimeShift,
    BUY:         THRESHOLDS.BUY         + regimeShift,
    ACCUMULATE:  THRESHOLDS.ACCUMULATE  + regimeShift,
    HOLD:        THRESHOLDS.HOLD,
    REDUCE:      THRESHOLDS.REDUCE,
  };

  // ══════════════════════════════════════════════════════════════════════════
  // PRIORITY SIGNAL PATHS (ordered by edge strength from 493K backtest)
  // ══════════════════════════════════════════════════════════════════════════

  if (stock) {
    const rsi     = stock.rsi14 ?? 50;
    const adx     = stock.adx14 ?? 0;
    const trend   = stock.trend_short ?? 0;
    const p20d    = stock.price_change_20d ?? stock.change_20d ?? 0;
    const pma20   = stock.pct_from_ma20 ?? 0;
    const bbPct   = stock.bb_pct ?? 0.5;
    const atrPct  = stock.atr_pct ?? 3;

    // ── PATH 1: Panic Bottom — edge +4.26-5.19%, win 64-66% ────────────
    // Backtest: drop>10% from MA20 + RSI<30 → Sharpe 0.320 (BEST)
    if (pma20 < -10 && rsi < 30 && bullWeight > 0.2) {
      const conv: ConvictionLevel = pma20 < -15 && rsi < 25 ? 'HIGH' : 'MEDIUM';
      if (bullWeight >= 0.4) {
        return { ...SIGNAL_CONFIG['STRONG_BUY'], action: 'STRONG_BUY', conviction: conv };
      }
      return { ...SIGNAL_CONFIG['BUY'], action: 'BUY', conviction: 'LOW' };
    }

    // ── PATH 2: Deep Crash — edge +4.05%, win 61.4% ────────────────────
    if (p20d < -20 && rsi < 40 && bullWeight > 0.2) {
      const conv: ConvictionLevel = rsi < 35 ? 'HIGH' : 'MEDIUM';
      if (bullWeight >= 0.4) {
        return { ...SIGNAL_CONFIG['BUY'], action: 'BUY', conviction: conv };
      }
      return { ...SIGNAL_CONFIG['ACCUMULATE'], action: 'ACCUMULATE', conviction: 'LOW' };
    }

    // ── PATH 3: Super Combo — edge +3.27%, win 59.2% ───────────────────
    if (trend === 1 && adx > 25 && rsi < 35 && bullWeight > 0.25) {
      const conv: ConvictionLevel = adx > 35 && rsi < 30 ? 'HIGH' : 'MEDIUM';
      if (bullWeight >= 0.5) {
        return { ...SIGNAL_CONFIG['STRONG_BUY'], action: 'STRONG_BUY', conviction: conv };
      }
      return { ...SIGNAL_CONFIG['BUY'], action: 'BUY', conviction: 'LOW' };
    }

    // ── PATH 4: Crash -15% + RSI<40 — edge +3.32%, win 62% ─────────────
    if (p20d < -15 && rsi < 40 && bullWeight > 0.25) {
      return { ...SIGNAL_CONFIG['ACCUMULATE'], action: 'ACCUMULATE',
               conviction: rsi < 30 ? 'HIGH' : 'MEDIUM' };
    }

    // ── PATH 5: RSI Deep Oversold — edge +1.49%, win 52.9% ─────────────
    if (rsi < 30 && bullWeight > 0.25) {
      return { ...SIGNAL_CONFIG['ACCUMULATE'], action: 'ACCUMULATE',
               conviction: rsi < 25 ? 'HIGH' : 'MEDIUM' };
    }

    // ── PATH 6: BB Below Lower Band — win 58.6%, edge +1.11% ───────────
    if (bbPct < 0 && rsi < 45 && bullWeight > 0.3) {
      return { ...SIGNAL_CONFIG['ACCUMULATE'], action: 'ACCUMULATE', conviction: 'MEDIUM' };
    }

    // ── SELL PATHS ──────────────────────────────────────────────────────

    // RSI > 80: edge -0.34%, win 43.2%
    if (rsi > 80) {
      if (bullWeight <= 0.4) {
        return { ...SIGNAL_CONFIG['SELL'], action: 'SELL', conviction: 'HIGH' };
      }
      return { ...SIGNAL_CONFIG['REDUCE'], action: 'REDUCE', conviction: 'HIGH' };
    }

    // Strong momentum + overbought: no edge confirmed
    if (p20d > 15 && rsi > 65) {
      return { ...SIGNAL_CONFIG['REDUCE'], action: 'REDUCE', conviction: 'MEDIUM' };
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

  // ── v4: Low Volatility boost — ATR%<2% Sharpe 0.154 (best risk-adjusted) ─
  if (stock && action === 'HOLD' && (stock.atr_pct ?? 3) < 2 && effectiveScore >= 45) {
    action = 'ACCUMULATE';
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
