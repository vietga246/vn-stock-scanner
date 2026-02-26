// DEBUG VERSION - xem TCBS trả về gì
import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

export async function GET() {
  const results: Record<string, unknown> = {}

  // Test 1: Gọi trực tiếp TCBS market overview
  try {
    const r1 = await fetch(
      'https://apipubaws.tcbs.com.vn/stock-insight/v1/index/overview',
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Accept': 'application/json',
          'Origin': 'https://tcinvest.tcbs.com.vn',
          'Referer': 'https://tcinvest.tcbs.com.vn/',
        },
        cache: 'no-store',
      }
    )
    results.market_status = r1.status
    results.market_ok = r1.ok
    if (r1.ok) {
      const data = await r1.json()
      results.market_data = data
    } else {
      results.market_error = await r1.text()
    }
  } catch (e) {
    results.market_exception = String(e)
  }

  // Test 2: Gọi 1 mã cổ phiếu FPT
  try {
    const r2 = await fetch(
      'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/ticker-overview/FPT',
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Accept': 'application/json',
          'Origin': 'https://tcinvest.tcbs.com.vn',
          'Referer': 'https://tcinvest.tcbs.com.vn/',
        },
        cache: 'no-store',
      }
    )
    results.fpt_status = r2.status
    results.fpt_ok = r2.ok
    if (r2.ok) {
      const data = await r2.json()
      results.fpt_data = data
    } else {
      results.fpt_error = await r2.text()
    }
  } catch (e) {
    results.fpt_exception = String(e)
  }

  // Test 3: Thử endpoint khác của TCBS
  try {
    const r3 = await fetch(
      'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/ticker-overview/VCB',
      {
        headers: {
          'User-Agent': 'Mozilla/5.0',
          'Accept': '*/*',
        },
        cache: 'no-store',
      }
    )
    results.vcb_status = r3.status
    if (r3.ok) {
      results.vcb_data = await r3.json()
    }
  } catch (e) {
    results.vcb_exception = String(e)
  }

  return NextResponse.json(results, { status: 200 })
}
