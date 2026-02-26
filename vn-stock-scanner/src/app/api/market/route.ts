import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0',
  'Accept': 'application/json, text/plain, */*',
  'Origin': 'https://iboard.ssi.com.vn',
  'Referer': 'https://iboard.ssi.com.vn/',
}

export async function GET() {
  // SSI iBoard — cùng nguồn đang lấy giá cổ phiếu thành công
  try {
    const res = await fetch(
      'https://iboard.ssi.com.vn/dchart/api/1.1/index/allIndex',
      { headers: HEADERS, cache: 'no-store', signal: AbortSignal.timeout(8000) }
    )

    if (res.ok) {
      const json = await res.json()
      // SSI trả về array các index
      const items: Record<string, unknown>[] = Array.isArray(json)
        ? json
        : (json.data ?? json.items ?? json.indexList ?? [])

      const find = (codes: string[]) => {
        const d = items.find(i => {
          const c = String(i.indexId ?? i.comGroupCode ?? i.code ?? i.index ?? '')
            .toUpperCase()
          return codes.some(code => c.includes(code))
        })
        if (!d) return { value: 0, change: 0, percentChange: 0 }

        const val = Number(d.indexValue ?? d.value ?? d.close ?? 0)
        const chg = Number(d.indexChange ?? d.change ?? d.changed ?? 0)
        const pct = Number(d.percentChange ?? d.pctChange ?? d.changed_percentage ?? 0)
        return { value: val, change: chg, percentChange: pct }
      }

      const vnindex = find(['VNINDEX'])
      const vn30 = find(['VN30'])
      const hnx = find(['HNXINDEX', 'HNX'])

      if (vnindex.value > 0) {
        return NextResponse.json({
          success: true,
          data: {
            vnindex, vn30, hnx,
            advancing: 0, declining: 0, unchanged: 0, totalValue: 0,
            timestamp: new Date().toISOString(),
          }
        })
      }
    }
  } catch (e) {
    console.log('[market] SSI allIndex lỗi:', e)
  }

  // Fallback 2: SSI endpoint khác
  try {
    const res = await fetch(
      'https://iboard.ssi.com.vn/dchart/api/1.1/defaultAllIndex',
      { headers: HEADERS, cache: 'no-store', signal: AbortSignal.timeout(8000) }
    )

    if (res.ok) {
      const json = await res.json()
      const items: Record<string, unknown>[] = Array.isArray(json) ? json : (json.data ?? [])

      const find = (code: string) => {
        const d = items.find(i =>
          String(i.indexId ?? i.comGroupCode ?? i.code ?? '').toUpperCase().includes(code)
        )
        if (!d) return { value: 0, change: 0, percentChange: 0 }
        return {
          value: Number(d.indexValue ?? d.value ?? 0),
          change: Number(d.indexChange ?? d.change ?? 0),
          percentChange: Number(d.percentChange ?? d.pctChange ?? 0),
        }
      }

      const vnindex = find('VNINDEX')
      if (vnindex.value > 0) {
        return NextResponse.json({
          success: true,
          data: {
            vnindex, vn30: find('VN30'), hnx: find('HNX'),
            advancing: 0, declining: 0, unchanged: 0, totalValue: 0,
            timestamp: new Date().toISOString(),
          }
        })
      }
    }
  } catch (e) {
    console.log('[market] SSI defaultAllIndex lỗi:', e)
  }

  // Trả về 0 thay vì crash
  return NextResponse.json({
    success: true,
    data: {
      vnindex: { value: 0, change: 0, percentChange: 0 },
      vn30: { value: 0, change: 0, percentChange: 0 },
      hnx: { value: 0, change: 0, percentChange: 0 },
      advancing: 0, declining: 0, unchanged: 0, totalValue: 0,
      timestamp: new Date().toISOString(),
    }
  })
}
