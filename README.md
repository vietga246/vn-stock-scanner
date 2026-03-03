# 📊 VN Stock Scanner

Hệ thống thu thập, phân tích và scoring chứng khoán Việt Nam tự động.
Chạy hoàn toàn trên **GitHub Actions** — không cần server, không tốn phí hosting.

---

## 🏗️ Kiến trúc tổng quan

```
GitHub Actions (Scheduler)
        │
        ├── [② Daily 17:00]  collectors/   ──→  data/db/stock.db
        ├── [③ Daily 17:30]  processors/   ──→  data/exports/*.json
        ├── [④ Weekly CN]    collectors/   ──→  data/db/stock.db
        └── [① Manual]      bootstrap      ──→  data/db/stock.db
                                                       │
                                              data/exports/*.json
                                                       │
                                              Next.js / Vercel (frontend)
```

---

## 📁 Cấu trúc thư mục

```
vn-stock-scanner/
│
├── pipeline/                          # Toàn bộ logic backend
│   ├── requirements.txt
│   │
│   ├── collectors/                    # Lấy dữ liệu từ vnstock API
│   │   ├── bootstrap_prices.py        # Tải toàn bộ lịch sử giá (1 lần)
│   │   ├── daily_prices.py            # Cập nhật giá OHLCV hàng ngày
│   │   ├── daily_foreign_flow.py      # Giao dịch khối ngoại & tự doanh
│   │   ├── weekly_symbols.py          # Thông tin công ty, ngành, sàn
│   │   ├── quarterly_financials.py    # Báo cáo tài chính theo quý
│   │   └── weekly_insider_deals.py    # Giao dịch cổ đông nội bộ
│   │
│   ├── processors/                    # Tính toán, phân tích
│   │   ├── technical_indicators.py    # MA, RSI, MACD, Bollinger, ATR
│   │   ├── scoring_engine.py          # Composite score 0–100
│   │   └── sector_analysis.py         # Heatmap ngành, dòng tiền
│   │
│   ├── exporters/                     # Xuất dữ liệu cho frontend
│   │   └── export_financials.py       # SQLite → JSON (prices, symbols, screener)
│   │
│   └── utils/                         # Tiện ích, debug, bảo trì
│       ├── inspect_db.py              # Xem schema & sample data
│       ├── debug_fields.py            # Debug field names từ API
│       ├── vacuum_db.py               # Compact DB
│       └── reset_financials_meta.py   # Reset để force re-fetch tài chính
│
├── .github/workflows/                 # GitHub Actions — đặt tên có số thứ tự
│   ├── 1_bootstrap.yml                # ① Chạy 1 lần để khởi tạo
│   ├── 2_daily_collect.yml            # ② 17:00 ICT T2-T6 — lấy giá & dòng tiền
│   ├── 3_daily_process.yml            # ③ 17:30 ICT T2-T6 — scoring & sector
│   ├── 4_weekly_update.yml            # ④ CN 08:00 ICT — tài chính & symbols
│   └── 5_maintenance.yml             # ⑤ Manual — debug, vacuum, export
│
├── data/
│   ├── db/                            # ← KHÔNG commit (trong .gitignore)
│   │   └── stock.db                   # SQLite — lưu qua GitHub Actions cache
│   │
│   └── exports/                       # ← COMMIT (static JSON cho frontend)
│       ├── prices.json                # Giá OHLCV 6 tháng gần nhất
│       ├── symbols.json               # Thông tin 700+ công ty
│       ├── screener.json              # Screener + composite score
│       ├── sectors.json               # Heatmap ngành + dòng tiền
│       └── summary.json              # Dashboard: top gainers/losers
│
└── README.md
```

---

## 🚀 Hướng dẫn Setup

### Bước 1 — Cấp quyền cho GitHub Actions push code
```
Settings → Actions → General → Workflow permissions
→ Chọn "Read and write permissions" → Save
```

### Bước 2 — Thêm API key (tuỳ chọn, tăng rate limit)
```
Settings → Secrets and variables → Actions → New repository secret
→ Name: VNSTOCK_API_KEY
→ Value: <api key của anh>
```

### Bước 3 — Bootstrap lần đầu
```
Actions → ① Bootstrap — Tải toàn bộ lịch sử → Run workflow
```
> ⚠️ Workflow này chạy ~3-6 tiếng, chỉ cần chạy **1 lần duy nhất**.

### Bước 4 — Các workflow tự động chạy theo lịch

| # | Workflow | Lịch chạy | Mục đích |
|---|---|---|---|
| ② | Daily Collect | 17:00 ICT T2-T6 | Giá OHLCV + khối ngoại |
| ③ | Daily Process | 17:30 ICT T2-T6 | Technical + Scoring + Sectors |
| ④ | Weekly Update | CN 08:00 ICT | Symbols + Tài chính (tuần chẵn) |
| ⑤ | Maintenance | Manual | Debug, vacuum, export thủ công |

---

## 📊 Dữ liệu xuất ra (data/exports/)

