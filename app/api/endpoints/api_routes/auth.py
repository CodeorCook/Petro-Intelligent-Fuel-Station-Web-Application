from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    SESSION_COOKIE_SECURE,
    create_session_token,
    get_current_user,
    get_current_user_optional,
    get_user_role,
    get_login_redirect,
    require_customer,
    verify_password,
)
from app.database.session import get_db
from app.models.request import YeuCauDoXang
from app.models.user import KhachHang, LoaiPhuongTien, NguoiDung, PhuongTien
from app.schemas.auth import (
    CustomerRegistrationRequest, CustomerRegistrationResponse,
    EnterpriseRegistrationRequest, EnterpriseRegistrationResponse,
)
from app.services.auth_service import register_customer, register_enterprise

router = APIRouter(prefix="/api/auth", tags=["Authentication & Roles"])


@router.post("/register", status_code=201, response_model=CustomerRegistrationResponse)
def register(payload: CustomerRegistrationRequest, db: Session = Depends(get_db)):
    return CustomerRegistrationResponse(username=register_customer(db, payload))


@router.post("/register/enterprise", status_code=201, response_model=EnterpriseRegistrationResponse)
def register_enterprise_account(payload: EnterpriseRegistrationRequest, db: Session = Depends(get_db)):
    return EnterpriseRegistrationResponse(username=register_enterprise(db, payload))


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, description="Tên đăng nhập hoặc Email")
    password: str = Field(min_length=1, max_length=128, description="Mật khẩu")
    expected_role: Literal["KHACH_HANG", "DOANH_NGHIEP", "QUAN_TRI_VIEN"] | None = None


class UpdateProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32, description="Họ và tên")
    email: str = Field(min_length=3, max_length=64, description="Email")
    phone: str = Field(min_length=8, max_length=11, description="Số điện thoại")
    gender: Optional[str] = Field(default=None, description="Nam hoặc Nữ")


class AddVehicleRequest(BaseModel):
    pt_bienso: str = Field(min_length=4, max_length=12, description="Biển số xe (VD: 65A-123.45)")
    pt_ten: str = Field(min_length=1, max_length=32, description="Tên gợi nhớ (VD: Honda Vision)")
    lpt_ma: str = Field(min_length=4, max_length=8, description="Mã loại phương tiện (LPT00001, ...)")


