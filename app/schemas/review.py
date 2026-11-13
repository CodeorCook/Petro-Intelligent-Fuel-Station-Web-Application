from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class DanhGiaBase(BaseModel):
    nd_tendangnhap: str = Field(max_length=32)
    tx_ma: str = Field(min_length=8, max_length=8)
    ngaygio: date
    dg_noidung: str
    dg_mucdo: int = Field(ge=1, le=5)


class DanhGiaCreate(DanhGiaBase):
    dg_ma: str = Field(min_length=8, max_length=8)


class DanhGiaUpdate(BaseModel):
    nd_tendangnhap: str | None = Field(default=None, max_length=32)
    tx_ma: str | None = Field(default=None, min_length=8, max_length=8)
    ngaygio: date | None = None
    dg_noidung: str | None = None
    dg_mucdo: int | None = Field(default=None, ge=1, le=5)


class DanhGiaResponse(DanhGiaBase):
    dg_ma: str
    model_config = ConfigDict(from_attributes=True)
