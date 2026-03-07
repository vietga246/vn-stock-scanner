'use client';

import { useState, useRef, useMemo, useCallback } from 'react';
import { formatPrice } from '@/lib/api';

interface OHLCV {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface CandlestickChartProps {
  symbol: string;
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  dates: string[];
  width?: number;
  height?: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function calcMA(data: number[], period: number): (number | null)[] {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    const slice = data.slice(i - period + 1, i + 1);
    return slice.reduce((s, v) => s + v, 0) / period;
  });
}

function calcRSI(close: number[], period = 14): (number | null)[] {
  const rsi: (number | null)[] = Array(close.length).fill(null);
  if (close.length < period + 1) return rsi;
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const d = close[i] - close[i - 1];
    if (d > 0) gains += d; else losses -= d;
  }
  let avgG = gains / period, avgL = losses / period;
  rsi[period] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  for (let i = period + 1; i < close.length; i++) {
    const d = close[i] - close[i - 1];
    avgG = (avgG * (period - 1) + Math.max(d, 0)) / period;
    avgL = (avgL * (period - 1) + Math.max(-d, 0)) / period;
    rsi[i] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  }
  return rsi;
}

function formatDate(s: string) {
  const d = new Date(s);
  return `${d.getDate().toString().padStart(2,'0')}/${(d.getMonth()+1).toString().padStart(2,'0')}`;
}

