from fastapi import APIRouter, Depends, Request
from app.core.auth import require_admin, require_enterprise_account, require_approved_enterprise
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["View Routes"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse, summary="Trang chủ")
@router.get("/TrangChu.html", response_class=HTMLResponse, include_in_schema=False)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="TrangChu.html")

@router.get("/map", response_class=HTMLResponse, summary="Bản đồ trạm xăng")
@router.get("/BanDo.html", response_class=HTMLResponse, include_in_schema=False)
async def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="BanDo.html")

@router.get("/login", response_class=HTMLResponse, summary="Đăng nhập")
@router.get("/DangNhap.html", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="DangNhap.html")

@router.get("/register", response_class=HTMLResponse, summary="Đăng ký")
@router.get("/DangKy.html", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="DangKy.html")

@router.get("/start", response_class=HTMLResponse, summary="Màn hình bắt đầu")
@router.get("/BatDau.html", response_class=HTMLResponse, include_in_schema=False)
async def start_page(request: Request):
    return templates.TemplateResponse(request=request, name="BatDau.html")

@router.get("/directions", response_class=HTMLResponse, summary="Chỉ đường")
@router.get("/ChiDuong.html", response_class=HTMLResponse, include_in_schema=False)
async def directions_page(request: Request):
    return templates.TemplateResponse(request=request, name="ChiDuong.html")

@router.get("/detail", response_class=HTMLResponse, summary="Chi tiết trạm xăng")
@router.get("/ChiTiet.html", response_class=HTMLResponse, include_in_schema=False)
async def detail_page(request: Request):
    return templates.TemplateResponse(request=request, name="ChiTiet.html")

@router.get("/transaction-detail", response_class=HTMLResponse, summary="Chi tiết giao dịch")
@router.get("/ChiTietGiaoDich.html", response_class=HTMLResponse, include_in_schema=False)
async def transaction_detail_page(request: Request):
    return templates.TemplateResponse(request=request, name="ChiTietGiaoDich.html")

@router.get("/news-detail", response_class=HTMLResponse, summary="Chi tiết tin tức")
@router.get("/ChiTietTinTuc.html", response_class=HTMLResponse, include_in_schema=False)
async def news_detail_page(request: Request):
    return templates.TemplateResponse(request=request, name="ChiTietTinTuc.html")

@router.get("/edit-profile", response_class=HTMLResponse, summary="Chỉnh sửa thông tin cá nhân")
@router.get("/ChinhSuaThongTin.html", response_class=HTMLResponse, include_in_schema=False)
async def edit_profile_page(request: Request):
    return templates.TemplateResponse(request=request, name="ChinhSuaThongTin.html")

@router.get("/logout", response_class=HTMLResponse, summary="Đăng xuất")
@router.get("/DangXuat.html", response_class=HTMLResponse, include_in_schema=False)
async def logout_page(request: Request):
    return templates.TemplateResponse(request=request, name="DangXuat.html")

@router.get("/change-password", response_class=HTMLResponse, summary="Đổi mật khẩu")
@router.get("/DoiMatKhau.html", response_class=HTMLResponse, include_in_schema=False)
async def change_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="DoiMatKhau.html")

@router.get("/fuel-prices", response_class=HTMLResponse, summary="Tra cứu giá xăng dầu")
@router.get("/GiaXangDau.html", response_class=HTMLResponse, include_in_schema=False)
async def fuel_prices_page(request: Request):
    return templates.TemplateResponse(request=request, name="GiaXangDau.html")

@router.get("/payment-failed", response_class=HTMLResponse, summary="Kết quả thanh toán thất bại")
@router.get("/KqThanhToanThatBai.html", response_class=HTMLResponse, include_in_schema=False)
async def payment_failed_page(request: Request):
    return templates.TemplateResponse(request=request, name="KqThanhToanThatBai.html")

@router.get("/history", response_class=HTMLResponse, summary="Lịch sử giao dịch")
@router.get("/LichSu.html", response_class=HTMLResponse, include_in_schema=False)
async def history_page(request: Request):
    return templates.TemplateResponse(request=request, name="LichSu.html")

@router.get("/account", response_class=HTMLResponse, summary="Quản lý tài khoản")
@router.get("/TaiKhoan.html", response_class=HTMLResponse, include_in_schema=False)
async def account_page(request: Request):
    return templates.TemplateResponse(request=request, name="TaiKhoan.html")

@router.get("/payment", response_class=HTMLResponse, summary="Thanh toán")
@router.get("/ThanhToan.html", response_class=HTMLResponse, include_in_schema=False)
async def payment_page(request: Request):
    return templates.TemplateResponse(request=request, name="ThanhToan.html")

@router.get("/news", response_class=HTMLResponse, summary="Tin tức")
@router.get("/TinTuc.html", response_class=HTMLResponse, include_in_schema=False)
async def news_page(request: Request):
    return templates.TemplateResponse(request=request, name="TinTuc.html")

@router.get("/location", response_class=HTMLResponse, summary="Chọn vị trí")
@router.get("/ViTri.html", response_class=HTMLResponse, include_in_schema=False)
async def location_page(request: Request):
    return templates.TemplateResponse(request=request, name="ViTri.html")

@router.get("/confirm-payment", response_class=HTMLResponse, summary="Xác nhận thanh toán")
@router.get("/XacNhanThanhToan.html", response_class=HTMLResponse, include_in_schema=False)
async def confirm_payment_page(request: Request):
    return templates.TemplateResponse(request=request, name="XacNhanThanhToan.html")

@router.get("/favorites", response_class=HTMLResponse, summary="Danh sách trạm xăng yêu thích")
@router.get("/YeuThich.html", response_class=HTMLResponse, include_in_schema=False)
async def favorites_page(request: Request):
    return templates.TemplateResponse(request=request, name="YeuThich.html")

@router.get("/doanh-nghiep", response_class=HTMLResponse, summary="Dashboard Doanh nghiệp Quản lý Trạm")
@router.get("/QuanLyTram.html", response_class=HTMLResponse, include_in_schema=False)
async def enterprise_page(request: Request, user=Depends(require_approved_enterprise)):
    return templates.TemplateResponse(request=request, name="QuanLyTram.html")


@router.get("/tiep-nhan-bom", response_class=HTMLResponse, summary="Tiếp nhận & Bơm Xăng (POS/Kiosk)")
@router.get("/TiepNhanBom.html", response_class=HTMLResponse, include_in_schema=False)
async def fueling_kiosk_page(request: Request, user=Depends(require_approved_enterprise)):
    return templates.TemplateResponse(request=request, name="TiepNhanBom.html")


@router.get("/TrangThaiDoanhNghiep.html", response_class=HTMLResponse, include_in_schema=False)
async def enterprise_status_page(request: Request, user=Depends(require_enterprise_account)):
    return templates.TemplateResponse(request=request, name="TrangThaiDoanhNghiep.html", context={"enterprise_status": user.doanh_nghiep.dn_trangthai})


@router.get("/QuanTriVien.html", response_class=HTMLResponse, include_in_schema=False)
async def administrator_page(request: Request, user=Depends(require_admin)):
    return templates.TemplateResponse(request=request, name="QuanTriVien.html")
