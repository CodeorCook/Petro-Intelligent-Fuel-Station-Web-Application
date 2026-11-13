"""Canonical meanings verified against development lookups; never seed or rename rows.

Physical request completion and financial settlement are independent dimensions.
Lifecycle states 6/7 require the separately approved Phase 5.8B migration.
The legacy non-operational path retains its fail-closed cancellation guard.
"""
import unicodedata
from fastapi import HTTPException
from sqlalchemy import select
from app.models import TrangThai, TrangThaiXacNhan

REQUEST_WAITING='TTXN0001'
REQUEST_ACCEPTED='TTXN0002'
REQUEST_PUMPING='TTXN0003'
REQUEST_COMPLETED='TTXN0004'
REQUEST_REJECTED='TTXN0005'
REQUEST_CANCELLED='TTXN0006'
REQUEST_EXPIRED='TTXN0007'
PAYMENT_SUCCEEDED='TT000001'
PAYMENT_FAILED='TT000002'
PAYMENT_PROCESSING='TT000003'
REQUEST_LABELS={REQUEST_WAITING:'Chờ duyệt',REQUEST_ACCEPTED:'Đã xác nhận',REQUEST_PUMPING:'Đang bơm',REQUEST_COMPLETED:'Hoàn thành',REQUEST_REJECTED:'Từ chối'}
PAYMENT_LABELS={PAYMENT_SUCCEEDED:'Thành công',PAYMENT_FAILED:'Thất bại',PAYMENT_PROCESSING:'Đang xử lý'}
REQUEST_TRANSITIONS={REQUEST_WAITING:{REQUEST_ACCEPTED,REQUEST_REJECTED},REQUEST_ACCEPTED:{REQUEST_PUMPING,REQUEST_REJECTED},REQUEST_PUMPING:{REQUEST_COMPLETED},REQUEST_COMPLETED:set(),REQUEST_REJECTED:set()}
PAYMENT_TRANSITIONS={PAYMENT_PROCESSING:{PAYMENT_SUCCEEDED,PAYMENT_FAILED},PAYMENT_SUCCEEDED:set(),PAYMENT_FAILED:set()}
REQUEST_LABELS.update({REQUEST_CANCELLED:'Đã hủy',REQUEST_EXPIRED:'Hết hạn'})
REQUEST_TRANSITIONS[REQUEST_WAITING].update({REQUEST_CANCELLED,REQUEST_EXPIRED})
REQUEST_TRANSITIONS[REQUEST_ACCEPTED]={REQUEST_PUMPING,REQUEST_CANCELLED}
REQUEST_TRANSITIONS.update({REQUEST_CANCELLED:set(),REQUEST_EXPIRED:set()})

def validate_catalog(db):
    """Fail closed on missing/mislabeled lookup, in the same UoW; no global cache."""
    for model,key,label,expected in [(TrangThai,'tt_ma','tt_ten',PAYMENT_LABELS),(TrangThaiXacNhan,'ttxn_ma','ttxn_ten',REQUEST_LABELS)]:
        from app.core.operational_mode import POSTGRESQL_OPERATIONS
        if model is TrangThaiXacNhan and not POSTGRESQL_OPERATIONS:
            expected={k:v for k,v in expected.items() if k not in (REQUEST_CANCELLED,REQUEST_EXPIRED)}
        actual={str(k).strip():unicodedata.normalize('NFC',str(v).strip()) for k,v in db.execute(select(getattr(model,key),getattr(model,label)))}
        if any(actual.get(k)!=v for k,v in expected.items()):
            raise HTTPException(503,'Danh mục trạng thái không khớp nghiệp vụ đã xác minh; cần đối soát, không tự sửa dữ liệu')

def advance_request(req,target):
    if target not in REQUEST_TRANSITIONS.get(req.ttxn_ma,set()):
        raise HTTPException(409,'Chuyển trạng thái yêu cầu không hợp lệ')
    req.ttxn_ma=target

def advance_payment(gd,target):
    if target not in PAYMENT_TRANSITIONS.get(gd.tt_ma,set()):
        raise HTTPException(409,'Chuyển trạng thái thanh toán không hợp lệ; cần đối soát giao dịch')
    gd.tt_ma=target

def cancel_unavailable():
    raise HTTPException(409,'Chưa có trạng thái Đã hủy trong danh mục đã duyệt; tạm khóa thao tác hủy, dữ liệu được giữ nguyên')

def view(req,gd=None):
    """Derived UI state; not new database statuses and not historical data migration."""
    payment={PAYMENT_SUCCEEDED:'SUCCEEDED',PAYMENT_FAILED:'FAILED',PAYMENT_PROCESSING:'PROCESSING'}.get(gd.tt_ma,'UNKNOWN') if gd else 'NONE'
    if req.ttxn_ma in (REQUEST_CANCELLED,REQUEST_EXPIRED):
        phase='CANCELLED' if req.ttxn_ma==REQUEST_CANCELLED else 'EXPIRED'
    elif req.ttxn_ma==REQUEST_REJECTED:
        phase='REJECTED' if gd is None else 'REVIEW_REQUIRED'
    elif gd is not None:
        phase={'SUCCEEDED':'PAID','FAILED':'PAYMENT_FAILED','PROCESSING':'PAYMENT_PENDING'}.get(payment,'REVIEW_REQUIRED') if req.ttxn_ma==REQUEST_COMPLETED else 'REVIEW_REQUIRED'
    else:
        phase={REQUEST_WAITING:'WAITING',REQUEST_ACCEPTED:'ACCEPTED',REQUEST_PUMPING:'PUMPING',REQUEST_COMPLETED:'COMPLETED_NO_INVOICE'}.get(req.ttxn_ma,'REVIEW_REQUIRED')
    return dict(phase=phase,payment_state=payment,payment_status_code=gd.tt_ma if gd else None,
        is_paid=payment=='SUCCEEDED',dispensing_completed=req.ttxn_ma==REQUEST_COMPLETED,
        can_cancel=req.ttxn_ma in (REQUEST_WAITING,REQUEST_ACCEPTED) and gd is None and req.yc_het_han_luc is not None,
        expires_at=req.yc_het_han_luc,closed_at=req.yc_dong_luc,closed_by=req.yc_dong_boi,close_reason=req.yc_lydo_dong)
