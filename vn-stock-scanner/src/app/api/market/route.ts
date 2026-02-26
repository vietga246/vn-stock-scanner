// ============================================================
// app/api/market/route.ts
//
// Route: GET /api/market
// Mục đích: Lấy tổng quan VN-Index, VN30, HNX
//
// Tại sao cần file này?
// → Code này chạy trên SERVER của Next.js (không phải browser)
// → Server không bị CORS block → gọi TCBS thoải mái
// → Browser gọi /api/market (cùng domain) → không bị block
// ============================================================

import { NextResponse } from 'next/server'
import { fetchMarketOverview } from '@/lib/tcbs'
import { ApiResponse, MarketOverview } from '@/types/stock'

export async function GET() {
  try {
    const data = await fetchMarketOverview()

    const response: ApiResponse<MarketOverview> = {
      success: true,
      data,
      timestamp: new Date().toISOString(),
    }

    return NextResponse.json(response, {
      headers: {
        // Cache 60 giây — dữ liệu thị trường cập nhật không quá nhanh
        'Cache-Control': 'public, s-maxage=60, stale-while-revalidate=30',
      },
    })

  } catch (error) {
    console.error('[API/market] Lỗi:', error)

    const response: ApiResponse<null> = {
      success: false,
      error: error instanceof Error ? error.message : 'Lỗi không xác định',
      timestamp: new Date().toISOString(),
    }

    return NextResponse.json(response, { status: 500 })
  }
}
