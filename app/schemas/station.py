from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DonViTinhBase(BaseModel):
    dvt_ten: str = Field(max_length=20)


class DonViTinhCreate(DonViTinhBase):
    dvt_ma: str = Field(min_length=8, max_length=8)


class DonViTinhUpdate(BaseModel):
    dvt_ten: str | None = Field(default=None, max_length=20)


class DonViTinhResponse(DonViTinhBase):
    dvt_ma: str
    model_config = ConfigDict(from_attributes=True)


class NhienLieuBase(BaseModel):
    dvt_ma: str = Field(min_length=8, max_length=8)
    nl_ten: str = Field(max_length=64)


class NhienLieuCreate(NhienLieuBase):
    nl_ma: str = Field(min_length=8, max_length=8)


class NhienLieuUpdate(BaseModel):
    dvt_ma: str | None = Field(default=None, min_length=8, max_length=8)
    nl_ten: str | None = Field(default=None, max_length=64)


class NhienLieuResponse(NhienLieuBase):
    nl_ma: str
    model_config = ConfigDict(from_attributes=True)


class DichVuBase(BaseModel):
    dv_ten: str = Field(max_length=64)


class DichVuCreate(DichVuBase):
    dv_ma: str = Field(min_length=8, max_length=8)


class DichVuUpdate(BaseModel):
    dv_ten: str | None = Field(default=None, max_length=64)


class DichVuResponse(DichVuBase):
    dv_ma: str
    model_config = ConfigDict(from_attributes=True)


class TxDvBase(BaseModel):
    dv_ma: str = Field(min_length=8, max_length=8)
    tx_ma: str = Field(min_length=8, max_length=8)


class TxDvCreate(TxDvBase):
    pass


class TxDvUpdate(BaseModel):
    pass


class TxDvResponse(TxDvBase):
    model_config = ConfigDict(from_attributes=True)


class ThoiDiemBase(BaseModel):
    ngaygio: date


class ThoiDiemCreate(ThoiDiemBase):
    pass


class ThoiDiemUpdate(BaseModel):
    pass


class ThoiDiemResponse(ThoiDiemBase):
    model_config = ConfigDict(from_attributes=True)


class GiaBase(BaseModel):
    ngaygio: date
    tx_ma: str = Field(min_length=8, max_length=8)
    nl_ma: str = Field(min_length=8, max_length=8)
    dongia: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=4)


class GiaCreate(GiaBase):
    pass


class GiaUpdate(BaseModel):
    dongia: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=12, decimal_places=4)


class GiaResponse(GiaBase):
    model_config = ConfigDict(from_attributes=True)


class TramXangBase(BaseModel):
    nd_tendangnhap: str = Field(max_length=32)
    tx_ten: str = Field(max_length=64)
    tx_diachi: str = Field(max_length=128)
    tx_kinhdo: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"), max_digits=11, decimal_places=8)
    tx_vido: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"), max_digits=10, decimal_places=8)
    tx_coconluon: bool = False
    tx_trucduong: str | None = Field(default=None, max_length=64)


class TramXangCreate(TramXangBase):
    tx_ma: str = Field(min_length=8, max_length=8)


class TramXangUpdate(BaseModel):
    nd_tendangnhap: str | None = Field(default=None, max_length=32)
    tx_ten: str | None = Field(default=None, max_length=64)
    tx_diachi: str | None = Field(default=None, max_length=128)
    tx_kinhdo: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"), max_digits=11, decimal_places=8)
    tx_vido: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"), max_digits=10, decimal_places=8)
    tx_coconluon: bool | None = None
    tx_trucduong: str | None = Field(default=None, max_length=64)


class TramXangResponse(TramXangBase):
    tx_ma: str
    tx_coconluon: bool | None = None
    model_config = ConfigDict(from_attributes=True)


class TramXangDetailResponse(TramXangResponse):
    tx_dv: list[TxDvResponse] = Field(default_factory=list)
    bang_gia: list[GiaResponse] = Field(default_factory=list)
