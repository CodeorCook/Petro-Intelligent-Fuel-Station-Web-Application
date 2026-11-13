from app.models.user import (
    NguoiDung,
    KhachHang,
    DoanhNghiep,
    ViTriHienTai,
    LoaiPhuongTien,
    PhuongTien,
)
from app.models.payment import (
    NganHang,
    TaiKhoanLienKet,
    TrangThai,
)
from app.models.station import (
    DonViTinh,
    NhienLieu,
    DichVu,
    TramXang,
    TxDv,
    ThoiDiem,
    Gia,
)
from app.models.transaction import (
    GiaoDich,
    ChiTietGiaoDich,
)
from app.models.review import (
    DanhGia,
)
from app.models.request import (
    TrangThaiXacNhan,
    YeuCauDoXang,
    ChiTietYeuCau,
)
from app.models.traffic import TuyenDuong, HeSoGiaoThong
from app.models.approval import (
    QuanTriVien, HoSoDoanhNghiep, YeuCauDuyetDoanhNghiep,
    YeuCauDuyetTram, TepMinhChung,
)

__all__ = [
    "NguoiDung",
    "KhachHang",
    "DoanhNghiep",
    "ViTriHienTai",
    "LoaiPhuongTien",
    "PhuongTien",
    "NganHang",
    "TaiKhoanLienKet",
    "TrangThai",
    "DonViTinh",
    "NhienLieu",
    "DichVu",
    "TramXang",
    "TxDv",
    "ThoiDiem",
    "Gia",
    "GiaoDich",
    "ChiTietGiaoDich",
    "DanhGia",
    "TrangThaiXacNhan",
    "YeuCauDoXang",
    "ChiTietYeuCau",
    "TuyenDuong",
    "HeSoGiaoThong",
    "QuanTriVien",
    "HoSoDoanhNghiep",
    "YeuCauDuyetDoanhNghiep",
    "YeuCauDuyetTram",
    "TepMinhChung",
]

# Isolated Phase 5.7B opt-in only. No startup DDL or implicit operational seeding.
import os as _os
if _os.getenv('PETRO_OPERATIONAL_STORAGE') != 'postgresql':
    try:
        from app.core.development_startup import configure_development
        configure_development()
    except Exception:
        pass

if _os.getenv('PETRO_OPERATIONAL_STORAGE') == 'postgresql':
    from app.database.base import Base as _Base
    from app.models.operations import prepare_models as _prepare_models
    _operations = _prepare_models(_Base)
    for _name in ('BonChua', 'TruBom', 'TruBomNhienLieu', 'GiuChoNhienLieu', 'BienDongKho'):
        globals()[_name] = getattr(_operations, _name)
        __all__.append(_name)
