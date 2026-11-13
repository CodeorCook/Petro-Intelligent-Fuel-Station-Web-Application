"""Mappings for the already-applied QTV approval migration v2.

PostgreSQL uses JSONB and timezone-aware timestamps. The JSON variant and
conditional JSONB CHECK only support the existing disposable SQLite tests;
PostgreSQL metadata retains the canonical JSONB/object constraint.
"""

from sqlalchemy import (
    BigInteger, CHAR, CheckConstraint, Column, DateTime, ForeignKey,
    Index, Integer, JSON, PrimaryKeyConstraint, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.base import Base


class QuanTriVien(Base):
    __tablename__ = "quan_tri_vien"
    __table_args__ = (PrimaryKeyConstraint("nd_tendangnhap", name="pk_quan_tri_vien"),)

    nd_tendangnhap = Column(String(32), ForeignKey(
        "nguoi_dung.nd_tendangnhap", name="fk_quan_tri_vien_nguoi_dung",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=False)

    nguoi_dung = relationship("NguoiDung", back_populates="quan_tri_vien")
    yeu_cau_duyet_doanh_nghiep = relationship(
        "YeuCauDuyetDoanhNghiep", back_populates="quan_tri_vien",
        foreign_keys="YeuCauDuyetDoanhNghiep.qtv_tendangnhap",
    )
    yeu_cau_duyet_tram = relationship(
        "YeuCauDuyetTram", back_populates="quan_tri_vien",
        foreign_keys="YeuCauDuyetTram.qtv_tendangnhap",
    )


class HoSoDoanhNghiep(Base):
    __tablename__ = "ho_so_doanh_nghiep"
    __table_args__ = (
        PrimaryKeyConstraint("hsdn_ma", name="pk_ho_so_doanh_nghiep"),
        UniqueConstraint("nd_tendangnhap", name="uq_ho_so_doanh_nghiep_nd"),
        UniqueConstraint("hsdn_masothue", name="uq_ho_so_doanh_nghiep_mst"),
    )

    hsdn_ma = Column(CHAR(12), nullable=False)
    nd_tendangnhap = Column(String(32), ForeignKey(
        "doanh_nghiep.nd_tendangnhap", name="fk_ho_so_doanh_nghiep_doanh_nghiep",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=False)
    hsdn_tenphaply = Column(String(128), nullable=True)
    hsdn_masothue = Column(String(20), nullable=True)
    hsdn_diachi = Column(String(256), nullable=True)
    hsdn_nguoidaidien = Column(String(128), nullable=True)
    hsdn_sodienthoai = Column(String(11), nullable=True)
    hsdn_email = Column(String(128), nullable=True)
    hsdn_ngaycapnhat = Column(DateTime(timezone=True), nullable=False,
                             server_default=text("CURRENT_TIMESTAMP"))

    doanh_nghiep = relationship("DoanhNghiep", back_populates="ho_so_doanh_nghiep")
    yeu_cau_duyet_doanh_nghiep = relationship(
        "YeuCauDuyetDoanhNghiep", back_populates="ho_so_doanh_nghiep",
    )


class YeuCauDuyetDoanhNghiep(Base):
    __tablename__ = "yeu_cau_duyet_doanh_nghiep"
    __table_args__ = (
        PrimaryKeyConstraint("ycdn_ma", name="pk_yeu_cau_duyet_doanh_nghiep"),
        UniqueConstraint("hsdn_ma", "ycdn_lan_gui", name="uq_ycdn_lan_gui"),
        CheckConstraint("ycdn_lan_gui >= 1", name="ck_ycdn_lan_gui"),
        CheckConstraint("jsonb_typeof(ycdn_dulieu) = 'object'", name="ck_ycdn_dulieu")
        .ddl_if(dialect="postgresql"),
        CheckConstraint(
            "ycdn_trangthai IN ('CHO_DUYET', 'CAN_BO_SUNG', 'TU_CHOI', 'DA_DUYET')",
            name="ck_ycdn_trangthai",
        ),
        CheckConstraint(
            "(ycdn_trangthai = 'CHO_DUYET' AND qtv_tendangnhap IS NULL "
            "AND ycdn_ngayxuly IS NULL) OR (ycdn_trangthai <> 'CHO_DUYET' "
            "AND qtv_tendangnhap IS NOT NULL AND ycdn_ngayxuly IS NOT NULL)",
            name="ck_ycdn_xuly",
        ),
        Index("idx_ycdn_hsdn_ma", "hsdn_ma"),
        Index("idx_ycdn_qtv", "qtv_tendangnhap"),
        Index("idx_ycdn_trangthai_ngaygui", "ycdn_trangthai", "ycdn_ngaygui"),
        Index("uq_ycdn_mot_cho_duyet", "hsdn_ma", unique=True,
              postgresql_where=text("ycdn_trangthai = 'CHO_DUYET'"),
              sqlite_where=text("ycdn_trangthai = 'CHO_DUYET'")),
    )

    ycdn_ma = Column(CHAR(12), nullable=False)
    hsdn_ma = Column(CHAR(12), ForeignKey(
        "ho_so_doanh_nghiep.hsdn_ma", name="fk_ycdn_ho_so_doanh_nghiep",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=False)
    ycdn_lan_gui = Column(Integer, nullable=False)
    ycdn_dulieu = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    ycdn_trangthai = Column(String(20), nullable=False, server_default=text("'CHO_DUYET'"))
    ycdn_ngaygui = Column(DateTime(timezone=True), nullable=False,
                          server_default=text("CURRENT_TIMESTAMP"))
    qtv_tendangnhap = Column(String(32), ForeignKey(
        "quan_tri_vien.nd_tendangnhap", name="fk_ycdn_quan_tri_vien",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=True)
    ycdn_ngayxuly = Column(DateTime(timezone=True), nullable=True)
    ycdn_lydo = Column(Text, nullable=True)

    ho_so_doanh_nghiep = relationship("HoSoDoanhNghiep", back_populates="yeu_cau_duyet_doanh_nghiep")
    quan_tri_vien = relationship("QuanTriVien", back_populates="yeu_cau_duyet_doanh_nghiep",
                                 foreign_keys=[qtv_tendangnhap])
    tep_minh_chung = relationship("TepMinhChung", back_populates="yeu_cau_duyet_doanh_nghiep",
                                  foreign_keys="TepMinhChung.ycdn_ma")


class YeuCauDuyetTram(Base):
    __tablename__ = "yeu_cau_duyet_tram"
    __table_args__ = (
        PrimaryKeyConstraint("ycdt_ma", name="pk_yeu_cau_duyet_tram"),
        UniqueConstraint("tx_ma", "ycdt_lan_gui", name="uq_ycdt_lan_gui"),
        CheckConstraint("ycdt_lan_gui >= 1", name="ck_ycdt_lan_gui"),
        CheckConstraint("ycdt_loai IN ('DANG_KY_MOI', 'CAP_NHAT')", name="ck_ycdt_loai"),
        CheckConstraint("jsonb_typeof(ycdt_dulieu) = 'object'", name="ck_ycdt_dulieu")
        .ddl_if(dialect="postgresql"),
        CheckConstraint(
            "ycdt_trangthai IN ('CHO_DUYET', 'CAN_BO_SUNG', 'TU_CHOI', 'DA_DUYET')",
            name="ck_ycdt_trangthai",
        ),
        CheckConstraint(
            "(ycdt_trangthai = 'CHO_DUYET' AND qtv_tendangnhap IS NULL "
            "AND ycdt_ngayxuly IS NULL) OR (ycdt_trangthai <> 'CHO_DUYET' "
            "AND qtv_tendangnhap IS NOT NULL AND ycdt_ngayxuly IS NOT NULL)",
            name="ck_ycdt_xuly",
        ),
        Index("idx_ycdt_tx_ma", "tx_ma"),
        Index("idx_ycdt_qtv", "qtv_tendangnhap"),
        Index("idx_ycdt_trangthai_ngaygui", "ycdt_trangthai", "ycdt_ngaygui"),
        Index("uq_ycdt_mot_cho_duyet", "tx_ma", unique=True,
              postgresql_where=text("ycdt_trangthai = 'CHO_DUYET'"),
              sqlite_where=text("ycdt_trangthai = 'CHO_DUYET'")),
    )

    ycdt_ma = Column(CHAR(12), nullable=False)
    tx_ma = Column(CHAR(8), ForeignKey(
        "tram_xang.tx_ma", name="fk_ycdt_tram_xang",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=False)
    ycdt_lan_gui = Column(Integer, nullable=False)
    ycdt_loai = Column(String(20), nullable=False)
    ycdt_dulieu = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    ycdt_trangthai = Column(String(20), nullable=False, server_default=text("'CHO_DUYET'"))
    ycdt_ngaygui = Column(DateTime(timezone=True), nullable=False,
                          server_default=text("CURRENT_TIMESTAMP"))
    qtv_tendangnhap = Column(String(32), ForeignKey(
        "quan_tri_vien.nd_tendangnhap", name="fk_ycdt_quan_tri_vien",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=True)
    ycdt_ngayxuly = Column(DateTime(timezone=True), nullable=True)
    ycdt_lydo = Column(Text, nullable=True)

    tram_xang = relationship("TramXang", back_populates="yeu_cau_duyet_tram")
    quan_tri_vien = relationship("QuanTriVien", back_populates="yeu_cau_duyet_tram",
                                 foreign_keys=[qtv_tendangnhap])
    tep_minh_chung = relationship("TepMinhChung", back_populates="yeu_cau_duyet_tram",
                                  foreign_keys="TepMinhChung.ycdt_ma")


class TepMinhChung(Base):
    __tablename__ = "tep_minh_chung"
    __table_args__ = (
        PrimaryKeyConstraint("tmc_ma", name="pk_tep_minh_chung"),
        CheckConstraint("(ycdn_ma IS NOT NULL) <> (ycdt_ma IS NOT NULL)",
                        name="ck_tmc_chi_mot_yeu_cau"),
        CheckConstraint("tmc_kich_thuoc IS NULL OR tmc_kich_thuoc >= 0",
                        name="ck_tmc_kich_thuoc"),
        Index("idx_tmc_ycdn", "ycdn_ma"),
        Index("idx_tmc_ycdt", "ycdt_ma"),
    )

    tmc_ma = Column(CHAR(12), nullable=False)
    ycdn_ma = Column(CHAR(12), ForeignKey(
        "yeu_cau_duyet_doanh_nghiep.ycdn_ma", name="fk_tmc_ycdn",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=True)
    ycdt_ma = Column(CHAR(12), ForeignKey(
        "yeu_cau_duyet_tram.ycdt_ma", name="fk_tmc_ycdt",
        ondelete="RESTRICT", onupdate="RESTRICT",
    ), nullable=True)
    tmc_ten = Column(String(255), nullable=False)
    tmc_duongdan = Column(String(512), nullable=False)
    tmc_mime = Column(String(100), nullable=True)
    tmc_kich_thuoc = Column(BigInteger, nullable=True)
    tmc_sha256 = Column(CHAR(64), nullable=True)
    tmc_ngaytai = Column(DateTime(timezone=True), nullable=False,
                         server_default=text("CURRENT_TIMESTAMP"))

    yeu_cau_duyet_doanh_nghiep = relationship(
        "YeuCauDuyetDoanhNghiep", back_populates="tep_minh_chung", foreign_keys=[ycdn_ma],
    )
    yeu_cau_duyet_tram = relationship(
        "YeuCauDuyetTram", back_populates="tep_minh_chung", foreign_keys=[ycdt_ma],
    )
