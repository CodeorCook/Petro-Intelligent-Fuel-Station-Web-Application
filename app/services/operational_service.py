"""PostgreSQL-only UoW; no JSON inventory I/O, external calls or helper commits.

Explicit hash-pinned private target policy is required for development activation.
Without it, only the original pinned disposable cluster remains permitted.
"""
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import logging
from pathlib import Path
import hashlib
import json
import re
import secrets
from fastapi import HTTPException
from sqlalchemy import select, func, text, inspect
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from app.models import (BonChua, TruBom, TruBomNhienLieu, GiuChoNhienLieu, BienDongKho,
    TramXang, DoanhNghiep, NguoiDung, Gia, YeuCauDoXang, ChiTietYeuCau,
    GiaoDich, ChiTietGiaoDich, ThoiDiem, KhachHang, NhienLieu)
from app.services.casso_integration import qr_fields, payment_amount, bank_transaction_id
from app.core.auth import get_user_role
from app.core.workflow_status import (REQUEST_WAITING,REQUEST_ACCEPTED,REQUEST_PUMPING,REQUEST_COMPLETED,REQUEST_REJECTED,
    PAYMENT_PROCESSING,PAYMENT_SUCCEEDED,PAYMENT_FAILED,validate_catalog,advance_request,advance_payment,cancel_unavailable)

logger = logging.getLogger(__name__)
CANONICAL = {'NL000001','NL000002','NL000003'}
D = Decimal

def fail(message, status=409):
    raise HTTPException(status, message)

def guard(db):
    from app.services.request_lifecycle import guard_schema
    from app.core.operational_mode import configured_target
    config=configured_target()
    url = db.get_bind().url
    if config:
        from app.core.local_dev_profile import PROFILE,runtime_guard
        if config.get('profile')==PROFILE:runtime_guard(config,db)
        if config.get('lifecycle_enabled') is not True:
            fail('Vòng đời yêu cầu 5.8B chưa được cho phép trong policy riêng tư',503)
        target=config['target']
        if url.get_backend_name()!='postgresql' or url.host not in target['hosts'] or url.port!=target['port'] or url.database!=target['database']:
            fail('Sai đích PostgreSQL đã phê duyệt',503)
        row=db.execute(text("SELECT current_setting('data_directory'),system_identifier::text FROM pg_control_system()")).one()
        if Path(row[0]).resolve()!=Path(target['data_directory']).resolve() or row[1]!=target['system_identifier']:
            fail('Không xác minh được PostgreSQL vận hành',503)
        guard_schema(db)
        from app.core.published_price_schema import validate as validate_public_schema
        try:
            validate_public_schema(db)
        except RuntimeError:
            fail('Schema vận hành không khớp phiên bản đã phê duyệt',503)
        names=list(db.execute(text("SELECT tgname,pg_get_triggerdef(oid,false) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('trg_tb_scope','trg_gc_scope','trg_bd_scope','trg_bd_immutable','trg_tb_immutable','trg_bc_immutable','trg_gc_immutable') ORDER BY tgname")))
        if {r[0]:hashlib.sha256(r[1].encode()).hexdigest() for r in names}!=config['trigger_sha256']:
            fail('Trigger vận hành không khớp bản đã kiểm chứng',503)
        functions=list(db.execute(text("SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname IN ('phase57_scope_guard','phase57_immutable_guard') ORDER BY proname")))
        if {r[0]:hashlib.sha256(r[1].encode()).hexdigest() for r in functions}!=config['function_sha256']:
            fail('Hàm bảo vệ kho không khớp bản đã kiểm chứng',503)
        if operation_schema_signature(db)!=config['operation_schema_sha256']:
            fail('Cột/ràng buộc/index kho không khớp bản đã kiểm chứng',503)
        db.execute(text("SET LOCAL lock_timeout='5s'"));db.execute(text("SET LOCAL statement_timeout='15s'"))
        return
    if url.get_backend_name() != 'postgresql' or url.host != '127.0.0.1' or url.port != 55457 or url.database != 'DB_TRAMXANG':
        fail('Kho PostgreSQL chưa được phép kích hoạt trên database này',503)
    # SELECT only, on the same connection/transaction that will perform writes.
    row = db.execute(text("SELECT current_setting('data_directory'),system_identifier::text FROM pg_control_system()")).one()
    expected = Path(__file__).resolve().parents[5] / '.runtime/phase57b/pgdata'
    if Path(row[0]).resolve() != expected.resolve() or row[1] != '7697315547285192184':
        fail('Không xác minh được môi trường PostgreSQL cách ly',503)
    guard_schema(db)
    db.execute(text("SET LOCAL lock_timeout='5s'"))
    db.execute(text("SET LOCAL statement_timeout='15s'"))

def operation_schema_signature(db):
    inspector=inspect(db.connection())
    schema={name:dict(columns=inspector.get_columns(name),pk=inspector.get_pk_constraint(name),
        fk=inspector.get_foreign_keys(name),indexes=inspector.get_indexes(name),
        checks=inspector.get_check_constraints(name),unique=inspector.get_unique_constraints(name))
        for name in ('bon_chua','tru_bom','tru_bom_nhien_lieu','giu_cho_nhien_lieu','bien_dong_kho')}
    return hashlib.sha256(json.dumps(schema,default=str,sort_keys=True).encode()).hexdigest()

def execute(db, command):
    """Own the request transaction, including auth's autobegun SELECTs; exactly one commit."""
    try:
        guard(db)
        validate_catalog(db)
        result = command()
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        logger.warning('Operational constraint conflict; transaction rolled back')
        fail('Dữ liệu xung đột; tải lại và kiểm tra thao tác')
    except DBAPIError:
        db.rollback()
        logger.warning('Operational database failure; transaction rolled back')
        fail('Kho nhiên liệu tạm thời không khả dụng; vui lòng thử lại',503)
    except Exception:
        db.rollback()
        raise
    if isinstance(result,dict) and result.get('_conflict_after_commit'):
        raise HTTPException(409,result['_conflict_after_commit'])
    return result

