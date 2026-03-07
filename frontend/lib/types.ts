// Types matching the backend data structure from GitHub repo
// https://github.com/vietga246/vn-stock-scanner/tree/main/data/exports

export interface Stock {
  symbol: string;
  name: string;
  industry: string;
  exchange?: string;
  
  // Scores (0-100)
  composite_score: number;
  fundamental_score: number;
  smart_money_score: number;
  momentum_score: number;
  technical_score: number;
  tier: 'A' | 'B' | 'C' | 'D' | 'F';
  rank: number;
  
  // Fundamentals
  roe?: number;
  roa?: number;
  pe?: number;
  pb?: number;
  revenue_growth?: number;
  net_margin?: number;
  debt_equity?: number;
  
  // Technical
  rsi14?: number;
  adx14?: number;
  trend_short?: number;  // 1 = up, 0 = sideways, -1 = down
  trend_medium?: number;
  trend_strength?: number;
  macd_signal?: number;
  fvg_bull?: boolean;
  fvg_bear?: boolean;
  pct_from_ma20?: number;
  pct_from_ma50?: number;
  vol_ratio?: number;
  atr14?: number;
  atr_pct?: number;
  bb_width?: number;
  macd_hist?: number;
  di_spread?: number;
  plus_di14?: number;
  minus_di14?: number;
  
  // Smart Money (billion VND)
  foreign_net_7d?: number;
  foreign_net_30d?: number;
  prop_net_7d?: number;
  
  // Price
  close?: number;
  price?: number;
  change_1d?: number;
  change_5d?: number;
  change_20d?: number;
  price_change_1d?: number;
  price_change_5d?: number;
  price_change_20d?: number;
  volume?: number;
  avg_volume_20d?: number;
  
  // Price history for sparkline (from prices.json)
  price_history?: number[];
  volume_history?: number[];
  dates?: string[];
  // Price board (from price_board.json)
  bid1_price?: number; bid1_volume?: number;
  bid2_price?: number; bid2_volume?: number;
  bid3_price?: number; bid3_volume?: number;
  ask1_price?: number; ask1_volume?: number;
  ask2_price?: number; ask2_volume?: number;
  ask3_price?: number; ask3_volume?: number;
  buy_pressure_pct?: number;
  foreign_buy_qty?: number;
  foreign_sell_qty?: number;
}

export interface ScreenerResponse {
  generated_at: string;
  total: number;
  screener: Stock[];
}

export interface Sector {
  name: string;
  symbol_count: number;
  avg_composite_score: number;
  foreign_net_7d: number;
  foreign_net_30d?: number;
  money_flow_rank: number;
  top_stocks: string[];
  change_1d?: number;
  change_5d?: number;
  status: 'accumulating' | 'distributing' | 'neutral';
}

export interface SectorsResponse {
  generated_at: string;
  sectors: Sector[];
  rotation_signal?: {
    accumulating: string[];
    distributing: string[];
    hot_sectors: string[];
  };
}

export interface PriceData {
  symbol: string;
  dates: string[];
  close: number[];
  volume: number[];
  high?: number[];
  low?: number[];
  open?: number[];
}

export interface PricesResponse {
  generated_at: string;
  period: string;
  prices: Record<string, PriceData>;
}

export interface SummaryResponse {
  generated_at: string;
  market: {
    vnindex: number;
    vnindex_change: number;
    vnindex_change_1d?: number;
    vnindex_change_5d?: number;
    vnindex_change_20d?: number;
    hnxindex?: number;
    upcom?: number;
  };
  top_gainers: Array<{ symbol: string; change: number }>;
  top_losers: Array<{ symbol: string; change: number }>;
  most_active: Array<{ symbol: string; volume?: number }>;
  foreign_buy: Array<{ symbol: string; net: number }>;
  foreign_sell: Array<{ symbol: string; net: number }>;
}

