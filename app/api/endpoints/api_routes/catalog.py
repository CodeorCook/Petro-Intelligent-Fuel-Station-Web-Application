from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status, Query
from typing import Literal
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.auth import get_current_user_optional, require_approved_enterprise, require_admin
from app.models.user import NguoiDung
from app.models import (
    DanhGia, DichVu, Gia, NganHang, NhienLieu, PhuongTien, TramXang, TxDv,
)
from app.schemas import (
    DanhGiaCreate, DanhGiaResponse, DanhGiaUpdate,
    DichVuCreate, DichVuResponse, DichVuUpdate,
    GiaCreate, GiaResponse, GiaUpdate,
    NganHangCreate, NganHangResponse, NganHangUpdate,
    NhienLieuCreate, NhienLieuResponse, NhienLieuUpdate,
    PhuongTienCreate, PhuongTienResponse, PhuongTienUpdate,
    TramXangCreate, TramXangResponse, TramXangUpdate,
    TxDvResponse, ViTriHienTaiCreate, ViTriHienTaiResponse,
)
from app.services import catalog as catalog_service
from app.services import location as location_service
from app.services.station_visibility import public_station_query,public_related_query,get_public_station
from app.services import station_approval as station_approval_service
from app.services.station_discovery import filter_station_query
from app.services import station_amenities as amenity_service
from app.schemas.station_approval import StationDraftInput

router = APIRouter(
    prefix="/api",
    tags=["Catalog"],
    responses={
        400: {"description": "Bad request"},
        404: {"description": "Not found"},
        409: {"description": "Conflict"},
    },
)


def _not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")


def _conflict() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request conflicts with database constraints")


def _write(operation):
    try:
        return operation()
    except catalog_service.ConflictError as error:
        raise _conflict() from error


def _station_owner(db: Session, tx_ma: str, user: NguoiDung) -> TramXang:
    require_approved_enterprise(user)
    station = db.get(TramXang, tx_ma)
    if station is None:
        raise _not_found("Station")
    if station.nd_tendangnhap != user.nd_tendangnhap:
        raise HTTPException(403, "Không có quyền quản lý trạm này")
    return station


