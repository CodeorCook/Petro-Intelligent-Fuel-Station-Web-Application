import re
import secrets
import string
import hmac
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from typing import Literal
from app.core.fuel_order import ordered_fuels
from app.services.station_readiness import customer_readiness
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select, func
from sqlalchemy.orm import Session, selectinload

from app.core.auth import require_workflow_actor, get_current_user_optional, require_doanh_nghiep, require_khach_hang
from app.database.session import get_db
from app.models import (
    ChiTietGiaoDich, ChiTietYeuCau, Gia, GiaoDich, NhienLieu,
    PhuongTien, ThoiDiem, TramXang, TrangThai, TrangThaiXacNhan, YeuCauDoXang,
)
from app.models.user import NguoiDung
from app.services.station_inventory_service import deduct_tank_fuel, get_tank_by_fuel, refill_tank
from app.services.station_visibility import get_public_station
from app.services.casso_integration import qr_fields, payment_setting, beneficiary, parse_casso_events, CassoPayloadConflict
from app.core.workflow_status import (REQUEST_WAITING,REQUEST_ACCEPTED,REQUEST_PUMPING,REQUEST_COMPLETED,REQUEST_REJECTED,
    PAYMENT_SUCCEEDED,PAYMENT_PROCESSING,PAYMENT_FAILED,view as workflow_view,validate_catalog,cancel_unavailable,advance_request,advance_payment)

router = APIRouter(prefix="/api", tags=["Payment & Refueling Workflow"])

from app.core.operational_mode import POSTGRESQL_OPERATIONS
if POSTGRESQL_OPERATIONS:
    from app.services import operational_service as ops
    from app.schemas.operations import Start as PumpAcceptInput, Reserve, Closure
    from app.services import request_lifecycle as lifecycle
else:
    class PumpAcceptInput(BaseModel):
        pump_id: str | None = None


def _require_request_access(db: Session, req: YeuCauDoXang, user: NguoiDung) -> None:
    station = db.get(TramXang, req.tx_ma)
    if req.nd_tendangnhap != user.nd_tendangnhap and (
        station is None or station.nd_tendangnhap != user.nd_tendangnhap
    ):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập yêu cầu này")


if POSTGRESQL_OPERATIONS:
    @router.post('/workflow/fuel-requests/{yc_ma}/accept')
    def accept_reserve(yc_ma:str,payload:Reserve,db:Session=Depends(get_db),user:NguoiDung=Depends(require_doanh_nghiep)):
        return ops.execute(db,lambda:ops.accept(db,yc_ma,user,payload.maximum_liters))

    @router.post('/workflow/fuel-requests/{yc_ma}/reject')
    def reject_waiting(yc_ma:str,payload:Closure,db:Session=Depends(get_db),user:NguoiDung=Depends(require_doanh_nghiep)):
        return ops.execute(db,lambda:lifecycle.reject(db,yc_ma,user,payload.reason))


def _require_station_owner(db: Session, tx_ma: str, user: NguoiDung) -> None:
    station = db.get(TramXang, tx_ma)
    if station is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng")
    if station.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không có quyền quản lý trạm này")


def _require_transaction_access(db: Session, gd: GiaoDich, user: NguoiDung) -> None:
    if gd.nd_tendangnhap == user.nd_tendangnhap:
        return
    tx_ma = gd.tx_ma or (gd.yeu_cau_do_xang.tx_ma if gd.yeu_cau_do_xang else None)
    station = db.get(TramXang, tx_ma) if tx_ma else None
    if station is None or station.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập giao dịch này")


def _latest_station_price(db: Session, tx_ma: str, nl_ma: str) -> Gia:
    price = db.scalars(
        select(Gia).where(Gia.tx_ma == tx_ma, Gia.nl_ma == nl_ma)
        .order_by(desc(Gia.ngaygio))
    ).first()
    if price is None:
        raise HTTPException(status_code=400, detail="Chưa có giá nhiên liệu cho trạm này")
    return price


def _generate_code(db: Session, model: type[Any], prefix: str, pk_name: str) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(100):
        code = prefix + "".join(secrets.choice(alphabet) for _ in range(6))
        if db.get(model, code) is None:
            return code
    raise HTTPException(status_code=500, detail=f"Không thể tạo mã duy nhất cho {prefix}")


