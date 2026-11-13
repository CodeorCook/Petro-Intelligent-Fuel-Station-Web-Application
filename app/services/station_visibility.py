"""Shared publication predicate equivalent to V_TRAM_XANG_CONG_KHAI."""
from sqlalchemy import and_,exists,select
from app.models import DoanhNghiep,TramXang


def public_condition():
    return and_(TramXang.tx_trangthai=="DA_DUYET",TramXang.tx_congkhai.is_(True),
                exists(select(DoanhNghiep.nd_tendangnhap).where(
                    DoanhNghiep.nd_tendangnhap==TramXang.nd_tendangnhap,
                    DoanhNghiep.dn_trangthai=="DA_DUYET")))


def public_station_query():return select(TramXang).where(public_condition())


def get_public_station(db,station_id):
    return db.scalars(public_station_query().where(TramXang.tx_ma==station_id)).first()


def public_related_query(model):
    return select(model).where(exists(select(TramXang.tx_ma).where(
        TramXang.tx_ma==model.tx_ma,public_condition())))
