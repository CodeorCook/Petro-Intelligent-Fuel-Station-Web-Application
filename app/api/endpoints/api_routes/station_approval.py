from fastapi import APIRouter,Depends,File,HTTPException,Query,Response,UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.core.auth import require_admin,require_approved_enterprise,get_current_user
from app.database.session import get_db
from app.models import TepMinhChung
from app.schemas.enterprise_approval import ApprovalState,EnterpriseDecisionInput
from app.schemas.station_approval import StationDraftInput,StationDraftPatch,StationSubmissionInput,OwnedStationResponse,StationApprovalResponse,DraftAmenitySetInput
from app.schemas import TxDvResponse
from app.services import station_approval as service
from app.services import station_amenities
from app.services.enterprise_evidence import get_evidence_store,MAX_FILE_BYTES
from app.api.endpoints.api_routes.enterprise_approval import check_origin,public_stage

router=APIRouter(tags=["Station individual approval"],dependencies=[Depends(check_origin)])


@router.get("/api/enterprise/stations",response_model=list[OwnedStationResponse])
def owned_list(db:Session=Depends(get_db),user=Depends(require_approved_enterprise)):
    return service.list_owned(db,user)


@router.post("/api/enterprise/stations",response_model=OwnedStationResponse,status_code=201)
def create(payload:StationDraftInput,db:Session=Depends(get_db),user=Depends(require_approved_enterprise)):
    return service.create_draft(db,user,payload.model_dump())


@router.get("/api/enterprise/stations/{station_id}",response_model=OwnedStationResponse)
def details(station_id:str,db:Session=Depends(get_db),user=Depends(require_approved_enterprise)):
    return service.owned(db,user,station_id)


@router.patch("/api/enterprise/stations/{station_id}",response_model=OwnedStationResponse)
def draft(station_id:str,payload:StationDraftPatch,db:Session=Depends(get_db),user=Depends(require_approved_enterprise)):
    return service.save_draft(db,user,station_id,payload.model_dump(exclude_unset=True))


@router.put('/api/enterprise/stations/{tx_ma}/services', response_model=list[TxDvResponse])
def draft_services(tx_ma:str, payload:DraftAmenitySetInput, db:Session=Depends(get_db),
                   user=Depends(require_approved_enterprise)):
    return station_amenities.replace_draft_set(db, user, tx_ma,
        payload.service_ids, payload.expected_amenity_ids)


@router.post("/api/enterprise/stations/{station_id}/activate",response_model=StationApprovalResponse,status_code=201)
def activate(station_id:str,payload:StationSubmissionInput,db:Session=Depends(get_db),user=Depends(require_approved_enterprise),store=Depends(get_evidence_store)):
    return service.submit(db,user,station_id,payload,store,self_service=True)


@router.get("/api/enterprise/stations/{station_id}/approvals",response_model=list[StationApprovalResponse])
def history(station_id:str,db:Session=Depends(get_db),user=Depends(require_approved_enterprise)):
    return service.history(db,user,station_id)


@router.post("/api/enterprise/stations/{station_id}/approvals",response_model=StationApprovalResponse,status_code=201)
def submit(station_id:str,payload:StationSubmissionInput,db:Session=Depends(get_db),user=Depends(require_approved_enterprise),store=Depends(get_evidence_store)):
    return service.submit(db,user,station_id,payload,store)


@router.get("/api/enterprise/stations/{station_id}/evidence/staging")
def stages(station_id:str,db:Session=Depends(get_db),user=Depends(require_approved_enterprise),store=Depends(get_evidence_store)):
    return [public_stage(m) for m in service.stages(db,user,station_id,store)]


@router.post("/api/enterprise/stations/{station_id}/evidence/staging",status_code=201)
async def upload(station_id:str,file:UploadFile=File(...),db:Session=Depends(get_db),user=Depends(require_approved_enterprise),store=Depends(get_evidence_store)):
    try:
        data=await file.read(MAX_FILE_BYTES+1)
        meta=await run_in_threadpool(service.upload,db,user,station_id,store,file.filename,file.content_type,data)
        return public_stage(meta)
    finally:await file.close()


@router.delete("/api/enterprise/stations/{station_id}/evidence/staging/{token}",status_code=204)
def remove(station_id:str,token:str,db:Session=Depends(get_db),user=Depends(require_approved_enterprise),store=Depends(get_evidence_store)):
    service.remove_stage(db,user,station_id,token,store);return Response(status_code=204)


@router.get("/api/admin/station-approvals",response_model=list[StationApprovalResponse])
def review_list(status:ApprovalState|None=None,limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0),
                db:Session=Depends(get_db),user=Depends(require_admin)):
    return service.admin_list(db,status,limit,offset)


@router.get("/api/admin/station-approvals/{request_id}",response_model=StationApprovalResponse)
def review_detail(request_id:str,db:Session=Depends(get_db),user=Depends(require_admin)):
    return service.get_request(db,user,request_id)


@router.post("/api/admin/station-approvals/{request_id}/decision",response_model=StationApprovalResponse)
def decision(request_id:str,payload:EnterpriseDecisionInput,db:Session=Depends(get_db),user=Depends(require_admin)):
    return service.decide(db,user,request_id,payload)


@router.get("/api/station-approval/evidence/{evidence_id}")
def evidence(evidence_id:str,db:Session=Depends(get_db),user=Depends(get_current_user),store=Depends(get_evidence_store)):
    row=db.get(TepMinhChung,evidence_id)
    if row is None or row.ycdt_ma is None:raise HTTPException(404,"Không tìm thấy minh chứng trạm")
    service.get_request(db,user,row.ycdt_ma)
    path=store.object_path(row.tmc_duongdan)
    if not path.is_file():raise HTTPException(404,"Tệp minh chứng không còn khả dụng")
    store.verify({"path":row.tmc_duongdan,"size":row.tmc_kich_thuoc,"sha256":row.tmc_sha256})
    return FileResponse(path,media_type=row.tmc_mime,filename=row.tmc_ten,
        headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff","Content-Security-Policy":"sandbox; default-src 'none'"})
