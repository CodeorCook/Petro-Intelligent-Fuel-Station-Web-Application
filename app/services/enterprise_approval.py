import logging
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.auth import get_user_role
from app.models import DoanhNghiep, HoSoDoanhNghiep, TepMinhChung, YeuCauDuyetDoanhNghiep
from app.schemas.enterprise_approval import EnterpriseProfileDraft, PROFILE_LIMITS
from app.services.enterprise_evidence import MAX_STAGED_FILES, STAGING_TTL_SECONDS

logger=logging.getLogger(__name__)


@contextmanager
def atomic(db: Session):
    try:
        yield
        db.commit()
    except HTTPException:
        db.rollback(); raise
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409,"Dữ liệu trùng hoặc xung đột: kiểm tra mã số thuế/lần nộp đang chờ duyệt.") from error
    except SQLAlchemyError as error:
        db.rollback()
        logger.error("Enterprise approval database operation failed")
        raise HTTPException(503,"Không thể xử lý hồ sơ lúc này. Vui lòng thử lại.") from error


def new_id(prefix):return prefix+secrets.token_hex(5).upper()


def lock_enterprise(db,username):
    dn=db.scalars(select(DoanhNghiep).where(DoanhNghiep.nd_tendangnhap==username)
                  .with_for_update().execution_options(populate_existing=True)).first()
    if dn is None:raise HTTPException(404,"Không tìm thấy doanh nghiệp")
    return dn


def editable(dn):
    if dn.dn_trangthai=="TAM_KHOA":raise HTTPException(403,"Doanh nghiệp đang bị khóa; vui lòng liên hệ hỗ trợ")
    if dn.dn_trangthai=="DA_DUYET":raise HTTPException(409,"Doanh nghiệp đã được duyệt; không cần nộp lại hồ sơ")


def profile(db,username):
    return db.scalars(select(HoSoDoanhNghiep).where(HoSoDoanhNghiep.nd_tendangnhap==username)).first()


def save_draft(db,user,values):
    with atomic(db):
        dn=lock_enterprise(db,user.nd_tendangnhap); editable(dn)
        row=profile(db,user.nd_tendangnhap)
        if row is None:
            row=HoSoDoanhNghiep(hsdn_ma=new_id("HS"),nd_tendangnhap=user.nd_tendangnhap)
            db.add(row)
        for key,value in values.items():setattr(row,key,value)
        if row.hsdn_masothue:
            duplicate=db.scalar(select(HoSoDoanhNghiep.hsdn_ma).where(
                func.replace(HoSoDoanhNghiep.hsdn_masothue,"-","")==row.hsdn_masothue.replace("-",""),
                HoSoDoanhNghiep.nd_tendangnhap!=user.nd_tendangnhap,
            ))
            if duplicate:raise HTTPException(409,"Mã số thuế đã được sử dụng bởi hồ sơ khác")
        row.hsdn_ngaycapnhat=datetime.now(timezone.utc)
        db.flush()
    db.refresh(row)
    return row


def attached(db,path):
    return db.scalar(select(TepMinhChung.tmc_ma).where(TepMinhChung.tmc_duongdan==path)) is not None


def staging(db,user,store,scope="enterprise",station_id=None):
    result=[]
    folder=store.root/"staging"
    if not folder.exists():return result
    for path in folder.glob("*.json"):
        try:meta=store.read(path.stem,user.nd_tendangnhap,allow_expired=True)
        except HTTPException:continue
        if attached(db,meta["path"]):continue
        if time.time()-meta["created"]>STAGING_TTL_SECONDS:
            store.remove(meta); continue
        if scope is None or (meta.get("scope","enterprise")==scope and (station_id is None or meta.get("station_id")==station_id)):
            result.append(meta)
    return result


def stage_upload(db,user,store,name,mime,data):
    meta=None
    try:
        with atomic(db):
            dn=lock_enterprise(db,user.nd_tendangnhap); editable(dn)
            if len(staging(db,user,store,scope=None))>=MAX_STAGED_FILES:
                raise HTTPException(400,"Tối đa 10 minh chứng nháp; vui lòng xóa tệp không dùng")
            meta=store.stage(user.nd_tendangnhap,name,mime,data)
    except Exception:
        if meta is not None:store.remove(meta)
        raise
    return meta


