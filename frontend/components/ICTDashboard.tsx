'use client';

import { useState, useEffect, useMemo } from 'react';
import type { ICTSignal, ICTSignalsResponse, ICTRegime, ICTMarketStats } from '@/lib/types';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function qualityColor(q: string): string {
  return q === 'A+' ? '#00ff88' : q === 'A' ? '#00d4ff' : q === 'B' ? '#a78bfa' : q === 'C' ? '#ffcc00' : '#4a5a6a';
}

function regimeColor(r: string): string {
  return r === 'BULL' ? '#00ff88' : r === 'BEAR' ? '#ff3366' : r === 'TRANSITION' ? '#ffcc00' : '#8b99a8';
}

function fmt(n: number | null | undefined, dec = 1): string {
  if (n == null) return '–';
  return n.toFixed(dec);
}

function fmtBn(n: number | null | undefined): string {
  if (n == null) return '–';
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + 'T';
  return n.toFixed(1) + 'B';
}

function pct(n: number | null | undefined): string {
  if (n == null) return '–';
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function RegimeBanner({ regime }: { regime: ICTRegime }) {
  const col = regimeColor(regime.regime);
  const bw  = regime.bull_weight ?? 0.5;
  return (
    <div
      className="rounded-xl p-4 mb-3"
      style={{
        background: `linear-gradient(135deg, ${col}08 0%, #0f1519 100%)`,
        border: `1px solid ${col}30`,
      }}
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        {/* Regime label */}
        <div className="flex items-center gap-3">
          <div
            className="px-3 py-1.5 rounded-lg font-bold text-sm tracking-widest"
            style={{ background: `${col}20`, color: col, border: `1px solid ${col}40` }}
          >
            {regime.regime}
          </div>
          <div>
            <div className="text-[10px]" style={{ color: '#4a5a6a' }}>BULL WEIGHT</div>
            <div className="font-mono font-bold text-lg" style={{ color: col }}>
              {(bw * 100).toFixed(0)}%
            </div>
          </div>
          <div>
            <div className="text-[10px]" style={{ color: '#4a5a6a' }}>STRENGTH</div>
            <div className="font-mono font-bold text-lg" style={{ color: '#e8edf2' }}>
              {fmt(regime.regime_strength, 0)}
            </div>
          </div>
        </div>

        {/* VNINDEX stats */}
        <div className="flex gap-4 flex-wrap">
          {[
            { label: 'VNINDEX', val: regime.vnindex != null ? regime.vnindex.toLocaleString('vi-VN', { minimumFractionDigits: 2 }) : '–', col: '#e8edf2' },
            { label: '1D', val: pct(regime.vnindex_change_1d), col: (regime.vnindex_change_1d ?? 0) >= 0 ? '#00ff88' : '#ff3366' },
            { label: '5D', val: pct(regime.vnindex_change_5d), col: (regime.vnindex_change_5d ?? 0) >= 0 ? '#00ff88' : '#ff3366' },
            { label: '20D', val: pct(regime.vnindex_change_20d), col: (regime.vnindex_change_20d ?? 0) >= 0 ? '#00ff88' : '#ff3366' },
            { label: 'BREADTH', val: fmt(regime.breadth_advance_pct) + '%', col: (regime.breadth_advance_pct ?? 0) >= 50 ? '#00ff88' : '#ff3366' },
            { label: 'NN NET', val: fmtBn(regime.foreign_net_total_bn), col: (regime.foreign_net_total_bn ?? 0) >= 0 ? '#00ff88' : '#ff3366' },
          ].map(({ label, val, col: c }) => (
            <div key={label} className="text-center">
              <div className="text-[9px] mb-0.5" style={{ color: '#4a5a6a', letterSpacing: '1px' }}>{label}</div>
              <div className="font-mono font-semibold text-xs" style={{ color: c }}>{val}</div>
            </div>
          ))}
        </div>

        {/* Bull weight bar */}
        <div className="w-full mt-1">
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: `${bw * 100}%`,
                background: `linear-gradient(90deg, ${col} 0%, ${col}88 100%)`,
                boxShadow: `0 0 8px ${col}60`,
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function MarketStats({ stats, qDist }: { stats: ICTMarketStats; qDist: Record<string, number> }) {
  const total = stats.total_symbols || 1;
  return (
    <div className="grid grid-cols-2 gap-2 mb-3">
      {/* Structure */}
      <div className="rounded-xl p-3" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
        <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>MARKET STRUCTURE</div>
        <div className="flex gap-3 flex-wrap">
          {[
            { label: 'Bullish', val: stats.bullish_structure, pct: stats.bullish_pct, col: '#00ff88' },
            { label: 'BOS ↑',  val: stats.bos_bull,          pct: +(stats.bos_bull / total * 100).toFixed(1), col: '#00d4ff' },
            { label: 'CHoCH ↑',val: stats.choch_bull,        pct: +(stats.choch_bull / total * 100).toFixed(1), col: '#a78bfa' },
            { label: 'BOS ↓',  val: stats.bos_bear,          pct: +(stats.bos_bear / total * 100).toFixed(1), col: '#ff3366' },
          ].map(({ label, val, pct: p, col }) => (
            <div key={label} className="flex flex-col items-center px-2">
              <div className="font-mono font-bold text-base" style={{ color: col }}>{val}</div>
              <div className="text-[9px]" style={{ color: '#8b99a8' }}>{label}</div>
              <div className="text-[9px] font-mono" style={{ color: '#4a5a6a' }}>{p}%</div>
            </div>
          ))}
        </div>
      </div>

      {/* Smart Money */}
      <div className="rounded-xl p-3" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
        <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>SMART MONEY</div>
        <div className="flex gap-3 flex-wrap">
          {[
            { label: 'Acc',         val: stats.accumulating,   col: '#00ff88' },
            { label: 'Spring',      val: stats.wyckoff_spring, col: '#a78bfa' },
            { label: 'Flow IN',     val: stats.flow_in,        col: '#00d4ff' },
            { label: 'Smart $',     val: stats.smart_money_conf, col: '#ffcc00' },
          ].map(({ label, val, col }) => (
            <div key={label} className="flex flex-col items-center px-2">
              <div className="font-mono font-bold text-base" style={{ color: col }}>{val}</div>
              <div className="text-[9px]" style={{ color: '#8b99a8' }}>{label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Quality dist */}
      <div className="col-span-2 rounded-xl p-3" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
        <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>SETUP QUALITY DISTRIBUTION</div>
        <div className="flex items-end gap-2 h-10">
          {['A+', 'A', 'B', 'C', 'SKIP'].map((q) => {
            const cnt = qDist[q] ?? 0;
            const maxVal = Math.max(...['A+', 'A', 'B', 'C', 'SKIP'].map(k => qDist[k] ?? 0), 1);
            const h = Math.max((cnt / maxVal) * 32, cnt > 0 ? 4 : 0);
            const col = qualityColor(q);
            return (
              <div key={q} className="flex flex-col items-center gap-1 flex-1">
                <div className="text-[9px] font-mono" style={{ color: col }}>{cnt}</div>
                <div
                  className="w-full rounded-t transition-all duration-500"
                  style={{ height: h, background: `${col}60`, border: `1px solid ${col}40` }}
                />
                <div className="text-[8px] font-bold" style={{ color: col }}>{q}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function SectorBadges({ rotation }: { rotation: ICTSignalsResponse['sector_rotation'] }) {
  const groups = [
    { label: '🔥 HOT', items: rotation.hot_sectors,       col: '#ff9500' },
    { label: '📈 LEADING', items: rotation.leading.slice(0,4), col: '#00ff88' },
    { label: '💰 ACCUM',  items: rotation.accumulating.slice(0,4), col: '#00d4ff' },
    { label: '🔄 ROTATING IN', items: rotation.rotating_in.slice(0,3), col: '#a78bfa' },
    { label: '📉 DISTRIBUTING', items: rotation.distributing.slice(0,3), col: '#ff3366' },
  ];
  return (
    <div className="rounded-xl p-3 mb-3" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
      <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>SECTOR ROTATION</div>
      <div className="flex flex-wrap gap-2">
        {groups.map(({ label, items, col }) => items.length > 0 && (
          <div key={label}>
            <div className="text-[8px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="flex gap-1 flex-wrap">
              {items.map((s) => (
                <span
                  key={s}
                  className="px-2 py-0.5 rounded text-[9px] font-medium"
                  style={{ background: `${col}15`, color: col, border: `1px solid ${col}30` }}
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Grid columns definition — shared by header and rows
const GRID = '32px minmax(140px,1.8fr) minmax(100px,1.2fr) minmax(90px,1fr) minmax(120px,1.5fr) minmax(60px,0.7fr) minmax(85px,1fr) minmax(75px,0.9fr) minmax(85px,1fr)';

function SignalRow({ signal, onClick }: { key?: string; signal: ICTSignal; onClick: () => void }) {
  const qCol     = qualityColor(signal.setup_quality);
  const structCol = signal.structure === 'BULLISH' ? '#00ff88' : signal.structure === 'BEARISH' ? '#ff3366' : '#4a5a6a';
  const flowCol   = signal.flow_direction === 'in' ? '#00ff88' : signal.flow_direction === 'out' ? '#ff3366' : '#4a5a6a';
  const p1d = signal.price_change_1d;
  const p5d = signal.price_change_5d;
  const accLabel = signal.accumulation_score >= 65 ? 'ACC' : signal.distribution_score >= 65 ? 'DIST' : 'NEU';
  const accCol   = signal.accumulation_score >= 65 ? '#00ff88' : signal.distribution_score >= 65 ? '#ff3366' : '#4a5a6a';
  const rs    = signal.signal_breakdown?.rs_sector;
  const rsCol = rs != null ? (rs >= 80 ? '#00ff88' : rs >= 65 ? '#00d4ff' : '#4a5a6a') : '#4a5a6a';

  const cellBase: React.CSSProperties = { padding: '10px 8px 2px', overflow: 'hidden', minWidth: 0 };
  const cell2Base: React.CSSProperties = { padding: '2px 8px 10px', overflow: 'hidden', minWidth: 0 };

  return (
    <div
      onClick={onClick}
      className="cursor-pointer"
      style={{ borderBottom: '1px solid #1e2832' }}
      onMouseEnter={(e) => (e.currentTarget.style.background = '#1e283218')}
      onMouseLeave={(e) => (e.currentTarget.style.background = '')}
    >
      {/* ── Row 1: main ── */}
      <div style={{ display: 'grid', gridTemplateColumns: GRID, alignItems: 'end' }}>

        {/* # */}
        <div style={{ ...cellBase, textAlign: 'center', fontFamily: 'monospace', fontSize: 9, color: '#4a5a6a' }}>
          {signal.ict_rank}
        </div>

        {/* SYMBOL */}
        <div style={{ ...cellBase }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'nowrap' }}>
            <span style={{ fontWeight: 700, fontSize: 12, whiteSpace: 'nowrap' }}>{signal.symbol}</span>
            {signal.setup_quality === 'SKIP' ? (
              <span style={{ padding: '1px 5px', borderRadius: 3, fontSize: 8, fontWeight: 700, background: '#1e283280', color: '#4a5a6a', border: '1px solid #2a364250', whiteSpace: 'nowrap' }}>WATCH</span>
            ) : (
              <span style={{ padding: '1px 5px', borderRadius: 3, fontSize: 8, fontWeight: 700, background: `${qCol}20`, color: qCol, border: `1px solid ${qCol}40`, whiteSpace: 'nowrap' }}>{signal.setup_quality}</span>
            )}
            {signal.smart_money   && <span style={{ fontSize: 8 }}>💎</span>}
            {signal.wyckoff_spring && <span style={{ fontSize: 8 }}>💧</span>}
          </div>
        </div>

        {/* SCORE */}
        <div style={{ ...cellBase, textAlign: 'right' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
            <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 12, color: qCol }}>{fmt(signal.alpha_score)}</span>
            {rs != null && (
              <span style={{ fontFamily: 'monospace', fontSize: 8, padding: '1px 4px', borderRadius: 3, color: rsCol, background: '#1e283240', whiteSpace: 'nowrap' }}>rs{rs.toFixed(0)}</span>
            )}
          </div>
        </div>

        {/* STRUCTURE */}
        <div style={{ ...cellBase, textAlign: 'center' }}>
          <span style={{ fontSize: 9, fontWeight: 600, color: structCol, whiteSpace: 'nowrap' }}>
            {signal.structure === 'BULLISH' ? '↑ BULL' : signal.structure === 'BEARISH' ? '↓ BEAR' : '— NEU'}
          </span>
        </div>

        {/* ICT SIGNALS */}
        <div style={{ ...cellBase }}>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'nowrap' }}>
            {!!signal.fvg_bull        && <span style={{ padding: '1px 4px', borderRadius: 3, fontSize: 8, background: '#00ff8815', color: '#00ff88', border: '1px solid #00ff8830' }}>FVG</span>}
            {!!signal.ob_bull && !signal.ob_mitigated && <span style={{ padding: '1px 4px', borderRadius: 3, fontSize: 8, background: '#00d4ff15', color: '#00d4ff', border: '1px solid #00d4ff30' }}>{signal.ob_price_at ? 'OB🎯' : 'OB'}</span>}
            {!!signal.sweep_bull      && <span style={{ padding: '1px 4px', borderRadius: 3, fontSize: 8, background: '#a78bfa15', color: '#a78bfa', border: '1px solid #a78bfa30' }}>SWP</span>}
            {!!signal.stop_hunt_bull  && <span style={{ padding: '1px 4px', borderRadius: 3, fontSize: 8, background: '#ff950015', color: '#ff9500', border: '1px solid #ff950030' }}>HUNT</span>}
            {!!signal.breakout_imminent && <span style={{ padding: '1px 4px', borderRadius: 3, fontSize: 8, background: '#ffcc0015', color: '#ffcc00', border: '1px solid #ffcc0030' }}>BRK</span>}
            {!signal.fvg_bull && !signal.ob_bull && !signal.sweep_bull && !signal.stop_hunt_bull && !signal.breakout_imminent && (
              <span style={{ fontSize: 9, color: '#2a3642' }}>–</span>
            )}
          </div>
        </div>

        {/* VOL */}
        <div style={{ ...cellBase, textAlign: 'right' }}>
          <span style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600, color: signal.vol_spike >= 2 ? '#ffcc00' : signal.vol_spike >= 1.5 ? '#00d4ff' : '#8b99a8' }}>
            {fmt(signal.vol_spike, 1)}x
          </span>
        </div>

        {/* FLOW */}
        <div style={{ ...cellBase, textAlign: 'center' }}>
          <span style={{ fontSize: 9, fontWeight: 600, color: flowCol, whiteSpace: 'nowrap' }}>
            {signal.flow_direction === 'in' ? '▲ IN' : signal.flow_direction === 'out' ? '▼ OUT' : '— NEU'}
          </span>
        </div>

        {/* 1D */}
        <div style={{ ...cellBase, textAlign: 'right' }}>
          {p1d != null
            ? <span style={{ fontFamily: 'monospace', fontSize: 10, color: p1d >= 0 ? '#00ff88' : '#ff3366' }}>{pct(p1d)}</span>
            : <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#2a3642' }}>—</span>}
        </div>

        {/* ADX */}
        <div style={{ ...cellBase, textAlign: 'right' }}>
          <span style={{ fontFamily: 'monospace', fontSize: 9, color: (signal.adx14 ?? 0) >= 25 ? '#00d4ff' : '#4a5a6a', whiteSpace: 'nowrap' }}>
            {signal.adx14 != null ? `ADX ${fmt(signal.adx14, 0)}` : ''}
          </span>
        </div>
      </div>

      {/* ── Row 2: sub ── */}
      <div style={{ display: 'grid', gridTemplateColumns: GRID, alignItems: 'start' }}>

        {/* # empty */}
        <div style={cell2Base} />

        {/* industry */}
        <div style={{ ...cell2Base }}>
          <span style={{ fontSize: 9, color: '#8b99a8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>{signal.industry}</span>
        </div>

        {/* ict score */}
        <div style={{ ...cell2Base, textAlign: 'right' }}>
          <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#4a5a6a' }}>ict {fmt(signal.ict_score)}</span>
        </div>

        {/* bos/choch */}
        <div style={{ ...cell2Base, textAlign: 'center' }}>
          <span style={{ fontSize: 8, color: '#4a5a6a' }}>
            {signal.bos_bull ? 'BOS↑' : signal.choch_bull ? 'CHoCH↑' : signal.bos_bear ? 'BOS↓' : ''}
          </span>
        </div>

        {/* conf */}
        <div style={{ ...cell2Base }}>
          <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#4a5a6a' }}>conf: {signal.ict_confluence}</span>
        </div>

        {/* VOL empty */}
        <div style={cell2Base} />

        {/* FLOW: acc/dist */}
        <div style={{ ...cell2Base, textAlign: 'center' }}>
          <span style={{ fontSize: 8, color: accCol }}>{accLabel}</span>
        </div>

        {/* 5D */}
        <div style={{ ...cell2Base, textAlign: 'right' }}>
          {p5d != null
            ? <span style={{ fontFamily: 'monospace', fontSize: 9, color: p5d >= 0 ? '#00ff8888' : '#ff336688' }}>{pct(p5d)}</span>
            : <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#2a3642' }}>—</span>}
        </div>

        {/* RSI */}
        <div style={{ ...cell2Base, textAlign: 'right' }}>
          {signal.rsi14 != null && (
            <span style={{ fontFamily: 'monospace', fontSize: 9, color: signal.rsi14 > 70 ? '#ff3366' : signal.rsi14 < 30 ? '#00ff88' : '#8b99a8', whiteSpace: 'nowrap' }}>
              RSI {fmt(signal.rsi14, 0)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function SignalDetail({ signal, onClose }: { signal: ICTSignal; onClose: () => void }) {
  const qCol = qualityColor(signal.setup_quality);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-2xl p-5 relative max-h-[85vh] overflow-y-auto"
        style={{ background: '#0a0f14', border: `1px solid ${qCol}40`, boxShadow: `0 0 40px ${qCol}20` }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold">{signal.symbol}</span>
              <span className="px-2 py-0.5 rounded font-bold text-sm" style={{ background: `${qCol}20`, color: qCol, border: `1px solid ${qCol}40` }}>
                {signal.setup_quality}
              </span>
              {signal.smart_money && <span title="Smart Money">💎</span>}
              {signal.wyckoff_spring && <span title="Wyckoff Spring">💧</span>}
            </div>
            <div className="text-xs mt-1" style={{ color: '#8b99a8' }}>{signal.industry}</div>
          </div>
          <button onClick={onClose} className="text-lg" style={{ color: '#4a5a6a' }}>✕</button>
        </div>

        {/* Scores */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          {[
            { label: 'ALPHA SCORE', val: fmt(signal.alpha_score), col: qCol },
            { label: 'ICT SCORE',   val: fmt(signal.ict_score),   col: '#00d4ff' },
            { label: 'CONFLUENCE',  val: `${signal.ict_confluence} signals`, col: '#a78bfa' },
          ].map(({ label, val, col }) => (
            <div key={label} className="rounded-lg p-2 text-center" style={{ background: '#0f1519', border: `1px solid ${col}30` }}>
              <div className="text-[8px] mb-1" style={{ color: '#4a5a6a', letterSpacing: '1px' }}>{label}</div>
              <div className="font-mono font-bold text-sm" style={{ color: col }}>{val}</div>
            </div>
          ))}
        </div>

        {/* Signal Breakdown */}
        <div className="mb-4">
          <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>SIGNAL BREAKDOWN</div>
          <div className="space-y-1.5">
            {Object.entries(signal.signal_breakdown).map(([key, val]) => {
              const barW = Math.max(val, 0);
              const col = val >= 70 ? '#00ff88' : val >= 55 ? '#00d4ff' : val >= 40 ? '#ffcc00' : '#ff3366';
              return (
                <div key={key} className="flex items-center gap-2">
                  <div className="text-[9px] w-32 shrink-0 font-mono" style={{ color: '#8b99a8' }}>
                    {key.replace(/_/g, ' ')}
                  </div>
                  <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${barW}%`, background: col, boxShadow: `0 0 4px ${col}60` }}
                    />
                  </div>
                  <div className="font-mono text-[9px] w-8 text-right" style={{ color: col }}>{val.toFixed(0)}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ICT Signals */}
        <div className="mb-4">
          <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>ICT SIGNALS</div>
          <div className="grid grid-cols-2 gap-1.5 text-[10px]">
            {[
              { label: 'Structure',     val: signal.structure,      on: signal.structure === 'BULLISH', col: '#00ff88' },
              { label: 'BOS Bull',      val: signal.bos_bull ? 'YES' : 'no', on: signal.bos_bull, col: '#00ff88' },
              { label: 'CHoCH Bull',    val: signal.choch_bull ? 'YES' : 'no', on: signal.choch_bull, col: '#00ff88' },
              { label: 'FVG Bull',      val: signal.fvg_bull ? 'YES' : 'no', on: !!signal.fvg_bull, col: '#00d4ff' },
              { label: 'Order Block',   val: signal.ob_bull ? (signal.ob_price_at ? 'AT OB 🎯' : 'YES') : 'no', on: signal.ob_bull, col: '#00d4ff' },
              { label: 'Liq Sweep',     val: signal.sweep_bull ? 'YES' : 'no', on: signal.sweep_bull, col: '#a78bfa' },
              { label: 'Stop Hunt',     val: signal.stop_hunt_bull ? 'YES' : 'no', on: signal.stop_hunt_bull, col: '#ff9500' },
              { label: 'Wyckoff Spring',val: signal.wyckoff_spring ? 'YES' : 'no', on: signal.wyckoff_spring, col: '#a78bfa' },
              { label: 'Vol Spike',     val: `${fmt(signal.vol_spike)}x`, on: signal.vol_spike >= 1.5, col: '#ffcc00' },
              { label: 'Smart Money',   val: signal.smart_money ? 'YES' : 'no', on: signal.smart_money, col: '#ffcc00' },
              { label: 'Flow',          val: signal.flow_direction.toUpperCase(), on: signal.flow_direction === 'in', col: '#00ff88' },
              { label: 'Breakout',      val: signal.breakout_imminent ? 'IMMINENT' : 'no', on: signal.breakout_imminent, col: '#ffcc00' },
            ].map(({ label, val, on, col }) => (
              <div key={label} className="flex items-center justify-between px-2 py-1 rounded" style={{ background: '#0f1519', opacity: on ? 1 : 0.4 }}>
                <span style={{ color: '#8b99a8' }}>{label}</span>
                <span className="font-mono font-semibold text-[9px]" style={{ color: on ? col : '#4a5a6a' }}>{val}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Top signals text */}
        {signal.top_signals.length > 0 && (
          <div>
            <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>TOP SIGNALS</div>
            <ul className="space-y-1">
              {signal.top_signals.map((s, i) => (
                <li key={i} className="flex items-start gap-2 text-[10px]" style={{ color: '#8b99a8' }}>
                  <span style={{ color: '#00d4ff' }}>•</span> {s}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

type QFilter = 'ALL' | 'A+' | 'A' | 'B' | 'C';

export default function ICTDashboard() {
  const [data, setData]           = useState<ICTSignalsResponse | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [qFilter, setQFilter]     = useState<QFilter>('ALL');
  const [search, setSearch]       = useState('');
  const [selected, setSelected]   = useState<ICTSignal | null>(null);
  const [actionOnly, setActionOnly] = useState(false);

  useEffect(() => {
    fetch('/api/ict-signals')
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => { setError('Không thể tải ICT Signals'); setLoading(false); });
  }, []);

  const signals = useMemo(() => {
    if (!data?.signals) return [];
    let s = data.signals;
    if (actionOnly) s = s.filter((x) => x.actionable);
    if (qFilter !== 'ALL') s = s.filter((x) => x.setup_quality === qFilter);
    if (search) {
      const q = search.toLowerCase();
      s = s.filter((x) => x.symbol.toLowerCase().includes(q) || x.industry.toLowerCase().includes(q));
    }
    return s;
  }, [data, qFilter, search, actionOnly]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin mx-auto mb-3" style={{ borderColor: '#00d4ff', borderTopColor: 'transparent' }} />
          <p className="text-xs" style={{ color: '#4a5a6a' }}>Đang tải ICT Signals...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <p className="text-xs mb-2" style={{ color: '#ff3366' }}>{error || 'Không có dữ liệu ICT'}</p>
          <p className="text-[10px]" style={{ color: '#4a5a6a' }}>ICT Scanner sẽ chạy sau khi push code lên repo và workflow hoàn tất</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Regime Banner */}
      <RegimeBanner regime={data.regime} />

      {/* Market Stats */}
      {data.market_stats?.total_symbols > 0 && (
        <MarketStats stats={data.market_stats} qDist={data.quality_distribution} />
      )}

      {/* Sector Rotation */}
      <SectorBadges rotation={data.sector_rotation} />

      {/* Filters */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {/* Quality filter */}
        {(['ALL', 'A+', 'A', 'B', 'C'] as QFilter[]).map((q) => {
          const col = q === 'ALL' ? '#8b99a8' : qualityColor(q);
          const active = qFilter === q;
          return (
            <button
              key={q}
              onClick={() => setQFilter(q)}
              className="px-2.5 py-1 rounded-md text-[10px] font-bold transition-all"
              style={{
                background: active ? `${col}25` : 'transparent',
                color: active ? col : '#4a5a6a',
                border: `1px solid ${active ? col + '60' : '#1e2832'}`,
              }}
            >
              {q}
              {q !== 'ALL' && data.quality_distribution[q] != null && data.quality_distribution[q] > 0 && (
                <span className="ml-1 font-mono" style={{ color: active ? col : '#2a3642' }}>
                  {data.quality_distribution[q]}
                </span>
              )}
            </button>
          );
        })}

        {/* Actionable toggle */}
        <button
          onClick={() => setActionOnly(!actionOnly)}
          className="px-2.5 py-1 rounded-md text-[10px] font-bold transition-all"
          style={{
            background: actionOnly ? '#00ff8825' : 'transparent',
            color: actionOnly ? '#00ff88' : (data.regime.regime === 'BEAR' ? '#ff336688' : '#4a5a6a'),
            border: `1px solid ${actionOnly ? '#00ff8860' : '#1e2832'}`,
          }}
          title={data.regime.regime === 'BEAR' ? 'BEAR market: 0 actionable — bỏ filter này để xem watchlist' : ''}
        >
          ⚡ {data.regime.regime === 'BEAR' ? 'ACTIONABLE (BEAR: 0)' : `ACTIONABLE${data.actionable_count > 0 ? ` (${data.actionable_count})` : ''}`}
        </button>

        {/* Search */}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Tìm symbol, ngành..."
          className="ml-auto px-3 py-1 rounded-lg text-xs outline-none"
          style={{ background: '#0f1519', border: '1px solid #1e2832', color: '#e8edf2', width: 180 }}
        />

        <span className="text-[10px] font-mono" style={{ color: '#4a5a6a' }}>
          {signals.length} signals
        </span>
      </div>

      {/* BEAR Watchlist Banner */}
      {data.regime.regime === 'BEAR' && (
        <div className="rounded-xl p-3 mb-3 flex items-start gap-3" style={{ background: '#ff336608', border: '1px solid #ff336630' }}>
          <span className="text-base shrink-0">⚠️</span>
          <div>
            <div className="text-[10px] font-bold mb-1" style={{ color: '#ff9500' }}>
              BEAR MARKET — WATCHLIST MODE
            </div>
            <div className="text-[9px] leading-relaxed" style={{ color: '#8b99a8' }}>
              Bull weight <span className="font-mono font-bold" style={{ color: '#ffcc00' }}>{(data.regime.bull_weight * 100).toFixed(0)}%</span> — 
              Tất cả setups bị SKIP. Danh sách này là <strong style={{ color: '#e8edf2' }}>watchlist chuẩn bị</strong>: 
              stocks có relative strength cao nhất vs thị trường, sẽ breakout sớm nhất khi phase đổi.
              Chờ bull_weight &gt; 30% để hành động.
            </div>
          </div>
        </div>
      )}

      {/* Signal Table */}
      <div className="rounded-xl overflow-hidden" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
        {/* Header */}
        <div style={{ display: 'grid', gridTemplateColumns: GRID, background: '#0a0f14', padding: '6px 0', borderBottom: '1px solid #1e2832' }}>
          {([
            { label: '#',           align: 'center' },
            { label: 'SYMBOL',      align: 'left'   },
            { label: 'SCORE',       align: 'right'  },
            { label: 'STRUCTURE',   align: 'center' },
            { label: 'ICT SIGNALS', align: 'left'   },
            { label: 'VOL',         align: 'right'  },
            { label: 'FLOW',        align: 'center' },
            { label: '1D / 5D',     align: 'right'  },
            { label: 'ADX/RSI',     align: 'right'  },
          ] as const).map(({ label, align }) => (
            <div key={label} style={{ padding: '0 8px', fontSize: 9, fontWeight: 500, letterSpacing: '0.8px', color: '#4a5a6a', textAlign: align, overflow: 'hidden', whiteSpace: 'nowrap' }}>
              {label}
            </div>
          ))}
        </div>
        {/* Rows */}
        {signals.length === 0 ? (
          <div className="p-8 text-center text-xs" style={{ color: '#4a5a6a' }}>
            {data.regime.regime === 'BEAR'
              ? '⚠️ BEAR market — Tất cả signals bị SKIP do bull_weight=0.3. Bỏ filter "ACTIONABLE" để xem watchlist chuẩn bị.'
              : 'Không có signals phù hợp với filter hiện tại'}
          </div>
        ) : (
          signals.map((s) => {
            const sym: ICTSignal = s as ICTSignal;
            return (
              <SignalRow
                key={sym.symbol}
                signal={sym}
                onClick={() => setSelected(sym)}
              />
            );
          })
        )}
      </div>

      {/* Disclaimer */}
      <div className="mt-3 text-[9px] text-center" style={{ color: '#2a3642' }}>
        ICT Framework — Smart Money Concepts. Không phải khuyến nghị đầu tư.
        Bull weight: {(data.regime.bull_weight * 100).toFixed(0)}% • {new Date(data.generated_at).toLocaleString('vi-VN')}
      </div>

      {/* Detail Modal */}
      {selected && <SignalDetail signal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
