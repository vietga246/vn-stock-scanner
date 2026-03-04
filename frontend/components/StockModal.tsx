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
import type { Stock, AIAnalysis } from '@/lib/types';
import { generateAnalysis, getRecommendationDisplay } from '@/lib/analysis';
import { formatPrice, formatPercent, getScoreColor, getTierColor } from '@/lib/api';
import Sparkline from './Sparkline';

interface StockModalProps {
  stock: Stock | null;
  sectorStatus?: 'accumulating' | 'distributing' | 'neutral';
  preloadedAnalysis?: AIAnalysis;
  onClose: () => void;
}

export default function StockModal({
  stock,
  sectorStatus,
  preloadedAnalysis,
  onClose,
}: StockModalProps) {
  const [visible, setVisible] = useState(false);
  const [activeTab, setActiveTab] = useState<'analysis' | 'scores' | 'chart'>('analysis');

  useEffect(() => {
    if (stock) {
      requestAnimationFrame(() => setVisible(true));
    }
  }, [stock]);

  if (!stock) return null;

  const close = () => {
    setVisible(false);
    setTimeout(onClose, 150);
  };

  // Use preloaded AI analysis or generate on-the-fly
  const analysis = preloadedAnalysis || generateAnalysis(stock, sectorStatus);
  const recDisplay = getRecommendationDisplay(analysis.recommendation);

  // Score circle component
  const ScoreCircle = ({
    value,
    label,
    Icon,
  }: {
    value: number;
    label: string;
    Icon: any;
  }) => {
    const r = 20,
      sw = 3,
      circ = 2 * Math.PI * r;
    const prog = ((value || 0) / 100) * circ;
    const color = getScoreColor(value);

    return (
      <div className="text-center">
        <div className="relative mx-auto" style={{ width: (r + sw) * 2, height: (r + sw) * 2 }}>
          <svg width={(r + sw) * 2} height={(r + sw) * 2} style={{ transform: 'rotate(-90deg)' }}>
            <circle cx={r + sw} cy={r + sw} r={r} fill="none" stroke="#1e2832" strokeWidth={sw} />
            <circle
              cx={r + sw}
              cy={r + sw}
              r={r}
              fill="none"
              stroke={color}
              strokeWidth={sw}
              strokeDasharray={circ}
              strokeDashoffset={circ - prog}
              strokeLinecap="round"
              style={{
                filter: `drop-shadow(0 0 4px ${color}50)`,
                transition: 'stroke-dashoffset 0.6s ease',
              }}
            />
          </svg>
          <div
            className="absolute inset-0 flex items-center justify-center font-mono font-bold text-[10px]"
            style={{ color, textShadow: `0 0 6px ${color}50` }}
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
  };

  // Highlight item component
  const HighlightItem = ({ item }: { item: { text: string; type: string } }) => {
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
        style={{ background: style.bg, border: `1px solid ${style.border}` }}
      >
        <IconComp size={12} color={style.text} className="mt-0.5 flex-shrink-0" />
        <span className="text-[11px]" style={{ color: style.text }}>
          {item.text}
        </span>
      </div>
    );
  };

  const tierColor = getTierColor(stock.tier);
  const price = stock.close || stock.price || 0;
  const change = stock.change_20d || stock.change_5d || 0;

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
        className="relative w-full max-w-md rounded-2xl overflow-hidden transition-all duration-200"
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
                    background: `${tierColor}20`,
                    color: tierColor,
                    border: `1px solid ${tierColor}40`,
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
                  style={{ color: change >= 0 ? '#00ff88' : '#ff3366' }}
                >
                  {formatPercent(change)}
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
                  background: `${recDisplay.color}20`,
                  color: recDisplay.color,
                  border: `1px solid ${recDisplay.color}50`,
                  boxShadow: `0 0 15px ${recDisplay.color}30`,
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
          {[
            { id: 'analysis' as const, label: 'Phân tích', icon: Target },
            { id: 'scores' as const, label: 'Điểm số', icon: Activity },
            { id: 'chart' as const, label: 'Biểu đồ', icon: BarChart3 },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
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
          {activeTab === 'analysis' && (
            <div>
              {/* Summary */}
              <div
                className="p-3 rounded-lg mb-3"
                style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Info size={12} color="#00d4ff" />
                  <span className="text-[10px] font-semibold" style={{ color: '#00d4ff' }}>
                    NHẬN ĐỊNH
                  </span>
                </div>
                <p className="text-[12px] leading-relaxed" style={{ color: '#e8edf2' }}>
                  {analysis.summary}
                </p>
              </div>

              {/* Highlights */}
              {analysis.highlights.length > 0 && (
                <div className="mb-3">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle size={12} color="#00ff88" />
                    <span className="text-[10px] font-semibold" style={{ color: '#00ff88' }}>
                      ĐIỂM TÍCH CỰC
                    </span>
                  </div>
                  {analysis.highlights.map((item, idx) => (
                    <HighlightItem key={idx} item={item} />
                  ))}
                </div>
              )}

              {/* Risks */}
              {analysis.risks.length > 0 && (
                <div className="mb-3">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle size={12} color="#ff3366" />
                    <span className="text-[10px] font-semibold" style={{ color: '#ff3366' }}>
                      RỦI RO CẦN LƯU Ý
                    </span>
                  </div>
                  {analysis.risks.map((item, idx) => (
                    <HighlightItem key={idx} item={item} />
                  ))}
                </div>
              )}

              {/* Detailed Analysis */}
              <div className="space-y-2">
                <div
                  className="p-2.5 rounded-lg"
                  style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <Shield size={11} color="#a855f7" />
                    <span className="text-[10px] font-semibold" style={{ color: '#a855f7' }}>
                      CƠ BẢN
                    </span>
                  </div>
                  <p className="text-[11px]" style={{ color: '#8b99a8' }}>
                    {analysis.fundamental_view}
                  </p>
                </div>

                <div
                  className="p-2.5 rounded-lg"
                  style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <Globe size={11} color="#00d4ff" />
                    <span className="text-[10px] font-semibold" style={{ color: '#00d4ff' }}>
                      DÒNG TIỀN
                    </span>
                  </div>
                  <p className="text-[11px]" style={{ color: '#8b99a8' }}>
                    {analysis.flow_view}
                  </p>
                </div>

                <div
                  className="p-2.5 rounded-lg"
                  style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <Activity size={11} color="#ffcc00" />
                    <span className="text-[10px] font-semibold" style={{ color: '#ffcc00' }}>
                      KỸ THUẬT
                    </span>
                  </div>
                  <p className="text-[11px]" style={{ color: '#8b99a8' }}>
                    {analysis.technical_view}
                  </p>
                </div>
              </div>
            </div>
          )}

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
              <div
                className="p-3 rounded-lg mb-3"
                style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
              >
                <div className="text-[10px] mb-3" style={{ color: '#4a5a6a', letterSpacing: '0.5px' }}>
                  BIẾN ĐỘNG GIÁ 30 NGÀY
                </div>
                {stock.price_history ? (
                  <Sparkline
                    data={stock.price_history}
                    volume={stock.volume_history}
                    dates={stock.dates}
                    width={320}
                    height={80}
                  />
                ) : (
                  <div className="text-center py-8 text-[11px]" style={{ color: '#4a5a6a' }}>
                    Không có dữ liệu lịch sử giá
                  </div>
                )}
              </div>

              {/* Price Stats */}
              <div className="grid grid-cols-3 gap-2 mb-3">
                {[
                  { label: '1D', value: stock.change_1d },
                  { label: '5D', value: stock.change_5d },
                  { label: '20D', value: stock.change_20d },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="p-2.5 rounded-lg text-center"
                    style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
                  >
                    <div className="text-[10px] mb-1" style={{ color: '#4a5a6a' }}>
                      {item.label}
                    </div>
                    <div
                      className="font-mono font-semibold text-sm"
                      style={{ color: (item.value || 0) >= 0 ? '#00ff88' : '#ff3366' }}
                    >
                      {formatPercent(item.value)}
                    </div>
                  </div>
                ))}
              </div>

              {/* Foreign Flow */}
              <div
                className="p-3 rounded-lg"
                style={{ background: '#0a0f14', border: '1px solid #1e2832' }}
              >
                <div className="text-[10px] mb-2" style={{ color: '#4a5a6a', letterSpacing: '0.5px' }}>
                  DÒNG TIỀN KHỐI NGOẠI 7D
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {(stock.foreign_net_7d || 0) >= 0 ? (
                      <TrendingUp size={16} color="#00ff88" />
                    ) : (
                      <TrendingDown size={16} color="#ff3366" />
                    )}
                    <span
                      className="font-mono font-bold text-lg"
                      style={{ color: (stock.foreign_net_7d || 0) >= 0 ? '#00ff88' : '#ff3366' }}
                    >
                      {(stock.foreign_net_7d || 0) >= 0 ? '+' : ''}
                      {(stock.foreign_net_7d || 0).toFixed(1)}B
                    </span>
                  </div>
                  <span
                    className="text-[11px]"
                    style={{ color: (stock.foreign_net_7d || 0) >= 0 ? '#00ff88' : '#ff3366' }}
                  >
                    {(stock.foreign_net_7d || 0) >= 0 ? 'Mua ròng' : 'Bán ròng'}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

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
