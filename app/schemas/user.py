from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class NguoiDungBase(BaseModel):
    nd_cccd: str | None = Field(default=None, min_length=12, max_length=12)
    nd_ten: str = Field(max_length=32)
    nd_sodienthoai: str = Field(max_length=11)
    nd_email: str = Field(max_length=64)
    nd_gioitinh: bool | None = None


class NguoiDungCreate(NguoiDungBase):
    nd_tendangnhap: str = Field(max_length=32)
    nd_matkhau: str = Field(min_length=6, max_length=256)


class NguoiDungUpdate(BaseModel):
    nd_matkhau: str | None = Field(default=None, min_length=6, max_length=256)
    nd_cccd: str | None = Field(default=None, min_length=12, max_length=12)
    nd_ten: str | None = Field(default=None, max_length=32)
    nd_sodienthoai: str | None = Field(default=None, max_length=11)
    nd_email: str | None = Field(default=None, max_length=64)
    nd_gioitinh: bool | None = None


class NguoiDungResponse(NguoiDungBase):
    nd_tendangnhap: str
    model_config = ConfigDict(from_attributes=True)


class NguoiDungLogin(BaseModel):
    nd_tendangnhap: str = Field(max_length=32)
    nd_matkhau: str = Field(max_length=256)


class KhachHangBase(BaseModel):
    nd_tendangnhap: str = Field(max_length=32)


class KhachHangCreate(KhachHangBase):
    pass


class KhachHangUpdate(BaseModel):
    pass


class KhachHangResponse(KhachHangBase):
    model_config = ConfigDict(from_attributes=True)


class DoanhNghiepBase(BaseModel):
    nd_tendangnhap: str = Field(max_length=32)


class DoanhNghiepCreate(DoanhNghiepBase):
    pass


class DoanhNghiepUpdate(BaseModel):
    pass


class DoanhNghiepResponse(DoanhNghiepBase):
    model_config = ConfigDict(from_attributes=True)


class ViTriHienTaiBase(BaseModel):
    kinhdo: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"), max_digits=11, decimal_places=8)
    vido: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"), max_digits=10, decimal_places=8)


class ViTriHienTaiCreate(ViTriHienTaiBase):
    nd_tendangnhap: str = Field(max_length=32)
    thoigian: datetime


class ViTriHienTaiUpdate(BaseModel):
    kinhdo: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"), max_digits=11, decimal_places=8)
    vido: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"), max_digits=10, decimal_places=8)


class ViTriHienTaiResponse(ViTriHienTaiBase):
    nd_tendangnhap: str
    thoigian: datetime
    model_config = ConfigDict(from_attributes=True)


class LoaiPhuongTienBase(BaseModel):
    lpt_ten: str = Field(max_length=20)


class LoaiPhuongTienCreate(LoaiPhuongTienBase):
    lpt_ma: str = Field(min_length=8, max_length=8)


class LoaiPhuongTienUpdate(BaseModel):
    lpt_ten: str | None = Field(default=None, max_length=20)


class LoaiPhuongTienResponse(LoaiPhuongTienBase):
    lpt_ma: str
    model_config = ConfigDict(from_attributes=True)


class PhuongTienBase(BaseModel):
    lpt_ma: str = Field(min_length=8, max_length=8)
    nd_tendangnhap: str = Field(max_length=32)
    pt_ten: str = Field(max_length=32)


class PhuongTienCreate(PhuongTienBase):
    pt_bienso: str = Field(min_length=12, max_length=12)


class PhuongTienUpdate(BaseModel):
    lpt_ma: str | None = Field(default=None, min_length=8, max_length=8)
    nd_tendangnhap: str | None = Field(default=None, max_length=32)
    pt_ten: str | None = Field(default=None, max_length=32)


class PhuongTienResponse(PhuongTienBase):
    pt_bienso: str
    model_config = ConfigDict(from_attributes=True)
