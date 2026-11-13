"""Transaction reviews only; legacy station reviews retain their original meaning.

No mapped gd_ma column: the existing 34-table development schema remains readable
until the separately approved additive migration is applied. No automatic DDL.
"""
import secrets
import string
from fastapi import HTTPException
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from app.models import GiaoDich, YeuCauDoXang
from app.core.workflow_status import PAYMENT_SUCCEEDED, REQUEST_COMPLETED


def storage_ready(db):
    inspector = inspect(db.connection())
    cols = {c['name']:c for c in inspector.get_columns('danh_gia')}
    col = cols.get('gd_ma')
    if not col or not col['nullable'] or getattr(col['type'], 'length', None) != 8:
        return False
    unique = any(c['column_names'] == ['gd_ma'] for c in inspector.get_unique_constraints('danh_gia'))
    foreign = any(c['constrained_columns'] == ['gd_ma'] and c['referred_table'] == 'giao_dich'
                  and c['referred_columns'] == ['gd_ma'] for c in inspector.get_foreign_keys('danh_gia'))
    check = any(c['name'] == 'ck_transaction_review_content' for c in inspector.get_check_constraints('danh_gia'))
    return unique and foreign and check


def transaction(db, invoice_id, user, *, lock=False):
    query = select(GiaoDich).where(GiaoDich.gd_ma == invoice_id,
                                  GiaoDich.nd_tendangnhap == user.nd_tendangnhap)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    invoice = db.scalar(query)
    if invoice is None: raise HTTPException(404, 'Không tìm thấy giao dịch của bạn')
    req = db.get(YeuCauDoXang, invoice.yc_ma)
    eligible = bool(invoice.tt_ma == PAYMENT_SUCCEEDED and req
                    and req.ttxn_ma == REQUEST_COMPLETED
                    and req.nd_tendangnhap == user.nd_tendangnhap
                    and invoice.tx_ma and invoice.tx_ma == req.tx_ma)
    return invoice, eligible


def state(db, invoice_id, user):
    invoice, eligible = transaction(db, invoice_id, user)
    ready = storage_ready(db)
    if not ready:
        return dict(enabled=False, eligible=False, reviewed=False, reason='Tính năng đánh giá giao dịch chưa được kích hoạt')
    review = db.execute(text('SELECT dg_ma,dg_mucdo,dg_noidung FROM danh_gia WHERE gd_ma=:id'), {'id':invoice.gd_ma}).mappings().first()
    return dict(enabled=True, eligible=eligible, reviewed=review is not None,
                review=dict(review) if review else None,
                reason=None if eligible else 'Chỉ đánh giá hóa đơn đã thanh toán và hoàn tất bơm')


def submit(db, invoice_id, user, stars, comment):
    invoice, eligible = transaction(db, invoice_id, user, lock=True)
    if not eligible: raise HTTPException(409, 'Giao dịch chưa đủ điều kiện đánh giá')
    if not storage_ready(db): raise HTTPException(503, 'Đánh giá giao dịch đang chờ kích hoạt')
    existing = db.execute(text('SELECT dg_ma,dg_mucdo,dg_noidung FROM danh_gia WHERE gd_ma=:id'), {'id':invoice.gd_ma}).mappings().first()
    if existing:
        if existing['dg_mucdo'] != stars or existing['dg_noidung'] != comment:
            raise HTTPException(409, 'Giao dịch đã được đánh giá; nội dung trước được giữ nguyên')
        return dict(review_id=existing['dg_ma'], replayed=True)
    # Same invoice lock serializes double-click/replay. UNIQUE(gd_ma) is the
    # database backstop, including writers outside this request process.
    day = db.scalar(text("SELECT (clock_timestamp() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date"))
    db.execute(text('INSERT INTO thoi_diem(ngaygio) VALUES (:day) ON CONFLICT DO NOTHING'), {'day':day})
    for _ in range(8):
        code = 'DG'+''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
        try:
            with db.begin_nested():
                db.execute(text('INSERT INTO danh_gia(dg_ma,nd_tendangnhap,tx_ma,ngaygio,dg_noidung,dg_mucdo,gd_ma) '
                    'VALUES (:code,:owner,:station,:day,:comment,:stars,:invoice)'),
                    dict(code=code, owner=user.nd_tendangnhap, station=invoice.tx_ma,
                         day=day, comment=comment, stars=stars, invoice=invoice.gd_ma))
            return dict(review_id=code, replayed=False)
        except IntegrityError:
            if not db.scalar(text('SELECT 1 FROM danh_gia WHERE dg_ma=:code'), {'code':code}):
                raise
    raise HTTPException(503, 'Chưa thể lưu đánh giá; vui lòng thử lại')
