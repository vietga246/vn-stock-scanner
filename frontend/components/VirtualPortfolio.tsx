'use client';

import { useState, useMemo, useCallback, useEffect } from 'react';
import { X, Plus, TrendingUp, TrendingDown, Trash2, RotateCcw, ChevronDown, ChevronUp, Settings, AlertTriangle, DollarSign } from 'lucide-react';
import type { Stock } from '@/lib/types';
import {
  VirtualTrade, VirtualPortfolio as PType, PositionSummary,
  loadPortfolio, savePortfolio, resetPortfolio, updateSettings,
  openTrade, closeTrade, deleteTrade,
  getPositions, getPortfolioStats, getBuyingPower, checkStopLossTakeProfit, calcTradePnL,
  fmtVND, fmtPrice, OrderType,
} from '@/lib/virtual-trading';

function SBadge({ s }: { s?: string }) {
  if (!s) return null;
  const c: Record<string, string> = { PANIC:'#00ff88', CRASH:'#00ff88', COMBO:'#00d4ff', OS:'#00ff88', BB:'#a78bfa', DIP:'#ffcc00', PULL:'#00d4ff', OTHER:'#8b99a8' };
  const cl = c[s] || '#8b99a8';
  return <span className="px-1.5 py-0.5 rounded text-[8px] font-bold" style={{ background:`${cl}15`, color:cl, border:`1px solid ${cl}30` }}>{s}</span>;
}

// ═══════════════════════════════════════════════════════════════════════════
// TRADE SCREEN
// ═══════════════════════════════════════════════════════════════════════════