### `screener.json` — Bộ lọc cổ phiếu
```json
{
  "generated_at": "2026-03-03T10:30:00Z",
  "total": 706,
  "screener": [
    {
      "symbol": "VCB",
      "name": "Ngân hàng TMCP Ngoại thương Việt Nam",
      "industry": "Ngân hàng",
      "composite_score": 72.4,
      "fundamental_score": 81.2,
      "smart_money_score": 68.5,
      "momentum_score": 63.1,
      "technical_score": 70.8,
      "tier": "A",
      "rank": 1,
      "roe": 18.5, "pe": 11.2, "revenue_growth": 22.1,
      "rsi14": 58.3, "trend_short": 1,
      "foreign_net_7d": 125.4
    }
  ]
}
```

### `sectors.json` — Phân tích ngành
```json
{
  "sectors": [
    {
      "name": "Ngân hàng",
      "symbol_count": 28,
      "avg_composite_score": 65.2,
      "foreign_net_7d": 1250.5,
      "money_flow_rank": 1,
      "top_stocks": ["VCB", "BID", "CTG", "MBB", "TCB"]
    }
  ],
  "rotation_signal": {
    "accumulating": ["Ngân hàng", "Công nghệ"],
    "distributing": ["Thép", "Phân bón"],
    "hot_sectors": ["Ngân hàng", "Bất động sản", "Dược phẩm"]
  }
}
```

---

## 🧮 Scoring Model

**Composite Score = 0–100**

| Trụ cột | Trọng số | Chỉ số |
|---|---|---|
| Fundamental | 35% | ROE, ROA, Revenue Growth, Net Margin, PE, D/E |
| Smart Money | 30% | Net Foreign Flow 7d/30d, Prop Trading 7d |
| Momentum | 20% | Price 5d/20d, Volume Surge, RS vs VN-Index |
| Technical | 15% | RSI(14), MACD, Trend (MA5 vs MA20) |

**Tier:**
- 🟢 **A** ≥ 70 điểm — Cơ hội tốt
- 🔵 **B** 55–69 — Theo dõi
- ⚪ **C** 40–54 — Trung bình
- 🟡 **D** 25–39 — Yếu
- 🔴 **F** < 25 — Tránh

---

## 🗄️ Database Schema (SQLite)

```
stock_prices          — Giá OHLCV hàng ngày
symbols               — Thông tin công ty
foreign_trading       — Giao dịch khối ngoại
prop_trading          — Giao dịch tự doanh
financials_ratio      — PE, PB, ROE, ROA, margins... (theo quý)
financials_income     — Doanh thu, lợi nhuận... (theo quý)
financials_balance    — Tài sản, nợ, vốn chủ... (theo quý)
financials_cashflow   — Dòng tiền CFO/CFI/CFF (theo quý)
technical_indicators  — MA, RSI, MACD, Bollinger (daily)
stock_scores          — Composite score + ranks (daily)
sector_scores         — Aggregate theo ngành (daily)
```

---

## 🔧 Chạy thủ công (local)

```bash
cd vn-stock-scanner
pip install -r pipeline/requirements.txt

# Set biến môi trường
export DB_PATH=data/db/stock.db
export EXPORT_DIR=data/exports
export VNSTOCK_API_KEY=your_key_here   # optional

mkdir -p data/db data/exports

# Chạy theo thứ tự
python pipeline/collectors/daily_prices.py
python pipeline/collectors/daily_foreign_flow.py
python pipeline/processors/technical_indicators.py
python pipeline/processors/scoring_engine.py
python pipeline/processors/sector_analysis.py
```

---

## 📅 Roadmap

- [x] **Phase 1** — Data pipeline (giá, tài chính, khối ngoại)
- [x] **Phase 2** — Scoring engine + Sector analysis
- [x] **Phase 3** — AI analyst (OpenAI/Claude tự động phân tích top picks)
- [ ] **Phase 4** — Next.js frontend (dashboard, screener, sector heatmap)
- [ ] **Phase 5** — Alert system (Telegram khi score đột biến)

---

## 🤖 AI Analyst (Phase 3)

Module phân tích tự động bằng AI, hỗ trợ cả OpenAI và Anthropic Claude.

### Setup

```bash
# Thêm API key vào GitHub Secrets
Settings → Secrets → New repository secret
→ OPENAI_API_KEY hoặc ANTHROPIC_API_KEY
→ AI_PROVIDER = "openai" hoặc "anthropic"
```

### Outputs

| File | Mô tả |
|------|-------|
| `ai_analysis.json` | Phân tích AI với top picks, reasoning |
| `daily_report.md` | Báo cáo hàng ngày dạng Markdown |
| `daily_report.html` | Báo cáo HTML cho email/web |
| `stocks/*.md` | Chi tiết từng cổ phiếu |

### Chạy thủ công

```bash
# Với AI API
export OPENAI_API_KEY=your_key
python pipeline/ai_analyst/ai_analyst.py

# Không có API (fallback rule-based)
python pipeline/ai_analyst/ai_analyst.py

# Chỉ tạo reports
python pipeline/ai_analyst/report_generator.py
```

### Workflow

```
Actions → ⑥ AI Analysis → Run workflow
```

Chạy tự động sau Daily Process hoặc vào Chủ nhật 19:00 ICT.
