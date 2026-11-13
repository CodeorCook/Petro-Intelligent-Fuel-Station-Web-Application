from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session
from app.core.auth import require_khach_hang
from app.database.session import get_db
from app.services import transaction_reviews as reviews
from app.services.operational_service import execute, guard

router = APIRouter(prefix='/api/transactions', tags=['Transaction reviews'])


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stars: int = Field(ge=1, le=5, strict=True)
    comment: str = Field(default='', max_length=500)


@router.get('/{invoice_id}/review')
def status(invoice_id: str, db: Session=Depends(get_db), user=Depends(require_khach_hang)):
    guard(db)
    return reviews.state(db, invoice_id, user)


@router.post('/{invoice_id}/review')
def submit(invoice_id: str, payload: ReviewInput, db: Session=Depends(get_db), user=Depends(require_khach_hang)):
    return execute(db, lambda: reviews.submit(db, invoice_id, user, payload.stars, payload.comment.strip()))
