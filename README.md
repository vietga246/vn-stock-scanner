# 📊 VN Stock Scanner

Hệ thống quét dữ liệu chứng khoán Việt Nam tự động, chạy trên GitHub Actions và hiển thị qua web.

---

## 🏗️ Kiến trúc

```
GitHub Actions (Scheduler)
    │
    ├── 17:00 ICT T2-T6 → hose_daily.py  → cập nhật giá hàng ngày
    ├── Chủ nhật 08:00  → symbol.py      → cập nhật thông tin công ty
    └── (1 lần)         → hose.py        → bootstrap toàn bộ lịch sử
           │
           ▼
    SQLite (data/stock.db)
           │
           ▼
    export_json.py → data/exports/*.json
           │
           ▼
    Next.js / Vercel (đọc JSON từ repo hoặc API)
```

---

## 📁 Cấu trúc thư mục

```
├── scripts/
│   ├── hose.py           # Tải toàn bộ lịch sử (chạy 1 lần)
│   ├── hose_daily.py     # Cập nhật giá hàng ngày
│   ├── symbol.py         # Cập nhật thông tin công ty (weekly)
│   ├── export_json.py    # Export SQLite → JSON cho web
│   └── requirements.txt
│
├── .github/workflows/
│   ├── daily_prices.yml  # Cron 17:00 ICT T2-T6
│   ├── weekly_symbols.yml# Cron Chủ nhật 08:00 ICT
│   └── bootstrap.yml     # Manual — chạy 1 lần duy nhất
│
├── data/
│   ├── exports/          # JSON files (commit lên git)
│   │   ├── prices.json   # Giá 6 tháng gần nhất
│   │   ├── symbols.json  # Thông tin tất cả công ty
│   │   └── summary.json  # Dashboard: top gainers/losers/volume
│   └── stock.db          # SQLite (KHÔNG commit, dùng cache)
│
└── vn-stock-scanner/     # Next.js app (Vercel)
```

---

## 🚀 Setup lần đầu

### 1. Cấp quyền cho GitHub Actions push code

Vào **Settings → Actions → General → Workflow permissions** → chọn **Read and write permissions** → Save.

### 2. Chạy bootstrap để tải toàn bộ lịch sử

Vào **Actions → Bootstrap Full History → Run workflow**

> ⚠️ Workflow này chạy ~3-6 tiếng, chỉ cần chạy 1 lần duy nhất.

### 3. Sau đó các workflow tự động chạy theo lịch

| Workflow | Lịch | Mục đích |
|---|---|---|
| Daily Price Update | 17:00 ICT T2-T6 | Cập nhật giá cuối ngày |
| Weekly Symbol Update | CN 08:00 ICT | Cập nhật P/E, ROE, market cap |

---

## 🌐 Tích hợp vào Next.js / Vercel

Sau khi GitHub Actions commit JSON lên repo, Next.js đọc qua:

```typescript
// Đọc trực tiếp từ GitHub raw content
const res = await fetch(
  "https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports/summary.json"
);
const data = await res.json();
```

Hoặc dùng **Vercel ISR** (Incremental Static Regeneration) để cache:

```typescript
export async function getStaticProps() {
  const res = await fetch(".../summary.json");
  const data = await res.json();
  return {
    props: { data },
    revalidate: 3600, // revalidate mỗi 1 tiếng
  };
}
```

---

## 📊 Dữ liệu export

### `summary.json`
```json
{
  "generated_at": "2025-02-26T17:05:00",
  "latest_date": "2025-02-26",
  "top_gainers": [...],   // Top 10 tăng mạnh nhất ngày
  "top_losers": [...],    // Top 10 giảm mạnh nhất ngày
  "top_volume": [...],    // Top 10 khối lượng cao nhất
  "cheapest_90d": [...]   // Top 10 giá thấp nhất 90 ngày
}
```

### `prices.json`
Giá OHLCV của tất cả mã trong 6 tháng gần nhất, kèm thông tin công ty.

### `symbols.json`
Thông tin tổng quan: exchange, industry, market_cap, P/E, ROE, beta, v.v.

---

## ⚙️ Environment Variables (tuỳ chỉnh)

| Biến | Mặc định | Mô tả |
|---|---|---|
| `DB_PATH` | `data/stock.db` | Đường dẫn SQLite |
| `DAYS_LOOKBACK` | `7` | Số ngày lookback cho daily update |
| `SLEEP_BETWEEN` | `1.5` | Delay giữa các request (tránh rate limit) |
| `EXPORT_DIR` | `data/exports` | Thư mục xuất JSON |
| `LOOKBACK_DAYS` | `180` | Số ngày dữ liệu trong prices.json |
