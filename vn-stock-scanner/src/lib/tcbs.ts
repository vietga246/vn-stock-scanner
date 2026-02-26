// ============================================================
// lib/tcbs.ts — Dùng nguồn dữ liệu MSN/KBS (vnstock compatible)
// Đây là nguồn mà thư viện vnstock đang dùng, hoạt động tốt 2025
// ============================================================

import { StockData, MarketOverview } from '@/types/stock'

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36',
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'vi-VN,vi;q=0.9',
  'Connection': 'keep-alive',
}

// ============================================================
// SOURCE 1: MSN Finance — nguồn vnstock đang dùng, ổn định
// ============================================================
async function fetchFromMSN(tickers: string[]): Promise<StockData[]> {
  const results: StockData[] = []

  try {
    // MSN Finance hỗ trợ nhiều mã cùng lúc
    const symbols = tickers.map(t => `${t}.HM`).join(',')
    const url = `https://api.msn.com/money/quotes/latest?symbols=${encodeURIComponent(symbols)}&apikey=0QfOX3Vn51YsPZNjCt3K4IHMDfHlheMT&ocid=finance-utils&cm=vi-vn`

    const res = await fetch(url, {
      headers: HEADERS,
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
    })

    if (!res.ok) return []
    const json = await res.json()
    const quotes = json.value ?? []

    quotes.forEach((q: Record<string, unknown>) => {
      const rawCode = String(q.symbol ?? '').replace('.HM', '').replace('.HN', '')
      const price = Number(q.price ?? q.lastPrice ?? 0)
      const prevClose = Number(q.previousClose ?? price)
      const high = Number(q.high ?? price)
      const low = Number(q.low ?? price)
      const vol = Number(q.volume ?? 0)
      const priceChange = price - prevClose
      const pctChange = prevClose > 0 ? (priceChange / prevClose) * 100 : 0
      const volatility = prevClose > 0 ? parseFloat(((high - low) / prevClose * 100).toFixed(2)) : 0

      if (price > 0) {
        results.push({
          ticker: rawCode.toUpperCase(),
          companyName: String(q.name ?? rawCode),
          price: price * 1000, // MSN trả về đơn vị nghìn đồng
          priceChange: priceChange * 1000,
          percentChange: pctChange,
          volume: vol,
          volatility,
          score: 0,
          signal: 'watch',
        })
      }
    })
  } catch { /* tiếp tục fallback */ }

  return results
}

// ============================================================
// SOURCE 2: HoSE API chính thức — data cuối phiên, ổn định
// ============================================================
async function fetchFromHoSE(tickers: string[]): Promise<StockData[]> {
  const results: StockData[] = []
  const BATCH = 20

  for (let i = 0; i < tickers.length; i += BATCH) {
    const batch = tickers.slice(i, i + BATCH)

    try {
      const res = await fetch(
        `https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date&size=${BATCH}&page=1&q=code:${batch.join('~code:')}`,
        {
          headers: { ...HEADERS, 'Origin': 'https://www.vndirect.com.vn', 'Referer': 'https://www.vndirect.com.vn/' },
          cache: 'no-store',
          signal: AbortSignal.timeout(8000),
        }
      )

      if (!res.ok) continue
      const json = await res.json()
      const items: Record<string, unknown>[] = json.data ?? []

      items.forEach(d => {
        const close = Number(d.close ?? 0) * 1000 // VNDirect tính bằng nghìn đồng
        const ref = Number(d.pctChange ?? 0)
        const vol = Number(d.nmVolume ?? d.volume ?? 0)
        const high = Number(d.high ?? 0) * 1000
        const low = Number(d.low ?? 0) * 1000
        const refPrice = close / (1 + ref / 100) || close
        const volatility = refPrice > 0 ? parseFloat(((high - low) / refPrice * 100).toFixed(2)) : 0

        if (close > 0) {
          results.push({
            ticker: String(d.code ?? '').toUpperCase(),
            companyName: String(d.code ?? ''),
            price: close,
            priceChange: close - refPrice,
            percentChange: ref,
            volume: vol,
            volatility,
            score: 0,
            signal: 'watch',
          })
        }
      })
    } catch { continue }

    if (i + BATCH < tickers.length) await new Promise(r => setTimeout(r, 150))
  }

  return results
}

