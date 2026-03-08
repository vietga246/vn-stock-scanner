'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  X,
  TrendingUp,
  TrendingDown,
  Activity,
  Shield,
  Globe,
  Zap,
  Target,
  BarChart3,
  AlertTriangle,
  CheckCircle,
  MinusCircle,
  ArrowUpCircle,
  ArrowDownCircle,
  Info,
} from 'lucide-react';
import type { Stock, AIAnalysis, ICTSignal, StockDetail, IncomeRecord, BalanceRecord, CashflowRecord, RatioRecord } from '@/lib/types';
import { generateAnalysis, getRecommendationDisplay } from '@/lib/analysis';
import { generateDeskAnalysis } from '@/lib/desk_analysis';
import type { DeskAnalysis, SignalGroup, SignalItem, TradeSetup, TradeAction } from '@/lib/types';
import { formatPrice, formatPercent, getScoreColor, getTierColor, getStockDetails } from '@/lib/api';
import Sparkline from './Sparkline';
import CandlestickChart from './CandlestickChart';

interface StockModalProps {
  stock: Stock | null;
  sectorStatus?: 'accumulating' | 'distributing' | 'neutral';
  preloadedAnalysis?: AIAnalysis;
  ictSignal?: ICTSignal;
  onClose: () => void;
}

// ============ Module-level sub-components (Q5 fix) ============

function ScoreCircle({
  value,
  label,
  Icon,
}: {
  value: number;
  label: string;
  Icon: any;
}) {
  const radius = 20;
  const sw = 3;
  const circ = 2 * Math.PI * radius;
  const prog = ((value || 0) / 100) * circ;
  const color = getScoreColor(value);
  const sz = (radius + sw) * 2;
  const cx = radius + sw;
  const filterStyle = 'drop-shadow(0 0 4px ' + color + '50)';

  return (
    <div className="text-center">
      <div className="relative mx-auto" style={{ width: sz, height: sz }}>
        <svg width={sz} height={sz} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={cx} cy={cx} r={radius} fill="none" stroke="#1e2832" strokeWidth={sw} />
          <circle
            cx={cx}
            cy={cx}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={sw}
            strokeDasharray={circ}
            strokeDashoffset={circ - prog}
            strokeLinecap="round"
            style={{
              filter: filterStyle,
              transition: 'stroke-dashoffset 0.6s ease',
            }}
          />
        </svg>
        <div
          className="absolute inset-0 flex items-center justify-center font-mono font-bold text-[10px]"
          style={{ color, textShadow: '0 0 6px ' + color + '50' }}
        >
          {value?.toFixed(0)}
        </div>
      </div>
      <div className="flex items-center justify-center gap-1 mt-1.5">
        <Icon size={9} color="#4a5a6a" />
        <span className="text-[9px]" style={{ color: '#4a5a6a' }}>
          {label}
        </span>
      </div>
    </div>
  );
}

function HighlightItem({ item }: { item: { text: string; type: string } }) {
  const colors: Record<string, { bg: string; border: string; text: string; icon: any }> = {
    positive: { bg: '#00ff8815', border: '#00ff8840', text: '#00ff88', icon: CheckCircle },
    negative: { bg: '#ff336615', border: '#ff336640', text: '#ff3366', icon: AlertTriangle },
    neutral: { bg: '#ffcc0015', border: '#ffcc0040', text: '#ffcc00', icon: MinusCircle },
    warning: { bg: '#ff990015', border: '#ff990040', text: '#ff9900', icon: AlertTriangle },
  };
  const style = colors[item.type] || colors.neutral;
  const IconComp = style.icon;

  return (
    <div
      className="flex items-start gap-2 p-2 rounded-md mb-1.5"
      style={{ background: style.bg, border: '1px solid ' + (style.border) }}
    >
      <IconComp size={12} color={style.text} className="mt-0.5 flex-shrink-0" />
      <span className="text-[11px]" style={{ color: style.text }}>
        {item.text}
      </span>
    </div>
  );
}