export interface PriceBoardStock {
  symbol: string;
  exchange?: string;
  organ_name?: string;
  match_price?: number;
  open_price?: number;
  highest_price?: number;
  lowest_price?: number;
  avg_price?: number;
  price_change?: number;
  price_change_pct?: number;
  total_traded_qty?: number;
  total_traded_value?: number;
  foreign_buy_qty?: number;
  foreign_sell_qty?: number;
  foreign_net_qty?: number;
  foreign_net_value_bn?: number;
  foreign_room?: number;
  bid1_price?: number;
  bid1_volume?: number;
  ask1_price?: number;
  ask1_volume?: number;
  buy_pressure_pct?: number;
}

export interface PriceBoardResponse {
  generated_at: string;
  snapshot_time: string | null;
  total_symbols: number;
  summary: {
    symbols_with_price: number;
    total_foreign_net_qty: number;
    total_foreign_net_value_bn: number;
    avg_buy_pressure_pct: number | null;
  };
  stocks: PriceBoardStock[];
}

// AI Analysis types (để match với frontend design)
export interface AIAnalysis {
  symbol: string;
  recommendation: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL';
  summary: string;
  highlights: AnalysisPoint[];
  risks: AnalysisPoint[];
  fundamental_view: string;
  technical_view: string;
  flow_view: string;
  target_price?: number;
  stop_loss?: number;
}

export interface AnalysisPoint {
  text: string;
  type: 'positive' | 'negative' | 'neutral' | 'warning';
}

export interface AIAnalysisResponse {
  generated_at: string;
  model: string;
  analyses: Record<string, AIAnalysis>;
}



// ─── Stock Detail Types (từ stocks.json) ─────────────────────────────────────

export interface IncomeRecord {
  symbol: string;
  year: number;
  quarter: number;
  revenue: number;
  gross_profit: number;
  operating_profit: number;
  ebit: number;
  net_profit: number;
  net_profit_parent: number;
  revenue_growth: number;
}

export interface BalanceRecord {
  symbol: string;
  year: number;
  quarter: number;
  total_assets: number;
  total_equity: number;
  total_debt: number;
  cash: number;
  short_term_debt: number;
  long_term_debt: number;
}

export interface CashflowRecord {
  symbol: string;
  year: number;
  quarter: number;
  cfo: number;
  cfi: number;
  cff: number;
  capex: number;
}

export interface RatioRecord {
  symbol: string;
  year: number;
  quarter: number;
  pe: number;
  pb: number;
  ps: number;
  ev_ebitda: number;
  roe: number;
  roa: number;
  roic: number;
  gross_margin: number;
  net_margin: number;
  debt_equity: number;
  current_ratio: number;
  quick_ratio: number;
}

export interface StockDetail {
  income: IncomeRecord[];
  balance: BalanceRecord[];
  cashflow: CashflowRecord[];
  ratio: RatioRecord[];
}

export interface StocksResponse {
  generated_at: string;
  total: number;
  details: Record<string, StockDetail>;
}

// ─── Desk Analysis — Prop Trading Style ─────────────────────────────────────

export type SignalStrength = 'STRONG' | 'MODERATE' | 'WEAK' | 'NEUTRAL' | 'NEGATIVE';
export type ConvictionLevel = 'HIGH' | 'MEDIUM' | 'LOW';
export type TradeAction = 'STRONG_BUY' | 'BUY' | 'ACCUMULATE' | 'HOLD' | 'REDUCE' | 'SELL' | 'AVOID';

export interface SignalGroup {
  id: string;
  label: string;           // "MACRO / REGIME", "STRUCTURE", etc.
  icon: string;            // emoji icon
  strength: SignalStrength;
  score: number;           // 0-100
  signals: SignalItem[];
}

export interface SignalItem {
  label: string;
  value: string;
  status: 'positive' | 'negative' | 'neutral' | 'warning';
  note?: string;
}

export interface TradeSetup {
  action: TradeAction;
  conviction: ConvictionLevel;
  entry_zone?: string;      // e.g. "12,400 – 12,800"
  stop_loss?: string;       // e.g. "11,900 (-4%)"
  target_1?: string;
  target_2?: string;
  risk_reward?: string;     // e.g. "1:2.5"
  time_horizon: string;     // "Swing 5-10 phiên" | "Position 1-3 tháng"
  invalidation?: string;    // "Đóng cửa dưới 11,900 và volume cao"
}