function formatMonth(s: string) {
  const d = new Date(s);
  const months = ['Th1','Th2','Th3','Th4','Th5','Th6','Th7','Th8','Th9','Th10','Th11','Th12'];
  return months[d.getMonth()];
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function CandlestickChart({
  symbol, open, high, low, close, volume, dates,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [showMA20, setShowMA20] = useState(true);
  const [showMA50, setShowMA50] = useState(true);
  const [showRSI, setShowRSI] = useState(true);
  const [showVol, setShowVol] = useState(true);
  const [range, setRange] = useState<'1M' | '3M' | '6M' | 'All'>('3M');

  // ── Slice data by range
  const sliceCount = range === '1M' ? 22 : range === '3M' ? 65 : range === '6M' ? 130 : close.length;
  const start = Math.max(0, close.length - sliceCount);
  const D = useMemo(() => {
    const arr: OHLCV[] = [];
    for (let i = start; i < close.length; i++) {
      arr.push({ date: dates[i], open: open[i], high: high[i], low: low[i], close: close[i], volume: volume[i] });
    }
    return arr;
  }, [start, close, open, high, low, volume, dates]);

  const closes = useMemo(() => D.map(d => d.close), [D]);
  const ma20 = useMemo(() => calcMA(closes, 20), [closes]);
  const ma50 = useMemo(() => calcMA(closes, 50), [closes]);
  const rsi  = useMemo(() => calcRSI(closes, 14), [closes]);

  // ── Layout constants
  const W = 620;
  const PRICE_H = showRSI ? 280 : showVol ? 320 : 380;
  const VOL_H = showVol ? 60 : 0;
  const RSI_H = showRSI ? 70 : 0;
  const GAP = 4;
  const PAD_L = 8, PAD_R = 52, PAD_T = 12, PAD_B = 24;
  const chartW = W - PAD_L - PAD_R;

  const volTop = PAD_T + PRICE_H + GAP;
  const rsiTop = volTop + VOL_H + (showVol ? GAP : 0);
  const totalH = PAD_T + PRICE_H + (showVol ? GAP + VOL_H : 0) + (showRSI ? GAP + RSI_H : 0) + PAD_B;

  // ── Price scale
  const priceMin = Math.min(...D.map(d => d.low)) * 0.998;
  const priceMax = Math.max(...D.map(d => d.high)) * 1.002;
  const priceRange = priceMax - priceMin || 1;
  const py = (v: number) => PAD_T + PRICE_H - ((v - priceMin) / priceRange) * PRICE_H;

  // ── Volume scale
  const volMax = Math.max(...D.map(d => d.volume)) * 1.05;
  const vy = (v: number) => volTop + VOL_H - (v / volMax) * VOL_H;

  // ── RSI scale
  const ry = (v: number) => rsiTop + RSI_H - ((v - 0) / 100) * RSI_H;

  // ── Candle geometry
  const n = D.length;
  const candleW = Math.max(1, Math.min(10, (chartW / n) - 1));
  const cx = (i: number) => PAD_L + (i / (n - 1 || 1)) * chartW;

  // ── Grid price levels
  const priceGridCount = 5;
  const priceStep = priceRange / priceGridCount;
  const priceGrids = Array.from({ length: priceGridCount + 1 }, (_, i) => priceMin + i * priceStep);

  // ── X-axis labels — show month markers
  const xLabels: { idx: number; label: string }[] = [];
  let lastMonth = -1;
  D.forEach((d, i) => {
    const m = new Date(d.date).getMonth();
    const yr = new Date(d.date).getFullYear();
    if (m !== lastMonth) {
      const isJan = m === 0;
      xLabels.push({ idx: i, label: isJan ? String(yr) : formatMonth(d.date) });
      lastMonth = m;
    }
  });

  // ── MA line path
  const maPath = (ma: (number | null)[]) => {
    let d = '';
    ma.forEach((v, i) => {
      if (v == null) return;
      const x = cx(i), y = py(v);
      d += d === '' || ma[i-1] == null ? `M${x},${y}` : `L${x},${y}`;
    });
    return d;
  };

  // ── RSI line path
  const rsiPath = () => {
    let d = '';
    rsi.forEach((v, i) => {
      if (v == null) return;
      const x = cx(i), y = ry(v);
      d += d === '' || rsi[i-1] == null ? `M${x},${y}` : `L${x},${y}`;
    });
    return d;
  };

  // ── Mouse handler
  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const rect = (e.target as SVGElement).closest('svg')!.getBoundingClientRect();
    const x = e.clientX - rect.left - PAD_L;
    const idx = Math.max(0, Math.min(n - 1, Math.round((x / chartW) * (n - 1))));
    setHoverIdx(idx);
  }, [n, chartW]);

  const hBar = hoverIdx != null ? D[hoverIdx] : null;
  const hRSI = hoverIdx != null ? rsi[hoverIdx] : null;
  const hChange = hBar ? ((hBar.close - hBar.open) / hBar.open * 100) : 0;

  return (
    <div className="flex flex-col gap-2" ref={containerRef}>
      {/* ── Header: OHLCV info + toggles */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        {/* OHLCV values on hover */}
        <div className="flex items-center gap-3 font-mono text-[10px]">
          {hBar ? (
            <>
              <span style={{ color: '#4a5a6a' }}>{hBar.date}</span>
              <span>O<span style={{ color: hBar.close >= hBar.open ? '#00ff88' : '#ff3366' }}> {formatPrice(hBar.open)}</span></span>
              <span>H<span style={{ color: '#00ff88' }}> {formatPrice(hBar.high)}</span></span>
              <span>L<span style={{ color: '#ff3366' }}> {formatPrice(hBar.low)}</span></span>
              <span>C<span style={{ color: hBar.close >= hBar.open ? '#00ff88' : '#ff3366' }}> {formatPrice(hBar.close)}</span></span>
              <span style={{ color: hChange >= 0 ? '#00ff88' : '#ff3366' }}>
                {hChange >= 0 ? '+' : ''}{hChange.toFixed(2)}%
              </span>
            </>
          ) : (
            <span style={{ color: '#4a5a6a' }}>{symbol} · 1D · HOSE — {n} phiên</span>
          )}
        </div>

        {/* Toggles */}
        <div className="flex items-center gap-1.5">
          {[
            { label: 'MA20', color: '#ffcc00', active: showMA20, toggle: () => setShowMA20(v => !v) },
            { label: 'MA50', color: '#00d4ff', active: showMA50, toggle: () => setShowMA50(v => !v) },
            { label: 'Vol',  color: '#a78bfa', active: showVol,  toggle: () => setShowVol(v => !v) },
            { label: 'RSI',  color: '#ff9500', active: showRSI,  toggle: () => setShowRSI(v => !v) },
          ].map(({ label, color, active, toggle }) => (
            <button
              key={label}
              onClick={toggle}
              className="px-2 py-0.5 rounded text-[9px] font-semibold transition-all"
              style={{
                background: active ? `${color}22` : 'transparent',
                border: `1px solid ${active ? color : '#2a3642'}`,
                color: active ? color : '#4a5a6a',
              }}
            >
              {label}
            </button>
          ))}
          {/* Range selector */}
          {(['1M','3M','6M','All'] as const).map(r => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className="px-2 py-0.5 rounded text-[9px] font-semibold transition-all"
              style={{
                background: range === r ? '#00d4ff22' : 'transparent',
                border: `1px solid ${range === r ? '#00d4ff' : '#2a3642'}`,
                color: range === r ? '#00d4ff' : '#4a5a6a',
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* ── SVG Chart */}
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${totalH}`}
        style={{ cursor: 'crosshair', display: 'block', background: '#0a0f14', borderRadius: '8px' }}
        onMouseMove={onMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* ── Price grid lines */}
        {priceGrids.map((v, i) => (
          <g key={i}>
            <line
              x1={PAD_L} y1={py(v)} x2={W - PAD_R} y2={py(v)}
              stroke="#1a2530" strokeWidth="1" strokeDasharray="3,4"
            />
            <text
              x={W - PAD_R + 4} y={py(v) + 3.5}
              fontSize="8" fill="#3a4a5a" fontFamily="monospace"
            >
              {formatPrice(v)}
            </text>
          </g>
        ))}

        {/* ── Volume grid lines */}
        {showVol && [0.5, 1].map((frac, i) => (
          <line key={i}
            x1={PAD_L} y1={vy(volMax * frac)} x2={W - PAD_R} y2={vy(volMax * frac)}
            stroke="#1a2530" strokeWidth="1" strokeDasharray="3,4"
          />
        ))}

        {/* ── RSI grid lines + labels */}
        {showRSI && [30, 50, 70].map(level => (
          <g key={level}>
            <line
              x1={PAD_L} y1={ry(level)} x2={W - PAD_R} y2={ry(level)}
              stroke={level === 50 ? '#1e2832' : level === 70 ? '#ff336630' : '#00ff8830'}
              strokeWidth="1" strokeDasharray="3,4"
            />
            <text x={W - PAD_R + 4} y={ry(level) + 3.5} fontSize="8" fill="#3a4a5a" fontFamily="monospace">
              {level}
            </text>
          </g>
        ))}

        {/* ── RSI overbought/sold fill */}
        {showRSI && (
          <>
            <rect x={PAD_L} y={rsiTop} width={chartW} height={ry(70) - rsiTop} fill="#ff336608" />
            <rect x={PAD_L} y={ry(30)} width={chartW} height={RSI_H - (ry(30) - rsiTop)} fill="#00ff8808" />
          </>
        )}

        {/* ── X-axis labels */}
        {xLabels.map(({ idx, label }) => (
          <text key={idx}
            x={cx(idx)} y={totalH - PAD_B + 12}
            fontSize="8" fill="#3a4a5a" textAnchor="middle" fontFamily="monospace"
          >
            {label}
          </text>
        ))}

        {/* ── Volume bars */}
        {showVol && D.map((d, i) => {
          const x = cx(i);
          const barH = Math.max(1, (volTop + VOL_H) - vy(d.volume));
          const isUp = d.close >= d.open;
          return (
            <rect
              key={i}
              x={x - candleW / 2} y={vy(d.volume)}
              width={candleW} height={barH}
              fill={isUp ? '#00ff8840' : '#ff336640'}
            />
          );
        })}

        {/* ── RSI line */}
        {showRSI && (
          <path d={rsiPath()} fill="none" stroke="#ff9500" strokeWidth="1.2" />
        )}

        {/* ── MA lines */}
        {showMA50 && <path d={maPath(ma50)} fill="none" stroke="#00d4ff" strokeWidth="1.2" opacity="0.85" />}
        {showMA20 && <path d={maPath(ma20)} fill="none" stroke="#ffcc00" strokeWidth="1.2" opacity="0.85" />}

        {/* ── Candlesticks */}
        {D.map((d, i) => {
          const x = cx(i);
          const isUp = d.close >= d.open;
          const bodyTop = py(Math.max(d.open, d.close));
          const bodyBot = py(Math.min(d.open, d.close));
          const bodyH = Math.max(1, bodyBot - bodyTop);
          const color = isUp ? '#00e676' : '#ff3366';
          const wickColor = isUp ? '#00c85380' : '#ff336680';
          return (
            <g key={i}>
              {/* Wick */}
              <line x1={x} y1={py(d.high)} x2={x} y2={py(d.low)} stroke={color} strokeWidth={Math.max(0.8, candleW * 0.15)} opacity="0.7" />
              {/* Body */}
              <rect
                x={x - candleW / 2} y={bodyTop}
                width={candleW} height={bodyH}
                fill={color}
                opacity={i === hoverIdx ? 1 : 0.85}
              />
            </g>
          );
        })}

        {/* ── Hover crosshair */}
        {hoverIdx != null && (
          <>
            <line
              x1={cx(hoverIdx)} y1={PAD_T}
              x2={cx(hoverIdx)} y2={totalH - PAD_B}
              stroke="#00d4ff" strokeWidth="0.8" strokeDasharray="3,3" opacity="0.5"
            />
            {/* Price level line */}
            {hBar && (
              <>
                <line
                  x1={PAD_L} y1={py(hBar.close)}
                  x2={W - PAD_R} y2={py(hBar.close)}
                  stroke="#00d4ff" strokeWidth="0.8" strokeDasharray="3,3" opacity="0.4"
                />
                {/* Price tag */}
                <rect x={W - PAD_R} y={py(hBar.close) - 7} width={PAD_R - 2} height={14} fill="#00d4ff" rx="2" />
                <text x={W - PAD_R + 3} y={py(hBar.close) + 4} fontSize="8" fill="#0a0f14" fontFamily="monospace" fontWeight="bold">
                  {formatPrice(hBar.close)}
                </text>
              </>
            )}
            {/* RSI value tag */}
            {showRSI && hRSI != null && (
              <>
                <line
                  x1={PAD_L} y1={ry(hRSI)}
                  x2={W - PAD_R} y2={ry(hRSI)}
                  stroke="#ff9500" strokeWidth="0.6" strokeDasharray="2,3" opacity="0.4"
                />
                <rect x={W - PAD_R} y={ry(hRSI) - 6} width={PAD_R - 2} height={12} fill="#ff9500" rx="2" />
                <text x={W - PAD_R + 3} y={ry(hRSI) + 4} fontSize="8" fill="#0a0f14" fontFamily="monospace" fontWeight="bold">
                  {hRSI.toFixed(1)}
                </text>
              </>
            )}
          </>
        )}

        {/* ── Panel separators */}
        {showVol && <line x1={PAD_L} y1={volTop} x2={W - PAD_R} y2={volTop} stroke="#1e2832" strokeWidth="1" />}
        {showRSI && <line x1={PAD_L} y1={rsiTop} x2={W - PAD_R} y2={rsiTop} stroke="#1e2832" strokeWidth="1" />}

        {/* ── Panel labels */}
        {showVol && <text x={PAD_L + 3} y={volTop + 12} fontSize="8" fill="#2a3a4a" fontFamily="monospace">VOL</text>}
        {showRSI && <text x={PAD_L + 3} y={rsiTop + 12} fontSize="8" fill="#2a3a4a" fontFamily="monospace">RSI(14)</text>}

        {/* ── MA legend */}
        <g>
          {showMA20 && (
            <g>
              <line x1={PAD_L + 4} y1={PAD_T + 10} x2={PAD_L + 18} y2={PAD_T + 10} stroke="#ffcc00" strokeWidth="1.5" />
              <text x={PAD_L + 22} y={PAD_T + 13.5} fontSize="8" fill="#ffcc00" fontFamily="monospace">MA20</text>
            </g>
          )}
          {showMA50 && (
            <g>
              <line x1={PAD_L + 60} y1={PAD_T + 10} x2={PAD_L + 74} y2={PAD_T + 10} stroke="#00d4ff" strokeWidth="1.5" />
              <text x={PAD_L + 78} y={PAD_T + 13.5} fontSize="8" fill="#00d4ff" fontFamily="monospace">MA50</text>
            </g>
          )}
        </g>
      </svg>
    </div>
  );
}