def station_lock(db, sid, user, *, customer=False, public=True):
    # Discover parent key without taking child lock first, then lock and recheck.
    owner = db.scalar(select(TramXang.nd_tendangnhap).where(TramXang.tx_ma == sid))
    if owner is None:
        fail('Không tìm thấy trạm',404)
    ent = db.scalar(select(DoanhNghiep).where(DoanhNghiep.nd_tendangnhap == owner).with_for_update().execution_options(populate_existing=True))
    station = db.scalar(select(TramXang).where(TramXang.tx_ma == sid).with_for_update().execution_options(populate_existing=True))
    if station.nd_tendangnhap != owner:
        fail('Chủ sở hữu trạm đã thay đổi; thử lại')
    role = get_user_role(user)[0]
    if customer:
        if role != 'KHACH_HANG': fail('Chỉ khách hàng được tạo yêu cầu',403)
    elif role != 'DOANH_NGHIEP' or owner != user.nd_tendangnhap:
        fail('Bạn không có quyền quản lý trạm này',403)
    if ent is None or (public and ent.dn_trangthai != 'DA_DUYET'):
        fail('Doanh nghiệp chưa được duyệt hoặc bị khóa',403)
    if public and (station.tx_trangthai != 'DA_DUYET' or not station.tx_congkhai):
        fail('Trạm chưa đủ điều kiện vận hành công khai')
    return station

def request_lock(db, rid, user, *, cancellation=False):
    sid = db.scalar(select(YeuCauDoXang.tx_ma).where(YeuCauDoXang.yc_ma == rid))
    if sid is None: fail('Không tìm thấy yêu cầu',404)
    customer = get_user_role(user)[0] == 'KHACH_HANG'
    station_lock(db,sid,user,customer=customer,public=not cancellation)
    req = db.scalar(select(YeuCauDoXang).where(YeuCauDoXang.yc_ma==rid).with_for_update().execution_options(populate_existing=True))
    if req.tx_ma != sid: fail('Yêu cầu đã thay đổi trạm')
    if customer and (not cancellation or req.nd_tendangnhap != user.nd_tendangnhap):
        fail('Không có quyền thao tác yêu cầu',403)
    assert_request_writable(rid)
    items = list(db.scalars(select(ChiTietYeuCau).where(ChiTietYeuCau.yc_ma==rid).order_by(ChiTietYeuCau.nl_ma).with_for_update().execution_options(populate_existing=True)))
    return req,items

def assert_request_writable(rid):
    from app.core.operational_mode import preserved_request
    if preserved_request(rid):
        fail('Yêu cầu có trước cutover được giữ chỉ đọc để đối soát; không tự bơm, hủy hoặc thanh toán lại')

def decimal(value, *, positive=True):
    try: value = D(str(value))
    except Exception: fail('Số lượng không hợp lệ',400)
    if not value.is_finite() or value < 0 or (positive and value == 0) or value >= D('1000000000000') or value != value.quantize(D('.01')):
        fail('Số lượng phải hữu hạn, không âm, tối đa hai chữ số thập phân',400)
    return value

def compatible(db,sid,fuels):
    if not fuels or len(set(fuels))!=len(fuels) or not set(fuels)<=CANONICAL:
        fail('Danh sách nhiên liệu không hợp lệ',400)
    for fid in sorted(fuels):
        if db.get(NhienLieu,fid) is None or db.scalar(select(BonChua.bc_ma).where(BonChua.tx_ma==sid,BonChua.nl_ma==fid,BonChua.bc_hoatdong.is_(True)).limit(1)) is None:
            fail('Nhiên liệu chưa có bồn tương thích: '+fid)

def invariant(db,tank):
    active = db.scalar(select(func.coalesce(func.sum(GiuChoNhienLieu.gc_solit),0)).where(GiuChoNhienLieu.bc_ma==tank.bc_ma,GiuChoNhienLieu.gc_trangthai=='GIU_CHO'))
    if active != tank.bc_giucho: fail('Số dư giữ chỗ không khớp; cần đối soát kho')

def create_tank(db,sid,user,data):
    station_lock(db,sid,user)
    if data['nl_ma'] not in CANONICAL or db.get(NhienLieu,data['nl_ma']) is None: fail('Nhiên liệu không hợp lệ',400)
    if db.get(BonChua,data['bc_ma']): fail('Mã bồn đã tồn tại')
    cap,threshold=decimal(data['bc_dungtich']),decimal(data['bc_nguong'],positive=False)
    if threshold>cap: fail('Ngưỡng cảnh báo vượt dung tích',400)
    row=BonChua(**data,tx_ma=sid,bc_ton=0,bc_giucho=0)
    db.add(row); db.flush()
    return tank_dict(row)

