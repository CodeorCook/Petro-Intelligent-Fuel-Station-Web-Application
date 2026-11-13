from datetime import time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TuyenDuongBase(BaseModel):
    td_ten: str = Field(max_length=100)
    td_khu_vuc: str | None = Field(default=None, max_length=100)


class TuyenDuongCreate(TuyenDuongBase):
    td_ma: str = Field(min_length=8, max_length=8)


class TuyenDuongUpdate(BaseModel):
    td_ten: str | None = Field(default=None, max_length=100)
    td_khu_vuc: str | None = Field(default=None, max_length=100)


class TuyenDuongResponse(TuyenDuongBase):
    td_ma: str
    model_config = ConfigDict(from_attributes=True)


class HeSoGiaoThongBase(BaseModel):
    td_ma: str = Field(min_length=8, max_length=8)
    gio_bat_dau: time
    gio_ket_thuc: time
    he_so: Decimal = Field(ge=Decimal("1.0"), max_digits=4, decimal_places=2)
    muc_do: str = Field(max_length=20, pattern="^(THONG_THOANG|XE_DONG|UN_TAC_CUC_BO|KET_CUNG)$")

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.gio_bat_dau > self.gio_ket_thuc:
            raise ValueError("gio_bat_dau must be before or equal to gio_ket_thuc")
        return self


class HeSoGiaoThongCreate(HeSoGiaoThongBase):
    hsgt_ma: str = Field(min_length=8, max_length=8)


class HeSoGiaoThongUpdate(BaseModel):
    td_ma: str | None = Field(default=None, min_length=8, max_length=8)
    gio_bat_dau: time | None = None
    gio_ket_thuc: time | None = None
    he_so: Decimal | None = Field(default=None, ge=Decimal("1.0"), max_digits=4, decimal_places=2)
    muc_do: str | None = Field(default=None, max_length=20, pattern="^(THONG_THOANG|XE_DONG|UN_TAC_CUC_BO|KET_CUNG)$")


class HeSoGiaoThongResponse(HeSoGiaoThongBase):
    hsgt_ma: str
    model_config = ConfigDict(from_attributes=True)