def register_crud(
    *, prefix: str, tag: str, model: type[Any], create_schema: type[BaseModel],
    update_schema: type[BaseModel], response_schema: type[BaseModel], pk_name: str,
) -> None:
    """Register single-column-key CRUD endpoints with typed Pydantic payloads."""
    def list_resources(db: Session = Depends(get_db)):
        if model is TramXang:return db.scalars(public_station_query()).all()
        if model is DanhGia:return db.scalars(public_related_query(model)).all()
        if model is DichVu:return catalog_service.list_service_catalog(db)
        return catalog_service.list_items(db, model)

    if model is TramXang:
        def list_resources(db: Session = Depends(get_db),
                           amenity_ids: list[str] = Query(default=[], max_length=50),
                           amenity_match: Literal['all', 'any'] = 'all',
                           fuel_type: str | None = Query(default=None, max_length=64),
                           search: str | None = Query(default=None, max_length=128)):
            return db.scalars(filter_station_query(db, public_station_query(),
                amenity_ids=amenity_ids, amenity_match=amenity_match,
                fuel_type=fuel_type, search=search)).all()

    def get_resource(resource_id: str, db: Session = Depends(get_db)):
        item = catalog_service.get_item(db, model, resource_id)
        if model is TramXang:item=get_public_station(db,resource_id)
        if model is DanhGia and item is not None and get_public_station(db,item.tx_ma) is None:item=None
        if item is None:
            raise _not_found(tag)
        return item

    write_guard = require_approved_enterprise if model is TramXang else require_admin if model is DichVu else get_current_user_optional

    def create_resource(payload: create_schema, db: Session = Depends(get_db), user=Depends(write_guard)):
        if model is DanhGia:
            raise HTTPException(405, 'Dùng đánh giá gắn với hóa đơn đã thanh toán; không ghi đánh giá lịch sử')
        if model is TramXang and payload.nd_tendangnhap != user.nd_tendangnhap:
            raise HTTPException(403, "Không thể tạo trạm cho doanh nghiệp khác")
        if model is TramXang:
            data=payload.model_dump(exclude={"nd_tendangnhap","tx_ma"})
            return station_approval_service.create_draft(db,user,station_approval_service.validate(data).model_dump())
        return _write(lambda: catalog_service.create_item(db, model, payload.model_dump()))

    def update_resource(resource_id: str, payload: update_schema, db: Session = Depends(get_db), user=Depends(write_guard)):
        if model is DanhGia:
            raise HTTPException(405, 'Đánh giá lịch sử được giữ nguyên')
        if model is TramXang:
            _station_owner(db, resource_id, user)
            if payload.nd_tendangnhap is not None and payload.nd_tendangnhap != user.nd_tendangnhap:
                raise HTTPException(403, "Không thể chuyển quyền sở hữu trạm")
            return station_approval_service.save_draft(db,user,resource_id,payload.model_dump(exclude_unset=True,exclude={"nd_tendangnhap"}))
        item = catalog_service.get_item(db, model, resource_id)
        if item is None:
            raise _not_found(tag)
        return _write(lambda: catalog_service.update_item(db, item, payload.model_dump(exclude_unset=True)))

    def delete_resource(resource_id: str, db: Session = Depends(get_db), user=Depends(write_guard)) -> Response:
        if model is DanhGia:
            raise HTTPException(405, 'Đánh giá lịch sử được giữ nguyên')
        if model is TramXang:
            station_approval_service.delete_draft(db,user,resource_id)
            return Response(status_code=204)
        item = catalog_service.get_item(db, model, resource_id)
        if item is None:
            raise _not_found(tag)
        if model is DichVu:
            catalog_service.ensure_service_unused(db, resource_id)
        _write(lambda: catalog_service.delete_item(db, item))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    list_resources.__name__ = f"list_{pk_name}_{tag.lower()}"
    get_resource.__name__ = f"get_{pk_name}_{tag.lower()}"
    create_resource.__name__ = f"create_{pk_name}_{tag.lower()}"
    update_resource.__name__ = f"update_{pk_name}_{tag.lower()}"
    delete_resource.__name__ = f"delete_{pk_name}_{tag.lower()}"
    router.add_api_route(prefix, list_resources, methods=["GET"], response_model=list[response_schema], tags=[tag])
    router.add_api_route(f"{prefix}/{{resource_id}}", get_resource, methods=["GET"], response_model=response_schema, tags=[tag])
    router.add_api_route(prefix, create_resource, methods=["POST"], status_code=status.HTTP_201_CREATED, response_model=response_schema, tags=[tag])
    router.add_api_route(f"{prefix}/{{resource_id}}", update_resource, methods=["PATCH"], response_model=response_schema, tags=[tag])
    router.add_api_route(f"{prefix}/{{resource_id}}", delete_resource, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT, tags=[tag])


register_crud(prefix="/stations", tag="Stations", model=TramXang, create_schema=TramXangCreate, update_schema=TramXangUpdate, response_schema=TramXangResponse, pk_name="tx_ma")
register_crud(prefix="/fuels", tag="Fuels", model=NhienLieu, create_schema=NhienLieuCreate, update_schema=NhienLieuUpdate, response_schema=NhienLieuResponse, pk_name="nl_ma")
register_crud(prefix="/services", tag="Services", model=DichVu, create_schema=DichVuCreate, update_schema=DichVuUpdate, response_schema=DichVuResponse, pk_name="dv_ma")
register_crud(prefix="/reviews", tag="Reviews", model=DanhGia, create_schema=DanhGiaCreate, update_schema=DanhGiaUpdate, response_schema=DanhGiaResponse, pk_name="dg_ma")
register_crud(prefix="/vehicles", tag="Vehicles", model=PhuongTien, create_schema=PhuongTienCreate, update_schema=PhuongTienUpdate, response_schema=PhuongTienResponse, pk_name="pt_bienso")
register_crud(prefix="/banks", tag="Banks", model=NganHang, create_schema=NganHangCreate, update_schema=NganHangUpdate, response_schema=NganHangResponse, pk_name="nh_ma")


def _price_key(value: str) -> tuple[date, str, str]:
    try:
        raw_date, tx_ma, nl_ma = value.split("|")
        return date.fromisoformat(raw_date), tx_ma, nl_ma
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Price id must be NGAYGIO|TX_MA|NL_MA") from error


@router.get("/prices", response_model=list[GiaResponse], tags=["Prices"])
def list_prices(db: Session = Depends(get_db)):
    return db.scalars(public_related_query(Gia).order_by(Gia.tx_ma,Gia.ngaygio.desc(),Gia.nl_ma)).all()


