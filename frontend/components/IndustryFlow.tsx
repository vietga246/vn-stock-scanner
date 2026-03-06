'use client';

import { useState } from 'react';
import { TrendingUp, TrendingDown, Zap, ChevronUp, ChevronDown } from 'lucide-react';
import type { Sector } from '@/lib/types';

interface IndustryFlowProps {
  sectors: Sector[];
  onIndustryClick?: (industry: string) => void;
  activeIndustry?: string | null;
}

export default function IndustryFlow({
  sectors,
  onIndustryClick,
  activeIndustry
}: IndustryFlowProps) {
  const [expanded, setExpanded] = useState(true);

  const maxFlow = Math.max(...sectors.map(s => Math.abs(s.foreign_net_7d || 0)), 1);

  const accumulating = sectors.filter(s => s.status === 'accumulating');
  const distributing = sectors.filter(s => s.status === 'distributing');

  const FlowBar = ({ value }: { value: number }) => {
    const pct = Math.min((Math.abs(value) / maxFlow) * 100, 100);
    const isUp = value >= 0;
    const color = isUp ? '#00ff88' : '#ff3366';

    return (
      <div className="flex items-center gap-2 flex-1">
        <div
          className="flex-1 h-1.5 rounded-full overflow-hidden relative"
          style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
        >
          <div
            className="absolute left-1/2 top-0 bottom-0 w-px"
            style={{ background: '#2a3642' }}
          />
          <div
            className="absolute top-0 bottom-0 rounded-full transition-all duration-500"
            style={{
              [isUp ? 'left' : 'right']: '50%',
              width: `${pct / 2}%`,
              background: `linear-gradient(${isUp ? '90deg' : '270deg'}, ${color}80, ${color})`,
              boxShadow: `0 0 6px ${color}60`,
            }}
          />
        </div>
        <span
          className="text-xs font-mono font-semibold min-w-[50px] text-right"
          style={{
            color,
            textShadow: `0 0 8px ${color}40`,
          }}
        >
          {isUp ? '+' : ''}
          {Math.abs(value) >= 1000 ? (value / 1000).toFixed(1) + 'K' : value.toFixed(1)}B
        </span>
      </div>
    );
  };

  const SectorItem = ({ sector }: { sector: Sector }) => {
    const isActive = activeIndustry === sector.name;
    const isAccumulating = sector.status === 'accumulating';

    return (
      <div
        onClick={() => onIndustryClick?.(sector.name)}
        className="sector-item flex items-center gap-2 p-2 rounded-md mb-1.5 cursor-pointer transition-all"
        data-status={isAccumulating ? 'accumulating' : 'distributing'}
        data-active={isActive ? '' : undefined}
      >
        <span className="text-[11px] font-medium min-w-[80px] truncate">
          {sector.name}
        </span>
        <FlowBar value={sector.foreign_net_7d} />
      </div>
    );
  };

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        background: 'linear-gradient(180deg, #0f1519 0%, #0a0f14 100%)',
        border: '1px solid #1e2832',
      }}
    >
      {/* Header */}
      <div
        className="p-3 flex items-center justify-between cursor-pointer"
        style={{
          borderBottom: expanded ? '1px solid #1e2832' : 'none',
          background: 'linear-gradient(90deg, rgba(0,212,255,0.05) 0%, transparent 100%)',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-7 h-7 rounded-md flex items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, #00d4ff20 0%, #a855f720 100%)',
              border: '1px solid #00d4ff40',
            }}
          >
            <Zap size={14} color="#00d4ff" />
          </div>
          <div>
            <div className="font-semibold text-xs tracking-wide">INDUSTRY FLOW</div>
            <div className="text-[10px]" style={{ color: '#4a5a6a' }}>
              7D Foreign Net
            </div>
          </div>
        </div>
        {expanded ? (
          <ChevronUp size={14} color="#4a5a6a" />
        ) : (
          <ChevronDown size={14} color="#4a5a6a" />
        )}
      </div>

      {/* Content */}
      {expanded && (
        <div className="p-3">
          {/* Accumulating */}
          {accumulating.length > 0 && (
            <div className="mb-3">
              <div
                className="flex items-center gap-2 mb-2 pb-1.5"
                style={{ borderBottom: '1px solid #1e2832' }}
              >
                <TrendingUp
                  size={12}
                  color="#00ff88"
                  style={{ filter: 'drop-shadow(0 0 3px rgba(0,255,136,0.5))' }}
                />
                <span
                  className="text-[10px] font-semibold tracking-wider"
                  style={{
                    color: '#00ff88',
                    textShadow: '0 0 8px rgba(0,255,136,0.3)',
                  }}
                >
                  ACCUMULATING
                </span>
              </div>
              {accumulating.map((sector) => (
                <SectorItem key={sector.name} sector={sector} />
              ))}
            </div>
          )}

          {/* Distributing */}
          {distributing.length > 0 && (
            <div>
              <div
                className="flex items-center gap-2 mb-2 pb-1.5"
                style={{ borderBottom: '1px solid #1e2832' }}
              >
                <TrendingDown
                  size={12}
                  color="#ff3366"
                  style={{ filter: 'drop-shadow(0 0 3px rgba(255,51,102,0.5))' }}
                />
                <span
                  className="text-[10px] font-semibold tracking-wider"
                  style={{
                    color: '#ff3366',
                    textShadow: '0 0 8px rgba(255,51,102,0.3)',
                  }}
                >
                  DISTRIBUTING
                </span>
              </div>
              {distributing.map((sector) => (
                <SectorItem key={sector.name} sector={sector} />
              ))}
            </div>
          )}

          {sectors.length === 0 && (
            <div className="text-center py-4 text-[11px]" style={{ color: '#4a5a6a' }}>
              Đang tải dữ liệu ngành...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
