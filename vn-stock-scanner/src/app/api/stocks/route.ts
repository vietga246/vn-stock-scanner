// ============================================================
// app/api/stocks/route.ts
//
// Route: GET /api/stocks?tickers=FPT,VCB,HPG
//        GET /api/stocks        (dùng danh sách mặc định)
//
// Đây là route chính — quét toàn bộ danh sách và trả về
// kết quả đã lọc + chấm điểm
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { fetchMultipleStocks, scoreStock, passesHardGates } from '@/lib/tcbs'
import { ALL_TICKERS } from '@/lib/tickers'
import { ApiResponse, StockData } from '@/types/stock'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)

    // Cho phép client truyền danh sách ticker tùy chỉnh
    // Ví dụ: /api/stocks?tickers=FPT,VCB,HPG
    const tickersParam = searchParams.get('tickers')
    const tickers = tickersParam
      ? tickersParam.split(',').map(t => t.trim().toUpperCase())
      : ALL_TICKERS

    console.log(`[API/stocks] Bắt đầu quét ${tickers.length} mã...`)
    const startTime = Date.now()

    // Lấy dữ liệu tất cả mã
    const rawStocks = await fetchMultipleStocks(tickers)
    console.log(`[API/stocks] Lấy được ${rawStocks.length} mã thô`)

    // Bước 1: Hard gates — lọc mã không đủ điều kiện
    const filtered = rawStocks.filter(passesHardGates)
    console.log(`[API/stocks] ${filtered.length} mã qua hard gates`)

    // Bước 2: Chấm điểm
    const scored: StockData[] = filtered.map(stock => {
      const { score, signal } = scoreStock(stock)
      return { ...stock, score, signal }
    })

    // Bước 3: Sắp xếp theo điểm cao → thấp
    scored.sort((a, b) => b.score - a.score)

    const elapsed = Date.now() - startTime
    console.log(`[API/stocks] Hoàn thành sau ${elapsed}ms`)

    // Thống kê tóm tắt
    const summary = {
      total: tickers.length,
      fetched: rawStocks.length,
      passed: filtered.length,
      buy: scored.filter(s => s.signal === 'buy').length,
      watch: scored.filter(s => s.signal === 'watch').length,
      avoid: scored.filter(s => s.signal === 'avoid').length,
      elapsedMs: elapsed,
    }

    const response: ApiResponse<{ stocks: StockData[]; summary: typeof summary }> = {
      success: true,
      data: { stocks: scored, summary },
      timestamp: new Date().toISOString(),
    }

    return NextResponse.json(response, {
      headers: {
        'Cache-Control': 'public, s-maxage=120, stale-while-revalidate=60',
      },
    })

  } catch (error) {
    console.error('[API/stocks] Lỗi nghiêm trọng:', error)

    const response: ApiResponse<null> = {
      success: false,
      error: error instanceof Error ? error.message : 'Lỗi server',
      timestamp: new Date().toISOString(),
    }

    return NextResponse.json(response, { status: 500 })
  }
}
