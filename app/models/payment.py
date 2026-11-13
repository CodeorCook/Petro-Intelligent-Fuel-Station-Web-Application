from sqlalchemy import CHAR, Column, ForeignKey, String
from sqlalchemy.orm import relationship

from app.database.base import Base


class NganHang(Base):
    __tablename__ = "ngan_hang"
    nh_ma = Column(CHAR(8), primary_key=True)
    nh_ten = Column(String(64), nullable=False)

    tai_khoan_lien_ket = relationship("TaiKhoanLienKet", back_populates="ngan_hang")


class TaiKhoanLienKet(Base):
    __tablename__ = "tai_khoan_lien_ket"
    tklk_mathe = Column(String(32), primary_key=True)
    nh_ma = Column(CHAR(8), ForeignKey("ngan_hang.nh_ma"), nullable=False)
    nd_tendangnhap = Column(String(32), ForeignKey("nguoi_dung.nd_tendangnhap"), nullable=False)

    ngan_hang = relationship("NganHang", back_populates="tai_khoan_lien_ket")
    nguoi_dung = relationship("NguoiDung", back_populates="tai_khoan_lien_ket")
    giao_dich = relationship("GiaoDich", back_populates="tai_khoan_lien_ket")


class TrangThai(Base):
    __tablename__ = "trang_thai"
    tt_ma = Column(CHAR(8), primary_key=True)
    tt_ten = Column(String(32), nullable=False)

    giao_dich = relationship("GiaoDich", back_populates="trang_thai")
