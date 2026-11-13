"""Owned private-draft assignments only. Approved public amenities require review."""
from fastapi import HTTPException
from sqlalchemy import select, delete
from app.models import DichVu, TxDv, YeuCauDuyetTram
from app.services.enterprise_approval import atomic
from app.services.station_approval import owned, approved_owner, amenity_records


def list_owned(db, user, station_id):
    owned(db, user, station_id)
    return db.scalars(select(TxDv).where(TxDv.tx_ma == station_id).order_by(TxDv.dv_ma)).all()


def editable_draft(db, user, station_id):
    approved_owner(db, user)
    station = owned(db, user, station_id, lock=True)
    if station.tx_phienban_hientai > 0 or station.tx_congkhai:
        raise HTTPException(409, 'Tiện ích trạm đã duyệt là thông tin công khai; cần đề xuất và xét duyệt, không sửa trực tiếp.')
    if station.tx_trangthai not in {'NHAP', 'CAN_BO_SUNG', 'TU_CHOI'}:
        raise HTTPException(409, 'Trạm không ở trạng thái nháp có thể chỉnh sửa.')
    if db.scalar(select(YeuCauDuyetTram.ycdt_ma).where(
        YeuCauDuyetTram.tx_ma == station_id, YeuCauDuyetTram.ycdt_trangthai == 'CHO_DUYET')):
        raise HTTPException(409, 'Trạm đang chờ duyệt; không sửa tiện ích của hồ sơ đã nộp.')
    return station


def replace_draft_set(db, user, station_id, service_ids, expected_ids):
    """Same ownership/pending guard as assign/remove, but a single full-set UoW.

    Multiple HTTP assign/remove calls cannot provide atomic full-set semantics.
    Lock order matches submission/decision: enterprise -> station -> catalog.
    """
    with atomic(db):
        editable_draft(db, user, station_id)
        current = set(db.scalars(select(TxDv.dv_ma).where(
            TxDv.tx_ma == station_id).with_for_update()))
        if current != set(expected_ids):
            raise HTTPException(409, 'Tiện ích nháp đã thay đổi ở phiên khác; tải lại trước khi lưu.')
        desired = set(service_ids)
        if len(desired) != len(service_ids) or len(set(expected_ids)) != len(expected_ids):
            raise HTTPException(400, 'Mã tiện ích bị trùng.')
        amenity_records(db, sorted(desired))  # Validate the entire set before deleting.
        removed = current - desired
        if removed:
            db.execute(delete(TxDv).where(TxDv.tx_ma == station_id, TxDv.dv_ma.in_(removed)),
                       execution_options={'synchronize_session': 'fetch'})
        for code in sorted(desired - current):
            db.add(TxDv(tx_ma=station_id, dv_ma=code))
        db.flush()
    return list_owned(db, user, station_id)


def assign(db, user, station_id, service_id):
    with atomic(db):
        editable_draft(db, user, station_id)
        if db.get(DichVu, service_id) is None:
            raise HTTPException(404, 'Tiện ích không tồn tại trong danh mục.')
        if db.get(TxDv, (service_id, station_id)) is not None:
            raise HTTPException(409, 'Trạm đã có tiện ích này.')
        row = TxDv(tx_ma=station_id, dv_ma=service_id)
        db.add(row); db.flush()
    db.refresh(row)
    return row


def remove(db, user, station_id, service_id):
    with atomic(db):
        editable_draft(db, user, station_id)
        row = db.get(TxDv, (service_id, station_id))
        if row is None: raise HTTPException(404, 'Trạm chưa có tiện ích này.')
        db.delete(row); db.flush()
