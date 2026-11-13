import secrets
import string
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import func,select,delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.core.auth import get_user_role
from app.models import TramXang,TepMinhChung,YeuCauDuyetTram,DichVu,TxDv
from app.schemas.station_approval import StationDraftInput,STATION_FIELDS
from app.services.enterprise_approval import atomic,lock_enterprise,new_id,staging,attached
from app.services.enterprise_evidence import MAX_STAGED_FILES


def owned(db,user,station_id,lock=False):
    q=select(TramXang).where(TramXang.tx_ma==station_id)
    if lock:q=q.with_for_update().execution_options(populate_existing=True)
    station=db.scalars(q).first()
    if station is None:raise HTTPException(404,"Không tìm thấy trạm")
    if station.nd_tendangnhap!=user.nd_tendangnhap:raise HTTPException(403,"Trạm không thuộc doanh nghiệp của bạn")
    return station


def approved_owner(db,user):
    dn=lock_enterprise(db,user.nd_tendangnhap)
    if get_user_role(user)[0]!="DOANH_NGHIEP" or dn.dn_trangthai!="DA_DUYET":
        raise HTTPException(403,"Chỉ doanh nghiệp đã duyệt được quản lý hồ sơ trạm")
    return dn


def list_owned(db,user):
    return db.scalars(select(TramXang).where(TramXang.nd_tendangnhap==user.nd_tendangnhap).order_by(TramXang.tx_ma)).all()


def values(station):
    data={k:getattr(station,k) for k in STATION_FIELDS}
    return data


def validate(data):
    try:return StationDraftInput(**data)
    except ValueError as error:raise HTTPException(400,"Thông tin trạm không hợp lệ: cần tên, địa chỉ và GPS đúng giới hạn") from error


def create_draft(db,user,data):
    with atomic(db):
        approved_owner(db,user)
        data=validate(data).model_dump()
        if db.scalar(select(TramXang.tx_ma).where(TramXang.nd_tendangnhap==user.nd_tendangnhap,
                func.lower(func.trim(TramXang.tx_ten))==data['tx_ten'].lower(),
                func.lower(func.trim(TramXang.tx_diachi))==data['tx_diachi'].lower())):
            raise HTTPException(409,"Đã có trạm cùng tên và địa chỉ trong doanh nghiệp; mở hồ sơ hiện có, không tạo bản sao.")
        for _ in range(20):
            code="TX"+"".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
            if db.get(TramXang,code) is not None:continue
            row=TramXang(tx_ma=code,nd_tendangnhap=user.nd_tendangnhap,**data,
                         tx_trangthai="NHAP",tx_congkhai=False,tx_du_lieu_cu=False,tx_phienban_hientai=0)
            try:
                with db.begin_nested():db.add(row);db.flush()
                break
            except IntegrityError:
                if db.get(TramXang,code) is None:raise
        else:raise HTTPException(409,"Không thể cấp mã trạm; vui lòng thử lại")
    db.refresh(row);return row


def save_draft(db,user,station_id,data):
    with atomic(db):
        approved_owner(db,user); row=owned(db,user,station_id,True)
        if row.tx_phienban_hientai>0 or row.tx_congkhai:
            raise HTTPException(409,"Trạm đang hoạt động: không sửa trực tiếp bằng API nháp; cần luồng cập nhật có audit hợp lệ.")
        if row.tx_trangthai not in {'NHAP','CAN_BO_SUNG','TU_CHOI'} or db.scalar(select(YeuCauDuyetTram.ycdt_ma).where(
                YeuCauDuyetTram.tx_ma==station_id,YeuCauDuyetTram.ycdt_trangthai=='CHO_DUYET')):
            raise HTTPException(409,"Hồ sơ lịch sử đã nộp cần đối soát trước khi chỉnh sửa; không tự đổi trạng thái.")
        validated=validate({**values(row),**data})
        for key,value in validated.model_dump().items():setattr(row,key,value)
        row.tx_trangthai="NHAP"
        row.tx_congkhai=False
        db.flush()
    db.refresh(row);return row


