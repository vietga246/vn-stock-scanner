'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';

// ─── Markdown renderer ────────────────────────────────────────────────────────
function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.split('\n');
  const nodes: React.ReactNode[] = [];
  let key = 0;

  for (const line of lines) {
    if (line.startsWith('# ')) {
      nodes.push(
        <h1 key={key++} style={{
          fontSize: '1.5rem', fontWeight: 800, color: '#e8edf2',
          borderBottom: '2px solid #00d4ff30', paddingBottom: '0.5rem',
          marginTop: '0.5rem', marginBottom: '1.2rem', letterSpacing: '-0.02em',
          fontFamily: "'JetBrains Mono', monospace",
        }}>{line.slice(2)}</h1>
      );
    } else if (line.startsWith('## ')) {
      nodes.push(
        <h2 key={key++} style={{
          fontSize: '1rem', fontWeight: 700, color: '#00d4ff',
          marginTop: '2rem', marginBottom: '0.6rem',
          paddingLeft: '0.75rem', borderLeft: '3px solid #00d4ff',
          letterSpacing: '0.04em', textTransform: 'uppercase' as const,
          fontFamily: "'JetBrains Mono', monospace",
        }}>{line.slice(3)}</h2>
      );
    } else if (line.startsWith('### ')) {
      nodes.push(
        <h3 key={key++} style={{
          fontSize: '0.8rem', fontWeight: 600, color: '#a78bfa',
          marginTop: '1.2rem', marginBottom: '0.4rem',
          letterSpacing: '0.06em', textTransform: 'uppercase' as const,
          fontFamily: "'JetBrains Mono', monospace",
        }}>{line.slice(4)}</h3>
      );
    } else if (line.startsWith('---')) {
      nodes.push(<hr key={key++} style={{ border: 'none', borderTop: '1px solid #1e2832', margin: '1.5rem 0' }} />);
    } else if (line.startsWith('*') && line.endsWith('*') && line.length > 2 && !line.startsWith('**')) {
      nodes.push(
        <p key={key++} style={{ fontSize: '0.72rem', color: '#4a5a6a', marginTop: '0.5rem', fontStyle: 'italic' }}>
          {line.slice(1, -1)}
        </p>
      );
    } else if (line.trim() === '') {
      nodes.push(<div key={key++} style={{ height: '0.4rem' }} />);
    } else {
      // Inline bold **text**
      const parts = line.split(/(\*\*[^*]+\*\*)/g);
      const rendered = parts.map((p, pi) =>
        p.startsWith('**') && p.endsWith('**')
          ? <strong key={pi} style={{ color: '#e8edf2', fontWeight: 700 }}>{p.slice(2, -2)}</strong>
          : p
      );
      nodes.push(
        <p key={key++} style={{ fontSize: '0.875rem', color: '#a8b8c8', lineHeight: '1.8', marginBottom: '0.2rem' }}>
          {rendered}
        </p>
      );
    }
  }
  return nodes;
}

