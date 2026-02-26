// ============================================================
// lib/tcbs.ts — Multi-source với fallback tự động
// Thứ tự thử: VNDirect → SSI → Mock data
// Lý do: Không có API nào 100% ổn định, cần fallback
// ============================================================

import { StockData, MarketOverview, IndexData } from '@/types/stock'

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0',
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
}

// ============================================================
// SOURCE 1: VNDirect — stock_prices endpoint (có docs rõ ràng)
// ============================================================
async function fetchFromVNDirect(tickers: string[]): Promise<StockData[]> {
  const results: StockData[] = []
  const BATCH = 20
  const today = new Date().toISOString().split('T')[0]

  for (let i = 0; i < tickers.length; i += BATCH) {
    const batch = tickers.slice(i, i + BATCH)
    const q = batch.map(t => `code:${t}`).join('~')

    try {
      const url = `https://finfo-api.vndirect.com.vn/v4/stock_prices?sort=date&size=${BATCH}&page=1&q=${encodeURIComponent(q + `~date:gte:${today}~date:lte:${today}`)}`
      const res = await fetch(url, {
        headers: HEADERS,
        cache: 'no-store',
        signal: AbortSignal.timeout(8000),
      })

      if (!res.ok) continue
      const json = await res.json()
      const items: Record<string, unknown>[] = json.data ?? []

      items.forEach(d => {
        const close = Number(d.close ?? 0)
        const ref = Number(d.adClose ?? d.open ?? close)
        const high = Number(d.high ?? close)
        const low = Number(d.low ?? close)
        const vol = Number(d.nmVolume ?? d.volume ?? 0)
        const pctChange = ref > 0 ? ((close - ref) / ref) * 100 : 0
        const volatility = ref > 0 ? parseFloat(((high - low) / ref * 100).toFixed(2)) : 0

        results.push({
          ticker: String(d.code ?? '').toUpperCase(),
          companyName: String(d.code ?? ''),
          price: close,
          priceChange: close - ref,
          percentChange: pctChange,
          volume: vol,
          volatility,
          score: 0,
          signal: 'watch',
        })
      })
    } catch { continue }

    if (i + BATCH < tickers.length) {
      await new Promise(r => setTimeout(r, 150))
    }
  }

  return results
}

// ============================================================
// SOURCE 2: SSI iBoard API — public, không cần auth
// ============================================================
async function fetchFromSSI(tickers: string[]): Promise<StockData[]> {
  const results: StockData[] = []

  try {
    // SSI trả về bảng giá toàn sàn trong 1 request
    const res = await fetch(
      'https://iboard.ssi.com.vn/dchart/api/1.1/defaultAllStocks',
      {
        headers: {
          ...HEADERS,
          'Origin': 'https://iboard.ssi.com.vn',
          'Referer': 'https://iboard.ssi.com.vn/',
        },
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      }
    )

    if (!res.ok) return []
    const json = await res.json()

    // SSI trả về array hoặc object tùy version
    const items: Record<string, unknown>[] = Array.isArray(json)
      ? json
      : (json.data ?? json.items ?? [])

    const tickerSet = new Set(tickers.map(t => t.toUpperCase()))

    items.forEach((d: Record<string, unknown>) => {
      const code = String(d.s ?? d.code ?? d.StockCode ?? '').toUpperCase()
      if (!tickerSet.has(code)) return

      const close = Number(d.c ?? d.close ?? d.lastPrice ?? d.MatchPrice ?? 0)
      const ref = Number(d.r ?? d.ref ?? d.RefPrice ?? close)
      const high = Number(d.h ?? d.high ?? d.HighPrice ?? close)
      const low = Number(d.l ?? d.low ?? d.LowPrice ?? close)
      const vol = Number(d.v ?? d.volume ?? d.TotalQtty ?? 0)
      const pctChange = ref > 0 ? ((close - ref) / ref) * 100 : 0
      const volatility = ref > 0 ? parseFloat(((high - low) / ref * 100).toFixed(2)) : 0

      results.push({
        ticker: code,
        companyName: String(d.n ?? d.name ?? d.StockName ?? code),
        price: close,
        priceChange: close - ref,
        percentChange: pctChange,
        volume: vol,
        volatility,
        score: 0,
        signal: 'watch',
        foreignNet: Number(d.fBVol ?? 0) - Number(d.fSVol ?? 0),
      })
    })
  } catch { /* fallback tiếp */ }

  return results
}

