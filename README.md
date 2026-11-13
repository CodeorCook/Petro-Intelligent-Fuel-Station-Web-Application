# Petro — Ứng dụng web thông minh cho người dùng trạm xăng

Petro là đề tài nghiên cứu khoa học **do nhóm thực hiện**. Ứng dụng hỗ trợ người lái xe tìm trạm, xem giá và tiện ích, dẫn đường và gửi yêu cầu đặt nhiên liệu. Nhân viên trạm tiếp nhận yêu cầu, ghi nhận lượng nhiên liệu đã bơm và xử lý thanh toán.

## Quy trình nghiệp vụ

1. Người lái xe tìm và lọc trạm trên bản đồ, xem tuyến đường rồi chọn trạm, nhiên liệu và định mức.
2. Trạm tiếp nhận yêu cầu, giữ chỗ nhiên liệu, ghi nhận lượng bơm thực tế và lập hóa đơn. Worker xử lý yêu cầu chờ đã hết hạn.
3. Khách theo dõi trạng thái và xem biên lai. Hệ thống hỗ trợ tiền mặt và tích hợp VietQR/Casso, với kiểm tra tài khoản nhận, số tiền và mã giao dịch khi đối soát.

Nhóm cũng xây dựng quy trình đăng ký và xét duyệt trạm, quản lý bồn/trụ bơm, và phân biệt giá nhiên liệu công bố với giá bán tại trạm. Phần đóng góp cá nhân nên được mô tả riêng trong CV theo phạm vi thực tế.

## Kiến trúc

- `app/` chứa FastAPI, các lớp nghiệp vụ, mô hình dữ liệu và giao diện HTML/CSS/JavaScript.
- Leaflet hiển thị bản đồ. OSRM cung cấp tuyến đường, còn giao diện dùng GPS để cập nhật chỉ dẫn.
- PostgreSQL 16 lưu dữ liệu nghiệp vụ. Supervisor quản lý worker hết hạn yêu cầu.
- `tests/` chứa các bài kiểm tra tập trung cho onboarding, startup và hợp đồng thanh toán.
- [Schema PostgreSQL](proposals/phase58/local_dev_schema.sql) và [dữ liệu danh mục thử nghiệm](proposals/phase58/local_dev_starter.sql) mô tả nền dữ liệu của bản development.

## Thiết lập thử nghiệm trên Windows

Cần Python 3.13 và PostgreSQL 16 chỉ lắng nghe trên loopback. Từ thư mục gốc, cài các thư viện bằng PowerShell.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Khi có môi trường thử nghiệm được duyệt, tạo database `DB_TRAMXANG` mới và rỗng, nạp schema rồi starter ở trên, và điền `DATABASE_URL` trong `.env` cục bộ. Starter chứa schema và danh mục, chưa có tài khoản hay trạm demo.

**Giới hạn của bản portfolio:** luồng `init-dev` cần gói cấu hình và công cụ release từ nhóm, gồm hồ sơ deployment dùng chung và các helper onboarding/worker liên quan. Bản xuất này thiếu các thành phần đó nên chưa thể khởi động độc lập. Khi nhóm cung cấp gói tương ứng và startup guard xác nhận cấu hình local, dùng hai lệnh dưới đây. Profile thử nghiệm khóa thanh toán ngân hàng.

```powershell
.\.venv\Scripts\python.exe scripts/onboard_petro_local.py init-dev
.\.venv\Scripts\python.exe scripts/run_petro_dev.py
```

Sau khi Start All báo sẵn sàng, mở [http://127.0.0.1:8000](http://127.0.0.1:8000). Các minh chứng nghiên cứu chứa trong kho nội bộ của nhóm cần được duyệt riêng trước khi chia sẻ.