// ============================================================
// SOURCE 3: SSI iBoard — bảng giá toàn sàn
// ============================================================
async function fetchFromSSI(tickers: string[]): Promise<StockData[]> {
  try {
    const res = await fetch(
      'https://iboard.ssi.com.vn/dchart/api/1.1/defaultAllStocks',
      {
        headers: { ...HEADERS, 'Origin': 'https://iboard.ssi.com.vn', 'Referer': 'https://iboard.ssi.com.vn/' },
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      }
    )

    if (!res.ok) return []
    const json = await res.json()
    const items: Record<string, unknown>[] = Array.isArray(json) ? json : (json.data ?? json.items ?? [])
    const tickerSet = new Set(tickers.map(t => t.toUpperCase()))
    const results: StockData[] = []

    items.forEach((d: Record<string, unknown>) => {
      const code = String(d.s ?? d.code ?? d.mc ?? '').toUpperCase()
      if (!tickerSet.has(code)) return

      const close = Number(d.c ?? d.lastPrice ?? d.mp ?? 0)
      const ref = Number(d.r ?? d.refPrice ?? d.cp ?? close)
      const high = Number(d.h ?? d.highPrice ?? close)
      const low = Number(d.l ?? d.lowPrice ?? close)
      const vol = Number(d.v ?? d.volume ?? d.mt ?? 0)

      // SSI có thể dùng đơn vị nghìn hoặc đồng tùy version
      const priceScale = close < 1000 ? 1000 : 1
      const price = close * priceScale
      const refPrice = ref * priceScale
      const pctChange = refPrice > 0 ? ((price - refPrice) / refPrice) * 100 : 0
      const volatility = refPrice > 0 ? parseFloat(((high - low) * priceScale / refPrice * 100).toFixed(2)) : 0

      if (price > 0) {
        results.push({
          ticker: code,
          companyName: String(d.n ?? d.name ?? code),
          price,
          priceChange: price - refPrice,
          percentChange: pctChange,
          volume: vol,
          volatility,
          score: 0,
          signal: 'watch',
          foreignNet: Number(d.fBVol ?? d.fv ?? 0) - Number(d.fSVol ?? 0),
        })
      }
    })

    return results
  } catch { return [] }
}



// ============================================================
// PUBLIC: fetchMultipleStocks — thử từng nguồn
// ============================================================
export async function fetchMultipleStocks(
  tickers: string[],
  onProgress?: (done: number, total: number) => void
): Promise<StockData[]> {
  onProgress?.(5, 100)

  // Thử SSI trước (bảng giá toàn sàn — 1 request duy nhất)
  console.log('[fetch] Thử SSI iBoard...')
  let results = await fetchFromSSI(tickers)
  onProgress?.(40, 100)

  if (results.length >= 5) {
    console.log(`[fetch] SSI OK: ${results.length} mã`)
    onProgress?.(tickers.length, tickers.length)
    return results
  }

  // Thử VNDirect
  console.log('[fetch] SSI thất bại, thử VNDirect...')
  results = await fetchFromHoSE(tickers)
  onProgress?.(80, 100)

  if (results.length >= 5) {
    console.log(`[fetch] VNDirect OK: ${results.length} mã`)
    onProgress?.(tickers.length, tickers.length)
    return results
  }

  // Tất cả API lỗi → trả về mảng rỗng, không dùng mock
  console.log('[fetch] Tất cả API lỗi, trả về rỗng')
  onProgress?.(tickers.length, tickers.length)
  return []
}

export async function fetchSingleStock(ticker: string): Promise<StockData | null> {
  const results = await fetchMultipleStocks([ticker])
  return results[0] ?? null
}

