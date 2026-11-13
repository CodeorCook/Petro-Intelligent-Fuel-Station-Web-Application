from sqlalchemy import CHAR, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Numeric, String, false, text
from sqlalchemy.orm import relationship

from app.database.base import Base


class NguoiDung(Base):
    __tablename__ = "nguoi_dung"
    nd_tendangnhap = Column(String(32), primary_key=True)
    nd_matkhau = Column(String(256), nullable=False)
    nd_cccd = Column(CHAR(12), nullable=True)
    nd_ten = Column(String(32), nullable=False)
    nd_sodienthoai = Column(String(11), nullable=False)
    nd_email = Column(String(64), nullable=False)
    nd_gioitinh = Column(Boolean, nullable=True)

    khach_hang = relationship("KhachHang", back_populates="nguoi_dung", uselist=False)
    doanh_nghiep = relationship("DoanhNghiep", back_populates="nguoi_dung", uselist=False)
    quan_tri_vien = relationship("QuanTriVien", back_populates="nguoi_dung", uselist=False)
    giao_dich = relationship("GiaoDich", back_populates="nguoi_dung")
    tai_khoan_lien_ket = relationship("TaiKhoanLienKet", back_populates="nguoi_dung")
    danh_gia = relationship("DanhGia", back_populates="nguoi_dung")
    vi_tri_hien_tai = relationship("ViTriHienTai", back_populates="nguoi_dung")


class KhachHang(Base):
    __tablename__ = "khach_hang"
    nd_tendangnhap = Column(String(32), ForeignKey("nguoi_dung.nd_tendangnhap"), primary_key=True)

    nguoi_dung = relationship("NguoiDung", back_populates="khach_hang")
    phuong_tien = relationship("PhuongTien", back_populates="khach_hang")
    yeu_cau_do_xang = relationship("YeuCauDoXang", back_populates="khach_hang")


class DoanhNghiep(Base):
    __tablename__ = "doanh_nghiep"
    __table_args__ = (
        CheckConstraint(
            "dn_trangthai IN ('CHUA_HOAN_THIEN', 'CHO_DUYET', 'CAN_BO_SUNG', "
            "'TU_CHOI', 'DA_DUYET', 'TAM_KHOA')",
            name="ck_doanh_nghiep_trangthai",
        ),
    )
    nd_tendangnhap = Column(String(32), ForeignKey(
        "nguoi_dung.nd_tendangnhap", ondelete="RESTRICT", onupdate="RESTRICT",
    ), primary_key=True)
    dn_trangthai = Column(String(20), nullable=False, server_default=text("'CHUA_HOAN_THIEN'"))
    dn_du_lieu_cu = Column(Boolean, nullable=False, server_default=false())

    nguoi_dung = relationship("NguoiDung", back_populates="doanh_nghiep")
    tram_xang = relationship("TramXang", back_populates="doanh_nghiep")
    ho_so_doanh_nghiep = relationship("HoSoDoanhNghiep", back_populates="doanh_nghiep", uselist=False)


class ViTriHienTai(Base):
    __tablename__ = "vi_tri_hien_tai"
    nd_tendangnhap = Column(String(32), ForeignKey("nguoi_dung.nd_tendangnhap"), primary_key=True)
    thoigian = Column(DateTime, primary_key=True)
    kinhdo = Column(Numeric(11, 8), nullable=False)
    vido = Column(Numeric(10, 8), nullable=False)

    nguoi_dung = relationship("NguoiDung", back_populates="vi_tri_hien_tai")


class LoaiPhuongTien(Base):
    __tablename__ = "loai_phuong_tien"
    lpt_ma = Column(CHAR(8), primary_key=True)
    lpt_ten = Column(String(20), nullable=False)

    phuong_tien = relationship("PhuongTien", back_populates="loai_phuong_tien")


class PhuongTien(Base):
    __tablename__ = "phuong_tien"
    pt_bienso = Column(CHAR(12), primary_key=True)
    lpt_ma = Column(CHAR(8), ForeignKey("loai_phuong_tien.lpt_ma"), nullable=False)
    nd_tendangnhap = Column(String(32), ForeignKey("khach_hang.nd_tendangnhap"), nullable=False)
    pt_ten = Column(String(32), nullable=False)

    loai_phuong_tien = relationship("LoaiPhuongTien", back_populates="phuong_tien")
    khach_hang = relationship("KhachHang", back_populates="phuong_tien")