def edit_tank(db,sid,tid,user,data):
    station_lock(db,sid,user)
    tank=db.scalar(select(BonChua).where(BonChua.bc_ma==tid,BonChua.tx_ma==sid).with_for_update())
    if tank is None: fail('Không tìm thấy bồn',404)
    if tank.bc_phienban!=data.pop('bc_phienban'): fail('Bồn đã thay đổi; tải lại')
    invariant(db,tank)
    cap=data.get('bc_dungtich',tank.bc_dungtich); threshold=data.get('bc_nguong',tank.bc_nguong)
    if any(v is None for v in data.values()): fail('Không được xóa trường bắt buộc',400)
    if cap<tank.bc_ton or threshold>cap: fail('Dung tích/ngưỡng không phù hợp tồn kho')
    if data.get('bc_hoatdong') is False:
        if tank.bc_giucho: fail('Bồn đang giữ chỗ')
        other=db.scalar(select(BonChua.bc_ma).where(BonChua.tx_ma==sid,BonChua.nl_ma==tank.nl_ma,BonChua.bc_ma!=tid,BonChua.bc_hoatdong.is_(True)).limit(1))
        linked=db.scalar(select(TruBomNhienLieu.tb_ma).where(TruBomNhienLieu.tx_ma==sid,TruBomNhienLieu.nl_ma==tank.nl_ma).limit(1))
        if linked and not other: fail('Trụ bơm đang phụ thuộc bồn nhiên liệu này')
    for k,v in data.items(): setattr(tank,k,v)
    tank.bc_phienban+=1; tank.bc_ngaycapnhat=func.now(); db.flush()
    return tank_dict(tank)

def create_pump(db,sid,user,data):
    station_lock(db,sid,user)
    data=dict(data); fuels=data.pop('nl_ma'); confirmed=data.pop('baseline_confirmed',False)
    if confirmed is not True: fail('Phải xác nhận chỉ số ban đầu',400)
    compatible(db,sid,fuels)
    if db.get(TruBom,data['tb_ma']): fail('Mã trụ đã tồn tại')
    row=TruBom(**data,tx_ma=sid,tb_luyke=data['tb_mocdau'])
    db.add(row); db.flush()
    db.add_all([TruBomNhienLieu(tb_ma=row.tb_ma,tx_ma=sid,nl_ma=f) for f in sorted(fuels)])
    db.flush(); return pump_dict(db,row)

def edit_pump(db,sid,pid,user,data):
    station_lock(db,sid,user)
    row=db.scalar(select(TruBom).where(TruBom.tb_ma==pid,TruBom.tx_ma==sid).with_for_update())
    if row is None: fail('Không tìm thấy trụ',404)
    if row.tb_phienban!=data.pop('tb_phienban'): fail('Trụ đã thay đổi; tải lại')
    if row.yc_dang_bom or row.tb_trangthai=='PUMPING': fail('Trụ đang bơm; không thể sửa')
    if any(v is None for v in data.values()): fail('Không được xóa trường bắt buộc',400)
    fuels=data.pop('nl_ma',None)
    if fuels is not None:
        compatible(db,sid,fuels)
        old=list(db.scalars(select(TruBomNhienLieu).where(TruBomNhienLieu.tb_ma==pid)))
        removed={r.nl_ma for r in old}-set(fuels)
        # Preserve historical pump/fuel references; destructive removal is never cascaded.
        if removed and db.scalar(select(BienDongKho.bd_ma).where(BienDongKho.tb_ma==pid,BienDongKho.nl_ma.in_(removed)).limit(1)):
            fail('Không thể bỏ nhiên liệu đã có lịch sử xuất kho')
        for r in old:
            if r.nl_ma in removed: db.delete(r)
        for fid in set(fuels)-{r.nl_ma for r in old}:
            db.add(TruBomNhienLieu(tb_ma=pid,tx_ma=sid,nl_ma=fid))
    for k,v in data.items(): setattr(row,k,v)
    row.tb_phienban+=1; row.tb_ngaycapnhat=func.now(); db.flush()
    return pump_dict(db,row)

def refill(db,user,data):
    sid=data['tx_ma']; station_lock(db,sid,user)
    tank=db.scalar(select(BonChua).where(BonChua.bc_ma==data['tank_id'],BonChua.tx_ma==sid).with_for_update())
    if tank is None: fail('Trạm chưa cấu hình bồn này',404)
    qty=decimal(data['liters']); key='refill:'+data['operation_key']
    old=db.scalar(select(BienDongKho).where(BienDongKho.bd_khoa_chonglap==key))
    if old:
        if old.tx_ma!=sid or old.bc_ma!=tank.bc_ma or old.bd_solit!=qty or old.bd_nhacungcap!=data.get('supplier') or old.nd_tendangnhap!=user.nd_tendangnhap:
            fail('Mã thao tác đã được dùng cho nội dung khác')
        return {'status':'success','replayed':True,'movement_id':old.bd_ma}
    invariant(db,tank)
    if not tank.bc_hoatdong or tank.bc_ton+qty>tank.bc_dungtich: fail('Số lít nhập vượt dung tích hoặc bồn ngừng hoạt động')
    before=tank.bc_ton; tank.bc_ton+=qty; tank.bc_phienban+=1; tank.bc_ngaycapnhat=func.now()
    movement=BienDongKho(bd_ma='BD'+secrets.token_hex(5).upper(),bd_khoa_chonglap=key,
        bc_ma=tank.bc_ma,tx_ma=sid,nl_ma=tank.nl_ma,bd_loai='NHAP',bd_solit=qty,bd_truoc=before,bd_sau=tank.bc_ton,
        bd_nhacungcap=data.get('supplier'),nd_tendangnhap=user.nd_tendangnhap)
    db.add(movement); db.flush()
    return {'status':'success','replayed':False,'movement_id':movement.bd_ma,'tank':tank_dict(tank)}

def quote(db,sid,fid):
    row=db.scalar(select(Gia).where(Gia.tx_ma==sid,Gia.nl_ma==fid).order_by(Gia.ngaygio.desc()).limit(1).with_for_update(read=True))
    if row is None or row.dongia<=0: fail('Chưa có giá nhiên liệu cho trạm này')
    return row

