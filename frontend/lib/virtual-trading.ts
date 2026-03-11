/**
 * virtual-trading.ts — Virtual Trading Engine v2
 *
 * Features: Cash + Margin trading, Order types, Buying power, Fees, SL/TP auto
 * Storage: localStorage (no backend needed)
 * Prices: realtime from screener.json stocks array
 */

// ─── Types ───────────────────────────────────────────────────────────────────

export type OrderType = 'MARKET' | 'LIMIT' | 'STOP';
export type TradeStatus = 'OPEN' | 'CLOSED' | 'STOPPED' | 'TP_HIT';

export interface VirtualTrade {
  id: string;
  symbol: string;
  type: 'BUY' | 'SELL';
  order_type: OrderType;
  entry_price: number;
  limit_price?: number;
  quantity: number;
  stop_loss?: number;
  take_profit?: number;
  use_margin: boolean;
  margin_borrowed: number;
  entry_date: string;
  exit_date?: string;
  exit_price?: number;
  status: TradeStatus;
  strategy?: string;
  note?: string;
  fees: number;
}

export interface VirtualPortfolio {
  initial_capital: number;
  margin_enabled: boolean;
  margin_ratio: number;
  margin_interest_rate: number;
  fee_rate: number;
  trades: VirtualTrade[];
  created_at: string;
}

export interface PortfolioStats {
  total_value: number;
  cash: number;
  buying_power: number;
  margin_used: number;
  margin_available: number;
  positions_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  total_fees: number;
  open_count: number;
  closed_count: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  best_trade_pnl: number;
  worst_trade_pnl: number;
  profit_factor: number;
}

export interface PositionSummary {
  trade: VirtualTrade;
  current_price: number;
  market_value: number;
  cost_basis: number;
  pnl: number;
  pnl_pct: number;
  days_held: number;
  hit_sl: boolean;
  hit_tp: boolean;
  margin_pct: number;
  maintenance_call_price: number;
}

export interface BuyingPowerBreakdown {
  cash_balance: number;
  margin_available: number;
  total_buying_power: number;
  margin_used: number;
  leverage: number;
  equity: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const STORAGE_KEY = 'vns-virtual-portfolio-v2';
const DEFAULT_CAPITAL = 1_000_000_000;
const DEFAULT_FEE_RATE = 0.0015;
const DEFAULT_MARGIN_RATIO = 2.0;
const DEFAULT_MARGIN_RATE = 0.12;
const MAINTENANCE_MARGIN = 0.30;

function genId(): string { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
function daysBetween(d1: string, d2: string): number { return Math.max(0, Math.floor((new Date(d2).getTime() - new Date(d1).getTime()) / 86400000)); }

// ─── Portfolio CRUD ──────────────────────────────────────────────────────────

function createDefault(): VirtualPortfolio {
  return { initial_capital: DEFAULT_CAPITAL, margin_enabled: false, margin_ratio: DEFAULT_MARGIN_RATIO, margin_interest_rate: DEFAULT_MARGIN_RATE, fee_rate: DEFAULT_FEE_RATE, trades: [], created_at: new Date().toISOString() };
}

export function loadPortfolio(): VirtualPortfolio {
  if (typeof window === 'undefined') return createDefault();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (!p.fee_rate) p.fee_rate = DEFAULT_FEE_RATE;
      if (!p.margin_ratio) p.margin_ratio = 1.0;
      if (!p.margin_interest_rate) p.margin_interest_rate = DEFAULT_MARGIN_RATE;
      if (p.margin_enabled === undefined) p.margin_enabled = false;
      p.trades = (p.trades || []).map((t: any) => ({ ...t, order_type: t.order_type || 'MARKET', use_margin: t.use_margin || false, margin_borrowed: t.margin_borrowed || 0, fees: t.fees || 0 }));
      return p;
    }
  } catch { /* */ }
  return createDefault();
}

export function savePortfolio(p: VirtualPortfolio): void {
  if (typeof window === 'undefined') return;
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)); } catch { /* */ }
}

export function resetPortfolio(capital?: number): VirtualPortfolio {
  const p = createDefault(); if (capital) p.initial_capital = capital; savePortfolio(p); return p;
}

export function updateSettings(portfolio: VirtualPortfolio, settings: Partial<Pick<VirtualPortfolio, 'margin_enabled' | 'margin_ratio' | 'margin_interest_rate' | 'fee_rate'>>): VirtualPortfolio {
  const u = { ...portfolio, ...settings }; savePortfolio(u); return u;
}

// ─── Buying Power ────────────────────────────────────────────────────────────

