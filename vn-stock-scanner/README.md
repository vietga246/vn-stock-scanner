# 🇻🇳 VN Stock Scanner — Hướng dẫn cài đặt

## Cấu trúc project

```
vn-stock-scanner/
│
├── src/
│   ├── app/
│   │   ├── layout.tsx          ← HTML wrapper, fonts
│   │   ├── page.tsx            ← Trang dashboard chính (UI)
│   │   ├── globals.css         ← CSS toàn cục
│   │   │
│   │   └── api/                ← 🔑 API ROUTES (chạy server-side)
│   │       ├── market/
│   │       │   └── route.ts    ← GET /api/market (VN-Index, VN30)
│   │       ├── stocks/
│   │       │   └── route.ts    ← GET /api/stocks (quét toàn bộ)
│   │       └── stock/
│   │           └── [ticker]/
│   │               └── route.ts ← GET /api/stock/FPT (1 mã)
│   │
│   ├── lib/
│   │   ├── tcbs.ts             ← 🔑 Thư viện gọi TCBS API
│   │   └── tickers.ts          ← Danh sách mã cổ phiếu
│   │
│   └── types/
│       └── stock.ts            ← TypeScript types
│
├── package.json
├── next.config.js
├── tsconfig.json
└── tailwind.config.ts
```

---

## Bước 1 — Cài Node.js

Vào https://nodejs.org → tải bản **LTS** (khuyến nghị)
→ Cài xong, mở Terminal, gõ: `node --version`
→ Thấy số `v20.x.x` là thành công ✓

---

## Bước 2 — Tạo project Next.js

```bash
# Mở Terminal tại thư mục bạn muốn lưu project
npx create-next-app@14 vn-stock-scanner \
  --typescript \
  --tailwind \
  --app \
  --no-src-dir=false \
  --import-alias "@/*"

cd vn-stock-scanner
```

---

## Bước 3 — Copy code vào

Thay thế các file mặc định bằng file trong thư mục này:

```
src/types/stock.ts          → copy vào
src/lib/tcbs.ts             → copy vào
src/lib/tickers.ts          → copy vào
src/app/globals.css         → thay thế
src/app/layout.tsx          → thay thế
src/app/page.tsx            → thay thế
src/app/api/market/route.ts         → tạo mới
src/app/api/stocks/route.ts         → tạo mới
src/app/api/stock/[ticker]/route.ts → tạo mới (tạo folder [ticker])
```

---

## Bước 4 — Chạy thử

```bash
npm run dev
```

Mở trình duyệt: **http://localhost:3000**
→ Nhấn "BẮT ĐẦU QUÉT"
→ Đợi 10-15 giây → thấy dữ liệu thật! ✓

---

## Tại sao không bị CORS nữa?

```
[Browser] → gọi /api/stocks (cùng domain, không CORS)
               ↓
[Next.js Server] → gọi TCBS API (server-to-server, không CORS)
               ↓
[TCBS API] → trả dữ liệu về server
               ↓
[Next.js Server] → trả dữ liệu về browser
```

---

## Deploy lên Vercel (miễn phí)

```bash
# Cài Vercel CLI
npm i -g vercel

# Deploy
vercel

# Làm theo hướng dẫn, sau đó truy cập link được cấp
```

---

## Bước tiếp theo — Tích hợp Claude AI

Sau khi app chạy ổn, thêm file:
- `src/app/api/analyze/route.ts` → gửi top stocks lên Claude API
- Claude viết nhận xét thị trường bằng tiếng Việt
- Thêm `.env.local` với `ANTHROPIC_API_KEY=sk-ant-...`

---

## Câu hỏi thường gặp

**Q: TCBS API có bị khóa không?**
A: API không chính thức nhưng cộng đồng dùng ổn. Nếu bị block, thêm header
`Origin` và `Referer` trong `tcbs.ts` (đã có sẵn).

**Q: Dữ liệu có real-time không?**
A: Gần real-time — delay ~15 phút theo quy định HoSE.

**Q: Có thể thêm cổ phiếu HNX/UpCom không?**
A: Được, thêm tickers vào `src/lib/tickers.ts`.
