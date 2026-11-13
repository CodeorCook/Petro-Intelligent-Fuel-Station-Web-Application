from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ViTriHienTai
from app.services.catalog import create_item


def create_location(db: Session, values: dict) -> ViTriHienTai:
    return create_item(db, ViTriHienTai, values)


def get_latest_location(db: Session, username: str) -> ViTriHienTai | None:
    statement = (
        select(ViTriHienTai)
        .where(ViTriHienTai.nd_tendangnhap == username)
        .order_by(desc(ViTriHienTai.thoigian))
        .limit(1)
    )
    return db.scalars(statement).first()