def delete_draft(db,user,station_id):
    with atomic(db):
        approved_owner(db,user);row=owned(db,user,station_id,True)
        if row.tx_phienban_hientai>0 or db.scalar(select(YeuCauDuyetTram.ycdt_ma).where(YeuCauDuyetTram.tx_ma==station_id)):
            raise HTTPException(409,"Không xóa trạm đã duyệt hoặc có lịch sử xét duyệt")
        db.delete(row)


def upload(db,user,station_id,store,name,mime,data):
    meta=None
    try:
        with atomic(db):
            approved_owner(db,user);owned(db,user,station_id,True)
            if len(staging(db,user,store,scope=None))>=MAX_STAGED_FILES:raise HTTPException(400,"Tối đa 10 minh chứng nháp/doanh nghiệp")
            meta=store.stage(user.nd_tendangnhap,name,mime,data,scope="station",station_id=station_id)
    except Exception:
        if meta is not None:store.remove(meta)
        raise
    return meta


def stages(db,user,station_id,store):
    with atomic(db):
        approved_owner(db,user);owned(db,user,station_id,True)
        return staging(db,user,store,"station",station_id)


def remove_stage(db,user,station_id,token,store):
    with atomic(db):
        approved_owner(db,user);owned(db,user,station_id,True)
        meta=store.read(token,user.nd_tendangnhap,allow_expired=True)
        if meta.get("scope")!="station" or meta.get("station_id")!=station_id:raise HTTPException(403,"Minh chứng không thuộc trạm này")
        if attached(db,meta["path"]):raise HTTPException(409,"Minh chứng đã nộp không được xóa")
        store.remove(meta)


def get_request(db,user,request_id):
    row=db.scalars(select(YeuCauDuyetTram).options(selectinload(YeuCauDuyetTram.tep_minh_chung))
                   .where(YeuCauDuyetTram.ycdt_ma==request_id)).first()
    if row is None:raise HTTPException(404,"Không tìm thấy lần nộp trạm")
    if get_user_role(user)[0]!="QUAN_TRI_VIEN":owned(db,user,row.tx_ma)
    return row


def history(db,user,station_id):
    owned(db,user,station_id)
    return db.scalars(select(YeuCauDuyetTram).options(selectinload(YeuCauDuyetTram.tep_minh_chung))
                      .where(YeuCauDuyetTram.tx_ma==station_id).order_by(YeuCauDuyetTram.ycdt_lan_gui.desc())).all()


def amenity_records(db, ids, *, conflict=False):
    """Shared catalog row locks keep existence/names stable until this commit."""
    rows=db.execute(select(DichVu.dv_ma,DichVu.dv_ten).where(DichVu.dv_ma.in_(ids))
                    .order_by(DichVu.dv_ma).with_for_update(read=True,of=DichVu)).all()
    if {code for code,name in rows}!=set(ids):
        raise HTTPException(409 if conflict else 400,'Tiện ích đã bị xóa hoặc không tồn tại; tải lại danh mục và gửi đề xuất mới.')
    return [{'dv_ma':code,'dv_ten':name} for code,name in rows]


def current_amenities(db,station_id):
    ids=list(db.scalars(select(TxDv.dv_ma).where(TxDv.tx_ma==station_id).order_by(TxDv.dv_ma)))
    return amenity_records(db,ids)


