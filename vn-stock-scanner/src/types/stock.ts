// ============================================================
// Types cho VN Stock Scanner
// Anh sẽ dùng các type này xuyên suốt dự án
// ============================================================

/** Dữ liệu thô trả về từ TCBS API */
export interface TCBSStockRaw {
  ticker: string
  companyName?: string
  closePrice?: number
  referencePrice?: number
  priceChange?: number
  percentChange?: number
  matchingVolume?: number
  totalVolume?: number
  highPrice?: number
  lowPrice?: number
  openPrice?: number
  foreignBuyVolume?: number
  foreignSellVolume?: number
  marketCap?: number
  eps?: number
  pe?: number
}

/** Dữ liệu đã qua xử lý của 1 cổ phiếu */
export interface StockData {
  ticker: string
  companyName: string
  price: number          // Giá hiện tại (VNĐ)
  priceChange: number    // Thay đổi tuyệt đối
  percentChange: number  // % thay đổi
  volume: number         // Khối lượng khớp lệnh
  volatility: number     // % biến động trong phiên (high-low)/ref
  score: number          // Điểm 0-100
  signal: 'buy' | 'watch' | 'avoid'
  sector?: string
  marketCap?: number
  foreignNet?: number    // Mua ròng nước ngoài
}

/** Tổng quan thị trường */
export interface MarketOverview {
  vnindex: IndexData
  vn30: IndexData
  hnx: IndexData
  advancing: number   // Số mã tăng
  declining: number   // Số mã giảm
  unchanged: number   // Số mã đứng
  totalValue: number  // Tổng giá trị giao dịch HoSE (tỷ đồng)
  timestamp: string
}

export interface IndexData {
  value: number
  change: number
  percentChange: number
}

/** Kết quả từ API route của Next.js */
export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  timestamp: string
}

/** Tham số bộ lọc cổ phiếu */
export interface FilterParams {
  minVolume: number       // Khối lượng tối thiểu (triệu CP)
  minVolatility: number   // Biến động tối thiểu %
  maxVolatility: number   // Biến động tối đa %
  signal?: 'buy' | 'watch' | 'avoid' | 'all'
  sector?: string
}