# ==========================================================
# 1. API Lấy thông tin trạm và phương tiện phục vụ trang đặt xăng
# ==========================================================
@router.get("/workflow/station-info/{tx_ma}")
def get_station_workflow_info(
    tx_ma: str,
    db: Session = Depends(get_db),
    current_user: Optional[NguoiDung] = Depends(get_current_user_optional),
):
    station = get_public_station(db,tx_ma.strip())
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng")

    # Lấy bảng giá nhiên liệu của trạm
    prices = db.scalars(
        select(Gia).options(selectinload(Gia.nhien_lieu))
        .where(Gia.tx_ma == station.tx_ma).order_by(desc(Gia.ngaygio))
    ).all()

    fuels = []
    if prices:
        seen_fuels = set()
        for p in prices:
            if p.nl_ma in seen_fuels:
                continue
            seen_fuels.add(p.nl_ma)
            fuels.append({
                "nl_ma": p.nl_ma.strip(),
                "nl_ten": p.nhien_lieu.nl_ten if p.nhien_lieu else "Nhiên liệu",
                "dongia": float(p.dongia),
            })

    # Lấy danh sách xe: ưu tiên xe của chính người dùng nếu đang đăng nhập
    if current_user and current_user.khach_hang is not None:
        user_vehicles = db.scalars(
            select(PhuongTien).where(PhuongTien.nd_tendangnhap == current_user.nd_tendangnhap)
        ).all()
        vehicles = user_vehicles
    else:
        vehicles = []

    vehicle_list = [
        {"pt_bienso": v.pt_bienso.strip(), "pt_ten": v.pt_ten, "nd_tendangnhap": v.nd_tendangnhap.strip()}
        for v in vehicles
    ]

    return {
        "tx_ma": station.tx_ma.strip(),
        "tx_ten": station.tx_ten,
        "tx_diachi": station.tx_diachi,
        "fuels": ordered_fuels(fuels, lambda f: f['nl_ma']),
        "vehicles": vehicle_list,
    }


@router.get('/workflow/station-info/{tx_ma}/readiness')
def station_customer_readiness(tx_ma: str, fuel_id: str = Query(min_length=1,max_length=8),
    mode: Literal['SO_LIT','SO_TIEN','DO_DAY_BINH']='DO_DAY_BINH',
    liters: Decimal | None = Query(default=None,gt=0,lt=1000000),
    budget: Decimal | None = Query(default=None,gt=0,lt=100000000),
    db: Session=Depends(get_db)):
    if get_public_station(db,tx_ma) is None:
        raise HTTPException(404,'Không tìm thấy trạm xăng')
    return customer_readiness(db,tx_ma,fuel_id,mode,liters,budget)


# ==========================================================
# 2. KHÁCH HÀNG: Tạo Yêu Cầu Đổ Xăng
# ==========================================================
class FuelRequestInput(BaseModel):
    tx_ma: str = Field(min_length=1, max_length=8)
    nl_ma: str = Field(min_length=1, max_length=8)
    pt_bienso: str = Field(min_length=1, max_length=12)
    hinh_thuc_do_xang: str = Field(default="SO_TIEN")  # SO_TIEN, SO_LIT, DO_DAY_BINH
    so_tien: Optional[float] = None
    so_lit: Optional[float] = None
    nd_tendangnhap: Optional[str] = None  # Legacy clients; validated against the session.
    yc_ma: Optional[str] = Field(default=None,pattern=r'^YC[A-Z0-9]{6}$')


