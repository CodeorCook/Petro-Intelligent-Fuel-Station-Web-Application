import logging
import secrets

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.user import DoanhNghiep, KhachHang, NguoiDung
from app.models.approval import QuanTriVien
from app.schemas.auth import CustomerRegistrationRequest

logger = logging.getLogger(__name__)


def register_customer(db: Session, payload: CustomerRegistrationRequest) -> str:
    return _register_public(db, payload, enterprise=False)


def register_enterprise(db: Session, payload: CustomerRegistrationRequest) -> str:
    return _register_public(db, payload, enterprise=True)


def _register_public(db: Session, payload: CustomerRegistrationRequest, *, enterprise: bool) -> str:
    """Create both records with one commit; usernames use kh_/dn_ + 24 random hex digits.

    No email UNIQUE constraint is added. PostgreSQL registrations acquire a
    transaction-scoped advisory lock for the normalized email so concurrent
    calls through this API cannot register the same email twice.
    """
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:email))"),
                {"email": payload.email},
            )
        existing = db.scalar(select(NguoiDung.nd_tendangnhap).where(
            func.lower(func.trim(NguoiDung.nd_email)) == payload.email
        ))
        if existing is not None:
            raise HTTPException(409, "Email này đã được đăng ký")
        username = ("dn_" if enterprise else "kh_") + secrets.token_hex(12)
        user = NguoiDung(
            nd_tendangnhap=username, nd_ten=payload.name,
            nd_email=payload.email, nd_sodienthoai=payload.phone,
            nd_matkhau=hash_password(payload.password),
        )
        db.add(user)
        db.flush()
        db.add(DoanhNghiep(nd_tendangnhap=username, dn_trangthai="DA_DUYET",
                          dn_du_lieu_cu=False) if enterprise else KhachHang(nd_tendangnhap=username))
        db.commit()
        return username
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as error:
        db.rollback()
        logger.warning("Public registration rejected by a database constraint")
        raise HTTPException(409, "Không thể tạo tài khoản do dữ liệu trùng hoặc không hợp lệ") from error
    except SQLAlchemyError as error:
        db.rollback()
        logger.error("Public registration database operation failed")
        raise HTTPException(503, "Không thể đăng ký lúc này. Vui lòng thử lại sau.") from error


def bootstrap_administrator(db: Session, username: str, payload: CustomerRegistrationRequest) -> bool:
    """Explicit CLI-only provisioning; repeat is a no-op, existing actors never convert."""
    import re
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", username):
        raise ValueError("Username phải dài 1–32 ký tự chữ, số, dấu . _ -")
    try:
        if db.get_bind().dialect.name == "postgresql":
            for key in sorted((payload.email, username)):
                db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
        existing = db.get(NguoiDung, username)
        email_users = db.scalars(select(NguoiDung).where(
            func.lower(func.trim(NguoiDung.nd_email)) == payload.email)).all()
        if existing is not None:
            if (existing.quan_tri_vien is not None and existing.khach_hang is None
                and existing.doanh_nghiep is None and existing.nd_email.strip().lower() == payload.email
                and all(u.nd_tendangnhap == username for u in email_users)):
                db.rollback()
                return False
            raise ValueError("Username đã tồn tại; không chuyển vai trò hoặc đặt lại mật khẩu")
        if email_users:
            raise ValueError("Email đã được sử dụng")
        db.add(NguoiDung(nd_tendangnhap=username, nd_ten=payload.name, nd_email=payload.email,
                        nd_sodienthoai=payload.phone, nd_matkhau=hash_password(payload.password)))
        db.flush()
        db.add(QuanTriVien(nd_tendangnhap=username))
        db.commit()
        return True
    except (ValueError, HTTPException):
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise ValueError("Không thể provision tài khoản; transaction đã rollback") from error
