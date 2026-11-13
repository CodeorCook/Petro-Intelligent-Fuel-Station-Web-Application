import secrets
import string
import unicodedata
from collections.abc import Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ChiTietGiaoDich, ChiTietYeuCau, Gia, GiaoDich, KhachHang, NganHang, NhienLieu,
    PhuongTien, TaiKhoanLienKet, ThoiDiem, TrangThai, TrangThaiXacNhan, TramXang,
    YeuCauDoXang,
)


from app.services.station_visibility import get_public_station

from app.core.operational_mode import POSTGRESQL_OPERATIONS
from app.core.workflow_status import REQUEST_WAITING,REQUEST_ACCEPTED,REQUEST_COMPLETED,REQUEST_REJECTED,REQUEST_TRANSITIONS,PAYMENT_PROCESSING,validate_catalog,advance_request,cancel_unavailable
from app.models.user import NguoiDung

def _operational_pending(db,request_id):
    if not POSTGRESQL_OPERATIONS: return
    from app.services import operational_service as ops
    ops.guard(db)
    req=get_fuel_request(db,request_id)
    ops.assert_request_writable(request_id)
    ops.station_lock(db,req.tx_ma,db.get(NguoiDung,req.nd_tendangnhap),customer=True)
    db.refresh(req,with_for_update=True)
    from app.services.request_lifecycle import refuse_expired
    result=refuse_expired(db,req)
    if result:
        db.commit()
        raise WorkflowError(409,'Yêu cầu đã hết hạn; không được sửa')
    if req.ttxn_ma!=REQUEST_WAITING: raise WorkflowError(409,'Yêu cầu đã tiếp nhận; không được sửa chi tiết hoặc xóa')


class WorkflowError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def create_linked_account(db: Session, values: dict[str, Any]) -> TaiKhoanLienKet:
    _require(db.get(KhachHang, values["nd_tendangnhap"]), "Customer")
    _require(db.get(NganHang, values["nh_ma"]), "Bank")
    return _commit_once(db, TaiKhoanLienKet(**values))


def list_linked_accounts(db: Session, username: str) -> Sequence[TaiKhoanLienKet]:
    _require(db.get(KhachHang, username), "Customer")
    return db.scalars(select(TaiKhoanLienKet).where(TaiKhoanLienKet.nd_tendangnhap == username)).all()


def delete_linked_account(db: Session, card_number: str) -> None:
    account = _require(db.get(TaiKhoanLienKet, card_number), "Linked account")
    _commit_once(db, delete=account)


def create_fuel_request(db: Session, values: dict[str, Any]) -> YeuCauDoXang:
    if values.get('ttxn_ma')!=REQUEST_WAITING: raise WorkflowError(409,'Yêu cầu mới phải ở trạng thái Chờ duyệt')
    if POSTGRESQL_OPERATIONS:
        if values.get('ttxn_ma')!=REQUEST_WAITING: raise WorkflowError(409,'Trạng thái ban đầu phải là chờ tiếp nhận')
        from app.services import operational_service as ops
        from app.models import NguoiDung
        ops.guard(db)
        ops.station_lock(db,values['tx_ma'],db.get(NguoiDung,values['nd_tendangnhap']),customer=True)
        if len(values['items'])!=1: raise WorkflowError(409,'Luồng bơm hiện tại yêu cầu một nhiên liệu')
        for item in values['items']:
            ops.quote(db,values['tx_ma'],item['nl_ma'])
            ops.validate_intake_configuration(db,values['tx_ma'],item['nl_ma'],ops.decimal(item['soluong']))
    _validate_request_references(db, values)
    plate = values.get("pt_bienso")
    if plate is not None:
        plate = plate.strip().upper()
        if not plate:
            raise WorkflowError(400, "Vehicle plate cannot be empty")
        vehicle = _require(db.get(PhuongTien, plate), "Vehicle")
        if vehicle.nd_tendangnhap != values["nd_tendangnhap"]:
            raise WorkflowError(403, "Vehicle does not belong to the customer")
    request_id = values.get("yc_ma") or _new_identifier(db, YeuCauDoXang, "YC")
    if db.get(YeuCauDoXang, request_id) is not None:
        raise WorkflowError(409, "Fuel request id already exists")
    request = YeuCauDoXang(
        yc_ma=request_id,
        ttxn_ma=values["ttxn_ma"],
        tx_ma=values["tx_ma"],
        nd_tendangnhap=values["nd_tendangnhap"],
        pt_bienso=plate,
        hinh_thuc_do_xang=values.get("hinh_thuc_do_xang"),
    )
    if POSTGRESQL_OPERATIONS:
        from sqlalchemy import func,text
        request.yc_het_han_luc=db.scalar(select(func.clock_timestamp()+text("interval '900 seconds'")))
    for item in values["items"]:
        _require(db.get(NhienLieu, item["nl_ma"]), "Fuel")
        request.chitiet_yeucau.append(ChiTietYeuCau(yc_ma=request_id, **item))
    return _commit_once(db, request)


