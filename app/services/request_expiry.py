"""Unattended expiry. No client clocks, no request-before-parent lock inversion."""
from sqlalchemy import select,func
from app.models import YeuCauDoXang
from app.core.workflow_status import REQUEST_WAITING
from app.services import operational_service as ops,request_lifecycle as lifecycle

def tick(session_factory,limit=50):
    with session_factory() as db:
        ops.guard(db)
        ids=list(db.scalars(select(YeuCauDoXang.yc_ma).where(
            YeuCauDoXang.ttxn_ma==REQUEST_WAITING,YeuCauDoXang.yc_het_han_luc.is_not(None),
            YeuCauDoXang.yc_het_han_luc<=func.clock_timestamp())
            .order_by(YeuCauDoXang.tx_ma,YeuCauDoXang.yc_ma).limit(limit)))
        db.rollback()
    processed=0
    for rid in ids:
        with session_factory() as db:
            if ops.execute(db,lambda:lifecycle.expire_one(db,rid)):processed+=1
    return processed
