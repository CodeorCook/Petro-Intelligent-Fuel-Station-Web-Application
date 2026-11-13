from sqlalchemy import CHAR, Column, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import relationship

from app.database.base import Base


class GiaoDich(Base):
    __tablename__ = "giao_dich"
    __table_args__ = (Index("idx_giao_dich_tx_ma", "tx_ma"),)
    gd_ma = Column(CHAR(8), primary_key=True)
    nd_tendangnhap = Column(String(32), ForeignKey("nguoi_dung.nd_tendangnhap"), nullable=False)
    tklk_mathe = Column(String(32), ForeignKey("tai_khoan_lien_ket.tklk_mathe"), nullable=True)
    tt_ma = Column(CHAR(8), ForeignKey("trang_thai.tt_ma"), nullable=False)
    ngaygio = Column(Date, ForeignKey("thoi_diem.ngaygio"), nullable=False)
    yc_ma = Column(CHAR(8), ForeignKey("yeu_cau_do_xang.yc_ma"), nullable=False)
    tx_ma = Column(CHAR(8), ForeignKey(
        "tram_xang.tx_ma", name="fk_giao_dich_tram_xang",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=True)
    gd_sotien = Column(Numeric(12, 4), nullable=False)
    gd_mathamchieu = Column(String(64), nullable=False)
    pttt_ten = Column(String(32), nullable=True, default="VIETQR", server_default="VIETQR")

    nguoi_dung = relationship("NguoiDung", back_populates="giao_dich")
    tai_khoan_lien_ket = relationship("TaiKhoanLienKet", back_populates="giao_dich")
    trang_thai = relationship("TrangThai", back_populates="giao_dich")
    thoi_diem = relationship("ThoiDiem", back_populates="giao_dich")
    yeu_cau_do_xang = relationship("YeuCauDoXang", back_populates="giao_dich")
    tram_xang = relationship("TramXang")
    chi_tiet_giao_dich = relationship("ChiTietGiaoDich", back_populates="giao_dich")


class ChiTietGiaoDich(Base):
    __tablename__ = "chi_tiet_giao_dich"
    nl_ma = Column(CHAR(8), ForeignKey("nhien_lieu.nl_ma"), primary_key=True)
    gd_ma = Column(CHAR(8), ForeignKey("giao_dich.gd_ma"), primary_key=True)
    soluong = Column(Numeric(8, 2), nullable=False)
    thanhtien = Column(Numeric(12, 4), nullable=False)
    dongialucban = Column(Numeric(12, 4), nullable=False)

    nhien_lieu = relationship("NhienLieu", back_populates="chi_tiet_giao_dich")
    giao_dich = relationship("GiaoDich", back_populates="chi_tiet_giao_dich")