def accept(db,rid,user,maximum_liters=None):
    req,items=request_lock(db,rid,user)
    from app.services.request_lifecycle import refuse_expired
    expired=refuse_expired(db,req)
    if expired:return expired
    if req.ttxn_ma!=REQUEST_WAITING:
        held=db.scalar(select(func.coalesce(func.sum(GiuChoNhienLieu.gc_solit),0)).where(GiuChoNhienLieu.yc_ma==rid,GiuChoNhienLieu.gc_trangthai=='GIU_CHO'))
        same_bound=(req.hinh_thuc_do_xang!='DO_DAY_BINH' and maximum_liters is None) or (req.hinh_thuc_do_xang=='DO_DAY_BINH' and maximum_liters is not None and decimal(maximum_liters)==held)
        if req.ttxn_ma==REQUEST_ACCEPTED and held>0 and same_bound:
            return {'status':'success','yc_ma':rid,'status_code':req.ttxn_ma,'replayed':True}
        fail('Yêu cầu không còn ở trạng thái chờ tiếp nhận')
    if len(items)!=1: fail('Luồng bơm hiện tại yêu cầu đúng một nhiên liệu; tách thành các yêu cầu riêng')
    if maximum_liters is not None and (len(items)!=1 or req.hinh_thuc_do_xang!='DO_DAY_BINH'):
        fail('Giới hạn số lít chỉ dành cho yêu cầu đầy bình một nhiên liệu',400)
    quotes={i.nl_ma:quote(db,req.tx_ma,i.nl_ma) for i in items}
    if req.yc_het_han_luc is None:fail('Đơn cũ cần đối soát, không tiếp nhận tự động')
    tanks=list(db.scalars(select(BonChua).where(BonChua.tx_ma==req.tx_ma,BonChua.nl_ma.in_(quotes),BonChua.bc_hoatdong.is_(True)).order_by(BonChua.bc_ma).with_for_update()))
    # Quotation/tank locks can wait. Recheck server time before creating any hold.
    expired=refuse_expired(db,req)
    if expired:return expired
    for tank in tanks: invariant(db,tank)
    for item in items:
        price=quotes[item.nl_ma]; mode=req.hinh_thuc_do_xang or 'SO_LIT'
        if mode=='SO_TIEN':
            if item.thanhtien is None or item.thanhtien<=0: fail('Chưa có ngân sách hợp lệ')
            qty=(item.thanhtien/price.dongia).quantize(D('.01'),rounding=ROUND_DOWN)
        elif mode=='DO_DAY_BINH':
            if maximum_liters is None: fail('Cần xác nhận số lít tối đa trước khi bơm đầy bình')
            qty=decimal(maximum_liters)
        elif mode=='SO_LIT':
            if item.soluong is None: fail('Chưa có số lít xác định')
            qty=decimal(item.soluong)
        else: fail('Hình thức đổ xăng không được hỗ trợ',400)
        if qty<=0 or qty>=D('1000000') or qty*price.dongia>=D('100000000'): fail('Số lượng/thành tiền vượt giới hạn')
        eligible=[t for t in tanks if t.nl_ma==item.nl_ma]
        if sum((t.bc_ton-t.bc_giucho for t in eligible),D(0))<qty: fail('Không đủ nhiên liệu khả dụng')
        remaining=qty
        for tank in eligible:
            held=min(remaining,tank.bc_ton-tank.bc_giucho)
            if held<=0: continue
            db.add(GiuChoNhienLieu(yc_ma=rid,nl_ma=item.nl_ma,bc_ma=tank.bc_ma,tx_ma=req.tx_ma,gc_solit=held,
                gc_chedo=mode,gia_ngaygio=price.ngaygio,gc_dongia=price.dongia,nd_tendangnhap=user.nd_tendangnhap))
            tank.bc_giucho+=held; tank.bc_phienban+=1; remaining-=held
            if remaining==0: break
        item.soluong=qty; item.thanhtien=(qty*price.dongia).quantize(D('.0001'),rounding=ROUND_HALF_UP)
    # Reserve only. A separate explicit command assigns and starts a pump.
    advance_request(req,REQUEST_ACCEPTED)
    db.flush()
    return {'status':'success','yc_ma':rid,'status_code':req.ttxn_ma,'replayed':False}

def start(db,rid,user,pump_id):
    req,items=request_lock(db,rid,user)
    pump=db.scalar(select(TruBom).where(TruBom.tb_ma==pump_id,TruBom.tx_ma==req.tx_ma).with_for_update().execution_options(populate_existing=True))
    if req.ttxn_ma==REQUEST_PUMPING and pump and pump.yc_dang_bom==rid:
        return dict(status='success',yc_ma=rid,status_code=req.ttxn_ma,replayed=True)
    if req.ttxn_ma!=REQUEST_ACCEPTED or req.yc_het_han_luc is None:fail('Chỉ bắt đầu đơn đã tiếp nhận mới')
    if pump is None or pump.tb_trangthai!='READY' or pump.yc_dang_bom:fail('Trụ không sẵn sàng')
    supports=set(db.scalars(select(TruBomNhienLieu.nl_ma).where(TruBomNhienLieu.tb_ma==pump_id)))
    if not {i.nl_ma for i in items}<=supports:fail('Trụ không hỗ trợ nhiên liệu')
    tanks=list(db.scalars(select(BonChua).join(GiuChoNhienLieu,GiuChoNhienLieu.bc_ma==BonChua.bc_ma).where(GiuChoNhienLieu.yc_ma==rid).order_by(BonChua.bc_ma).with_for_update(of=BonChua)))
    holds=list(db.scalars(select(GiuChoNhienLieu).where(GiuChoNhienLieu.yc_ma==rid).order_by(GiuChoNhienLieu.bc_ma).with_for_update()))
    if not holds or any(h.gc_trangthai!='GIU_CHO' for h in holds):fail('Không có giữ chỗ hợp lệ')
    for tank in tanks:
        invariant(db,tank)
        if not tank.bc_hoatdong:fail('Bồn đã ngừng hoạt động; cần đối soát')
    for item in items:
        if sum((h.gc_solit for h in holds if h.nl_ma==item.nl_ma),D(0))!=item.soluong:fail('Giữ chỗ không khớp định mức')
    advance_request(req,REQUEST_PUMPING)
    pump.tb_trangthai='PUMPING';pump.yc_dang_bom=rid;pump.tb_phienban+=1;pump.tb_ngaycapnhat=func.now()
    db.flush();return dict(status='success',yc_ma=rid,status_code=req.ttxn_ma,pump_id=pump_id,replayed=False)

