"""
trading_calendar.py — Lịch giao dịch HOSE/HNX

Cung cấp:
  - Danh sách ngày lễ Việt Nam (2024-2030)
  - is_trading_day(date) → bool
  - get_trading_days(n, end_date) → list[str]  — n phiên giao dịch thực tế
  - trading_date_range(n_days, end_date) → (start_str, end_str)
    dùng trực tiếp trong WHERE date BETWEEN ... AND ...

Ngày lễ theo Bộ LĐ-TB&XH: Tết Nguyên Đán, 30/4, 1/5, Quốc khánh 2/9, 1/1
Nếu lễ rơi T7/CN → được nghỉ bù ngày kế tiếp (áp dụng từ 2007).
HOSE/HNX không giao dịch T7 và CN.
"""

from datetime import date, timedelta
from typing import Optional

# ─── NGÀY LỄ CỐ ĐỊNH (YYYY-MM-DD) ─────────────────────────────────────────
# Bao gồm nghỉ bù nếu lễ trùng cuối tuần.
# Tết Nguyên Đán thay đổi hàng năm — cần cập nhật thủ công.

_VN_HOLIDAYS: set[str] = {
    # ── 2024 ──
    "2024-01-01",  # Tết Dương lịch
    "2024-02-08", "2024-02-09", "2024-02-10", "2024-02-11",
    "2024-02-12", "2024-02-13", "2024-02-14",  # Tết Giáp Thìn (29/12 ÂL – mùng 5)
    "2024-04-18",  # Giỗ Tổ Hùng Vương (10/3 ÂL)
    "2024-04-30",  # Ngày Giải phóng
    "2024-05-01",  # Quốc tế Lao động
    "2024-09-02",  # Quốc khánh
    "2024-09-03",  # Nghỉ bù (2/9 rơi thứ Hai → nghỉ bù thứ Ba theo QĐ)

    # ── 2025 ──
    "2025-01-01",  # Tết Dương lịch
    "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-01-31", "2025-02-03",  # Tết Ất Tỵ (nghỉ 28/12 ÂL – mùng 5, có bù)
    "2025-04-07",  # Giỗ Tổ Hùng Vương (10/3 ÂL)
    "2025-04-30",  # Ngày Giải phóng
    "2025-05-01",  # Quốc tế Lao động
    "2025-05-02",  # Nghỉ bù (1/5 rơi thứ Năm → không bù, 30/4 thứ Tư)
    "2025-09-01",  # Nghỉ bù Quốc khánh (2/9 rơi thứ Ba)
    "2025-09-02",  # Quốc khánh

    # ── 2026 ──
    "2026-01-01",  # Tết Dương lịch
    "2026-01-02",  # Nghỉ bù (1/1 rơi thứ Năm)
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-23",  # Tết Bính Ngọ (nghỉ 29/12 ÂL – mùng 5, có bù)
    "2026-03-30",  # Giỗ Tổ Hùng Vương (10/3 ÂL)
    "2026-04-30",  # Ngày Giải phóng
    "2026-05-01",  # Quốc tế Lao động
    "2026-09-02",  # Quốc khánh
    "2026-09-03",  # Nghỉ bù

    # ── 2027 ──
    "2027-01-01",  # Tết Dương lịch
    "2027-02-05", "2027-02-06", "2027-02-07", "2027-02-08",
    "2027-02-09", "2027-02-10",  # Tết Đinh Mùi
    "2027-04-19",  # Giỗ Tổ Hùng Vương
    "2027-04-30",  # Ngày Giải phóng
    "2027-05-01",  # Quốc tế Lao động
    "2027-09-02",  # Quốc khánh

    # ── 2028 ──
    "2028-01-01",  # Tết Dương lịch
    "2028-01-26", "2028-01-27", "2028-01-28", "2028-01-29",
    "2028-01-30", "2028-01-31",  # Tết Mậu Thân
    "2028-04-06",  # Giỗ Tổ Hùng Vương
    "2028-05-01",  # Quốc tế Lao động (30/4 rơi CN → bù)
    "2028-05-02",  # Nghỉ bù 30/4
    "2028-09-02",  # Quốc khánh
    "2028-09-04",  # Nghỉ bù

    # ── 2029 ──
    "2029-01-01",  # Tết Dương lịch
    "2029-02-12", "2029-02-13", "2029-02-14", "2029-02-15",
    "2029-02-16", "2029-02-17",  # Tết Kỷ Dậu
    "2029-04-25",  # Giỗ Tổ Hùng Vương
    "2029-04-30",  # Ngày Giải phóng
    "2029-05-01",  # Quốc tế Lao động
    "2029-09-02",  # Quốc khánh
    "2029-09-03",  # Nghỉ bù

    # ── 2030 ──
    "2030-01-01",  # Tết Dương lịch
    "2030-02-02", "2030-02-03", "2030-02-04", "2030-02-05",
    "2030-02-06", "2030-02-07",  # Tết Canh Tuất
    "2030-04-15",  # Giỗ Tổ Hùng Vương
    "2030-04-30",  # Ngày Giải phóng
    "2030-05-01",  # Quốc tế Lao động
    "2030-09-02",  # Quốc khánh
}


def is_trading_day(d: date) -> bool:
    """Trả về True nếu d là ngày giao dịch HOSE/HNX."""
    if d.weekday() >= 5:          # 5=T7, 6=CN
        return False
    if d.strftime("%Y-%m-%d") in _VN_HOLIDAYS:
        return False
    return True


def get_trading_days(n: int, end_date: Optional[date] = None) -> list[str]:
    """
    Trả về danh sách n ngày giao dịch gần nhất (kể cả end_date nếu là ngày GD).
    Kết quả theo thứ tự tăng dần (cũ → mới).

    Ví dụ: get_trading_days(7) → ['2026-03-02', '2026-03-03', ..., '2026-03-09']
    """
    if end_date is None:
        end_date = date.today()

    days = []
    cursor = end_date
    while len(days) < n:
        if is_trading_day(cursor):
            days.append(cursor.strftime("%Y-%m-%d"))
        cursor -= timedelta(days=1)

    days.reverse()
    return days


def trading_date_cutoff(n_trading_days: int, end_date: Optional[date] = None) -> str:
    """
    Trả về ngày bắt đầu (string YYYY-MM-DD) để dùng trong:
        WHERE date >= trading_date_cutoff(7)

    Trả về ngày GD cũ nhất trong n phiên gần nhất.
    """
    days = get_trading_days(n_trading_days, end_date)
    return days[0] if days else (end_date or date.today()).strftime("%Y-%m-%d")


def get_trading_date_list_sql(n_trading_days: int, end_date: Optional[date] = None) -> str:
    """
    Trả về chuỗi SQL IN clause: ('2026-03-02','2026-03-03',...) để dùng trong:
        WHERE date IN <result>

    An toàn hơn cutoff khi DB có dữ liệu thưa (missing dates vẫn không bị đếm).
    """
    days = get_trading_days(n_trading_days, end_date)
    quoted = ", ".join(f"'{d}'" for d in days)
    return f"({quoted})"
