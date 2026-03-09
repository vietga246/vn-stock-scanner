'use client';

import { useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation';

// ─── Markdown-like renderer ───────────────────────────────────────────────────
function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.split('\n');
  const nodes: React.ReactNode[] = [];
  let key = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('# ')) {
      nodes.push(
        <h1 key={key++} style={{
          fontSize: '1.6rem', fontWeight: 800, color: '#e8edf2',
          borderBottom: '2px solid #00d4ff30', paddingBottom: '0.5rem',
          marginTop: '0.5rem', marginBottom: '1.2rem',
          letterSpacing: '-0.02em', fontFamily: "'JetBrains Mono', monospace",
        }}>{line.slice(2)}</h1>
      );
    } else if (line.startsWith('## ')) {
      nodes.push(
        <h2 key={key++} style={{
          fontSize: '1.05rem', fontWeight: 700, color: '#00d4ff',
          marginTop: '2rem', marginBottom: '0.6rem',
          paddingLeft: '0.75rem',
          borderLeft: '3px solid #00d4ff',
          letterSpacing: '0.04em', textTransform: 'uppercase',
          fontFamily: "'JetBrains Mono', monospace",
        }}>{line.slice(3)}</h2>
      );
    } else if (line.startsWith('### ')) {
      nodes.push(
        <h3 key={key++} style={{
          fontSize: '0.82rem', fontWeight: 600, color: '#a78bfa',
          marginTop: '1.2rem', marginBottom: '0.4rem',
          letterSpacing: '0.06em', textTransform: 'uppercase',
          fontFamily: "'JetBrains Mono', monospace",
        }}>{line.slice(4)}</h3>
      );
    } else if (line.startsWith('---')) {
      nodes.push(<hr key={key++} style={{ border: 'none', borderTop: '1px solid #1e2832', margin: '1.5rem 0' }} />);
    } else if (line.startsWith('*') && line.endsWith('*') && line.length > 2) {
      nodes.push(
        <p key={key++} style={{ fontSize: '0.72rem', color: '#4a5a6a', marginTop: '0.5rem', fontStyle: 'italic' }}>
          {line.slice(1, -1)}
        </p>
      );
    } else if (line.trim() === '') {
      nodes.push(<div key={key++} style={{ height: '0.5rem' }} />);
    } else {
      // Inline bold: **text**
      const parts = line.split(/(\*\*[^*]+\*\*)/g);
      const rendered = parts.map((p, pi) =>
        p.startsWith('**') && p.endsWith('**')
          ? <strong key={pi} style={{ color: '#e8edf2', fontWeight: 700 }}>{p.slice(2, -2)}</strong>
          : p
      );
      nodes.push(
        <p key={key++} style={{
          fontSize: '0.875rem', color: '#a8b8c8', lineHeight: '1.75',
          marginBottom: '0.25rem',
        }}>{rendered}</p>
      );
    }
  }
  return nodes;
}