// ============================================================
// SOURCE 3: Mock data — luôn hoạt động, dùng khi API down
// ============================================================
function getMockStocks(tickers: string[]): StockData[] {
  const mockPrices: Record<string, { p: number; c: number; v: number }> = {
    FPT:  { p: 145200, c: 2.1,  v: 8200000  },
    VCB:  { p: 92400,  c: 0.8,  v: 5100000  },
    HPG:  { p: 28600,  c: 3.4,  v: 22400000 },
    MBB:  { p: 27300,  c: 1.2,  v: 12600000 },
    ACB:  { p: 24900,  c: 0.6,  v: 7800000  },
    TCB:  { p: 53600,  c: -0.5, v: 6300000  },
    VNM:  { p: 77600,  c: -1.1, v: 2100000  },
    GAS:  { p: 82100,  c: 0.9,  v: 1800000  },
    SSI:  { p: 35300,  c: 4.2,  v: 9700000  },
    VPB:  { p: 21600,  c: -0.9, v: 14200000 },
    STB:  { p: 38900,  c: 2.8,  v: 8900000  },
    BID:  { p: 48300,  c: 0.4,  v: 4600000  },
    MSN:  { p: 85100,  c: -1.8, v: 2900000  },
    VHM:  { p: 42700,  c: 1.5,  v: 7100000  },
    REE:  { p: 68600,  c: 1.9,  v: 1500000  },
    GMD:  { p: 74300,  c: 3.1,  v: 1200000  },
    DGC:  { p: 89100,  c: 0.2,  v: 1800000  },
    PNJ:  { p: 115100, c: -0.4, v: 1400000  },
    CTG:  { p: 39600,  c: 0.1,  v: 3800000  },
    HDB:  { p: 31200,  c: 1.7,  v: 5200000  },
  }

  return tickers.map(ticker => {
    const m = mockPrices[ticker.toUpperCase()]
    if (!m) return null
    const pct = m.c
    const price = m.p
    const priceChange = price * pct / 100
    const volatility = Math.abs(pct) + Math.random() * 1.5
    return {
      ticker: ticker.toUpperCase(),
      companyName: ticker,
      price,
      priceChange,
      percentChange: pct,
      volume: m.v,
      volatility: parseFloat(volatility.toFixed(2)),
      score: 0,
      signal: 'watch' as const,
    }
  }).filter(Boolean) as StockData[]
}

// ============================================================
// PUBLIC: fetchMultipleStocks — thử từng nguồn, fallback tự động
// ============================================================
export async function fetchMultipleStocks(
  tickers: string[],
  onProgress?: (done: number, total: number) => void
): Promise<StockData[]> {
  onProgress?.(10, 100)

  // Thử VNDirect trước
  console.log('[fetchMultipleStocks] Thử VNDirect...')
  let results = await fetchFromVNDirect(tickers)
  onProgress?.(40, 100)

  if (results.length > 5) {
    console.log(`[fetchMultipleStocks] VNDirect OK: ${results.length} mã`)
    onProgress?.(tickers.length, tickers.length)
    return results
  }

  // Fallback sang SSI
  console.log('[fetchMultipleStocks] VNDirect ít data, thử SSI...')
  results = await fetchFromSSI(tickers)
  onProgress?.(80, 100)

  if (results.length > 5) {
    console.log(`[fetchMultipleStocks] SSI OK: ${results.length} mã`)
    onProgress?.(tickers.length, tickers.length)
    return results
  }

  // Fallback cuối: mock data
  console.log('[fetchMultipleStocks] API đều lỗi, dùng mock data')
  results = getMockStocks(tickers)
  onProgress?.(tickers.length, tickers.length)
  return results
}

// ============================================================
// PUBLIC: fetchSingleStock
// ============================================================
export async function fetchSingleStock(ticker: string): Promise<StockData | null> {
  const results = await fetchMultipleStocks([ticker])
  return results[0] ?? null
}

// ============================================================
// PUBLIC: fetchMarketOverview
// ============================================================
export async function fetchMarketOverview(): Promise<MarketOverview> {
  try {
    const today = new Date().toISOString().split('T')[0]
    const url = `https://finfo-api.vndirect.com.vn/v4/stock_prices?sort=date&size=3&page=1&q=${encodeURIComponent(`code:VNINDEX~code:VN30~code:HNXINDEX~date:gte:${today}~date:lte:${today}`)}`

    const res = await fetch(url, {
      headers: HEADERS,
      cache: 'no-store',
      signal: AbortSignal.timeout(8000),
    })

    if (res.ok) {
      const json = await res.json()
      const items: Record<string, unknown>[] = json.data ?? []

      const findIndex = (code: string): IndexData => {
        const item = items.find(d => String(d.code ?? '').toUpperCase() === code)
        const close = Number(item?.close ?? 0)
        const ref = Number(item?.adClose ?? item?.open ?? close)
        return {
          value: close,
          change: close - ref,
          percentChange: ref > 0 ? ((close - ref) / ref) * 100 : 0,
        }
      }

      return {
        vnindex: findIndex('VNINDEX'),
        vn30: findIndex('VN30'),
        hnx: findIndex('HNXINDEX'),
        advancing: 0, declining: 0, unchanged: 0, totalValue: 0,
        timestamp: new Date().toISOString(),
      }
    }
  } catch { /* fallback */ }

  // Fallback: giá trị rỗng nhưng không crash
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