@router.post("/workflow/fuel-request", status_code=status.HTTP_201_CREATED)
def create_fuel_request(
    payload: FuelRequestInput,
    db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    if payload.nd_tendangnhap and payload.nd_tendangnhap.strip() != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không thể tạo yêu cầu cho khách hàng khác")
    tx_ma = payload.tx_ma.strip()
    station = get_public_station(db,tx_ma)
    if not station:
        raise HTTPException(status_code=404, detail="Trạm xăng không tồn tại")

    fuel = db.get(NhienLieu, payload.nl_ma.strip())
    if not fuel:
        raise HTTPException(status_code=404, detail="Nhiên liệu không tồn tại")

    _latest_station_price(db, tx_ma, fuel.nl_ma)

    yc_ma = payload.yc_ma or _generate_code(db, YeuCauDoXang, "YC", "yc_ma")

    # Tính toán dự kiến
    so_lit_est = None
    so_tien_est = None
    if payload.hinh_thuc_do_xang == "SO_TIEN" and payload.so_tien:
        so_tien_est = Decimal(str(payload.so_tien))
    elif payload.hinh_thuc_do_xang == "SO_LIT" and payload.so_lit:
        so_lit_est = Decimal(str(payload.so_lit))

    plate_clean = payload.pt_bienso.strip().upper()
    if not plate_clean:
        raise HTTPException(status_code=400, detail="Vui lòng chọn phương tiện đã đăng ký")
    vehicle = db.get(PhuongTien, plate_clean)
    if not vehicle:
        raise HTTPException(status_code=400, detail="Phương tiện chưa được đăng ký trong tài khoản")
    if vehicle.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Phương tiện không thuộc khách hàng hiện tại")

    if POSTGRESQL_OPERATIONS:
        return ops.execute(db,lambda:ops.intake(db,user,yc_ma,tx_ma,fuel.nl_ma,plate_clean,
            payload.hinh_thuc_do_xang,so_lit_est,so_tien_est))

    request_obj = YeuCauDoXang(
        yc_ma=yc_ma,
        ttxn_ma=REQUEST_WAITING,  # Chờ xác nhận
        tx_ma=tx_ma,
        nd_tendangnhap=user.nd_tendangnhap,
        pt_bienso=plate_clean,
        hinh_thuc_do_xang=payload.hinh_thuc_do_xang,
        thoi_gian_tao=datetime.now(),
    )
    db.add(request_obj)

    detail_item = ChiTietYeuCau(
        nl_ma=fuel.nl_ma,
        yc_ma=yc_ma,
        soluong=so_lit_est,
        thanhtien=so_tien_est,
    )
    db.add(detail_item)
    db.commit()

    return {
        "status": "success",
        "message": "Gửi yêu cầu đổ xăng thành công",
        "yc_ma": yc_ma,
        "tx_ten": station.tx_ten,
        "nl_ten": fuel.nl_ten,
        "hinh_thuc_do_xang": payload.hinh_thuc_do_xang,
        "so_tien_est": float(so_tien_est) if so_tien_est else None,
        "so_lit_est": float(so_lit_est) if so_lit_est else None,
    }


# ==========================================================
# 3. Lấy chi tiết yêu cầu đổ xăng
# ==========================================================
@router.get("/workflow/fuel-requests/{yc_ma}")
def get_fuel_request_detail(
    yc_ma: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_workflow_actor),
):
    statement = (
        select(YeuCauDoXang)
        .options(
            selectinload(YeuCauDoXang.chitiet_yeucau).selectinload(ChiTietYeuCau.nhien_lieu),
            selectinload(YeuCauDoXang.tram_xang),
            selectinload(YeuCauDoXang.trang_thai_xac_nhan),
        )
        .where(YeuCauDoXang.yc_ma == yc_ma.strip())
    )
    req = db.scalars(statement).first()
    if not req:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    _require_request_access(db, req, user)

    item = req.chitiet_yeucau[0] if req.chitiet_yeucau else None
    nl_ten = item.nhien_lieu.nl_ten if item and item.nhien_lieu else "Nhiên liệu"
    nl_ma = item.nl_ma.strip() if item else None

    # Lấy đơn giá trạm hiện tại
    price_rec = db.scalars(
        select(Gia).where(Gia.tx_ma == req.tx_ma, Gia.nl_ma == nl_ma).order_by(desc(Gia.ngaygio))
    ).first() if nl_ma else None
    dongia = float(price_rec.dongia) if price_rec else None
    if POSTGRESQL_OPERATIONS and nl_ma:
        fixed=ops.frozen_quote(db,req.yc_ma,nl_ma)
        if fixed is not None: dongia=float(fixed)

    return {
        "yc_ma": req.yc_ma.strip(),
        "tx_ma": req.tx_ma.strip(),
        "tx_ten": req.tram_xang.tx_ten if req.tram_xang else "",
        "tx_diachi": req.tram_xang.tx_diachi if req.tram_xang else "",
        "nd_tendangnhap": req.nd_tendangnhap.strip(),
        "pt_bienso": req.pt_bienso.strip() if req.pt_bienso else "",
        "hinh_thuc_do_xang": req.hinh_thuc_do_xang,
        "status_code": req.ttxn_ma.strip(),
        "status_text": req.trang_thai_xac_nhan.ttxn_ten if req.trang_thai_xac_nhan else "",
        **workflow_view(req,req.giao_dich[0] if req.giao_dich else None),
        "nl_ma": nl_ma,
        "nl_ten": nl_ten,
        "dongia": dongia,
        "so_lit_est": float(item.soluong) if item and item.soluong else None,
        "so_tien_est": float(item.thanhtien) if item and item.thanhtien else None,
    }


# ==========================================================
# 3.1 DOANH NGHIỆP: Xác nhận tiếp nhận & Bắt đầu bơm xăng
# ==========================================================
@router.post("/workflow/fuel-requests/{yc_ma}/confirm-pump")
def confirm_pump_start(
    yc_ma: str, payload: Optional[PumpAcceptInput] = None, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_doanh_nghiep),
):
    if POSTGRESQL_OPERATIONS:
        if payload is None: raise HTTPException(400,'Vui lòng chọn trụ bơm thực tế')
        return ops.execute(db,lambda:ops.start(db,yc_ma.strip(),user,payload.pump_id))
    req = db.get(YeuCauDoXang, yc_ma.strip())
    if not req:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    _require_station_owner(db, req.tx_ma, user)
    validate_catalog(db)
    if req.ttxn_ma==REQUEST_WAITING: advance_request(req,REQUEST_ACCEPTED)
    advance_request(req,REQUEST_PUMPING)
    db.commit()

    return {
        "status": "success",
        "message": "Trạm xăng đã xác nhận tiếp nhận yêu cầu và bắt đầu bơm xăng",
        "yc_ma": req.yc_ma.strip(),
        "status_code": REQUEST_PUMPING,
        "status_text": "Đang bơm",
    }