@router.get("/prices/{price_id}", response_model=GiaResponse, tags=["Prices"])
def get_price(price_id: str, db: Session = Depends(get_db)):
    item = catalog_service.get_item(db, Gia, _price_key(price_id))
    if item is not None and get_public_station(db,item.tx_ma) is None:item=None
    if item is None:
        raise _not_found("Price")
    return item


@router.post("/prices", response_model=GiaResponse, status_code=status.HTTP_201_CREATED, tags=["Prices"])
def create_price(payload: GiaCreate, db: Session = Depends(get_db), user=Depends(require_approved_enterprise)):
    _station_owner(db, payload.tx_ma, user)
    return _write(lambda: catalog_service.create_item(db, Gia, payload.model_dump()))


@router.patch("/prices/{price_id}", response_model=GiaResponse, tags=["Prices"])
def update_price(price_id: str, payload: GiaUpdate, db: Session = Depends(get_db), user=Depends(require_approved_enterprise)):
    _station_owner(db, _price_key(price_id)[1], user)
    item = catalog_service.get_item(db, Gia, _price_key(price_id))
    if item is None:
        raise _not_found("Price")
    return _write(lambda: catalog_service.update_item(db, item, payload.model_dump(exclude_unset=True)))


@router.delete("/prices/{price_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Prices"])
def delete_price(price_id: str, db: Session = Depends(get_db), user=Depends(require_approved_enterprise)) -> Response:
    _station_owner(db, _price_key(price_id)[1], user)
    item = catalog_service.get_item(db, Gia, _price_key(price_id))
    if item is None:
        raise _not_found("Price")
    _write(lambda: catalog_service.delete_item(db, item))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stations/{tx_ma}/services", response_model=list[TxDvResponse], tags=["Station services"])
def list_station_services(tx_ma: str, db: Session = Depends(get_db)):
    if get_public_station(db,tx_ma) is None:raise _not_found("Station")
    return catalog_service.list_station_services(db, tx_ma, TxDv)


@router.post("/stations/{tx_ma}/services/{dv_ma}", response_model=TxDvResponse, status_code=status.HTTP_201_CREATED, tags=["Station services"])
def add_station_service(tx_ma: str, dv_ma: str, db: Session = Depends(get_db), user=Depends(require_approved_enterprise)):
    return amenity_service.assign(db, user, tx_ma, dv_ma)


@router.delete("/stations/{tx_ma}/services/{dv_ma}", status_code=status.HTTP_204_NO_CONTENT, tags=["Station services"])
def remove_station_service(tx_ma: str, dv_ma: str, db: Session = Depends(get_db), user=Depends(require_approved_enterprise)) -> Response:
    amenity_service.remove(db, user, tx_ma, dv_ma)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/enterprise/stations/{tx_ma}/services', response_model=list[TxDvResponse], tags=['Station services'])
def own_station_services(tx_ma: str, db: Session = Depends(get_db), user=Depends(require_approved_enterprise)):
    return amenity_service.list_owned(db, user, tx_ma)


@router.get("/stations/{tx_ma}/prices", response_model=list[GiaResponse], tags=["Station prices"])
def list_station_prices(tx_ma: str, db: Session = Depends(get_db)):
    if get_public_station(db,tx_ma) is None:raise _not_found("Station")
    return catalog_service.list_station_prices(db, tx_ma, Gia)


@router.get("/stations/{tx_ma}/prices/current", response_model=list[GiaResponse], tags=["Station prices"])
def current_station_prices(tx_ma: str, db: Session = Depends(get_db)):
    if get_public_station(db,tx_ma) is None:raise _not_found("Station")
    return catalog_service.current_station_prices(db, tx_ma, Gia)


@router.post("/locations", response_model=ViTriHienTaiResponse, status_code=status.HTTP_201_CREATED, tags=["Locations"])
def create_location(payload: ViTriHienTaiCreate, db: Session = Depends(get_db)):
    return _write(lambda: location_service.create_location(db, payload.model_dump()))


@router.get("/locations/{username}/latest", response_model=ViTriHienTaiResponse, tags=["Locations"])
def latest_location(username: str, db: Session = Depends(get_db)):
    item = location_service.get_latest_location(db, username)
    if item is None:
        raise _not_found("Location")
    return item