// ─── Rec badge ────────────────────────────────────────────────────────────────
function RecBadge({ rec }: { rec: string }) {
  const cfg: Record<string, { color: string; bg: string }> = {
    STRONG_BUY:  { color: '#00ff88', bg: '#00ff8820' },
    BUY:         { color: '#00ff88', bg: '#00ff8812' },
    HOLD:        { color: '#ffcc00', bg: '#ffcc0015' },
    SELL:        { color: '#ff3366', bg: '#ff336615' },
    STRONG_SELL: { color: '#ff3366', bg: '#ff336622' },
  };
  const c = cfg[rec] ?? cfg.HOLD;
  return (
    <span style={{
      padding: '3px 10px', borderRadius: 5, fontWeight: 800, fontSize: '0.75rem',
      color: c.color, background: c.bg, border: `1px solid ${c.color}50`,
      letterSpacing: '0.08em', fontFamily: "'JetBrains Mono', monospace",
    }}>{rec.replace('_', ' ')}</span>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────
export default function ReportPage() {
  const params = useParams();
  const symbol = (params?.symbol as string ?? '').toUpperCase();

  const [report, setReport]     = useState('');
  const [meta, setMeta]         = useState({ name: '', industry: '', price: '', rec: '' });
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');

  useEffect(() => {
    if (!symbol) return;
    (async () => {
      try {
        // Đọc thẳng từ ai_analysis.json — output của workflow 6
        const res  = await fetch('/api/ai-analysis');
        const data = await res.json();
        const ai   = data?.analyses?.[symbol];

        if (!ai) {
          setError(`Chưa có báo cáo AI cho ${symbol}. Chạy workflow 6 để tạo.`);
          setLoading(false);
          return;
        }

        if (!ai.detailed_report) {
          setError(`${symbol} chưa có báo cáo chi tiết. Cần chạy lại workflow 6 với phiên bản mới nhất của ai_analyst.py.`);
          setLoading(false);
          return;
        }

        // Đọc thêm screener để lấy giá
        const screenerRes = await fetch('/api/screener');
        const screenerData = await screenerRes.json();
        const stock = screenerData?.screener?.find((s: Record<string, unknown>) => s.symbol === symbol);

        setMeta({
          name:     ai.name     ?? stock?.name     ?? '',
          industry: ai.industry ?? stock?.industry ?? '',
          price:    String(stock?.close ?? stock?.price ?? ''),
          rec:      ai.recommendation ?? '',
        });
        setReport(ai.detailed_report);
        setLoading(false);
      } catch (e) {
        setError(String(e));
        setLoading(false);
      }
    })();
  }, [symbol]);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Newsreader:ital,wght@0,400;0,600;1,400&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #05080a; color: #c8d4e0; font-family: 'Newsreader', Georgia, serif; }
        @keyframes pulse { 0%,100%{opacity:.4} 50%{opacity:1} }
        @keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:none} }
        .fade-in { animation: fadeIn 0.35s ease both; }
        @media print {
          .no-print { display:none!important; }
          body { background:white; color:black; }
          h1,h2,h3 { color:black!important; border-color:#ccc!important; }
          p { color:#333!important; }
        }
      `}</style>

      {/* Header */}
      <div className="no-print" style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'rgba(5,8,10,0.96)', backdropFilter: 'blur(12px)',
        borderBottom: '1px solid #1e2832', padding: '10px 24px',
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <button onClick={() => window.close()} style={{
          background: 'none', border: '1px solid #2a3642', color: '#8b99a8',
          borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: '0.75rem',
          fontFamily: "'JetBrains Mono', monospace",
        }}>← Đóng</button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, flexWrap: 'wrap' as const }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 800, fontSize: '1rem', color: '#e8edf2' }}>
            {symbol}
          </span>
          {meta.name && <span style={{ fontSize: '0.75rem', color: '#4a5a6a' }}>{meta.name}</span>}
          {meta.industry && (
            <span style={{ fontSize: '0.7rem', color: '#8b99a8', background: '#1e2832', padding: '2px 8px', borderRadius: 4 }}>
              {meta.industry}
            </span>
          )}
          {meta.price && (
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.85rem', color: '#00ff88' }}>
              {Number(meta.price).toFixed(1)}
            </span>
          )}
          {meta.rec && <RecBadge rec={meta.rec} />}
        </div>

        {!loading && !error && (
          <button onClick={() => window.print()} className="fade-in" style={{
            background: '#00d4ff12', border: '1px solid #00d4ff35', color: '#00d4ff',
            borderRadius: 6, padding: '4px 14px', cursor: 'pointer', fontSize: '0.75rem',
            fontFamily: "'JetBrains Mono', monospace", letterSpacing: '0.05em',
          }}>🖨 In</button>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ maxWidth: 860, margin: '80px auto', padding: '0 24px', textAlign: 'center' }}>
          <div style={{ animation: 'pulse 1.5s ease infinite' }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.75rem', color: '#00d4ff', letterSpacing: '0.15em', marginBottom: 12 }}>
              ● ĐANG TẢI BÁO CÁO
            </div>
            <div style={{ color: '#4a5a6a', fontSize: '0.8rem' }}>Đọc dữ liệu từ workflow 6...</div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ maxWidth: 860, margin: '60px auto', padding: '0 24px' }}>
          <div style={{ background: '#ff336610', border: '1px solid #ff336640', borderRadius: 10, padding: '20px 24px' }}>
            <div style={{ color: '#ff3366', fontWeight: 700, marginBottom: 8 }}>⚠ Không có báo cáo</div>
            <div style={{ color: '#c8d4e0', fontSize: '0.85rem', lineHeight: 1.6 }}>{error}</div>
          </div>
        </div>
      )}

      {/* Report */}
      {!loading && !error && report && (
        <main className="fade-in" style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px 80px' }}>
          {/* Meta header */}
          <div className="no-print" style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #1e2832',
          }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.65rem', color: '#2a3642', letterSpacing: '0.1em' }}>
              VN STOCK SCANNER — AI RESEARCH REPORT · WORKFLOW 6
            </div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.65rem', color: '#2a3642' }}>
              {new Date().toLocaleDateString('vi-VN')}
            </div>
          </div>

          {renderMarkdown(report)}

          <div style={{
            marginTop: 40, padding: '14px 20px', textAlign: 'center',
            background: '#0a0f14', border: '1px solid #1e2832', borderRadius: 10,
            fontFamily: "'JetBrains Mono', monospace", fontSize: '0.7rem', color: '#2a3642', lineHeight: 1.8,
          }}>
            ✓ BÁO CÁO ĐƯỢC TẠO BỞI WORKFLOW 6 · GPT-4o · Chỉ mang tính tham khảo
          </div>
        </main>
      )}
    </>
  );
}