# ==========================================================
# 3.1b HỦY YÊU CẦU: Khách hàng hoặc Doanh nghiệp hủy yêu cầu
# ==========================================================
class CancelFuelRequestInput(BaseModel):
    reason: str = Field(default='Khách hàng không cần bơm nữa',min_length=1,max_length=256)
    confirm_no_dispense: bool = False


@router.post("/workflow/fuel-requests/{yc_ma}/cancel")
def cancel_fuel_request(
    yc_ma: str,
    payload: Optional[CancelFuelRequestInput] = None,
    db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_workflow_actor),
):
    if POSTGRESQL_OPERATIONS:
        if payload is None:raise HTTPException(400,'Cần lý do hủy và xác nhận')
        return ops.execute(db,lambda:ops.cancel(db,yc_ma.strip(),user,reason=payload.reason,confirm_no_dispense=payload.confirm_no_dispense))
    statement = (
        select(YeuCauDoXang)
        .options(
            selectinload(YeuCauDoXang.trang_thai_xac_nhan),
            selectinload(YeuCauDoXang.chitiet_yeucau),
            selectinload(YeuCauDoXang.giao_dich),
        )
        .where(YeuCauDoXang.yc_ma == yc_ma.strip())
    )
    req = db.scalars(statement).first()
    if not req:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    _require_request_access(db, req, user)
    cancel_unavailable()


# ==========================================================
# 3.2 KHÁCH HÀNG / DOANH NGHIỆP: Kiểm tra trạng thái yêu cầu
# ==========================================================
@router.get("/workflow/fuel-requests/{yc_ma}/status")
def get_fuel_request_status(
    yc_ma: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_workflow_actor),
):
    statement = (
        select(YeuCauDoXang)
        .options(
            selectinload(YeuCauDoXang.trang_thai_xac_nhan),
            selectinload(YeuCauDoXang.chitiet_yeucau).selectinload(ChiTietYeuCau.nhien_lieu),
            selectinload(YeuCauDoXang.giao_dich),
            selectinload(YeuCauDoXang.tram_xang),
        )
        .where(YeuCauDoXang.yc_ma == yc_ma.strip())
    )
    req = db.scalars(statement).first()
    if not req:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    _require_request_access(db, req, user)

    if POSTGRESQL_OPERATIONS:
        ops.execute(db,lambda:lifecycle.expire_one(db,yc_ma))
        db.expire_all()

    item = req.chitiet_yeucau[0] if req.chitiet_yeucau else None
    gd = req.giao_dich[0] if req.giao_dich else None

    thanhtien = float(gd.gd_sotien) if gd else (float(item.thanhtien) if item and item.thanhtien else 0.0)
    soluong = float(item.soluong) if item and item.soluong else 0.0
    dongia = None
    if item and req.tx_ma:
        transaction_item = gd.chi_tiet_giao_dich[0] if gd and gd.chi_tiet_giao_dich else None
        if transaction_item:
            dongia = float(transaction_item.dongialucban)
        elif soluong > 0 and thanhtien > 0:
            dongia = round(thanhtien / soluong, 2)
        else:
            price_rec = db.scalars(
                select(Gia).where(Gia.tx_ma == req.tx_ma, Gia.nl_ma == item.nl_ma).order_by(desc(Gia.ngaygio))
            ).first()
            dongia = float(price_rec.dongia) if price_rec else None

    qr_data = qr_fields(gd.gd_ma, gd.gd_sotien) if gd else qr_fields("", 0)

    # Lấy thông tin bồn chứa & số lít còn lại
    tank_info = get_tank_by_fuel(req.tx_ma, item.nl_ma,db=db) if (item and req.tx_ma) else None

    # Tính toán thứ tự xe trong hàng chờ theo nguyên tắc FIFO
    queue_order = None
    if req.ttxn_ma in [REQUEST_WAITING, REQUEST_ACCEPTED, REQUEST_PUMPING]:
        earlier_filter = [
            YeuCauDoXang.tx_ma == req.tx_ma,
            YeuCauDoXang.ttxn_ma.in_([REQUEST_WAITING, REQUEST_ACCEPTED, REQUEST_PUMPING]),
        ]
        if req.thoi_gian_tao:
            earlier_filter.append(
                or_(
                    YeuCauDoXang.thoi_gian_tao < req.thoi_gian_tao,
                    and_(YeuCauDoXang.thoi_gian_tao == req.thoi_gian_tao, YeuCauDoXang.yc_ma < req.yc_ma)
                )
            )
        else:
            earlier_filter.append(YeuCauDoXang.yc_ma < req.yc_ma)
        
        ahead_count = db.scalar(select(func.count()).select_from(YeuCauDoXang).where(*earlier_filter)) or 0
        queue_order = ahead_count + 1

    return {
        "yc_ma": req.yc_ma.strip(),
        "status_code": req.ttxn_ma.strip(),
        "status_text": req.trang_thai_xac_nhan.ttxn_ten if req.trang_thai_xac_nhan else "",
        "tx_ma": req.tx_ma.strip(),
        "tx_ten": req.tram_xang.tx_ten if req.tram_xang else "",
        "tx_diachi": req.tram_xang.tx_diachi if req.tram_xang else "",
        "nl_ten": item.nhien_lieu.nl_ten if item and item.nhien_lieu else "",
        "pt_bienso": req.pt_bienso.strip() if req.pt_bienso else "",
        "hinh_thuc_do_xang": req.hinh_thuc_do_xang,
        "gd_ma": gd.gd_ma.strip() if gd else None,
        **workflow_view(req,gd),
        **(lifecycle.metadata(req,db) if POSTGRESQL_OPERATIONS else {}),
        "is_paid": gd.tt_ma == PAYMENT_SUCCEEDED if gd else False,
        "soluong": soluong,
        "dongia": dongia,
        "thanhtien": thanhtien,
        "vietqr_url": qr_data["vietqr_url"],
        "transfer_content": qr_data["transfer_content"],
        "bank_account": qr_data["bank_account"],
        "bank_name": qr_data["bank_name"],
        "account_name": qr_data["account_name"],
        "qr_configured": qr_data["qr_configured"],
        "qr_payment_amount": qr_data["qr_payment_amount"],
        "tank_name": tank_info.get("tank_name") if tank_info else None,
        "tank_liters_remaining": tank_info.get("current_liters") if tank_info else None,
        "tank_capacity": tank_info.get("capacity") if tank_info else None,
        "tank_percentage": tank_info.get("percentage") if tank_info else None,
        "queue_order": queue_order,
        "created_time": req.thoi_gian_tao.strftime("%H:%M:%S") if req.thoi_gian_tao else "",
    }


