"""Request closure only. Never reverses physical dispensing or financial records."""
from sqlalchemy import select,func,text
from fastapi import HTTPException
from app.models import (DoanhNghiep,TramXang,YeuCauDoXang,TruBom,BonChua,
    GiuChoNhienLieu,BienDongKho,GiaoDich)
from app.core.workflow_status import (REQUEST_WAITING,REQUEST_ACCEPTED,REQUEST_CANCELLED,
    REQUEST_EXPIRED,REQUEST_REJECTED,advance_request)
from app.core.operational_mode import preserved_request

def now(db):return db.scalar(select(func.clock_timestamp()))

def guard_schema(db):
    from sqlalchemy import inspect
    inspector=inspect(db.connection());cols={r['name']:r for r in inspector.get_columns('yeu_cau_do_xang')}
    for name in ('yc_het_han_luc','yc_dong_luc'):
        if name not in cols or not getattr(cols[name]['type'],'timezone',False) or not cols[name]['nullable']:
            raise HTTPException(503,'Schema vòng đời yêu cầu chưa được phê duyệt/kích hoạt')
    for name,length in [('yc_dong_boi',32),('yc_lydo_dong',256)]:
        if name not in cols or getattr(cols[name]['type'],'length',None)!=length or not cols[name]['nullable']:
            raise HTTPException(503,'Schema vòng đời yêu cầu không khớp')
    if 'idx_yc_waiting_deadline' not in {r['name'] for r in inspector.get_indexes('yeu_cau_do_xang')}:
        raise HTTPException(503,'Thiếu index vòng đời yêu cầu')
    checks={r['name']:r for r in inspector.get_check_constraints('yeu_cau_do_xang')}
    fks={r['name']:r for r in inspector.get_foreign_keys('yeu_cau_do_xang')}
    actor=fks.get('fk_yc_closed_actor',{})
    if 'ck_yc_terminal_metadata' not in checks or actor.get('referred_table')!='nguoi_dung' or actor.get('constrained_columns')!=['yc_dong_boi']:
        raise HTTPException(503,'Thiếu ràng buộc vòng đời yêu cầu')

def metadata(req,db):
    return dict(server_now=now(db),expires_at=req.yc_het_han_luc,closed_at=req.yc_dong_luc,
                closed_by=req.yc_dong_boi,close_reason=req.yc_lydo_dong)

def pristine(db,req):
    """A no-posting check alone NEVER authorizes cancellation of a PUMPING request."""
    from app.services.operational_service import fail
    if req.yc_het_han_luc is None:fail('Đơn cũ cần đối soát riêng; không tự hủy hoặc hết hạn')
    if db.scalar(select(TruBom.tb_ma).where(TruBom.yc_dang_bom==req.yc_ma).limit(1)):
        fail('Yêu cầu có phiên trụ bơm; cần đối soát tại trạm')
    if db.scalar(select(BienDongKho.bd_ma).where(BienDongKho.yc_ma==req.yc_ma).limit(1)) or db.scalar(select(GiaoDich.gd_ma).where(GiaoDich.yc_ma==req.yc_ma).limit(1)):
        fail('Đã có bút toán hoặc hóa đơn; không được hoàn tồn tự động')

def release(db,req):
    from app.services.operational_service import invariant,fail
    tanks=list(db.scalars(select(BonChua).join(GiuChoNhienLieu,GiuChoNhienLieu.bc_ma==BonChua.bc_ma)
        .where(GiuChoNhienLieu.yc_ma==req.yc_ma).order_by(BonChua.bc_ma).with_for_update(of=BonChua)))
    holds=list(db.scalars(select(GiuChoNhienLieu).where(GiuChoNhienLieu.yc_ma==req.yc_ma)
        .order_by(GiuChoNhienLieu.bc_ma).with_for_update()))
    by_id={t.bc_ma:t for t in tanks}
    for t in tanks:invariant(db,t)
    for h in holds:
        if h.gc_trangthai!='GIU_CHO':fail('Giữ chỗ đã xử lý; cần đối soát')
        tank=by_id[h.bc_ma]
        if tank.bc_giucho<h.gc_solit:fail('Số dư giữ chỗ không nhất quán')
        tank.bc_giucho-=h.gc_solit;tank.bc_phienban+=1;tank.bc_ngaycapnhat=func.now()
        h.gc_trangthai='DA_HUY';h.gc_ngaycapnhat=func.now()

