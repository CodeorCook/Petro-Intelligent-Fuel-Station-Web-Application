from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ChiTietGiaoDichBase(BaseModel):
    nl_ma: str = Field(min_length=8, max_length=8)
    gd_ma: str = Field(min_length=8, max_length=8)
    soluong: Decimal = Field(gt=Decimal("0"), max_digits=8, decimal_places=2)
    thanhtien: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=4)
    dongialucban: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=4)


class ChiTietGiaoDichCreate(ChiTietGiaoDichBase):
    pass


class ChiTietGiaoDichUpdate(BaseModel):
    soluong: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=8, decimal_places=2)
    thanhtien: Decimal | None = Field(default=None, ge=Decimal("0"), max_digits=12, decimal_places=4)
    dongialucban: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=12, decimal_places=4)


class ChiTietGiaoDichResponse(ChiTietGiaoDichBase):
    model_config = ConfigDict(from_attributes=True)


class GiaoDichBase(BaseModel):
    nd_tendangnhap: str = Field(max_length=32)
    tklk_mathe: str = Field(max_length=32)
    tt_ma: str = Field(min_length=8, max_length=8)
    ngaygio: date
    yc_ma: str = Field(min_length=8, max_length=8)
    gd_sotien: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=4)
    gd_mathamchieu: str = Field(max_length=64)


class GiaoDichCreate(GiaoDichBase):
    gd_ma: str = Field(min_length=8, max_length=8)
    chi_tiet_giao_dich: list[ChiTietGiaoDichCreate] = Field(default_factory=list)


class GiaoDichUpdate(BaseModel):
    nd_tendangnhap: str | None = Field(default=None, max_length=32)
    tklk_mathe: str | None = Field(default=None, max_length=32)
    tt_ma: str | None = Field(default=None, min_length=8, max_length=8)
    ngaygio: date | None = None
    yc_ma: str | None = Field(default=None, min_length=8, max_length=8)
    gd_sotien: Decimal | None = Field(default=None, ge=Decimal("0"), max_digits=12, decimal_places=4)
    gd_mathamchieu: str | None = Field(default=None, max_length=64)


class GiaoDichResponse(GiaoDichBase):
    gd_ma: str
    tklk_mathe: str | None = Field(default=None, max_length=32)
    tx_ma: str | None = Field(default=None, min_length=8, max_length=8)
    pttt_ten: str | None = Field(default=None, max_length=32)
    chi_tiet_giao_dich: list[ChiTietGiaoDichResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class TransactionItemInput(BaseModel):
    nl_ma: str = Field(min_length=8, max_length=8)
    soluong: Decimal = Field(gt=Decimal("0"), max_digits=8, decimal_places=2)
    thanhtien: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=4)
    dongialucban: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=4)


class TransactionCreateInput(GiaoDichBase):
    gd_ma: str | None = Field(default=None, min_length=8, max_length=8)
    items: list[TransactionItemInput] = Field(min_length=1)