export interface DeskAnalysis {
  symbol: string;
  generated_at: string;
  headline: string;         // 1-line thesis
  narrative: string;        // 2-3 câu tổng hợp
  setup: TradeSetup;
  signal_groups: SignalGroup[];
  key_risks: string[];
  catalysts: string[];
}

// ─── ICT Signal Types ────────────────────────────────────────────────────────

export interface ICTSignal {
  symbol: string;
  ict_rank: number;
  alpha_score: number;
  ict_score: number;
  ict_confluence: number;
  setup_quality: 'A+' | 'A' | 'B' | 'C' | 'SKIP';
  actionable: boolean;
  bull_weight: number;

  // Structure
  structure: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  bos_bull: boolean;
  bos_bear: boolean;
  choch_bull: boolean;
  choch_bear: boolean;
  last_sh?: number;
  last_sl?: number;
  eq_high_count: number;
  eq_low_count: number;

  // Order Block
  ob_bull: boolean;
  ob_bull_top?: number;
  ob_bull_bottom?: number;
  ob_bull_age?: number;
  ob_bear?: boolean;
  ob_bear_top?: number;
  ob_bear_bottom?: number;
  ob_price_at: boolean;
  ob_mitigated: boolean;

  // Liquidity Sweep
  sweep_bull: boolean;
  stop_hunt_bull: boolean;
  sweep_price?: number;
  sweep_age?: number;

  // Volume / Accumulation
  accumulation_score: number;
  distribution_score: number;
  vol_spike: number;
  vol_trend: 'increasing' | 'decreasing' | 'flat';
  wyckoff_spring: boolean;
  nr7: boolean;
  breakout_imminent: boolean;

  // Institutional Flow
  inst_flow_score: number;
  flow_direction: 'in' | 'out' | 'neutral';
  smart_money: boolean;
  buy_pressure_pct?: number;
  flow_trend: string;

  // Pass-through from screener
  composite_score: number;
  industry: string;
  tier: string;
  rsi14?: number;
  adx14?: number;
  fvg_bull?: boolean;
  trend_strength?: number;
  price_change_1d?: number;
  price_change_5d?: number;
  foreign_net_7d?: number;

  // Signals
  top_signals: string[];
  signal_breakdown: Record<string, number>;
}

export interface ICTRegime {
  regime: 'BULL' | 'BEAR' | 'RANGE' | 'TRANSITION' | 'UNKNOWN';
  regime_strength: number;
  bull_weight: number;
  composite_score: number;
  vnindex?: number;
  vnindex_change_1d?: number;
  vnindex_change_5d?: number;
  vnindex_change_20d?: number;
  breadth_advance_pct?: number;
  bull_sectors?: number;
  bear_sectors?: number;
  foreign_net_total_bn?: number;
  components?: {
    market_breadth?: {
      advance?: number;
      decline?: number;
      total?: number;
      advance_pct?: number;
      score?: number;
      signal?: string;
    };
    vnindex_momentum?: { score?: number; signal?: string; detail?: string };
    sector_breadth?: { score?: number; bull_sectors?: number; bear_sectors?: number; total_sectors?: number };
    foreign_flow?: { score?: number; net_total_bn?: number; signal?: string };
  };
}

export interface ICTMarketStats {
  total_symbols: number;
  bullish_structure: number;
  bearish_structure: number;
  bullish_pct: number;
  bos_bull: number;
  bos_bear: number;
  choch_bull: number;
  accumulating: number;
  wyckoff_spring: number;
  flow_in: number;
  smart_money_conf: number;
}

export interface ICTSignalsResponse {
  generated_at: string;
  elapsed_seconds: number;
  total_symbols: number;
  actionable_count: number;
  regime: ICTRegime;
  sector_rotation: {
    leading: string[];
    lagging: string[];
    rotating_in: string[];
    rotating_out: string[];
    accumulating: string[];
    distributing: string[];
    hot_sectors: string[];
    breakout_candidate: string[];
  };
  market_stats: ICTMarketStats;
  quality_distribution: Record<string, number>;
  signals: ICTSignal[];
}
