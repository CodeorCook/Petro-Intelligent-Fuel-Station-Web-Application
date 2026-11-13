from datetime import datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import HeSoGiaoThong, TuyenDuong


class TrafficError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def lookup_traffic_factor(
    road_name_or_id: str, check_time: time | None = None, *, db: Session
) -> dict[str, Any]:
    """Look up a configured factor; intervals and factors always come from the DB."""
    road = db.scalars(
        select(TuyenDuong)
        .where(or_(TuyenDuong.td_ma == road_name_or_id, TuyenDuong.td_ten.ilike(f"%{road_name_or_id}%")))
        .order_by(TuyenDuong.td_ma)
    ).first()
    current_time = check_time or datetime.now().time()
    fallback = {
        "td_ma": road.td_ma if road else None,
        "td_ten": road.td_ten if road else None,
        "check_time": current_time,
        "he_so": Decimal("1.00"),
        "muc_do": "THONG_THOANG",
    }
    if road is None:
        return fallback
    factor = db.scalars(
        select(HeSoGiaoThong)
        .where(
            HeSoGiaoThong.td_ma == road.td_ma,
            HeSoGiaoThong.gio_bat_dau <= current_time,
            HeSoGiaoThong.gio_ket_thuc >= current_time,
        )
        .order_by(HeSoGiaoThong.he_so.desc())
    ).first()
    if factor is None:
        return fallback
    return {
        "td_ma": road.td_ma,
        "td_ten": road.td_ten,
        "check_time": current_time,
        "he_so": factor.he_so,
        "muc_do": factor.muc_do,
        "hsgt_ma": factor.hsgt_ma,
    }


def list_roads(db: Session) -> list[TuyenDuong]:
    return db.scalars(select(TuyenDuong).order_by(TuyenDuong.td_ma)).all()


def get_road(db: Session, road_id: str) -> TuyenDuong:
    return _require(db.get(TuyenDuong, road_id), "Road")


def create_road(db: Session, values: dict[str, Any]) -> TuyenDuong:
    return _save(db, TuyenDuong(**values))


def update_road(db: Session, road_id: str, values: dict[str, Any]) -> TuyenDuong:
    road = get_road(db, road_id)
    for field, value in values.items():
        setattr(road, field, value)
    return _save(db, road)


def delete_road(db: Session, road_id: str) -> None:
    db.delete(get_road(db, road_id))
    _save(db)


def list_traffic_factors(db: Session, road_id: str | None = None) -> list[HeSoGiaoThong]:
    statement = select(HeSoGiaoThong).order_by(HeSoGiaoThong.td_ma, HeSoGiaoThong.gio_bat_dau)
    if road_id is not None:
        statement = statement.where(HeSoGiaoThong.td_ma == road_id)
    return db.scalars(statement).all()


def get_traffic_factor(db: Session, factor_id: str) -> HeSoGiaoThong:
    return _require(db.get(HeSoGiaoThong, factor_id), "Traffic factor")


def create_traffic_factor(db: Session, values: dict[str, Any]) -> HeSoGiaoThong:
    _require(db.get(TuyenDuong, values["td_ma"]), "Road")
    return _save(db, HeSoGiaoThong(**values))


def update_traffic_factor(db: Session, factor_id: str, values: dict[str, Any]) -> HeSoGiaoThong:
    factor = get_traffic_factor(db, factor_id)
    if "td_ma" in values:
        _require(db.get(TuyenDuong, values["td_ma"]), "Road")
    for field, value in values.items():
        setattr(factor, field, value)
    if factor.gio_bat_dau > factor.gio_ket_thuc:
        raise TrafficError(400, "gio_bat_dau must be before or equal to gio_ket_thuc")
    return _save(db, factor)


def delete_traffic_factor(db: Session, factor_id: str) -> None:
    db.delete(get_traffic_factor(db, factor_id))
    _save(db)


def _require(value: Any | None, label: str) -> Any:
    if value is None:
        raise TrafficError(404, f"{label} not found")
    return value


def _save(db: Session, item: Any | None = None) -> Any | None:
    if item is not None:
        db.add(item)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise TrafficError(409, "Request conflicts with database constraints") from error
    if item is not None:
        db.refresh(item)
    return item