function AnalysisTab({ stock, deskAnalysis }: { stock: Stock; deskAnalysis: DeskAnalysis }) {
  const d = deskAnalysis;

  // Action config
  const actionCfg: Record<string, { label: string; color: string; bg: string }> = {
    STRONG_BUY: { label: 'STRONG BUY',  color: '#00ff88', bg: '#00ff8820' },
    BUY:        { label: 'BUY',          color: '#00ff88', bg: '#00ff8815' },
    ACCUMULATE: { label: 'ACCUMULATE',   color: '#00d4ff', bg: '#00d4ff15' },
    HOLD:       { label: 'HOLD',         color: '#ffcc00', bg: '#ffcc0015' },
    REDUCE:     { label: 'REDUCE',       color: '#ff9500', bg: '#ff950015' },
    SELL:       { label: 'SELL',         color: '#ff3366', bg: '#ff336615' },
    AVOID:      { label: 'AVOID',        color: '#ff3366', bg: '#ff336615' },
  };
  const convCfg: Record<string, { label: string; color: string }> = {
    HIGH:   { label: 'HIGH CONVICTION',   color: '#00ff88' },
    MEDIUM: { label: 'MEDIUM CONVICTION', color: '#ffcc00' },
    LOW:    { label: 'LOW CONVICTION',    color: '#8b99a8' },
  };
  const strengthCfg: Record<string, { color: string; bar: number }> = {
    STRONG:   { color: '#00ff88', bar: 90 },
    MODERATE: { color: '#00d4ff', bar: 65 },
    NEUTRAL:  { color: '#8b99a8', bar: 50 },
    WEAK:     { color: '#ff9500', bar: 35 },
    NEGATIVE: { color: '#ff3366', bar: 15 },
  };
  const statusStyle: Record<string, { color: string; bg: string }> = {
    positive: { color: '#00ff88', bg: '#00ff8812' },
    negative: { color: '#ff3366', bg: '#ff336612' },
    neutral:  { color: '#8b99a8', bg: '#1e2832' },
    warning:  { color: '#ff9500', bg: '#ff950012' },
  };

  const ac = actionCfg[d.setup.action] ?? actionCfg.HOLD;
  const cc = convCfg[d.setup.conviction] ?? convCfg.LOW;

  return (
    <div>
      {/* ── 1. Headline + Action ─────────────────────────────── */}
      <div className="rounded-xl p-3 mb-3"
        style={{ background: ac.bg, border: '1px solid ' + (ac.color) + '30' }}>
        <div className="flex items-start justify-between gap-2 mb-2">
          <div>
            <div className="font-bold text-sm" style={{ color: ac.color }}>{d.headline}</div>
            <div className="text-[9px] mt-0.5 font-semibold tracking-widest" style={{ color: cc.color }}>{cc.label}</div>
          </div>
          <div className="px-3 py-1.5 rounded-lg font-black text-sm shrink-0"
            style={{ background: ac.color, color: '#05080a' }}>
            {ac.label}
          </div>
        </div>
        <p className="text-[11px] leading-relaxed" style={{ color: '#c8d4e0' }}>{d.narrative}</p>
      </div>

      {/* ── 2. Trade Setup ───────────────────────────────────── */}
      {(d.setup.entry_zone || d.setup.stop_loss) && (
        <div className="rounded-xl p-3 mb-3"
          style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
          <div className="text-[9px] font-semibold tracking-widest mb-2" style={{ color: '#4a5a6a' }}>TRADE SETUP</div>
          <div className="grid grid-cols-2 gap-2 text-[10px]">
            {[
              { label: '📍 Entry Zone',     val: d.setup.entry_zone    },
              { label: '🛑 Stop Loss',      val: d.setup.stop_loss     },
              { label: '🎯 Target 1',       val: d.setup.target_1      },
              { label: '🚀 Target 2',       val: d.setup.target_2      },
              { label: '⚖️ Risk / Reward',  val: d.setup.risk_reward   },
              { label: '⏱ Time Horizon',   val: d.setup.time_horizon  },
            ].filter(r => r.val).map(({ label, val }) => (
              <div key={label} className="p-2 rounded-lg" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
                <div style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono font-semibold mt-0.5" style={{ color: '#e8edf2' }}>{val}</div>
              </div>
            ))}
          </div>
          {d.setup.invalidation && (
            <div className="mt-2 p-2 rounded-lg text-[10px]"
              style={{ background: '#ff336610', border: '1px solid #ff336630' }}>
              <span style={{ color: '#ff3366' }}>⚡ Invalidation: </span>
              <span style={{ color: '#c8d4e0' }}>{d.setup.invalidation}</span>
            </div>
          )}
        </div>
      )}

      {/* ── 3. Catalysts & Risks ────────────────────────────── */}
      {(d.catalysts.length > 0 || d.key_risks.length > 0) && (
        <div className="grid grid-cols-2 gap-2 mb-3">
          {d.catalysts.length > 0 && (
            <div className="rounded-xl p-2.5" style={{ background: '#00ff8808', border: '1px solid #00ff8830' }}>
              <div className="text-[9px] font-semibold mb-1.5 tracking-widest" style={{ color: '#00ff88' }}>✅ CATALYSTS</div>
              <ul className="space-y-1">
                {d.catalysts.map((c, i) => (
                  <li key={i} className="text-[10px] leading-snug flex gap-1.5" style={{ color: '#c8d4e0' }}>
                    <span style={{ color: '#00ff88' }}>+</span>{c}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {d.key_risks.length > 0 && (
            <div className="rounded-xl p-2.5" style={{ background: '#ff336808', border: '1px solid #ff336830' }}>
              <div className="text-[9px] font-semibold mb-1.5 tracking-widest" style={{ color: '#ff3366' }}>⚠️ KEY RISKS</div>
              <ul className="space-y-1">
                {d.key_risks.map((r, i) => (
                  <li key={i} className="text-[10px] leading-snug flex gap-1.5" style={{ color: '#c8d4e0' }}>
                    <span style={{ color: '#ff3366' }}>–</span>{r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── 4. Signal Groups ─────────────────────────────────── */}
      <div className="text-[9px] font-semibold tracking-widest mb-2" style={{ color: '#4a5a6a' }}>
        SIGNAL ANALYSIS — {d.signal_groups.length} GROUPS
      </div>
      <div className="space-y-2">
        {d.signal_groups.map((group) => {
          const sc = strengthCfg[group.strength] ?? strengthCfg.NEUTRAL;
          return (
            <div key={group.id} className="rounded-xl overflow-hidden"
              style={{ border: '1px solid ' + (sc.color) + '25', background: '#0a0f14' }}>
              {/* Group header */}
              <div className="flex items-center justify-between px-3 py-2"
                style={{ background: (sc.color) + '08', borderBottom: '1px solid ' + (sc.color) + '20' }}>
                <div className="flex items-center gap-2">
                  <span className="text-sm">{group.icon}</span>
                  <span className="text-[10px] font-bold tracking-widest" style={{ color: sc.color }}>
                    {group.label}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {/* Score bar */}
                  <div className="w-16 h-1 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                    <div className="h-full rounded-full"
                      style={{ width: (group.score) + '%', background: sc.color, boxShadow: '0 0 4px ' + (sc.color) + '60' }} />
                  </div>
                  <span className="font-mono font-bold text-[10px]" style={{ color: sc.color }}>
                    {group.strength}
                  </span>
                </div>
              </div>
              {/* Signal items */}
              <div className="divide-y" style={{ borderColor: '#1e2832' }}>
                {group.signals.map((sig, i) => {
                  const ss = statusStyle[sig.status] ?? statusStyle.neutral;
                  return (
                    <div key={i} className="flex items-start justify-between px-3 py-2 gap-2"
                      style={{ background: i % 2 === 0 ? 'transparent' : '#0f151905' }}>
                      <div className="flex items-start gap-2 flex-1 min-w-0">
                        <div className="w-1 h-1 rounded-full mt-1.5 shrink-0"
                          style={{ background: ss.color }} />
                        <div className="min-w-0">
                          <div className="text-[9px] font-semibold" style={{ color: '#8b99a8' }}>{sig.label}</div>
                          {sig.note && <div className="text-[9px] mt-0.5 leading-snug" style={{ color: '#4a5a6a' }}>{sig.note}</div>}
                        </div>
                      </div>
                      <div className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold shrink-0"
                        style={{ background: ss.bg, color: ss.color, border: '1px solid ' + (ss.color) + '30' }}>
                        {sig.value}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ICTTab({ ictSignal }: { ictSignal: ICTSignal }) {
  const qColors: Record<string, string> = { 'A+': '#00ff88', 'A': '#00d4ff', 'B': '#a78bfa', 'C': '#ffcc00', 'SKIP': '#4a5a6a' };
  const qCol = qColors[ictSignal.setup_quality] || '#4a5a6a';
  const structCol = ictSignal.structure === 'BULLISH' ? '#00ff88' : ictSignal.structure === 'BEARISH' ? '#ff3366' : '#4a5a6a';
  return (
    <div>
      {/* ICT Score summary */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        {[
          { label: 'ALPHA SCORE', val: ictSignal.alpha_score.toFixed(1), col: qCol },
          { label: 'ICT SCORE',   val: ictSignal.ict_score.toFixed(1),   col: '#00d4ff' },
          { label: 'QUALITY',     val: ictSignal.setup_quality,          col: qCol },
        ].map(({ label, val, col }) => (
          <div key={label} className="rounded-lg p-2 text-center" style={{ background: '#0a0f14', border: '1px solid ' + (col) + '30' }}>
            <div className="text-[8px] mb-1 tracking-widest" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color: col }}>{val}</div>
          </div>
        ))}
      </div>

      {/* Market Structure */}
      <div className="p-2.5 rounded-lg mb-2" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>MARKET STRUCTURE</div>
        <div className="flex items-center gap-2 mb-2">
          <span className="font-bold text-sm" style={{ color: structCol }}>
            {ictSignal.structure === 'BULLISH' ? '↑ BULLISH' : ictSignal.structure === 'BEARISH' ? '↓ BEARISH' : '— NEUTRAL'}
          </span>
          {(ictSignal.smart_money || ictSignal.wyckoff_spring) && (
            <span className="text-base">{ictSignal.smart_money ? '💎' : ''}{ictSignal.wyckoff_spring ? '💧' : ''}</span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          {[
            { label: 'BOS Bullish',   on: ictSignal.bos_bull,         col: '#00ff88' },
            { label: 'BOS Bearish',   on: ictSignal.bos_bear,         col: '#ff3366' },
            { label: 'CHoCH Bull',    on: ictSignal.choch_bull,       col: '#00ff88' },
            { label: 'CHoCH Bear',    on: ictSignal.choch_bear,       col: '#ff3366' },
          ].map(({ label, on, col }) => (
            <div key={label} className="flex items-center justify-between px-2 py-1 rounded" style={{ background: '#0f1519', opacity: on ? 1 : 0.35 }}>
              <span style={{ color: '#8b99a8' }}>{label}</span>
              <span className="font-bold text-[9px]" style={{ color: on ? col : '#2a3642' }}>{on ? 'YES' : 'no'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ICT Confluences */}
      <div className="p-2.5 rounded-lg mb-2" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>ICT CONFLUENCES ({ictSignal.ict_confluence} signals)</div>
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          {[
            { label: 'Fair Value Gap', on: !!ictSignal.fvg_bull,          col: '#00ff88', extra: '' },
            { label: 'Order Block',    on: ictSignal.ob_bull && !ictSignal.ob_mitigated, col: '#00d4ff', extra: ictSignal.ob_price_at ? ' 🎯' : '' },
            { label: 'Liq Sweep',      on: ictSignal.sweep_bull,           col: '#a78bfa', extra: '' },
            { label: 'Stop Hunt',      on: ictSignal.stop_hunt_bull,       col: '#ff9500', extra: '' },
            { label: 'Wyckoff Spring', on: ictSignal.wyckoff_spring,       col: '#a78bfa', extra: '' },
            { label: 'Smart Money',    on: ictSignal.smart_money,          col: '#ffcc00', extra: '' },
            { label: 'Breakout',       on: ictSignal.breakout_imminent,    col: '#ffcc00', extra: ' imminent' },
            { label: 'Flow IN',        on: ictSignal.flow_direction === 'in', col: '#00ff88', extra: '' },
          ].map(({ label, on, col, extra }) => (
            <div key={label} className="flex items-center justify-between px-2 py-1 rounded" style={{ background: '#0f1519', opacity: on ? 1 : 0.3 }}>
              <span style={{ color: '#8b99a8' }}>{label}</span>
              <span className="font-bold text-[9px]" style={{ color: on ? col : '#2a3642' }}>{on ? 'YES' + (extra) : 'no'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Signal Breakdown bars */}
      <div className="p-2.5 rounded-lg mb-2" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>SIGNAL BREAKDOWN</div>
        <div className="space-y-1.5">
          {Object.entries(ictSignal.signal_breakdown).map(([key, val]) => {
            const col = val >= 70 ? '#00ff88' : val >= 55 ? '#00d4ff' : val >= 40 ? '#ffcc00' : '#ff3366';
            return (
              <div key={key} className="flex items-center gap-2">
                <div className="text-[9px] w-28 shrink-0 font-mono" style={{ color: '#8b99a8' }}>
                  {key.replace(/_/g, ' ')}
                </div>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                  <div className="h-full rounded-full transition-all" style={{ width: (Math.max(val, 0)) + '%', background: col, boxShadow: '0 0 4px ' + (col) + '60' }} />
                </div>
                <div className="font-mono text-[9px] w-7 text-right" style={{ color: col }}>{val.toFixed(0)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top signals */}
      {ictSignal.top_signals.length > 0 && (
        <div className="p-2.5 rounded-lg" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[9px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>TOP SIGNALS</div>
          <ul className="space-y-1">
            {ictSignal.top_signals.map((sig, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[10px]" style={{ color: '#8b99a8' }}>
                <span style={{ color: '#00d4ff' }}>•</span>{sig}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─── Finance Tab ─────────────────────────────────────────────────────────────
function FinanceTab({ detail, detailLoading }: { detail: StockDetail | null; detailLoading: boolean }) {
  const fmtB = (v: number | null | undefined) => {
    if (v == null) return '–';
    return Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'T' : v.toFixed(0) + 'B';
  };
  const colPct = (v: number) => v >= 20 ? '#00ff88' : v >= 10 ? '#00d4ff' : v >= 0 ? '#ffcc00' : '#ff3366';

  const income = [...detail.income].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter)).slice(0, 6);
  const ratio = [...detail.ratio].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter));
  const latestR = ratio[0] ?? null;
  const cf = [...detail.cashflow].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter)).slice(0, 6);

  return (
    <div className="space-y-3">
      {latestR && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[9px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
            CHỈ SỐ ĐỊNH GIÁ & HIỆU QUẢ
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'P/E', val: latestR.pe != null ? latestR.pe.toFixed(1) : '–', note: 'x', color: undefined as string | undefined },
              { label: 'P/B', val: latestR.pb != null ? latestR.pb.toFixed(2) : '–', note: 'x', color: undefined as string | undefined },
              { label: 'EV/EBITDA', val: latestR.ev_ebitda != null ? latestR.ev_ebitda.toFixed(1) : '–', note: 'x', color: undefined as string | undefined },
              { label: 'ROE', val: latestR.roe != null ? latestR.roe.toFixed(1) : '–', note: '%', color: colPct(latestR.roe ?? 0) },
              { label: 'ROA', val: latestR.roa != null ? latestR.roa.toFixed(1) : '–', note: '%', color: colPct(latestR.roa ?? 0) },
              { label: 'ROIC', val: latestR.roic != null ? latestR.roic.toFixed(1) : '–', note: '%', color: colPct(latestR.roic ?? 0) },
              { label: 'Gross Margin', val: latestR.gross_margin != null ? latestR.gross_margin.toFixed(1) : '–', note: '%', color: colPct(latestR.gross_margin ?? 0) },
              { label: 'Net Margin', val: latestR.net_margin != null ? latestR.net_margin.toFixed(1) : '–', note: '%', color: colPct(latestR.net_margin ?? 0) },
              { label: 'D/E', val: latestR.debt_equity != null ? latestR.debt_equity.toFixed(2) : '–', note: 'x', color: undefined as string | undefined },
            ].map(({ label, val, note, color }) => (
              <div key={label} className="p-2 rounded-lg text-center" style={{ background: '#0d1520' }}>
                <div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono text-xs font-bold" style={{ color: color || '#e2e8f0' }}>
                  {val}<span className="text-[9px] ml-0.5" style={{ color: '#4a5a6a' }}>{note}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {income.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[9px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            KẾT QUẢ KINH DOANH
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr style={{ borderBottom: '1px solid #1e2832' }}>
                  <th className="p-2 text-left font-semibold" style={{ color: '#4a5a6a' }}>Chỉ tiêu</th>
                  {income.map((r) => (
                    <th key={r.year + '-' + r.quarter} className="p-2 text-right font-semibold" style={{ color: '#4a5a6a' }}>
                      Q{r.quarter}/{r.year}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: 'Doanh thu', key: 'revenue' as const },
                  { label: 'Lợi nhuận', key: 'net_income' as const },
                ].map(({ label, key }) => (
                  <tr key={label} style={{ borderBottom: '1px solid #0d1520' }}>
                    <td className="p-2 font-medium" style={{ color: '#8b99a8' }}>{label}</td>
                    {income.map((r) => (
                      <td key={r.year + '-' + r.quarter} className="p-2 text-right font-mono" style={{ color: '#e2e8f0' }}>{fmtB(r[key])}</td>
                    ))}
                  </tr>
                ))}
                <tr style={{ borderBottom: '1px solid #0d1520' }}>
                  <td className="p-2 font-medium" style={{ color: '#8b99a8' }}>Tăng trưởng DT</td>
                  {income.map((r) => (
                    <td key={r.year + '-' + r.quarter} className="p-2 text-right font-mono" style={{ color: r.revenue_growth != null ? (r.revenue_growth >= 0 ? '#00ff88' : '#ff3366') : '#4a5a6a' }}>
                      {r.revenue_growth != null ? (r.revenue_growth >= 0 ? '+' : '') + r.revenue_growth.toFixed(1) + '%' : '–'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
      {cf.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[9px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            DÒNG TIỀN
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr style={{ borderBottom: '1px solid #1e2832' }}>
                  <th className="p-2 text-left font-semibold" style={{ color: '#4a5a6a' }}>Chỉ tiêu</th>
                  {cf.map((r) => (
                    <th key={r.year + '-' + r.quarter} className="p-2 text-right font-semibold" style={{ color: '#4a5a6a' }}>
                      Q{r.quarter}/{r.year}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: 'HĐKD', key: 'cfo' as const },
                  { label: 'HĐĐT', key: 'cfi' as const },
                  { label: 'HĐTC', key: 'cff' as const },
                  { label: 'CapEx', key: 'capex' as const },
                ].map(({ label, key }) => (
                  <tr key={label} style={{ borderBottom: '1px solid #0d1520' }}>
                    <td className="p-2 font-medium" style={{ color: '#8b99a8' }}>{label}</td>
                    {cf.map((r) => (
                      <td key={r.year + '-' + r.quarter} className="p-2 text-right font-mono" style={{ color: r[key] == null ? '#4a5a6a' : r[key] > 0 ? '#00ff88' : '#ff3366' }}>
                        {r[key] == null ? '–' : (r[key] > 0 ? '+' : '') + fmtB(r[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}


// ─── Trading Tab ─────────────────────────────────────────────────────────────
function TradingTab({ stock }: { stock: Stock }) {
  const history = stock.price_history ?? [];
  const volumes = stock.volume_history ?? [];
  const dates = stock.dates ?? [];
  const price = stock.close || stock.price || 0;
  const chg1d = stock.change_1d ?? 0;
  const priceItems = [
    { label: 'Giá hiện tại', val: formatPrice(price), color: chg1d >= 0 ? '#00ff88' : '#ff3366' },
    { label: 'Thay đổi 1D', val: (chg1d >= 0 ? '+' : '') + chg1d.toFixed(2) + '%', color: chg1d >= 0 ? '#00ff88' : '#ff3366' },
    { label: 'Vol Ratio', val: stock.vol_ratio != null ? stock.vol_ratio.toFixed(2) + 'x' : '–', color: '#00d4ff' },
    { label: 'ATR (14)', val: stock.atr14 != null ? stock.atr14.toFixed(2) : '–', color: '#ffcc00' },
    { label: 'BB Width', val: stock.bb_width != null ? stock.bb_width.toFixed(1) : '–', color: '#a78bfa' },
    { label: 'MACD Hist', val: stock.macd_hist != null ? stock.macd_hist.toFixed(3) : '–', color: (stock.macd_hist ?? 0) > 0 ? '#00ff88' : '#ff3366' },
  ];
  const fnet = stock.foreign_net_7d ?? 0;
  const foreignItems = [
    { label: 'NN Mua', val: stock.foreign_buy_qty != null ? (stock.foreign_buy_qty / 1000).toFixed(0) + 'K' : '–', color: '#00ff88' },
    { label: 'NN Bán', val: stock.foreign_sell_qty != null ? (stock.foreign_sell_qty / 1000).toFixed(0) + 'K' : '–', color: '#ff3366' },
    { label: 'NN Ròng 7D', val: (fnet >= 0 ? '+' : '') + fnet.toFixed(1) + 'B', color: fnet >= 0 ? '#00ff88' : '#ff3366' },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {priceItems.map(({ label, val, color }) => (
          <div key={label} className="p-2.5 rounded-lg" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
            <div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>
      {history.length > 1 && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[9px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
            GIÁ {history.length} PHIÊN GẦN NHẤT
          </div>
          <Sparkline data={history} volume={volumes} dates={dates} width={580} height={100} />
        </div>
      )}
      <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="grid grid-cols-2" style={{ borderBottom: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[9px] font-semibold tracking-widest text-center" style={{ color: '#00ff88', borderRight: '1px solid #1e2832' }}>BÊN MUA</div>
          <div className="px-3 py-2 text-[9px] font-semibold tracking-widest text-center" style={{ color: '#ff3366' }}>BÊN BÁN</div>
        </div>
        {[0, 1, 2].map(i => (
          <div key={i} className="grid grid-cols-2" style={{ borderBottom: i < 2 ? '1px solid #1e2832' : 'none' }}>
            <div className="flex justify-between px-3 py-1.5" style={{ borderRight: '1px solid #1e2832' }}>
              <span className="font-mono text-[11px]" style={{ color: '#00ff88' }}>
                {i === 0 && stock.bid1_price != null ? formatPrice(stock.bid1_price) : i === 1 && stock.bid2_price != null ? formatPrice(stock.bid2_price) : i === 2 && stock.bid3_price != null ? formatPrice(stock.bid3_price) : '–'}
              </span>
              <span className="font-mono text-[10px]" style={{ color: '#8b99a8' }}>
                {i === 0 && stock.bid1_volume != null ? (stock.bid1_volume / 1000).toFixed(0) + 'K' : i === 1 && stock.bid2_volume != null ? (stock.bid2_volume / 1000).toFixed(0) + 'K' : i === 2 && stock.bid3_volume != null ? (stock.bid3_volume / 1000).toFixed(0) + 'K' : '–'}
              </span>
            </div>
            <div className="flex justify-between px-3 py-1.5">
              <span className="font-mono text-[11px]" style={{ color: '#ff3366' }}>
                {i === 0 && stock.ask1_price != null ? formatPrice(stock.ask1_price) : i === 1 && stock.ask2_price != null ? formatPrice(stock.ask2_price) : i === 2 && stock.ask3_price != null ? formatPrice(stock.ask3_price) : '–'}
              </span>
              <span className="font-mono text-[10px]" style={{ color: '#8b99a8' }}>
                {i === 0 && stock.ask1_volume != null ? (stock.ask1_volume / 1000).toFixed(0) + 'K' : i === 1 && stock.ask2_volume != null ? (stock.ask2_volume / 1000).toFixed(0) + 'K' : i === 2 && stock.ask3_volume != null ? (stock.ask3_volume / 1000).toFixed(0) + 'K' : '–'}
              </span>
            </div>
          </div>
        ))}
        {stock.buy_pressure_pct != null && (
          <div className="px-3 py-2" style={{ borderTop: '1px solid #1e2832' }}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[9px]" style={{ color: '#4a5a6a' }}>Buy Pressure</span>
              <span className="font-mono text-[10px] font-bold" style={{ color: stock.buy_pressure_pct >= 50 ? '#00ff88' : '#ff3366' }}>
                {stock.buy_pressure_pct.toFixed(0)}%
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
              <div className="h-full rounded-full" style={{ width: (stock.buy_pressure_pct) + '%', background: stock.buy_pressure_pct >= 50 ? '#00ff88' : '#ff3366' }} />
            </div>
          </div>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {foreignItems.map(({ label, val, color }) => (
          <div key={label} className="p-2.5 rounded-lg text-center" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
            <div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Capital Tab ─────────────────────────────────────────────────────────────
function CapitalTab({ detail, detailLoading }: { detail: StockDetail | null; detailLoading: boolean }) {
  const fmtB = (v: number | null | undefined) => {
    if (v == null) return '–';
    return Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'T' : v.toFixed(0) + 'B';
  };

  const bal = detail ? [...detail.balance].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter)) : [];
  const annual = bal.filter((b) => b.quarter === 4).slice(0, 5).reverse();
  const latest = bal[0] ?? null;
  const totalAssets = latest ? (latest.total_assets || 1) : 1;

  return (
    <div>
      {detailLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="text-[11px] animate-pulse" style={{ color: '#4a5a6a' }}>Đang tải...</div>
        </div>
      )}
      {!detailLoading && !detail && (
        <div className="flex items-center justify-center py-12">
          <div className="text-[11px]" style={{ color: '#4a5a6a' }}>Không có dữ liệu</div>
        </div>
      )}
      {!detailLoading && detail && (
    <div className="space-y-3">
      {latest && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[9px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
            BẢNG CÂN ĐỐI — Q{latest.quarter}/{latest.year}
          </div>
          {[
            { label: 'Tổng tài sản', val: latest.total_assets, color: '#00d4ff' },
            { label: 'Vốn chủ sở hữu', val: latest.total_equity, color: '#00ff88' },
            { label: 'Tổng nợ', val: latest.total_debt, color: '#ff9500' },
            { label: 'Nợ ngắn hạn', val: latest.short_term_debt, color: '#ff3366' },
            { label: 'Tiền mặt', val: latest.cash, color: '#a78bfa' },
          ].map(({ label, val, color }) => (
            <div key={label} className="mb-2">
              <div className="flex justify-between mb-1">
                <span className="text-[10px]" style={{ color: '#8b99a8' }}>{label}</span>
                <span className="font-mono text-[10px] font-semibold" style={{ color }}>{fmtB(val)}</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                <div
                  className="h-full rounded-full"
                  style={{ width: Math.min((val / totalAssets) * 100, 100) + '%', background: color }}
                />
              </div>
            </div>
          ))}
          <div className="grid grid-cols-2 gap-2 mt-3">
            {latest.total_equity > 0 ? [
              { label: 'Đòn bẩy (D/E)', val: (latest.total_debt / latest.total_equity).toFixed(2) + 'x', color: latest.total_debt / latest.total_equity > 2 ? '#ff3366' : '#00d4ff' },
              { label: 'Cash / Equity', val: ((latest.cash / latest.total_equity) * 100).toFixed(1) + '%', color: '#a78bfa' },
            ].map(({ label, val, color }) => (
              <div key={label} className="p-2 rounded-lg text-center" style={{ background: '#0d1520' }}>
                <div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono text-xs font-bold" style={{ color }}>{val}</div>
              </div>
            )) : null}
          </div>
        </div>
      )}
      {annual.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[9px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            XU HƯỚNG VỐN (HÀNG NĂM)
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr style={{ borderBottom: '1px solid #1e2832' }}>
                  <th className="p-2 text-left font-semibold" style={{ color: '#4a5a6a' }}>Chỉ số</th>
                  {annual.map((r) => (
                    <th key={r.year} className="p-2 text-right font-semibold" style={{ color: '#4a5a6a' }}>{r.year}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: 'Tổng TS', key: 'total_assets' as const },
                  { label: 'VCSH', key: 'total_equity' as const },
                  { label: 'Tổng nợ', key: 'total_debt' as const },
                  { label: 'Tiền mặt', key: 'cash' as const },
                ].map(({ label, key }) => (
                  <tr key={label} style={{ borderBottom: '1px solid #0d1520' }}>
                    <td className="p-2 font-medium" style={{ color: '#8b99a8' }}>{label}</td>
                    {annual.map((r) => (
                      <td key={r.year} className="p-2 text-right font-mono" style={{ color: '#e2e8f0' }}>{fmtB(r[key])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
      )}
    </div>
  );
}


// ─── Stats Tab ────────────────────────────────────────────────────────────────
function StatsTab({ stock }: { stock: Stock }) {
  const history = stock.price_history ?? [];
  const volumes = stock.volume_history ?? [];
  const dates = stock.dates ?? [];

  const perfItems = [
    { label: '1 Ngày', val: stock.change_1d },
    { label: '5 Ngày', val: stock.change_5d },
    { label: '20 Ngày', val: stock.change_20d },
  ];
  const rsi = stock.rsi14 ?? 50;
  const adx = stock.adx14 ?? 0;
  const ma20diff = stock.pct_from_ma20 ?? 0;
  const ma50diff = stock.pct_from_ma50 ?? 0;
  const indicatorItems = [
    { label: 'RSI (14)', val: stock.rsi14 != null ? stock.rsi14.toFixed(0) : '–', color: rsi > 70 ? '#ff3366' : rsi < 30 ? '#00ff88' : '#ffcc00', note: rsi > 70 ? 'Overbought' : rsi < 30 ? 'Oversold' : 'Normal' },
    { label: 'ADX (14)', val: stock.adx14 != null ? stock.adx14.toFixed(0) : '–', color: adx >= 25 ? '#00d4ff' : '#8b99a8', note: adx >= 30 ? 'Strong trend' : 'Moderate' },
    { label: '+DI', val: stock.plus_di14 != null ? stock.plus_di14.toFixed(1) : '–', color: '#00ff88', note: 'Bull pressure' },
    { label: '-DI', val: stock.minus_di14 != null ? stock.minus_di14.toFixed(1) : '–', color: '#ff3366', note: 'Bear pressure' },
    { label: 'Từ MA20', val: stock.pct_from_ma20 != null ? (ma20diff >= 0 ? '+' : '') + ma20diff.toFixed(1) + '%' : '–', color: ma20diff >= 0 ? '#00d4ff' : '#ff9500', note: 'vs MA20' },
    { label: 'Từ MA50', val: stock.pct_from_ma50 != null ? (ma50diff >= 0 ? '+' : '') + ma50diff.toFixed(1) + '%' : '–', color: ma50diff >= 0 ? '#00d4ff' : '#ff9500', note: 'vs MA50' },
    { label: 'Vol Ratio', val: stock.vol_ratio != null ? stock.vol_ratio.toFixed(2) : '–', color: (stock.vol_ratio ?? 1) >= 1.5 ? '#ffcc00' : '#8b99a8', note: 'Volume vs MA' },
    { label: 'ATR %', val: stock.atr_pct != null ? stock.atr_pct.toFixed(2) : '–', color: '#a78bfa', note: 'Volatility' },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        {perfItems.map(({ label, val }) => (
          <div key={label} className="p-2.5 rounded-lg text-center" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
            <div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color: (val ?? 0) >= 0 ? '#00ff88' : '#ff3366' }}>
              {val != null ? (val >= 0 ? '+' : '') + val.toFixed(2) + '%' : '–'}
            </div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {([
          { label: 'RSI (14)', val: stock.rsi14?.toFixed(0) ?? '–', color: (stock.rsi14 ?? 50) > 70 ? '#ff3366' : (stock.rsi14 ?? 50) < 30 ? '#00ff88' : '#ffcc00', note: (stock.rsi14 ?? 50) > 70 ? 'Overbought' : (stock.rsi14 ?? 50) < 30 ? 'Oversold' : 'Normal' },
          { label: 'ADX (14)', val: stock.adx14?.toFixed(0) ?? '–', color: (stock.adx14 ?? 0) >= 25 ? '#00d4ff' : '#8b99a8', note: (stock.adx14 ?? 0) >= 30 ? 'Strong trend' : 'Moderate' },
          { label: '+DI', val: stock.plus_di14?.toFixed(1) ?? '–', color: '#00ff88', note: 'Bull pressure' },
          { label: '-DI', val: stock.minus_di14?.toFixed(1) ?? '–', color: '#ff3366', note: 'Bear pressure' },
          { label: 'Từ MA20', val: stock.pct_from_ma20 != null ? (ma20diff >= 0 ? '+' : '') + ma20diff.toFixed(1) + '%' : '–', color: (stock.pct_from_ma20 ?? 0) >= 0 ? '#00d4ff' : '#ff9500', note: 'vs MA20' },
          { label: 'Từ MA50', val: stock.pct_from_ma50 != null ? (ma50diff >= 0 ? '+' : '') + ma50diff.toFixed(1) + '%' : '–', color: (stock.pct_from_ma50 ?? 0) >= 0 ? '#00d4ff' : '#ff9500', note: 'vs MA50' },
          { label: 'Vol Ratio', val: stock.vol_ratio?.toFixed(2) ?? '–', color: (stock.vol_ratio ?? 1) >= 1.5 ? '#ffcc00' : '#8b99a8', note: 'Volume vs MA' },
          { label: 'ATR %', val: stock.atr_pct?.toFixed(2) ?? '–', color: '#a78bfa', note: 'Volatility' },
        ]).map(({ label, val, color, note }) => (
          <div key={label} className="p-2.5 rounded-lg flex items-center justify-between" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
            <div>
              <div className="text-[9px]" style={{ color: '#4a5a6a' }}>{label}</div>
              <div className="text-[9px] mt-0.5" style={{ color: '#2a3642' }}>{note}</div>
            </div>
            <div className="font-mono font-bold text-sm" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>
      {history.length > 0 && dates.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[9px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            LỊCH SỬ GIÁ — {dates.length} phiên
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: '200px' }}>
            <table className="w-full text-[10px]">
              <thead className="sticky top-0" style={{ background: '#0f1519' }}>
                <tr>
                  {['Ngày', 'Giá đóng cửa', 'Thay đổi', 'KL/MA'].map(h => (
                    <th key={h} className="p-2 text-right font-medium first:text-left" style={{ color: '#4a5a6a' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...dates].reverse().map((date, ri) => {
                  const idx = dates.length - 1 - ri;
                  const p = history[idx];
                  const pPrev = idx > 0 ? history[idx - 1] : p;
                  const chg = pPrev ? ((p - pPrev) / pPrev * 100) : 0;
                  const vol = volumes[idx];
                  const slice = volumes.slice(Math.max(0, idx - 20), idx);
                  const avgVol = slice.length > 0 ? slice.reduce((s, v) => s + v, 0) / slice.length : 1;
                  const volRatio = vol / avgVol;
                  return (
                    <tr key={date} style={{ borderTop: '1px solid #1e2832' }}>
                      <td className="p-2 font-mono" style={{ color: '#8b99a8' }}>{date}</td>
                      <td className="p-2 text-right font-mono font-semibold" style={{ color: '#e8edf2' }}>{formatPrice(p)}</td>
                      <td className="p-2 text-right font-mono" style={{ color: chg >= 0 ? '#00ff88' : '#ff3366' }}>
                        {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
                      </td>
                      <td className="p-2 text-right font-mono" style={{ color: volRatio >= 1.5 ? '#ffcc00' : '#8b99a8' }}>
                        {isFinite(volRatio) ? volRatio.toFixed(1) + 'x' : '–'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}


// ============ Main Component ============

export default function StockModal({
  stock,
  sectorStatus,
  preloadedAnalysis,
  ictSignal,
  onClose,
}: StockModalProps) {
  const [visible, setVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<'analysis' | 'scores' | 'chart' | 'ict' | 'finance' | 'trading' | 'capital' | 'stats'>('analysis');
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (stock) {
      requestAnimationFrame(() => setVisible(true));
    }
  }, [stock]);

  // Lazy-load detail data khi cần
  useEffect(() => {
    if (!stock || detail) return;
    const needsDetail = ['finance','trading','capital','stats'].includes(activeTab);
    if (!needsDetail) return;
    setDetailLoading(true);
    getStockDetails()
      .then((res) => {
        const d = res?.details?.[stock.symbol];
        if (d) setDetail(d);
      })
      .catch(() => {})
      .finally(() => setDetailLoading(false));
  }, [stock, activeTab, detail]);

  const close = () => {
    setVisible(false);
    setTimeout(onClose, 150);
  };

  const analysis = stock ? (preloadedAnalysis || generateAnalysis(stock, sectorStatus)) : null;
  const deskAnalysis = stock ? generateDeskAnalysis(stock, ictSignal, sectorStatus) : null;
  const recDisplay = analysis ? getRecommendationDisplay(analysis.recommendation) : null;
  const tierColor = stock ? getTierColor(stock.tier) : '#8b99a8';
  const price = stock ? (stock.close || stock.price || 0) : 0;
  const tabList = ictSignal
    ? [{ id: 'analysis', label: 'Phân tích', icon: Target }, { id: 'scores', label: 'Điểm số', icon: Activity }, { id: 'finance', label: 'Tài chính', icon: BarChart3 }, { id: 'trading', label: 'Giao dịch', icon: TrendingUp }, { id: 'capital', label: 'Vốn', icon: Shield }, { id: 'stats', label: 'Thống kê', icon: Activity }, { id: 'ict', label: '🧠 ICT', icon: Zap }]
    : [{ id: 'analysis', label: 'Phân tích', icon: Target }, { id: 'scores', label: 'Điểm số', icon: Activity }, { id: 'finance', label: 'Tài chính', icon: BarChart3 }, { id: 'trading', label: 'Giao dịch', icon: TrendingUp }, { id: 'capital', label: 'Vốn', icon: Shield }, { id: 'stats', label: 'Thống kê', icon: Activity }];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ display: (!stock || !analysis || !deskAnalysis || !recDisplay) ? 'none' : undefined }}>
      {/* Backdrop */}
      <div
        className="absolute inset-0 transition-opacity duration-200"
        style={{
          background: 'rgba(5,8,10,0.9)',
          backdropFilter: 'blur(6px)',
          opacity: visible ? 1 : 0,
        }}
        onClick={close}
      />

      {/* Modal */}
      <div
        className="relative w-full max-w-2xl rounded-2xl overflow-hidden transition-all duration-200"
        style={{
          background: 'linear-gradient(180deg, #0f1519 0%, #0a0f14 100%)',
          border: '1px solid #2a3642',
          opacity: visible ? 1 : 0,
          transform: visible ? 'scale(1)' : 'scale(0.95)',
          boxShadow: '0 0 40px rgba(0,212,255,0.1), 0 20px 40px rgba(0,0,0,0.4)',
          maxHeight: '90vh',
        }}
      >
        {/* Header */}
        <div
          className="p-4"
          style={{
            borderBottom: '1px solid #1e2832',
            background: 'linear-gradient(90deg, rgba(0,212,255,0.05) 0%, transparent 100%)',
          }}
        >
          <div className="flex justify-between items-start">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold">{stock.symbol}</span>
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-bold"
                  style={{
                    background: (tierColor) + '20',
                    color: tierColor,
                    border: '1px solid ' + (tierColor) + '40',
                  }}
                >
                  {stock.tier}
                </span>
              </div>
              <div className="text-xs mt-1" style={{ color: '#8b99a8' }}>
                {stock.name} • {stock.industry}
              </div>
            </div>
            <button
              onClick={close}
              className="p-1.5 rounded-md"
              style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#4a5a6a' }}
            >
              <X size={14} />
            </button>
          </div>

          {/* Price and Recommendation */}
          <div className="flex justify-between items-end mt-3">
            <div>
              <div className="text-2xl font-bold font-mono">{formatPrice(price)}</div>
              <div className="flex items-center gap-2 mt-1">
                <span
                  className="font-mono font-semibold text-sm"
                  style={{ color: (stock.change_20d || stock.change_5d || 0) >= 0 ? '#00ff88' : '#ff3366' }}
                >
                  {formatPercent(stock.change_20d || stock.change_5d || 0)}
                </span>
                <span className="text-[10px]" style={{ color: '#4a5a6a' }}>
                  20D
                </span>
              </div>
            </div>
            <div className="text-right">
              <div
                className="px-3 py-1.5 rounded-lg font-bold text-sm flex items-center gap-1.5"
                style={{
                  background: (recDisplay.color) + '20',
                  color: recDisplay.color,
                  border: '1px solid ' + (recDisplay.color) + '50',
                  boxShadow: '0 0 15px ' + (recDisplay.color) + '30',
                }}
              >
                {recDisplay.icon === 'up' && <ArrowUpCircle size={14} />}
                {recDisplay.icon === 'down' && <ArrowDownCircle size={14} />}
                {recDisplay.icon === 'hold' && <MinusCircle size={14} />}
                {recDisplay.text}
              </div>
              <div className="text-[10px] mt-1" style={{ color: '#4a5a6a' }}>
                Score:{' '}
                <span style={{ color: getScoreColor(stock.composite_score) }}>
                  {stock.composite_score.toFixed(1)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b" style={{ borderColor: '#1e2832' }}>
          {tabList.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className="flex-1 py-2.5 flex items-center justify-center gap-1.5 text-[11px] font-medium transition-all"
              style={{
                background:
                  activeTab === tab.id
                    ? 'linear-gradient(180deg, #00d4ff10 0%, transparent 100%)'
                    : 'transparent',
                color: activeTab === tab.id ? '#00d4ff' : '#4a5a6a',
                borderBottom: activeTab === tab.id ? '2px solid #00d4ff' : '2px solid transparent',
              }}
            >
              <tab.icon size={12} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto" style={{ maxHeight: 'calc(90vh - 220px)' }}>
          {/* Analysis Tab */}
          {activeTab === 'analysis' && <AnalysisTab stock={stock} deskAnalysis={deskAnalysis} />}

          {/* Scores Tab */}
          {activeTab === 'scores' && (
            <div>
              <div
                className="p-3 rounded-lg mb-3"
                style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
              >
                <div className="text-[10px] mb-3" style={{ color: '#4a5a6a', letterSpacing: '0.5px' }}>
                  COMPONENT SCORES
                </div>
                <div className="grid grid-cols-4 gap-3">
                  <ScoreCircle value={stock.fundamental_score} label="FUND" Icon={Shield} />
                  <ScoreCircle value={stock.smart_money_score} label="FLOW" Icon={Globe} />
                  <ScoreCircle value={stock.momentum_score} label="MOM" Icon={Zap} />
                  <ScoreCircle value={stock.technical_score} label="TECH" Icon={Activity} />
                </div>
              </div>

              {/* Score Explanations */}
              <div className="space-y-2">
                {[
                  {
                    label: 'Fundamental (F)',
                    value: stock.fundamental_score,
                    color: '#a855f7',
                    desc: 'Đánh giá sức khỏe tài chính: ROE, ROA, P/E, tăng trưởng doanh thu',
                  },
                  {
                    label: 'Smart Flow (S)',
                    value: stock.smart_money_score,
                    color: '#00d4ff',
                    desc: 'Dòng tiền thông minh: Khối ngoại, tự doanh, tổ chức',
                  },
                  {
                    label: 'Momentum (M)',
                    value: stock.momentum_score,
                    color: '#ffcc00',
                    desc: 'Động lực giá: Tốc độ tăng/giảm, so sánh với VN-Index',
                  },
                  {
                    label: 'Technical (T)',
                    value: stock.technical_score,
                    color: '#00ff88',
                    desc: 'Phân tích kỹ thuật: MA, RSI, MACD, xu hướng',
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="p-2.5 rounded-lg"
                    style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
                  >
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-[10px] font-semibold" style={{ color: item.color }}>
                        {item.label}
                      </span>
                      <span
                        className="text-[11px] font-mono font-bold"
                        style={{ color: getScoreColor(item.value) }}
                      >
                        {item.value.toFixed(0)}
                      </span>
                    </div>
                    <p className="text-[10px]" style={{ color: '#6a7a8a' }}>
                      {item.desc}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Chart Tab */}
          {activeTab === 'chart' && (
            <div>
              {stock.open_history && stock.high_history && stock.low_history && stock.price_history && stock.volume_history && stock.dates ? (
                <CandlestickChart
                  symbol={stock.symbol}
                  open={stock.open_history}
                  high={stock.high_history}
                  low={stock.low_history}
                  close={stock.price_history}
                  volume={stock.volume_history}
                  dates={stock.dates}
                />
              ) : (
                <div>
                  <Sparkline
                    data={stock.price_history ?? []}
                    volume={stock.volume_history}
                    dates={stock.dates}
                    width={320}
                    height={80}
                  />
                  <div className="text-center py-2 text-[10px]" style={{ color: '#4a5a6a' }}>
                    Dữ liệu OHLC chưa sẵn sàng
                  </div>
                </div>
              )}
            </div>
          )}

        {activeTab === 'ict' && ictSignal && <ICTTab ictSignal={ictSignal} />}

        {/* ── TAB: TÀI CHÍNH ──────────────────────────────── */}
        {activeTab === 'finance' && <FinanceTab detail={detail} detailLoading={detailLoading} />}

        {/* ── TAB: GIAO DỊCH ───────────────────────────────── */}
        {activeTab === 'trading' && <TradingTab stock={stock} />}

        {/* ── TAB: VỐN ─────────────────────────────────────── */}
        {activeTab === 'capital' && <CapitalTab detail={detail} detailLoading={detailLoading} />}

        {/* ── TAB: THỐNG KÊ ────────────────────────────────── */}
        {activeTab === 'stats' && <StatsTab stock={stock} />}

        {/* Footer Disclaimer */}
        <div className="px-4 py-2" style={{ borderTop: '1px solid #1e2832', background: '#0a0f14' }}>
          <p className="text-[9px] text-center" style={{ color: '#4a5a6a' }}>
            * Phân tích chỉ mang tính tham khảo, không phải khuyến nghị đầu tư
          </p>
        </div>
      </div>
    </div>
  );
}
