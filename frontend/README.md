# 🚀 VN Stock Scanner - Frontend

Dashboard phân tích cổ phiếu Việt Nam với giao diện Cyber Terminal.

## ✨ Features

- **📊 Real-time Screener**: Hiển thị 700+ cổ phiếu với scoring và ranking
- **🎯 AI Analysis**: Phân tích tự động với khuyến nghị MUA/BÁN/GIỮ
- **📈 Industry Flow**: Theo dõi dòng tiền khối ngoại theo ngành
- **🔍 Smart Search**: Tìm kiếm theo mã CK, tên công ty, ngành
- **📱 Responsive**: Tương thích mobile và desktop
- **🌙 Cyber Theme**: Giao diện dark mode chuyên nghiệp

## 🏗️ Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Icons**: Lucide React
- **Data**: Fetch từ GitHub (static JSON)

## 📁 Project Structure

```
vn-stock-frontend/
├── app/
│   ├── globals.css      # Global styles
│   ├── layout.tsx       # Root layout
│   └── page.tsx         # Home page
├── components/
│   ├── Dashboard.tsx    # Main dashboard
│   ├── IndustryFlow.tsx # Industry panel
│   ├── Sparkline.tsx    # Price chart
│   └── StockModal.tsx   # Detail modal
├── lib/
│   ├── api.ts          # Data fetching
│   ├── analysis.ts     # AI analysis logic
│   └── types.ts        # TypeScript types
└── pipeline/
    └── ai_analyst/      # Backend AI scripts
```

## 🚀 Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn

### Installation

```bash
# Clone repo
git clone https://github.com/vietga246/vn-stock-scanner.git
cd vn-stock-scanner/frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### Build for Production

```bash
npm run build
npm start
```

## 📊 Data Source

Frontend fetches data từ GitHub repo:
- `screener.json` - Danh sách cổ phiếu với scores
- `sectors.json` - Phân tích ngành
- `prices.json` - Lịch sử giá 6 tháng
- `ai_analysis.json` - AI analysis results

Data được cập nhật tự động bởi GitHub Actions:
- **Daily 17:00 ICT**: Giá & dòng tiền
- **Daily 17:30 ICT**: Scoring & sectors
- **Weekly**: AI analysis

## 🎨 UI Design

### Color Palette

| Color | Hex | Usage |
|-------|-----|-------|
| Primary | `#00d4ff` | Highlights, links |
| Success | `#00ff88` | Positive, buy |
| Danger | `#ff3366` | Negative, sell |
| Warning | `#ffcc00` | Hold, neutral |
| Background | `#05080a` | Main bg |
| Card | `#0a0f14` | Card bg |
| Border | `#1e2832` | Borders |

### Scoring Model

| Score | Tier | Recommendation |
|-------|------|----------------|
| ≥75 | A | STRONG BUY |
| 65-74 | A/B | BUY |
| 55-64 | B | HOLD |
| 45-54 | C | SELL |
| <45 | D/F | STRONG SELL |

## 🔧 Configuration

### Environment Variables

```env
# Optional - for server-side rendering
NEXT_PUBLIC_DATA_URL=https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports
```

### Vercel Deployment

1. Connect repo to Vercel
2. Set root directory to `frontend` (if needed)
3. Deploy

## 📝 AI Analysis Output Format

```json
{
  "generated_at": "2024-01-01T10:00:00Z",
  "model": "rule-based",
  "analyses": {
    "VCB": {
      "symbol": "VCB",
      "recommendation": "STRONG_BUY",
      "summary": "Nhận định...",
      "highlights": [
        {"text": "Điểm tích cực", "type": "positive"}
      ],
      "risks": [
        {"text": "Rủi ro", "type": "negative"}
      ],
      "fundamental_view": "...",
      "technical_view": "...",
      "flow_view": "..."
    }
  }
}
```

## 🤝 Contributing

1. Fork the repo
2. Create feature branch
3. Commit changes
4. Push to branch
5. Open Pull Request

## 📄 License

MIT License - See LICENSE file

## 🙏 Acknowledgments

- [vnstock](https://github.com/thinh-vu/vnstock) - Data source
- [Lucide](https://lucide.dev/) - Icons
- [Tailwind CSS](https://tailwindcss.com/) - Styling

---

**Powered by VN Stock Scanner** 🇻🇳
