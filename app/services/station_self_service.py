"""Capability gate, not an automatic migration or an alternative audit store."""
from fastapi import HTTPException
from sqlalchemy import inspect

METHOD = 'SELF_SERVICE_DEMO'
# Existing audit JSON stores actor/method; no extra columns or fake QTV account.
LEGACY_CHECK = "(ycdt_trangthai = 'CHO_DUYET' AND qtv_tendangnhap IS NULL AND ycdt_ngayxuly IS NULL) OR (ycdt_trangthai <> 'CHO_DUYET' AND qtv_tendangnhap IS NOT NULL AND ycdt_ngayxuly IS NOT NULL)"
SELF_CHECK = "(" + LEGACY_CHECK + ") OR (ycdt_trangthai = 'DA_DUYET' AND qtv_tendangnhap IS NULL AND ycdt_ngayxuly IS NOT NULL AND COALESCE(ycdt_dulieu ->> 'activation_method', '') = 'SELF_SERVICE_DEMO' AND COALESCE(ycdt_dulieu ->> 'activation_actor', '') <> '' AND ycdt_dulieu ->> 'activation_actor' = COALESCE(ycdt_dulieu ->> 'nd_tendangnhap', ''))"


def require_schema(db):
    checks = inspect(db.connection()).get_check_constraints('yeu_cau_duyet_tram')
    check = next((c['sqltext'] for c in checks if c['name'] == 'ck_ycdt_xuly'), '')
    if 'SELF_SERVICE_DEMO' not in check or 'activation_actor' not in check:
        raise HTTPException(503, 'Chưa kích hoạt: schema audit tự phục vụ chưa được triển khai/phê duyệt. Nháp và minh chứng vẫn được giữ nguyên.')
    if db.bind.dialect.name == 'postgresql':
        # The full pinned schema contract remains authoritative, including CHECK
        # semantics. A marker substring alone can never authorize a PG write.
        from app.services.operational_service import guard
        guard(db)
