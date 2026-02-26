// ============================================================
// app/api/stock/[ticker]/route.ts
//
// Route: GET /api/stock/FPT
//        GET /api/stock/VCB
//
// Lấy chi tiết 1 cổ phiếu cụ thể
// Dùng khi user click vào 1 mã để xem thêm
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { fetchSingleStock, scoreStock } from '@/lib/tcbs'
import { ApiResponse, StockData } from '@/types/stock'

export const dynamic = 'force-dynamic'

export async function GET(
  _request: NextRequest,
  { params }: { params: { ticker: string } }
) {
  const ticker = params.ticker.toUpperCase()

  try {
    const stock = await fetchSingleStock(ticker)

    if (!stock) {
      return NextResponse.json(
        {
          success: false,
          error: `Không tìm thấy dữ liệu cho mã ${ticker}`,
          timestamp: new Date().toISOString(),
        } satisfies ApiResponse<null>,
        { status: 404 }
      )
    }

    // Chấm điểm
    const { score, signal } = scoreStock(stock)
    const result: StockData = { ...stock, score, signal }

    return NextResponse.json(
      {
        success: true,
        data: result,
        timestamp: new Date().toISOString(),
      } satisfies ApiResponse<StockData>,
      {
        headers: { 'Cache-Control': 'public, s-maxage=30' },
      }
    )

  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : 'Lỗi server',
        timestamp: new Date().toISOString(),
      } satisfies ApiResponse<null>,
      { status: 500 }
    )
  }
}
