'use client';

import { useState, useRef, useId } from 'react';
import { formatPrice, formatNumber } from '@/lib/api';

interface SparklineProps {
  data: number[];
  volume?: number[];
  dates?: string[];
  width?: number;
  height?: number;
}

export default function SparklineModal({
  data,
  volume,
  dates,
  width = 90,
  height = 28
}: SparklineProps) {
  const reactId = useId();
  const [hover, setHover] = useState<{
    pt: { x: number; y: number; value: number; vol?: number; date?: string };
    idx: number;
    mouseX: number;
    mouseY: number;
  } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const pts = data.map((v, i) => ({
    x: (i / (data.length - 1)) * width,
    y: height - ((v - min) / range) * (height - 6) - 3,
    value: v,
    vol: volume?.[i],
    date: dates?.[i],
  }));

  const ptsStr = pts.map(p => p.x + ',' + p.y).join(' ');
  const isUp = data[data.length - 1] >= data[0];
  const color = isUp ? '#00ff88' : '#ff3366';
  const gradientId = `spark-${isUp ? 'up' : 'down'}-${reactId}`;

  const onMove = (e: React.MouseEvent) => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const idx = Math.max(0, Math.min(data.length - 1, Math.round((x / width) * (data.length - 1))));
    setHover({ 
      pt: pts[idx], 
      idx,
      mouseX: e.clientX,
      mouseY: e.clientY
    });
  };

  // Tooltip hiện bên trái chuột, căn giữa dọc
  // Nếu sát mép trái màn hình → hiện bên phải
  const getTooltipStyle = () => {
    if (!hover) return {};

    const tooltipWidth  = 100; // actual rendered width (minWidth 70, maxWidth 90 + border/shadow)
    const tooltipHeight = 95;
    const offset        = 14;

    const showRight = hover.mouseX - tooltipWidth - offset < 0;

    return {
      position: 'fixed' as const,
      left: showRight
        ? hover.mouseX + offset
        : hover.mouseX - tooltipWidth - offset,
      top: hover.mouseY - tooltipHeight / 2,
      zIndex: 99999,
    };
  };

  return (
    <div
      ref={ref}
      className="relative inline-flex items-center gap-2"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      <svg
        width={width}
        height={height}
        style={{
          cursor: 'crosshair',
          display: 'block',
          filter: `drop-shadow(0 0 2px ${color}60)`,
        }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon
          points={`0,${height} ${ptsStr} ${width},${height}`}
          fill={`url(#${gradientId})`}
        />
        <polyline
          points={ptsStr}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        {hover && (
          <>
            <line
              x1={hover.pt.x}
              y1={0}
              x2={hover.pt.x}
              y2={height}
              stroke="#00d4ff"
              strokeWidth="1"
              strokeDasharray="2,2"
              opacity="0.5"
            />
            <circle cx={hover.pt.x} cy={hover.pt.y} r={3} fill={color} />
            <circle cx={hover.pt.x} cy={hover.pt.y} r={1.5} fill="#fff" />
          </>
        )}
      </svg>

      {/* Tooltip - Above cursor with smart positioning */}
      {hover && (
        <div
          style={{
            ...getTooltipStyle(),
            background: 'linear-gradient(180deg, #141b22 0%, #0a0f14 100%)',
            border: '1px solid rgba(0, 212, 255, 0.5)',
            borderRadius: '8px',
            boxShadow: '0 0 20px rgba(0,212,255,0.3), 0 8px 24px rgba(0,0,0,0.6)',
            pointerEvents: 'none',
            overflow: 'hidden',
            minWidth: '70px',
            maxWidth: '90px',
          }}
        >
          {hover.pt.date && (
            <div
              style={{
                padding: '4px 10px',
                textAlign: 'center',
                background: 'rgba(0, 212, 255, 0.1)',
                borderBottom: '1px solid rgba(0, 212, 255, 0.2)',
              }}
            >
              <span style={{ fontSize: '10px', fontWeight: 600, color: '#00d4ff' }}>
                {hover.pt.date}
              </span>
            </div>
          )}
          <div style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ fontSize: '9px', color: '#4a5a6a', marginBottom: '2px' }}>
              Price
            </div>
            <div
              style={{
                fontFamily: 'monospace',
                fontWeight: 700,
                fontSize: '12px',
                color: '#e8edf2',
              }}
            >
              {formatPrice(hover.pt.value)}
            </div>
          </div>
          {hover.pt.vol !== undefined && (
            <div
              style={{
                padding: '6px 10px',
                textAlign: 'center',
                borderTop: '1px solid #1e2832',
              }}
            >
              <div style={{ fontSize: '9px', color: '#4a5a6a', marginBottom: '2px' }}>
                Vol
              </div>
              <div
                style={{
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  fontSize: '11px',
                  color: '#a855f7',
                }}
              >
                {formatNumber(hover.pt.vol)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
