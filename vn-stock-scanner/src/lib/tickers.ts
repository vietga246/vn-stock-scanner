// ============================================================
// lib/tickers.ts — Danh sách mã cổ phiếu VN
//
// Anh có thể chỉnh sửa danh sách này tùy ý
// VN30: bluechip → ưu tiên cao
// EXTRA: cổ phiếu phổ biến khác
// ============================================================

/** VN30 — 30 bluechip lớn nhất HoSE */
export const VN30: string[] = [
  'ACB', 'BCM', 'BID', 'BVH', 'CTG',
  'FPT', 'GAS', 'GVR', 'HDB', 'HPG',
  'MBB', 'MSN', 'MWG', 'NVL', 'PDR',
  'PLX', 'PNJ', 'POW', 'SAB', 'SHB',
  'SSB', 'SSI', 'STB', 'TCB', 'TPB',
  'VCB', 'VHM', 'VIB', 'VIC', 'VJC',
  'VNM', 'VPB', 'VRE', 'VTP', 'TCH',
]

/** Cổ phiếu vừa — thanh khoản tốt, được theo dõi nhiều */
export const MID_CAP: string[] = [
  'DGC', 'KDH', 'DXG', 'HDG', 'REE',
  'GMD', 'PVT', 'QNS', 'DHC', 'EVF',
  'DBC', 'HAH', 'PPC', 'IDC', 'VSH',
  'HNG', 'AGR', 'BSR', 'VEA', 'DCM',
  'DPM', 'GEX', 'HBC', 'FCN', 'PTB',
  'VGC', 'TDC', 'NLG', 'CII', 'LCG',
]

/** Ngân hàng — sector riêng, quan trọng với VN-Index */
export const BANKS: string[] = [
  'VCB', 'BID', 'CTG', 'MBB', 'ACB',
  'TCB', 'VPB', 'HDB', 'STB', 'TPB',
  'SHB', 'SSB', 'VIB', 'LPB', 'MSB',
  'OCB', 'ABB', 'EIB', 'NAB', 'KLB',
]

/** Tổng hợp tất cả, loại trùng */
export const ALL_TICKERS: string[] = [
  ...new Set([...VN30, ...MID_CAP, ...BANKS])
]

/** Mapping sector đơn giản (mở rộng sau) */
export const SECTOR_MAP: Record<string, string> = {
  // Ngân hàng
  VCB: 'Ngân hàng', BID: 'Ngân hàng', CTG: 'Ngân hàng',
  MBB: 'Ngân hàng', ACB: 'Ngân hàng', TCB: 'Ngân hàng',
  VPB: 'Ngân hàng', HDB: 'Ngân hàng', STB: 'Ngân hàng',
  TPB: 'Ngân hàng', SHB: 'Ngân hàng', SSB: 'Ngân hàng',
  VIB: 'Ngân hàng',
  // Bất động sản
  VHM: 'BĐS', VIC: 'BĐS', NVL: 'BĐS', PDR: 'BĐS',
  VRE: 'BĐS', KDH: 'BĐS', DXG: 'BĐS', NLG: 'BĐS',
  // Thép & Vật liệu
  HPG: 'Thép', VGC: 'VL Xây dựng',
  // Công nghệ
  FPT: 'Công nghệ',
  // Tiêu dùng
  VNM: 'Tiêu dùng', MSN: 'Tiêu dùng', SAB: 'Tiêu dùng',
  MWG: 'Tiêu dùng', PNJ: 'Tiêu dùng',
  // Năng lượng
  GAS: 'Năng lượng', PLX: 'Năng lượng', POW: 'Năng lượng',
  BSR: 'Năng lượng', PVT: 'Năng lượng',
  // Chứng khoán
  SSI: 'Chứng khoán', VCI: 'Chứng khoán',
}
