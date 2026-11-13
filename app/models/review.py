# 1bang: DanhGia
from sqlalchemy import Column, CHAR, Date, Text, SmallInteger, String, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base import Base


class DanhGia(Base):
    __tablename__ = "danh_gia"

    dg_ma = Column(CHAR(8), primary_key=True)
    # CHANGE: tk_ma (bang TaiKhoan) -> nd_tendangnhap (bang NguoiDung)
    nd_tendangnhap = Column(String(32), ForeignKey("nguoi_dung.nd_tendangnhap"), nullable=False)
    tx_ma = Column(CHAR(8), ForeignKey("tram_xang.tx_ma"), nullable=False)
    # CHANGE: doi ten cot tu "ngay" sang "ngaygio"
    ngaygio = Column(Date, ForeignKey("thoi_diem.ngaygio"), nullable=False)
    dg_noidung = Column(Text, nullable=False)
    dg_mucdo = Column(SmallInteger, nullable=False)

    nguoi_dung = relationship("NguoiDung", back_populates="danh_gia")
    tram_xang = relationship("TramXang", back_populates="danh_gia")
    thoi_diem = relationship("ThoiDiem", back_populates="danh_gia")
