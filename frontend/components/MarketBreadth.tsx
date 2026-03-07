'use client';

import { TrendingUp, TrendingDown, Activity, Globe } from 'lucide-react';
import type { SummaryResponse, ICTSignalsResponse, PriceBoardResponse } from '@/lib/types';

interface MarketBreadthProps {
  summary: SummaryResponse | null;
  ictData: ICTSignalsResponse | null;
  priceBoard: PriceBoardResponse | null;
  vnindexBaseValue?: number; // điểm VN-Index hôm qua (để tính điểm thay đổi)
  onSymbolClick?: (symbol: string) => void;
}

function StatCell({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  color?: string;
  sub?: string;
}) {
  return (
    <div
      className="flex flex-col px-3 py-2 rounded-lg"
      style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
    >
      <span className="text-[9px] tracking-widest mb-1" style={{ color: '#4a5a6a' }}>
        {label}
      </span>
      <span className="font-mono font-bold text-sm" style={{ color: color || '#e8edf2' }}>
        {value}
      </span>
      {sub && (
        <span className="text-[9px] mt-0.5 font-mono" style={{ color: '#4a5a6a' }}>
          {sub}
        </span>
      )}
    </div>
  );
}

function ChangeChip({
  value,
  label,
  points,
}: {
  value?: number | null;
  label: string;
  points?: number | null;
}) {
  if (value == null) return null;
  const up = value >= 0;
  const color = up ? '#00ff88' : '#ff3366';
  const shadow = up ? 'rgba(0,255,136,0.25)' : 'rgba(255,51,102,0.25)';

  return (
    <div
      className="flex flex-col items-center px-2.5 py-1.5 rounded-lg"
      style={{
        background: `${color}10`,
        border: `1px solid ${color}30`,
        minWidth: 56,
      }}
    >
      <span className="text-[8px] tracking-widest mb-0.5" style={{ color: '#4a5a6a' }}>
        {label}
      </span>
      <span
        className="font-mono font-bold text-xs"
        style={{ color, textShadow: `0 0 8px ${shadow}` }}
      >
        {up ? '+' : ''}
        {value.toFixed(2)}%
      </span>
      {points != null && (
        <span className="font-mono text-[9px] mt-0.5" style={{ color: `${color}cc` }}>
          {up ? '+' : ''}
          {points.toFixed(2)} pts
        </span>
      )}
    </div>
  );
}

