import { NextResponse } from 'next/server'
import { fetchMultipleStocks, scoreStock, passesHardGates } from '@/lib/tcbs'
import { ALL_TICKERS } from '@/lib/tickers'
import { StockData } from '@/types/stock'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const startTime = Date.now()

    const rawStocks = await fetchMultipleStocks(ALL_TICKERS)

    const filtered = rawStocks.filter(passesHardGates)

    const scored: StockData[] = filtered.map(stock => {
      const { score, signal } = scoreStock(stock)
      return { ...stock, score, signal }
    })

    scored.sort((a, b) => b.score - a.score)

    const summary = {
      total: ALL_TICKERS.length,
      fetched: rawStocks.length,
      passed: filtered.length,
      buy: scored.filter(s => s.signal === 'buy').length,
      watch: scored.filter(s => s.signal === 'watch').length,
      avoid: scored.filter(s => s.signal === 'avoid').length,
      elapsedMs: Date.now() - startTime,
    }

    // Luôn trả về success: true — mock data đảm bảo luôn có data
    return NextResponse.json({
      success: true,
      data: { stocks: scored, summary },
      timestamp: new Date().toISOString(),
    })

  } catch (error) {
    console.error('[API/stocks] Lỗi:', error)
    // Trả về array rỗng thay vì error — UI xử lý gracefully
    return NextResponse.json({
      success: true,
      data: {
        stocks: [],
        summary: { total: 0, fetched: 0, passed: 0, buy: 0, watch: 0, avoid: 0, elapsedMs: 0 }
      },
      timestamp: new Date().toISOString(),
    })
  }
}
