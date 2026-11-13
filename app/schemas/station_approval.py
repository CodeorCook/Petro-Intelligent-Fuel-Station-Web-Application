from datetime import datetime
from decimal import Decimal
from typing import Any,Literal,Annotated
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator,StringConstraints
from app.schemas.enterprise_approval import EnterpriseEvidenceResponse

STATION_FIELDS=("tx_ten","tx_diachi","tx_kinhdo","tx_vido","tx_coconluon","tx_trucduong")
AmenityId = Annotated[str, StringConstraints(min_length=8, max_length=8)]


class DraftAmenitySetInput(BaseModel):
    """Replace one private draft set atomically; expected IDs prevent stale writes."""
    model_config = ConfigDict(extra="forbid")
    service_ids: list[AmenityId] = Field(max_length=50)
    expected_amenity_ids: list[AmenityId] = Field(max_length=50)

    @field_validator("service_ids", "expected_amenity_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Mã tiện ích bị trùng")
        return value


class StationDraftInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tx_ten:str=Field(min_length=1,max_length=64)
    tx_diachi:str=Field(min_length=1,max_length=128)
    tx_kinhdo:Decimal=Field(ge=-180,le=180,max_digits=11,decimal_places=8)
    tx_vido:Decimal=Field(ge=-90,le=90,max_digits=10,decimal_places=8)
    tx_coconluon:bool|None=False
    tx_trucduong:str|None=Field(None,max_length=64)

    @field_validator("tx_ten","tx_diachi","tx_trucduong",mode="before")
    @classmethod
    def trim(cls,value):
        if isinstance(value,str):
            if any(ord(c)<32 for c in value):raise ValueError("Thông tin trạm chứa ký tự không hợp lệ")
            return value.strip()
        return value


class StationDraftPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tx_ten:str|None=Field(None,min_length=1,max_length=64)
    tx_diachi:str|None=Field(None,min_length=1,max_length=128)
    tx_kinhdo:Decimal|None=Field(None,ge=-180,le=180,max_digits=11,decimal_places=8)
    tx_vido:Decimal|None=Field(None,ge=-90,le=90,max_digits=10,decimal_places=8)
    tx_coconluon:bool|None=None
    tx_trucduong:str|None=Field(None,max_length=64)

    @model_validator(mode="after")
    def no_null_required(self):
        if any(getattr(self,k) is None for k in self.model_fields_set if k not in {"tx_trucduong","tx_coconluon"}):
            raise ValueError("Tên, địa chỉ và GPS không được null")
        return self


class StationSubmissionInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    evidence_tokens:list[str]=Field(min_length=1,max_length=10)
    proposed_values:StationDraftPatch|None=None
    base_version:int|None=Field(None,ge=0)
    # None preserves the relation set; [] explicitly proposes removing all.
    proposed_amenity_ids:list[AmenityId]|None=Field(None,max_length=50)
    # Optional for old clients; the draft UI sends its last persisted set.
    expected_amenity_ids:list[AmenityId]|None=Field(None,max_length=50)

    @field_validator('proposed_amenity_ids', 'expected_amenity_ids')
    @classmethod
    def unique_amenities(cls,value):
        if value is not None and len(set(value))!=len(value):
            raise ValueError('Mã tiện ích bị trùng trong tập đề xuất')
        return value


class OwnedStationResponse(StationDraftInput):
    model_config=ConfigDict(from_attributes=True)
    tx_ma:str
    tx_coconluon:bool|None=None
    nd_tendangnhap:str
    tx_trangthai:str
    tx_congkhai:bool
    tx_du_lieu_cu:bool
    tx_phienban_hientai:int


class StationApprovalResponse(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    ycdt_ma:str
    tx_ma:str
    ycdt_lan_gui:int
    ycdt_loai:Literal["DANG_KY_MOI","CAP_NHAT"]
    ycdt_dulieu:dict[str,Any]
    ycdt_trangthai:Literal["CHO_DUYET","CAN_BO_SUNG","TU_CHOI","DA_DUYET"]
    ycdt_ngaygui:datetime
    qtv_tendangnhap:str|None
    ycdt_ngayxuly:datetime|None
    ycdt_lydo:str|None
    tep_minh_chung:list[EnterpriseEvidenceResponse]=Field(default_factory=list)