export default function MarketBreadth({
  summary,
  ictData,
  priceBoard,
  onSymbolClick,
}: MarketBreadthProps) {
  const market = summary?.market;
  const regime = ictData?.regime;
  const breadth = regime?.components?.market_breadth;
  const stats = ictData?.market_stats;

  const vnindex = market?.vnindex ?? regime?.vnindex ?? null;
  const change1d = market?.vnindex_change_1d ?? market?.vnindex_change ?? regime?.vnindex_change_1d ?? null;
  const change5d = market?.vnindex_change_5d ?? regime?.vnindex_change_5d ?? null;
  const change20d = market?.vnindex_change_20d ?? regime?.vnindex_change_20d ?? null;

  // Tính điểm thay đổi tuyệt đối từ %
  const pts1d = vnindex != null && change1d != null
    ? (vnindex / (1 + change1d / 100)) * (change1d / 100)
    : null;
  const pts5d = vnindex != null && change5d != null
    ? (vnindex / (1 + change5d / 100)) * (change5d / 100)
    : null;
  const pts20d = vnindex != null && change20d != null
    ? (vnindex / (1 + change20d / 100)) * (change20d / 100)
    : null;

  const regimeColor =
    regime?.regime === 'BULL' ? '#00ff88' :
    regime?.regime === 'BEAR' ? '#ff3366' :
    regime?.regime === 'TRANSITION' ? '#ffcc00' : '#8b99a8';

  // Market breadth từ ICT
  const advance = breadth?.advance ?? 0;
  const decline = breadth?.decline ?? 0;
  const total = breadth?.total ?? (stats?.total_symbols ?? 0);
  const advancePct = total > 0 ? (advance / total * 100) : null;

  // Foreign net từ price_board summary
  const foreignNetBn =
    priceBoard?.summary?.total_foreign_net_value_bn ??
    regime?.foreign_net_total_bn ??
    null;
  const foreignNetColor = foreignNetBn != null
    ? (foreignNetBn >= 0 ? '#00ff88' : '#ff3366')
    : '#8b99a8';

  // Most active từ price_board
  const mostActive = priceBoard?.stocks
    ? [...priceBoard.stocks]
        .filter((s) => s.total_traded_value != null && s.total_traded_value > 0)
        .sort((a, b) => (b.total_traded_value ?? 0) - (a.total_traded_value ?? 0))
        .slice(0, 5)
    : [];

  // Breadth bar width
  const advanceBarW = advancePct ?? 0;
  const declineBarW = total > 0 ? (decline / total * 100) : 0;

  if (!market && !ictData) return null;

  return (
    <div
      className="rounded-xl overflow-hidden mb-3"
      style={{
        background: 'linear-gradient(180deg, #0f1519 0%, #0a0f14 100%)',
        border: `1px solid ${regimeColor}25`,
        boxShadow: `0 0 20px ${regimeColor}08`,
      }}
    >
      {/* ── Top row: VN-Index + Regime ─────────────────────────────── */}
      <div
        className="flex items-stretch gap-0 flex-wrap"
        style={{ borderBottom: '1px solid #1e2832' }}
      >
        {/* VN-Index block */}
        <div
          className="flex-1 min-w-[200px] p-3"
          style={{
            background: `linear-gradient(135deg, ${
              change1d != null && change1d >= 0 ? 'rgba(0,255,136,0.04)' : 'rgba(255,51,102,0.04)'
            } 0%, transparent 100%)`,
            borderRight: '1px solid #1e2832',
          }}
        >
          <div className="text-[9px] tracking-widest mb-1" style={{ color: '#4a5a6a' }}>
            VN-INDEX
          </div>
          <div className="flex items-end gap-3 flex-wrap">
            {/* Điểm số tuyệt đối */}
            <div>
              <span
                className="font-mono font-black text-2xl"
                style={{
                  color: change1d != null && change1d >= 0 ? '#00ff88' : '#ff3366',
                  textShadow: `0 0 20px ${
                    change1d != null && change1d >= 0
                      ? 'rgba(0,255,136,0.3)'
                      : 'rgba(255,51,102,0.3)'
                  }`,
                }}
              >
                {vnindex != null
                  ? vnindex.toLocaleString('vi-VN', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })
                  : '—'}
              </span>
            </div>

            {/* Chips thay đổi */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <ChangeChip value={change1d} label="1D" points={pts1d} />
              <ChangeChip value={change5d} label="5D" points={pts5d} />
              <ChangeChip value={change20d} label="20D" points={pts20d} />
            </div>
          </div>
        </div>

        {/* Regime block */}
        {regime && (
          <div
            className="flex flex-col justify-center p-3 gap-1"
            style={{
              minWidth: 130,
              background: `${regimeColor}06`,
              borderRight: '1px solid #1e2832',
            }}
          >
            <div className="text-[9px] tracking-widest" style={{ color: '#4a5a6a' }}>
              MARKET REGIME
            </div>
            <div className="flex items-center gap-2">
              <span
                className="px-2 py-1 rounded-md font-black text-xs tracking-widest"
                style={{
                  background: `${regimeColor}20`,
                  color: regimeColor,
                  border: `1px solid ${regimeColor}40`,
                  boxShadow: `0 0 10px ${regimeColor}30`,
                }}
              >
                {regime.regime}
              </span>
              <span className="font-mono text-[10px]" style={{ color: `${regimeColor}aa` }}>
                {(regime.bull_weight * 100).toFixed(0)}% bull
              </span>
            </div>
            <div
              className="text-[9px] font-mono"
              style={{
                color:
                  regime.regime === 'BEAR' ? '#ff336699' :
                  regime.regime === 'BULL' ? '#00ff8899' : '#4a5a6a',
              }}
            >
              Strength: {regime.regime_strength?.toFixed(0) ?? '—'}%
            </div>
          </div>
        )}
      </div>

      {/* ── Middle row: Market Breadth + Stats ─────────────────────── */}
      <div
        className="flex gap-3 p-3 flex-wrap items-start"
        style={{ borderBottom: '1px solid #1e2832' }}
      >
        {/* Advance / Decline */}
        <div className="flex-1 min-w-[180px]">
          <div className="text-[9px] tracking-widest mb-2" style={{ color: '#4a5a6a' }}>
            MARKET BREADTH
          </div>

          {/* Progress bar */}
          <div
            className="flex h-2 rounded-full overflow-hidden mb-1.5"
            style={{ background: '#1e2832' }}
          >
            <div
              style={{
                width: `${advanceBarW}%`,
                background: 'linear-gradient(90deg, #00ff8860, #00ff88)',
                transition: 'width 0.5s ease',
              }}
            />
            <div
              style={{
                width: `${declineBarW}%`,
                background: 'linear-gradient(90deg, #ff336660, #ff3366)',
                transition: 'width 0.5s ease',
              }}
            />
          </div>

          <div className="flex justify-between text-[10px]">
            <span>
              <span style={{ color: '#00ff88' }}>▲ {advance.toLocaleString()}</span>
              <span style={{ color: '#4a5a6a' }} className="ml-1">
                ({advancePct?.toFixed(0) ?? 0}%)
              </span>
            </span>
            <span style={{ color: '#4a5a6a' }}>
              {(total - advance - decline).toLocaleString()} flat
            </span>
            <span>
              <span style={{ color: '#4a5a6a' }} className="mr-1">
                ({total > 0 ? (decline / total * 100).toFixed(0) : 0}%)
              </span>
              <span style={{ color: '#ff3366' }}>{decline.toLocaleString()} ▼</span>
            </span>
          </div>
        </div>

        {/* Stats mini grid */}
        <div className="flex gap-1.5 flex-wrap">
          {stats && (
            <>
              <StatCell
                label="BULLISH STR"
                value={`${stats.bullish_pct?.toFixed(0) ?? '—'}%`}
                color={stats.bullish_pct > 50 ? '#00ff88' : '#ff3366'}
                sub={`${stats.bullish_structure}/${stats.total_symbols}`}
              />
              <StatCell
                label="ACCUMULATE"
                value={stats.accumulating}
                color="#00d4ff"
                sub={`${total > 0 ? (stats.accumulating / total * 100).toFixed(0) : 0}%`}
              />
              <StatCell
                label="FLOW IN"
                value={stats.flow_in}
                color="#a78bfa"
                sub={`${total > 0 ? (stats.flow_in / total * 100).toFixed(0) : 0}%`}
              />
              <StatCell
                label="WYCKOFF"
                value={stats.wyckoff_spring}
                color="#ffcc00"
              />
            </>
          )}
          <StatCell
            label="NN NET"
            value={
              foreignNetBn != null
                ? `${foreignNetBn >= 0 ? '+' : ''}${
                    Math.abs(foreignNetBn) >= 1000
                      ? (foreignNetBn / 1000).toFixed(2) + 'T'
                      : foreignNetBn.toFixed(1) + 'B'
                  }`
                : '—'
            }
            color={foreignNetColor}
            sub="7D tỷ đồng"
          />
        </div>
      </div>

      {/* ── Bottom row: Top Gainers / Losers / Most Active ────────── */}
      <div className="flex gap-0 divide-x" style={{ borderColor: '#1e2832' }}>
        {/* Top gainers */}
        <div className="flex-1 p-2.5">
          <div className="flex items-center gap-1 mb-1.5">
            <TrendingUp size={10} color="#00ff88" />
            <span className="text-[9px] tracking-widest" style={{ color: '#00ff88' }}>
              TOP TĂNG
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {(summary?.top_gainers ?? []).slice(0, 5).map((s) => (
              <div
                key={s.symbol}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded cursor-pointer transition-all"
                style={{ background: '#00ff8810', border: '1px solid #00ff8825' }}
                onClick={() => onSymbolClick?.(s.symbol)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#00ff8825'; (e.currentTarget as HTMLDivElement).style.border = '1px solid #00ff8855'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#00ff8810'; (e.currentTarget as HTMLDivElement).style.border = '1px solid #00ff8825'; }}
              >
                <span className="font-semibold text-[10px]">{s.symbol}</span>
                <span className="font-mono text-[9px]" style={{ color: '#00ff88' }}>
                  +{s.change.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Most active */}
        <div className="flex-1 p-2.5">
          <div className="flex items-center gap-1 mb-1.5">
            <Activity size={10} color="#00d4ff" />
            <span className="text-[9px] tracking-widest" style={{ color: '#00d4ff' }}>
              THANH KHOẢN
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {mostActive.slice(0, 5).map((s) => (
              <div
                key={s.symbol}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded cursor-pointer transition-all"
                style={{ background: '#00d4ff10', border: '1px solid #00d4ff25' }}
                onClick={() => onSymbolClick?.(s.symbol)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#00d4ff25'; (e.currentTarget as HTMLDivElement).style.border = '1px solid #00d4ff55'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#00d4ff10'; (e.currentTarget as HTMLDivElement).style.border = '1px solid #00d4ff25'; }}
              >
                <span className="font-semibold text-[10px]">{s.symbol}</span>
                <span className="font-mono text-[9px]" style={{ color: '#00d4ff' }}>
                  {s.total_traded_value != null
                    ? s.total_traded_value >= 1e9
                      ? (s.total_traded_value / 1e9).toFixed(1) + 'T'
                      : (s.total_traded_value / 1e6).toFixed(0) + 'M'
                    : '—'}
                </span>
              </div>
            ))}
            {mostActive.length === 0 && (
              <span className="text-[10px]" style={{ color: '#2a3642' }}>
                —
              </span>
            )}
          </div>
        </div>

        {/* Top foreign sell */}
        <div className="flex-1 p-2.5">
          <div className="flex items-center gap-1 mb-1.5">
            <TrendingDown size={10} color="#ff3366" />
            <span className="text-[9px] tracking-widest" style={{ color: '#ff3366' }}>
              TOP GIẢM
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {(summary?.top_losers ?? []).slice(0, 5).map((s) => (
              <div
                key={s.symbol}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded cursor-pointer transition-all"
                style={{ background: '#ff336610', border: '1px solid #ff336625' }}
                onClick={() => onSymbolClick?.(s.symbol)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#ff336625'; (e.currentTarget as HTMLDivElement).style.border = '1px solid #ff336655'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#ff336610'; (e.currentTarget as HTMLDivElement).style.border = '1px solid #ff336625'; }}
              >
                <span className="font-semibold text-[10px]">{s.symbol}</span>
                <span className="font-mono text-[9px]" style={{ color: '#ff3366' }}>
                  {s.change.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* NN buy/sell */}
        <div className="flex-1 p-2.5">
          <div className="flex items-center gap-1 mb-1.5">
            <Globe size={10} color="#a78bfa" />
            <span className="text-[9px] tracking-widest" style={{ color: '#a78bfa' }}>
              KHỐI NGOẠI
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            {(summary?.foreign_buy ?? []).slice(0, 2).map((s) => (
              <div
                key={s.symbol}
                className="flex items-center justify-between text-[9px] px-1.5 py-0.5 rounded cursor-pointer transition-all"
                style={{ borderRadius: 4 }}
                onClick={() => onSymbolClick?.(s.symbol)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#00ff8812'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
              >
                <span className="font-semibold">{s.symbol}</span>
                <span className="font-mono" style={{ color: '#00ff88' }}>
                  +{s.net.toFixed(1)}B
                </span>
              </div>
            ))}
            {(summary?.foreign_sell ?? []).slice(0, 2).map((s) => (
              <div
                key={s.symbol}
                className="flex items-center justify-between text-[9px] px-1.5 py-0.5 rounded cursor-pointer transition-all"
                style={{ borderRadius: 4 }}
                onClick={() => onSymbolClick?.(s.symbol)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#ff336612'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
              >
                <span className="font-semibold">{s.symbol}</span>
                <span className="font-mono" style={{ color: '#ff3366' }}>
                  {s.net.toFixed(1)}B
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