def complete(db,rid,user,data):
    req,items=request_lock(db,rid,user)
    # Existing operational posting, not merely a pre-existing generic invoice.
    gd=db.scalar(select(GiaoDich).join(BienDongKho,BienDongKho.gd_ma==GiaoDich.gd_ma).where(BienDongKho.yc_ma==rid).limit(1))
    qty=decimal(data['so_lit_thuc_te'])
    if gd:
        details=list(db.scalars(select(ChiTietGiaoDich).where(ChiTietGiaoDich.gd_ma==gd.gd_ma)))
        if len(details)!=1 or details[0].soluong!=qty: fail('Kết quả hoàn tất trước đó khác dữ liệu gửi lại')
        if data.get('dongia') is not None and data['dongia']!=details[0].dongialucban: fail('Đơn giá không khớp')
        if data.get('so_tien_thuc_te') is not None and data['so_tien_thuc_te']!=gd.gd_sotien: fail('Thành tiền không khớp')
        return sale_response(db,gd,details[0],True)
    if req.ttxn_ma!=REQUEST_PUMPING or len(items)!=1: fail('Chỉ hoàn tất đơn một nhiên liệu đã giữ chỗ và bắt đầu bơm')
    if db.scalar(select(GiaoDich.gd_ma).where(GiaoDich.yc_ma==rid).limit(1)): fail('Yêu cầu đã có hóa đơn chưa đối soát')
    pump=db.scalar(select(TruBom).where(TruBom.yc_dang_bom==rid,TruBom.tx_ma==req.tx_ma).with_for_update())
    if pump is None or pump.tb_trangthai!='PUMPING': fail('Yêu cầu chưa gắn trụ bơm thực tế')
    tanks=list(db.scalars(select(BonChua).join(GiuChoNhienLieu,GiuChoNhienLieu.bc_ma==BonChua.bc_ma).where(GiuChoNhienLieu.yc_ma==rid).order_by(BonChua.bc_ma).with_for_update(of=BonChua)))
    for tank in tanks: invariant(db,tank)
    holds=list(db.scalars(select(GiuChoNhienLieu).where(GiuChoNhienLieu.yc_ma==rid).order_by(GiuChoNhienLieu.bc_ma).with_for_update()))
    if not holds or any(h.gc_trangthai!='GIU_CHO' for h in holds) or qty>sum((h.gc_solit for h in holds),D(0)): fail('Số lít thực tế vượt số lượng giữ chỗ')
    prices={h.gc_dongia for h in holds}
    if len(prices)!=1: fail('Đơn giá giữ chỗ không nhất quán')
    price=next(iter(prices)); amount=(qty*price).quantize(D('.0001'),rounding=ROUND_HALF_UP)
    if amount>=D('100000000'): fail('Hóa đơn vượt giới hạn')
    if data.get('dongia') is not None and data['dongia']!=price: fail('Đơn giá không khớp giá đã chốt')
    if data.get('so_tien_thuc_te') is not None and data['so_tien_thuc_te']!=amount: fail('Thành tiền phải khớp số lít và giá đã chốt')
    today=date.today()
    # Date creation is serialized across stations; ON CONFLICT does not commit.
    from sqlalchemy.dialects.postgresql import insert
    db.execute(insert(ThoiDiem).values(ngaygio=today).on_conflict_do_nothing())
    gid='GD'+secrets.token_hex(3).upper()
    gd=GiaoDich(gd_ma=gid,nd_tendangnhap=req.nd_tendangnhap,tx_ma=req.tx_ma,yc_ma=rid,
        ngaygio=today,gd_sotien=amount,gd_mathamchieu='PETRO-'+gid,tt_ma=PAYMENT_PROCESSING,pttt_ten='VIETQR')
    db.add(gd); db.flush()
    item=items[0]; detail=ChiTietGiaoDich(gd_ma=gid,nl_ma=item.nl_ma,soluong=qty,thanhtien=amount,dongialucban=price)
    db.add(detail); db.flush()
    by_id={t.bc_ma:t for t in tanks}; remaining=qty; meter=pump.tb_luyke
    for hold in holds:
        tank=by_id[hold.bc_ma]; used=min(remaining,hold.gc_solit)
        tank.bc_giucho-=hold.gc_solit; hold.gc_trangthai='DA_TIEU_THU'; hold.gc_ngaycapnhat=func.now()
        db.flush()  # CHECK reserved <= stock before physical deduction.
        if used:
            before=tank.bc_ton; tank.bc_ton-=used
            db.add(BienDongKho(bd_ma='BD'+secrets.token_hex(5).upper(),bd_khoa_chonglap='sale:'+rid+':'+tank.bc_ma,
                bc_ma=tank.bc_ma,tx_ma=req.tx_ma,nl_ma=item.nl_ma,bd_loai='XUAT',bd_solit=used,bd_truoc=before,bd_sau=tank.bc_ton,
                yc_ma=rid,gd_ma=gid,tb_ma=pump.tb_ma,bd_luyke_truoc=meter,bd_luyke_sau=meter+used,nd_tendangnhap=user.nd_tendangnhap))
            meter+=used; remaining-=used
        tank.bc_phienban+=1; tank.bc_ngaycapnhat=func.now()
    pump.tb_luyke=meter; pump.tb_trangthai='READY'; pump.yc_dang_bom=None; pump.tb_phienban+=1; pump.tb_ngaycapnhat=func.now()
    item.soluong=qty; item.thanhtien=amount; advance_request(req,REQUEST_COMPLETED)
    db.flush(); return sale_response(db,gd,detail,False)

