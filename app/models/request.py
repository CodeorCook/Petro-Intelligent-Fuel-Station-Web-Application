from datetime import datetime
from sqlalchemy import Column, String, CHAR, Numeric, ForeignKey, DateTime, Index, CheckConstraint, text
from sqlalchemy.orm import relationship
from app.database.base import Base


class TrangThaiXacNhan(Base):
    __tablename__ = "trang_thai_xac_nhan"

    ttxn_ma = Column(CHAR(8), primary_key=True)
    ttxn_ten = Column(String(20), nullable=False)

    yeu_cau_do_xang = relationship("YeuCauDoXang", back_populates="trang_thai_xac_nhan")


class YeuCauDoXang(Base):
    __tablename__ = "yeu_cau_do_xang"
    __table_args__ = (Index("idx_yeu_cau_do_xang_pt_bienso", "pt_bienso"),
        Index('idx_yc_waiting_deadline','yc_het_han_luc','tx_ma','yc_ma',postgresql_where=text("ttxn_ma='TTXN0001' AND yc_het_han_luc IS NOT NULL")),
        # PostgreSQL is authoritative; SQLite fixture databases do not implement btrim.
        CheckConstraint("ttxn_ma NOT IN ('TTXN0006','TTXN0007') OR (yc_dong_luc IS NOT NULL AND length(btrim(yc_lydo_dong))>0 AND yc_lydo_dong IS NOT NULL)",name='ck_yc_terminal_metadata').ddl_if(dialect='postgresql'))

    yc_ma = Column(CHAR(8), primary_key=True)
    ttxn_ma = Column(CHAR(8), ForeignKey("trang_thai_xac_nhan.ttxn_ma"), nullable=False)
    tx_ma = Column(CHAR(8), ForeignKey("tram_xang.tx_ma"), nullable=False)
    nd_tendangnhap = Column(String(32), ForeignKey("khach_hang.nd_tendangnhap"), nullable=False)
    pt_bienso = Column(CHAR(12), ForeignKey(
        "phuong_tien.pt_bienso", name="fk_yeu_cau_do_xang_phuong_tien",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=True)
    hinh_thuc_do_xang = Column(String(32), nullable=True)
    thoi_gian_tao = Column(DateTime, default=datetime.now, nullable=True)
    yc_het_han_luc = Column(DateTime(timezone=True),nullable=True)
    yc_dong_luc = Column(DateTime(timezone=True),nullable=True)
    yc_dong_boi = Column(String(32),ForeignKey('nguoi_dung.nd_tendangnhap',name='fk_yc_closed_actor',ondelete='RESTRICT',onupdate='RESTRICT'),nullable=True)
    yc_lydo_dong = Column(String(256),nullable=True)

    trang_thai_xac_nhan = relationship("TrangThaiXacNhan", back_populates="yeu_cau_do_xang")
    tram_xang = relationship("TramXang", back_populates="yeu_cau_do_xang")
    khach_hang = relationship("KhachHang", back_populates="yeu_cau_do_xang")
    phuong_tien = relationship("PhuongTien")
    chitiet_yeucau = relationship("ChiTietYeuCau", back_populates="yeu_cau_do_xang")
    giao_dich = relationship("GiaoDich", back_populates="yeu_cau_do_xang")


class ChiTietYeuCau(Base):
    """Chi tiet loai nhien lieu/so luong trong 1 yeu cau do xang.
    soluong/thanhtien cho phep NULL vi luc moi gui yeu cau co the chua
    chot duoc so lit chinh xac (chi chot sau khi bom xong)."""
    __tablename__ = "chitiet_yeucau"

    nl_ma = Column(CHAR(8), ForeignKey("nhien_lieu.nl_ma"), primary_key=True)
    yc_ma = Column(CHAR(8), ForeignKey("yeu_cau_do_xang.yc_ma"), primary_key=True)
    soluong = Column(Numeric(8, 2), nullable=True)
    thanhtien = Column(Numeric(12, 4), nullable=True)

    nhien_lieu = relationship("NhienLieu", back_populates="chitiet_yeucau")
    yeu_cau_do_xang = relationship("YeuCauDoXang", back_populates="chitiet_yeucau")