def list_fuel_requests(
    db: Session, username: str | None, station_id: str | None,
    owner_username: str | None = None,
) -> Sequence[YeuCauDoXang]:
    statement = select(YeuCauDoXang).options(selectinload(YeuCauDoXang.chitiet_yeucau))
    if owner_username is not None:
        statement = statement.join(TramXang).where(TramXang.nd_tendangnhap == owner_username)
    if username is not None:
        statement = statement.where(YeuCauDoXang.nd_tendangnhap == username)
    if station_id is not None:
        statement = statement.where(YeuCauDoXang.tx_ma == station_id)
    return db.scalars(statement).all()


def get_fuel_request(db: Session, request_id: str) -> YeuCauDoXang:
    statement = select(YeuCauDoXang).options(selectinload(YeuCauDoXang.chitiet_yeucau)).where(YeuCauDoXang.yc_ma == request_id)
    return _require(db.scalars(statement).first(), "Fuel request")


def update_fuel_request_status(db: Session, request_id: str, status_value: str, actor=None) -> YeuCauDoXang:
    if POSTGRESQL_OPERATIONS:
        raise WorkflowError(409,'Dùng endpoint tiếp nhận/bắt đầu/từ chối/hủy có kiểm soát')
    request = get_fuel_request(db, request_id)
    confirmation_status = _resolve_confirmation_status(db, status_value)
    validate_catalog(db)
    # Physical completion requires the guarded pumping/ledger command, not a PATCH.
    if confirmation_status.ttxn_ma not in {REQUEST_WAITING,REQUEST_ACCEPTED,REQUEST_REJECTED}:
        raise WorkflowError(409,'Dùng luồng bơm có kiểm soát để cập nhật trạng thái vật lý')
    advance_request(request,confirmation_status.ttxn_ma)
    return _commit_once(db, request)


def delete_fuel_request(db: Session, request_id: str) -> None:
    if POSTGRESQL_OPERATIONS:
        get_fuel_request(db,request_id)
        cancel_unavailable()
    _operational_pending(db,request_id)
    request = get_fuel_request(db, request_id)
    for item in list(request.chitiet_yeucau):
        db.delete(item)
    db.delete(request)
    _commit_once(db)


def list_request_items(db: Session, request_id: str) -> Sequence[ChiTietYeuCau]:
    return get_fuel_request(db, request_id).chitiet_yeucau


def add_request_item(db: Session, request_id: str, values: dict[str, Any]) -> ChiTietYeuCau:
    if POSTGRESQL_OPERATIONS: raise WorkflowError(409,'Tạo yêu cầu riêng cho nhiên liệu khác')
    _require(db.get(NhienLieu, values["nl_ma"]), "Fuel")
    if db.get(ChiTietYeuCau, (values["nl_ma"], request_id)) is not None:
        raise WorkflowError(409, "Fuel is already present in this request")
    get_fuel_request(db, request_id)
    return _commit_once(db, ChiTietYeuCau(yc_ma=request_id, **values))


def update_request_item(db: Session, request_id: str, fuel_id: str, values: dict[str, Any]) -> ChiTietYeuCau:
    _operational_pending(db,request_id)
    item = _require(db.get(ChiTietYeuCau, (fuel_id, request_id)), "Fuel request item")
    for field, value in values.items():
        setattr(item, field, value)
    return _commit_once(db, item)


def delete_request_item(db: Session, request_id: str, fuel_id: str) -> None:
    _operational_pending(db,request_id)
    item = _require(db.get(ChiTietYeuCau, (fuel_id, request_id)), "Fuel request item")
    _commit_once(db, delete=item)