def cancel(db,rid,user,*,confirm_no_dispense=False,reason=None):
    from app.services.request_lifecycle import cancel as command
    return command(db,rid,user,reason,confirm_no_dispense)

def reject(db,rid,user):
    """A station refusal, not a customer cancellation or physical-stock reversal."""
    req,_=request_lock(db,rid,user)
    if db.scalar(select(GiuChoNhienLieu.yc_ma).where(GiuChoNhienLieu.yc_ma==rid).limit(1)) or db.scalar(select(GiaoDich.gd_ma).where(GiaoDich.yc_ma==rid).limit(1)):
        fail('Không thể từ chối yêu cầu đã giữ chỗ/bơm/xuất hóa đơn; cần đối soát')
    advance_request(req,REQUEST_REJECTED)
    db.flush();return req

def cash(db,gid,user,*,method='TIEN_MAT',reference=None):
    if get_user_role(user)[0]!='DOANH_NGHIEP': fail('Chỉ chủ trạm được xác nhận thanh toán',403)
    rid=db.scalar(select(GiaoDich.yc_ma).where(GiaoDich.gd_ma==gid))
    if rid is None: fail('Không tìm thấy giao dịch',404)
    req,_=request_lock(db,rid,user,cancellation=True)
    gd=db.scalar(select(GiaoDich).where(GiaoDich.gd_ma==gid).with_for_update().execution_options(populate_existing=True))
    if not db.scalar(select(BienDongKho.bd_ma).where(BienDongKho.gd_ma==gid).limit(1)): fail('Hóa đơn chưa có bút toán bơm; cần đối soát')
    if gd.tt_ma==PAYMENT_SUCCEEDED:
        if gd.pttt_ten!=method: fail('Giao dịch đã thanh toán bằng phương thức khác')
        return {'status':'success','gd_ma':gid,'replayed':True}
    if gd.tt_ma!=PAYMENT_PROCESSING or req.ttxn_ma!=REQUEST_COMPLETED: fail('Trạng thái thanh toán không hợp lệ')
    advance_payment(gd,PAYMENT_SUCCEEDED)
    gd.pttt_ten=method; gd.gd_mathamchieu=reference or 'CASH-'+gid
    db.flush(); return {'status':'success','gd_ma':gid,'amount':gd.gd_sotien}

def record_payment_failure(db,gid,user):
    """Internal audited adapter operation, not an unauthenticated failure endpoint.

    Only call on an explicitly verified terminal failure, never on network timeout.
    The existing inbound bank adapter supplies success events only.
    """
    if get_user_role(user)[0]!='DOANH_NGHIEP': fail('Không có quyền đối soát',403)
    rid=db.scalar(select(GiaoDich.yc_ma).where(GiaoDich.gd_ma==gid))
    if rid is None: fail('Không tìm thấy giao dịch',404)
    req,_=request_lock(db,rid,user,cancellation=True)
    gd=db.scalar(select(GiaoDich).where(GiaoDich.gd_ma==gid).with_for_update().execution_options(populate_existing=True))
    if req.ttxn_ma!=REQUEST_COMPLETED or not db.scalar(select(BienDongKho.bd_ma).where(BienDongKho.gd_ma==gid).limit(1)):
        fail('Giao dịch chưa có bút toán bơm hợp lệ')
    if gd.tt_ma==PAYMENT_FAILED:return {'status':'success','gd_ma':gid,'replayed':True}
    advance_payment(gd,PAYMENT_FAILED)
    db.flush();return {'status':'success','gd_ma':gid,'replayed':False}

def tank_dict(t):
    return dict(tank_id=t.bc_ma,tank_name=t.bc_ten,nl_ma=t.nl_ma,capacity=t.bc_dungtich,
        current_liters=t.bc_ton,reserved_liters=t.bc_giucho,available_liters=t.bc_ton-t.bc_giucho,
        min_alert_liters=t.bc_nguong,percentage=(t.bc_ton/t.bc_dungtich*100),version=t.bc_phienban,active=t.bc_hoatdong,
        last_updated=t.bc_ngaycapnhat.isoformat() if t.bc_ngaycapnhat else None,
        alert_status='CRITICAL' if t.bc_ton-t.bc_giucho<=t.bc_nguong else 'SAFE')

def pump_dict(db,p):
    fuels=list(db.scalars(select(TruBomNhienLieu.nl_ma).where(TruBomNhienLieu.tb_ma==p.tb_ma).order_by(TruBomNhienLieu.nl_ma)))
    return dict(pump_id=p.tb_ma,pump_code=p.tb_code,pump_name=p.tb_ten,status=p.tb_trangthai,
        fuels=fuels,totalizer_liters=p.tb_luyke,baseline=p.tb_mocdau,version=p.tb_phienban,current_session=p.yc_dang_bom)

