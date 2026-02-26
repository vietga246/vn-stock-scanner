// ============================================================
// lib/tcbs.ts — Thư viện gọi TCBS API
//
// File này chạy trên SERVER (Next.js API routes)
// → Không bị CORS block
// → Anh có thể mở rộng thêm endpoints sau
// ============================================================

import { TCBSStockRaw, StockData, MarketOverview, IndexData } from '@/types/stock'

const TCBS_BASE = 'https://apipubaws.tcbs.com.vn'

// Timeout cho mỗi request (ms)
const REQUEST_TIMEOUT = 8000

// ============================================================
// HELPER: Fetch với timeout
// ============================================================
async function fetchWithTimeout(url: string, timeoutMs = REQUEST_TIMEOUT): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        // TCBS cần header này để không trả về lỗi 403
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
        'Origin': 'https://tcinvest.tcbs.com.vn',
        'Referer': 'https://tcinvest.tcbs.com.vn/',
      },
      cache: 'no-store', // Luôn lấy dữ liệu mới nhất
    })
    return res
  } finally {
    clearTimeout(timer)
  }
}

// ============================================================
// API 1: Lấy tổng quan thị trường (VN-Index, VN30, HNX)
// Endpoint: /stock-insight/v1/index/overview
// ============================================================
export async function fetchMarketOverview(): Promise<MarketOverview> {
  const url = `${TCBS_BASE}/stock-insight/v1/index/overview`

  const res = await fetchWithTimeout(url)
  if (!res.ok) throw new Error(`TCBS Market API lỗi: HTTP ${res.status}`)

  const data = await res.json()

  // Hàm helper tìm index theo code
  const findIndex = (code: string): IndexData => {
    const item = data.find((d: { code: string }) => d.code === code)
    return {
      value: item?.indexValue ?? 0,
      change: item?.indexChange ?? 0,
      percentChange: item?.percentChange ?? 0,
    }
  }

  return {
    vnindex: findIndex('VNINDEX'),
    vn30: findIndex('VN30'),
    hnx: findIndex('HNX'),
    // Những field này cần endpoint riêng, để mặc định trước
    advancing: 0,
    declining: 0,
    unchanged: 0,
    totalValue: 0,
    timestamp: new Date().toISOString(),
  }
}

// ============================================================
// API 2: Lấy dữ liệu 1 cổ phiếu
// Endpoint: /stock-insight/v1/stock/ticker-overview/{ticker}
// ============================================================
export async function fetchSingleStock(ticker: string): Promise<StockData | null> {
  try {
    const url = `${TCBS_BASE}/stock-insight/v1/stock/ticker-overview/${ticker.toUpperCase()}`
    const res = await fetchWithTimeout(url, 5000) // Timeout ngắn hơn cho từng mã

    if (!res.ok) return null

    const d: TCBSStockRaw = await res.json()

    // Tính biến động trong phiên
    const high = d.highPrice ?? 0
    const low = d.lowPrice ?? 0
    const ref = d.referencePrice ?? d.closePrice ?? 1
    const volatility = ref > 0 ? parseFloat(((high - low) / ref * 100).toFixed(2)) : 0

    const price = d.closePrice ?? d.referencePrice ?? 0
    const priceChange = d.priceChange ?? 0
    const percentChange = d.percentChange ?? 0
    const volume = d.matchingVolume ?? d.totalVolume ?? 0

    const stock: StockData = {
      ticker: ticker.toUpperCase(),
      companyName: d.companyName ?? ticker,
      price,
      priceChange,
      percentChange,
      volume,
      volatility,
      score: 0, // Tính sau bằng scoreStock()
      signal: 'watch',
      marketCap: d.marketCap,
      foreignNet: (d.foreignBuyVolume ?? 0) - (d.foreignSellVolume ?? 0),
    }

    return stock
  } catch {
    // Không throw, chỉ return null để batch fetch tiếp tục
    return null
  }
}