def verify_reviewed_draft_amenities(db, station, snapshot):
    # Older pre-amenity submissions remain readable. New submissions always
    # include IDs and frozen names; approval must not publish a different set.
    if 'amenities' not in snapshot:
        return
    try:
        entries = snapshot['amenities']
        if not isinstance(entries, list) or len(entries) > 50:
            raise ValueError()
        ids = [item['dv_ma'] for item in entries]
        if (any(not isinstance(code, str) or len(code) != 8 for code in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, 'Snapshot tiện ích trạm mới không hợp lệ; cần gửi lại hồ sơ.')
    actual = set(db.scalars(select(TxDv.dv_ma).where(TxDv.tx_ma == station.tx_ma).with_for_update()))
    if actual != set(ids):
        raise HTTPException(409, 'Tiện ích nháp khác tập đã xét duyệt; không công khai dữ liệu ngoài snapshot.')
    amenity_records(db, sorted(ids), conflict=True)


def apply_amenity_change(db,station,snapshot):
    change=snapshot.get('amenity_change')
    if change is None:return  # Backwards-compatible field-only/older requests.
    try:
        if not isinstance(change,dict):raise ValueError()
        def ids(key):
            entries=change[key]
            if not isinstance(entries,list) or len(entries)>50:raise ValueError()
            codes=[entry['dv_ma'] for entry in entries]
            if any(not isinstance(code,str) or len(code)!=8 for code in codes) or len(set(codes))!=len(codes):raise ValueError()
            return set(codes)
        before,proposed=ids('current'),ids('proposed')
    except (KeyError,TypeError,ValueError):
        raise HTTPException(409,'Snapshot tiện ích không hợp lệ; cần gửi lại đề xuất.')
    live=set(db.scalars(select(TxDv.dv_ma).where(TxDv.tx_ma==station.tx_ma).with_for_update()))
    if live!=before:
        raise HTTPException(409,'Tiện ích hiện tại đã thay đổi so với snapshot; không ghi đè dữ liệu mới.')
    amenity_records(db,sorted(proposed),conflict=True)
    removed=live-proposed
    if removed:
        db.execute(delete(TxDv).where(TxDv.tx_ma==station.tx_ma,TxDv.dv_ma.in_(removed)),
                   execution_options={'synchronize_session':'fetch'})
    for code in sorted(proposed-live):db.add(TxDv(tx_ma=station.tx_ma,dv_ma=code))
    db.flush()


def submit(db,user,station_id,payload,store,*,self_service=False):
    with atomic(db):
        approved_owner(db,user);station=owned(db,user,station_id,True)
        if self_service:
            from app.services.station_self_service import require_schema
            require_schema(db)
            if payload.base_version != station.tx_phienban_hientai:
                raise HTTPException(409,"Phiên bản trạm đã thay đổi; tải lại trước khi kích hoạt/cập nhật.")
            if station.tx_phienban_hientai==0 and (station.tx_congkhai or station.tx_trangthai not in {'NHAP','CAN_BO_SUNG','TU_CHOI'}):
                raise HTTPException(409,"Hồ sơ cũ không thể tự chuyển trạng thái; cần chủ máy đối soát.")
        if db.scalar(select(YeuCauDuyetTram.ycdt_ma).where(YeuCauDuyetTram.tx_ma==station_id,YeuCauDuyetTram.ycdt_trangthai=="CHO_DUYET")):
            raise HTTPException(409,"Trạm đã có yêu cầu đang chờ duyệt")
        is_update=station.tx_phienban_hientai>0
        if is_update and station.tx_trangthai!="DA_DUYET":raise HTTPException(409,"Trạm đang tạm ngừng; không được tự tái công khai")
        if is_update and (payload.base_version is None or payload.base_version!=station.tx_phienban_hientai):
            raise HTTPException(409,"Phiên bản trạm đã thay đổi; tải lại thông tin")
        if payload.proposed_amenity_ids is not None and not is_update:
            raise HTTPException(400,'Đề xuất tập tiện ích chỉ dành cho CAP_NHAT trạm đã duyệt; tiện ích nháp dùng API hiện có.')
        changes=payload.proposed_values.model_dump(exclude_unset=True) if payload.proposed_values else {}
        candidate=validate({**values(station),**changes})
        if len(candidate.tx_ten)<2 or len(candidate.tx_diachi)<5:raise HTTPException(400,"Tên trạm cần ít nhất 2 ký tự; địa chỉ cần ít nhất 5 ký tự")
        if len(set(payload.evidence_tokens))!=len(payload.evidence_tokens):raise HTTPException(400,"Minh chứng bị trùng")
        metas=[]
        for token in payload.evidence_tokens:
            meta=store.read(token,user.nd_tendangnhap)
            if meta.get("scope")!="station" or meta.get("station_id")!=station_id:raise HTTPException(403,"Minh chứng không thuộc trạm này")
            if attached(db,meta["path"]):raise HTTPException(409,"Minh chứng đã thuộc lần nộp cũ")
            store.verify(meta);metas.append(meta)
        seq=(db.scalar(select(func.max(YeuCauDuyetTram.ycdt_lan_gui)).where(YeuCauDuyetTram.tx_ma==station_id)) or 0)+1
        snapshot={**candidate.model_dump(mode="json"),"tx_ma":station_id,"nd_tendangnhap":user.nd_tendangnhap,
                  "base_version":station.tx_phienban_hientai}
        # Private draft assignments are frozen by the same station-row lock.
        # Capture names as well as IDs so later global catalog edits cannot
        # rewrite the evidence of which amenities the administrator reviewed.
        snapshot['amenities'] = current_amenities(db,station_id)
        if payload.expected_amenity_ids is not None:
            if is_update:
                raise HTTPException(400, 'expected_amenity_ids chỉ dùng kiểm tra tập đã lưu của trạm nháp.')
            if set(payload.expected_amenity_ids) != {item['dv_ma'] for item in snapshot['amenities']}:
                raise HTTPException(409, 'Tiện ích nháp đã thay đổi; tải lại trước khi nộp hồ sơ.')
        if payload.proposed_amenity_ids is not None:
            current=snapshot['amenities']
            proposed=amenity_records(db,sorted(payload.proposed_amenity_ids))
            old_ids={item['dv_ma'] for item in current};new_ids={item['dv_ma'] for item in proposed}
            snapshot['amenity_change']={'current':current,'proposed':proposed,
                'added':[item for item in proposed if item['dv_ma'] not in old_ids],
                'removed':[item for item in current if item['dv_ma'] not in new_ids]}
        if self_service:
            snapshot.update(activation_method='SELF_SERVICE_DEMO',activation_actor=user.nd_tendangnhap,
                            activated_version=station.tx_phienban_hientai+1)
        request=YeuCauDuyetTram(ycdt_ma=new_id("TR"),tx_ma=station_id,ycdt_lan_gui=seq,
            ycdt_loai="CAP_NHAT" if is_update else "DANG_KY_MOI",ycdt_dulieu=snapshot,
            ycdt_trangthai="CHO_DUYET",ycdt_ngaygui=datetime.now(timezone.utc))
        db.add(request)
        for meta in metas:request.tep_minh_chung.append(TepMinhChung(tmc_ma=new_id("MC"),tmc_ten=meta["name"],
            tmc_duongdan=meta["path"],tmc_mime=meta["mime"],tmc_kich_thuoc=meta["size"],tmc_sha256=meta["sha256"],tmc_ngaytai=datetime.now(timezone.utc)))
        if self_service:
            if is_update:apply_amenity_change(db,station,snapshot)
            else:verify_reviewed_draft_amenities(db,station,snapshot)
            for key,value in candidate.model_dump().items():setattr(station,key,value)
            station.tx_trangthai='DA_DUYET'
            if not is_update:station.tx_congkhai=True
            station.tx_phienban_hientai+=1
            request.ycdt_trangthai='DA_DUYET'
            request.ycdt_ngayxuly=datetime.now(timezone.utc)
            request.ycdt_lydo='Doanh nghiệp tự kích hoạt/cập nhật theo chính sách demo; không phải quyết định QTV.'
        elif not is_update:
            for key,value in candidate.model_dump().items():setattr(station,key,value)
            station.tx_trangthai="CHO_DUYET";station.tx_congkhai=False
        db.flush()
    return get_request(db,user,request.ycdt_ma)


def admin_list(db,status=None,limit=100,offset=0):
    q=select(YeuCauDuyetTram).options(selectinload(YeuCauDuyetTram.tep_minh_chung))
    if status:q=q.where(YeuCauDuyetTram.ycdt_trangthai==status)
    return db.scalars(q.order_by(YeuCauDuyetTram.ycdt_ngaygui.desc()).limit(limit).offset(offset)).all()


def decide(db,user,request_id,payload):
    if get_user_role(user)[0]!="QUAN_TRI_VIEN":raise HTTPException(403,"Chỉ quản trị viên được duyệt trạm")
    with atomic(db):
        owner=db.scalar(select(TramXang.nd_tendangnhap).join(YeuCauDuyetTram).where(YeuCauDuyetTram.ycdt_ma==request_id))
        if owner is None:raise HTTPException(404,"Không tìm thấy yêu cầu")
        dn=lock_enterprise(db,owner)
        station=db.scalars(select(TramXang).join(YeuCauDuyetTram).where(YeuCauDuyetTram.ycdt_ma==request_id)
                           .with_for_update(of=TramXang).execution_options(populate_existing=True)).one()
        row=db.scalars(select(YeuCauDuyetTram).where(YeuCauDuyetTram.ycdt_ma==request_id)
                       .with_for_update().execution_options(populate_existing=True)).one()
        if station.nd_tendangnhap!=owner:raise HTTPException(409,'Quyền sở hữu trạm đã thay đổi; không thể duyệt snapshot cũ.')
        if row.ycdt_trangthai!="CHO_DUYET":raise HTTPException(409,"Yêu cầu đã được xử lý")
        if row.ycdt_dulieu.get("base_version")!=station.tx_phienban_hientai:raise HTTPException(409,"Phiên bản trạm không còn khớp snapshot")
        update=row.ycdt_loai=="CAP_NHAT"
        if update!=(station.tx_phienban_hientai>0):raise HTTPException(409,"Loại yêu cầu không phù hợp phiên bản trạm")
        if not update and station.tx_trangthai!="CHO_DUYET":raise HTTPException(409,"Trạm không còn chờ duyệt")
        if update and station.tx_trangthai!="DA_DUYET":raise HTTPException(409,"Trạm không còn ở trạng thái đã duyệt")
        if payload.decision=="DA_DUYET":
            if dn.dn_trangthai!="DA_DUYET":raise HTTPException(409,"Doanh nghiệp không còn được duyệt; chưa thể công khai trạm")
            if row.ycdt_dulieu.get("tx_ma")!=station.tx_ma or row.ycdt_dulieu.get("nd_tendangnhap")!=owner:
                raise HTTPException(409,"Snapshot không khớp trạm/doanh nghiệp")
            reviewed=validate({k:row.ycdt_dulieu.get(k) for k in STATION_FIELDS})
            if not update:
                verify_reviewed_draft_amenities(db, station, row.ycdt_dulieu)
            # Same transaction as station fields/version and review decision.
            # Any validation/FK failure rolls the entire relation diff back.
            apply_amenity_change(db,station,row.ycdt_dulieu)
            for k,v in reviewed.model_dump().items():setattr(station,k,v)
            station.tx_trangthai="DA_DUYET"
            if not update:station.tx_congkhai=True
            station.tx_phienban_hientai+=1
        elif not update:
            station.tx_trangthai=payload.decision;station.tx_congkhai=False
        row.ycdt_trangthai=payload.decision;row.qtv_tendangnhap=user.nd_tendangnhap
        row.ycdt_ngayxuly=datetime.now(timezone.utc);row.ycdt_lydo=payload.reason
        db.flush()
    return get_request(db,user,request_id)