// ─── Recommendation badge ─────────────────────────────────────────────────────
function RecBadge({ rec }: { rec: string }) {
  const cfg: Record<string, { color: string; bg: string; label: string }> = {
    STRONG_BUY:  { color: '#00ff88', bg: '#00ff8820', label: 'STRONG BUY' },
    BUY:         { color: '#00ff88', bg: '#00ff8815', label: 'BUY' },
    HOLD:        { color: '#ffcc00', bg: '#ffcc0015', label: 'HOLD' },
    SELL:        { color: '#ff3366', bg: '#ff336615', label: 'SELL' },
    STRONG_SELL: { color: '#ff3366', bg: '#ff336620', label: 'STRONG SELL' },
  };
  const c = cfg[rec] ?? cfg.HOLD;
  return (
    <span style={{
      padding: '4px 12px', borderRadius: 6, fontWeight: 800, fontSize: '0.8rem',
      color: c.color, background: c.bg, border: `1px solid ${c.color}50`,
      letterSpacing: '0.1em', fontFamily: "'JetBrains Mono', monospace",
    }}>{c.label}</span>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function ReportPage() {
  const params = useParams();
  const symbol = (params?.symbol as string ?? '').toUpperCase();

  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');
  const [meta, setMeta]       = useState({ name: '', industry: '', price: '', rec: '' });
  const [done, setDone]       = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);

  useEffect(() => {
    if (!symbol) return;

    const ctrl = new AbortController();

    (async () => {
      try {
        const res = await fetch(`/api/report/${symbol}`, { signal: ctrl.signal });
        if (!res.ok) {
          const j = await res.json();
          setError(j.error ?? 'Lỗi không xác định');
          setLoading(false);
          return;
        }

        setMeta({
          name:     res.headers.get('X-Stock-Name')     ?? '',
          industry: res.headers.get('X-Stock-Industry') ?? '',
          price:    res.headers.get('X-Stock-Price')    ?? '',
          rec:      res.headers.get('X-AI-Rec')         ?? '',
        });
        setLoading(false);

        const reader = res.body!.getReader();
        const dec    = new TextDecoder();
        let buf = '';

        while (true) {
          const { done: d, value } = await reader.read();
          if (d) { setDone(true); break; }
          buf += dec.decode(value, { stream: true });
          setContent(buf);
          if (autoScroll.current) {
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
          }
        }
      } catch (e: unknown) {
        if ((e as Error).name !== 'AbortError') setError(String(e));
      }
    })();

    return () => ctrl.abort();
  }, [symbol]);

  // Stop auto-scroll if user scrolls up
  useEffect(() => {
    const onScroll = () => {
      const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 120;
      autoScroll.current = atBottom;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const print = () => window.print();
  const back  = () => window.close();

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Newsreader:ital,wght@0,400;0,600;1,400&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #05080a; color: #c8d4e0; font-family: 'Newsreader', Georgia, serif; }

        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes pulse  { 0%,100%{opacity:.5} 50%{opacity:1} }
        .cursor { display:inline-block; width:2px; height:1em; background:#00d4ff; animation:blink 1s step-end infinite; vertical-align:text-bottom; margin-left:2px; }
        .fade-in { animation: fadeIn 0.4s ease both; }

        @media print {
          .no-print { display:none !important; }
          body { background: white; color: black; }
          h1,h2,h3 { color: black !important; border-color: #ccc !important; }
          p { color: #333 !important; }
        }
      `}</style>

      {/* ── Header bar ── */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'rgba(5,8,10,0.95)', backdropFilter: 'blur(12px)',
        borderBottom: '1px solid #1e2832',
        padding: '10px 24px', display: 'flex', alignItems: 'center', gap: 16,
      }} className="no-print">
        {/* Back */}
        <button onClick={back} style={{
          background: 'none', border: '1px solid #2a3642', color: '#8b99a8',
          borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: '0.75rem',
          fontFamily: "'JetBrains Mono', monospace",
        }}>← Đóng</button>

        {/* Symbol */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
          <span style={{
            fontFamily: "'JetBrains Mono', monospace", fontWeight: 800,
            fontSize: '1rem', color: '#e8edf2', letterSpacing: '-0.02em',
          }}>{symbol}</span>
          {meta.name && (
            <span style={{ fontSize: '0.75rem', color: '#4a5a6a' }}>
              {meta.name}
            </span>
          )}
          {meta.industry && (
            <span style={{
              fontSize: '0.7rem', color: '#8b99a8',
              background: '#1e2832', padding: '2px 8px', borderRadius: 4,
            }}>{meta.industry}</span>
          )}
          {meta.price && (
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.85rem', color: '#00ff88' }}>
              {Number(meta.price).toFixed(1)}
            </span>
          )}
          {meta.rec && <RecBadge rec={meta.rec} />}
        </div>

        {/* Print */}
        {done && (
          <button onClick={print} className="fade-in" style={{
            background: '#00d4ff15', border: '1px solid #00d4ff40', color: '#00d4ff',
            borderRadius: 6, padding: '4px 14px', cursor: 'pointer', fontSize: '0.75rem',
            fontFamily: "'JetBrains Mono', monospace", letterSpacing: '0.05em',
          }}>🖨 In báo cáo</button>
        )}
      </div>

      {/* ── Loading skeleton ── */}
      {loading && (
        <div style={{ maxWidth: 860, margin: '80px auto', padding: '0 24px', textAlign: 'center' }}>
          <div style={{ animation: 'pulse 1.5s ease infinite' }}>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: '0.75rem',
              color: '#00d4ff', letterSpacing: '0.15em', marginBottom: 16,
            }}>● ĐANG TẠO BÁO CÁO AI</div>
            <div style={{ color: '#4a5a6a', fontSize: '0.8rem' }}>
              Phân tích dữ liệu tài chính {symbol}...
            </div>
          </div>
        </div>
      )}

      {/* ── Error ── */}
      {error && (
        <div style={{ maxWidth: 860, margin: '80px auto', padding: '0 24px' }}>
          <div style={{
            background: '#ff336610', border: '1px solid #ff336640',
            borderRadius: 10, padding: '20px 24px',
          }}>
            <div style={{ color: '#ff3366', fontWeight: 700, marginBottom: 8 }}>⚠ Lỗi tạo báo cáo</div>
            <div style={{ color: '#c8d4e0', fontSize: '0.85rem' }}>{error}</div>
          </div>
        </div>
      )}

      {/* ── Report content ── */}
      {!loading && !error && (
        <main style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px 80px' }}>

          {/* Watermark header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #1e2832',
          }} className="no-print">
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.65rem', color: '#2a3642', letterSpacing: '0.1em' }}>
              VN STOCK SCANNER — AI RESEARCH REPORT
            </div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.65rem', color: '#2a3642' }}>
              {new Date().toLocaleDateString('vi-VN', { day:'2-digit', month:'2-digit', year:'numeric' })}
            </div>
          </div>

          {/* Streamed markdown */}
          <div style={{ lineHeight: 1.75 }}>
            {renderMarkdown(content)}
            {!done && <span className="cursor" />}
          </div>

          {done && (
            <div className="fade-in" style={{
              marginTop: 40, padding: '16px 20px',
              background: '#0a0f14', border: '1px solid #1e2832', borderRadius: 10,
              fontFamily: "'JetBrains Mono', monospace", fontSize: '0.7rem',
              color: '#2a3642', textAlign: 'center', lineHeight: 1.8,
            }}>
              ✓ BÁO CÁO HOÀN CHỈNH · VN Stock Scanner AI · Chỉ mang tính tham khảo, không phải khuyến nghị đầu tư
            </div>
          )}

          <div ref={bottomRef} />
        </main>
      )}
    </>
  );
}