def create_transaction(db: Session, values: dict[str, Any]) -> GiaoDich:
    if POSTGRESQL_OPERATIONS: raise WorkflowError(409,'Hóa đơn vận hành chỉ được tạo khi hoàn tất bơm nguyên tử')
    customer = _require(db.get(KhachHang, values["nd_tendangnhap"]), "Customer")
    account = _require(db.get(TaiKhoanLienKet, values["tklk_mathe"]), "Linked account")
    if account.nd_tendangnhap != customer.nd_tendangnhap:
        raise WorkflowError(400, "Linked account does not belong to the customer")
    request = get_fuel_request(db, values["yc_ma"])
    if request.nd_tendangnhap != customer.nd_tendangnhap:
        raise WorkflowError(400, "Fuel request does not belong to the customer")
    _require(get_public_station(db, request.tx_ma), "Public station")
    if values.get('tt_ma')!=PAYMENT_PROCESSING: raise WorkflowError(409,'Giao dịch mới phải ở trạng thái Đang xử lý; khách hàng không được tự đánh dấu thành công')
    if not _is_payable_status(db, request.ttxn_ma):
        raise WorkflowError(400, "Fuel request is not in a payable status")
    _require(db.get(TrangThai, values["tt_ma"]), "Transaction status")
    for item in values["items"]:
        _require(db.get(NhienLieu, item["nl_ma"]), "Fuel")
        station_price = db.scalars(
            select(Gia).where(
                Gia.tx_ma == request.tx_ma,
                Gia.nl_ma == item["nl_ma"],
                Gia.ngaygio <= values["ngaygio"],
            ).order_by(Gia.ngaygio.desc())
        ).first()
        if station_price is None:
            raise WorkflowError(400, "Chưa có giá nhiên liệu cho trạm này")
        if item["dongialucban"] != station_price.dongia:
            raise WorkflowError(409, "Đơn giá giao dịch không khớp bảng giá của trạm")
    transaction_id = values.get("gd_ma") or _new_identifier(db, GiaoDich, "GD")
    if db.get(GiaoDich, transaction_id) is not None:
        raise WorkflowError(409, "Transaction id already exists")
    if db.get(ThoiDiem, values["ngaygio"]) is None:
        db.add(ThoiDiem(ngaygio=values["ngaygio"]))
    transaction = GiaoDich(
        gd_ma=transaction_id,
        nd_tendangnhap=values["nd_tendangnhap"],
        tklk_mathe=values["tklk_mathe"], tt_ma=values["tt_ma"],
        ngaygio=values["ngaygio"], yc_ma=values["yc_ma"],
        gd_sotien=values["gd_sotien"], gd_mathamchieu=values["gd_mathamchieu"],
    )
    for item in values["items"]:
        transaction.chi_tiet_giao_dich.append(ChiTietGiaoDich(gd_ma=transaction_id, **item))
    return _commit_once(db, transaction)


def list_transactions(
    db: Session, username: str | None = None, owner_username: str | None = None,
) -> Sequence[GiaoDich]:
    statement = select(GiaoDich).options(selectinload(GiaoDich.chi_tiet_giao_dich))
    if username is not None:
        statement = statement.where(GiaoDich.nd_tendangnhap == username)
    if owner_username is not None:
        statement = statement.join(YeuCauDoXang, GiaoDich.yc_ma == YeuCauDoXang.yc_ma).join(TramXang).where(
            TramXang.nd_tendangnhap == owner_username
        )
    return db.scalars(statement).all()


def get_transaction(db: Session, transaction_id: str) -> GiaoDich:
    statement = select(GiaoDich).options(selectinload(GiaoDich.chi_tiet_giao_dich)).where(GiaoDich.gd_ma == transaction_id)
    return _require(db.scalars(statement).first(), "Transaction")


def _validate_request_references(db: Session, values: dict[str, Any]) -> None:
    _require(db.get(KhachHang, values["nd_tendangnhap"]), "Customer")
    _require(get_public_station(db, values["tx_ma"]), "Public station")
    _require(db.get(TrangThaiXacNhan, values["ttxn_ma"]), "Confirmation status")


def _resolve_confirmation_status(db: Session, value: str) -> TrangThaiXacNhan:
    statement = select(TrangThaiXacNhan).where(
        or_(TrangThaiXacNhan.ttxn_ma == value, TrangThaiXacNhan.ttxn_ten.ilike(value))
    )
    return _require(db.scalars(statement).first(), "Confirmation status")


def _is_payable_status(db: Session, status_id: str) -> bool:
    status = _require(db.get(TrangThaiXacNhan, status_id), "Confirmation status")
    normalized = _normalize_status_name(status.ttxn_ten)
    return status.ttxn_ma==REQUEST_COMPLETED and normalized=="HOAN_THANH"


def _normalize_status_name(value: str) -> str:
    text = "".join(char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn")
    return "_".join(text.upper().replace("-", " ").split())


def _new_identifier(db: Session, model: type[Any], prefix: str) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        identifier = prefix + "".join(secrets.choice(alphabet) for _ in range(6))
        if db.get(model, identifier) is None:
            return identifier
    raise WorkflowError(409, f"Could not generate a unique {prefix} identifier")


def _require(value: Any | None, label: str) -> Any:
    if value is None:
        raise WorkflowError(404, f"{label} not found")
    return value


def _commit_once(db: Session, refresh: Any | None = None, delete: Any | None = None) -> Any | None:
    if refresh is not None:
        db.add(refresh)
    if delete is not None:
        db.delete(delete)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise WorkflowError(409, "Request conflicts with database constraints") from error
    if refresh is not None:
        db.refresh(refresh)
    return refresh