def inventory(db,sid,user):
    station_lock(db,sid,user)
    tanks=list(db.scalars(select(BonChua).where(BonChua.tx_ma==sid).order_by(BonChua.nl_ma,BonChua.bc_ma)))
    pumps=list(db.scalars(select(TruBom).where(TruBom.tx_ma==sid).order_by(TruBom.tb_ma)))
    latest_prices={}
    for row in db.scalars(select(Gia).where(Gia.tx_ma==sid).order_by(Gia.ngaygio.desc(),Gia.nl_ma)):
        latest_prices.setdefault(row.nl_ma,row.dongia)
    priced={fid for fid,price in latest_prices.items() if price.is_finite() and price>0}
    ready_pumps=[p for p in pumps if p.tb_trangthai=='READY' and p.yc_dang_bom is None]
    supported=set(db.scalars(select(TruBomNhienLieu.nl_ma).where(TruBomNhienLieu.tb_ma.in_([p.tb_ma for p in ready_pumps])))) if ready_pumps else set()
    for t in tanks: invariant(db,t)
    available={f:sum((t.bc_ton-t.bc_giucho for t in tanks if t.nl_ma==f and t.bc_hoatdong),D(0)) for f in sorted(CANONICAL)}
    history=list(db.scalars(select(BienDongKho).where(BienDongKho.tx_ma==sid,BienDongKho.bd_loai=='NHAP').order_by(BienDongKho.bd_ngaytao.desc()).limit(20)))
    return dict(status='success',tx_ma=sid,tanks=[tank_dict(t) for t in tanks],pumps=[pump_dict(db,p) for p in pumps],
        total_current_liters=sum((t.bc_ton for t in tanks),D(0)),total_capacity_liters=sum((t.bc_dungtich for t in tanks),D(0)),
        total_capacity=sum((t.bc_dungtich for t in tanks),D(0)),
        overall_percentage=(sum((t.bc_ton for t in tanks),D(0))/sum((t.bc_dungtich for t in tanks),D(0))*100) if tanks else D(0),
        refill_history=[dict(refill_id=h.bd_ma,tank_name=next(t.bc_ten for t in tanks if t.bc_ma==h.bc_ma),liters=h.bd_solit,supplier=h.bd_nhacungcap,created_at=h.bd_ngaytao.isoformat()) for h in history],
        readiness=dict(publicly_approved=True,has_prices=bool(priced),has_tanks=bool(tanks),has_usable_pump=bool(ready_pumps),
            available_by_fuel=available,ready_fuels=sorted(f for f in CANONICAL if f in priced and f in supported and available[f]>0)),
        storage='postgresql')

def sale_dict(gd,item,replayed):
    return dict(status='success',gd_ma=gd.gd_ma,yc_ma=gd.yc_ma,soluong=item.soluong,
        dongia=item.dongialucban,thanhtien=gd.gd_sotien,replayed=replayed,transfer_content='PETRO '+gd.gd_ma)

def sale_response(db,gd,item,replayed):
    rows=list(db.scalars(select(BonChua).where(BonChua.tx_ma==gd.tx_ma,BonChua.nl_ma==item.nl_ma)))
    stock=sum((r.bc_ton for r in rows),D(0)); capacity=sum((r.bc_dungtich for r in rows),D(0))
    return dict(sale_dict(gd,item,replayed), **qr_fields(gd.gd_ma, gd.gd_sotien),
        tank_name=' / '.join(r.bc_ten for r in rows),tank_liters_remaining=stock,
        tank_capacity=capacity,tank_percentage=stock/capacity*100 if capacity else D(0))

def frozen_quote(db,rid,fid):
    return db.scalar(select(GiuChoNhienLieu.gc_dongia).where(GiuChoNhienLieu.yc_ma==rid,GiuChoNhienLieu.nl_ma==fid).limit(1))

def intake(db,user,rid,sid,fid,plate,mode,liters,budget):
    station_lock(db,sid,user,customer=True)
    if mode not in ('SO_LIT','SO_TIEN','DO_DAY_BINH'): fail('Hình thức đổ xăng không hợp lệ',400)
    existing=db.scalar(select(YeuCauDoXang).where(YeuCauDoXang.yc_ma==rid).with_for_update())
    if existing:
        item=db.get(ChiTietYeuCau,(fid,rid))
        if existing.nd_tendangnhap!=user.nd_tendangnhap or existing.tx_ma!=sid or (existing.pt_bienso or '').strip()!=plate or existing.hinh_thuc_do_xang!=mode or not item or item.soluong!=liters or item.thanhtien!=budget:
            fail('Mã yêu cầu đã được dùng cho nội dung khác')
        return {'status':'success','yc_ma':rid,'replayed':True}
    if mode=='SO_LIT':
        liters=decimal(liters)
        if liters>=D('1000000'): fail('Số lít vượt giới hạn',400)
    elif mode=='SO_TIEN':
        budget=decimal(budget)
        if budget>=D('100000000'): fail('Số tiền vượt giới hạn',400)
    else: liters=budget=None
    price=quote(db,sid,fid)
    maximum=liters if mode=='SO_LIT' else ((budget/price.dongia).quantize(D('.01'),rounding=ROUND_DOWN) if mode=='SO_TIEN' else None)
    validate_intake_configuration(db,sid,fid,maximum)
    req=YeuCauDoXang(yc_ma=rid,tx_ma=sid,nd_tendangnhap=user.nd_tendangnhap,ttxn_ma=REQUEST_WAITING,pt_bienso=plate,hinh_thuc_do_xang=mode,
        yc_het_han_luc=db.scalar(select(func.clock_timestamp()+text("interval '180 seconds'"))))
    db.add(req); db.flush(); db.add(ChiTietYeuCau(yc_ma=rid,nl_ma=fid,soluong=liters,thanhtien=budget)); db.flush()
    from app.services.request_lifecycle import metadata
    return {'status':'success','yc_ma':rid,'quantity_confirmation_required':mode=='DO_DAY_BINH','replayed':False,**metadata(req,db)}

def validate_intake_configuration(db,sid,fid,maximum):
    # Caller holds enterprise/station locks; all operational writers use that order.
    from app.services.station_readiness import customer_readiness
    summary=customer_readiness(db,sid,fid,'SO_LIT' if maximum is not None else 'DO_DAY_BINH',liters=maximum)
    if not summary['orderable']:
        fail(summary['message'],400 if summary['reason_code']=='INVALID_QUANTITY' else 409)

