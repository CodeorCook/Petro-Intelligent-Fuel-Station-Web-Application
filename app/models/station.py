# 7bang: TramXang,DichVu,Lienket giữa TramXang-DichVu,NhienLieu,DonViTinh,ThoiDiem,GiaXangDau
from sqlalchemy import Boolean, CheckConstraint, Column, Index, Integer, String, CHAR, Date, Numeric, ForeignKey, false, text
from sqlalchemy.orm import relationship
from app.database.base import Base


class DonViTinh(Base):
    __tablename__ = "don_vi_tinh"

    dvt_ma = Column(CHAR(8), primary_key=True)
    dvt_ten = Column(String(20), nullable=False)

    nhien_lieu = relationship("NhienLieu", back_populates="don_vi_tinh")


class NhienLieu(Base):
    __tablename__ = "nhien_lieu"

    nl_ma = Column(CHAR(8), primary_key=True)
    dvt_ma = Column(CHAR(8), ForeignKey("don_vi_tinh.dvt_ma"), nullable=False)
    nl_ten = Column(String(64), nullable=False)

    don_vi_tinh = relationship("DonViTinh", back_populates="nhien_lieu")
    bang_gia = relationship("Gia", back_populates="nhien_lieu")
    chi_tiet_giao_dich = relationship("ChiTietGiaoDich", back_populates="nhien_lieu")
    chitiet_yeucau = relationship("ChiTietYeuCau", back_populates="nhien_lieu")


class DichVu(Base):
    __tablename__ = "dich_vu"

    dv_ma = Column(CHAR(8), primary_key=True)
    dv_ten = Column(String(64), nullable=False)

    tx_dv = relationship("TxDv", back_populates="dich_vu")


class TramXang(Base):
    __tablename__ = "tram_xang"
    __table_args__ = (
        CheckConstraint(
            "tx_trangthai IN ('NHAP', 'CHO_DUYET', 'CAN_BO_SUNG', "
            "'TU_CHOI', 'DA_DUYET', 'TAM_NGUNG')",
            name="ck_tram_xang_trangthai",
        ),
        CheckConstraint("tx_congkhai = FALSE OR tx_trangthai = 'DA_DUYET'",
                        name="ck_tram_xang_congkhai"),
        CheckConstraint("tx_phienban_hientai >= 0", name="ck_tram_xang_phienban"),
        Index("idx_tram_xang_congkhai", "nd_tendangnhap",
              postgresql_where=text("tx_trangthai = 'DA_DUYET' AND tx_congkhai = TRUE"),
              sqlite_where=text("tx_trangthai = 'DA_DUYET' AND tx_congkhai = TRUE")),
    )

    tx_ma = Column(CHAR(8), primary_key=True)
    # CHANGE: FK doi tu doanh_nghiep.nd_cccd sang doanh_nghiep.nd_tendangnhap
    nd_tendangnhap = Column(String(32), ForeignKey(
        "doanh_nghiep.nd_tendangnhap", ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=False)
    tx_ten = Column(String(64), nullable=False)
    tx_diachi = Column(String(128), nullable=False)
    # CHANGE: tx_toado (chuoi gop) -> tach thanh 2 cot Numeric rieng
    tx_kinhdo = Column(Numeric(11, 8), nullable=False)
    tx_vido = Column(Numeric(10, 8), nullable=False)
    tx_coconluon = Column(Boolean, nullable=True, default=False, server_default=false())
    tx_trucduong = Column(String(64), nullable=True)
    tx_trangthai = Column(String(20), nullable=False, server_default=text("'NHAP'"))
    tx_congkhai = Column(Boolean, nullable=False, server_default=false())
    tx_du_lieu_cu = Column(Boolean, nullable=False, server_default=false())
    tx_phienban_hientai = Column(Integer, nullable=False, server_default=text("0"))

    doanh_nghiep = relationship("DoanhNghiep", back_populates="tram_xang")
    tx_dv = relationship("TxDv", back_populates="tram_xang")
    bang_gia = relationship("Gia", back_populates="tram_xang")
    danh_gia = relationship("DanhGia", back_populates="tram_xang")
    yeu_cau_do_xang = relationship("YeuCauDoXang", back_populates="tram_xang")
    yeu_cau_duyet_tram = relationship("YeuCauDuyetTram", back_populates="tram_xang")


class TxDv(Base):
    __tablename__ = "tx_dv"

    dv_ma = Column(CHAR(8), ForeignKey("dich_vu.dv_ma"), primary_key=True)
    tx_ma = Column(CHAR(8), ForeignKey("tram_xang.tx_ma"), primary_key=True)

    dich_vu = relationship("DichVu", back_populates="tx_dv")
    tram_xang = relationship("TramXang", back_populates="tx_dv")


class ThoiDiem(Base):
    __tablename__ = "thoi_diem"

    # CHANGE: doi ten cot tu "ngay" sang "ngaygio" (van la kieu Date, khong co gio)
    ngaygio = Column(Date, primary_key=True)

    bang_gia = relationship("Gia", back_populates="thoi_diem")
    giao_dich = relationship("GiaoDich", back_populates="thoi_diem")
    danh_gia = relationship("DanhGia", back_populates="thoi_diem")


class Gia(Base):
    __tablename__ = "gia"

    ngaygio = Column(Date, ForeignKey("thoi_diem.ngaygio"), primary_key=True)
    tx_ma = Column(CHAR(8), ForeignKey("tram_xang.tx_ma"), primary_key=True)
    nl_ma = Column(CHAR(8), ForeignKey("nhien_lieu.nl_ma"), primary_key=True)
    dongia = Column(Numeric(12, 4), nullable=False)

    thoi_diem = relationship("ThoiDiem", back_populates="bang_gia")
    tram_xang = relationship("TramXang", back_populates="bang_gia")
    nhien_lieu = relationship("NhienLieu", back_populates="bang_gia")
