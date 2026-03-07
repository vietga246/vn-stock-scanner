'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import { Search, Star, BarChart3, X } from 'lucide-react';
import type { Stock, Sector, AIAnalysis, ICTSignal, ICTSignalsResponse } from '@/lib/types';
import { getDashboardData, getSummary, loadPrices, formatPrice, formatPercent, getScoreColor, getTierColor } from '@/lib/api';
import IndustryFlow from './IndustryFlow';
import ICTDashboard from './ICTDashboard';
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
  if (value === undefined || Math.abs(value) < 0.01) {
    return (
      <span className="font-mono text-[10px]" style={{ color: '#4a5a6a' }}>
        0.00%
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

// Type-safe sort keys (Q4 fix)
type SortableKey = 'rank' | 'close' | 'change_1d' | 'change_5d' | 'change_20d' | 'composite_score' | 'foreign_net_7d' | 'adx14' | 'rsi14';

function getSortValue(stock: Stock, key: SortableKey): number {
  const v = stock[key as keyof Stock];
  return (typeof v === 'number' ? v : 0);
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

  // UI state
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [industryFilter, setIndustryFilter] = useState<string | null>(null);
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
        if (summary?.market) {
          setVnindex({
            value: summary.market.vnindex,
            change: summary.market.vnindex_change,
          });
        }
        setError(null);

        // P6: Lazy-load prices after initial render
        loadPrices(data.stocks).then((stocksWithPrices) => {
          setStocks(stocksWithPrices);
        });

        // Lazy-load ICT signals
        fetch('/api/ict-signals')
          .then((r) => r.json())
          .then((ict: ICTSignalsResponse) => {
            if (ict?.signals) {
              const map: Record<string, ICTSignal> = {};
              ict.signals.forEach((s) => { map[s.symbol] = s; });
              setIctMap(map);
            }
          })
          .catch(() => { /* ICT signals optional */ });
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

    // Sort (type-safe)
    result.sort((a, b) => {
      const aVal = getSortValue(a, sortBy);
      const bVal = getSortValue(b, sortBy);
      return sortOrder === 'desc' ? bVal - aVal : aVal - bVal;
    });

    return result;
  }, [stocks, searchQuery, tierFilter, industryFilter, sortBy, sortOrder]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [searchQuery, tierFilter, industryFilter]);

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

      {/* Market Stats Bar */}
      <div className="p-2.5 flex gap-3 flex-wrap" style={{ background: '#0a0f14', borderBottom: '1px solid #1e2832' }}>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
          <span className="text-[10px]" style={{ color: '#4a5a6a' }}>VN-INDEX</span>
          <span className="font-mono font-semibold">
            {vnindex?.value != null ? vnindex.value.toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'}
          </span>
          {vnindex?.value != null && vnindex?.change != null && (
            <span
              className="font-mono text-xs"
              style={{
                color: vnindex.change >= 0 ? '#00ff88' : '#ff3366',
                textShadow: `0 0 6px ${vnindex.change >= 0 ? 'rgba(0,255,136,0.3)' : 'rgba(255,51,102,0.3)'}`
              }}
            >
              {vnindex.change >= 0 ? '+' : ''}{vnindex.change.toFixed(2)}%
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
          <span className="text-[10px]" style={{ color: '#4a5a6a' }}>STOCKS</span>
          <span className="font-mono font-semibold" style={{ color: '#00d4ff' }}>{stocks.length}</span>
        </div>
        {generatedAt && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md ml-auto" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
            <span className="text-[10px]" style={{ color: '#4a5a6a' }}>Updated</span>
            <span className="text-[10px] font-mono" style={{ color: '#8b99a8' }}>
              {new Date(generatedAt).toLocaleDateString('vi-VN')}
            </span>
          </div>
        )}
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
        {searchQuery && (
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[10px]" style={{ color: '#4a5a6a' }}>
              Tìm thấy <span style={{ color: '#00d4ff' }}>{filteredStocks.length}</span> kết quả
            </span>
          </div>
        )}
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
                  <th onClick={() => handleSort('foreign_net_7d')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>NN 7D</th>
                  <th onClick={() => handleSort('adx14')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>ADX</th>
                  <th onClick={() => handleSort('rsi14')} className="p-2 text-right text-[9px] font-medium cursor-pointer" style={{ color: '#4a5a6a' }}>RSI</th>
                  <th className="p-2 text-center text-[9px] font-medium" style={{ color: '#4a5a6a' }}>ICT</th>
                  <th className="p-2 text-right text-[9px] font-medium w-[100px]" style={{ color: '#4a5a6a' }}>30D</th>
                </tr>
              </thead>
              <tbody>
                {paginatedStocks.length === 0 ? (
                  <tr>
                    <td colSpan={13} className="p-8 text-center">
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
                      onClick={() => setSelectedStock(s)}
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
                      <td className="p-2 text-right font-mono text-[10px]" style={{
                        color: (s.foreign_net_7d || 0) >= 0 ? '#00ff88' : '#ff3366',
                        textShadow: `0 0 6px ${(s.foreign_net_7d || 0) >= 0 ? 'rgba(0,255,136,0.3)' : 'rgba(255,51,102,0.3)'}`,
                      }}>
                        {(s.foreign_net_7d || 0) >= 0 ? '+' : ''}{Math.abs(s.foreign_net_7d || 0) >= 1000 ? ((s.foreign_net_7d || 0) / 1000).toFixed(2) + 'TB' : (s.foreign_net_7d || 0).toFixed(1) + 'B'}
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
                      <td className="p-2 text-center">
                        <div className="flex items-center justify-center gap-0.5 flex-wrap">
                          {s.fvg_bull && (
                            <span
                              className="px-1 py-0.5 rounded text-[7px] font-bold"
                              style={{ background: '#00ff8815', color: '#00ff88', border: '1px solid #00ff8830' }}
                              title="Fair Value Gap Bullish"
                            >
                              FVG
                            </span>
                          )}
                          {(s.trend_strength != null && (s.trend_strength || 0) >= 65) && (
                            <span
                              className="px-1 py-0.5 rounded text-[7px] font-bold"
                              style={{ background: '#00d4ff15', color: '#00d4ff', border: '1px solid #00d4ff30' }}
                              title={`Trend strength: ${s.trend_strength}`}
                            >
                              TRD
                            </span>
                          )}
                          {!s.fvg_bull && !(s.trend_strength != null && (s.trend_strength || 0) >= 65) && (
                            <span className="text-[9px]" style={{ color: '#2a3642' }}>–</span>
                          )}
                        </div>
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
          onClose={() => setSelectedStock(null)}
        />
      )}
    </div>
  );
}
