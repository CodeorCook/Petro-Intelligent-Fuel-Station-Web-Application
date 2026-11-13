from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Quantity = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
Positive = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
Identifier = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')]

class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class TankCreate(Command):
    bc_ma: Identifier
    bc_ten: str = Field(min_length=1, max_length=128)
    nl_ma: str = Field(pattern=r'^NL00000[123]$')
    bc_dungtich: Positive
    bc_nguong: Quantity
    @model_validator(mode='after')
    def valid_capacity(self):
        if self.bc_nguong > self.bc_dungtich:
            raise ValueError('Ngưỡng cảnh báo không được vượt dung tích')
        return self

class TankUpdate(Command):
    bc_phienban: int = Field(ge=0)
    bc_ten: str | None = Field(default=None, min_length=1, max_length=128)
    bc_dungtich: Positive | None = None
    bc_nguong: Quantity | None = None
    bc_hoatdong: bool | None = None

class PumpCreate(Command):
    tb_ma: Identifier
    tb_code: str = Field(pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')
    tb_ten: str = Field(min_length=1,max_length=128)
    nl_ma: list[str] = Field(min_length=1,max_length=3)
    tb_mocdau: Decimal = Field(ge=0,max_digits=18,decimal_places=2,allow_inf_nan=False)
    baseline_confirmed: Literal[True]
    tb_trangthai: Literal['READY','OFFLINE','MAINTENANCE'] = 'OFFLINE'
    @model_validator(mode='after')
    def unique_fuels(self):
        if len(set(self.nl_ma)) != len(self.nl_ma) or not set(self.nl_ma) <= {'NL000001','NL000002','NL000003'}:
            raise ValueError('Danh sách nhiên liệu không hợp lệ hoặc bị trùng')
        return self

class PumpUpdate(Command):
    tb_phienban: int = Field(ge=0)
    tb_ten: str | None = Field(default=None,min_length=1,max_length=128)
    tb_trangthai: Literal['READY','OFFLINE','MAINTENANCE'] | None = None
    nl_ma: list[str] | None = Field(default=None,min_length=1,max_length=3)

class Refill(Command):
    tx_ma: str = Field(min_length=1,max_length=8)
    tank_id: Identifier
    liters: Positive
    supplier: str | None = Field(default=None,max_length=256)
    operation_key: str = Field(min_length=8,max_length=96,pattern=r'^[A-Za-z0-9:_-]+$')

class Accept(Command):
    pump_id: Identifier
    maximum_liters: Annotated[Decimal,Field(gt=0,max_digits=8,decimal_places=2,allow_inf_nan=False)] | None = None

class Reserve(Command):
    maximum_liters: Annotated[Decimal,Field(gt=0,max_digits=8,decimal_places=2,allow_inf_nan=False)] | None = None

class Start(Command):
    pump_id: Identifier

class Closure(Command):
    reason: str = Field(min_length=1,max_length=256)
    confirm_no_dispense: bool = False

class Complete(Command):
    so_lit_thuc_te: Annotated[Decimal,Field(gt=0,max_digits=8,decimal_places=2,allow_inf_nan=False)]
    so_tien_thuc_te: Decimal | None = Field(default=None,gt=0,max_digits=12,decimal_places=4,allow_inf_nan=False)
    dongia: Decimal | None = Field(default=None,gt=0,max_digits=12,decimal_places=4,allow_inf_nan=False)