# ==========================================================
# 4. NHÂN VIÊN TRẠM: Bơm xăng xong & Nhập số lít thực tế
# ==========================================================
class PumpCompleteInput(BaseModel):
    so_lit_thuc_te: Optional[float] = Field(default=None, description="Số lít thực tế bơm được")
    so_tien_thuc_te: Optional[float] = Field(default=None, description="Số tiền thực tế chốt hóa đơn")
    dongia: Optional[float] = None

if POSTGRESQL_OPERATIONS:
    from app.schemas.operations import Complete as PumpCompleteInput


@router.post("/workflow/fuel-requests/{yc_ma}/pump-complete")
def pump_complete(
    yc_ma: str, payload: PumpCompleteInput, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_doanh_nghiep),
):
    if POSTGRESQL_OPERATIONS:
        return ops.execute(db,lambda:ops.complete(db,yc_ma.strip(),user,payload.model_dump()))
    req = db.get(YeuCauDoXang, yc_ma.strip())
    if not req:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    _require_station_owner(db, req.tx_ma, user)
    if get_public_station(db, req.tx_ma) is None:
        raise HTTPException(status_code=409, detail="Trạm không còn công khai; không thể khởi tạo thanh toán mới")

    statement = (
        select(ChiTietYeuCau)
        .options(selectinload(ChiTietYeuCau.nhien_lieu))
        .where(ChiTietYeuCau.yc_ma == req.yc_ma)
    )
    item = db.scalars(statement).first()
    if not item:
        raise HTTPException(status_code=400, detail="Yêu cầu không có thông tin nhiên liệu")
    validate_catalog(db)
    if req.ttxn_ma!=REQUEST_PUMPING or req.giao_dich:
        raise HTTPException(409,'Chỉ hoàn tất yêu cầu đang bơm và chưa có hóa đơn')

    # Xác định đơn giá
    if get_tank_by_fuel(req.tx_ma, item.nl_ma) is None:
        raise HTTPException(status_code=400, detail="Trạm chưa cấu hình bồn nhiên liệu")
    dongia = float(_latest_station_price(db, req.tx_ma, item.nl_ma).dongia)
    if payload.dongia is not None and Decimal(str(payload.dongia)) != Decimal(str(dongia)):
        raise HTTPException(status_code=409, detail="Đơn giá gửi lên không khớp bảng giá của trạm")

    # Tính toán số lượng lít và thành tiền dựa trên lựa chọn chốt số lít hoặc chốt số tiền
    if payload.so_tien_thuc_te is not None and payload.so_tien_thuc_te > 0:
        thanhtien = Decimal(str(round(payload.so_tien_thuc_te)))
        if payload.so_lit_thuc_te is not None and payload.so_lit_thuc_te > 0:
            soluong = Decimal(str(round(payload.so_lit_thuc_te, 2)))
        else:
            soluong = Decimal(str(round(float(thanhtien) / dongia, 2)))
    elif payload.so_lit_thuc_te is not None and payload.so_lit_thuc_te > 0:
        soluong = Decimal(str(round(payload.so_lit_thuc_te, 2)))
        thanhtien = Decimal(str(round(float(soluong) * dongia)))
    else:
        raise HTTPException(status_code=400, detail="Vui lòng nhập số lít hoặc số tiền thực tế hợp lệ")

    # Cập nhật chi tiết yêu cầu
    item.soluong = soluong
    item.thanhtien = thanhtien
    advance_request(req,REQUEST_COMPLETED)  # Hoàn tất vật lý, chưa xác nhận thanh toán.

    # Khấu trừ số lít thực tế trong bồn chứa xăng tương ứng
    deduct_result = deduct_tank_fuel(req.tx_ma, item.nl_ma, float(soluong))

    # Tạo mã giao dịch
    gd_ma = _generate_code(db, GiaoDich, "GD", "gd_ma")
    today = date.today()
    if db.get(ThoiDiem, today) is None:
        db.add(ThoiDiem(ngaygio=today))
        db.flush()

    # Tạo giao dịch (trạng thái Chờ thanh toán)
    giao_dich = GiaoDich(
        gd_ma=gd_ma,
        nd_tendangnhap=req.nd_tendangnhap,
        tx_ma=req.tx_ma,
        yc_ma=req.yc_ma,
        ngaygio=today,
        gd_sotien=thanhtien,
        gd_mathamchieu=f"PETRO-{gd_ma}",
        tt_ma=PAYMENT_PROCESSING,  # Chờ thanh toán
        pttt_ten="VIETQR",
    )
    db.add(giao_dich)

    # Tạo chi tiết giao dịch
    ctgd = ChiTietGiaoDich(
        nl_ma=item.nl_ma,
        gd_ma=gd_ma,
        soluong=soluong,
        dongialucban=Decimal(str(dongia)),
        thanhtien=thanhtien,
    )
    db.add(ctgd)
    db.commit()

    # Bank identity and QR amount come from approved machine-local payment settings.
    qr_data = qr_fields(gd_ma, thanhtien)

    return {
        "status": "success",
        "message": "Đã ghi nhận số lít thực tế & xuất hóa đơn chờ thanh toán",
        "gd_ma": gd_ma,
        "yc_ma": req.yc_ma.strip(),
        "soluong": float(soluong),
        "dongia": dongia,
        "thanhtien": float(thanhtien),
        **qr_data,
        "tank_name": deduct_result.get("tank_name"),
        "tank_liters_remaining": deduct_result.get("liters_remaining"),
        "tank_capacity": deduct_result.get("capacity"),
        "tank_percentage": deduct_result.get("percentage"),
    }


