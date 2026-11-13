from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models import DichVu, TxDv, NhienLieu
from app.core.fuel_order import ordered_fuels

logger = logging.getLogger(__name__)


class ConflictError(Exception):
    """A database constraint prevented a requested write."""


def list_service_catalog(db):
    """Public read-only stable catalog contract: list of dv_ma/dv_ten DTOs."""
    try:
        return db.scalars(select(DichVu).order_by(DichVu.dv_ma)).all()
    except SQLAlchemyError as error:
        logger.warning('Amenity catalog database read failed')
        raise HTTPException(503, 'Danh mục tiện ích tạm thời không khả dụng. Vui lòng thử lại.') from error


def ensure_service_unused(db, service_id):
    # Hold the catalog row lock until delete commit. A concurrent TX_DV insert
    # cannot acquire its FK key-share lock between this check and the deletion.
    db.scalars(select(DichVu).where(DichVu.dv_ma == service_id).with_for_update()).first()
    if db.scalar(select(TxDv.dv_ma).where(TxDv.dv_ma == service_id).limit(1)) is not None:
        raise HTTPException(409, 'Tiện ích đang được trạm sử dụng; không thể xóa danh mục.')


def list_items(db: Session, model: type[Any]) -> Sequence[Any]:
    rows = db.scalars(select(model)).all()
    return ordered_fuels(rows, lambda r:r.nl_ma) if model is NhienLieu else rows


def get_item(db: Session, model: type[Any], identifier: Any) -> Any | None:
    return db.get(model, identifier)


def get_one(db: Session, statement: Select[tuple[Any]]) -> Any | None:
    return db.scalars(statement).first()


def create_item(db: Session, model: type[Any], values: dict[str, Any]) -> Any:
    item = model(**values)
    db.add(item)
    _commit(db)
    db.refresh(item)
    return item


def update_item(db: Session, item: Any, values: dict[str, Any]) -> Any:
    for field, value in values.items():
        setattr(item, field, value)
    _commit(db)
    db.refresh(item)
    return item


def delete_item(db: Session, item: Any) -> None:
    db.delete(item)
    _commit(db)


def list_station_services(db: Session, tx_ma: str, association_model: type[Any]) -> Sequence[Any]:
    return db.scalars(select(association_model).where(association_model.tx_ma == tx_ma)).all()


def list_station_prices(db: Session, tx_ma: str, price_model: type[Any]) -> Sequence[Any]:
    statement = select(price_model).where(price_model.tx_ma == tx_ma).order_by(desc(price_model.ngaygio))
    return db.scalars(statement.order_by(price_model.nl_ma)).all()


def current_station_prices(db: Session, tx_ma: str, price_model: type[Any]) -> Sequence[Any]:
    latest_date = db.scalar(
        select(price_model.ngaygio).where(price_model.tx_ma == tx_ma).order_by(desc(price_model.ngaygio)).limit(1)
    )
    if latest_date is None:
        return []
    return db.scalars(select(price_model).where(price_model.tx_ma == tx_ma, price_model.ngaygio == latest_date).order_by(price_model.nl_ma)).all()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ConflictError from error
