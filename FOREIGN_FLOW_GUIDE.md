# Hướng dẫn: Lấy đủ dữ liệu foreign_net_7D và foreign_net_30D

## Vấn đề hiện tại

`foreign_net_7D == foreign_net_30D` trong StockModal vì DB chỉ có **1 ngày data**.

### Nguyên nhân kỹ thuật

```
Trading.price_board()  →  real-time only  →  không có historical API
         ↓
price_board_snapshot   →  chỉ lưu ngày hiện tại
         ↓
foreign_trading table  →  1 row/ngày (thêm dần sau mỗi phiên)
         ↓
foreign_net_7D  = SUM(7 ngày gần nhất)
foreign_net_30D = SUM(30 ngày gần nhất)
→ Khi chỉ có 1 ngày: 7D == 30D
```

**Không thể backfill dữ liệu quá khứ** — vnstock không cung cấp historical
foreign flow API. Data chỉ tích lũy dần theo mỗi phiên giao dịch.

---

## Timeline để có đủ dữ liệu

| Điều kiện | Cần | Ước tính |
|-----------|-----|----------|
| `foreign_net_7D` chính xác | 7 phiên giao dịch | ~2 tuần |
| `foreign_net_30D` chính xác | 30 phiên giao dịch | ~6–7 tuần |

**Điều kiện bắt buộc:** Workflow `② Daily Collect` phải chạy thành công
**mỗi ngày T2–T6 lúc 15:15 ICT** (sau phiên ATC đóng cửa).

---

## Checklist setup

### Bước 1 — Kiểm tra secrets

Đảm bảo `VNSTOCK_API_KEY` đã được set trong:
```
GitHub repo → Settings → Secrets and variables → Actions → VNSTOCK_API_KEY
```

### Bước 2 — Kiểm tra trạng thái hiện tại

Chạy workflow `⓪ Backfill Foreign Flow` với `check_only = true`:
```
Actions → ⓪ Backfill Foreign Flow → Run workflow → ✅ check_only=true
```

Xem output để biết hiện có bao nhiêu ngày data và còn thiếu bao nhiêu.

### Bước 3 — Đảm bảo Daily Collect chạy đúng

Vào Actions → `② Daily Collect` → xem các lần chạy gần nhất:
- ✅ Tất cả thành công → đang tích lũy đúng
- ❌ Có lần thất bại → chạy lại manual:
  ```
  Actions → ② Daily Collect → Run workflow → Run workflow
  ```

### Bước 4 — Nếu muốn re-aggregate từ snapshot cũ

Nếu `price_board_snapshot` đã có nhiều ngày trong DB nhưng `foreign_trading`
chưa được aggregate, chạy:
```
Actions → ② Daily Collect → Run workflow
  → days_lookback = 35
  → Run workflow
```

---

## Theo dõi tiến độ

Mỗi lần `② Daily Collect` chạy xong, xem log của step
**🌍 Cập nhật giao dịch khối ngoại**:

```
foreign_trading: 5 ngày (2026-03-03 → 2026-03-07)
7D window:  5/7  | 30D window: 5/30
foreign_net_7D:  ⏳ cần thêm 2 ngày
foreign_net_30D: ⏳ cần thêm 25 ngày
```

---

## Hiển thị trên frontend trong thời gian chờ

Trong khi chưa đủ data, frontend (`StockModal → Smart Money / Flow`) sẽ:

- Khi `7D == 30D` → hiện nhãn **"Khối ngoại (tích lũy)"** thay vì "7D"
- Ẩn dòng "Flow Trend 30D" (không có giá trị thêm)
- Khi đủ data → tự động hiện lại đúng nhãn "Khối ngoại 7D" và "Flow Trend 30D"

Không cần thay đổi code frontend khi data đã đủ.

---

## Câu hỏi thường gặp

**Q: Có cách nào có ngay 30 ngày data không?**

Không. `Trading.price_board()` chỉ là real-time snapshot — không có
endpoint lịch sử cho foreign trading. Đây là giới hạn của vnstock/VCI.

**Q: Tại sao không dùng API khác như SSI, TCBS?**

Các source khác cũng không có public API cho historical foreign flow
theo ngày. Chỉ VCI có real-time foreign data qua price_board.

**Q: DB cache bị mất thì sao?**

GitHub Actions cache có TTL 7 ngày nếu không được access. Nếu bị mất,
data sẽ tích lũy lại từ đầu. Để tránh mất data lâu dài, cân nhắc
commit `foreign_trading` table dưới dạng SQLite dump hàng tuần.
