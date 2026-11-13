import re

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=3, max_length=64)
    phone: str = Field(min_length=8, max_length=11)
    password: str = Field(min_length=8, max_length=128, repr=False)

    @field_validator("name", "email", "phone", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            email = validate_email(value.lower(), check_deliverability=False).normalized.lower()
        except EmailNotValidError as error:
            raise ValueError("Email không hợp lệ") from error
        if len(email) > 64:
            raise ValueError("Email không được vượt quá 64 ký tự")
        return email

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not re.fullmatch(r"\+?[0-9]{8,11}", value):
            raise ValueError("Số điện thoại không hợp lệ")
        return value


class CustomerRegistrationResponse(BaseModel):
    status: str = "success"
    message: str = "Đăng ký thành công. Vui lòng đăng nhập."
    username: str
    redirect_url: str = "/DangNhap.html"


class EnterpriseRegistrationRequest(CustomerRegistrationRequest):
    """Same validated account fields; public role is fixed by endpoint."""


class EnterpriseRegistrationResponse(CustomerRegistrationResponse):
    message: str = "Tài khoản doanh nghiệp đã được tạo. Vui lòng đăng nhập để xem trạng thái."