def delete_stage(db,user,store,token):
    with atomic(db):
        lock_enterprise(db,user.nd_tendangnhap)
        meta=store.read(token,user.nd_tendangnhap,allow_expired=True)
        if attached(db,meta["path"]):raise HTTPException(409,"Minh chứng đã thuộc một lần nộp; không được xóa")
        store.remove(meta)


def submit(db,user,tokens,store):
    with atomic(db):
        dn=lock_enterprise(db,user.nd_tendangnhap); editable(dn)
        row=profile(db,user.nd_tendangnhap)
        if row is None:raise HTTPException(400,"Vui lòng tạo hồ sơ doanh nghiệp trước")
        data={key:getattr(row,key) for key in PROFILE_LIMITS}
        if any(not value for value in data.values()):
            raise HTTPException(400,"Cần điền đủ tên pháp lý, mã số thuế, địa chỉ, người đại diện, điện thoại và email")
        if len(data["hsdn_tenphaply"])<2 or len(data["hsdn_nguoidaidien"])<2 or len(data["hsdn_diachi"])<5:
            raise HTTPException(400,"Tên pháp lý/người đại diện cần ít nhất 2 ký tự và địa chỉ cần ít nhất 5 ký tự")
        # Draft validation is reapplied to reject malformed legacy/imported data.
        try:validated=EnterpriseProfileDraft(**data)
        except ValueError as error:raise HTTPException(400,"Thông tin hồ sơ không hợp lệ; vui lòng kiểm tra lại") from error
        pending=db.scalar(select(YeuCauDuyetDoanhNghiep.ycdn_ma).where(
            YeuCauDuyetDoanhNghiep.hsdn_ma==row.hsdn_ma,
            YeuCauDuyetDoanhNghiep.ycdn_trangthai=="CHO_DUYET"))
        if pending is not None:raise HTTPException(409,"Đã có hồ sơ đang chờ duyệt")
        if not tokens or len(tokens)>10 or len(set(tokens))!=len(tokens):
            raise HTTPException(400,"Cần 1–10 minh chứng riêng biệt")
        metas=[]
        for token in tokens:
            meta=store.read(token,user.nd_tendangnhap)
            if meta.get("scope","enterprise")!="enterprise":raise HTTPException(400,"Minh chứng này dành cho duyệt trạm")
            if attached(db,meta["path"]):raise HTTPException(409,"Minh chứng đã được nộp; vui lòng tải bản mới")
            store.verify(meta); metas.append(meta)
        next_sequence=(db.scalar(select(func.max(YeuCauDuyetDoanhNghiep.ycdn_lan_gui)).where(
            YeuCauDuyetDoanhNghiep.hsdn_ma==row.hsdn_ma)) or 0)+1
        request=YeuCauDuyetDoanhNghiep(
            ycdn_ma=new_id("DN"),hsdn_ma=row.hsdn_ma,ycdn_lan_gui=next_sequence,
            ycdn_dulieu={**validated.model_dump(),"hsdn_ma":row.hsdn_ma,
                         "nd_tendangnhap":user.nd_tendangnhap,
                         "hsdn_ngaycapnhat":row.hsdn_ngaycapnhat.isoformat()},
            ycdn_trangthai="CHO_DUYET",ycdn_ngaygui=datetime.now(timezone.utc),
        )
        db.add(request)
        for meta in metas:
            request.tep_minh_chung.append(TepMinhChung(
                tmc_ma=new_id("MC"),tmc_ten=meta["name"],tmc_duongdan=meta["path"],
                tmc_mime=meta["mime"],tmc_kich_thuoc=meta["size"],tmc_sha256=meta["sha256"],
                tmc_ngaytai=datetime.now(timezone.utc),
            ))
        dn.dn_trangthai="CHO_DUYET"
        db.flush()
    return get_submission(db,request.ycdn_ma,user)


def get_submission(db,request_id,user):
    row=db.scalars(select(YeuCauDuyetDoanhNghiep).options(selectinload(YeuCauDuyetDoanhNghiep.tep_minh_chung))
                   .where(YeuCauDuyetDoanhNghiep.ycdn_ma==request_id)).first()
    if row is None:raise HTTPException(404,"Không tìm thấy lần nộp")
    role=get_user_role(user)[0]
    if role!="QUAN_TRI_VIEN" and (role!="DOANH_NGHIEP" or row.ho_so_doanh_nghiep.nd_tendangnhap!=user.nd_tendangnhap):
        raise HTTPException(403,"Không có quyền xem hồ sơ này")
    return row


