from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import require_workflow_actor, get_user_role, require_doanh_nghiep, require_khach_hang
from app.database.session import get_db
from app.models import TaiKhoanLienKet, TramXang
from app.models.user import NguoiDung
from app.schemas import (
    ChiTietYeuCauResponse, ChiTietYeuCauUpdate, FuelRequestCreateInput,
    FuelRequestItemInput, FuelRequestStatusUpdate, GiaoDichResponse,
    TaiKhoanLienKetCreate, TaiKhoanLienKetResponse, TransactionCreateInput,
    YeuCauDoXangResponse,
)
from app.services import workflow as workflow_service
from app.services.station_visibility import get_public_station

router = APIRouter(
    prefix="/api",
    responses={
        400: {"description": "Bad request"},
        404: {"description": "Not found"},
        409: {"description": "Conflict"},
    },
)


def _run(operation):
    try:
        return operation()
    except workflow_service.WorkflowError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _request_access(db: Session, yc_ma: str, user: NguoiDung, *, enterprise_only: bool = False):
    request = _run(lambda: workflow_service.get_fuel_request(db, yc_ma))
    role, _ = get_user_role(user)
    if role == "KHACH_HANG" and not enterprise_only and request.nd_tendangnhap == user.nd_tendangnhap:
        return request
    if role == "DOANH_NGHIEP":
        station = db.get(TramXang, request.tx_ma)
        if station and station.nd_tendangnhap == user.nd_tendangnhap:
            return request
    raise HTTPException(status_code=403, detail="Không có quyền truy cập yêu cầu này")


def _transaction_access(db: Session, gd_ma: str, user: NguoiDung):
    transaction = _run(lambda: workflow_service.get_transaction(db, gd_ma))
    role, _ = get_user_role(user)
    if role == "KHACH_HANG" and transaction.nd_tendangnhap == user.nd_tendangnhap:
        return transaction
    if role == "DOANH_NGHIEP":
        request = _run(lambda: workflow_service.get_fuel_request(db, transaction.yc_ma))
        station = db.get(TramXang, request.tx_ma)
        if station and station.nd_tendangnhap == user.nd_tendangnhap:
            return transaction
    raise HTTPException(status_code=403, detail="Không có quyền truy cập giao dịch này")


