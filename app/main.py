from app.core.development_startup import configure_development

configure_development()

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.endpoints.view_routes.views import router as view_router
from app.api.endpoints.api_routes.stations import router as stations_router
from app.api.endpoints.api_routes.catalog import router as catalog_router
from app.api.endpoints.api_routes.workflows import router as workflow_router
from app.api.endpoints.api_routes.traffic import router as traffic_router
from app.api.endpoints.api_routes.routing import router as routing_router
from app.api.endpoints.api_routes.fuel_pricing import router as fuel_pricing_router
from app.api.endpoints.api_routes.payment_workflow import router as payment_workflow_router
from app.api.endpoints.api_routes.auth import router as auth_router
from app.api.endpoints.api_routes.doanh_nghiep import router as doanh_nghiep_router
from app.api.endpoints.api_routes.enterprise_approval import router as enterprise_approval_router
from app.api.endpoints.api_routes.station_approval import router as station_approval_router
from app.core.evidence_limits import EvidenceBodyLimit

import app.models

# The PostgreSQL schema is maintained by explicit migrations. Importing or
# starting the app must never create tables or act as a migration mechanism.

app = FastAPI(
    title="Petro App Backend & Frontend",
    description="Hệ thống ứng dụng tìm trạm xăng và thanh toán Petro",
    version="1.0.0"
)
app.add_middleware(EvidenceBodyLimit)

@app.middleware("http")
async def public_station_cache_policy(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/map/", "/api/stations", "/api/routing/", "/api/workflow/station-info/")):
        # Publication can change independently of the client's previous query.
        response.headers["Cache-Control"] = "no-store"
    return response

@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Expose invalid API input as 400 instead of FastAPI's default 422."""
    errors = exc.errors()
    if request.url.path.startswith(("/api/auth/", "/api/enterprise/", "/api/admin/enterprise-approvals", "/api/admin/station-approvals")):
        # Validation errors must never echo submitted credentials.
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in errors]
    return JSONResponse(status_code=400, content={"detail": errors})

# Mount thư mục tĩnh để phục vụ các file CSS, JS, Hình ảnh, Fonts
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register Routers
app.include_router(view_router)
app.include_router(auth_router)
app.include_router(doanh_nghiep_router)
app.include_router(enterprise_approval_router)
app.include_router(station_approval_router)
app.include_router(stations_router)
app.include_router(catalog_router)
app.include_router(workflow_router)
app.include_router(traffic_router)
app.include_router(routing_router)
app.include_router(fuel_pricing_router)
app.include_router(payment_workflow_router)

from app.core.operational_mode import POSTGRESQL_OPERATIONS
if POSTGRESQL_OPERATIONS:
    from app.database.session import SessionLocal
    from app.services.operational_service import guard
    from app.core.workflow_status import validate_catalog
    with SessionLocal() as operational_startup_db:
        guard(operational_startup_db)
        validate_catalog(operational_startup_db)
        operational_startup_db.rollback()
    from app.api.endpoints.api_routes.operations import router as operations_router
    app.include_router(operations_router)
    from app.api.endpoints.api_routes.transaction_reviews import router as transaction_reviews_router
    app.include_router(transaction_reviews_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