export function TradeScreen({ stocks, priceMap, portfolio, onExecute, onClose, initialSymbol, initialAction }: {
  stocks: Stock[]; priceMap: Record<string, number>; portfolio: PType;
  onExecute: (p: Parameters<typeof openTrade>[1]) => string | undefined; onClose: () => void;
  initialSymbol?: string; initialAction?: 'BUY' | 'SELL';
}) {
  const [action, setAction] = useState<'BUY'|'SELL'>(initialAction || 'BUY');
  const [symbol, setSymbol] = useState(initialSymbol || '');
  const [search, setSearch] = useState('');
  const [showDrop, setShowDrop] = useState(false);
  const [orderType, setOrderType] = useState<OrderType>('MARKET');
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('100');
  const [sl, setSl] = useState('');
  const [tp, setTp] = useState('');
  const [useMargin, setUseMargin] = useState(false);
  const [strategy, setStrategy] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [showBP, setShowBP] = useState(false);

  const stock = useMemo(() => stocks.find(s => s.symbol === symbol), [stocks, symbol]);
  const bp = useMemo(() => getBuyingPower(portfolio, priceMap), [portfolio, priceMap]);

  useEffect(() => {
    if (stock) {
      const p = stock.close || stock.price || 0;
      setPrice(p.toString());
      const atr = stock.atr14 ?? 0;
      if (atr > 0) { setSl((p - atr * 2).toFixed(1)); setTp((p + atr * 3).toFixed(1)); }
    }
  }, [stock]);

  const filtered = useMemo(() => {
    if (!search) return [];
    const q = search.toLowerCase();
    return stocks.filter(s => s.symbol.toLowerCase().includes(q) || (s.name||'').toLowerCase().includes(q)).slice(0, 8);
  }, [search, stocks]);

  const pN = parseFloat(price) || 0;
  const qN = parseInt(quantity) || 0;
  const cost = pN * qN * 1000;
  const fees = cost * portfolio.fee_rate;
  const total = cost + fees;
  const shortfall = total - bp.cash_balance;
  const marginNeeded = useMargin && shortfall > 0 ? shortfall : 0;
  const canAfford = useMargin ? total <= bp.total_buying_power : total <= bp.cash_balance;
  const insufficient = qN > 0 && pN > 0 && !canAfford;
  const leverage = cost > 0 && marginNeeded > 0 ? cost / (cost - marginNeeded) : 1;
  const dailyInt = marginNeeded * portfolio.margin_interest_rate / 365;
  const isBuy = action === 'BUY';
  const ac = isBuy ? '#00ff88' : '#ff3366';

  const handleSubmit = () => {
    if (!symbol || !pN || !qN) return;
    setError('');
    const err = onExecute({ symbol, type: action, order_type: orderType, price: pN,
      limit_price: orderType !== 'MARKET' ? parseFloat(price) || undefined : undefined,
      quantity: qN, stop_loss: sl ? parseFloat(sl) : undefined, take_profit: tp ? parseFloat(tp) : undefined,
      use_margin: useMargin && marginNeeded > 0, strategy: strategy || undefined, note: note || undefined });
    if (err) setError(err); else onClose();
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-3">
      <div className="absolute inset-0" style={{ background: 'rgba(3,5,8,0.92)', backdropFilter: 'blur(8px)' }} onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-2xl overflow-hidden" style={{ background: '#0b1016', border: `1px solid ${ac}20`, boxShadow: `0 0 60px ${ac}08`, maxHeight: '92vh', overflowY: 'auto' }}>

        {/* Header */}
        <div className="p-4 flex justify-between items-start" style={{ borderBottom: `1px solid ${ac}12` }}>
          <div>
            <div className="text-[9px] tracking-widest mb-1" style={{ color: '#4a5a6a' }}>ĐẶT LỆNH ẢO</div>
            {symbol ? (<><div className="flex items-center gap-2"><span className="text-lg font-black">{symbol}</span><span className="text-[10px]" style={{ color: '#4a5a6a' }}>{stock?.name}</span></div><span className="text-xl font-black" style={{ color: ac }}>{fmtPrice(pN)}</span></>
            ) : <span className="text-sm" style={{ color: '#4a5a6a' }}>Chọn mã chứng khoán</span>}
          </div>
          <button onClick={onClose} className="p-2 rounded-lg" style={{ color: '#4a5a6a' }}><X size={18} /></button>
        </div>

        {/* BUY / SELL toggle */}
        <div className="grid grid-cols-2" style={{ borderBottom: '1px solid #1e2832' }}>
          {(['BUY','SELL'] as const).map(a => (
            <button key={a} onClick={() => setAction(a)} className="py-3 text-sm font-black tracking-wider" style={{ background: action===a ? (a==='BUY'?'#00ff8812':'#ff336612') : 'transparent', color: action===a ? (a==='BUY'?'#00ff88':'#ff3366') : '#4a5a6a', borderBottom: action===a ? `2px solid ${a==='BUY'?'#00ff88':'#ff3366'}` : '2px solid transparent' }}>
              {a==='BUY' ? '🟢 MUA' : '🔴 BÁN'}
            </button>
          ))}
        </div>

        <div className="p-4 space-y-3">
          {/* Buying Power */}
          <div className="rounded-lg overflow-hidden" style={{ border: '1px solid #1e2832' }}>
            <button onClick={() => setShowBP(!showBP)} className="w-full p-3 flex justify-between items-center text-left" style={{ background: '#0a0f14' }}>
              <div><div className="text-[8px] tracking-widest" style={{ color: '#4a5a6a' }}>SỨC MUA</div><div className="text-lg font-black" style={{ color: '#00d4ff' }}>{fmtVND(bp.total_buying_power)}</div></div>
              {showBP ? <ChevronUp size={14} color="#4a5a6a" /> : <ChevronDown size={14} color="#4a5a6a" />}
            </button>
            {showBP && (
              <div className="px-3 pb-3 grid grid-cols-2 gap-2" style={{ background: '#0a0f14' }}>
                {[{ l:'Tiền mặt', v:fmtVND(bp.cash_balance), c:'#e8edf2' }, { l:'Margin khả dụng', v:portfolio.margin_enabled?fmtVND(bp.margin_available):'Tắt', c:portfolio.margin_enabled?'#a78bfa':'#4a5a6a' }, { l:'Margin đang dùng', v:fmtVND(bp.margin_used), c:bp.margin_used>0?'#ff9500':'#4a5a6a' }, { l:'Đòn bẩy', v:bp.leverage.toFixed(2)+'x', c:bp.leverage>1.5?'#ff9500':'#8b99a8' }].map(x => (
                  <div key={x.l} className="p-2 rounded" style={{ background: '#0d1520' }}><div className="text-[8px]" style={{ color: '#4a5a6a' }}>{x.l}</div><div className="text-xs font-bold" style={{ color: x.c }}>{x.v}</div></div>
                ))}
              </div>
            )}
          </div>

          {/* Symbol */}
          <div className="relative">
            <div className="text-[9px] mb-1 tracking-wider" style={{ color: '#4a5a6a' }}>MÃ CK</div>
            <input value={symbol||search} onChange={e => { setSearch(e.target.value); setSymbol(''); setShowDrop(true); }} onFocus={() => setShowDrop(true)} placeholder="VCB, FPT, HPG..."
              className="w-full px-3 py-2.5 rounded-lg text-sm font-black" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#e8edf2', outline: 'none' }} />
            {showDrop && filtered.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 rounded-lg overflow-hidden z-10" style={{ background: '#0f1519', border: '1px solid #2a3642', maxHeight: 200, overflowY: 'auto' }}>
                {filtered.map(s => (<div key={s.symbol} onClick={() => { setSymbol(s.symbol); setSearch(''); setShowDrop(false); }} className="px-3 py-2 cursor-pointer flex justify-between hover:bg-[#1e2832]" style={{ borderBottom: '1px solid #1e283280' }}>
                  <div className="flex items-center gap-2"><span className="font-black text-xs">{s.symbol}</span><span className="text-[9px]" style={{ color: '#4a5a6a' }}>{s.name}</span></div>
                  <span className="text-xs font-bold">{fmtPrice(s.close||s.price||0)}</span></div>))}
              </div>
            )}
          </div>

          {/* Order config */}
          <div className="grid grid-cols-3 gap-2">
            <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>LOẠI LỆNH</div>
              <select value={orderType} onChange={e => setOrderType(e.target.value as OrderType)} className="w-full px-2 py-2.5 rounded-lg text-xs font-bold" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#8b99a8', outline: 'none' }}>
                <option value="MARKET">Market</option><option value="LIMIT">Limit</option><option value="STOP">Stop</option>
              </select></div>
            <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>GIÁ (nghìn)</div>
              <input value={price} onChange={e => setPrice(e.target.value)} type="number" step="0.1" disabled={orderType==='MARKET'} className="w-full px-2 py-2.5 rounded-lg text-xs font-black text-center" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#e8edf2', outline: 'none' }} /></div>
            <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>SỐ LƯỢNG</div>
              <input value={quantity} onChange={e => setQuantity(e.target.value)} type="number" step="100" className="w-full px-2 py-2.5 rounded-lg text-xs font-black text-center" style={{ background: '#0a0f14', border: `1px solid ${insufficient?'#ff3366':'#1e2832'}`, color: insufficient?'#ff3366':'#e8edf2', outline: 'none' }} /></div>
          </div>

          {/* SL / TP */}
          <div className="grid grid-cols-2 gap-2">
            <div><div className="text-[9px] mb-1" style={{ color: '#ff3366' }}>⛔ STOP LOSS</div>
              <input value={sl} onChange={e => setSl(e.target.value)} type="number" step="0.1" placeholder="–" className="w-full px-2 py-2 rounded-lg text-xs font-bold text-center" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#ff9500', outline: 'none' }} /></div>
            <div><div className="text-[9px] mb-1" style={{ color: '#00ff88' }}>🎯 TAKE PROFIT</div>
              <input value={tp} onChange={e => setTp(e.target.value)} type="number" step="0.1" placeholder="–" className="w-full px-2 py-2 rounded-lg text-xs font-bold text-center" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#00ff88', outline: 'none' }} /></div>
          </div>

          {/* Margin toggle */}
          {portfolio.margin_enabled && (
            <div className="flex items-center justify-between p-3 rounded-lg" style={{ background: useMargin?'#a78bfa08':'#0a0f14', border: `1px solid ${useMargin?'#a78bfa25':'#1e2832'}` }}>
              <div className="flex items-center gap-2"><DollarSign size={14} color={useMargin?'#a78bfa':'#4a5a6a'} /><div><div className="text-[10px] font-bold" style={{ color: useMargin?'#a78bfa':'#4a5a6a' }}>Dùng Margin</div>
                {useMargin && marginNeeded > 0 && <div className="text-[9px]" style={{ color: '#ff9500' }}>Vay: {fmtVND(marginNeeded)} · Lãi: {fmtVND(dailyInt)}/ngày · {leverage.toFixed(1)}x</div>}</div></div>
              <button onClick={() => setUseMargin(!useMargin)} className="w-10 h-5 rounded-full relative" style={{ background: useMargin?'#a78bfa':'#1e2832' }}>
                <div className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all" style={{ left: useMargin?'calc(100% - 18px)':'2px' }} /></button>
            </div>
          )}

          {/* Strategy + Note */}
          <div className="grid grid-cols-2 gap-2">
            <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>CHIẾN LƯỢC</div>
              <select value={strategy} onChange={e => setStrategy(e.target.value)} className="w-full px-2 py-2 rounded-lg text-[10px]" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#8b99a8', outline: 'none' }}>
                <option value="">—</option><option value="PANIC">PANIC</option><option value="CRASH">CRASH</option><option value="COMBO">COMBO</option><option value="OS">Oversold</option><option value="BB">BB Below</option><option value="DIP">DIP</option><option value="PULL">Pullback</option><option value="OTHER">Khác</option>
              </select></div>
            <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>GHI CHÚ</div>
              <input value={note} onChange={e => setNote(e.target.value)} placeholder="..." className="w-full px-2 py-2 rounded-lg text-[10px]" style={{ background: '#0a0f14', border: '1px solid #1e2832', color: '#8b99a8', outline: 'none' }} /></div>
          </div>

          {/* Order Summary */}
          <div className="rounded-lg overflow-hidden" style={{ border: `1px solid ${ac}18`, background: '#0a0f14' }}>
            <div className="px-3 py-2 text-[9px] tracking-widest font-bold" style={{ color: ac, borderBottom: `1px solid ${ac}10` }}>TỔNG QUAN LỆNH</div>
            <div className="px-3 py-2 space-y-1">
              {[{ l:'Giá trị', v:fmtVND(cost), c:'#e8edf2' }, { l:`Phí (${(portfolio.fee_rate*100).toFixed(2)}%)`, v:fmtVND(fees), c:'#ff9500' },
                ...(marginNeeded > 0 ? [{ l:'Tiền mặt', v:fmtVND(Math.min(total, bp.cash_balance)), c:'#e8edf2' }, { l:'Vay margin', v:fmtVND(marginNeeded), c:'#a78bfa' }] : []),
                { l:'Tổng chi', v:fmtVND(total), c:ac }
              ].map(x => (<div key={x.l} className="flex justify-between"><span className="text-[10px]" style={{ color: '#4a5a6a' }}>{x.l}</span><span className="text-[11px] font-bold" style={{ color: x.c }}>{x.v}</span></div>))}
            </div>
            {marginNeeded > 0 && pN > 0 && (
              <div className="px-3 py-2 flex items-center gap-2" style={{ borderTop: '1px solid #1e2832', background: '#ff950006' }}>
                <AlertTriangle size={12} color="#ff9500" /><span className="text-[9px]" style={{ color: '#ff9500' }}>Ký quỹ duy trì: 30%. Margin call nếu giá giảm đến {fmtPrice(pN * 0.7)}</span>
              </div>
            )}
          </div>

          {(error || insufficient) && (
            <div className="p-3 rounded-lg flex items-center gap-2" style={{ background: '#ff336612', border: '1px solid #ff336625' }}>
              <AlertTriangle size={14} color="#ff3366" /><span className="text-[10px] font-bold" style={{ color: '#ff3366' }}>{error || `Không đủ sức mua: ${fmtVND(total)} > ${fmtVND(useMargin?bp.total_buying_power:bp.cash_balance)}`}</span>
            </div>
          )}

          <button onClick={handleSubmit} disabled={!symbol||!pN||!qN||insufficient} className="w-full py-3.5 rounded-xl text-sm font-black tracking-wider" style={{ background: (!symbol||!pN||!qN||insufficient)?'#1e2832':`${ac}18`, color: (!symbol||!pN||!qN||insufficient)?'#4a5a6a':ac, border: `1px solid ${(!symbol||!pN||!qN||insufficient)?'#1e2832':`${ac}40`}`, cursor: (!symbol||!pN||!qN||insufficient)?'not-allowed':'pointer' }}>
            {isBuy ? '🟢 XÁC NHẬN MUA' : '🔴 XÁC NHẬN BÁN'} {symbol && `${symbol} × ${qN}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PORTFOLIO TAB
// ═══════════════════════════════════════════════════════════════════════════

export default function VirtualPortfolioTab({ stocks }: { stocks: Stock[] }) {
  const [portfolio, setPortfolio] = useState<PType>(() => loadPortfolio());
  const [showTrade, setShowTrade] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const priceMap = useMemo(() => { const m: Record<string,number> = {}; stocks.forEach(s => { m[s.symbol] = s.close||s.price||0; }); return m; }, [stocks]);

  useEffect(() => { const u = checkStopLossTakeProfit(portfolio, priceMap); if (JSON.stringify(u.trades)!==JSON.stringify(portfolio.trades)) setPortfolio(u); }, [priceMap]); // eslint-disable-line

  const positions = useMemo(() => getPositions(portfolio, priceMap), [portfolio, priceMap]);
  const stats = useMemo(() => getPortfolioStats(portfolio, priceMap), [portfolio, priceMap]);
  const closed = useMemo(() => portfolio.trades.filter(t => t.status!=='OPEN').sort((a,b) => (b.exit_date||b.entry_date).localeCompare(a.exit_date||a.entry_date)), [portfolio]);

  const handleExecute = useCallback((p: Parameters<typeof openTrade>[1]) => { const { portfolio: u, error: e } = openTrade(portfolio, p, priceMap); if (e) return e; setPortfolio(u); return undefined; }, [portfolio, priceMap]);
  const handleClose = useCallback((id: string) => { const t = portfolio.trades.find(x => x.id===id); if (!t) return; setPortfolio(closeTrade(portfolio, id, priceMap[t.symbol]??t.entry_price)); }, [portfolio, priceMap]);
  const handleDelete = useCallback((id: string) => { setPortfolio(deleteTrade(portfolio, id)); }, [portfolio]);

  const pc = (v: number) => v > 0 ? '#00ff88' : v < 0 ? '#ff3366' : '#8b99a8';

  return (
    <div className="p-3 space-y-3">
      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        {[{ l:'Tổng giá trị', v:fmtVND(stats.total_value), c:pc(stats.total_pnl) }, { l:'Lãi/Lỗ', v:`${stats.total_pnl>=0?'+':''}${fmtVND(stats.total_pnl)} (${stats.total_pnl_pct>=0?'+':''}${stats.total_pnl_pct.toFixed(2)}%)`, c:pc(stats.total_pnl) }, { l:'Sức mua', v:fmtVND(stats.buying_power), c:'#00d4ff' }, { l:'Win Rate', v:stats.closed_count>0?`${stats.win_rate.toFixed(0)}% (${stats.closed_count})`:'–', c:stats.win_rate>=50?'#00ff88':stats.closed_count>0?'#ff3366':'#4a5a6a' }, { l:'Phí', v:fmtVND(stats.total_fees), c:'#ff9500' }].map(x => (
          <div key={x.l} className="p-3 rounded-xl" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}><div className="text-[9px] mb-1 tracking-wider" style={{ color: '#4a5a6a' }}>{x.l}</div><div className="font-bold text-sm" style={{ color: x.c }}>{x.v}</div></div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => setShowTrade(true)} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[11px] font-bold" style={{ background: '#00ff8820', color: '#00ff88', border: '1px solid #00ff8850' }}><Plus size={14} /> Đặt lệnh</button>
        <button onClick={() => setShowHistory(!showHistory)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[11px] font-bold" style={{ background: '#0a0f14', color: '#8b99a8', border: '1px solid #1e2832' }}>{showHistory?<ChevronUp size={14} />:<ChevronDown size={14} />} Lịch sử ({closed.length})</button>
        <button onClick={() => setShowSettings(!showSettings)} className="p-2 rounded-lg" style={{ color: '#4a5a6a', border: '1px solid #1e2832' }}><Settings size={14} /></button>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[10px]" style={{ color: '#4a5a6a' }}>Vốn: {fmtVND(portfolio.initial_capital)} · {stats.open_count} vị thế{portfolio.margin_enabled && stats.margin_used>0 && <span style={{ color: '#a78bfa' }}> · M: {fmtVND(stats.margin_used)}</span>}</span>
          {confirmReset ? (<div className="flex gap-1"><button onClick={() => { setPortfolio(resetPortfolio()); setConfirmReset(false); }} className="px-2 py-1 rounded text-[9px] font-bold" style={{ background: '#ff336620', color: '#ff3366' }}>Reset</button><button onClick={() => setConfirmReset(false)} className="px-2 py-1 rounded text-[9px]" style={{ color: '#4a5a6a' }}>Hủy</button></div>
          ) : <button onClick={() => setConfirmReset(true)} className="p-1.5 rounded" style={{ color: '#4a5a6a' }}><RotateCcw size={14} /></button>}
        </div>
      </div>

      {/* Settings */}
      {showSettings && (
        <div className="rounded-xl p-3 grid grid-cols-2 lg:grid-cols-4 gap-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>Phí GD (%)</div><input type="number" step="0.01" value={(portfolio.fee_rate*100).toFixed(2)} onChange={e => setPortfolio(updateSettings(portfolio, { fee_rate: parseFloat(e.target.value)/100||0.0015 }))} className="w-full px-2 py-1.5 rounded text-xs font-bold" style={{ background: '#0d1520', border: '1px solid #1e2832', color: '#e8edf2', outline: 'none' }} /></div>
          <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>Margin</div><button onClick={() => setPortfolio(updateSettings(portfolio, { margin_enabled: !portfolio.margin_enabled }))} className="px-3 py-1.5 rounded text-xs font-bold" style={{ background: portfolio.margin_enabled?'#a78bfa20':'#0d1520', color: portfolio.margin_enabled?'#a78bfa':'#4a5a6a', border: `1px solid ${portfolio.margin_enabled?'#a78bfa40':'#1e2832'}` }}>{portfolio.margin_enabled?'BẬT':'TẮT'}</button></div>
          {portfolio.margin_enabled && (<><div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>Margin ratio (x)</div><input type="number" step="0.5" min="1" max="5" value={portfolio.margin_ratio} onChange={e => setPortfolio(updateSettings(portfolio, { margin_ratio: parseFloat(e.target.value)||2 }))} className="w-full px-2 py-1.5 rounded text-xs font-bold" style={{ background: '#0d1520', border: '1px solid #1e2832', color: '#e8edf2', outline: 'none' }} /></div>
            <div><div className="text-[9px] mb-1" style={{ color: '#4a5a6a' }}>Lãi (%/năm)</div><input type="number" step="1" value={(portfolio.margin_interest_rate*100).toFixed(0)} onChange={e => setPortfolio(updateSettings(portfolio, { margin_interest_rate: parseFloat(e.target.value)/100||0.12 }))} className="w-full px-2 py-1.5 rounded text-xs font-bold" style={{ background: '#0d1520', border: '1px solid #1e2832', color: '#e8edf2', outline: 'none' }} /></div></>)}
        </div>
      )}

      {/* Positions */}
      {positions.length > 0 ? (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-bold tracking-widest flex justify-between" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>
            <span>📊 VỊ THẾ MỞ ({positions.length})</span><span style={{ color: pc(positions.reduce((s,p)=>s+p.pnl,0)) }}>{fmtVND(positions.reduce((s,p)=>s+p.pnl,0))}</span>
          </div>
          <div className="overflow-x-auto"><table className="w-full text-[11px]"><thead><tr style={{ borderBottom: '1px solid #1e2832' }}>
            {['Mã','','Mua','Giá','SL','TP','KL','P&L','%','Ngày',''].map(h => <th key={h} className="p-2 text-right first:text-left" style={{ color: '#4a5a6a', fontSize: 10 }}>{h}</th>)}
          </tr></thead><tbody>
            {positions.map(p => (<tr key={p.trade.id} style={{ borderBottom: '1px solid #0d1520' }}>
              <td className="p-2 text-left"><div className="flex items-center gap-1"><span className="font-bold">{p.trade.symbol}</span><SBadge s={p.trade.strategy} /></div></td>
              <td className="p-2 text-right font-bold" style={{ color: p.trade.type==='BUY'?'#00ff88':'#ff3366' }}>{p.trade.type}</td>
              <td className="p-2 text-right" style={{ color: '#8b99a8' }}>{fmtPrice(p.trade.entry_price)}</td>
              <td className="p-2 text-right font-bold">{fmtPrice(p.current_price)}</td>
              <td className="p-2 text-right text-[10px]" style={{ color: p.hit_sl?'#ff3366':'#4a5a6a' }}>{p.trade.stop_loss?fmtPrice(p.trade.stop_loss):'–'}</td>
              <td className="p-2 text-right text-[10px]" style={{ color: p.hit_tp?'#00ff88':'#4a5a6a' }}>{p.trade.take_profit?fmtPrice(p.trade.take_profit):'–'}</td>
              <td className="p-2 text-right text-[10px]" style={{ color: '#8b99a8' }}>{p.trade.quantity.toLocaleString()}{p.trade.use_margin&&<span style={{ color:'#a78bfa',marginLeft:2 }}>M</span>}</td>
              <td className="p-2 text-right font-bold" style={{ color: pc(p.pnl) }}>{p.pnl>=0?'+':''}{fmtVND(p.pnl)}</td>
              <td className="p-2 text-right font-black" style={{ color: pc(p.pnl_pct) }}>{p.pnl_pct>=0?'+':''}{p.pnl_pct.toFixed(2)}%</td>
              <td className="p-2 text-right text-[10px]" style={{ color: '#4a5a6a' }}>{p.days_held}d</td>
              <td className="p-2 text-right"><button onClick={() => handleClose(p.trade.id)} className="px-2 py-1 rounded text-[9px] font-bold" style={{ background: '#ff950015', color: '#ff9500', border: '1px solid #ff950030' }}>Đóng</button></td>
            </tr>))}
          </tbody></table></div>
        </div>
      ) : (
        <div className="rounded-xl p-10 text-center" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-3xl mb-2">💰</div><p className="text-sm font-bold" style={{ color: '#4a5a6a' }}>Chưa có vị thế</p><p className="text-[11px] mt-1" style={{ color: '#2a3642' }}>Bấm "Đặt lệnh" để bắt đầu</p>
        </div>
      )}

      {/* History */}
      {showHistory && closed.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="px-3 py-2 text-[10px] font-bold tracking-widest" style={{ color: '#4a5a6a', borderBottom: '1px solid #1e2832' }}>📜 LỊCH SỬ ({closed.length})</div>
          <div className="overflow-x-auto" style={{ maxHeight: 280, overflowY: 'auto' }}><table className="w-full text-[11px]"><thead className="sticky top-0" style={{ background: '#0f1519' }}><tr style={{ borderBottom: '1px solid #1e2832' }}>
            {['Mã','','Mua','Bán','KL','P&L','%','Phí','TT','Ngày',''].map(h => <th key={h} className="p-2 text-right first:text-left" style={{ color: '#4a5a6a', fontSize: 10 }}>{h}</th>)}
          </tr></thead><tbody>
            {closed.map(t => { const { pnl, pnl_pct } = calcTradePnL(t, t.exit_price??t.entry_price); const sc: Record<string,string> = { CLOSED:'#00d4ff', STOPPED:'#ff3366', TP_HIT:'#00ff88' }; const sl: Record<string,string> = { CLOSED:'Đóng', STOPPED:'Cắt lỗ', TP_HIT:'Chốt lời' };
              return (<tr key={t.id} style={{ borderBottom: '1px solid #0d1520' }}>
                <td className="p-2 text-left"><div className="flex items-center gap-1"><span className="font-bold">{t.symbol}</span><SBadge s={t.strategy} /></div></td>
                <td className="p-2 text-right font-bold" style={{ color: t.type==='BUY'?'#00ff88':'#ff3366' }}>{t.type}</td>
                <td className="p-2 text-right" style={{ color: '#8b99a8' }}>{fmtPrice(t.entry_price)}</td>
                <td className="p-2 text-right">{t.exit_price?fmtPrice(t.exit_price):'–'}</td>
                <td className="p-2 text-right text-[10px]" style={{ color: '#8b99a8' }}>{t.quantity.toLocaleString()}</td>
                <td className="p-2 text-right font-bold" style={{ color: pc(pnl) }}>{pnl>=0?'+':''}{fmtVND(pnl)}</td>
                <td className="p-2 text-right font-black" style={{ color: pc(pnl_pct) }}>{pnl_pct>=0?'+':''}{pnl_pct.toFixed(2)}%</td>
                <td className="p-2 text-right text-[10px]" style={{ color: '#ff9500' }}>{fmtVND(t.fees)}</td>
                <td className="p-2 text-right"><span className="px-1.5 py-0.5 rounded text-[8px] font-bold" style={{ background:`${sc[t.status]||'#4a5a6a'}15`, color:sc[t.status]||'#4a5a6a' }}>{sl[t.status]||t.status}</span></td>
                <td className="p-2 text-right text-[10px]" style={{ color: '#4a5a6a' }}>{t.exit_date?new Date(t.exit_date).toLocaleDateString('vi-VN'):'–'}</td>
                <td className="p-2 text-right"><button onClick={() => handleDelete(t.id)} className="p-1 rounded" style={{ color: '#4a5a6a' }}><Trash2 size={12} /></button></td>
              </tr>); })}
          </tbody></table></div>
        </div>
      )}

      {/* Strategy Performance */}
      {portfolio.trades.filter(t => t.strategy && t.status!=='OPEN').length > 0 && (() => {
        const m: Record<string,{c:number;w:number;pnl:number}> = {};
        portfolio.trades.filter(t => t.strategy && t.status!=='OPEN').forEach(t => { const k=t.strategy!; if(!m[k]) m[k]={c:0,w:0,pnl:0}; const{pnl}=calcTradePnL(t,t.exit_price??t.entry_price); m[k].c++; if(pnl>0) m[k].w++; m[k].pnl+=pnl; });
        return (<div className="rounded-xl p-3" style={{ background: '#0a0f14', border: '1px solid #1e2832' }}>
          <div className="text-[10px] font-bold tracking-widest mb-2" style={{ color: '#4a5a6a' }}>🎯 HIỆU QUẢ CHIẾN LƯỢC</div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            {Object.entries(m).sort((a,b)=>b[1].pnl-a[1].pnl).map(([k,v])=>(<div key={k} className="p-2 rounded-lg" style={{ background: '#0d1520' }}>
              <div className="flex items-center gap-1.5 mb-1"><SBadge s={k} /><span className="text-[9px]" style={{ color: '#4a5a6a' }}>{v.c} lệnh</span></div>
              <div className="font-bold text-xs" style={{ color: pc(v.pnl) }}>{v.pnl>=0?'+':''}{fmtVND(v.pnl)}</div>
              <div className="text-[9px]" style={{ color: v.w/v.c>=0.5?'#00ff88':'#ff3366' }}>Win: {((v.w/v.c)*100).toFixed(0)}%</div>
            </div>))}
          </div>
        </div>);
      })()}

      {showTrade && <TradeScreen stocks={stocks} priceMap={priceMap} portfolio={portfolio} onExecute={handleExecute} onClose={() => setShowTrade(false)} />}
    </div>
  );
}