# ==========================================================
# 5. KHÁCH HÀNG: Thanh toán Tiền mặt (Nhân viên xác nhận)
# ==========================================================
class CashConfirmInput(BaseModel):
    gd_ma: str = Field(min_length=1, max_length=8)


@router.post("/payment/cash-confirm")
def confirm_cash_payment(
    payload: CashConfirmInput, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_doanh_nghiep),
):
    if POSTGRESQL_OPERATIONS:
        return ops.execute(db,lambda:ops.cash(db,payload.gd_ma.strip(),user))
    gd = db.get(GiaoDich, payload.gd_ma.strip())
    if not gd:
        raise HTTPException(status_code=404, detail="Giao dịch không tồn tại")
    tx_ma = gd.tx_ma or (gd.yeu_cau_do_xang.tx_ma if gd.yeu_cau_do_xang else None)
    if not tx_ma:
        raise HTTPException(status_code=400, detail="Giao dịch chưa gắn với trạm xăng")
    _require_station_owner(db, tx_ma, user)
    validate_catalog(db)
    db.refresh(gd,with_for_update=True)
    if gd.tt_ma==PAYMENT_SUCCEEDED:
        if gd.pttt_ten!='TIEN_MAT':raise HTTPException(409,'Đã thanh toán bằng phương thức khác')
        return {'status':'success','gd_ma':gd.gd_ma,'replayed':True}
    if not gd.yeu_cau_do_xang or gd.yeu_cau_do_xang.ttxn_ma!=REQUEST_COMPLETED:
        raise HTTPException(409,'Chưa xác nhận hoàn tất bơm; cần đối soát')
    advance_payment(gd,PAYMENT_SUCCEEDED)
    gd.pttt_ten = "TIEN_MAT"
    gd.gd_mathamchieu = f"CASH-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    db.commit()
    return {
        "status": "success",
        "message": "Nhân viên trạm đã xác nhận nhận tiền mặt thành công",
        "gd_ma": gd.gd_ma.strip(),
        "amount": float(gd.gd_sotien),
    }