export function getBuyingPower(portfolio: VirtualPortfolio, priceMap: Record<string, number>): BuyingPowerBreakdown {
  const open = portfolio.trades.filter(t => t.status === 'OPEN');
  const openCashUsed = open.reduce((s, t) => s + (t.entry_price * t.quantity * 1000) - t.margin_borrowed + t.fees, 0);
  const closedPnl = portfolio.trades.filter(t => t.status !== 'OPEN').reduce((s, t) => s + calcTradePnL(t, t.exit_price ?? t.entry_price).pnl, 0);
  const closedFees = portfolio.trades.filter(t => t.status !== 'OPEN').reduce((s, t) => s + t.fees, 0);
  const cash = portfolio.initial_capital - openCashUsed + closedPnl - closedFees;
  const posValue = open.reduce((s, t) => s + (priceMap[t.symbol] ?? t.entry_price) * t.quantity * 1000, 0);
  const marginUsed = open.reduce((s, t) => s + t.margin_borrowed, 0);
  const equity = cash + posValue - marginUsed;
  const maxMargin = portfolio.margin_enabled ? equity * (portfolio.margin_ratio - 1) : 0;
  const marginAvail = Math.max(0, maxMargin - marginUsed);
  return { cash_balance: cash, margin_available: marginAvail, total_buying_power: cash + marginAvail, margin_used: marginUsed, leverage: equity > 0 ? (cash + posValue) / equity : 1, equity };
}

// ─── Trade Ops ───────────────────────────────────────────────────────────────

export function openTrade(portfolio: VirtualPortfolio, params: { symbol: string; type: 'BUY' | 'SELL'; order_type: OrderType; price: number; limit_price?: number; quantity: number; stop_loss?: number; take_profit?: number; use_margin: boolean; strategy?: string; note?: string }, priceMap: Record<string, number>): { portfolio: VirtualPortfolio; error?: string } {
  const cost = params.price * params.quantity * 1000;
  const fees = cost * portfolio.fee_rate;
  const bp = getBuyingPower(portfolio, priceMap);
  let borrowed = 0;
  if (params.use_margin && portfolio.margin_enabled) {
    const need = cost + fees;
    if (need > bp.cash_balance) {
      borrowed = Math.min(need - bp.cash_balance, bp.margin_available);
      if (borrowed < need - bp.cash_balance) return { portfolio, error: `Vượt sức mua. Cần ${fmtVND(need)}, BP: ${fmtVND(bp.total_buying_power)}` };
    }
  } else if (cost + fees > bp.cash_balance) {
    return { portfolio, error: `Không đủ tiền. Cần ${fmtVND(cost + fees)}, có ${fmtVND(bp.cash_balance)}` };
  }
  const trade: VirtualTrade = { id: genId(), symbol: params.symbol, type: params.type, order_type: params.order_type, entry_price: params.price, limit_price: params.limit_price, quantity: params.quantity, stop_loss: params.stop_loss, take_profit: params.take_profit, use_margin: borrowed > 0, margin_borrowed: borrowed, entry_date: new Date().toISOString(), status: 'OPEN', strategy: params.strategy, note: params.note, fees };
  const u = { ...portfolio, trades: [...portfolio.trades, trade] }; savePortfolio(u); return { portfolio: u };
}

export function closeTrade(portfolio: VirtualPortfolio, tradeId: string, exitPrice: number, reason: 'MANUAL' | 'STOP_LOSS' | 'TAKE_PROFIT' = 'MANUAL'): VirtualPortfolio {
  const sm = { MANUAL: 'CLOSED' as const, STOP_LOSS: 'STOPPED' as const, TAKE_PROFIT: 'TP_HIT' as const };
  const u = { ...portfolio, trades: portfolio.trades.map(t => { if (t.id !== tradeId || t.status !== 'OPEN') return t; const ef = exitPrice * t.quantity * 1000 * portfolio.fee_rate; return { ...t, exit_price: exitPrice, exit_date: new Date().toISOString(), status: sm[reason], fees: t.fees + ef }; }) };
  savePortfolio(u); return u;
}

export function deleteTrade(portfolio: VirtualPortfolio, tradeId: string): VirtualPortfolio {
  const u = { ...portfolio, trades: portfolio.trades.filter(t => t.id !== tradeId) }; savePortfolio(u); return u;
}

// ─── P&L ─────────────────────────────────────────────────────────────────────

export function calcTradePnL(trade: VirtualTrade, currentPrice: number): { pnl: number; pnl_pct: number } {
  const ep = trade.exit_price ?? currentPrice;
  const cost = trade.entry_price * trade.quantity * 1000;
  const val = ep * trade.quantity * 1000;
  const raw = trade.type === 'BUY' ? val - cost : cost - val;
  const pnl = raw - trade.fees;
  return { pnl, pnl_pct: cost > 0 ? (pnl / cost) * 100 : 0 };
}

