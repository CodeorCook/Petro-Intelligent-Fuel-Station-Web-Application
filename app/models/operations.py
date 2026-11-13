"""Phase 5.7B staged operational mappings. No startup DDL.

app.models calls the factory only with explicit PostgreSQL operational opt-in.
The active development application's model package has NOT been modified.
Relationships are read-only intentionally: financial commands must set explicit
FK values in one unit of work, not persist through implicit relationship cascades.
"""
from types import SimpleNamespace
from sqlalchemy import (
    Boolean, CHAR, CheckConstraint, Column, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, Numeric, PrimaryKeyConstraint,
    String, UniqueConstraint, false, text, true,
)
from sqlalchemy.orm import relationship

TABLES = ('bon_chua', 'tru_bom', 'tru_bom_nhien_lieu', 'giu_cho_nhien_lieu', 'bien_dong_kho')


def prepare_models(base):
    if any(name in base.metadata.tables for name in TABLES):
        raise ValueError('Operational tables already registered; refuse duplicate mappings')

    def stamp():
        return Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP'))

    def fk(target):
        return ForeignKey(target, ondelete='RESTRICT', onupdate='RESTRICT')

    def check(expression, name):
        return CheckConstraint(expression, name=name)

    class BonChua(base):
        __tablename__ = 'bon_chua'
        __table_args__ = (
            PrimaryKeyConstraint('bc_ma', name='pk_bon_chua'),
            UniqueConstraint('bc_ma', 'tx_ma', 'nl_ma', name='uq_bc_station_fuel'),
            check("bc_ma ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$'", 'ck_bc_id'),
            check('length(btrim(bc_ten)) > 0', 'ck_bc_ten'),
            check("bc_dungtich <> 'NaN' AND bc_dungtich > 0", 'ck_bc_dungtich'),
            check("bc_ton <> 'NaN' AND bc_ton >= 0 AND bc_ton <= bc_dungtich", 'ck_bc_ton'),
            check("bc_giucho <> 'NaN' AND bc_giucho >= 0 AND bc_giucho <= bc_ton", 'ck_bc_giucho'),
            check("bc_nguong <> 'NaN' AND bc_nguong >= 0 AND bc_nguong <= bc_dungtich", 'ck_bc_nguong'),
            check('bc_phienban >= 0', 'ck_bc_phienban'),
            Index('idx_bc_station_fuel', 'tx_ma', 'nl_ma'),
        )
        bc_ma = Column(String(32), nullable=False)
        tx_ma = Column(CHAR(8), fk('tram_xang.tx_ma'), nullable=False)
        nl_ma = Column(CHAR(8), fk('nhien_lieu.nl_ma'), nullable=False)
        bc_ten = Column(String(128), nullable=False)
        bc_dungtich = Column(Numeric(14, 2), nullable=False)
        bc_ton = Column(Numeric(14, 2), nullable=False, server_default=text('0'))
        bc_giucho = Column(Numeric(14, 2), nullable=False, server_default=text('0'))
        bc_nguong = Column(Numeric(14, 2), nullable=False)
        bc_hoatdong = Column(Boolean, nullable=False, server_default=true())
        bc_phienban = Column(Integer, nullable=False, server_default=text('0'))
        bc_ngaytao = stamp()
        bc_ngaycapnhat = stamp()
        tram_xang = relationship('TramXang', viewonly=True, foreign_keys=[tx_ma])
        nhien_lieu = relationship('NhienLieu', viewonly=True, foreign_keys=[nl_ma])
        giu_cho = relationship('GiuChoNhienLieu', back_populates='bon_chua', viewonly=True)
        bien_dong = relationship('BienDongKho', back_populates='bon_chua', viewonly=True)

    class TruBom(base):
        __tablename__ = 'tru_bom'
        __table_args__ = (
            PrimaryKeyConstraint('tb_ma', name='pk_tru_bom'),
            UniqueConstraint('tb_ma', 'tx_ma', name='uq_tb_station'),
            UniqueConstraint('tx_ma', 'tb_code', name='uq_tb_station_code'),
            check("tb_ma ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$'", 'ck_tb_id'),
            check("tb_code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", 'ck_tb_code'),
            check('length(btrim(tb_ten)) > 0', 'ck_tb_ten'),
            check("tb_trangthai IN ('READY','OFFLINE','MAINTENANCE','PUMPING')", 'ck_tb_trangthai'),
            check("tb_mocdau <> 'NaN' AND tb_mocdau >= 0", 'ck_tb_mocdau'),
            check("tb_luyke <> 'NaN' AND tb_luyke >= tb_mocdau", 'ck_tb_luyke'),
            check("(tb_trangthai = 'PUMPING' AND yc_dang_bom IS NOT NULL) OR "
                  "(tb_trangthai <> 'PUMPING' AND yc_dang_bom IS NULL)", 'ck_tb_session'),
            check('tb_phienban >= 0', 'ck_tb_phienban'),
            check("tb_nguon_sha256 IS NULL OR tb_nguon_sha256 ~ '^[0-9a-f]{64}$'", 'ck_tb_sha'),
            Index('uq_tb_one_request', 'yc_dang_bom', unique=True,
                  postgresql_where=text('yc_dang_bom IS NOT NULL')),
        )
        tb_ma = Column(String(32), nullable=False)
        tx_ma = Column(CHAR(8), fk('tram_xang.tx_ma'), nullable=False)
        tb_code = Column(String(32), nullable=False)
        tb_ten = Column(String(128), nullable=False)
        tb_trangthai = Column(String(20), nullable=False, server_default=text("'OFFLINE'"))
        tb_mocdau = Column(Numeric(18, 2), nullable=False)  # Explicit verified baseline, no guessed default.
        tb_luyke = Column(Numeric(18, 2), nullable=False)
        yc_dang_bom = Column(CHAR(8), fk('yeu_cau_do_xang.yc_ma'), nullable=True)
        tb_nguon_sha256 = Column(CHAR(64), nullable=True)
        tb_phienban = Column(Integer, nullable=False, server_default=text('0'))
        tb_ngaytao = stamp()
        tb_ngaycapnhat = stamp()
        tram_xang = relationship('TramXang', viewonly=True, foreign_keys=[tx_ma])
        yeu_cau_dang_bom = relationship('YeuCauDoXang', viewonly=True, foreign_keys=[yc_dang_bom])
        nhien_lieu = relationship('TruBomNhienLieu', back_populates='tru_bom', viewonly=True)

    class TruBomNhienLieu(base):
        __tablename__ = 'tru_bom_nhien_lieu'
        __table_args__ = (
            PrimaryKeyConstraint('tb_ma', 'nl_ma', name='pk_tru_bom_nhien_lieu'),
            UniqueConstraint('tb_ma', 'tx_ma', 'nl_ma', name='uq_tbnl_scope'),
            ForeignKeyConstraint(['tb_ma', 'tx_ma'], ['tru_bom.tb_ma', 'tru_bom.tx_ma'],
                                 name='fk_tbnl_pump_scope', ondelete='RESTRICT', onupdate='RESTRICT'),
            Index('idx_tbnl_station_fuel', 'tx_ma', 'nl_ma'),
        )
        tb_ma = Column(String(32), nullable=False)
        tx_ma = Column(CHAR(8), nullable=False)
        nl_ma = Column(CHAR(8), fk('nhien_lieu.nl_ma'), nullable=False)
        tru_bom = relationship('TruBom', back_populates='nhien_lieu', viewonly=True)
        nhien_lieu = relationship('NhienLieu', viewonly=True, foreign_keys=[nl_ma])

    class GiuChoNhienLieu(base):
        __tablename__ = 'giu_cho_nhien_lieu'
        __table_args__ = (
            PrimaryKeyConstraint('yc_ma', 'nl_ma', 'bc_ma', name='pk_giu_cho_nhien_lieu'),
            ForeignKeyConstraint(['yc_ma', 'nl_ma'], ['chitiet_yeucau.yc_ma', 'chitiet_yeucau.nl_ma'],
                                 name='fk_gc_request_item', ondelete='RESTRICT', onupdate='RESTRICT'),
            ForeignKeyConstraint(['bc_ma', 'tx_ma', 'nl_ma'], ['bon_chua.bc_ma', 'bon_chua.tx_ma', 'bon_chua.nl_ma'],
                                 name='fk_gc_tank_scope', ondelete='RESTRICT', onupdate='RESTRICT'),
            ForeignKeyConstraint(['gia_ngaygio', 'tx_ma', 'nl_ma'], ['gia.ngaygio', 'gia.tx_ma', 'gia.nl_ma'],
                                 name='fk_gc_price_period', ondelete='RESTRICT', onupdate='RESTRICT'),
            check("gc_solit <> 'NaN' AND gc_solit > 0", 'ck_gc_solit'),
            check("gc_dongia <> 'NaN' AND gc_dongia > 0", 'ck_gc_dongia'),
            check("gc_chedo IN ('SO_LIT','SO_TIEN','DO_DAY_BINH')", 'ck_gc_chedo'),
            check("gc_trangthai IN ('GIU_CHO','DA_TIEU_THU','DA_HUY')", 'ck_gc_trangthai'),
            Index('idx_gc_active_tank', 'bc_ma', postgresql_where=text("gc_trangthai = 'GIU_CHO'")),
            Index('idx_gc_station_state', 'tx_ma', 'gc_trangthai'),
        )
        yc_ma = Column(CHAR(8), nullable=False)
        nl_ma = Column(CHAR(8), nullable=False)
        bc_ma = Column(String(32), nullable=False)
        tx_ma = Column(CHAR(8), nullable=False)
        gc_solit = Column(Numeric(8, 2), nullable=False)
        gc_chedo = Column(String(32), nullable=False)
        gia_ngaygio = Column(Date, nullable=False)
        gc_dongia = Column(Numeric(12, 4), nullable=False)
        gc_trangthai = Column(String(20), nullable=False, server_default=text("'GIU_CHO'"))
        nd_tendangnhap = Column(String(32), fk('nguoi_dung.nd_tendangnhap'), nullable=False)
        gc_ngaytao = stamp()
        gc_ngaycapnhat = stamp()
        bon_chua = relationship('BonChua', back_populates='giu_cho', viewonly=True)
        chi_tiet_yeu_cau = relationship('ChiTietYeuCau', viewonly=True)
        gia_thamchieu = relationship('Gia', viewonly=True)
        nguoi_thuchien = relationship('NguoiDung', viewonly=True, foreign_keys=[nd_tendangnhap])
        bien_dong = relationship('BienDongKho', back_populates='giu_cho', viewonly=True)

    class BienDongKho(base):
        __tablename__ = 'bien_dong_kho'
        __table_args__ = (
            PrimaryKeyConstraint('bd_ma', name='pk_bien_dong_kho'),
            UniqueConstraint('bd_khoa_chonglap', name='uq_bd_idempotency'),
            ForeignKeyConstraint(['bc_ma', 'tx_ma', 'nl_ma'], ['bon_chua.bc_ma', 'bon_chua.tx_ma', 'bon_chua.nl_ma'],
                                 name='fk_bd_tank_scope', ondelete='RESTRICT', onupdate='RESTRICT'),
            ForeignKeyConstraint(['tb_ma', 'tx_ma', 'nl_ma'], ['tru_bom_nhien_lieu.tb_ma', 'tru_bom_nhien_lieu.tx_ma', 'tru_bom_nhien_lieu.nl_ma'],
                                 name='fk_bd_pump_fuel_scope', ondelete='RESTRICT', onupdate='RESTRICT'),
            ForeignKeyConstraint(['yc_ma', 'nl_ma', 'bc_ma'], ['giu_cho_nhien_lieu.yc_ma', 'giu_cho_nhien_lieu.nl_ma', 'giu_cho_nhien_lieu.bc_ma'],
                                 name='fk_bd_reservation', ondelete='RESTRICT', onupdate='RESTRICT'),
            ForeignKeyConstraint(['nl_ma', 'gd_ma'], ['chi_tiet_giao_dich.nl_ma', 'chi_tiet_giao_dich.gd_ma'],
                                 name='fk_bd_sale_item', ondelete='RESTRICT', onupdate='RESTRICT'),
            check("bd_loai IN ('NHAP','XUAT','KHOI_TAO_DI_TRU')", 'ck_bd_loai'),
            check('length(btrim(bd_khoa_chonglap)) > 0', 'ck_bd_key'),
            check("bd_solit <> 'NaN' AND bd_solit > 0", 'ck_bd_solit'),
            check("bd_truoc <> 'NaN' AND bd_truoc >= 0 AND bd_sau <> 'NaN' AND bd_sau >= 0", 'ck_bd_balance'),
            check("(bd_loai = 'XUAT' AND bd_sau = bd_truoc - bd_solit) OR "
                  "(bd_loai <> 'XUAT' AND bd_sau = bd_truoc + bd_solit)", 'ck_bd_arithmetic'),
            check("(bd_loai = 'XUAT' AND yc_ma IS NOT NULL AND gd_ma IS NOT NULL) OR "
                  "(bd_loai <> 'XUAT' AND yc_ma IS NULL AND gd_ma IS NULL AND tb_ma IS NULL)", 'ck_bd_sale_refs'),
            check("(bd_loai = 'XUAT' AND tb_ma IS NULL AND length(btrim(coalesce(bd_lydo_khong_tru,''))) > 0) OR "
                  "((bd_loai <> 'XUAT' OR tb_ma IS NOT NULL) AND bd_lydo_khong_tru IS NULL)", 'ck_bd_unassigned'),
            check("(tb_ma IS NULL AND bd_luyke_truoc IS NULL AND bd_luyke_sau IS NULL) OR "
                  "(tb_ma IS NOT NULL AND bd_luyke_truoc IS NOT NULL AND bd_luyke_sau IS NOT NULL "
                  "AND bd_luyke_truoc <> 'NaN' AND bd_luyke_truoc >= 0 "
                  "AND bd_luyke_sau <> 'NaN' AND bd_luyke_sau = bd_luyke_truoc + bd_solit)", 'ck_bd_totalizer'),
            check("(bd_loai = 'KHOI_TAO_DI_TRU' AND bd_truoc = 0 AND bd_nguon_sha256 IS NOT NULL "
                  "AND bd_nguon_key IS NOT NULL) OR (bd_loai <> 'KHOI_TAO_DI_TRU' "
                  "AND bd_nguon_sha256 IS NULL AND bd_nguon_key IS NULL)", 'ck_bd_migration_source'),
            check("bd_nguon_sha256 IS NULL OR bd_nguon_sha256 ~ '^[0-9a-f]{64}$'", 'ck_bd_sha'),
            Index('uq_bd_sale_tank', 'gd_ma', 'nl_ma', 'bc_ma', unique=True,
                  postgresql_where=text("bd_loai = 'XUAT'")),
            Index('uq_bd_opening_tank', 'bc_ma', unique=True,
                  postgresql_where=text("bd_loai = 'KHOI_TAO_DI_TRU'")),
            Index('idx_bd_station_date', 'tx_ma', 'bd_ngaytao'),
            Index('idx_bd_tank_date', 'bc_ma', 'bd_ngaytao'),
            Index('idx_bd_reservation', 'yc_ma', 'nl_ma', 'bc_ma'),
            Index('idx_bd_pump', 'tb_ma'),
        )
        bd_ma = Column(CHAR(12), nullable=False)
        bd_khoa_chonglap = Column(String(128), nullable=False)
        bc_ma = Column(String(32), nullable=False)
        tx_ma = Column(CHAR(8), nullable=False)
        nl_ma = Column(CHAR(8), nullable=False)
        bd_loai = Column(String(20), nullable=False)
        bd_solit = Column(Numeric(14, 2), nullable=False)
        bd_truoc = Column(Numeric(14, 2), nullable=False)
        bd_sau = Column(Numeric(14, 2), nullable=False)
        yc_ma = Column(CHAR(8), nullable=True)
        gd_ma = Column(CHAR(8), nullable=True)
        tb_ma = Column(String(32), nullable=True)
        bd_luyke_truoc = Column(Numeric(18, 2), nullable=True)
        bd_luyke_sau = Column(Numeric(18, 2), nullable=True)
        bd_lydo_khong_tru = Column(String(256), nullable=True)
        bd_nhacungcap = Column(String(256), nullable=True)
        nd_tendangnhap = Column(String(32), fk('nguoi_dung.nd_tendangnhap'), nullable=False)
        bd_nguon_sha256 = Column(CHAR(64), nullable=True)
        bd_nguon_key = Column(String(128), nullable=True)
        bd_ngaytao = stamp()
        bon_chua = relationship('BonChua', back_populates='bien_dong', viewonly=True,
                               foreign_keys=[bc_ma, tx_ma, nl_ma])
        giu_cho = relationship('GiuChoNhienLieu', back_populates='bien_dong', viewonly=True,
                              foreign_keys=[yc_ma, nl_ma, bc_ma])
        tru_bom_nhien_lieu = relationship('TruBomNhienLieu', viewonly=True, foreign_keys=[tb_ma, tx_ma, nl_ma])
        chi_tiet_giao_dich = relationship('ChiTietGiaoDich', viewonly=True, foreign_keys=[nl_ma, gd_ma])
        nguoi_thuchien = relationship('NguoiDung', viewonly=True, foreign_keys=[nd_tendangnhap])

    return SimpleNamespace(BonChua=BonChua, TruBom=TruBom, TruBomNhienLieu=TruBomNhienLieu,
                           GiuChoNhienLieu=GiuChoNhienLieu, BienDongKho=BienDongKho)