def list_submissions(db,user,status=None,limit=100,offset=0):
    query=select(YeuCauDuyetDoanhNghiep).options(selectinload(YeuCauDuyetDoanhNghiep.tep_minh_chung))
    if get_user_role(user)[0]!="QUAN_TRI_VIEN":
        query=query.join(HoSoDoanhNghiep).where(HoSoDoanhNghiep.nd_tendangnhap==user.nd_tendangnhap)
    if status:query=query.where(YeuCauDuyetDoanhNghiep.ycdn_trangthai==status)
    return db.scalars(query.order_by(YeuCauDuyetDoanhNghiep.ycdn_ngaygui.desc(),YeuCauDuyetDoanhNghiep.ycdn_ma)
                      .limit(limit).offset(offset)).all()


def decide(db,user,request_id,decision,reason):
    if get_user_role(user)[0]!="QUAN_TRI_VIEN":raise HTTPException(403,"Chỉ quản trị viên được xét duyệt")
    with atomic(db):
        owner=db.scalar(select(HoSoDoanhNghiep.nd_tendangnhap).join(YeuCauDuyetDoanhNghiep)
                        .where(YeuCauDuyetDoanhNghiep.ycdn_ma==request_id))
        if owner is None:raise HTTPException(404,"Không tìm thấy lần nộp")
        # Same DN-first lock order as draft/submit/upload prevents deadlocks.
        dn=lock_enterprise(db,owner)
        row=db.scalars(select(YeuCauDuyetDoanhNghiep).where(YeuCauDuyetDoanhNghiep.ycdn_ma==request_id)
                       .with_for_update().execution_options(populate_existing=True)).one()
        if row.ycdn_trangthai!="CHO_DUYET" or dn.dn_trangthai!="CHO_DUYET":
            raise HTTPException(409,"Hồ sơ đã được xử lý hoặc doanh nghiệp không còn chờ duyệt")
        if decision not in {"DA_DUYET","CAN_BO_SUNG","TU_CHOI"}:raise HTTPException(400,"Quyết định không hợp lệ")
        reason=reason.strip() if reason else None
        if decision!="DA_DUYET" and not reason:raise HTTPException(400,"Cần nhập lý do")
        if decision=="DA_DUYET":
            # The approved legal profile must be the version actually reviewed,
            # not a later draft edit that bypassed the submission snapshot.
            reviewed={key:row.ycdn_dulieu.get(key) for key in PROFILE_LIMITS}
            if any(not value for value in reviewed.values()):
                raise HTTPException(409,"Bản chụp hồ sơ chưa đầy đủ để phê duyệt")
            try:reviewed=EnterpriseProfileDraft(**reviewed).model_dump()
            except ValueError as error:raise HTTPException(409,"Bản chụp hồ sơ không hợp lệ") from error
            legal_profile=profile(db,owner)
            for key,value in reviewed.items():setattr(legal_profile,key,value)
            legal_profile.hsdn_ngaycapnhat=datetime.now(timezone.utc)
        row.ycdn_trangthai=decision; row.qtv_tendangnhap=user.nd_tendangnhap
        row.ycdn_ngayxuly=datetime.now(timezone.utc); row.ycdn_lydo=reason
        dn.dn_trangthai=decision
        db.flush()
    return get_submission(db,request_id,user)


def evidence_download(db,user,evidence_id,store):
    row=db.get(TepMinhChung,evidence_id)
    if row is None or row.ycdn_ma is None:raise HTTPException(404,"Không tìm thấy minh chứng doanh nghiệp")
    get_submission(db,row.ycdn_ma,user)
    path=store.object_path(row.tmc_duongdan)
    if not path.is_file():raise HTTPException(404,"Tệp minh chứng không còn khả dụng")
    if row.tmc_kich_thuoc is not None and row.tmc_sha256:
        store.verify({"path":row.tmc_duongdan,"size":row.tmc_kich_thuoc,"sha256":row.tmc_sha256})
    return row,path
