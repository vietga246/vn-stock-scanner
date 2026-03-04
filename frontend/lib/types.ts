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
  trend_short?: number;  // 1 = up, 0 = sideways, -1 = down
  trend_medium?: number;
  macd_signal?: number;
  
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
  volume?: number;
  avg_volume_20d?: number;
  
  // Price history for sparkline (from prices.json)
  price_history?: number[];
  volume_history?: number[];
  dates?: string[];
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
    hnxindex?: number;
    upcom?: number;
  };
  top_gainers: Stock[];
  top_losers: Stock[];
  most_active: Stock[];
  foreign_buy: Stock[];
  foreign_sell: Stock[];
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
