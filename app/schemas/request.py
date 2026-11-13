from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TrangThaiXacNhanBase(BaseModel):
    ttxn_ten: str = Field(max_length=20)


class TrangThaiXacNhanCreate(TrangThaiXacNhanBase):
    ttxn_ma: str = Field(min_length=8, max_length=8)


class TrangThaiXacNhanUpdate(BaseModel):
    ttxn_ten: str | None = Field(default=None, max_length=20)


class TrangThaiXacNhanResponse(TrangThaiXacNhanBase):
    ttxn_ma: str
    model_config = ConfigDict(from_attributes=True)


class ChiTietYeuCauBase(BaseModel):
    yc_ma: str = Field(min_length=8, max_length=8)
    nl_ma: str = Field(min_length=8, max_length=8)
    soluong: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=8, decimal_places=2)
    thanhtien: Decimal | None = Field(default=None, ge=Decimal("0"), max_digits=12, decimal_places=4)


class ChiTietYeuCauCreate(ChiTietYeuCauBase):
    pass


class ChiTietYeuCauUpdate(BaseModel):
    soluong: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=8, decimal_places=2)
    thanhtien: Decimal | None = Field(default=None, ge=Decimal("0"), max_digits=12, decimal_places=4)


class ChiTietYeuCauResponse(ChiTietYeuCauBase):
    model_config = ConfigDict(from_attributes=True)


class YeuCauDoXangBase(BaseModel):
    ttxn_ma: str = Field(min_length=8, max_length=8)
    tx_ma: str = Field(min_length=8, max_length=8)
    nd_tendangnhap: str = Field(max_length=32)


class YeuCauDoXangCreate(YeuCauDoXangBase):
    yc_ma: str = Field(min_length=8, max_length=8)
    pt_bienso: str | None = Field(default=None, max_length=12)
    hinh_thuc_do_xang: str | None = Field(default=None, max_length=32)
    chitiet_yeucau: list[ChiTietYeuCauCreate] = Field(default_factory=list)


class YeuCauDoXangUpdate(BaseModel):
    ttxn_ma: str | None = Field(default=None, min_length=8, max_length=8)
    tx_ma: str | None = Field(default=None, min_length=8, max_length=8)
    nd_tendangnhap: str | None = Field(default=None, max_length=32)


class YeuCauDoXangResponse(YeuCauDoXangBase):
    yc_ma: str
    pt_bienso: str | None = Field(default=None, max_length=12)
    hinh_thuc_do_xang: str | None = Field(default=None, max_length=32)
    thoi_gian_tao: datetime | None = None
    yc_het_han_luc: datetime | None = None
    yc_dong_luc: datetime | None = None
    yc_dong_boi: str | None = None
    yc_lydo_dong: str | None = None
    chitiet_yeucau: list[ChiTietYeuCauResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class FuelRequestItemInput(BaseModel):
    nl_ma: str = Field(min_length=8, max_length=8)
    soluong: Decimal = Field(gt=Decimal("0"), max_digits=8, decimal_places=2)
    thanhtien: Decimal | None = Field(default=None, ge=Decimal("0"), max_digits=12, decimal_places=4)


class FuelRequestCreateInput(YeuCauDoXangBase):
    yc_ma: str | None = Field(default=None, min_length=8, max_length=8)
    pt_bienso: str | None = Field(default=None, max_length=12)
    hinh_thuc_do_xang: str | None = Field(default=None, max_length=32)
    items: list[FuelRequestItemInput] = Field(min_length=1)


class FuelRequestStatusUpdate(BaseModel):
    """Accepts either TTXN_MA or TTXN_TEN from the database."""
    status: str = Field(min_length=1, max_length=20)
