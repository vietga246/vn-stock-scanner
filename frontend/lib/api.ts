// API client để fetch data từ GitHub repo
// Data được cập nhật tự động bởi GitHub Actions

import type { 
  ScreenerResponse, 
  SectorsResponse, 
  PricesResponse, 
  SummaryResponse,
  AIAnalysisResponse,
  Stock 
} from './types';

const GITHUB_RAW_BASE = 'https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports';

// Cache config
const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes
const cache: Record<string, { data: any; timestamp: number }> = {};

async function fetchWithCache<T>(endpoint: string): Promise<T> {
  const url = `${GITHUB_RAW_BASE}/${endpoint}`;
  const now = Date.now();
  
  // Check cache
  if (cache[endpoint] && (now - cache[endpoint].timestamp) < CACHE_DURATION) {
    return cache[endpoint].data as T;
  }
  
  try {
    const response = await fetch(url, {
      next: { revalidate: 300 }, // ISR: revalidate every 5 minutes
      headers: {
        'Accept': 'application/json',
      }
    });
    
    if (!response.ok) {
      throw new Error(`Failed to fetch ${endpoint}: ${response.status}`);
    }
    
    const data = await response.json();
    
    // Update cache
    cache[endpoint] = { data, timestamp: now };
    
    return data as T;
  } catch (error) {
    console.error(`Error fetching ${endpoint}:`, error);
    
    // Return cached data if available (stale-while-revalidate)
    if (cache[endpoint]) {
      return cache[endpoint].data as T;
    }
    
    throw error;
  }
}

// ============ API Functions ============

export async function getScreener(): Promise<ScreenerResponse> {
  return fetchWithCache<ScreenerResponse>('screener.json');
}

export async function getSectors(): Promise<SectorsResponse> {
  return fetchWithCache<SectorsResponse>('sectors.json');
}

export async function getPrices(): Promise<PricesResponse> {
  return fetchWithCache<PricesResponse>('prices.json');
}

export async function getSummary(): Promise<SummaryResponse> {
  return fetchWithCache<SummaryResponse>('summary.json');
}

export async function getAIAnalysis(): Promise<AIAnalysisResponse | null> {
  try {
    return await fetchWithCache<AIAnalysisResponse>('ai_analysis.json');
  } catch {
    // AI analysis might not exist
    return null;
  }
}

// ============ Combined Data Fetcher ============

export interface DashboardData {
  stocks: Stock[];
  sectors: SectorsResponse['sectors'];
  rotationSignal?: SectorsResponse['rotation_signal'];
  summary?: SummaryResponse;
  aiAnalyses?: Record<string, any>;
  generatedAt: string;
}

export async function getDashboardData(): Promise<DashboardData> {
  const [screenerData, sectorsData, pricesData, aiData] = await Promise.all([
    getScreener(),
    getSectors().catch(() => null),
    getPrices().catch(() => null),
    getAIAnalysis().catch(() => null),
  ]);
  
  // Merge price history into stocks
  const stocks = screenerData.screener.map(stock => {
    const priceData = pricesData?.prices?.[stock.symbol];
    
    if (priceData) {
      return {
        ...stock,
        price_history: priceData.close?.slice(-30), // Last 30 days
        volume_history: priceData.volume?.slice(-30),
        dates: priceData.dates?.slice(-30),
        close: priceData.close?.[priceData.close.length - 1] || stock.close,
      };
    }
    
    return stock;
  });
  
  // Determine sector status from rotation signal
  const sectors = sectorsData?.sectors?.map(sector => {
    let status: 'accumulating' | 'distributing' | 'neutral' = 'neutral';
    
    if (sectorsData.rotation_signal) {
      if (sectorsData.rotation_signal.accumulating.includes(sector.name)) {
        status = 'accumulating';
      } else if (sectorsData.rotation_signal.distributing.includes(sector.name)) {
        status = 'distributing';
      }
    } else {
      // Fallback: determine by foreign flow
      status = sector.foreign_net_7d > 0 ? 'accumulating' : 
               sector.foreign_net_7d < 0 ? 'distributing' : 'neutral';
    }
    
    return { ...sector, status };
  }) || [];
  
  return {
    stocks,
    sectors,
    rotationSignal: sectorsData?.rotation_signal,
    aiAnalyses: aiData?.analyses,
    generatedAt: screenerData.generated_at,
  };
}

// ============ Utility Functions ============

export function formatPrice(price: number | undefined): string {
  if (!price) return '-';
  return new Intl.NumberFormat('vi-VN').format(price);
}

export function formatNumber(num: number | undefined, decimals = 1): string {
  if (num === undefined || num === null) return '-';
  if (Math.abs(num) >= 1e9) return (num / 1e9).toFixed(decimals) + 'T';
  if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(decimals) + 'M';
  if (Math.abs(num) >= 1e3) return (num / 1e3).toFixed(decimals) + 'K';
  return num.toFixed(decimals);
}

export function formatPercent(value: number | undefined): string {
  if (value === undefined || value === null) return '-';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

export function getTierColor(tier: string): string {
  const colors: Record<string, string> = {
    A: '#00ff88',
    B: '#00d4ff', 
    C: '#8b99a8',
    D: '#ffcc00',
    F: '#ff3366',
  };
  return colors[tier] || colors.C;
}

export function getScoreColor(score: number): string {
  if (score >= 70) return '#00ff88';
  if (score >= 55) return '#00d4ff';
  if (score >= 40) return '#ffcc00';
  return '#ff3366';
}

export function getRecommendation(stock: Stock): {
  text: string;
  color: string;
} {
  const score = stock.composite_score;
  
  if (score >= 75) return { text: 'STRONG BUY', color: '#00ff88' };
  if (score >= 65) return { text: 'BUY', color: '#00ff88' };
  if (score >= 55) return { text: 'HOLD', color: '#ffcc00' };
  if (score >= 45) return { text: 'SELL', color: '#ff3366' };
  return { text: 'STRONG SELL', color: '#ff3366' };
}