# ==========================================================
# 6. CASSO WEBHOOK: Tự động đối soát chuyển khoản ngân hàng
# ==========================================================
@router.post("/payment/casso-webhook")
async def casso_webhook(request: Request, db: Session = Depends(get_db)):
    """Verify Casso secure-token and bank account, then use approved PG UoW.

    No payment can succeed from a QR image, a browser response, or an unverified
    webhook. Do not expose the public API through a wide-open tunnel.
    """
    webhook_secret = payment_setting("CASSO_WEBHOOK_SECRET")
    if not webhook_secret or beneficiary() is None:
        raise HTTPException(503, "Casso chưa được cấu hình và xác minh")
    provided_secret = request.headers.get("secure-token", "").strip()
    if not provided_secret or not hmac.compare_digest(provided_secret.encode('utf-8'), webhook_secret.encode('utf-8')):
        raise HTTPException(401, "Không xác thực được webhook")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Webhook JSON không hợp lệ") from None
    try:
        events, rejected = parse_casso_events(body)
    except CassoPayloadConflict:
        raise HTTPException(409, 'TID trong webhook có nội dung xung đột; chưa xử lý batch') from None
    if not events:
        return {"error": 0, "processed_count": 0, "settled_count": 0,
                "reconciliation_count": 0, "details": [], "rejected": rejected,
                "rejected_count": len(rejected), "audit_persisted": False}

    if POSTGRESQL_OPERATIONS:
        result = ops.execute(db, lambda: ops.bank_callback(db, events))
        return {**result, "rejected": rejected, "rejected_count": len(rejected),
                "audit_persisted": False}

    # The 35-table approved production workflow is the only payment settlement
    # path. Never fall back to the pre-migration mutable legacy workflow.
    raise HTTPException(503, "Đối soát ngân hàng chỉ khả dụng trong chế độ PostgreSQL đã phê duyệt")


# ==========================================================
# 7. MÔ PHỎNG CASSO WEBHOOK (Dành cho kiểm thử & Demo NCKH)
# ==========================================================
class SimulateCassoInput(BaseModel):
    gd_ma: str = Field(min_length=1, max_length=8)


@router.post("/payment/simulate-casso")
def simulate_casso(
    payload: SimulateCassoInput, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_doanh_nghiep),
):
    if POSTGRESQL_OPERATIONS:
        raise HTTPException(409,'Không cho phép tạo xác nhận thanh toán giả trong chế độ kho PostgreSQL')
    if os.getenv("ENABLE_PAYMENT_SIMULATION", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Chức năng mô phỏng chưa được bật")
    gd = db.get(GiaoDich, payload.gd_ma.strip())
    if not gd:
        raise HTTPException(status_code=404, detail="Giao dịch không tồn tại")
    tx_ma = gd.tx_ma or (gd.yeu_cau_do_xang.tx_ma if gd.yeu_cau_do_xang else None)
    if not tx_ma:
        raise HTTPException(status_code=400, detail="Giao dịch chưa gắn với trạm xăng")
    _require_station_owner(db, tx_ma, user)

    validate_catalog(db)
    db.refresh(gd,with_for_update=True)
    if not gd.yeu_cau_do_xang or gd.yeu_cau_do_xang.ttxn_ma!=REQUEST_COMPLETED:
        raise HTTPException(409,'Chưa hoàn tất bơm; không được mô phỏng thanh toán')
    advance_payment(gd,PAYMENT_SUCCEEDED)
    gd.pttt_ten = "VIETQR"
    fake_tid = f"MB-{secrets.token_hex(4).upper()}"
    gd.gd_mathamchieu = fake_tid

    db.commit()
    return {
        "status": "success",
        "message": f"Mô phỏng Casso Webhook thành công! Đã khớp GD {gd.gd_ma.strip()} với số tiền {float(gd.gd_sotien):,.0f} đ",
        "gd_ma": gd.gd_ma.strip(),
        "tid": fake_tid,
        "amount": float(gd.gd_sotien),
    }


# ==========================================================
# 8. POLLING: Kiểm tra trạng thái giao dịch theo thời gian thực
# ==========================================================
@router.get("/payment/status/{gd_ma}")
def check_transaction_status(
    gd_ma: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_workflow_actor),
):
    statement = (
        select(GiaoDich)
        .options(selectinload(GiaoDich.trang_thai))
        .where(GiaoDich.gd_ma == gd_ma.strip())
    )
    gd = db.scalars(statement).first()
    if not gd:
        raise HTTPException(status_code=404, detail="Giao dịch không tồn tại")
    _require_transaction_access(db, gd, user)

    is_paid = gd.tt_ma == PAYMENT_SUCCEEDED
    return {
        "gd_ma": gd.gd_ma.strip(),
        "payment_state": {PAYMENT_SUCCEEDED:'SUCCEEDED',PAYMENT_FAILED:'FAILED',PAYMENT_PROCESSING:'PROCESSING'}.get(gd.tt_ma,'UNKNOWN'),
        "status_code": gd.tt_ma.strip(),
        "status_text": gd.trang_thai.tt_ten if gd.trang_thai else "Chờ thanh toán",
        "is_paid": is_paid,
        "amount": float(gd.gd_sotien),
        "payment_method": gd.pttt_ten,
        "ref_code": gd.gd_mathamchieu,
    }


