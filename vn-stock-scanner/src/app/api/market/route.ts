import { NextResponse } from 'next/server'
import { fetchMarketOverview } from '@/lib/tcbs'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const data = await fetchMarketOverview()
    return NextResponse.json({ success: true, data, timestamp: new Date().toISOString() })
  } catch {
    // Không bao giờ crash — trả về zeros
    return NextResponse.json({
      success: true,
      data: {
        vnindex: { value: 0, change: 0, percentChange: 0 },
        vn30: { value: 0, change: 0, percentChange: 0 },
        hnx: { value: 0, change: 0, percentChange: 0 },
        advancing: 0, declining: 0, unchanged: 0, totalValue: 0,
        timestamp: new Date().toISOString(),
      },
      timestamp: new Date().toISOString(),
    })
  }
}