// ============================================================
// fetchMarketOverview
// ============================================================
export async function fetchMarketOverview() {
  // SSI iBoard index endpoint bị block từ Vercel
  // → Tính thống kê từ data cổ phiếu SSI đã fetch được
  try {
    const res = await fetch(
      'https://iboard.ssi.com.vn/dchart/api/1.1/defaultAllStocks',
      {
        headers: { ...HEADERS, 'Origin': 'https://iboard.ssi.com.vn', 'Referer': 'https://iboard.ssi.com.vn/' },
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      }
    )

    if (res.ok) {
      const json = await res.json()
      const items: Record<string, unknown>[] = Array.isArray(json) ? json : (json.data ?? json.items ?? [])

      if (items.length > 10) {
        // Tìm index VN-Index trong danh sách (SSI có thể trả về cả index)
        const vnItem = items.find((i: Record<string, unknown>) => {
          const code = String(i.s ?? i.code ?? '').toUpperCase()
          return code === 'VNINDEX' || code === 'VNI'
        })
        const vn30Item = items.find((i: Record<string, unknown>) => String(i.s ?? i.code ?? '').toUpperCase() === 'VN30')

        if (vnItem) {
          const parseIndex = (d: Record<string, unknown>) => {
            const value = Number(d.c ?? d.iv ?? d.lastValue ?? 0)
            const change = Number(d.ch ?? d.change ?? 0)
            const pct = Number(d.cp ?? d.percentChange ?? 0)
            return { value, change, percentChange: pct }
          }
          return {
            vnindex: parseIndex(vnItem),
            vn30: vn30Item ? parseIndex(vn30Item) : { value: 0, change: 0, percentChange: 0 },
            hnx: { value: 0, change: 0, percentChange: 0 },
            advancing: items.filter((i: Record<string, unknown>) => Number(i.c ?? 0) > Number(i.r ?? i.c ?? 0)).length,
            declining: items.filter((i: Record<string, unknown>) => Number(i.c ?? 0) < Number(i.r ?? i.c ?? 1)).length,
            unchanged: 0,
            totalValue: 0,
            timestamp: new Date().toISOString(),
          }
        }

        // Nếu không tìm thấy index riêng, tính thống kê tăng/giảm từ cổ phiếu
        const advancing = items.filter((i: Record<string, unknown>) => Number(i.cp ?? i.percentChange ?? 0) > 0).length
        const declining = items.filter((i: Record<string, unknown>) => Number(i.cp ?? i.percentChange ?? 0) < 0).length

        return {
          vnindex: { value: 0, change: 0, percentChange: 0 },
          vn30: { value: 0, change: 0, percentChange: 0 },
          hnx: { value: 0, change: 0, percentChange: 0 },
          advancing,
          declining,
          unchanged: items.length - advancing - declining,
          totalValue: 0,
          timestamp: new Date().toISOString(),
        }
      }
    }
  } catch { /* fallback */ }

  return {
    vnindex: { value: 0, change: 0, percentChange: 0 },
    vn30: { value: 0, change: 0, percentChange: 0 },
    hnx: { value: 0, change: 0, percentChange: 0 },
    advancing: 0, declining: 0, unchanged: 0, totalValue: 0,
    timestamp: new Date().toISOString(),
  }
}

// ============================================================
// SCORING ENGINE
// ============================================================
export function scoreStock(stock: StockData): { score: number; signal: 'buy' | 'watch' | 'avoid' } {
  let score = 50

  const volM = stock.volume / 1_000_000
  if (volM >= 10)     score += 20
  else if (volM >= 3) score += 12
  else if (volM >= 1) score += 5
  else                score -= 20

  const vol = stock.volatility
  if (vol >= 2 && vol <= 5)     score += 15
  else if (vol > 5 && vol <= 8) score += 8
  else if (vol > 8)              score -= 15
  else                           score -= 5

  const pct = stock.percentChange
  if (pct >= 1 && pct <= 4)       score += 12
  else if (pct > 4)                score += 5
  else if (pct >= -1 && pct < 1)  score += 3
  else if (pct < -3)               score -= 10

  if (stock.foreignNet && stock.foreignNet > 0)           score += 8
  else if (stock.foreignNet && stock.foreignNet < -500000) score -= 5

  score = Math.max(0, Math.min(100, Math.round(score)))
  const signal: 'buy' | 'watch' | 'avoid' =
    score >= 65 ? 'buy' : score < 35 ? 'avoid' : 'watch'

  return { score, signal }
}

// ============================================================
// FILTER ENGINE
// ============================================================
export function passesHardGates(stock: StockData): boolean {
  if (stock.price <= 0) return false
  if (stock.volume > 0 && stock.volume < 100_000) return false
  if (stock.volatility > 20) return false
  return true
}