// ============================================================
// API 3: Lấy nhiều cổ phiếu cùng lúc (batch)
// Dùng Promise.allSettled để 1 mã lỗi không ảnh hưởng mã khác
// ============================================================
export async function fetchMultipleStocks(
  tickers: string[],
  onProgress?: (done: number, total: number) => void
): Promise<StockData[]> {
  const BATCH_SIZE = 8  // Gọi 8 mã song song, tránh quá tải API
  const DELAY_MS = 150  // Nghỉ 150ms giữa các batch

  const results: StockData[] = []

  for (let i = 0; i < tickers.length; i += BATCH_SIZE) {
    const batch = tickers.slice(i, i + BATCH_SIZE)

    const batchResults = await Promise.allSettled(
      batch.map(ticker => fetchSingleStock(ticker))
    )

    batchResults.forEach(result => {
      if (result.status === 'fulfilled' && result.value) {
        results.push(result.value)
      }
    })

    // Báo cáo tiến độ
    onProgress?.(Math.min(i + BATCH_SIZE, tickers.length), tickers.length)

    // Nghỉ giữa batch (trừ batch cuối)
    if (i + BATCH_SIZE < tickers.length) {
      await new Promise(resolve => setTimeout(resolve, DELAY_MS))
    }
  }

  return results
}

// ============================================================
// SCORING ENGINE
// Chấm điểm 0-100 cho mỗi cổ phiếu
// ============================================================
export function scoreStock(stock: StockData): { score: number; signal: 'buy' | 'watch' | 'avoid' } {
  let score = 50 // Điểm base

  // === TIÊU CHÍ 1: Thanh khoản (quan trọng nhất) ===
  // KLGD tối thiểu 1 triệu cổ phiếu/phiên để dễ vào/ra lệnh
  const volM = stock.volume / 1_000_000
  if (volM >= 10) score += 20      // Rất thanh khoản
  else if (volM >= 3)  score += 12  // Thanh khoản tốt
  else if (volM >= 1)  score += 5   // Chấp nhận được
  else score -= 20                   // Thanh khoản kém → penalize nặng

  // === TIÊU CHÍ 2: Biến động phiên (volatility) ===
  // Quá phẳng = ít cơ hội. Quá wild = rủi ro cao
  const vol = stock.volatility
  if (vol >= 2 && vol <= 5)  score += 15  // Sweet spot
  else if (vol > 5 && vol <= 8) score += 8
  else if (vol > 8)          score -= 15  // Quá biến động
  else                       score -= 5   // Quá phẳng

  // === TIÊU CHÍ 3: Momentum giá ===
  const pct = stock.percentChange
  if (pct >= 1 && pct <= 4)   score += 12  // Tăng khỏe, chưa quá mua
  else if (pct > 4)            score += 5   // Tăng mạnh nhưng cẩn thận
  else if (pct >= -1 && pct < 1) score += 3 // Trung tính
  else if (pct < -3)           score -= 10  // Giảm mạnh

  // === TIÊU CHÍ 4: Mua ròng nước ngoài ===
  if (stock.foreignNet && stock.foreignNet > 0) score += 8
  else if (stock.foreignNet && stock.foreignNet < -500_000) score -= 5

  // === Clamp 0-100 ===
  score = Math.max(0, Math.min(100, Math.round(score)))

  // === Phân loại tín hiệu ===
  const signal: 'buy' | 'watch' | 'avoid' =
    score >= 65 ? 'buy' :
    score < 35  ? 'avoid' : 'watch'

  return { score, signal }
}

// ============================================================
// FILTER ENGINE
// Lọc hard gates trước khi chấm điểm
// ============================================================
export function passesHardGates(stock: StockData): boolean {
  // Gate 1: Giá > 0 (loại mã không có dữ liệu)
  if (stock.price <= 0) return false

  // Gate 2: Khối lượng tối thiểu 500k cp/phiên
  if (stock.volume < 500_000) return false

  // Gate 3: Biến động không cực đoan (tránh mã bị kiểm soát đột biến)
  if (stock.volatility > 15) return false

  return true
}