def close(db,req,target,actor,reason):
    from app.services.operational_service import fail
    pristine(db,req)
    if req.ttxn_ma==REQUEST_WAITING:
        if db.scalar(select(GiuChoNhienLieu.yc_ma).where(GiuChoNhienLieu.yc_ma==req.yc_ma).limit(1)):
            fail('Đơn chờ có giữ chỗ bất thường; cần đối soát')
    elif req.ttxn_ma==REQUEST_ACCEPTED:release(db,req)
    else:fail('Chỉ được đóng đơn chưa bắt đầu bơm')
    advance_request(req,target)
    req.yc_dong_luc=now(db);req.yc_dong_boi=actor;req.yc_lydo_dong=reason
    db.flush()
    return dict(status='success',yc_ma=req.yc_ma,status_code=req.ttxn_ma,replayed=False,**metadata(req,db))

def expire_locked(db,req):
    if (not preserved_request(req.yc_ma) and req.ttxn_ma==REQUEST_WAITING and
        req.yc_het_han_luc is not None and now(db)>=req.yc_het_han_luc):
        return close(db,req,REQUEST_EXPIRED,None,'Hết thời gian chờ tiếp nhận 180 giây')
    return None

def refuse_expired(db,req):
    result=expire_locked(db,req)
    if result:return dict(result,_conflict_after_commit='Yêu cầu đã hết hạn tiếp nhận')
    return None

def cancel(db,rid,user,reason,confirm_no_dispense=False):
    from app.services.operational_service import request_lock,fail
    from app.core.auth import get_user_role
    req,_=request_lock(db,rid,user,cancellation=True)
    role=get_user_role(user)[0];reason=(reason or '').strip()
    if not reason or len(reason)>256:fail('Cần lý do hủy từ 1 đến 256 ký tự',400)
    if req.ttxn_ma==REQUEST_CANCELLED:
        if req.yc_dong_boi!=user.nd_tendangnhap or req.yc_lydo_dong!=reason:
            fail('Nội dung hủy khác thao tác đã hoàn tất')
        return dict(status='success',yc_ma=rid,status_code=req.ttxn_ma,replayed=True,**metadata(req,db))
    expired=refuse_expired(db,req)
    if expired:return expired
    if req.ttxn_ma==REQUEST_ACCEPTED and not confirm_no_dispense:
        fail('Phải xác nhận chưa bắt đầu bơm trước khi hủy',400)
    if role=='DOANH_NGHIEP' and req.ttxn_ma==REQUEST_WAITING:
        fail('Đơn chờ: dùng thao tác từ chối, không đổi nghĩa thành hủy')
    return close(db,req,REQUEST_CANCELLED,user.nd_tendangnhap,reason)

def reject(db,rid,user,reason):
    from app.services.operational_service import request_lock,fail
    from app.core.auth import get_user_role
    if get_user_role(user)[0]!='DOANH_NGHIEP':fail('Chỉ chủ trạm được từ chối yêu cầu',403)
    req,_=request_lock(db,rid,user,cancellation=True);reason=(reason or '').strip()
    if not reason or len(reason)>256:fail('Cần lý do từ chối từ 1 đến 256 ký tự',400)
    if req.ttxn_ma==REQUEST_REJECTED and req.yc_dong_boi==user.nd_tendangnhap and req.yc_lydo_dong==reason:
        return dict(status='success',replayed=True,yc_ma=rid,status_code=req.ttxn_ma)
    expired=refuse_expired(db,req)
    if expired:return expired
    if req.ttxn_ma!=REQUEST_WAITING:fail('Chỉ được từ chối đơn đang chờ')
    return close(db,req,REQUEST_REJECTED,user.nd_tendangnhap,reason)

def expire_one(db,rid):
    """System actor: discovery is unlocked, parent→station→request locks are ordered."""
    from app.services.operational_service import fail
    sid=db.scalar(select(YeuCauDoXang.tx_ma).where(YeuCauDoXang.yc_ma==rid))
    if sid is None:return None
    owner=db.scalar(select(TramXang.nd_tendangnhap).where(TramXang.tx_ma==sid))
    db.scalar(select(DoanhNghiep).where(DoanhNghiep.nd_tendangnhap==owner).with_for_update())
    station=db.scalar(select(TramXang).where(TramXang.tx_ma==sid).with_for_update().execution_options(populate_existing=True))
    if station.nd_tendangnhap!=owner:fail('Chủ trạm thay đổi; thử lại')
    req=db.scalar(select(YeuCauDoXang).where(YeuCauDoXang.yc_ma==rid).with_for_update().execution_options(populate_existing=True))
    if req is None or req.tx_ma!=sid:return None
    return expire_locked(db,req)
