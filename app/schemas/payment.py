from pydantic import BaseModel, ConfigDict, Field


class NganHangBase(BaseModel):
    nh_ten: str = Field(max_length=64)


class NganHangCreate(NganHangBase):
    nh_ma: str = Field(min_length=8, max_length=8)


class NganHangUpdate(BaseModel):
    nh_ten: str | None = Field(default=None, max_length=64)


class NganHangResponse(NganHangBase):
    nh_ma: str
    model_config = ConfigDict(from_attributes=True)


class TaiKhoanLienKetBase(BaseModel):
    nh_ma: str = Field(min_length=8, max_length=8)
    nd_tendangnhap: str = Field(max_length=32)


class TaiKhoanLienKetCreate(TaiKhoanLienKetBase):
    tklk_mathe: str = Field(max_length=32)


class TaiKhoanLienKetUpdate(BaseModel):
    nh_ma: str | None = Field(default=None, min_length=8, max_length=8)
    nd_tendangnhap: str | None = Field(default=None, max_length=32)


class TaiKhoanLienKetResponse(TaiKhoanLienKetBase):
    tklk_mathe: str
    model_config = ConfigDict(from_attributes=True)


class TrangThaiBase(BaseModel):
    tt_ten: str = Field(max_length=32)


class TrangThaiCreate(TrangThaiBase):
    tt_ma: str = Field(min_length=8, max_length=8)


class TrangThaiUpdate(BaseModel):
    tt_ten: str | None = Field(default=None, max_length=32)


class TrangThaiResponse(TrangThaiBase):
    tt_ma: str
    model_config = ConfigDict(from_attributes=True)