def bank_callback(db, transactions):
    """Casso bank receipts already verified by router; preserve PG stock guards.

    Exactly-once payment marking uses original PG advisory event lock and locks
    the station/owner according to the project-wide lock order. Not a ledger for
    unmatched/overpaid events; these remain pending manual reconciliation.
    """
    processed, events = [], {}
    for item in transactions:
        if not isinstance(item, dict):
            fail('Sự kiện ngân hàng không hợp lệ',400)
        gid, tid = item.get('gd_ma'), item.get('tid')
        if not isinstance(gid,str) or not re.fullmatch(r'GD[A-Z0-9]{6}',gid) or bank_transaction_id(tid) != tid or not tid:
            fail('Định danh sự kiện ngân hàng không hợp lệ',400)
        try:
            amount = D(str(item.get('amount')))
        except Exception:
            fail('Số tiền ngân hàng không hợp lệ',400)
        if not amount.is_finite() or amount <= 0 or amount >= D('1000000000000'):
            fail('Số tiền ngân hàng không hợp lệ',400)
        if tid in events and events[tid] != (gid,amount):
            fail('TID có nội dung hóa đơn hoặc số tiền xung đột')
        events[tid] = (gid,amount)

    # Lock every verified TID before reading settlement state, including receipt
    # amounts that don't match. Otherwise a conflicting entry can be silently
    # filtered out before the idempotency check. No helper commits inside UoW.
    for tid,(gid,amount) in sorted(events.items()):
        db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:event, 0))'),{'event':'petro-bank:'+tid})
        prior = list(db.scalars(select(GiaoDich).where(GiaoDich.gd_mathamchieu==tid).limit(2).execution_options(populate_existing=True)))
        if len(prior)>1:
            fail('TID có nhiều hóa đơn lịch sử; cần đối soát')
        previous = prior[0] if prior else None
        if previous and (previous.gd_ma!=gid or previous.tt_ma!=PAYMENT_SUCCEEDED or previous.pttt_ten!='VIETQR'
                         or payment_amount(previous.gd_sotien)!=amount):
            fail('TID đã được dùng với nội dung thanh toán khác')

    found=[]
    for tid,(gid,amount) in events.items():
        gd=db.scalar(select(GiaoDich).where(GiaoDich.gd_ma==gid).execution_options(populate_existing=True))
        if gd is None or gd.tx_ma is None:
            processed.append(dict(gd_ma=gid,tid=tid,status='manual_reconciliation_order_not_found',
                reconciliation_status='ORDER_NOT_FOUND',is_settled=False,audit_persisted=False))
        else:
            found.append((gd.tx_ma,gid,tid,amount,gd.yc_ma))
    station_ids=sorted({x[0] for x in found})
    owners=sorted(set(db.scalars(select(TramXang.nd_tendangnhap).where(TramXang.tx_ma.in_(station_ids)))))
    list(db.scalars(select(DoanhNghiep).where(DoanhNghiep.nd_tendangnhap.in_(owners)).order_by(DoanhNghiep.nd_tendangnhap).with_for_update()))
    list(db.scalars(select(TramXang).where(TramXang.tx_ma.in_(station_ids)).order_by(TramXang.tx_ma).with_for_update()))
    for sid,gid,tid,amount,rid in sorted(found):
        station=db.get(TramXang,sid)
        owner=db.get(NguoiDung,station.nd_tendangnhap)
        # Follow the cash path's parent -> request -> invoice lock order. It
        # revalidates ownership and preserved-request rules; never bypass them.
        req,_=request_lock(db,rid,owner,cancellation=True)
        gd = db.scalar(select(GiaoDich).where(GiaoDich.gd_ma==gid).with_for_update().execution_options(populate_existing=True))
        if gd.tx_ma!=sid or gd.yc_ma!=rid:
            fail('Hóa đơn đã thay đổi phạm vi; cần đối soát')
        expected=payment_amount(gd.gd_sotien)
        details=dict(gd_ma=gid,tid=tid,expected_amount=expected,actual_amount=amount,
            shortage_amount=max(expected-amount,D(0)),excess_amount=max(amount-expected,D(0)),
            is_settled=False,audit_persisted=False)
        if amount!=expected:
            processed.append(dict(details,status='manual_reconciliation_amount_mismatch',
                reconciliation_status='SHORTAGE' if amount<expected else 'EXCESS'))
            continue
        if gd.tt_ma == PAYMENT_SUCCEEDED:
            same=gd.pttt_ten=='VIETQR' and gd.gd_mathamchieu==tid
            processed.append(dict(details,status='already_paid' if same else 'manual_reconciliation_already_paid',
                reconciliation_status='SETTLED' if same else 'DUPLICATE_PAYMENT',
                is_settled=same,replayed=same))
            continue
        if gd.tt_ma != PAYMENT_PROCESSING or req.ttxn_ma!=REQUEST_COMPLETED:
            processed.append(dict(details,status='manual_reconciliation_invalid_state',
                reconciliation_status='INVALID_STATE'))
            continue
        if not db.scalar(select(BienDongKho.bd_ma).where(BienDongKho.gd_ma==gid).limit(1)):
            processed.append(dict(details,status='manual_reconciliation_not_posted',reconciliation_status='NOT_POSTED'))
            continue
        result=cash(db,gid,owner,method='VIETQR',reference=tid)
        processed.append({**details,**result,'amount':amount,'reconciliation_status':'SETTLED','is_settled':True})
    return dict(error=0,processed_count=len(processed),details=processed,
        settled_count=sum(p['is_settled'] for p in processed),
        reconciliation_count=sum(not p['is_settled'] for p in processed))
