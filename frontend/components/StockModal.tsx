'use client';

import { useState, useEffect } from 'react';
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
import SparklineModal from './SparklineModal';
import CandlestickChart from './CandlestickChart';

interface StockModalProps {
  stock: Stock | null;
  sectorStatus?: 'accumulating' | 'distributing' | 'neutral';
  preloadedAnalysis?: AIAnalysis;
  ictSignal?: ICTSignal;
  regimeBullWeight?: number;
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
          className="absolute inset-0 flex items-center justify-center font-mono font-bold text-[11px]"
          style={{ color, textShadow: '0 0 6px ' + color + '50' }}
        >
          {value?.toFixed(0)}
        </div>
      </div>
      <div className="flex items-center justify-center gap-1 mt-1.5">
        <Icon size={9} color="#4a5a6a" />
        <span className="text-[10px]" style={{ color: '#4a5a6a' }}>
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
      <span className="text-[12px]" style={{ color: style.text }}>
        {item.text}
      </span>
    </div>
  );
}


function AnalysisTab({
  stock,
  deskAnalysis,
  aiAnalysis,
}: {
  stock: Stock;
  deskAnalysis: DeskAnalysis;
  aiAnalysis?: AIAnalysis;
}) {
  const d = deskAnalysis;
  const ai = aiAnalysis;

  // ── Action config ─────────────────────────────────────────────
  const actionCfg: Record<string, { label: string; color: string; bg: string; border: string }> = {
    STRONG_BUY: { label: 'STRONG BUY',  color: '#00ff88', bg: '#00ff8818', border: '#00ff8840' },
    BUY:        { label: 'BUY',          color: '#00ff88', bg: '#00ff8810', border: '#00ff8830' },
    ACCUMULATE: { label: 'ACCUMULATE',   color: '#00d4ff', bg: '#00d4ff10', border: '#00d4ff30' },
    HOLD:       { label: 'HOLD',         color: '#ffcc00', bg: '#ffcc0010', border: '#ffcc0030' },
    REDUCE:     { label: 'REDUCE',       color: '#ff9500', bg: '#ff950010', border: '#ff950030' },
    SELL:       { label: 'SELL',         color: '#ff3366', bg: '#ff336610', border: '#ff336630' },
    STRONG_SELL:{ label: 'STRONG SELL',  color: '#ff3366', bg: '#ff336618', border: '#ff336650' },
    AVOID:      { label: 'AVOID',        color: '#ff3366', bg: '#ff336610', border: '#ff336630' },
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
  const statusStyle: Record<string, { color: string; bg: string; border: string }> = {
    positive: { color: '#00ff88', bg: '#00ff8810', border: '#00ff8828' },
    negative: { color: '#ff3366', bg: '#ff336610', border: '#ff336628' },
    neutral:  { color: '#8b99a8', bg: '#1e283220', border: '#1e2832' },
    warning:  { color: '#ff9500', bg: '#ff950010', border: '#ff950028' },
  };

  // Determine display recommendation — prefer AI if available
  const rec = ai?.recommendation ?? d.setup.action;
  const ac = actionCfg[rec] ?? actionCfg.HOLD;
  const cc = convCfg[d.setup.conviction] ?? convCfg.LOW;

  // AI sections
  const aiSections = ai?.sections as Record<string, string> | undefined;
  const priceLevels = ai?.price_levels as Record<string, string> | undefined;
  const hasAI = !!ai;

  return (
    <div>

      {/* ── 0. AI Source Badge ───────────────────────────────── */}
      {hasAI && (
        <div className="flex items-center justify-between mb-3">
          {/* AI badge */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg"
            style={{ background: '#00d4ff0c', border: '1px solid #00d4ff25' }}>
            <span className="text-[10px]">🤖</span>
            <span className="text-[10px] font-semibold tracking-widest" style={{ color: '#00d4ff' }}>
              AI ANALYSIS — GPT-4o
            </span>
          </div>
          {/* Báo cáo chi tiết button */}
          <button
            onClick={() => window.open(`/report/${stock.symbol}`, '_blank')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold tracking-widest transition-all"
            style={{
              background: '#00d4ff12',
              border: '1px solid #00d4ff40',
              color: '#00d4ff',
              cursor: 'pointer',
              letterSpacing: '0.06em',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.background = '#00d4ff20';
              (e.currentTarget as HTMLButtonElement).style.borderColor = '#00d4ff70';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.background = '#00d4ff12';
              (e.currentTarget as HTMLButtonElement).style.borderColor = '#00d4ff40';
            }}
          >
            📋 BÁO CÁO CHI TIẾT ↗
          </button>
        </div>
      )}

      {/* ── 1. Verdict Hero ──────────────────────────────────── */}
      <div className="rounded-xl p-3 mb-3"
        style={{ background: ac.bg, border: '1px solid ' + ac.border }}>
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex-1 min-w-0">
            <div className="font-bold text-sm leading-snug" style={{ color: ac.color }}>
              {hasAI ? (ai.executive_summary ?? ai.summary ?? d.headline) : d.headline}
            </div>
            {!hasAI && (
              <div className="text-[10px] mt-0.5 font-semibold tracking-widest" style={{ color: cc.color }}>
                {cc.label}
              </div>
            )}
          </div>
          <div className="px-3 py-1.5 rounded-lg font-black text-sm shrink-0"
            style={{ background: ac.color, color: '#05080a' }}>
            {ac.label}
          </div>
        </div>
        {/* Narrative (rule-based only, AI uses executive_summary above) */}
        {!hasAI && (
          <p className="text-[12px] leading-relaxed" style={{ color: '#c8d4e0' }}>{d.narrative}</p>
        )}
      </div>

      {/* ── 2. AI Sections ───────────────────────────────────── */}
      {hasAI && aiSections && (
        <div className="space-y-2 mb-3">
          {/* Regime impact — prominent if BEAR */}
          {aiSections.regime_impact && (
            <div className="rounded-lg px-3 py-2"
              style={{ background: '#ff950008', border: '1px solid #ff950025' }}>
              <div className="text-[9px] font-semibold tracking-widest mb-1" style={{ color: '#ff9500' }}>
                🌐 MARKET REGIME
              </div>
              <p className="text-[11px] leading-relaxed" style={{ color: '#c8d4e0' }}>
                {aiSections.regime_impact}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            {[
              { key: 'ict_analysis',    icon: '🧠', label: 'ICT ANALYSIS',   accent: '#a78bfa' },
              { key: 'technical_view',  icon: '📈', label: 'KỸ THUẬT',       accent: '#00d4ff' },
              { key: 'flow_analysis',   icon: '💰', label: 'DÒNG TIỀN',      accent: '#00ff88' },
              { key: 'fundamental_view',icon: '📊', label: 'CƠ BẢN',         accent: '#ffcc00' },
              { key: 'sector_context',  icon: '🏭', label: 'NGÀNH',          accent: '#8b99a8' },
            ].filter(({ key }) => aiSections[key]).map(({ key, icon, label, accent }) => (
              <div key={key} className="rounded-lg p-2.5"
                style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-[11px]">{icon}</span>
                  <div className="text-[9px] font-semibold tracking-widest" style={{ color: accent }}>
                    {label}
                  </div>
                </div>
                <p className="text-[11px] leading-relaxed" style={{ color: '#a8b8c8' }}>
                  {aiSections[key]}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 3. AI Price Levels ───────────────────────────────── */}
      {hasAI && priceLevels && (priceLevels.support || priceLevels.resistance) && (
        <div className="rounded-xl p-3 mb-3"
          style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-2" style={{ color: '#4a5a6a' }}>
            📍 ICT PRICE LEVELS
          </div>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            {[
              { label: '🟢 Support',    val: priceLevels.support,    col: '#00ff88' },
              { label: '🔴 Resistance', val: priceLevels.resistance, col: '#ff3366' },
              { label: '🛑 Stop Loss',  val: priceLevels.stop_loss_note, col: '#ff9500' },
            ].filter(r => r.val).map(({ label, val, col }) => (
              <div key={label} className="p-2 rounded-lg"
                style={{ background: '#0a0f14', border: '1px solid ' + col + '25' }}>
                <div className="text-[9px] mb-1" style={{ color: col + 'aa' }}>{label}</div>
                <div className="font-mono text-[10px] font-semibold leading-snug" style={{ color: col }}>
                  {val}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 3b. Rule-based Trade Setup (no AI) ──────────────── */}
      {!hasAI && (d.setup.entry_zone || d.setup.stop_loss) && (
        <div className="rounded-xl p-3 mb-3"
          style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-2" style={{ color: '#4a5a6a' }}>
            TRADE SETUP
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            {[
              { label: '📍 Entry Zone',    val: d.setup.entry_zone   },
              { label: '🛑 Stop Loss',     val: d.setup.stop_loss    },
              { label: '🎯 Target 1',      val: d.setup.target_1     },
              { label: '🚀 Target 2',      val: d.setup.target_2     },
              { label: '⚖️ Risk / Reward', val: d.setup.risk_reward  },
              { label: '⏱ Time Horizon',  val: d.setup.time_horizon },
            ].filter(r => r.val).map(({ label, val }) => (
              <div key={label} className="p-2 rounded-lg"
                style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
                <div style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono font-semibold mt-0.5" style={{ color: '#e8edf2' }}>{val}</div>
              </div>
            ))}
          </div>
          {d.setup.invalidation && (
            <div className="mt-2 p-2 rounded-lg text-[11px]"
              style={{ background: '#ff336610', border: '1px solid #ff336630' }}>
              <span style={{ color: '#ff3366' }}>⚡ Invalidation: </span>
              <span style={{ color: '#c8d4e0' }}>{d.setup.invalidation}</span>
            </div>
          )}
        </div>
      )}

      {/* ── 4. Highlights & Risks ────────────────────────────── */}
      {(() => {
        const highlights = hasAI ? (ai.highlights ?? []) : d.catalysts.map(c => ({ text: c, type: 'positive' as const }));
        const risks      = hasAI ? (ai.risks      ?? []) : d.key_risks.map(r  => ({ text: r, type: 'negative'  as const }));
        if (!highlights.length && !risks.length) return null;
        return (
          <div className="grid grid-cols-2 gap-2 mb-3">
            {highlights.length > 0 && (
              <div className="rounded-xl p-2.5"
                style={{ background: '#00ff8808', border: '1px solid #00ff8828' }}>
                <div className="text-[10px] font-semibold mb-1.5 tracking-widest" style={{ color: '#00ff88' }}>
                  ✅ {hasAI ? 'HIGHLIGHTS' : 'CATALYSTS'}
                </div>
                <ul className="space-y-1">
                  {highlights.map((h, i) => (
                    <li key={i} className="text-[11px] leading-snug flex gap-1.5" style={{ color: '#c8d4e0' }}>
                      <span style={{ color: '#00ff88' }}>+</span>{h.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {risks.length > 0 && (
              <div className="rounded-xl p-2.5"
                style={{ background: '#ff336808', border: '1px solid #ff336828' }}>
                <div className="text-[10px] font-semibold mb-1.5 tracking-widest" style={{ color: '#ff3366' }}>
                  ⚠️ {hasAI ? 'RISKS' : 'KEY RISKS'}
                </div>
                <ul className="space-y-1">
                  {risks.map((r, i) => {
                    const ss = statusStyle[r.type] ?? statusStyle.negative;
                    return (
                      <li key={i} className="text-[11px] leading-snug flex gap-1.5" style={{ color: '#c8d4e0' }}>
                        <span style={{ color: ss.color }}>–</span>{r.text}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── 5. Signal Groups (rule-based desk analysis) ─────── */}
      {d.signal_groups.length > 0 && (
        <>
          <div className="text-[10px] font-semibold tracking-widest mb-2" style={{ color: '#4a5a6a' }}>
            SIGNAL ANALYSIS — {d.signal_groups.length} GROUPS
            {hasAI && <span style={{ color: '#00d4ff50' }}> · rule-based detail</span>}
          </div>
          <div className="space-y-2">
            {d.signal_groups.map((group) => {
              const sc = strengthCfg[group.strength] ?? strengthCfg.NEUTRAL;
              return (
                <div key={group.id} className="rounded-xl overflow-hidden"
                  style={{ border: '1px solid ' + sc.color + '25', background: '#0a0f14' }}>
                  <div className="flex items-center justify-between px-3 py-2"
                    style={{ background: sc.color + '08', borderBottom: '1px solid ' + sc.color + '20' }}>
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{group.icon}</span>
                      <span className="text-[11px] font-bold tracking-widest" style={{ color: sc.color }}>
                        {group.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                        <div className="h-full rounded-full"
                          style={{ width: group.score + '%', background: sc.color, boxShadow: '0 0 4px ' + sc.color + '60' }} />
                      </div>
                      <span className="font-mono font-bold text-[11px]" style={{ color: sc.color }}>
                        {group.strength}
                      </span>
                    </div>
                  </div>
                  <div className="divide-y" style={{ borderColor: '#1e2832' }}>
                    {group.signals.map((sig, i) => {
                      const ss = statusStyle[sig.status] ?? statusStyle.neutral;
                      return (
                        <div key={i} className="flex items-start justify-between px-3 py-2 gap-2"
                          style={{ background: i % 2 === 0 ? 'transparent' : '#0f151905' }}>
                          <div className="flex items-start gap-2 flex-1 min-w-0">
                            <div className="w-1 h-1 rounded-full mt-1.5 shrink-0" style={{ background: ss.color }} />
                            <div className="min-w-0">
                              <div className="text-[10px] font-semibold" style={{ color: '#8b99a8' }}>{sig.label}</div>
                              {sig.note && <div className="text-[10px] mt-0.5 leading-snug" style={{ color: '#4a5a6a' }}>{sig.note}</div>}
                            </div>
                          </div>
                          <div className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0"
                            style={{ background: ss.bg, color: ss.color, border: '1px solid ' + ss.color + '30' }}>
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
        </>
      )}
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
            <div className="text-[9px] mb-1 tracking-widest" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color: col }}>{val}</div>
          </div>
        ))}
      </div>

      {/* Market Structure */}
      <div className="p-2.5 rounded-lg mb-2" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[10px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>MARKET STRUCTURE</div>
        <div className="flex items-center gap-2 mb-2">
          <span className="font-bold text-sm" style={{ color: structCol }}>
            {ictSignal.structure === 'BULLISH' ? '↑ BULLISH' : ictSignal.structure === 'BEARISH' ? '↓ BEARISH' : '— NEUTRAL'}
          </span>
          {(ictSignal.smart_money || ictSignal.wyckoff_spring) && (
            <span className="text-base">{ictSignal.smart_money ? '💎' : ''}{ictSignal.wyckoff_spring ? '💧' : ''}</span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-1 text-[11px]">
          {[
            { label: 'BOS Bullish',   on: ictSignal.bos_bull,         col: '#00ff88' },
            { label: 'BOS Bearish',   on: ictSignal.bos_bear,         col: '#ff3366' },
            { label: 'CHoCH Bull',    on: ictSignal.choch_bull,       col: '#00ff88' },
            { label: 'CHoCH Bear',    on: ictSignal.choch_bear,       col: '#ff3366' },
          ].map(({ label, on, col }) => (
            <div key={label} className="flex items-center justify-between px-2 py-1 rounded" style={{ background: '#0f1519', opacity: on ? 1 : 0.35 }}>
              <span style={{ color: '#8b99a8' }}>{label}</span>
              <span className="font-bold text-[10px]" style={{ color: on ? col : '#2a3642' }}>{on ? 'YES' : 'no'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ICT Confluences */}
      <div className="p-2.5 rounded-lg mb-2" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[10px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>ICT CONFLUENCES ({ictSignal.ict_confluence} signals)</div>
        <div className="grid grid-cols-2 gap-1 text-[11px]">
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
              <span className="font-bold text-[10px]" style={{ color: on ? col : '#2a3642' }}>{on ? 'YES' + (extra) : 'no'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Signal Breakdown bars */}
      <div className="p-2.5 rounded-lg mb-2" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[10px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>SIGNAL BREAKDOWN</div>
        <div className="space-y-1.5">
          {Object.entries(ictSignal.signal_breakdown).map(([key, val]) => {
            const col = val >= 70 ? '#00ff88' : val >= 55 ? '#00d4ff' : val >= 40 ? '#ffcc00' : '#ff3366';
            return (
              <div key={key} className="flex items-center gap-2">
                <div className="text-[10px] w-28 shrink-0 font-mono" style={{ color: '#8b99a8' }}>
                  {key.replace(/_/g, ' ')}
                </div>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                  <div className="h-full rounded-full transition-all" style={{ width: (Math.max(val, 0)) + '%', background: col, boxShadow: '0 0 4px ' + (col) + '60' }} />
                </div>
                <div className="font-mono text-[10px] w-7 text-right" style={{ color: col }}>{val.toFixed(0)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top signals */}
      {ictSignal.top_signals.length > 0 && (
        <div className="p-2.5 rounded-lg" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold mb-2 tracking-widest" style={{ color: '#4a5a6a' }}>TOP SIGNALS</div>
          <ul className="space-y-1">
            {ictSignal.top_signals.map((sig, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[11px]" style={{ color: '#8b99a8' }}>
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
    return new Intl.NumberFormat('vi-VN').format(Math.round(v)) + ' tỷ';
  };
  const colPct = (v: number) => v >= 20 ? '#00ff88' : v >= 10 ? '#00d4ff' : v >= 0 ? '#ffcc00' : '#ff3366';

  if (!detail) return (
    <div className="flex items-center justify-center py-12 text-[12px]" style={{ color: '#4a5a6a' }}>
      {detailLoading ? 'Đang tải dữ liệu tài chính...' : 'Không có dữ liệu tài chính'}
    </div>
  );

  const income = [...detail.income].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter)).slice(0, 6);
  const ratio = [...detail.ratio].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter));
  const latestR = ratio[0] ?? null;
  const cf = [...detail.cashflow].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter)).slice(0, 6);
  const bal = [...detail.balance].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter));
  const latestBal = bal[0] ?? null;
  const annual = bal.filter((b) => b.quarter === 4).slice(0, 5);
  const totalAssets = latestBal ? (latestBal.total_assets || 1) : 1;

  return (
    <div className="space-y-3">
      {/* ── 1. CHỈ SỐ ĐÁNH GIÁ HIỆU QUẢ ────────────────────── */}
      {latestR && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
            📊 CHỈ SỐ ĐÁNH GIÁ HIỆU QUẢ — Q{latestR.quarter}/{latestR.year}
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
              { label: 'D/E', val: latestR.debt_equity != null ? latestR.debt_equity.toFixed(2) : '–', note: 'x', color: latestR.debt_equity != null ? (latestR.debt_equity > 2 ? '#ff3366' : latestR.debt_equity > 1 ? '#ff9500' : '#00d4ff') : undefined },
            ].map(({ label, val, note, color }) => (
              <div key={label} className="p-2 rounded-lg text-center" style={{ background: '#0d1520' }}>
                <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono text-sm font-bold" style={{ color: color || '#e2e8f0' }}>
                  {val}<span className="text-[10px] ml-0.5" style={{ color: '#4a5a6a' }}>{note}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 2. BẢNG CÂN ĐỐI KẾ TOÁN — QUÝ GẦN NHẤT ─────── */}
      {latestBal && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
            🏦 BẢNG CÂN ĐỐI KẾ TOÁN — Q{latestBal.quarter}/{latestBal.year}
          </div>
          {[
            { label: 'Tổng tài sản', val: latestBal.total_assets, color: '#00d4ff' },
            { label: 'Vốn chủ sở hữu', val: latestBal.total_equity, color: '#00ff88' },
            { label: 'Tổng nợ', val: latestBal.total_debt, color: '#ff9500' },
            { label: 'Nợ ngắn hạn', val: latestBal.short_term_debt, color: '#ff3366' },
            { label: 'Tiền mặt', val: latestBal.cash, color: '#a78bfa' },
          ].map(({ label, val, color }) => (
            <div key={label} className="mb-2">
              <div className="flex justify-between mb-1">
                <span className="text-[11px]" style={{ color: '#8b99a8' }}>{label}</span>
                <span className="font-mono text-[11px] font-semibold" style={{ color }}>{fmtB(val)}</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                <div className="h-full rounded-full" style={{ width: Math.min((val / totalAssets) * 100, 100) + '%', background: color, boxShadow: `0 0 4px ${color}40` }} />
              </div>
            </div>
          ))}
          <div className="grid grid-cols-2 gap-2 mt-3">
            {latestBal.total_equity > 0 ? [
              { label: 'Đòn bẩy (D/E)', val: (latestBal.total_debt / latestBal.total_equity).toFixed(2) + 'x', color: latestBal.total_debt / latestBal.total_equity > 2 ? '#ff3366' : '#00d4ff' },
              { label: 'Cash / Equity', val: ((latestBal.cash / latestBal.total_equity) * 100).toFixed(1) + '%', color: '#a78bfa' },
            ].map(({ label, val, color }) => (
              <div key={label} className="p-2 rounded-lg text-center" style={{ background: '#0d1520' }}>
                <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono text-sm font-bold" style={{ color }}>{val}</div>
              </div>
            )) : null}
          </div>
        </div>
      )}

      {/* ── 3. XU HƯỚNG VỐN HÀNG NĂM ────────────────────────── */}
      {annual.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            📈 XU HƯỚNG VỐN (HÀNG NĂM)
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
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
                  { label: 'Tổng TS', key: 'total_assets' as const, color: '#00d4ff' },
                  { label: 'VCSH', key: 'total_equity' as const, color: '#00ff88' },
                  { label: 'Tổng nợ', key: 'total_debt' as const, color: '#ff9500' },
                  { label: 'Tiền mặt', key: 'cash' as const, color: '#a78bfa' },
                ].map(({ label, key, color }) => (
                  <tr key={label} style={{ borderBottom: '1px solid #0d1520' }}>
                    <td className="p-2 font-medium" style={{ color }}>{label}</td>
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

      {/* ── 4. KẾT QUẢ KINH DOANH ────────────────────────────── */}
      {income.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            💰 KẾT QUẢ KINH DOANH
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr style={{ borderBottom: '1px solid #1e2832' }}>
                  <th className="p-2 text-left font-semibold" style={{ color: '#4a5a6a' }}>Chỉ tiêu</th>
                  {income.map((r) => (
                    <th key={r.year + '-' + r.quarter} className="p-2 text-right font-semibold" style={{ color: '#4a5a6a' }}>Q{r.quarter}/{r.year}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: 'Doanh thu', key: 'revenue' as const },
                  { label: 'LN gộp', key: 'gross_profit' as const },
                  { label: 'LN ròng', key: 'net_profit' as const },
                ].map(({ label, key }) => (
                  <tr key={label} style={{ borderBottom: '1px solid #0d1520' }}>
                    <td className="p-2 font-medium" style={{ color: '#8b99a8' }}>{label}</td>
                    {income.map((r) => (
                      <td key={r.year + '-' + r.quarter} className="p-2 text-right font-mono" style={{ color: r[key] != null && r[key] < 0 ? '#ff3366' : '#e2e8f0' }}>{fmtB(r[key])}</td>
                    ))}
                  </tr>
                ))}
                <tr style={{ borderBottom: '1px solid #0d1520' }}>
                  <td className="p-2 font-medium" style={{ color: '#8b99a8' }}>Tăng trưởng DT</td>
                  {income.map((r) => (
                    <td key={r.year + '-' + r.quarter} className="p-2 text-right font-mono font-semibold" style={{ color: r.revenue_growth != null ? (r.revenue_growth >= 0 ? '#00ff88' : '#ff3366') : '#4a5a6a' }}>
                      {r.revenue_growth != null ? (r.revenue_growth >= 0 ? '+' : '') + r.revenue_growth.toFixed(1) + '%' : '–'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── 5. DÒNG TIỀN ─────────────────────────────────────── */}
      {cf.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            💸 DÒNG TIỀN
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr style={{ borderBottom: '1px solid #1e2832' }}>
                  <th className="p-2 text-left font-semibold" style={{ color: '#4a5a6a' }}>Chỉ tiêu</th>
                  {cf.map((r) => (
                    <th key={r.year + '-' + r.quarter} className="p-2 text-right font-semibold" style={{ color: '#4a5a6a' }}>Q{r.quarter}/{r.year}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: 'HĐKD (CFO)', key: 'cfo' as const },
                  { label: 'HĐĐT (CFI)', key: 'cfi' as const },
                  { label: 'HĐTC (CFF)', key: 'cff' as const },
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
    { label: 'NN Ròng 7D', val: (fnet >= 0 ? '+' : '') + new Intl.NumberFormat('vi-VN').format(Math.round(fnet)) + ' tỷ', color: fnet >= 0 ? '#00ff88' : '#ff3366' },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {priceItems.map(({ label, val, color }) => (
          <div key={label} className="p-2.5 rounded-lg" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
            <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>
      {history.length > 1 && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
            GIÁ {history.length} PHIÊN GẦN NHẤT
          </div>
          <SparklineModal data={history} volume={volumes} dates={dates} width={580} height={100} />
        </div>
      )}
      <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="grid grid-cols-2" style={{ borderBottom: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest text-center" style={{ color: '#00ff88', borderRight: '1px solid #1e2832' }}>BÊN MUA</div>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest text-center" style={{ color: '#ff3366' }}>BÊN BÁN</div>
        </div>
        {[0, 1, 2].map(i => (
          <div key={i} className="grid grid-cols-2" style={{ borderBottom: i < 2 ? '1px solid #1e2832' : 'none' }}>
            <div className="flex justify-between px-3 py-1.5" style={{ borderRight: '1px solid #1e2832' }}>
              <span className="font-mono text-[12px]" style={{ color: '#00ff88' }}>
                {i === 0 && stock.bid1_price != null ? formatPrice(stock.bid1_price) : i === 1 && stock.bid2_price != null ? formatPrice(stock.bid2_price) : i === 2 && stock.bid3_price != null ? formatPrice(stock.bid3_price) : '–'}
              </span>
              <span className="font-mono text-[11px]" style={{ color: '#8b99a8' }}>
                {i === 0 && stock.bid1_volume != null ? (stock.bid1_volume / 1000).toFixed(0) + 'K' : i === 1 && stock.bid2_volume != null ? (stock.bid2_volume / 1000).toFixed(0) + 'K' : i === 2 && stock.bid3_volume != null ? (stock.bid3_volume / 1000).toFixed(0) + 'K' : '–'}
              </span>
            </div>
            <div className="flex justify-between px-3 py-1.5">
              <span className="font-mono text-[12px]" style={{ color: '#ff3366' }}>
                {i === 0 && stock.ask1_price != null ? formatPrice(stock.ask1_price) : i === 1 && stock.ask2_price != null ? formatPrice(stock.ask2_price) : i === 2 && stock.ask3_price != null ? formatPrice(stock.ask3_price) : '–'}
              </span>
              <span className="font-mono text-[11px]" style={{ color: '#8b99a8' }}>
                {i === 0 && stock.ask1_volume != null ? (stock.ask1_volume / 1000).toFixed(0) + 'K' : i === 1 && stock.ask2_volume != null ? (stock.ask2_volume / 1000).toFixed(0) + 'K' : i === 2 && stock.ask3_volume != null ? (stock.ask3_volume / 1000).toFixed(0) + 'K' : '–'}
              </span>
            </div>
          </div>
        ))}
        {stock.buy_pressure_pct != null && (
          <div className="px-3 py-2" style={{ borderTop: '1px solid #1e2832' }}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px]" style={{ color: '#4a5a6a' }}>Buy Pressure</span>
              <span className="font-mono text-[11px] font-bold" style={{ color: stock.buy_pressure_pct >= 50 ? '#00ff88' : '#ff3366' }}>
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
            <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
            <div className="font-mono font-bold text-sm" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Capital Tab ─────────────────────────────────────────────────────────────
function CapitalTab({ detail, detailLoading }: { detail: StockDetail | null; detailLoading: boolean }) {
  // Luôn hiển thị đơn vị tỷ đồng, format số có dấu phân cách hàng nghìn
  const fmtB = (v: number | null | undefined) => {
    if (v == null) return '–';
    return new Intl.NumberFormat('vi-VN').format(Math.round(v)) + ' tỷ';
  };

  const bal = detail ? [...detail.balance].sort((a, b) => b.year * 10 + b.quarter - (a.year * 10 + a.quarter)) : [];
  const annual = bal.filter((b) => b.quarter === 4).slice(0, 5);
  const latest = bal[0] ?? null;
  const totalAssets = latest ? (latest.total_assets || 1) : 1;

  return (
    <div>
      {detailLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="text-[12px] animate-pulse" style={{ color: '#4a5a6a' }}>Đang tải...</div>
        </div>
      )}
      {!detailLoading && !detail && (
        <div className="flex items-center justify-center py-12">
          <div className="text-[12px]" style={{ color: '#4a5a6a' }}>Không có dữ liệu</div>
        </div>
      )}
      {!detailLoading && detail && (
    <div className="space-y-3">
      {latest && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-3" style={{ color: '#4a5a6a' }}>
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
                <span className="text-[11px]" style={{ color: '#8b99a8' }}>{label}</span>
                <span className="font-mono text-[11px] font-semibold" style={{ color }}>{fmtB(val)}</span>
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
                <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono text-sm font-bold" style={{ color }}>{val}</div>
              </div>
            )) : null}
          </div>
        </div>
      )}
      {annual.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            XU HƯỚNG VỐN (HÀNG NĂM)
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
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
            <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
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
              <div className="text-[10px]" style={{ color: '#4a5a6a' }}>{label}</div>
              <div className="text-[10px] mt-0.5" style={{ color: '#2a3642' }}>{note}</div>
            </div>
            <div className="font-mono font-bold text-sm" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>
      {history.length > 0 && dates.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            LỊCH SỬ GIÁ — {dates.length} phiên
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: '200px' }}>
            <table className="w-full text-[11px]">
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


// ─── Trading Strategy Tab ─────────────────────────────────────────────────────
function TradingStrategyTab({
  stock,
  deskAnalysis,
  aiAnalysis,
  ictSignal,
}: {
  stock: Stock;
  deskAnalysis: DeskAnalysis;
  aiAnalysis?: AIAnalysis;
  ictSignal?: ICTSignal;
}) {
  const d = deskAnalysis;
  const s = d.setup;
  const price = stock.close || stock.price || 0;
  const atr = stock.atr14 ?? 0;
  const atrPct = stock.atr_pct ?? 0;
  const rsi = stock.rsi14 ?? 50;
  const adx = stock.adx14 ?? 0;
  const bullWeight = ictSignal?.bull_weight ?? 0.5;
  const isBear = bullWeight < 0.40;
  const isBull = bullWeight >= 0.65;

  // ── Raw indicator values ──────────────────────────────────────────────────
  const trend = stock.trend_short ?? 0;
  const trendMed = stock.trend_medium ?? 0;
  const mom20 = stock.price_change_20d ?? stock.change_20d ?? 0;
  const pctMa20 = stock.pct_from_ma20 ?? 0;
  const bbPct = stock.bb_pct ?? 0.5;
  const bbWidth = stock.bb_width ?? 15;
  const stochK = stock.stoch_k ?? 50;
  const cci = stock.cci20 ?? 0;
  const williamsR = stock.williams_r ?? -50;

  // ═══════════════════════════════════════════════════════════════════════════
  // BACKTEST-PROVEN SIGNAL DETECTION (493,695 obs, Oct'22–Mar'26, 717 symbols)
  // ═══════════════════════════════════════════════════════════════════════════

  type ActiveSignal = {
    id: string;
    label: string;
    icon: string;
    color: string;
    type: 'buy' | 'sell' | 'warning';
    edge: string;
    horizon: string;
    win: string;
    n: number;
    confidence: 'HIGH' | 'MEDIUM' | 'LOW';
    desc: string;
  };

  const activeSignals: ActiveSignal[] = [];

  // 1. RSI < 30 (Deep Oversold) — edge +1.49% 20D, win 52.9%, n=21,083
  if (rsi < 30) {
    activeSignals.push({
      id: 'rsi_deep_os', label: 'RSI Deep Oversold', icon: '📉', color: '#00ff88',
      type: 'buy', edge: '+1.49%', horizon: '20D', win: '52.9%', n: 21083, confidence: 'HIGH',
      desc: `RSI ${rsi.toFixed(0)} < 30 — cổ phiếu bị bán quá mức. Edge +1.49% forward 20D trên 493K obs.`,
    });
  } else if (rsi < 35) {
    activeSignals.push({
      id: 'rsi_os', label: 'RSI Oversold', icon: '📉', color: '#00ff88',
      type: 'buy', edge: '+1.00%', horizon: '20D', win: '53.7%', n: 40707, confidence: 'HIGH',
      desc: `RSI ${rsi.toFixed(0)} < 35 — oversold. Edge +1.00% forward 20D.`,
    });
  }

  // 2. Stochastic Oversold + Uptrend — edge +0.52%, win 53.8%, n=40,277
  if (stochK < 20 && trendMed === 1) {
    activeSignals.push({
      id: 'pullback_uptrend', label: 'Pullback in Uptrend', icon: '🎯', color: '#00d4ff',
      type: 'buy', edge: '+0.52%', horizon: '20D', win: '53.8%', n: 40277, confidence: 'HIGH',
      desc: `Stochastic ${stochK.toFixed(0)} oversold trong xu hướng tăng (MA20>MA50). Mẫu lớn (40K obs).`,
    });
  }

  // 3. Low Volatility (ATR% < 2%) — Sharpe 0.154 (best risk-adjusted)
  if (atrPct > 0 && atrPct < 2) {
    activeSignals.push({
      id: 'low_vol', label: 'Low Volatility Edge', icon: '🛡️', color: '#ffcc00',
      type: 'buy', edge: '+1.46%', horizon: '20D', win: '48%', n: 6892, confidence: 'HIGH',
      desc: `ATR% ${atrPct.toFixed(1)}% < 2% — biến động thấp outperform. Sharpe 0.154 (cao nhất).`,
    });
  }

  // 4. Triple Oversold (RSI<35 + Stoch<20 + CCI<-100) — win 57.3%
  if (rsi < 35 && stochK < 20 && cci < -100) {
    activeSignals.push({
      id: 'triple_os', label: 'Triple Oversold', icon: '🔻', color: '#a78bfa',
      type: 'buy', edge: '+1.13%', horizon: '20D', win: '57.3%', n: 22328, confidence: 'HIGH',
      desc: `RSI + Stoch + CCI đồng loạt oversold. Ba chỉ báo xác nhận — mẫu 22K obs.`,
    });
  }

  // 5. BB Below Lower Band — WIN 58.6% (best single indicator by win rate)
  if (bbPct < 0) {
    activeSignals.push({
      id: 'bb_below', label: 'BB Below Lower Band', icon: '📊', color: '#00d4ff',
      type: 'buy', edge: '+1.11%', horizon: '20D', win: '58.6%', n: 20796, confidence: 'HIGH',
      desc: `BB %B=${bbPct.toFixed(2)} — giá phá dưới dải BB. Win 58.6% — chỉ báo đơn có tỷ lệ thắng cao nhất (493K obs).`,
    });
  }

  // 6. Panic Bottom (drop>10% MA20 + RSI<30) — BEST Sharpe 0.320, win 65.8%
  if (pctMa20 < -10 && rsi < 30) {
    activeSignals.push({
      id: 'panic_bottom', label: 'PANIC BOTTOM', icon: '💥', color: '#00ff88',
      type: 'buy', edge: '+4.26%', horizon: '20D', win: '65.8%', n: 6585, confidence: 'HIGH',
      desc: `Drop ${pctMa20.toFixed(1)}% from MA20 + RSI ${rsi.toFixed(0)} — Sharpe 0.320, chiến lược #1 trên VNSTOCK.`,
    });
  } else if (mom20 < -15 && rsi < 40) {
    activeSignals.push({
      id: 'mean_rev', label: 'Crash Recovery', icon: '🔄', color: '#ff9500',
      type: 'buy', edge: '+3.32%', horizon: '20D', win: '62.0%', n: 14300, confidence: 'HIGH',
      desc: `Giảm ${mom20.toFixed(1)}% (20D) + RSI ${rsi.toFixed(0)} — mean reversion edge mạnh.`,
    });
  } else if (mom20 < -10) {
    activeSignals.push({
      id: 'crash_10', label: 'Crash -10% Bounce', icon: '🔄', color: '#ffcc00',
      type: 'buy', edge: '+1.76%', horizon: '20D', win: '57.4%', n: 40312, confidence: 'HIGH',
      desc: `Giảm ${mom20.toFixed(1)}% (20D) — crash bounce tiềm năng. Win 57.4%.`,
    });
  }

  // 7. Trend + ADX combo — edge +0.31%, win 49.2%, n=58,713
  if (trend === 1 && adx > 30 && rsi < 70) {
    activeSignals.push({
      id: 'trend_adx', label: 'Trend + ADX Combo', icon: '📈', color: '#00d4ff',
      type: 'buy', edge: '+0.31%', horizon: '20D', win: '49.2%', n: 58713, confidence: 'MEDIUM',
      desc: `Trend UP + ADX ${adx.toFixed(0)} > 30 + RSI < 70 — edge nhẹ nhưng mẫu rất lớn.`,
    });
  }

  // 8. BB Squeeze + ADX — NEGATIVE EDGE (remove as buy signal)
  // Backtest 493K: BB Squeeze<8% + ADX>20 → edge -0.52%, win 46.9%
  // BB Squeeze is NOT a buy signal on VNSTOCK — it's actually a warning
  if (bbWidth < 6 && adx > 25) {
    activeSignals.push({
      id: 'bb_squeeze', label: 'BB Squeeze (Caution)', icon: '⚡', color: '#ff9500',
      type: 'warning', edge: '-0.40%', horizon: '20D', win: '44.8%', n: 41340, confidence: 'MEDIUM',
      desc: `BB Squeeze ${bbWidth.toFixed(1)}% — backtest 493K obs cho thấy breakout setup có edge ÂM trên VNSTOCK.`,
    });
  }

  // ── SELL SIGNALS ──────────────────────────────────────────────────────────

  // 9. RSI > 80 — edge -0.34%, win 43.2% (n=11,968)
  if (rsi > 80) {
    activeSignals.push({
      id: 'rsi_deep_ob', label: 'RSI Deep Overbought', icon: '🔴', color: '#ff3366',
      type: 'sell', edge: '-0.34%', horizon: '20D', win: '43.2%', n: 11968, confidence: 'HIGH',
      desc: `RSI ${rsi.toFixed(0)} > 80 — overbought. Win chỉ 43.2% trên 493K observations.`,
    });
  } else if (rsi > 70) {
    activeSignals.push({
      id: 'rsi_ob', label: 'RSI Overbought', icon: '⚠️', color: '#ff9500',
      type: 'warning', edge: '+0.18%', horizon: '20D', win: '47.6%', n: 38510, confidence: 'LOW',
      desc: `RSI ${rsi.toFixed(0)} > 70 — vùng overbought. Edge gần 0, cân nhắc chốt lời.`,
    });
  }

  // 10. Strong Momentum > +15% (20D) — edge -2.38%
  if (mom20 > 15) {
    activeSignals.push({
      id: 'momentum_ob', label: 'Momentum Overbought', icon: '⚠️', color: '#ff3366',
      type: 'sell', edge: '-2.38%', horizon: '20D', win: '38%', n: 1482, confidence: 'HIGH',
      desc: `Tăng ${mom20.toFixed(1)}% (20D) > 15% — VNSTOCK mean-revert mạnh. Tránh mua đuổi.`,
    });
  }

  // 11. High Volatility ATR% > 5% — edge -1.74%, win 31%
  if (atrPct > 5) {
    activeSignals.push({
      id: 'high_vol', label: 'High Volatility Risk', icon: '💀', color: '#ff3366',
      type: 'sell', edge: '-1.74%', horizon: '20D', win: '31%', n: 2706, confidence: 'HIGH',
      desc: `ATR% ${atrPct.toFixed(1)}% > 5% — biến động cao underperform mạnh. Win chỉ 31%.`,
    });
  }

  // ── Determine primary strategy ────────────────────────────────────────────
  const buySignals = activeSignals.filter(s => s.type === 'buy');
  const sellSignals = activeSignals.filter(s => s.type === 'sell' || s.type === 'warning');

  type StrategyKey = 'strong_buy' | 'buy' | 'caution' | 'sell' | 'neutral';
  const primaryStrategy: StrategyKey =
    sellSignals.some(s => s.type === 'sell') ? 'sell' :
    sellSignals.length > 0 && buySignals.length === 0 ? 'caution' :
    buySignals.length >= 3 ? 'strong_buy' :
    buySignals.length >= 1 ? 'buy' :
    'neutral';

  const stratColors: Record<StrategyKey, { color: string; bg: string; border: string; label: string; icon: string }> = {
    strong_buy: { color: '#00ff88', bg: '#00ff8812', border: '#00ff8835', label: 'STRONG BUY SETUP', icon: '🚀' },
    buy:        { color: '#00d4ff', bg: '#00d4ff10', border: '#00d4ff35', label: 'BUY OPPORTUNITY',   icon: '📈' },
    caution:    { color: '#ff9500', bg: '#ff950010', border: '#ff950035', label: 'THẬN TRỌNG',        icon: '⚠️' },
    sell:       { color: '#ff3366', bg: '#ff336610', border: '#ff336635', label: 'OVERBOUGHT — BÁN',  icon: '🔴' },
    neutral:    { color: '#8b99a8', bg: '#8b99a808', border: '#8b99a825', label: 'WATCH & WAIT',      icon: '👁' },
  };
  const ps = stratColors[primaryStrategy];

  // ── Position sizing via ATR ───────────────────────────────────────────────
  const portfolioVal = 100_000_000;
  const riskPerTrade = isBear ? 0.01 : 0.02;
  const atrStop = atr > 0 ? atr * 1.5 : price * 0.04;
  const positionShares = atrStop > 0 ? Math.floor((portfolioVal * riskPerTrade) / atrStop / 100) * 100 : 0;
  const positionValue = positionShares * price;
  const positionPct = portfolioVal > 0 ? (positionValue / portfolioVal * 100) : 0;
  const sizeMultiplier = isBear ? 0.5 : isBull ? 1.0 : 0.75;
  const adjShares = Math.floor(positionShares * sizeMultiplier / 100) * 100;
  const adjValue  = adjShares * price;

  // ── Checklist items (v4: expanded with new indicators) ────────────────────
  type ChecklistItem = { label: string; pass: boolean; note: string; weight: string };
  const checklist: ChecklistItem[] = [
    {
      label: 'RSI không overbought (<70)',
      pass: rsi < 70,
      note: rsi < 70 ? `RSI ${rsi.toFixed(0)} ✓` : `RSI ${rsi.toFixed(0)} — edge -0.96%`,
      weight: 'edge -2.91% nếu >80',
    },
    {
      label: 'Momentum không quá nóng (<15%)',
      pass: mom20 < 15,
      note: mom20 < 15 ? `${mom20.toFixed(1)}% — chưa overextended` : `${mom20.toFixed(1)}% — mean reversion risk`,
      weight: 'edge -2.38% nếu >15%',
    },
    {
      label: 'ATR% biến động hợp lý (<5%)',
      pass: atrPct < 5 || atrPct === 0,
      note: atrPct > 0 ? `ATR% ${atrPct.toFixed(1)}%` : 'N/A',
      weight: 'win chỉ 31% nếu >5%',
    },
    {
      label: 'Trend UP medium (MA20>MA50)',
      pass: trendMed === 1,
      note: trendMed === 1 ? `MA20>MA50 — edge +0.85%` : `Chưa có uptrend trung hạn`,
      weight: 'edge +0.85%',
    },
    {
      label: 'ADX xác nhận trend (>25)',
      pass: adx > 25,
      note: `ADX ${adx.toFixed(0)}`,
      weight: 'edge +0.40%',
    },
    {
      label: 'Market regime phù hợp',
      pass: !isBear,
      note: isBear ? `BEAR — hạn chế long` : `Bull weight ${(bullWeight*100).toFixed(0)}%`,
      weight: 'bear = giảm bậc signal',
    },
    {
      label: 'RSI oversold bonus (<35)',
      pass: rsi < 35,
      note: rsi < 35 ? `RSI ${rsi.toFixed(0)} — edge +0.91%` : `RSI ${rsi.toFixed(0)} — chưa oversold`,
      weight: 'edge +0.91% ~ +1.52%',
    },
    {
      label: 'BB %B < 0.2 (near lower band)',
      pass: bbPct < 0.2,
      note: `BB %B = ${bbPct.toFixed(2)}`,
      weight: 'win 51% nếu %B < 0',
    },
  ];

  const passCount = checklist.filter(c => c.pass).length;

  return (
    <div className="space-y-3">

      {/* ── 1. Strategy Header ────────────────────────────────────────── */}
      <div className="rounded-xl p-3" style={{ background: ps.bg, border: '1px solid ' + ps.border }}>
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-lg">{ps.icon}</span>
              <span className="font-black text-sm tracking-widest" style={{ color: ps.color }}>
                {ps.label}
              </span>
              {buySignals.length >= 2 && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold tracking-widest"
                  style={{ background: '#a78bfa20', color: '#a78bfa', border: '1px solid #a78bfa40' }}>
                  {buySignals.length} CONFLUENCES
                </span>
              )}
            </div>
            <p className="text-[11px] leading-relaxed" style={{ color: '#c8d4e0' }}>
              {activeSignals.length === 0
                ? 'Chưa có tín hiệu kỹ thuật rõ ràng từ backtest. Nên chờ RSI về vùng oversold (<35) hoặc pullback trong uptrend.'
                : `${buySignals.length} tín hiệu mua + ${sellSignals.length} cảnh báo từ backtest 493,695 quan sát (Oct'22–Mar'26).`
              }
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="text-[9px] tracking-widest mb-1" style={{ color: '#4a5a6a' }}>SIGNALS</div>
            <div className="font-mono font-black text-lg" style={{ color: ps.color }}>
              {buySignals.length}<span className="text-[10px] mx-0.5" style={{ color: '#4a5a6a' }}>/</span>{sellSignals.length}
            </div>
            <div className="text-[9px]" style={{ color: '#4a5a6a' }}>buy / sell</div>
          </div>
        </div>
      </div>

      {/* ── 2. Active Signals (Backtest-verified) ─────────────────────── */}
      {activeSignals.length > 0 && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-2.5" style={{ color: '#4a5a6a' }}>
            🧪 ACTIVE SIGNALS — BACKTEST VERIFIED
          </div>
          <div className="space-y-2">
            {activeSignals.map(sig => (
              <div key={sig.id} className="p-2.5 rounded-lg"
                style={{
                  background: sig.type === 'sell' ? '#ff336808' : sig.type === 'warning' ? '#ff950008' : '#00ff8808',
                  border: '1px solid ' + (sig.type === 'sell' ? '#ff336825' : sig.type === 'warning' ? '#ff950025' : '#00ff8825'),
                }}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{sig.icon}</span>
                    <span className="text-[11px] font-bold" style={{ color: sig.color }}>{sig.label}</span>
                    <span className="px-1.5 py-0.5 rounded text-[8px] font-bold"
                      style={{
                        color: sig.confidence === 'HIGH' ? '#00ff88' : sig.confidence === 'MEDIUM' ? '#ffcc00' : '#8b99a8',
                        background: sig.confidence === 'HIGH' ? '#00ff8815' : sig.confidence === 'MEDIUM' ? '#ffcc0015' : '#8b99a815',
                        border: `1px solid ${sig.confidence === 'HIGH' ? '#00ff8830' : sig.confidence === 'MEDIUM' ? '#ffcc0030' : '#8b99a830'}`,
                      }}>
                      {sig.confidence}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-[10px] font-mono">
                    <span style={{ color: sig.color, fontWeight: 700 }}>{sig.edge}</span>
                    <span style={{ color: '#4a5a6a' }}>win {sig.win}</span>
                    <span style={{ color: '#4a5a6a' }}>n={sig.n.toLocaleString()}</span>
                  </div>
                </div>
                <p className="text-[10px] leading-relaxed" style={{ color: '#8b99a8' }}>{sig.desc}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 3. Entry / Exit Setup ─────────────────────────────────────── */}
      {(s.entry_zone || s.stop_loss || s.target_1) && (
        <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-2.5" style={{ color: '#4a5a6a' }}>
            📍 ENTRY / EXIT PLAN
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: '🟢 Vùng vào lệnh',   val: s.entry_zone,   col: '#00ff88' },
              { label: '🛑 Cắt lỗ (Stop)',    val: s.stop_loss,    col: '#ff3366' },
              { label: '🎯 Mục tiêu 1 (T1)',  val: s.target_1,     col: '#00d4ff' },
              { label: '🚀 Mục tiêu 2 (T2)',  val: s.target_2,     col: '#a78bfa' },
              { label: '⚖️ Risk / Reward',    val: s.risk_reward,  col: '#ffcc00' },
              { label: '⏱ Thời gian giữ',    val: s.time_horizon, col: '#8b99a8' },
            ].filter(r => r.val).map(({ label, val, col }) => (
              <div key={label} className="p-2 rounded-lg"
                style={{ background: '#0d1520', border: '1px solid ' + col + '20' }}>
                <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
                <div className="font-mono text-[11px] font-semibold leading-snug" style={{ color: col }}>
                  {val}
                </div>
              </div>
            ))}
          </div>
          {s.invalidation && (
            <div className="mt-2 px-2.5 py-2 rounded-lg text-[11px]"
              style={{ background: '#ff336610', border: '1px solid #ff336630' }}>
              <span style={{ color: '#ff3366' }}>⚡ Invalidation: </span>
              <span style={{ color: '#c8d4e0' }}>{s.invalidation}</span>
            </div>
          )}
        </div>
      )}

      {/* ── 4. Position Sizing (ATR-based) ───────────────────────────── */}
      <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="flex items-center justify-between mb-2.5">
          <div className="text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a' }}>
            📐 POSITION SIZING — ATR-BASED (ref: 100M VND)
          </div>
          <div className="text-[9px] px-1.5 py-0.5 rounded"
            style={{ background: isBear ? '#ff336615' : isBull ? '#00ff8815' : '#ffcc0015',
                     color: isBear ? '#ff3366' : isBull ? '#00ff88' : '#ffcc00',
                     border: '1px solid ' + (isBear ? '#ff336630' : isBull ? '#00ff8830' : '#ffcc0030') }}>
            {isBear ? 'BEAR × 0.5' : isBull ? 'BULL × 1.0' : 'RANGE × 0.75'}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mb-2">
          {[
            { label: 'ATR Stop (1.5×)',  val: atr > 0 ? `${(atrStop).toFixed(2)}đ` : '–',                           col: '#ffcc00' },
            { label: 'Số CP gợi ý',      val: adjShares > 0 ? adjShares.toLocaleString('vi-VN') + ' CP' : '–',       col: '#00d4ff' },
            { label: 'Giá trị vị thế',   val: adjValue > 0 ? new Intl.NumberFormat('vi-VN').format(Math.round(adjValue / 1e9)) + ' tỷ' : '–', col: '#00ff88' },
          ].map(({ label, val, col }) => (
            <div key={label} className="p-2 rounded-lg text-center" style={{ background: '#0d1520' }}>
              <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>{label}</div>
              <div className="font-mono font-bold text-sm" style={{ color: col }}>{val}</div>
            </div>
          ))}
        </div>
        <div className="text-[10px] leading-relaxed" style={{ color: '#4a5a6a' }}>
          Rủi ro mỗi lệnh: {isBear ? '1%' : '2%'} portfolio · ATR ({atrPct > 0 ? atrPct.toFixed(1) + '% volatility' : 'N/A'}) · Chỉ mang tính tham khảo
        </div>
        {adjValue > 0 && (
          <div className="mt-2">
            <div className="flex justify-between text-[10px] mb-1" style={{ color: '#4a5a6a' }}>
              <span>% Portfolio</span>
              <span style={{ color: '#00d4ff' }}>{Math.min(positionPct * sizeMultiplier, 100).toFixed(1)}%</span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
              <div className="h-full rounded-full"
                style={{ width: Math.min(positionPct * sizeMultiplier, 100) + '%', background: '#00d4ff',
                         boxShadow: '0 0 6px #00d4ff60' }} />
            </div>
          </div>
        )}
      </div>

      {/* ── 5. Entry Checklist (v4: expanded) ──────────────────────────── */}
      <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="flex items-center justify-between mb-2.5">
          <div className="text-[10px] font-semibold tracking-widest" style={{ color: '#4a5a6a' }}>
            ✅ ENTRY CHECKLIST — BACKTEST v5 (493K obs)
          </div>
          <div className="font-mono text-[11px] font-bold"
            style={{ color: passCount >= 6 ? '#00ff88' : passCount >= 4 ? '#ffcc00' : '#ff3366' }}>
            {passCount} / {checklist.length}
          </div>
        </div>
        <div className="space-y-1.5">
          {checklist.map(({ label, pass, note, weight }) => (
            <div key={label} className="flex items-start gap-2 px-2 py-1.5 rounded-lg"
              style={{ background: pass ? '#00ff8808' : '#ff336808',
                       border: '1px solid ' + (pass ? '#00ff8825' : '#ff336825') }}>
              <span className="text-[12px] mt-0.5 shrink-0" style={{ color: pass ? '#00ff88' : '#ff3366' }}>
                {pass ? '✓' : '✗'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-medium" style={{ color: pass ? '#c8d4e0' : '#8b99a8' }}>
                  {label}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px]" style={{ color: '#4a5a6a' }}>{note}</span>
                  <span className="text-[9px] font-mono" style={{ color: '#3a4a5a' }}>({weight})</span>
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-2.5 px-2.5 py-2 rounded-lg text-[11px]"
          style={{ background: passCount >= 6 ? '#00ff8808' : passCount >= 4 ? '#ffcc0008' : '#ff336808',
                   border: '1px solid ' + (passCount >= 6 ? '#00ff8828' : passCount >= 4 ? '#ffcc0028' : '#ff336828') }}>
          <span style={{ color: passCount >= 6 ? '#00ff88' : passCount >= 4 ? '#ffcc00' : '#ff3366', fontWeight: 700 }}>
            {passCount >= 7 ? '★ Setup tối ưu — Đủ điều kiện vào lệnh (nhiều confluence)' :
             passCount >= 5 ? '◆ Setup tốt — Có thể vào lệnh với size vừa' :
             passCount >= 4 ? '◇ Setup trung bình — Giảm size, chờ thêm confirmation' :
             '✗ Setup yếu — Nhiều tín hiệu tiêu cực, tiếp tục theo dõi'}
          </span>
        </div>
      </div>

      {/* ── 6. Indicator Dashboard ───────────────────────────────────── */}
      <div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
        <div className="text-[10px] font-semibold tracking-widest mb-2.5" style={{ color: '#4a5a6a' }}>
          📊 INDICATOR DASHBOARD
        </div>
        <div className="grid grid-cols-4 gap-1.5">
          {[
            { label: 'RSI', val: rsi.toFixed(0), color: rsi > 70 ? '#ff3366' : rsi < 30 ? '#00ff88' : '#8b99a8', sub: rsi < 30 ? 'Oversold' : rsi > 70 ? 'Overbought' : 'Neutral' },
            { label: 'ADX', val: adx.toFixed(0), color: adx > 30 ? '#00d4ff' : adx > 25 ? '#ffcc00' : '#4a5a6a', sub: adx > 30 ? 'Strong' : adx > 25 ? 'Trend' : 'Weak' },
            { label: 'Stoch K', val: stochK.toFixed(0), color: stochK < 20 ? '#00ff88' : stochK > 80 ? '#ff3366' : '#8b99a8', sub: stochK < 20 ? 'Oversold' : stochK > 80 ? 'OB' : '' },
            { label: 'CCI', val: cci.toFixed(0), color: cci < -100 ? '#00ff88' : cci > 200 ? '#ff3366' : '#8b99a8', sub: cci < -100 ? 'Oversold' : cci > 100 ? 'OB' : '' },
            { label: 'BB %B', val: bbPct.toFixed(2), color: bbPct < 0 ? '#00ff88' : bbPct > 1 ? '#ff3366' : '#8b99a8', sub: bbPct < 0 ? 'Below' : bbPct > 1 ? 'Above' : '' },
            { label: 'W%R', val: williamsR.toFixed(0), color: williamsR < -80 ? '#00ff88' : williamsR > -20 ? '#ff3366' : '#8b99a8', sub: williamsR < -80 ? 'Oversold' : '' },
            { label: 'ATR%', val: atrPct > 0 ? atrPct.toFixed(1) + '%' : '–', color: atrPct < 2 ? '#ffcc00' : atrPct > 5 ? '#ff3366' : '#8b99a8', sub: atrPct < 2 ? 'Low Vol' : atrPct > 5 ? 'High!' : '' },
            { label: 'BB Width', val: bbWidth.toFixed(1), color: bbWidth < 8 ? '#a78bfa' : '#8b99a8', sub: bbWidth < 8 ? 'Squeeze!' : '' },
          ].map(({ label, val, color, sub }) => (
            <div key={label} className="p-2 rounded-lg text-center" style={{ background: '#0d1520' }}>
              <div className="text-[9px] mb-0.5" style={{ color: '#4a5a6a' }}>{label}</div>
              <div className="font-mono text-sm font-bold" style={{ color }}>{val}</div>
              {sub && <div className="text-[8px] mt-0.5" style={{ color }}>{sub}</div>}
            </div>
          ))}
        </div>
      </div>

      {/* ── 7. AI Strategy Note ───────────────────────────────────────── */}
      {aiAnalysis?.sections && (aiAnalysis.sections as Record<string,string>).ict_analysis && (
        <div className="rounded-xl p-3" style={{ background: '#0f1519', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-semibold tracking-widest mb-1.5" style={{ color: '#a78bfa' }}>
            🤖 AI — ICT ANALYSIS
          </div>
          <p className="text-[11px] leading-relaxed" style={{ color: '#a8b8c8' }}>
            {(aiAnalysis.sections as Record<string,string>).ict_analysis}
          </p>
        </div>
      )}

    </div>
  );
}


// ============ Main Component ============

// ─── Inner Modal (no hooks - pure render) ────────────────────────────────────
function ModalInner({
  stock,
  sectorStatus,
  preloadedAnalysis,
  ictSignal,
  regimeBullWeight,
  detail,
  detailLoading,
  visible,
  activeTab,
  setActiveTab,
  onClose,
}: {
  stock: Stock;
  sectorStatus?: 'accumulating' | 'distributing' | 'neutral';
  preloadedAnalysis?: AIAnalysis;
  ictSignal?: ICTSignal;
  regimeBullWeight?: number;
  detail: StockDetail | null;
  detailLoading: boolean;
  visible: boolean;
  activeTab: string;
  setActiveTab: (tab: string) => void;
  onClose: () => void;
}) {
  const close = () => {
    onClose();
  };

  // bull_weight: ictSignal (stock-level) > regimeBullWeight (market-level) > 0.5 (neutral fallback)
  // Tránh race condition: nếu ICT chưa load, dùng regime bull_weight thay vì hardcode 0.5
  const bullWeight = ictSignal?.bull_weight ?? regimeBullWeight;
  const analysis = preloadedAnalysis || generateAnalysis(stock, sectorStatus, bullWeight);
  const deskAnalysis = generateDeskAnalysis(stock, ictSignal, sectorStatus);
  // recDisplay: dùng analysis.recommendation (= AI khi có, rule-based khi không)
  // Đảm bảo nhất quán với AnalysisTab bên dưới
  const recDisplay = getRecommendationDisplay(analysis.recommendation);
  const tierColor = getTierColor(stock.tier);
  const price = stock.close || stock.price || 0;
  const change = stock.change_20d || stock.change_5d || 0;
  const baseTabs = [
    { id: 'analysis',  label: 'Phân tích',  icon: Target },
    { id: 'strategy',  label: 'Chiến lược', icon: Zap },
    { id: 'scores',    label: 'Điểm số',    icon: Activity },
    { id: 'finance',   label: 'Tài chính',  icon: BarChart3 },
    { id: 'trading',   label: 'Giao dịch',  icon: TrendingUp },
    { id: 'stats',     label: 'Thống kê',   icon: Activity },
  ];
  const tabs = ictSignal ? [...baseTabs, { id: 'ict', label: '🧠 ICT', icon: Info }] : baseTabs;


  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
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
                  className="px-2 py-0.5 rounded text-[11px] font-bold"
                  style={{
                    background: (tierColor) + '20',
                    color: tierColor,
                    border: '1px solid ' + (tierColor) + '40',
                  }}
                >
                  {stock.tier}
                </span>
              </div>
              <div className="text-sm mt-1" style={{ color: '#8b99a8' }}>
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
                  style={{ color: change >= 0 ? '#00ff88' : '#ff3366' }}
                >
                  {formatPercent(change)}
                </span>
                <span className="text-[11px]" style={{ color: '#4a5a6a' }}>
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
              <div className="text-[11px] mt-1" style={{ color: '#4a5a6a' }}>
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
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className="flex-1 py-2.5 flex items-center justify-center gap-1.5 text-[12px] font-medium transition-all"
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
          {activeTab === 'analysis' && <AnalysisTab stock={stock} deskAnalysis={deskAnalysis} aiAnalysis={preloadedAnalysis} />}

          {/* Strategy Tab */}
          {activeTab === 'strategy' && (
            <TradingStrategyTab
              stock={stock}
              deskAnalysis={deskAnalysis}
              aiAnalysis={preloadedAnalysis}
              ictSignal={ictSignal}
            />
          )}

          {/* Scores Tab */}
          {activeTab === 'scores' && (
            <div>
              {/* Component Score Circles */}
              <div className="p-3 rounded-lg mb-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
                <div className="text-[11px] mb-3" style={{ color: '#4a5a6a', letterSpacing: '0.5px' }}>
                  COMPONENT SCORES (v5 — 5 trụ cột)
                </div>
                <div className="grid grid-cols-5 gap-2">
                  <ScoreCircle value={stock.fundamental_score} label="FUND 35%" Icon={Shield} />
                  <ScoreCircle value={stock.smart_money_score} label="FLOW 25%" Icon={Globe} />
                  <ScoreCircle value={stock.momentum_score} label="MOM 10%" Icon={Zap} />
                  <ScoreCircle value={stock.technical_score} label="TECH 20%" Icon={Activity} />
                  <ScoreCircle value={stock.mean_reversion_score ?? 50} label="MR 10%" Icon={TrendingUp} />
                </div>
              </div>

              {/* Composite Score Bar */}
              <div className="p-2.5 rounded-lg mb-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-[11px] font-bold" style={{ color: '#00d4ff' }}>COMPOSITE SCORE</span>
                  <span className="text-[14px] font-mono font-black" style={{ color: getScoreColor(stock.composite_score) }}>
                    {stock.composite_score.toFixed(1)}
                  </span>
                </div>
                <div className="h-2 rounded-full overflow-hidden" style={{ background: '#1e2832' }}>
                  <div className="h-full rounded-full" style={{ width: `${Math.min(stock.composite_score, 100)}%`, background: getScoreColor(stock.composite_score), boxShadow: `0 0 8px ${getScoreColor(stock.composite_score)}60` }} />
                </div>
              </div>

              {/* ── FUNDAMENTAL BREAKDOWN ──────────────────────────── */}
              {(() => {
                const fmtPct = (v?: number) => v != null ? (Math.abs(v) < 1 ? (v * 100).toFixed(1) + '%' : v.toFixed(1) + '%') : '–';
                const fmtX = (v?: number) => v != null ? v.toFixed(1) + 'x' : '–';
                const subColor = (v: number) => v >= 70 ? '#00ff88' : v >= 50 ? '#00d4ff' : v >= 30 ? '#ffcc00' : '#ff3366';

                type SubItem = { label: string; raw: string; weight: string; note?: string };

                const fundItems: SubItem[] = [
                  { label: 'ROE', raw: fmtPct(stock.roe), weight: '25%', note: stock.roe != null ? (stock.roe > 0.15 || stock.roe > 15 ? 'Tốt' : stock.roe > 0.08 || stock.roe > 8 ? 'TB' : 'Yếu') : undefined },
                  { label: 'ROA', raw: fmtPct(stock.roa), weight: '15%' },
                  { label: 'Revenue Growth', raw: fmtPct(stock.revenue_growth), weight: '20%', note: stock.revenue_growth != null ? ((stock.revenue_growth > 0.1 || stock.revenue_growth > 10) ? 'Tăng trưởng' : stock.revenue_growth < 0 ? 'Suy giảm' : 'Ổn định') : undefined },
                  { label: 'Net Margin', raw: fmtPct(stock.net_margin), weight: '15%' },
                  { label: 'P/E', raw: fmtX(stock.pe), weight: '15%', note: stock.pe != null ? (stock.pe < 10 ? 'Rẻ' : stock.pe < 20 ? 'Hợp lý' : 'Đắt') : undefined },
                  { label: 'D/E', raw: fmtX(stock.debt_equity), weight: '10%', note: stock.debt_equity != null ? (stock.debt_equity < 0.5 ? 'An toàn' : stock.debt_equity < 1.5 ? 'TB' : 'Cao') : undefined },
                ];

                const flowItems: SubItem[] = [
                  { label: 'Foreign Net 7D', raw: stock.foreign_net_7d != null ? `${stock.foreign_net_7d >= 0 ? '+' : ''}${Math.round(stock.foreign_net_7d)} tỷ` : '–', weight: '60%', note: stock.foreign_net_7d != null ? (stock.foreign_net_7d > 50 ? 'Mua ròng mạnh' : stock.foreign_net_7d > 0 ? 'Mua ròng' : stock.foreign_net_7d < -50 ? 'Bán ròng mạnh' : 'Bán ròng') : undefined },
                  { label: 'Foreign Net 30D', raw: stock.foreign_net_30d != null ? `${stock.foreign_net_30d >= 0 ? '+' : ''}${Math.round(stock.foreign_net_30d)} tỷ` : '–', weight: '40%' },
                ];

                const momItems: SubItem[] = [
                  { label: 'Price 5D', raw: stock.price_change_5d != null ? `${stock.price_change_5d >= 0 ? '+' : ''}${stock.price_change_5d.toFixed(1)}%` : '–', weight: '25%' },
                  { label: 'Price 20D', raw: stock.price_change_20d != null ? `${stock.price_change_20d >= 0 ? '+' : ''}${stock.price_change_20d.toFixed(1)}%` : '–', weight: '15%', note: stock.price_change_20d != null ? (stock.price_change_20d > 15 ? '⚠ Edge ~0%' : stock.price_change_20d < -15 ? '🟢 Mean Rev edge' : '') : undefined },
                  { label: 'Volume Ratio', raw: stock.vol_ratio != null ? `${stock.vol_ratio.toFixed(2)}x` : '–', weight: '30%', note: stock.vol_ratio != null ? (stock.vol_ratio > 2 ? 'Vol spike!' : stock.vol_ratio < 0.5 ? 'Vol dry' : '') : undefined },
                  { label: 'RS vs Market', raw: '–', weight: '30%' },
                ];

                const rsi = stock.rsi14 ?? 50;
                const adx = stock.adx14 ?? 0;
                const pma20 = stock.pct_from_ma20 ?? 0;
                const bbW = stock.bb_width ?? 15;
                const atrP = stock.atr_pct ?? 3;

                const techItems: SubItem[] = [
                  { label: 'RSI(14)', raw: rsi.toFixed(1), weight: '30%', note: rsi < 30 ? '🟢 Oversold +1.49%' : rsi < 35 ? '🟢 OS nhẹ +1.00%' : rsi > 80 ? '🔴 OB! -0.34%' : rsi > 70 ? '🟡 Overbought' : 'Trung tính' },
                  { label: 'BB Position', raw: `MA20: ${pma20.toFixed(1)}%`, weight: '25%', note: pma20 < -(bbW/2) ? '🟢 Below BB ↓ win 58.6%' : pma20 > (bbW/2) ? 'Above BB ↑' : 'Trong dải BB' },
                  { label: 'Stoch/W%R', raw: stock.williams_r != null ? `W%R: ${stock.williams_r.toFixed(0)}` : (stock.stoch_k != null ? `K: ${stock.stoch_k.toFixed(0)}` : '–'), weight: '20%', note: (stock.williams_r ?? -50) < -80 ? '🟢 Oversold' : (stock.williams_r ?? -50) > -20 ? '🔴 Overbought' : '' },
                  { label: 'Trend', raw: (stock.trend_short ?? 0) > 0 ? 'UP ↑' : (stock.trend_short ?? 0) < 0 ? 'DOWN ↓' : 'Sideways', weight: '15%', note: (stock.trend_medium ?? 0) > 0 ? 'MA20>MA50 ✓' : '' },
                  { label: 'ADX', raw: adx.toFixed(1), weight: '10%', note: adx > 30 ? 'Trend mạnh' : adx > 25 ? 'Trending' : 'Yếu' },
                ];

                const p20d = stock.price_change_20d ?? 0;
                const mrItems: SubItem[] = [
                  { label: 'Crash 20D', raw: `${p20d >= 0 ? '+' : ''}${p20d.toFixed(1)}%`, weight: '–', note: p20d < -15 ? '🟢 Crash bounce +3.3%' : p20d < -10 ? '🟢 Dip bounce +1.8%' : p20d > 15 ? '🟡 No edge' : '' },
                  { label: 'Distance MA20', raw: `${pma20 >= 0 ? '+' : ''}${pma20.toFixed(1)}%`, weight: '–', note: pma20 < -10 ? '🟢 Panic zone' : '' },
                  { label: 'RSI Level', raw: rsi.toFixed(0), weight: '–', note: rsi < 30 ? '🟢 Deep OS' : rsi < 40 ? 'OS vùng phục hồi' : '' },
                  { label: 'ATR%', raw: `${atrP.toFixed(1)}%`, weight: '–', note: atrP > 5 ? '⚠ Vol cao' : atrP < 2 ? '🟢 Vol thấp +1.46%' : '' },
                ];

                const sections = [
                  { label: 'Fundamental', color: '#a855f7', score: stock.fundamental_score, weight: '35%', items: fundItems },
                  { label: 'Smart Flow', color: '#00d4ff', score: stock.smart_money_score, weight: '25%', items: flowItems },
                  { label: 'Momentum', color: '#ffcc00', score: stock.momentum_score, weight: '10%', items: momItems },
                  { label: 'Technical', color: '#00ff88', score: stock.technical_score, weight: '20%', items: techItems },
                  { label: 'Mean Reversion', color: '#ff9500', score: stock.mean_reversion_score ?? 50, weight: '10%', items: mrItems },
                ];

                return (
                  <div className="space-y-2">
                    {sections.map(sec => (
                      <div key={sec.label} className="rounded-lg overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
                        {/* Section header */}
                        <div className="flex justify-between items-center px-3 py-2" style={{ borderBottom: '1px solid #1e2832' }}>
                          <div className="flex items-center gap-2">
                            <span className="text-[11px] font-bold" style={{ color: sec.color }}>{sec.label}</span>
                            <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: `${sec.color}12`, color: `${sec.color}aa`, border: `1px solid ${sec.color}20` }}>{sec.weight}</span>
                          </div>
                          <span className="text-[13px] font-mono font-black" style={{ color: getScoreColor(sec.score) }}>{sec.score.toFixed(0)}</span>
                        </div>
                        {/* Sub-items */}
                        <div className="px-3 py-1.5">
                          {sec.items.map(item => (
                            <div key={item.label} className="flex items-center gap-2 py-1" style={{ borderBottom: '1px solid #0d1520' }}>
                              <span className="text-[10px] w-[110px] shrink-0" style={{ color: '#6a7a8a' }}>{item.label}</span>
                              <span className="text-[10px] font-mono font-semibold w-[70px] shrink-0" style={{ color: '#c8d4e0' }}>{item.raw}</span>
                              <span className="text-[9px] w-[30px] shrink-0" style={{ color: '#3a4a5a' }}>{item.weight}</span>
                              {item.note && <span className="text-[9px]" style={{ color: item.note.startsWith('🟢') ? '#00ff88' : item.note.startsWith('🔴') ? '#ff3366' : item.note.startsWith('🟡') || item.note.startsWith('⚠') ? '#ff9500' : '#4a5a6a' }}>{item.note}</span>}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })()}
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
                  <SparklineModal
                    data={stock.price_history ?? []}
                    volume={stock.volume_history}
                    dates={stock.dates}
                    width={320}
                    height={80}
                  />
                  <div className="text-center py-2 text-[11px]" style={{ color: '#4a5a6a' }}>
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

        {/* ── TAB: THỐNG KÊ ────────────────────────────────── */}
        {activeTab === 'stats' && <StatsTab stock={stock} />}

        {/* Footer Disclaimer */}
        <div className="px-4 py-2" style={{ borderTop: '1px solid #1e2832', background: '#0a0f14' }}>
          <p className="text-[10px] text-center" style={{ color: '#4a5a6a' }}>
            * Phân tích chỉ mang tính tham khảo, không phải khuyến nghị đầu tư
          </p>
        </div>
      </div>
    </div>
  </div>
  );
}

// ─── Main Export (hooks only) ─────────────────────────────────────────────────
export default function StockModal({
  stock,
  sectorStatus,
  preloadedAnalysis,
  ictSignal,
  regimeBullWeight,
  onClose,
}: StockModalProps) {
  const [visible, setVisible] = useState(false);
  const [activeTab, setActiveTab] = useState('analysis');
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (stock) {
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
    }
  }, [stock]);

  useEffect(() => {
    if (!stock || detail) return;
    const needsDetail = ['finance', 'trading', 'stats'].includes(activeTab);
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

  if (!stock) return null;

  return (
    <ModalInner
      stock={stock}
      sectorStatus={sectorStatus}
      preloadedAnalysis={preloadedAnalysis}
      ictSignal={ictSignal}
      regimeBullWeight={regimeBullWeight}
      detail={detail}
      detailLoading={detailLoading}
      visible={visible}
      activeTab={activeTab}
      setActiveTab={setActiveTab}
      onClose={() => {
        setVisible(false);
        setTimeout(onClose, 150);
      }}
    />
  );
}
