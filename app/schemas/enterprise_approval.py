import re
from datetime import datetime
from typing import Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ApprovalState = Literal["CHO_DUYET", "CAN_BO_SUNG", "TU_CHOI", "DA_DUYET"]
PROFILE_LIMITS = {"hsdn_tenphaply":128, "hsdn_masothue":20, "hsdn_diachi":256,
                  "hsdn_nguoidaidien":128, "hsdn_sodienthoai":11, "hsdn_email":128}


class EnterpriseProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hsdn_tenphaply: str | None = Field(None, max_length=128)
    hsdn_masothue: str | None = Field(None, max_length=20)
    hsdn_diachi: str | None = Field(None, max_length=256)
    hsdn_nguoidaidien: str | None = Field(None, max_length=128)
    hsdn_sodienthoai: str | None = Field(None, max_length=11)
    hsdn_email: str | None = Field(None, max_length=128)

    @field_validator("*", mode="before")
    @classmethod
    def clean(cls, value, info):
        if isinstance(value,str) and info.field_name in PROFILE_LIMITS:
            value=value.strip()
            if any(ord(c)<32 or ord(c)==127 for c in value):
                raise ValueError("Thông tin hồ sơ không được chứa ký tự điều khiển")
            if len(value)>PROFILE_LIMITS[info.field_name]:
                raise ValueError(f"{info.field_name} vượt quá {PROFILE_LIMITS[info.field_name]} ký tự")
            return value or None
        return value

    @field_validator("hsdn_masothue")
    @classmethod
    def tax(cls,value):
        if value is not None and not re.fullmatch(r"[0-9]{10}(?:-?[0-9]{3})?",value):
            raise ValueError("Mã số thuế phải có 10 chữ số hoặc mã đơn vị phụ thuộc 13 chữ số")
        return value[:10]+"-"+value[10:] if value is not None and len(value)==13 else value

    @field_validator("hsdn_sodienthoai")
    @classmethod
    def phone(cls,value):
        if value is not None and not re.fullmatch(r"\+?[0-9]{8,11}",value):
            raise ValueError("Số điện thoại liên hệ không hợp lệ")
        return value

    @field_validator("hsdn_email")
    @classmethod
    def email(cls,value):
        if value is None:return None
        try:
            normalized=validate_email(value.lower(),check_deliverability=False).normalized.lower()
            if len(normalized)>128:raise ValueError("Email liên hệ vượt quá 128 ký tự")
            return normalized
        except EmailNotValidError as error:raise ValueError("Email liên hệ không hợp lệ") from error


class EnterpriseProfileResponse(EnterpriseProfileDraft):
    model_config = ConfigDict(from_attributes=True)
    hsdn_ma: str
    nd_tendangnhap: str
    hsdn_ngaycapnhat: datetime


class EnterpriseSubmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_tokens: list[str] = Field(min_length=1,max_length=10)

    @field_validator("evidence_tokens")
    @classmethod
    def unique_tokens(cls,values):
        if len(set(values))!=len(values) or any(not re.fullmatch(r"[0-9a-f]{32}",v) for v in values):
            raise ValueError("Danh sách minh chứng trùng lặp hoặc mã không hợp lệ")
        return values


class EnterpriseDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["DA_DUYET","CAN_BO_SUNG","TU_CHOI"]
    reason: str | None = Field(None,max_length=4000)

    @model_validator(mode="after")
    def require_reason(self):
        self.reason=self.reason.strip() if self.reason else None
        if self.decision!="DA_DUYET" and not self.reason:
            raise ValueError("Cần nêu lý do từ chối hoặc yêu cầu bổ sung")
        return self


class EnterpriseEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tmc_ma: str
    tmc_ten: str
    tmc_mime: str | None
    tmc_kich_thuoc: int | None
    tmc_sha256: str | None
    tmc_ngaytai: datetime


class EnterpriseApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ycdn_ma: str
    hsdn_ma: str
    ycdn_lan_gui: int
    ycdn_dulieu: dict[str,Any]
    ycdn_trangthai: ApprovalState
    ycdn_ngaygui: datetime
    qtv_tendangnhap: str | None
    ycdn_ngayxuly: datetime | None
    ycdn_lydo: str | None
    tep_minh_chung: list[EnterpriseEvidenceResponse] = Field(default_factory=list)
