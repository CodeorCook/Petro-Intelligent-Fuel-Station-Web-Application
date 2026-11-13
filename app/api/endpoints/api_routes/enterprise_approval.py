from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.auth import get_current_user, require_admin, require_enterprise_account
from app.database.session import get_db
from app.schemas.enterprise_approval import (
    ApprovalState, EnterpriseApprovalResponse, EnterpriseDecisionInput,
    EnterpriseProfileDraft, EnterpriseProfileResponse, EnterpriseSubmissionInput,
)
from app.services import enterprise_approval as service
from app.services.enterprise_evidence import get_evidence_store, MAX_FILE_BYTES

def check_origin(request:Request):
    if request.method in {"POST","PUT","DELETE"}:
        origin=request.headers.get("origin")
        if origin is not None and origin.rstrip("/")!=str(request.base_url).rstrip("/"):
            raise HTTPException(403,"Yêu cầu phải được gửi từ trang Petro đang đăng nhập")


router=APIRouter(tags=["Enterprise legal approval"],dependencies=[Depends(check_origin)])


@router.get("/api/enterprise/profile",response_model=EnterpriseProfileResponse | None)
def get_profile(db:Session=Depends(get_db),user=Depends(require_enterprise_account)):
    return service.profile(db,user.nd_tendangnhap)


@router.put("/api/enterprise/profile",response_model=EnterpriseProfileResponse)
def save_profile(payload:EnterpriseProfileDraft,db:Session=Depends(get_db),user=Depends(require_enterprise_account)):
    return service.save_draft(db,user,payload.model_dump(exclude_unset=True))


@router.get("/api/enterprise/status")
def get_status(user=Depends(require_enterprise_account)):
    dn=user.doanh_nghiep
    return {"enterprise_status":dn.dn_trangthai,"legacy_data":dn.dn_du_lieu_cu,
            "can_submit":dn.dn_trangthai in {"CHUA_HOAN_THIEN","CAN_BO_SUNG","TU_CHOI"}}


@router.get("/api/enterprise/approvals",response_model=list[EnterpriseApprovalResponse])
def history(limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0),
            db:Session=Depends(get_db),user=Depends(require_enterprise_account)):
    return service.list_submissions(db,user,limit=limit,offset=offset)


@router.get("/api/enterprise/approvals/{request_id}",response_model=EnterpriseApprovalResponse)
def own_submission(request_id:str,db:Session=Depends(get_db),user=Depends(require_enterprise_account)):
    return service.get_submission(db,request_id,user)


@router.post("/api/enterprise/approvals",response_model=EnterpriseApprovalResponse,status_code=201)
def submit(payload:EnterpriseSubmissionInput,db:Session=Depends(get_db),
           user=Depends(require_enterprise_account),store=Depends(get_evidence_store)):
    return service.submit(db,user,payload.evidence_tokens,store)


def public_stage(meta):
    return {k:meta[k] for k in ("token","name","mime","size")}


@router.post("/api/enterprise/evidence/staging",status_code=201)
async def upload(file:UploadFile=File(...),db:Session=Depends(get_db),
                 user=Depends(require_enterprise_account),store=Depends(get_evidence_store)):
    try:
        data=await file.read(MAX_FILE_BYTES+1)
        meta=await run_in_threadpool(service.stage_upload,db,user,store,file.filename,file.content_type,data)
        return public_stage(meta)
    finally:await file.close()


@router.get("/api/enterprise/evidence/staging")
def staged(db:Session=Depends(get_db),user=Depends(require_enterprise_account),store=Depends(get_evidence_store)):
    # DN lock serializes deletion/expiry cleanup against submission.
    with service.atomic(db):
        service.lock_enterprise(db,user.nd_tendangnhap)
        return [public_stage(m) for m in service.staging(db,user,store)]


@router.delete("/api/enterprise/evidence/staging/{token}",status_code=204)
def remove_staged(token:str,db:Session=Depends(get_db),user=Depends(require_enterprise_account),store=Depends(get_evidence_store)):
    service.delete_stage(db,user,store,token)
    return Response(status_code=204)


@router.get("/api/enterprise-approval/evidence/{evidence_id}")
def download(evidence_id:str,db:Session=Depends(get_db),user=Depends(get_current_user),store=Depends(get_evidence_store)):
    row,path=service.evidence_download(db,user,evidence_id,store)
    return FileResponse(path,media_type=row.tmc_mime or "application/octet-stream",filename=row.tmc_ten,
                        headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff",
                                 "Content-Security-Policy":"sandbox; default-src 'none'"})


@router.get("/api/admin/enterprise-approvals",response_model=list[EnterpriseApprovalResponse])
def admin_list(status:ApprovalState | None=None,limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0),
               db:Session=Depends(get_db),user=Depends(require_admin)):
    return service.list_submissions(db,user,status,limit,offset)


@router.get("/api/admin/enterprise-approvals/{request_id}",response_model=EnterpriseApprovalResponse)
def admin_detail(request_id:str,db:Session=Depends(get_db),user=Depends(require_admin)):
    return service.get_submission(db,request_id,user)


@router.post("/api/admin/enterprise-approvals/{request_id}/decision",response_model=EnterpriseApprovalResponse)
def decision(request_id:str,payload:EnterpriseDecisionInput,db:Session=Depends(get_db),user=Depends(require_admin)):
    return service.decide(db,user,request_id,payload.decision,payload.reason)