class UserProfileResponse(BaseModel):
    username: str
    name: str
    email: str
    phone: str
    role: Literal["KHACH_HANG", "DOANH_NGHIEP", "QUAN_TRI_VIEN"]
    role_label: str
    redirect_url: str
    stations_count: Optional[int] = None
    gender: str | None = None
    enterprise_status: Literal["CHUA_HOAN_THIEN", "CHO_DUYET", "CAN_BO_SUNG", "TU_CHOI", "DA_DUYET", "TAM_KHOA"] | None = None


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    login_id = payload.username.strip()
    user = db.scalars(
        select(NguoiDung)
        .options(
            selectinload(NguoiDung.doanh_nghiep),
            selectinload(NguoiDung.khach_hang),
            selectinload(NguoiDung.quan_tri_vien),
        )
        .where(
            or_(
                NguoiDung.nd_tendangnhap == login_id,
                func.lower(func.trim(NguoiDung.nd_email)) == login_id.lower(),
            )
        )
    ).first()

    if not user or not verify_password(payload.password, user.nd_matkhau):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác"
        )

    role_code, role_label = get_user_role(user)

    # Optional role check if user selected a specific role tab
    if payload.expected_role and payload.expected_role != role_code:
        role_names = {
            "DOANH_NGHIEP": "Doanh nghiệp",
            "KHACH_HANG": "Khách hàng",
            "QUAN_TRI_VIEN": "Quản trị viên",
        }
        actual_name = role_names.get(role_code, role_code)
        expected_name = role_names.get(payload.expected_role, payload.expected_role)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tài khoản '{user.nd_tendangnhap}' thuộc nhóm [{actual_name}], vui lòng chọn đúng nhóm [{expected_name}] để đăng nhập."
        )

    # Determine redirect target
    redirect_url = get_login_redirect(user)

    # Create signed session token
    token = create_session_token({
        "username": user.nd_tendangnhap,
        "name": user.nd_ten,
        "role": role_code,
    })

    # Set HTTP-only Cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=SESSION_COOKIE_SECURE,
    )

    return {
        "status": "success",
        "message": f"Đăng nhập thành công với vai trò {role_label}",
        "user": {
            "username": user.nd_tendangnhap,
            "name": user.nd_ten,
            "email": user.nd_email,
            "phone": user.nd_sodienthoai,
            "role": role_code,
            "role_label": role_label,
            "redirect_url": redirect_url,
            "enterprise_status": user.doanh_nghiep.dn_trangthai if role_code == "DOANH_NGHIEP" else None,
        }
    }


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    role_code, role_label = get_user_role(user)

    stations_count = 0
    if role_code == "DOANH_NGHIEP":
        from app.models.station import TramXang
        stations_count = len(db.scalars(select(TramXang).where(TramXang.nd_tendangnhap == user.nd_tendangnhap)).all())

    redirect_url = get_login_redirect(user)

    return {
        "username": user.nd_tendangnhap,
        "name": user.nd_ten,
        "email": user.nd_email,
        "phone": user.nd_sodienthoai,
        "gender": "Nam" if user.nd_gioitinh else "Nữ",
        "role": role_code,
        "role_label": role_label,
        "redirect_url": redirect_url,
        "stations_count": stations_count,
        "enterprise_status": user.doanh_nghiep.dn_trangthai if role_code == "DOANH_NGHIEP" else None,
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {
        "status": "success",
        "message": "Đăng xuất thành công",
        "redirect_url": "/DangNhap.html"
    }


# ==========================================================
# CẬP NHẬT HỒ SƠ CÁ NHÂN
# ==========================================================
@router.put("/profile")
def update_profile(
    payload: UpdateProfileRequest,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clean_email = payload.email.strip().lower()
    if clean_email != user.nd_email.strip().lower():
        existing_email_user = db.scalars(
            select(NguoiDung).where(
                NguoiDung.nd_email == clean_email,
                NguoiDung.nd_tendangnhap != user.nd_tendangnhap,
            )
        ).first()
        if existing_email_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email này đã được sử dụng bởi tài khoản khác"
            )

    user.nd_ten = payload.name.strip()
    user.nd_email = clean_email
    user.nd_sodienthoai = payload.phone.strip()
    if payload.gender is not None:
        user.nd_gioitinh = True if payload.gender.strip().lower() in ["nam", "true", "1"] else False

    db.commit()
    db.refresh(user)

    role_code, role_label = get_user_role(user)
    return {
        "status": "success",
        "message": "Cập nhật thông tin cá nhân thành công",
        "user": {
            "username": user.nd_tendangnhap,
            "name": user.nd_ten,
            "email": user.nd_email,
            "phone": user.nd_sodienthoai,
            "gender": "Nam" if user.nd_gioitinh else "Nữ",
            "role": role_code,
            "role_label": role_label,
        }
    }


# ==========================================================
# QUẢN LÝ PHƯƠNG TIỆN KHÁCH HÀNG
# ==========================================================
@router.get("/vehicle-types")
def get_vehicle_types(db: Session = Depends(get_db)):
    types = db.scalars(select(LoaiPhuongTien).order_by(LoaiPhuongTien.lpt_ma)).all()
    return [
        {
            "lpt_ma": t.lpt_ma.strip(),
            "lpt_ten": t.lpt_ten.strip(),
        }
        for t in types
    ]


@router.get("/vehicles")
def get_user_vehicles(
    user: NguoiDung = Depends(require_customer),
    db: Session = Depends(get_db),
):
    vehicles = db.scalars(
        select(PhuongTien)
        .options(selectinload(PhuongTien.loai_phuong_tien))
        .where(PhuongTien.nd_tendangnhap == user.nd_tendangnhap)
        .order_by(PhuongTien.pt_bienso)
    ).all()

    return [
        {
            "pt_bienso": v.pt_bienso.strip(),
            "pt_ten": v.pt_ten.strip(),
            "lpt_ma": v.lpt_ma.strip(),
            "lpt_ten": v.loai_phuong_tien.lpt_ten.strip() if v.loai_phuong_tien else "Khác",
        }
        for v in vehicles
    ]


@router.post("/vehicles")
def add_or_update_vehicle(
    payload: AddVehicleRequest,
    user: NguoiDung = Depends(require_customer),
    db: Session = Depends(get_db),
):
    clean_plate = payload.pt_bienso.strip().upper()
    if len(clean_plate) > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Biển số xe không được vượt quá 12 ký tự"
        )

    # Kiểm tra loại xe hợp lệ
    lpt = db.get(LoaiPhuongTien, payload.lpt_ma.strip())
    if not lpt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Loại phương tiện '{payload.lpt_ma}' không tồn tại"
        )

    # Đảm bảo người dùng có bản ghi trong bảng khach_hang
    kh = db.get(KhachHang, user.nd_tendangnhap)
    if not kh:
        kh = KhachHang(nd_tendangnhap=user.nd_tendangnhap)
        db.add(kh)
        db.flush()

    # Kiểm tra biển số xe đã tồn tại hay chưa
    existing = db.scalars(
        select(PhuongTien).where(PhuongTien.pt_bienso.like(f"{clean_plate}%"))
    ).first()

    if existing:
        if existing.nd_tendangnhap != user.nd_tendangnhap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Biển số xe '{clean_plate}' đã được đăng ký bởi người dùng khác"
            )
        # Cập nhật thông tin xe nếu là của chính người dùng
        existing.pt_ten = payload.pt_ten.strip()
        existing.lpt_ma = payload.lpt_ma.strip()
        db.commit()
        db.refresh(existing)
        return {
            "status": "success",
            "message": f"Cập nhật phương tiện {clean_plate} thành công",
            "vehicle": {
                "pt_bienso": existing.pt_bienso.strip(),
                "pt_ten": existing.pt_ten.strip(),
                "lpt_ma": existing.lpt_ma.strip(),
                "lpt_ten": lpt.lpt_ten.strip(),
            }
        }

    # Thêm xe mới
    new_vehicle = PhuongTien(
        pt_bienso=clean_plate,
        pt_ten=payload.pt_ten.strip(),
        lpt_ma=payload.lpt_ma.strip(),
        nd_tendangnhap=user.nd_tendangnhap,
    )
    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)

    return {
        "status": "success",
        "message": f"Thêm phương tiện {clean_plate} thành công",
        "vehicle": {
            "pt_bienso": new_vehicle.pt_bienso.strip(),
            "pt_ten": new_vehicle.pt_ten.strip(),
            "lpt_ma": new_vehicle.lpt_ma.strip(),
            "lpt_ten": lpt.lpt_ten.strip(),
        }
    }


@router.delete("/vehicles/{pt_bienso}")
def delete_vehicle(
    pt_bienso: str,
    user: NguoiDung = Depends(require_customer),
    db: Session = Depends(get_db),
):
    clean_plate = pt_bienso.strip().upper()
    vehicle = db.scalars(
        select(PhuongTien).where(
            PhuongTien.pt_bienso.like(f"{clean_plate}%"),
            PhuongTien.nd_tendangnhap == user.nd_tendangnhap,
        )
    ).first()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy phương tiện biển số '{clean_plate}' trong tài khoản của bạn"
        )

    # Gỡ liên kết các đơn đổ xăng liên quan để xóa phương tiện an toàn (không bị chặn bởi đơn cũ/đang xử lý)
    related_requests = db.scalars(
        select(YeuCauDoXang).where(YeuCauDoXang.pt_bienso.like(f"{clean_plate}%"))
    ).all()
    for req in related_requests:
        req.pt_bienso = None
    db.flush()

    db.delete(vehicle)
    db.commit()

    return {
        "status": "success",
        "message": f"Đã xóa phương tiện {clean_plate} thành công",
    }
