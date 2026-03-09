import { NextRequest, NextResponse } from 'next/server';

// ─── Dùng OpenAI GPT-4o — khớp với pipeline workflow 6 (ai_analyst.py) ──────
const OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions';

const SYSTEM_PROMPT = `Bạn là chuyên gia phân tích đầu tư chứng khoán Việt Nam với 20 năm kinh nghiệm, thành thạo phân tích kỹ thuật ICT, dòng tiền tổ chức, phân tích cơ bản và định giá.

Viết báo cáo phân tích đầu tư TOÀN DIỆN bằng tiếng Việt, có chiều sâu, dùng dữ liệu cụ thể để lập luận. Không viết chung chung.`;

function buildPrompt(
  symbol: string,
  stock: Record<string, unknown>,
  detail: Record<string, unknown[]> | null,
  aiAnalysis: Record<string, unknown> | null,
  regime: Record<string, unknown> | null,
): string {
  const fmt    = (v: unknown, dec = 1) => (v != null && v !== '' ? Number(v).toFixed(dec) : 'N/A');
  const fmtPct = (v: unknown) => v != null ? (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' : 'N/A';
  const fmtB   = (v: unknown) => v != null ? (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(1) + 'B' : 'N/A';

  type IncomeR   = { year:number; quarter:number; revenue:number; net_profit:number; revenue_growth:number };
  type BalanceR  = { year:number; quarter:number; total_assets:number; total_equity:number; total_debt:number; cash:number };
  type CashflowR = { year:number; quarter:number; cfo:number; capex:number };
  type RatioR    = { year:number; quarter:number; pe:number; pb:number; roe:number; roa:number; net_margin:number; debt_equity:number; current_ratio:number };

  const incomeStr = ((detail?.income ?? []) as unknown as IncomeR[]).slice(0, 8).map(r =>
    `  ${r.year}Q${r.quarter}: DT=${fmt(r.revenue,0)}B LN=${fmt(r.net_profit,0)}B TT=${fmtPct(r.revenue_growth)}`
  ).join('\n') || '  Không có dữ liệu';

  const ratioStr = ((detail?.ratio ?? []) as unknown as RatioR[]).slice(0, 6).map(r =>
    `  ${r.year}Q${r.quarter}: PE=${fmt(r.pe)} PB=${fmt(r.pb)} ROE=${fmt(r.roe)}% ROA=${fmt(r.roa)}% BienRong=${fmt(r.net_margin)}% DE=${fmt(r.debt_equity)} CR=${fmt(r.current_ratio)}`
  ).join('\n') || '  Không có dữ liệu';

  const balanceStr = ((detail?.balance ?? []) as unknown as BalanceR[]).slice(0, 4).map(r =>
    `  ${r.year}Q${r.quarter}: TS=${fmt(r.total_assets,0)}B VonCSH=${fmt(r.total_equity,0)}B No=${fmt(r.total_debt,0)}B Tien=${fmt(r.cash,0)}B`
  ).join('\n') || '  Không có dữ liệu';

  const cashflowStr = ((detail?.cashflow ?? []) as unknown as CashflowR[]).slice(0, 4).map(r => {
    const fcf = Number(r.cfo ?? 0) + Number(r.capex ?? 0);
    return `  ${r.year}Q${r.quarter}: CFO=${fmt(r.cfo,0)}B CAPEX=${fmt(r.capex,0)}B FCF=${fmt(fcf,0)}B`;
  }).join('\n') || '  Không có dữ liệu';

  // Context từ ai_analysis.json — output của workflow 6
  const aiCtx = aiAnalysis ? `
Phân tích AI từ workflow 6 (tham khảo):
  Khuyến nghị: ${aiAnalysis.recommendation}
  Tóm tắt: ${aiAnalysis.executive_summary || aiAnalysis.summary || ''}
  Kỹ thuật: ${(aiAnalysis.sections as Record<string,string>)?.ict_analysis || aiAnalysis.technical_view || ''}
  Dòng tiền: ${(aiAnalysis.sections as Record<string,string>)?.flow_analysis || aiAnalysis.flow_view || ''}
  Cơ bản: ${(aiAnalysis.sections as Record<string,string>)?.fundamental_view || aiAnalysis.fundamental_view || ''}
  Regime: ${(aiAnalysis.sections as Record<string,string>)?.regime_impact || ''}` : '';

  const regimeCtx = regime
    ? `\nRegime thị trường: ${regime.regime} | bull_weight=${Number(regime.bull_weight ?? 0.5) * 100}% | VN-Index=${fmt(regime.vnindex)}`
    : '';

  return `${regimeCtx}${aiCtx}

DỮ LIỆU CỔ PHIẾU ${symbol}:
  Tên: ${stock.name} | Ngành: ${stock.industry} | Sàn: ${stock.exchange}
  Giá: ${fmt(stock.close || stock.price)} nghìn đồng
  Thay đổi: 1D=${fmtPct(stock.price_change_1d)} 5D=${fmtPct(stock.price_change_5d)} 20D=${fmtPct(stock.price_change_20d)}
  Điểm: Tổng=${fmt(stock.composite_score)} Cơbản=${fmt(stock.fundamental_score)} SmartMoney=${fmt(stock.smart_money_score)} Momentum=${fmt(stock.momentum_score)} Kỹthuật=${fmt(stock.technical_score)} | Tier=${stock.tier}
  PE=${fmt(stock.pe)} ROE=${fmt(stock.roe)}% ROA=${fmt(stock.roa)}% TT.DT=${fmtPct(stock.revenue_growth)} BienRong=${fmt(stock.net_margin)}% D/E=${fmt(stock.debt_equity)}
  RSI=${fmt(stock.rsi14)} ADX=${fmt(stock.adx14)} %vsMa20=${fmtPct(stock.pct_from_ma20)}
  Khối ngoại: 7D=${fmtB(stock.foreign_net_7d)} 30D=${fmtB(stock.foreign_net_30d)}

LỊCH SỬ THU NHẬP:
${incomeStr}

CHỈ SỐ TÀI CHÍNH:
${ratioStr}

BẢNG CÂN ĐỐI:
${balanceStr}

DÒNG TIỀN:
${cashflowStr}

---
Hãy viết báo cáo đầy đủ BẰNG TIẾNG VIỆT theo đúng 8 phần. Mỗi phần phải có phân tích THỰC CHẤT dựa trên số liệu cụ thể ở trên:

# BÁO CÁO PHÂN TÍCH ĐẦU TƯ: ${symbol}

## 1. TÓM TẮT ĐIỀU HÀNH
Tổng quan hoạt động kinh doanh. Luận điểm đầu tư 2-3 câu: MUA/GIỮ/BÁN ở mức giá hiện tại? Catalyst chính và rủi ro lớn nhất.

## 2. HIỆU QUẢ TÀI CHÍNH & TÌNH HÌNH TÀI CHÍNH
### 2.1 Phân tích Báo cáo Thu nhập
Xu hướng doanh thu, biên lợi nhuận gộp/hoạt động/ròng qua các năm — dùng số liệu cụ thể.
### 2.2 Phân tích Bảng Cân đối Kế toán
Mức nợ, D/E ratio, thanh khoản, vị thế tiền mặt — mạnh hay yếu?
### 2.3 Phân tích Dòng tiền
CFO, CAPEX, FCF — công ty có liên tục dương FCF không?

## 3. ĐỊNH GIÁ
### 3.1 Phân tích Bội số
So sánh PE/PB/ROE hiện tại vs lịch sử 5 năm vs ngành ${stock.industry} vs 3 đối thủ cạnh tranh trực tiếp.
### 3.2 Kết luận Định giá
Đang định giá quá cao / thấp / hợp lý ở mức giá ${fmt(stock.close || stock.price)}?

## 4. MÔ HÌNH KINH DOANH & HÀO KINH TẾ
### 4.1 Phân khúc Kinh doanh
Các mảng kinh doanh cốt lõi và đóng góp doanh thu tương ứng.
### 4.2 Lợi thế Cạnh tranh
Nguồn lợi thế: thương hiệu, chi phí, quy mô, mạng lưới? Độ bền của hào kinh tế.

## 5. CHIẾN LƯỢC TĂNG TRƯỞNG & TRIỂN VỌNG
### 5.1 Động lực Tăng trưởng
Catalyst kỳ vọng: sản phẩm mới, mở rộng thị trường, xu hướng ngành ${stock.industry}.
### 5.2 Cơ hội Thị trường
TAM ngành và tiềm năng tăng thị phần của ${symbol}.

## 6. QUẢN LÝ & QUẢN TRỊ
### 6.1 Lãnh đạo
CEO và ban điều hành — nhiệm kỳ, thành tích.
### 6.2 Phân bổ Vốn
Cổ tức, mua lại cổ phiếu, M&A.
### 6.3 Sở hữu Nội bộ
Tỷ lệ cổ đông nội bộ và cổ đông lớn.

## 7. PHÂN TÍCH RỦI RO
### 7.1 Rủi ro Đặc thù
3 rủi ro nội tại cụ thể của ${symbol}.
### 7.2 Rủi ro Hệ thống
3 rủi ro vĩ mô / thị trường ảnh hưởng trực tiếp.

## 8. KHUYẾN NGHỊ CUỐI CÙNG
Tổng hợp → Xếp hạng **MUA / GIỮ / BÁN** với lý luận cân bằng cơ hội vs rủi ro ở giá ${fmt(stock.close || stock.price)}.

---
*Báo cáo tạo tự động bởi VN Stock Scanner AI · Chỉ mang tính tham khảo, không phải khuyến nghị đầu tư chính thức.*`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: { symbol: string } }
) {
  const symbol = params.symbol.toUpperCase();
  const apiKey = process.env.OPENAI_API_KEY;

  if (!apiKey) {
    return NextResponse.json(
      { error: 'OPENAI_API_KEY chưa được cấu hình. Thêm vào .env.local hoặc Vercel environment variables.' },
      { status: 500 }
    );
  }

  try {
    const base = request.nextUrl.origin;

    const [screenerRes, stocksRes, aiRes, ictRes] = await Promise.all([
      fetch(`${base}/api/screener`).then(r => r.json()).catch(() => null),
      fetch(`${base}/api/stocks`).then(r => r.json()).catch(() => null),
      fetch(`${base}/api/ai-analysis`).then(r => r.json()).catch(() => null),
      fetch(`${base}/api/ict-signals`).then(r => r.json()).catch(() => null),
    ]);

    const stock = screenerRes?.screener?.find(
      (s: Record<string, unknown>) => s.symbol === symbol
    );
    if (!stock) {
      return NextResponse.json(
        { error: `Không tìm thấy mã ${symbol}` },
        { status: 404 }
      );
    }

    const detail     = stocksRes?.details?.[symbol] ?? null;
    const aiAnalysis = aiRes?.analyses?.[symbol]     ?? null;
    const regime     = ictRes?.regime                ?? null;

    const prompt = buildPrompt(symbol, stock, detail, aiAnalysis, regime);

    // Gọi OpenAI GPT-4o với streaming
    const openaiRes = await fetch(OPENAI_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model:      'gpt-4o',
        max_tokens: 4096,
        stream:     true,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user',   content: prompt },
        ],
      }),
    });

    if (!openaiRes.ok) {
      const err = await openaiRes.text();
      return NextResponse.json(
        { error: `OpenAI API lỗi ${openaiRes.status}: ${err.slice(0, 300)}` },
        { status: 500 }
      );
    }

    // Parse OpenAI SSE stream → plain text stream cho frontend
    const stream = new ReadableStream({
      async start(controller) {
        const reader  = openaiRes.body!.getReader();
        const decoder = new TextDecoder();
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            for (const line of chunk.split('\n')) {
              if (!line.startsWith('data: ')) continue;
              const data = line.slice(6).trim();
              if (data === '[DONE]') continue;
              try {
                const parsed = JSON.parse(data);
                const text   = parsed?.choices?.[0]?.delta?.content ?? '';
                if (text) controller.enqueue(new TextEncoder().encode(text));
              } catch { /* bỏ qua SSE line lỗi parse */ }
            }
          }
        } finally {
          controller.close();
        }
      },
    });

    return new Response(stream, {
      headers: {
        'Content-Type':      'text/plain; charset=utf-8',
        'Transfer-Encoding': 'chunked',
        'Cache-Control':     'no-cache',
        'X-Stock-Symbol':    symbol,
        'X-Stock-Name':      String(stock.name     ?? ''),
        'X-Stock-Industry':  String(stock.industry ?? ''),
        'X-Stock-Price':     String(stock.close ?? stock.price ?? ''),
        'X-AI-Rec':          String(aiAnalysis?.recommendation ?? ''),
        'X-AI-Model':        'gpt-4o',
      },
    });

  } catch (err) {
    console.error('[/api/report] error:', err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
