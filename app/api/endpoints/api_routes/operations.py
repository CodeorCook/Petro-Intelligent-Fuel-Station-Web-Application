from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.auth import require_approved_enterprise
from app.database.session import get_db
from app.models import NguoiDung
from app.schemas.operations import TankCreate,TankUpdate,PumpCreate,PumpUpdate
from app.services import operational_service as ops

router=APIRouter(prefix='/api/doanh-nghiep/stations',tags=['Operational setup'])

@router.get('/{tx_ma}/readiness')
def readiness(tx_ma:str,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.inventory(db,tx_ma,user)['readiness'])

@router.get('/{tx_ma}/tanks')
def tanks(tx_ma:str,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.inventory(db,tx_ma,user)['tanks'])

@router.post('/{tx_ma}/tanks',status_code=201)
def create_tank(tx_ma:str,payload:TankCreate,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.create_tank(db,tx_ma,user,payload.model_dump()))

@router.patch('/{tx_ma}/tanks/{tank_id}')
def edit_tank(tx_ma:str,tank_id:str,payload:TankUpdate,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.edit_tank(db,tx_ma,tank_id,user,payload.model_dump(exclude_unset=True)))

@router.get('/{tx_ma}/pumps')
def pumps(tx_ma:str,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.inventory(db,tx_ma,user)['pumps'])

@router.post('/{tx_ma}/pumps',status_code=201)
def create_pump(tx_ma:str,payload:PumpCreate,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.create_pump(db,tx_ma,user,payload.model_dump()))

@router.patch('/{tx_ma}/pumps/{pump_id}')
def edit_pump(tx_ma:str,pump_id:str,payload:PumpUpdate,db:Session=Depends(get_db),user:NguoiDung=Depends(require_approved_enterprise)):
    return ops.execute(db,lambda:ops.edit_pump(db,tx_ma,pump_id,user,payload.model_dump(exclude_unset=True)))
