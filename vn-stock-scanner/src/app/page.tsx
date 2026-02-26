'use client'

import { useState, useCallback, useEffect } from 'react'
import { StockData, MarketOverview } from '@/types/stock'

interface ScanSummary {
  total: number; fetched: number; passed: number
  buy: number; watch: number; avoid: number; elapsedMs: number
}
type SignalFilter = 'all' | 'buy' | 'watch' | 'avoid'

function IndexCard({ label, data }: { label: string; data?: { value: number; change: number; percentChange: number } }) {
  const isUp = (data?.change ?? 0) >= 0
  const hasData = data && data.value > 0
  return (
    <div className="market-card">
      <div className="card-label">{label}</div>
      <div className="card-value mono">{hasData ? data.value.toLocaleString('vi-VN', { maximumFractionDigits: 2 }) : '—'}</div>
      {hasData && (
        <div className={`card-change mono ${isUp ? 'text-up' : 'text-down'}`}>
          {isUp ? '+' : ''}{data.change.toFixed(2)} ({isUp ? '+' : ''}{data.percentChange.toFixed(2)}%)
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="market-card">
      <div className="card-label">{label}</div>
      <div className={`card-value mono ${color ?? ''}`}>{value}</div>
      {sub && <div className="card-change">{sub}</div>}
    </div>
  )
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 65 ? 'var(--up)' : score < 35 ? 'var(--down)' : 'var(--accent3)'
  const textColor = score >= 65 ? 'text-up' : score < 35 ? 'text-down' : 'text-blue'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
      <div style={{ flex: 1, height: '4px', background: 'var(--border)', borderRadius: '2px', overflow: 'hidden', maxWidth: '80px' }}>
        <div style={{ height: '100%', width: `${score}%`, background: color, borderRadius: '2px', transition: 'width 0.5s ease' }} />
      </div>
      <span className={`mono ${textColor}`} style={{ fontSize: '13px', minWidth: '26px', textAlign: 'right' }}>{score}</span>
    </div>
  )
}

function SignalBadge({ signal }: { signal: 'buy' | 'watch' | 'avoid' }) {
  const map = { buy: { label: '▲ MUA', cls: 'signal-buy' }, watch: { label: '○ THEO DÕI', cls: 'signal-watch' }, avoid: { label: '▼ TRÁNH', cls: 'signal-avoid' } }
  const { label, cls } = map[signal]
  return <span className={`signal ${cls}`}>{label}</span>
}

export default function DashboardPage() {
  const [stocks, setStocks] = useState<StockData[]>([])
  const [market, setMarket] = useState<MarketOverview | null>(null)
  const [summary, setSummary] = useState<ScanSummary | null>(null)
  const [filter, setFilter] = useState<SignalFilter>('all')
  const [loading, setLoading] = useState(false)
  const [loadingStep, setLoadingStep] = useState('')
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [dataSource, setDataSource] = useState<string>('')

  const startScan = useCallback(async () => {
    if (loading) return
    setLoading(true)
    setLoadingStep('Kết nối server...')

    try {
      setLoadingStep('Lấy tổng quan thị trường...')
      const marketRes = await fetch('/api/market')
      if (marketRes.ok) {
        const mj = await marketRes.json()
        if (mj.success) setMarket(mj.data)
      }

      setLoadingStep('Đang quét cổ phiếu... (10-15 giây)')
      const stocksRes = await fetch('/api/stocks')
      const sj = await stocksRes.json()

      const stocks: StockData[] = sj.data?.stocks ?? []
      const summary: ScanSummary = sj.data?.summary ?? {}

      setStocks(stocks)
      setSummary(summary)
      setLastUpdated(new Date().toLocaleString('vi-VN'))

      // Xác định nguồn data
      if (stocks.length > 0) {
        const hasRealPrice = stocks.some(s => s.price > 10000)
        const isRealTime = stocks.some(s => s.volume > 0 && s.percentChange !== 0)
        if (isRealTime) setDataSource('📡 Dữ liệu thật')
        else if (hasRealPrice) setDataSource('📋 Dữ liệu demo')
        else setDataSource('⚠️ Thị trường đóng cửa')
      }

    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [loading])

  // Tự động quét khi mở trang
  useEffect(() => {
    startScan()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const displayed = filter === 'all' ? stocks : stocks.filter(s => s.signal === filter)

  return (
    <>
      <style>{`
        .market-card { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:20px; transition:border-color 0.2s; }
        .market-card:hover { border-color:var(--accent); }
        .card-label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; font-family:var(--font-mono); margin-bottom:8px; }
        .card-value { font-size:26px; font-weight:600; letter-spacing:-1px; }
        .card-change { font-size:12px; color:var(--muted); margin-top:4px; }
        .text-up { color:var(--up) !important; }
        .text-down { color:var(--down) !important; }
        .text-blue { color:var(--accent3) !important; }
        .signal { display:inline-block; padding:3px 10px; border-radius:4px; font-size:11px; font-family:var(--font-mono); font-weight:700; letter-spacing:0.5px; }
        .signal-buy { background:rgba(0,229,160,0.1); color:var(--up); border:1px solid rgba(0,229,160,0.2); }
        .signal-watch { background:rgba(77,166,255,0.1); color:var(--accent3); border:1px solid rgba(77,166,255,0.2); }
        .signal-avoid { background:rgba(255,77,109,0.1); color:var(--down); border:1px solid rgba(255,77,109,0.2); }
        .tab { background:var(--surface); border:1px solid var(--border); color:var(--muted); padding:7px 16px; border-radius:6px; font-size:13px; cursor:pointer; font-family:var(--font-mono); transition:all 0.15s; }
        .tab.active,.tab:hover { border-color:var(--accent); color:var(--accent); background:rgba(0,229,160,0.05); }
        .scan-btn { background:var(--accent); color:#0a0c0f; border:none; padding:14px 32px; font-family:var(--font-mono); font-size:13px; font-weight:700; border-radius:6px; cursor:pointer; transition:all 0.2s; white-space:nowrap; }
        .scan-btn:hover:not(:disabled) { background:#00fdb5; transform:translateY(-1px); }
        .scan-btn:disabled { background:var(--border); color:var(--muted); cursor:not-allowed; }
        .spinner { width:40px; height:40px; border:2px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin 0.8s linear infinite; }
        tbody tr { animation:fadeSlideIn 0.3s ease both; }
        tbody tr:hover td { background:rgba(255,255,255,0.02); }
        .source-badge { display:inline-block; padding:3px 10px; border-radius:100px; font-size:11px; font-family:var(--font-mono); background:rgba(0,229,160,0.08); border:1px solid rgba(0,229,160,0.2); color:var(--accent); margin-left:12px; }
      `}</style>

      {/* Loading overlay */}
      {loading && (
        <div style={{ position:'fixed', inset:0, background:'rgba(10,12,15,0.85)', backdropFilter:'blur(6px)', zIndex:200, display:'flex', alignItems:'center', justifyContent:'center', flexDirection:'column', gap:'20px' }}>
          <div className="spinner" />
          <div className="mono" style={{ fontSize:'13px', color:'var(--muted)' }}>ĐANG QUÉT THỊ TRƯỜNG</div>
          <div className="mono" style={{ fontSize:'12px', color:'var(--accent)', textAlign:'center' }}>{loadingStep}</div>
        </div>
      )}

      {/* Header */}
      <header style={{ borderBottom:'1px solid var(--border)', padding:'20px 0', position:'sticky', top:0, background:'rgba(10,12,15,0.9)', backdropFilter:'blur(12px)', zIndex:100 }}>
        <div style={{ maxWidth:'1200px', margin:'0 auto', padding:'0 24px', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <div className="mono" style={{ fontSize:'18px', fontWeight:700, color:'var(--accent)' }}>
            VN<span style={{ color:'var(--muted)' }}>/</span>SCAN
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:'8px', fontSize:'12px', color:'var(--muted)', fontFamily:'var(--font-mono)', background:'var(--surface)', border:'1px solid var(--border)', padding:'6px 14px', borderRadius:'100px' }}>
            <div style={{ width:'6px', height:'6px', borderRadius:'50%', background: loading ? 'var(--accent2)' : lastUpdated ? 'var(--accent)' : 'var(--muted)', animation: loading || lastUpdated ? 'pulse 2s infinite' : 'none' }} />
            {loading ? 'ĐANG QUÉT...' : lastUpdated ? `CẬP NHẬT ${lastUpdated}` : 'CHƯA QUÉT'}
          </div>
        </div>
      </header>

      <main style={{ maxWidth:'1200px', margin:'0 auto', padding:'0 24px', position:'relative', zIndex:1 }}>

        {/* Hero */}
        <section style={{ padding:'48px 0 32px', display:'grid', gridTemplateColumns:'1fr auto', alignItems:'end', gap:'32px', borderBottom:'1px solid var(--border)', marginBottom:'32px' }}>
          <div>
            <h1 style={{ fontSize:'clamp(28px,4vw,48px)', fontWeight:600, letterSpacing:'-1.5px', lineHeight:1.1 }}>
              Quét <em style={{ fontStyle:'normal', color:'var(--accent)', fontFamily:'var(--font-mono)' }}>toàn bộ</em><br/>VN-Index tự động
            </h1>
            <p style={{ marginTop:'12px', color:'var(--muted)', fontSize:'15px', maxWidth:'480px', lineHeight:1.6 }}>
              Lọc cổ phiếu theo thanh khoản, biến động, và điểm số kỹ thuật.
              {dataSource && <span className="source-badge">{dataSource}</span>}
            </p>
          </div>
          <button className="scan-btn" disabled={loading} onClick={startScan}>
            {loading ? '⏳ ĐANG QUÉT...' : '↺ QUÉT LẠI'}
          </button>
        </section>

        {/* Market cards */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:'12px', marginBottom:'32px' }}>
          <IndexCard label="VN-Index" data={market?.vnindex} />
          <IndexCard label="VN30" data={market?.vn30} />
          <IndexCard label="HNX" data={market?.hnx} />
          {summary && <>
            <StatCard label="Mã qua lọc" value={summary.passed} sub={`/ ${summary.total} mã quét`} />
            <StatCard label="Tín hiệu MUA" value={summary.buy} color="text-up" sub="cổ phiếu" />
            <StatCard label="Thời gian" value={`${(summary.elapsedMs / 1000).toFixed(1)}s`} sub="quét xong" />
          </>}
        </div>

        {/* Table */}
        {stocks.length > 0 && (
          <>
            <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'16px' }}>
              <div className="mono" style={{ fontSize:'12px', color:'var(--muted)', textTransform:'uppercase', letterSpacing:'1px' }}>Cổ phiếu đáng chú ý</div>
              <div style={{ background:'rgba(0,229,160,0.1)', border:'1px solid rgba(0,229,160,0.3)', color:'var(--accent)', fontFamily:'var(--font-mono)', fontSize:'11px', padding:'3px 10px', borderRadius:'100px' }}>{displayed.length} mã</div>
            </div>

            <div style={{ display:'flex', gap:'8px', marginBottom:'20px', flexWrap:'wrap' }}>
              {(['all','buy','watch','avoid'] as const).map(f => (
                <button key={f} className={`tab ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
                  {f === 'all' ? 'Tất cả' : f === 'buy' ? '⬆ Mua' : f === 'watch' ? '👁 Theo dõi' : '⬇ Tránh'}
                </button>
              ))}
            </div>

            <div style={{ background:'var(--surface)', border:'1px solid var(--border)', borderRadius:'12px', overflow:'hidden', marginBottom:'40px' }}>
              <table style={{ width:'100%', borderCollapse:'collapse' }}>
                <thead>
                  <tr style={{ borderBottom:'1px solid var(--border)', background:'rgba(0,0,0,0.2)' }}>
                    {['Mã / Công ty','Giá (VNĐ)','% Thay đổi','KL (triệu)','Biến động','Điểm','Tín hiệu'].map((h, i) => (
                      <th key={h} style={{ textAlign: i < 2 ? 'left' : 'right', padding:'12px 16px', fontSize:'11px', color:'var(--muted)', textTransform:'uppercase', letterSpacing:'1px', fontFamily:'var(--font-mono)', fontWeight:400, ...(i >= 5 ? { textAlign:'left' } : {}) }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {displayed.map((s, i) => (
                    <tr key={s.ticker} style={{ borderBottom:'1px solid var(--border)', animationDelay:`${i * 25}ms`, cursor:'pointer' }}>
                      <td style={{ padding:'14px 16px' }}>
                        <div className="mono" style={{ fontWeight:700, fontSize:'15px' }}>{s.ticker}</div>
                        <div style={{ fontSize:'12px', color:'var(--muted)', marginTop:'2px' }}>{s.companyName !== s.ticker ? s.companyName : ''}</div>
                      </td>
                      <td style={{ padding:'14px 16px', fontFamily:'var(--font-mono)', fontSize:'14px' }}>
                        {s.price > 0 ? s.price.toLocaleString('vi-VN') : '—'}
                      </td>
                      <td style={{ padding:'14px 16px', textAlign:'right' }}>
                        <span className={`mono ${s.percentChange >= 0 ? 'text-up' : 'text-down'}`} style={{ fontSize:'13px' }}>
                          {s.percentChange >= 0 ? '+' : ''}{s.percentChange.toFixed(2)}%
                        </span>
                      </td>
                      <td style={{ padding:'14px 16px', textAlign:'right', fontFamily:'var(--font-mono)', fontSize:'13px', color:'var(--muted)' }}>
                        {(s.volume / 1_000_000).toFixed(1)}
                      </td>
                      <td style={{ padding:'14px 16px', textAlign:'right', fontFamily:'var(--font-mono)', fontSize:'13px', color:'var(--muted)' }}>
                        {s.volatility}%
                      </td>
                      <td style={{ padding:'14px 16px' }}><ScoreBar score={s.score} /></td>
                      <td style={{ padding:'14px 16px' }}><SignalBadge signal={s.signal} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* Loading skeleton khi chưa có data */}
        {stocks.length === 0 && loading && (
          <div style={{ padding:'60px 24px', textAlign:'center', color:'var(--muted)' }}>
            <div className="spinner" style={{ margin:'0 auto 20px' }} />
            <p className="mono" style={{ fontSize:'13px' }}>Đang tải dữ liệu...</p>
          </div>
        )}
      </main>

      <footer style={{ borderTop:'1px solid var(--border)', padding:'24px', maxWidth:'1200px', margin:'0 auto', display:'flex', justifyContent:'space-between' }}>
        <p className="mono" style={{ fontSize:'11px', color:'var(--muted)' }}>VN/SCAN · Không phải tư vấn tài chính</p>
        <p className="mono" style={{ fontSize:'11px', color:'var(--muted)' }}>Data: VNDirect + SSI</p>
      </footer>
    </>
  )
}
