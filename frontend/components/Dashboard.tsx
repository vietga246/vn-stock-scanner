'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import { Search, Star, BarChart3, X } from 'lucide-react';
import type { Stock, Sector, AIAnalysis, ICTSignal, ICTSignalsResponse, SummaryResponse, PriceBoardResponse } from '@/lib/types';
import { getDashboardData, getSummary, loadPrices, getPriceBoard, formatPrice, formatPercent, getScoreColor, getTierColor, getICTSignals } from '@/lib/api';
import { getStockSignal } from '@/lib/signals';
import IndustryFlow from './IndustryFlow';
import ICTDashboard from './ICTDashboard';
import MarketBreadth from './MarketBreadth';
import StockModal from './StockModal';
import Sparkline from './Sparkline';

const ITEMS_PER_PAGE = 20;

// ============ Module-level sub-components (P3 fix) ============

function ScoreBadge({ value }: { value: number }) {
  const color = getScoreColor(value);
  return (
    <span
      className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
      style={{
        background: `${color}15`,
        color,
        border: `1px solid ${color}40`,
        boxShadow: `0 0 8px ${color}30`,
      }}
    >
      {value.toFixed(1)}
    </span>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const color = getTierColor(tier);
  return (
    <span
      className="ml-1.5 px-1.5 py-0.5 rounded text-[8px] font-bold"
      style={{ background: `${color}20`, color, border: `1px solid ${color}30` }}
    >
      {tier}
    </span>
  );
}

function PriceChange({ value }: { value?: number }) {
  if (value === undefined || value === null || Math.abs(value) < 0.01) {
    return (
      <span className="font-mono text-[10px]" style={{ color: '#2a3642' }}>
        —
      </span>
    );
  }
  const up = value >= 0;
  return (
    <span
      className="font-mono text-[10px] font-medium"
      style={{
        color: up ? '#00ff88' : '#ff3366',
        textShadow: `0 0 6px ${up ? 'rgba(0,255,136,0.3)' : 'rgba(255,51,102,0.3)'}`,
      }}
    >
      {formatPercent(value)}
    </span>
  );
}

function SignalBadge({ stock, ict }: { stock: Stock; ict?: import('@/lib/types').ICTSignal }) {
  const sig = getStockSignal(stock, ict);
  const convColor = sig.conviction === 'HIGH' ? '#00ff88' : sig.conviction === 'MEDIUM' ? '#ffcc00' : '#8b99a8';
  return (
    <span className="strat-tip-wrap">
      <span
        className="px-1.5 py-0.5 rounded font-bold text-[9px] tracking-wide whitespace-nowrap cursor-help"
        style={{ color: sig.color, background: sig.bg, border: `1px solid ${sig.border}`, boxShadow: `0 0 8px ${sig.color}20` }}
      >
        {sig.label}
      </span>
      {sig.reason && (
        <div className="strat-tip" style={{ width: 260 }}>
          <div style={{ position: 'absolute', bottom: -5, left: '50%', transform: 'translateX(-50%) rotate(45deg)', width: 10, height: 10, background: '#0f1519', borderRight: '1px solid #2a3642', borderBottom: '1px solid #2a3642' }} />
          <div style={{ padding: '10px 12px 8px', borderBottom: '1px solid #1e2832', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: sig.color }}>{sig.label}</span>
            <span style={{ fontSize: 9, fontWeight: 700, color: convColor, padding: '2px 6px', borderRadius: 4, background: `${convColor}15`, border: `1px solid ${convColor}30` }}>
              {sig.conviction}
            </span>
          </div>
          <div style={{ padding: '8px 12px 10px' }}>
            <p style={{ fontSize: 10.5, color: '#b8c8d8', lineHeight: 1.65, margin: 0 }}>{sig.reason}</p>
          </div>
        </div>
      )}
    </span>
  );
}

// Type-safe sort keys (Q4 fix)
type SortableKey = 'rank' | 'close' | 'change_1d' | 'change_5d' | 'change_20d' | 'composite_score' | 'foreign_net_7d' | 'adx14' | 'rsi14';

function getSortValue(stock: Stock, key: SortableKey): number {
  const v = stock[key as keyof Stock];
  return (typeof v === 'number' ? v : 0);
}

// ── Strategy detection — single source of truth ──────────────────────────
// Used by: filter logic, column render, badge display
type StrategyKey = 'panic' | 'crash' | 'combo' | 'os_deep' | 'bb_below' | 'dip' | 'os' | 'pull' | 'ob_deep' | 'ob' | 'hot' | 'none';

const STRATEGY_DEFS: Record<StrategyKey, { label: string; name: string; type: 'buy'|'sell'|'warn'|'none'; color: string; bg: string; border: string; def: string; edge: string; win: string; n: string; conf: number; confLabel: string }> = {
  panic:   { label: 'PANIC', name: 'Panic Bottom',        type: 'buy',  color: '#00ff88', bg: '#00ff8818', border: '#00ff8840', def: 'Bán tháo hoảng loạn — giá xa MA20 bất thường + RSI oversold cực mạnh. Setup #1 trên VNSTOCK.',        edge: '+4.26%', win: '65.8%', n: '6,585',  conf: 92, confLabel: 'Rất cao' },
  crash:   { label: 'CRASH', name: 'Crash Recovery',      type: 'buy',  color: '#00ff88', bg: '#00ff8815', border: '#00ff8835', def: 'Crash mạnh + RSI thấp → xác suất phục hồi cao. VNSTOCK mean-revert: crash càng sâu, bounce càng lớn.', edge: '+3.32%', win: '62.0%', n: '14,300', conf: 88, confLabel: 'Rất cao' },
  combo:   { label: 'COMBO', name: 'Super Combo',         type: 'buy',  color: '#00d4ff', bg: '#00d4ff18', border: '#00d4ff40', def: 'Trend tăng + ADX xác nhận + RSI pullback oversold — vào lệnh lý tưởng trong uptrend. Sharpe 0.381.',  edge: '+3.27%', win: '59.2%', n: '326',    conf: 82, confLabel: 'Cao' },
  os_deep: { label: 'OS',    name: 'RSI Deep Oversold',   type: 'buy',  color: '#00ff88', bg: '#00ff8812', border: '#00ff8830', def: 'RSI < 30: áp lực bán kiệt sức, lực cầu sắp quay lại. Mẫu lớn nhất nhóm oversold.',                    edge: '+1.49%', win: '52.9%', n: '21,083', conf: 78, confLabel: 'Cao' },
  bb_below:{ label: 'BB↓',   name: 'BB Below Lower',     type: 'buy',  color: '#a78bfa', bg: '#a78bfa12', border: '#a78bfa30', def: 'Giá phá dưới dải Bollinger dưới — xu hướng quay về TB. TỶ LỆ THẮNG CAO NHẤT toàn dataset.',           edge: '+1.11%', win: '58.6%', n: '20,796', conf: 80, confLabel: 'Cao' },
  dip:     { label: 'DIP',   name: 'Crash Dip -10%',     type: 'buy',  color: '#ffcc00', bg: '#ffcc0012', border: '#ffcc0030', def: 'Điều chỉnh đáng kể (>10%). Chưa panic nhưng đã có edge bounce dương trên VNSTOCK.',                    edge: '+1.76%', win: '57.4%', n: '40,312', conf: 75, confLabel: 'Khá cao' },
  os:      { label: 'OS',    name: 'RSI Oversold',        type: 'buy',  color: '#00ff88', bg: '#00ff8808', border: '#00ff8825', def: 'RSI < 35: oversold nhẹ. Edge dương có ý nghĩa nhưng thấp hơn RSI<30.',                                 edge: '+1.00%', win: '53.7%', n: '40,707', conf: 68, confLabel: 'Trung bình' },
  pull:    { label: 'PULL',  name: 'Pullback in Uptrend', type: 'buy',  color: '#00d4ff', bg: '#00d4ff08', border: '#00d4ff25', def: 'Stoch oversold trong uptrend trung hạn — mua pullback tốt hơn mua breakout trên VNSTOCK.',              edge: '+0.52%', win: '53.8%', n: '40,277', conf: 62, confLabel: 'Trung bình' },
  ob_deep: { label: 'OB!',   name: 'Deep Overbought',    type: 'sell', color: '#ff3366', bg: '#ff336618', border: '#ff336640', def: 'RSI > 80: overbought cực. Xác suất giảm 20 phiên cao hơn TB. Nên chốt lời.',                           edge: '-0.34%', win: '43.2%', n: '11,968', conf: 72, confLabel: 'Khá cao' },
  ob:      { label: 'OB',    name: 'Overbought',         type: 'warn', color: '#ff9500', bg: '#ff950010', border: '#ff950030', def: 'Edge gần 0 — không nên mua đuổi. Theo dõi thêm.',                                                       edge: '+0.18%', win: '47.6%', n: '38,510', conf: 55, confLabel: 'Trung bình' },
  hot:     { label: 'HOT',   name: 'Momentum quá nóng',  type: 'warn', color: '#ff9500', bg: '#ff950008', border: '#ff950025', def: 'Backtest 493K obs: momentum >15% KHÔNG có edge trên VNSTOCK. Tránh mua đuổi.',                           edge: '+0.06%', win: '46.3%', n: '37,580', conf: 45, confLabel: 'Thấp' },
  none:    { label: '–',     name: 'Không có tín hiệu',  type: 'none', color: '#2a3642', bg: 'transparent', border: 'transparent', def: '',                                                                                                    edge: '',       win: '',      n: '',       conf: 0,  confLabel: '' },
};

function getStockStrategy(s: Stock): StrategyKey {
  const rsi = s.rsi14 ?? 50, adx = s.adx14 ?? 0, trend = s.trend_short ?? 0;
  const trendMed = s.trend_medium ?? 0, p20d = s.price_change_20d ?? s.change_20d ?? 0;
  const pma20 = s.pct_from_ma20 ?? 0, bbWidth = s.bb_width ?? 15, stochK = s.stoch_k ?? 50;

  if (pma20 < -10 && rsi < 30) return 'panic';
  if (p20d < -15 && rsi < 40) return 'crash';
  if (trend === 1 && adx > 25 && rsi < 35) return 'combo';
  if (rsi < 30) return 'os_deep';
  if (pma20 < -(bbWidth / 2)) return 'bb_below';
  if (p20d < -10) return 'dip';
  if (rsi < 35) return 'os';
  if (stochK < 20 && trendMed === 1) return 'pull';
  if (rsi > 80) return 'ob_deep';
  if (rsi > 70) return 'ob';
  if (p20d > 15) return 'hot';
  return 'none';
}

export default function Dashboard() {
  // Data state
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [aiAnalyses, setAiAnalyses] = useState<Record<string, AIAnalysis>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string>('');
  const [vnindex, setVnindex] = useState<{ value: number; change: number } | null>(null);
  const [ictMap, setIctMap] = useState<Record<string, ICTSignal>>({});
  const [summaryData, setSummaryData] = useState<SummaryResponse | null>(null);
  const [ictData, setIctData] = useState<ICTSignalsResponse | null>(null);
  const [priceBoardData, setPriceBoardData] = useState<PriceBoardResponse | null>(null);

  // UI state
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);

  // Merge bid/ask + buy_pressure từ price_board vào stock object
  const withPriceBoard = (stock: Stock): Stock => {
    if (!priceBoardData?.stocks) return stock;
    const pb = priceBoardData.stocks.find((p: any) => p.symbol === stock.symbol);
    if (!pb) return stock;
    return {
      ...stock,
      bid1_price: pb.bid1_price, bid1_volume: pb.bid1_volume,
      bid2_price: pb.bid2_price, bid2_volume: pb.bid2_volume,
      bid3_price: pb.bid3_price, bid3_volume: pb.bid3_volume,
      ask1_price: pb.ask1_price, ask1_volume: pb.ask1_volume,
      ask2_price: pb.ask2_price, ask2_volume: pb.ask2_volume,
      ask3_price: pb.ask3_price, ask3_volume: pb.ask3_volume,
      buy_pressure_pct: pb.buy_pressure_pct,
      foreign_buy_qty: pb.foreign_buy_qty,
      foreign_sell_qty: pb.foreign_sell_qty,
    };
  };
  const [searchQuery, setSearchQuery] = useState('');
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [industryFilter, setIndustryFilter] = useState<string | null>(null);
  const [strategyFilter, setStrategyFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<SortableKey>('rank');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);
  const [activeTab, setActiveTab] = useState<'screener' | 'ict'>('screener');

  // P5: Watchlist persisted to localStorage
  const [watchlist, setWatchlist] = useState<Set<string>>(() => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem('vns-watchlist');
        if (saved) return new Set(JSON.parse(saved));
      } catch { /* ignore */ }
    }
    return new Set();
  });

  // Persist watchlist changes
  useEffect(() => {
    try {
      localStorage.setItem('vns-watchlist', JSON.stringify(Array.from(watchlist)));
    } catch { /* ignore */ }
  }, [watchlist]);

  // Fetch data (P6: lazy-load prices separately)
  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const [data, summary] = await Promise.all([
          getDashboardData(),
          getSummary().catch(() => null),
        ]);
        setStocks(data.stocks);
        setSectors(data.sectors);
        setAiAnalyses(data.aiAnalyses || {});
        setGeneratedAt(data.generatedAt);
        if (summary) {
          setSummaryData(summary);
          if (summary.market) {
            setVnindex({
              value: summary.market.vnindex,
              change: summary.market.vnindex_change,
            });
          }
        }
        setError(null);

        // P6: Lazy-load prices after initial render
        loadPrices(data.stocks).then((stocksWithPrices) => {
          setStocks(stocksWithPrices);
        });

        // Lazy-load ICT signals
        getICTSignals()
          .then((ict: ICTSignalsResponse) => {
            setIctData(ict);
            if (ict?.signals) {
              const map: Record<string, ICTSignal> = {};
              ict.signals.forEach((s) => { map[s.symbol] = s; });
              setIctMap(map);
            }
          })
          .catch(() => { /* ICT signals optional */ });

        // Lazy-load price board for most_active + market breadth
        getPriceBoard()
          .then((pb: PriceBoardResponse) => {
            setPriceBoardData(pb);
          })
          .catch(() => { /* price board optional */ });

      } catch (err) {
        console.error('Failed to fetch data:', err);
        setError('Không thể tải dữ liệu. Vui lòng thử lại sau.');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  // Filter and sort stocks (Q4: type-safe sort)
  const filteredStocks = useMemo(() => {
    let result = [...stocks];

    // Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          (s.symbol && s.symbol.toLowerCase().includes(q)) ||
          (s.name && s.name.toLowerCase().includes(q)) ||
          (s.industry && s.industry.toLowerCase().includes(q))
      );
    }

    // Tier filter
    if (tierFilter !== 'all') {
      result = result.filter((s) => s.tier === tierFilter);
    }

    // Industry filter
    if (industryFilter) {
      result = result.filter((s) => s.industry === industryFilter);
    }

    // Strategy filter
    if (strategyFilter !== 'all') {
      if (strategyFilter === 'buy') {
        result = result.filter((s) => { const k = getStockStrategy(s); return STRATEGY_DEFS[k].type === 'buy'; });
      } else if (strategyFilter === 'sell') {
        result = result.filter((s) => { const k = getStockStrategy(s); return STRATEGY_DEFS[k].type === 'sell' || STRATEGY_DEFS[k].type === 'warn'; });
      } else {
        result = result.filter((s) => getStockStrategy(s) === strategyFilter);
      }
    }

    // Sort (type-safe)
    result.sort((a, b) => {
      const aVal = getSortValue(a, sortBy);
      const bVal = getSortValue(b, sortBy);
      return sortOrder === 'desc' ? bVal - aVal : aVal - bVal;
    });

    return result;
  }, [stocks, searchQuery, tierFilter, industryFilter, strategyFilter, sortBy, sortOrder]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [searchQuery, tierFilter, industryFilter, strategyFilter]);

  // Pagination
  const totalPages = Math.ceil(filteredStocks.length / ITEMS_PER_PAGE);
  const paginatedStocks = filteredStocks.slice((page - 1) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE);

  // Sort handler
  const handleSort = useCallback((field: SortableKey) => {
    setSortBy((prev) => {
      if (prev === field) {
        setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
        return field;
      }
      setSortOrder(field === 'rank' ? 'asc' : 'desc');
      return field;
    });
  }, []);

  // Toggle watchlist
  const toggleWatchlist = useCallback((symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setWatchlist((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) {
        next.delete(symbol);
      } else {
        next.add(symbol);
      }
      return next;
    });
  }, []);

  // Get sector status for selected stock
  const getStockSectorStatus = (stock: Stock) => {
    const sector = sectors.find((s) => s.name === stock.industry);
    return sector?.status;
  };

  // Pagination component (moved out of render, now uses closure)
  const renderPagination = () => {
    if (totalPages <= 1) return null;

    const getPageNumbers = () => {
      const pages: number[] = [];
      const maxVisible = 5;
      let start = Math.max(1, page - Math.floor(maxVisible / 2));
      const end = Math.min(totalPages, start + maxVisible - 1);
      if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);
      for (let i = start; i <= end; i++) pages.push(i);
      return pages;
    };

    return (
      <div className="flex items-center justify-center gap-1 mt-3">
        <button onClick={() => setPage(1)} disabled={page === 1} className="pagination-btn" data-active={page === 1 ? undefined : 'false'}>
          ««
        </button>
        <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} className="pagination-btn">
          «
        </button>
        {getPageNumbers().map((p) => (
          <button key={p} onClick={() => setPage(p)} className="pagination-btn" data-current={p === page ? '' : undefined}>
            {p}
          </button>
        ))}
        <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages} className="pagination-btn">
          »
        </button>
        <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="pagination-btn">
          »»
        </button>
      </div>
    );
  };

  if (loading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: '#05080a', color: '#e8edf2' }}
      >
        <div className="text-center">
          <div className="w-12 h-12 border-2 border-t-transparent rounded-full animate-spin mx-auto mb-4" style={{ borderColor: '#00d4ff', borderTopColor: 'transparent' }} />
          <p className="text-sm" style={{ color: '#8b99a8' }}>Đang tải dữ liệu...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: '#05080a', color: '#e8edf2' }}
      >
        <div className="text-center">
          <p className="text-red-400 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg"
            style={{ background: '#00d4ff20', color: '#00d4ff', border: '1px solid #00d4ff40' }}
          >
            Thử lại
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen text-sm"
      style={{
        background: '#05080a',
        color: '#e8edf2',
        fontFamily: "'Space Grotesk', system-ui, sans-serif",
      }}
    >
      {/* Header */}
      <header
        className="sticky top-0 z-40 p-3"
        style={{
          background: 'linear-gradient(180deg, #0a0f14 0%, #0a0f14ee 100%)',
          backdropFilter: 'blur(10px)',
          borderBottom: '1px solid #1e2832',
        }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{
                background: 'linear-gradient(135deg, #00d4ff20 0%, #a855f720 100%)',
                border: '1px solid #00d4ff40',
                boxShadow: '0 0 15px rgba(0,212,255,0.2)',
              }}
            >
              <BarChart3 size={16} color="#00d4ff" />
            </div>
            <div>
              <div className="font-bold text-sm tracking-wide">VN SCANNER</div>
              <div className="text-[9px]" style={{ color: '#4a5a6a', letterSpacing: '1px' }}>
                MARKET INTELLIGENCE
              </div>
            </div>
          </div>

          {/* Search */}
          <div className="flex-1 max-w-[280px]">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#4a5a6a' }} />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Tìm mã CK, tên công ty, ngành..."
                className="search-input w-full rounded-lg py-2.5 pl-10 pr-8 text-xs transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  style={{ color: '#4a5a6a' }}
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          {/* Tab switcher */}
          <div className="flex items-center gap-1" style={{ background: '#0f1519', border: '1px solid #1e2832', borderRadius: 8, padding: 3 }}>
            {([
              { key: 'screener', label: 'SCREENER' },
              { key: 'ict',      label: '🧠 ICT' },
            ] as { key: 'screener' | 'ict'; label: string }[]).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className="px-3 py-1 rounded text-[10px] font-bold transition-all"
                style={{
                  background: activeTab === key ? (key === 'ict' ? '#a78bfa25' : '#00d4ff15') : 'transparent',
                  color: activeTab === key ? (key === 'ict' ? '#a78bfa' : '#00d4ff') : '#4a5a6a',
                  border: activeTab === key ? `1px solid ${key === 'ict' ? '#a78bfa40' : '#00d4ff30'}` : '1px solid transparent',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Live indicator */}
          <div
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md"
            style={{ background: '#00ff8810', border: '1px solid #00ff8830' }}
          >
            <div
              className="w-1.5 h-1.5 rounded-full animate-pulse"
              style={{ background: '#00ff88', boxShadow: '0 0 8px #00ff88' }}
            />
            <span className="text-[10px] font-semibold" style={{ color: '#00ff88', letterSpacing: '0.5px' }}>
              LIVE
            </span>
          </div>
        </div>
      </header>

      {/* Market Breadth Panel */}
      <div className="px-3 pt-3">
        <MarketBreadth
          summary={summaryData}
          ictData={ictData}
          priceBoard={priceBoardData}
          onSymbolClick={(symbol) => {
            const stock = stocks.find((s) => s.symbol === symbol);
            if (stock) setSelectedStock(withPriceBoard(stock));
          }}
        />
      </div>

      {/* Filters */}
      <div className="p-2.5 flex gap-2 items-center flex-wrap" style={{ borderBottom: '1px solid #1e2832' }}>
        {['all', 'A', 'B', 'C', 'D', 'F'].map((t) => (
          <button
            key={t}
            onClick={() => setTierFilter(t)}
            className="tier-filter-btn"
            data-active={tierFilter === t ? '' : undefined}
          >
            {t === 'all' ? 'ALL' : `TIER ${t}`}
          </button>
        ))}

        {/* Divider */}
        <div style={{ width: 1, height: 20, background: '#1e2832', margin: '0 4px' }} />

        {/* Strategy filter */}
        {([
          { key: 'all',   label: 'ALL',     color: '#8b99a8' },
          { key: 'buy',   label: '🟢 MUA',  color: '#00ff88' },
          { key: 'sell',  label: '🔴 BÁN',  color: '#ff3366' },
          { key: 'panic', label: 'PANIC',   color: '#00ff88' },
          { key: 'crash', label: 'CRASH',   color: '#00ff88' },
          { key: 'combo', label: 'COMBO',   color: '#00d4ff' },
          { key: 'os_deep', label: 'OS',    color: '#00ff88' },
          { key: 'bb_below', label: 'BB↓',  color: '#a78bfa' },
          { key: 'dip',   label: 'DIP',     color: '#ffcc00' },
          { key: 'pull',  label: 'PULL',    color: '#00d4ff' },
          { key: 'ob_deep', label: 'OB!',   color: '#ff3366' },
          { key: 'hot',   label: 'HOT',     color: '#ff9500' },
        ] as { key: string; label: string; color: string }[]).map(({ key, label, color }) => {
          const isActive = strategyFilter === key;
          return (
            <button
              key={key}
              onClick={() => setStrategyFilter(key)}
              className="px-2 py-1 rounded text-[9px] font-bold transition-all"
              style={{
                background: isActive ? `${color}18` : 'transparent',
                color: isActive ? color : '#4a5a6a',
                border: isActive ? `1px solid ${color}40` : '1px solid transparent',
                letterSpacing: '0.3px',
              }}
            >
              {label}
            </button>
          );
        })}

        {/* Active strategy filter tag */}
        {strategyFilter !== 'all' && (
          <div
            className="flex items-center gap-1.5 ml-1 px-2 py-1 rounded-md"
            style={{ background: '#a78bfa12', border: '1px solid #a78bfa30' }}
          >
            <span className="text-[9px] font-semibold" style={{ color: '#a78bfa' }}>
              Strategy: {STRATEGY_DEFS[strategyFilter as StrategyKey]?.name || (strategyFilter === 'buy' ? 'Tất cả MUA' : 'Tất cả BÁN')}
            </span>
            <X
              size={10}
              color="#a78bfa"
              className="cursor-pointer"
              onClick={() => setStrategyFilter('all')}
            />
          </div>
        )}

        {industryFilter && (
          <div
            className="flex items-center gap-1.5 ml-2 px-2.5 py-1.5 rounded-md"
            style={{ background: '#00d4ff15', border: '1px solid #00d4ff40' }}
          >
            <span className="text-[10px] font-medium" style={{ color: '#00d4ff' }}>{industryFilter}</span>
            <X
              size={10}
              color="#00d4ff"
              className="cursor-pointer"
              onClick={() => setIndustryFilter(null)}
            />
          </div>
        )}
        <div className="ml-auto flex items-center gap-3">
          {searchQuery && (
            <span className="text-[10px]" style={{ color: '#4a5a6a' }}>
              Tìm thấy <span style={{ color: '#00d4ff' }}>{filteredStocks.length}</span> kết quả
            </span>
          )}
          <span className="text-[10px]" style={{ color: '#4a5a6a' }}>
            <span style={{ color: '#00d4ff' }}>{stocks.length}</span> cổ phiếu
          </span>
          {generatedAt && (
            <span className="text-[10px] font-mono" style={{ color: '#4a5a6a' }}>
              Cập nhật: <span style={{ color: '#8b99a8' }}>{new Date(generatedAt).toLocaleDateString('vi-VN')}</span>
            </span>
          )}
        </div>
      </div>

      {/* Main Content */}
      {activeTab === 'ict' ? (
        <div className="p-3">
          <ICTDashboard />
        </div>
      ) : (
      <div className="flex gap-3 p-3">
        {/* Industry Flow Panel */}
        <div className="w-[260px] flex-shrink-0">
          <IndustryFlow
            sectors={sectors}
            onIndustryClick={(ind) => setIndustryFilter(industryFilter === ind ? null : ind)}
            activeIndustry={industryFilter}
          />
        </div>

        {/* Stock Table */}
        <main className="flex-1 min-w-0">
          <div
            className="rounded-xl overflow-hidden"
            style={{
              background: 'linear-gradient(180deg, #0f1519 0%, #0a0f14 100%)',
              border: '1px solid #1e2832',
              boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
            }}
          >
            <table className="w-full">
              <thead>
                <tr style={{ background: '#0a0f14' }}>
                  <th className="w-7 p-2"></th>
                  <th onClick={() => handleSort('rank')} className="p-2 text-center text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>#</th>
                  <th className="p-2 text-left text-[9px] font-medium" style={{ color: '#4a5a6a' }}>NAME</th>
                  <th onClick={() => handleSort('close')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>PRICE</th>
                  <th onClick={() => handleSort('change_1d')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>1D</th>
                  <th onClick={() => handleSort('change_5d')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>5D</th>
                  <th onClick={() => handleSort('change_20d')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>20D</th>
                  <th onClick={() => handleSort('composite_score')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>SCORE</th>
                  <th className="p-2 text-center text-[9px] font-medium" style={{ color: '#4a5a6a' }}>SIGNAL</th>
                  <th onClick={() => handleSort('foreign_net_7d')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>NN 7D</th>
                  <th onClick={() => handleSort('adx14')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>ADX</th>
                  <th onClick={() => handleSort('rsi14')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>RSI</th>
                  <th className="p-2 text-center text-[9px] font-medium" style={{ color: '#4a5a6a' }}>STRATEGY</th>
                  <th className="p-2 text-right text-[9px] font-medium w-[100px]" style={{ color: '#4a5a6a' }}>30D</th>
                </tr>
              </thead>
              <tbody>
                {paginatedStocks.length === 0 ? (
                  <tr>
                    <td colSpan={14} className="p-8 text-center">
                      <div style={{ color: '#4a5a6a' }}>
                        <Search size={32} className="mx-auto mb-2 opacity-50" />
                        <p className="text-sm">Không tìm thấy kết quả</p>
                        <p className="text-[11px] mt-1">Thử tìm với từ khóa khác</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginatedStocks.map((s) => (
                    <tr
                      key={s.symbol}
                      onClick={() => setSelectedStock(withPriceBoard(s))}
                      className="stock-row cursor-pointer transition-all"
                      style={{ borderBottom: '1px solid #1e2832' }}
                    >
                      <td className="p-2 text-center">
                        <Star
                          size={12}
                          className="cursor-pointer transition-all"
                          style={{
                            color: watchlist.has(s.symbol) ? '#ffcc00' : '#2a3642',
                            fill: watchlist.has(s.symbol) ? '#ffcc00' : 'none',
                            filter: watchlist.has(s.symbol) ? 'drop-shadow(0 0 4px rgba(255,204,0,0.5))' : 'none',
                          }}
                          onClick={(e) => toggleWatchlist(s.symbol, e)}
                        />
                      </td>
                      <td className="p-2 text-center font-mono text-[10px]" style={{ color: '#4a5a6a' }}>{s.rank}</td>
                      <td className="p-2 text-left">
                        <div className="flex items-center">
                          <span className="font-semibold text-xs">{s.symbol}</span>
                          <TierBadge tier={s.tier} />
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-[10px] truncate max-w-[120px]" style={{ color: '#8b99a8' }}>{s.name}</span>
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              setIndustryFilter(industryFilter === s.industry ? null : s.industry);
                            }}
                            className="industry-tag text-[8px] px-1.5 py-0.5 rounded cursor-pointer"
                            data-active={industryFilter === s.industry ? '' : undefined}
                          >
                            {s.industry}
                          </span>
                        </div>
                      </td>
                      <td className="p-2 text-right font-mono font-semibold text-[11px]">{formatPrice(s.close || s.price)}</td>
                      <td className="p-2 text-right"><PriceChange value={s.change_1d} /></td>
                      <td className="p-2 text-right"><PriceChange value={s.change_5d} /></td>
                      <td className="p-2 text-right"><PriceChange value={s.change_20d} /></td>
                      <td className="p-2 text-right"><ScoreBadge value={s.composite_score} /></td>
                      <td className="p-2 text-center">
                        <SignalBadge stock={s} ict={ictMap[s.symbol]} />
                      </td>
                      <td className="p-2 text-right font-mono text-[10px]" style={{
                        color: s.foreign_net_7d == null ? '#2a3642' : s.foreign_net_7d >= 0 ? '#00ff88' : '#ff3366',
                      }}>
                        {s.foreign_net_7d == null
                          ? '—'
                          : `${s.foreign_net_7d >= 0 ? '+' : ''}${new Intl.NumberFormat('vi-VN').format(Math.round(s.foreign_net_7d))} tỷ`}
                      </td>
                      <td className="p-2 text-right">
                        {s.adx14 != null ? (
                          <div className="flex flex-col items-end gap-0.5">
                            <span
                              className="font-mono text-[10px] font-semibold"
                              style={{ color: (s.adx14 || 0) >= 25 ? '#00d4ff' : '#4a5a6a' }}
                            >
                              {(s.adx14 || 0).toFixed(0)}
                            </span>
                            {s.trend_short != null && (
                              <span className="text-[8px]" style={{ color: (s.trend_short || 0) > 0 ? '#00ff88' : (s.trend_short || 0) < 0 ? '#ff3366' : '#4a5a6a' }}>
                                {(s.trend_short || 0) > 0 ? '↑' : (s.trend_short || 0) < 0 ? '↓' : '—'}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-[10px]" style={{ color: '#2a3642' }}>–</span>
                        )}
                      </td>
                      <td className="p-2 text-right">
                        {s.rsi14 != null ? (
                          <span
                            className="font-mono text-[10px] font-semibold"
                            style={{
                              color: (s.rsi14 || 0) > 70 ? '#ff3366' : (s.rsi14 || 0) < 30 ? '#00ff88' : '#8b99a8',
                            }}
                          >
                            {(s.rsi14 || 0).toFixed(0)}
                          </span>
                        ) : (
                          <span className="text-[10px]" style={{ color: '#2a3642' }}>–</span>
                        )}
                      </td>
                      <td className="p-2 text-center" style={{ overflow: 'visible', position: 'relative' }}>
                        {(() => {
                          const sk = getStockStrategy(s);
                          if (sk === 'none') return <span className="text-[9px]" style={{ color: '#2a3642' }}>–</span>;
                          const d = STRATEGY_DEFS[sk];
                          const rsi = s.rsi14 ?? 50, adx = s.adx14 ?? 0, p20d = s.price_change_20d ?? s.change_20d ?? 0;
                          const pma20 = s.pct_from_ma20 ?? 0, bbW = s.bb_width ?? 15, stK = s.stoch_k ?? 50;
                          const condMap: Record<StrategyKey, string> = {
                            panic:`MA20: ${pma20.toFixed(1)}% · RSI: ${rsi.toFixed(0)}`, crash:`20D: ${p20d.toFixed(1)}% · RSI: ${rsi.toFixed(0)}`,
                            combo:`Trend↑ · ADX: ${adx.toFixed(0)} · RSI: ${rsi.toFixed(0)}`, os_deep:`RSI: ${rsi.toFixed(0)}`,
                            bb_below:`MA20: ${pma20.toFixed(1)}% · BB: ${bbW.toFixed(0)}%`, dip:`20D: ${p20d.toFixed(1)}%`,
                            os:`RSI: ${rsi.toFixed(0)}`, pull:`Stoch: ${stK.toFixed(0)} · MA20>MA50`,
                            ob_deep:`RSI: ${rsi.toFixed(0)}`, ob:`RSI: ${rsi.toFixed(0)}`, hot:`20D: +${p20d.toFixed(1)}%`, none:'',
                          };
                          const cc = d.conf >= 80 ? '#00ff88' : d.conf >= 65 ? '#00d4ff' : d.conf >= 50 ? '#ffcc00' : '#ff9500';
                          const ti = d.type === 'buy' ? '🟢' : d.type === 'sell' ? '🔴' : '🟡';
                          return (
                            <span className="strat-tip-wrap">
                              <span className="px-1.5 py-0.5 rounded text-[7px] font-bold tracking-wide whitespace-nowrap cursor-help"
                                style={{ background: d.bg, color: d.color, border: `1px solid ${d.border}`, boxShadow: `0 0 6px ${d.color}15` }}>{d.label}</span>
                              <div className="strat-tip" onClick={(e) => e.stopPropagation()}>
                                <div style={{ position:'absolute', bottom:-5, left:'50%', transform:'translateX(-50%) rotate(45deg)', width:10, height:10, background:'#0f1519', borderRight:`1px solid ${d.border}`, borderBottom:`1px solid ${d.border}` }} />
                                <div style={{ padding:'10px 12px 8px', borderBottom:'1px solid #1e2832', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                                  <div style={{ display:'flex', alignItems:'center', gap:6 }}><span style={{ fontSize:13 }}>{ti}</span><span style={{ fontSize:12, fontWeight:800, color:d.color, letterSpacing:0.5 }}>{d.name}</span></div>
                                  <span style={{ fontSize:9, fontWeight:700, padding:'2px 6px', borderRadius:4, background:d.type==='buy'?'#00ff8815':d.type==='sell'?'#ff336615':'#ff950015', color:d.type==='buy'?'#00ff88':d.type==='sell'?'#ff3366':'#ff9500' }}>{d.type==='buy'?'MUA':d.type==='sell'?'BÁN':'CHỜ'}</span>
                                </div>
                                <div style={{ padding:'8px 12px', borderBottom:'1px solid #1e2832' }}><p style={{ fontSize:10.5, color:'#b8c8d8', lineHeight:1.65, margin:0 }}>{d.def}</p></div>
                                <div style={{ padding:'6px 12px', borderBottom:'1px solid #1e2832', display:'flex', alignItems:'center', gap:6 }}>
                                  <span style={{ fontSize:9, color:'#4a5a6a' }}>Điều kiện:</span>
                                  <span style={{ fontSize:10.5, color:d.color, fontFamily:"'JetBrains Mono',monospace", fontWeight:600 }}>{condMap[sk]}</span>
                                </div>
                                <div style={{ padding:'8px 12px', display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:6, borderBottom:'1px solid #1e2832' }}>
                                  {[{l:'EDGE 20D',v:d.edge,c:d.type==='sell'?'#ff3366':d.color},{l:'WIN RATE',v:d.win,c:parseFloat(d.win)>=55?'#00ff88':parseFloat(d.win)>=50?'#00d4ff':'#ff9500'},{l:'MẪU (N)',v:d.n,c:'#8b99a8'}].map(x=>(
                                    <div key={x.l} style={{ textAlign:'center' }}><div style={{ fontSize:8, color:'#4a5a6a', marginBottom:2, letterSpacing:0.5 }}>{x.l}</div><div style={{ fontSize:13, fontWeight:800, fontFamily:"'JetBrains Mono',monospace", color:x.c }}>{x.v}</div></div>
                                  ))}
                                </div>
                                <div style={{ padding:'8px 12px 10px' }}>
                                  <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:5 }}><span style={{ fontSize:9, color:'#4a5a6a', fontWeight:500 }}>Mức độ tự tin</span><span style={{ fontSize:10, fontWeight:700, color:cc }}>{d.confLabel} ({d.conf}%)</span></div>
                                  <div style={{ height:5, background:'#1e2832', borderRadius:3, overflow:'hidden' }}><div style={{ height:'100%', width:`${d.conf}%`, background:`linear-gradient(90deg, ${cc}90, ${cc})`, borderRadius:3, boxShadow:`0 0 8px ${cc}50` }} /></div>
                                </div>
                              </div>
                            </span>
                          );
                        })()}
                      </td>
                      <td className="p-2 text-right overflow-visible" onClick={(e) => e.stopPropagation()}>
                        {s.price_history && s.price_history.length > 1 ? (
                          <Sparkline data={s.price_history} volume={s.volume_history} dates={s.dates} />
                        ) : (
                          <span className="text-[10px]" style={{ color: '#4a5a6a' }}>-</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {renderPagination()}

          {/* Footer */}
          <div className="mt-3 flex justify-between px-1 text-[10px]" style={{ color: '#4a5a6a' }}>
            <span>
              Hiển thị{' '}
              <span className="font-mono" style={{ color: '#00d4ff' }}>
                {(page - 1) * ITEMS_PER_PAGE + 1}-{Math.min(page * ITEMS_PER_PAGE, filteredStocks.length)}
              </span>{' '}
              /{' '}
              <span className="font-mono" style={{ color: '#00d4ff' }}>
                {filteredStocks.length}
              </span>{' '}
              cổ phiếu
              {industryFilter && (
                <>
                  {' '}trong{' '}
                  <span style={{ color: '#00d4ff' }}>{industryFilter}</span>
                </>
              )}
            </span>
            <span style={{ letterSpacing: '0.5px' }}>POWERED BY VNSTOCK</span>
          </div>
        </main>
      </div>
      )}

      {/* Stock Modal */}
      {selectedStock && (
        <StockModal
          stock={selectedStock}
          sectorStatus={getStockSectorStatus(selectedStock)}
          preloadedAnalysis={aiAnalyses[selectedStock.symbol]}
          ictSignal={ictMap[selectedStock.symbol]}
          regimeBullWeight={ictData?.regime?.bull_weight}
          onClose={() => setSelectedStock(null)}
        />
      )}
    </div>
  );
}