export function getPositions(portfolio: VirtualPortfolio, priceMap: Record<string, number>): PositionSummary[] {
  const now = new Date().toISOString();
  return portfolio.trades.filter(t => t.status === 'OPEN').map(t => {
    const cp = priceMap[t.symbol] ?? t.entry_price;
    const { pnl, pnl_pct } = calcTradePnL(t, cp);
    const cost = t.entry_price * t.quantity * 1000;
    const mPct = cost > 0 ? (t.margin_borrowed / cost) * 100 : 0;
    const mcp = t.use_margin && t.quantity > 0 ? t.entry_price * (1 - (1 - MAINTENANCE_MARGIN) * (cost / Math.max(1, cost - t.margin_borrowed))) : 0;
    return { trade: t, current_price: cp, market_value: cp * t.quantity * 1000, cost_basis: cost, pnl, pnl_pct, days_held: daysBetween(t.entry_date, now), hit_sl: t.stop_loss != null && cp <= t.stop_loss, hit_tp: t.take_profit != null && cp >= t.take_profit, margin_pct: mPct, maintenance_call_price: Math.max(0, mcp) };
  });
}

export function getPortfolioStats(portfolio: VirtualPortfolio, priceMap: Record<string, number>): PortfolioStats {
  const bp = getBuyingPower(portfolio, priceMap);
  const pos = getPositions(portfolio, priceMap);
  const closed = portfolio.trades.filter(t => t.status !== 'OPEN');
  const posV = pos.reduce((s, p) => s + p.market_value, 0);
  const tv = bp.cash_balance + posV;
  const tp = tv - portfolio.initial_capital;
  const tf = portfolio.trades.reduce((s, t) => s + t.fees, 0);
  const mu = pos.reduce((s, p) => s + p.trade.margin_borrowed, 0);
  let w = 0, l = 0, twp = 0, tlp = 0, twa = 0, tla = 0, best = -Infinity, worst = Infinity;
  closed.forEach(t => { const { pnl, pnl_pct } = calcTradePnL(t, t.exit_price ?? t.entry_price); if (pnl > 0) { w++; twp += pnl_pct; twa += pnl; } else { l++; tlp += pnl_pct; tla += Math.abs(pnl); } if (pnl > best) best = pnl; if (pnl < worst) worst = pnl; });
  return { total_value: tv, cash: bp.cash_balance, buying_power: bp.total_buying_power, margin_used: mu, margin_available: bp.margin_available, positions_value: posV, total_pnl: tp, total_pnl_pct: portfolio.initial_capital > 0 ? (tp / portfolio.initial_capital) * 100 : 0, total_fees: tf, open_count: pos.length, closed_count: closed.length, win_rate: closed.length > 0 ? (w / closed.length) * 100 : 0, avg_win_pct: w > 0 ? twp / w : 0, avg_loss_pct: l > 0 ? tlp / l : 0, best_trade_pnl: best === -Infinity ? 0 : best, worst_trade_pnl: worst === Infinity ? 0 : worst, profit_factor: tla > 0 ? twa / tla : twa > 0 ? Infinity : 0 };
}

export function checkStopLossTakeProfit(portfolio: VirtualPortfolio, priceMap: Record<string, number>): VirtualPortfolio {
  let ch = false;
  const trades = portfolio.trades.map(t => { if (t.status !== 'OPEN') return t; const cp = priceMap[t.symbol]; if (!cp) return t; if (t.stop_loss != null && cp <= t.stop_loss) { ch = true; return { ...t, exit_price: t.stop_loss, exit_date: new Date().toISOString(), status: 'STOPPED' as const, fees: t.fees + t.stop_loss * t.quantity * 1000 * portfolio.fee_rate }; } if (t.take_profit != null && cp >= t.take_profit) { ch = true; return { ...t, exit_price: t.take_profit, exit_date: new Date().toISOString(), status: 'TP_HIT' as const, fees: t.fees + t.take_profit * t.quantity * 1000 * portfolio.fee_rate }; } return t; });
  if (ch) { const u = { ...portfolio, trades }; savePortfolio(u); return u; }
  return portfolio;
}

export function fmtVND(v: number): string { if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(2) + ' tỷ'; if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'tr'; return new Intl.NumberFormat('vi-VN').format(Math.round(v)) + 'đ'; }
export function fmtPrice(v: number): string { return new Intl.NumberFormat('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v); }
