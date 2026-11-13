from sqlalchemy import CHAR, CheckConstraint, Column, ForeignKey, Numeric, String, Time
from sqlalchemy.orm import relationship

from app.database.base import Base


class TuyenDuong(Base):
    __tablename__ = "tuyen_duong"

    td_ma = Column(CHAR(8), primary_key=True)
    td_ten = Column(String(100), nullable=False)
    td_khu_vuc = Column(String(100), nullable=True)

    he_so_giao_thong = relationship("HeSoGiaoThong", back_populates="tuyen_duong")


class HeSoGiaoThong(Base):
    __tablename__ = "he_so_giao_thong"
    __table_args__ = (
        CheckConstraint("he_so >= 1.0", name="ck_he_so_giao_thong_he_so"),
        CheckConstraint(
            "muc_do IN ('THONG_THOANG', 'XE_DONG', 'UN_TAC_CUC_BO', 'KET_CUNG')",
            name="ck_he_so_giao_thong_muc_do",
        ),
        CheckConstraint("gio_bat_dau <= gio_ket_thuc", name="ck_he_so_giao_thong_khung_gio"),
    )

    hsgt_ma = Column(CHAR(8), primary_key=True)
    td_ma = Column(CHAR(8), ForeignKey("tuyen_duong.td_ma"), nullable=False)
    gio_bat_dau = Column(Time, nullable=False)
    gio_ket_thuc = Column(Time, nullable=False)
    he_so = Column(Numeric(4, 2), nullable=False)
    muc_do = Column(String(20), nullable=False)

    tuyen_duong = relationship("TuyenDuong", back_populates="he_so_giao_thong")