@router.post("/linked-accounts", response_model=TaiKhoanLienKetResponse, status_code=status.HTTP_201_CREATED, tags=["Linked accounts"])
def create_linked_account(
    payload: TaiKhoanLienKetCreate, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    if payload.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không thể liên kết thẻ cho khách hàng khác")
    return _run(lambda: workflow_service.create_linked_account(db, payload.model_dump()))


@router.get("/linked-accounts/{username}", response_model=list[TaiKhoanLienKetResponse], tags=["Linked accounts"])
def list_linked_accounts(
    username: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    if username != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không có quyền xem thẻ của khách hàng khác")
    return _run(lambda: workflow_service.list_linked_accounts(db, username))


@router.delete("/linked-accounts/{card_number}", status_code=status.HTTP_204_NO_CONTENT, tags=["Linked accounts"])
def delete_linked_account(
    card_number: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
) -> Response:
    account = db.get(TaiKhoanLienKet, card_number)
    if account is None:
        raise HTTPException(status_code=404, detail="Linked account not found")
    if account.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không có quyền hủy liên kết thẻ này")
    _run(lambda: workflow_service.delete_linked_account(db, card_number))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/fuel-requests", response_model=YeuCauDoXangResponse, status_code=status.HTTP_201_CREATED, tags=["Fuel requests"])
def create_fuel_request(
    payload: FuelRequestCreateInput, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    if payload.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không thể tạo yêu cầu cho khách hàng khác")
    if get_public_station(db,payload.tx_ma) is None:
        raise HTTPException(404,"Không tìm thấy trạm công khai")
    return _run(lambda: workflow_service.create_fuel_request(db, payload.model_dump()))


@router.get("/fuel-requests", response_model=list[YeuCauDoXangResponse], tags=["Fuel requests"])
def list_fuel_requests(
    username: str | None = None, station_id: str | None = None,
    db: Session = Depends(get_db), user: NguoiDung = Depends(require_workflow_actor),
):
    role, _ = get_user_role(user)
    if role == "KHACH_HANG":
        if username and username != user.nd_tendangnhap:
            raise HTTPException(status_code=403, detail="Không có quyền xem yêu cầu của khách hàng khác")
        return _run(lambda: workflow_service.list_fuel_requests(db, user.nd_tendangnhap, station_id))
    return _run(lambda: workflow_service.list_fuel_requests(db, username, station_id, user.nd_tendangnhap))


@router.get("/fuel-requests/{yc_ma}", response_model=YeuCauDoXangResponse, tags=["Fuel requests"])
def get_fuel_request(
    yc_ma: str, db: Session = Depends(get_db), user: NguoiDung = Depends(require_workflow_actor),
):
    return _request_access(db, yc_ma, user)


@router.patch("/fuel-requests/{yc_ma}/status", response_model=YeuCauDoXangResponse, tags=["Fuel requests"])
def update_fuel_request_status(
    yc_ma: str, payload: FuelRequestStatusUpdate, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_doanh_nghiep),
):
    _request_access(db, yc_ma, user, enterprise_only=True)
    return _run(lambda: workflow_service.update_fuel_request_status(db, yc_ma, payload.status,user))


@router.delete("/fuel-requests/{yc_ma}", status_code=status.HTTP_204_NO_CONTENT, tags=["Fuel requests"])
def delete_fuel_request(
    yc_ma: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
) -> Response:
    _request_access(db, yc_ma, user)
    _run(lambda: workflow_service.delete_fuel_request(db, yc_ma))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fuel-requests/{yc_ma}/items", response_model=list[ChiTietYeuCauResponse], tags=["Fuel request items"])
def list_fuel_request_items(
    yc_ma: str, db: Session = Depends(get_db), user: NguoiDung = Depends(require_workflow_actor),
):
    _request_access(db, yc_ma, user)
    return _run(lambda: workflow_service.list_request_items(db, yc_ma))


@router.post("/fuel-requests/{yc_ma}/items", response_model=ChiTietYeuCauResponse, status_code=status.HTTP_201_CREATED, tags=["Fuel request items"])
def add_fuel_request_item(
    yc_ma: str, payload: FuelRequestItemInput, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    _request_access(db, yc_ma, user)
    return _run(lambda: workflow_service.add_request_item(db, yc_ma, payload.model_dump()))


@router.patch("/fuel-requests/{yc_ma}/items/{nl_ma}", response_model=ChiTietYeuCauResponse, tags=["Fuel request items"])
def update_fuel_request_item(
    yc_ma: str, nl_ma: str, payload: ChiTietYeuCauUpdate,
    db: Session = Depends(get_db), user: NguoiDung = Depends(require_khach_hang),
):
    _request_access(db, yc_ma, user)
    return _run(lambda: workflow_service.update_request_item(db, yc_ma, nl_ma, payload.model_dump(exclude_unset=True)))


@router.delete("/fuel-requests/{yc_ma}/items/{nl_ma}", status_code=status.HTTP_204_NO_CONTENT, tags=["Fuel request items"])
def delete_fuel_request_item(
    yc_ma: str, nl_ma: str, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
) -> Response:
    _request_access(db, yc_ma, user)
    _run(lambda: workflow_service.delete_request_item(db, yc_ma, nl_ma))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/transactions", response_model=GiaoDichResponse, status_code=status.HTTP_201_CREATED, tags=["Transactions"])
def create_transaction(
    payload: TransactionCreateInput, db: Session = Depends(get_db),
    user: NguoiDung = Depends(require_khach_hang),
):
    if payload.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(status_code=403, detail="Không thể tạo giao dịch cho khách hàng khác")
    _request_access(db, payload.yc_ma, user)
    return _run(lambda: workflow_service.create_transaction(db, payload.model_dump()))


@router.get("/transactions", response_model=list[GiaoDichResponse], tags=["Transactions"])
def list_transactions(
    db: Session = Depends(get_db), user: NguoiDung = Depends(require_workflow_actor),
):
    role, _ = get_user_role(user)
    if role == "KHACH_HANG":
        return _run(lambda: workflow_service.list_transactions(db, username=user.nd_tendangnhap))
    return _run(lambda: workflow_service.list_transactions(db, owner_username=user.nd_tendangnhap))


@router.get("/transactions/{gd_ma}", response_model=GiaoDichResponse, tags=["Transactions"])
def get_transaction(
    gd_ma: str, db: Session = Depends(get_db), user: NguoiDung = Depends(require_workflow_actor),
):
    return _transaction_access(db, gd_ma, user)