# ==========================================================
# 9. LỊCH SỬ GIAO DỊCH (Cho trang LichSu.html)
# ==========================================================
@router.get("/payment/history")
def get_transaction_history(
    username: Optional[str] = None,
    db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    if username and username.strip() != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không có quyền xem lịch sử của khách hàng khác")
    statement = (
        select(GiaoDich)
        .options(
            selectinload(GiaoDich.tram_xang),
            selectinload(GiaoDich.trang_thai),
            selectinload(GiaoDich.chi_tiet_giao_dich).selectinload(ChiTietGiaoDich.nhien_lieu),
        )
        .where(GiaoDich.nd_tendangnhap == user.nd_tendangnhap)
        .order_by(desc(GiaoDich.ngaygio), desc(GiaoDich.gd_ma))
    )
    transactions = db.scalars(statement).all()

    items = []
    total_spent = Decimal("0")
    success_count = 0

    for gd in transactions:
        is_success = gd.tt_ma == PAYMENT_SUCCEEDED
        if is_success:
            total_spent += gd.gd_sotien
            success_count += 1

        ct = gd.chi_tiet_giao_dich[0] if gd.chi_tiet_giao_dich else None
        fuel_name = ct.nhien_lieu.nl_ten if ct and ct.nhien_lieu else "Nhiên liệu"
        station_name = gd.tram_xang.tx_ten if gd.tram_xang else "Không rõ trạm"

        items.append({
            "gd_ma": gd.gd_ma.strip(),
            "tx_ten": station_name,
            "nl_ten": fuel_name,
            "soluong": float(ct.soluong) if ct else 0.0,
            "amount": float(gd.gd_sotien),
            "amount_formatted": f"{int(gd.gd_sotien):,} đ",
            "date": gd.ngaygio.strftime("%d/%m/%Y") if gd.ngaygio else "",
            "status_code": gd.tt_ma.strip(),
            "status_text": gd.trang_thai.tt_ten if gd.trang_thai else "Chờ thanh toán",
            "is_success": is_success,
            "payment_method": gd.pttt_ten or "VIETQR",
        })

    return {
        "status": "success",
        "total_transactions": len(items),
        "success_count": success_count,
        "total_spent": float(total_spent),
        "total_spent_formatted": f"{int(total_spent):,} VNĐ",
        "transactions": items,
    }


# ==========================================================
# 10. CHI TIẾT GIAO DỊCH (Cho ChiTietGiaoDich.html & XacNhanThanhToan.html)
# ==========================================================
@router.get("/payment/detail/{gd_ma}")
def get_transaction_detail(
    gd_ma: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_workflow_actor),
):
    statement = (
        select(GiaoDich)
        .options(
            selectinload(GiaoDich.tram_xang),
            selectinload(GiaoDich.trang_thai),
            selectinload(GiaoDich.chi_tiet_giao_dich).selectinload(ChiTietGiaoDich.nhien_lieu),
            selectinload(GiaoDich.yeu_cau_do_xang),
        )
        .where(GiaoDich.gd_ma == gd_ma.strip())
    )
    gd = db.scalars(statement).first()
    if not gd:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch")
    _require_transaction_access(db, gd, user)

    ct = gd.chi_tiet_giao_dich[0] if gd.chi_tiet_giao_dich else None
    fuel_name = ct.nhien_lieu.nl_ten if ct and ct.nhien_lieu else "Nhiên liệu"
    unit_price = float(ct.dongialucban) if ct else None
    liters = float(ct.soluong) if ct else 0.0

    station = gd.tram_xang
    req = gd.yeu_cau_do_xang

    return {
        "gd_ma": gd.gd_ma.strip(),
        "yc_ma": gd.yc_ma.strip() if gd.yc_ma else "",
        "tx_ma": station.tx_ma.strip() if station else "",
        "tx_ten": station.tx_ten if station else "Không rõ trạm",
        "tx_diachi": station.tx_diachi if station else "",
        "nl_ten": fuel_name,
        "dongia": unit_price,
        "dongia_formatted": f"{int(unit_price):,} đ/Lít" if unit_price is not None else "Chưa có đơn giá",
        "soluong": liters,
        "amount": float(gd.gd_sotien),
        "amount_formatted": f"{int(gd.gd_sotien):,} đ",
        "pt_bienso": req.pt_bienso.strip() if req and req.pt_bienso else "",
        "date_formatted": gd.ngaygio.strftime("%d/%m/%Y") if gd.ngaygio else datetime.now().strftime("%d/%m/%Y"),
        "time_formatted": datetime.now().strftime("%H:%M"),
        "payment_method": "Tiền mặt" if gd.pttt_ten == "TIEN_MAT" else "Chuyển khoản VietQR",
        "status_code": gd.tt_ma.strip(),
        "status_text": gd.trang_thai.tt_ten if gd.trang_thai else "Thành công",
        "status_name": gd.trang_thai.tt_ten if gd.trang_thai else "Thành công",
        "is_success": gd.tt_ma == PAYMENT_SUCCEEDED,
        "ref_code": gd.gd_mathamchieu,
    }
