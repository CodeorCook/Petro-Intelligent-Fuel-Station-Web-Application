import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.user import NguoiDung

# Secret key for session token signing (persisted in env or fallback)
SECRET_KEY = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_NAME = "petro_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days
logger = logging.getLogger(__name__)


# ==========================================================
# 1. Password Verification & Hashing
# ==========================================================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify only the supported salt:PBKDF2-HMAC-SHA256 format."""
    if not plain_password or not isinstance(hashed_password, str):
        return False
    if not re.fullmatch(r"[0-9a-f]{32}:[0-9a-f]{64}", hashed_password):
        return False
    salt, stored_hash = hashed_password.split(":", 1)
    derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return hmac.compare_digest(derived.hex(), stored_hash)


def hash_password(password: str) -> str:
    """Generate salted PBKDF2-HMAC-SHA256 password hash."""
    salt = os.urandom(16).hex()
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}:{derived.hex()}"


# ==========================================================
# 2. Session Token (Signed Base64 JSON)
# ==========================================================
def create_session_token(data: dict[str, Any], expires_in: int = SESSION_MAX_AGE) -> str:
    payload = {
        **data,
        "exp": int(time.time()) + expires_in,
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_session_token(token: str) -> Optional[dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, signature = parts
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None

        # Add padding back if necessary
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(payload_bytes.decode("utf-8"))

        if payload.get("exp", 0) < time.time():
            return None  # Expired
        return payload
    except Exception:
        return None


# ==========================================================
# 3. Role Detection Helper
# ==========================================================
def get_user_role(user: NguoiDung) -> tuple[str, str]:
    """Resolve exactly one database subtype; session/client role is never authority."""
    roles = [
        (code, label) for code, label, member in (
            ("KHACH_HANG", "Khách hàng", user.khach_hang),
            ("DOANH_NGHIEP", "Doanh nghiệp", user.doanh_nghiep),
            ("QUAN_TRI_VIEN", "Quản trị viên", user.quan_tri_vien),
        ) if member is not None
    ]
    if len(roles) > 1:
        logger.warning("Authorization denied: multiple actor subtypes on one account")
        raise HTTPException(403, "Tài khoản có vai trò không nhất quán. Vui lòng liên hệ hỗ trợ.")
    if roles:
        return roles[0]
    raise HTTPException(status_code=403, detail="Tài khoản chưa thuộc nhóm người dùng được hỗ trợ")


def get_login_redirect(user: NguoiDung) -> str:
    role, _ = get_user_role(user)
    if role == "QUAN_TRI_VIEN":
        return "/QuanTriVien.html"
    if role == "DOANH_NGHIEP":
        return "/QuanLyTram.html"
    return "/TrangChu.html"


# ==========================================================
# 4. FastAPI Dependencies for Authentication & Authorization
# ==========================================================
def get_session_data(request: Request) -> Optional[dict[str, Any]]:
    # 1. Check cookie
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        data = decode_session_token(cookie_token)
        if data:
            return data

    # 2. Check Authorization header: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        header_token = auth_header[7:].strip()
        data = decode_session_token(header_token)
        if data:
            return data

    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> NguoiDung:
    session_data = get_session_data(request)
    if not session_data or "username" not in session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Vui lòng đăng nhập để tiếp tục",
            headers={"WWW-Authenticate": "Bearer"}
        )

    username = session_data["username"]
    user = db.get(NguoiDung, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại hoặc đã bị vô hiệu hóa"
        )
    get_user_role(user)
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[NguoiDung]:
    session_data = get_session_data(request)
    if not session_data or "username" not in session_data:
        return None
    user = db.get(NguoiDung, session_data["username"])
    if user is not None:
        get_user_role(user)
    return user


def require_roles(allowed_roles: list[str]):
    """Role Guard Dependency Generator"""
    def role_checker(user: NguoiDung = Depends(get_current_user)) -> NguoiDung:
        role_code, _ = get_user_role(user)
        if role_code not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Quyền truy cập bị từ chối. Trang này yêu cầu vai trò: {', '.join(allowed_roles)}"
            )
        return user
    return role_checker


# Authentication to enterprise status is distinct from station authorization.
require_enterprise_account = require_roles(["DOANH_NGHIEP"])
require_khach_hang = require_roles(["KHACH_HANG"])
require_customer = require_khach_hang
require_admin = require_roles(["QUAN_TRI_VIEN"])


def require_approved_enterprise(user: NguoiDung = Depends(require_enterprise_account)) -> NguoiDung:
    if get_user_role(user)[0] != "DOANH_NGHIEP" or user.doanh_nghiep.dn_trangthai != "DA_DUYET":
        raise HTTPException(403, "Doanh nghiệp chưa được duyệt hoặc đang bị khóa; chưa có quyền quản lý trạm.")
    return user


# Existing enterprise routes inherit the approval gate without changing ownership logic.
require_doanh_nghiep = require_approved_enterprise


def require_workflow_actor(user: NguoiDung = Depends(get_current_user)) -> NguoiDung:
    role, _ = get_user_role(user)
    if role == "DOANH_NGHIEP":
        return require_approved_enterprise(user)
    if role != "KHACH_HANG":
        raise HTTPException(403, "Không có quyền truy cập nghiệp vụ khách hàng/doanh nghiệp.")
    return user
