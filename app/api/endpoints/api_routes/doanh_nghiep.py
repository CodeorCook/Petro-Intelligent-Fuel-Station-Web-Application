from datetime import date
from decimal import Decimal
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, select, or_
from sqlalchemy.orm import Session, selectinload

from app.core.auth import get_current_user, require_doanh_nghiep
from app.database.session import get_db
from app.models.request import ChiTietYeuCau, YeuCauDoXang
from app.models.station import Gia, NhienLieu, ThoiDiem, TramXang
from app.models.transaction import ChiTietGiaoDich, GiaoDich
from app.models.user import NguoiDung
from app.core.fuel_order import ordered_fuels
from app.services.station_inventory_service import (
    get_station_inventory,
    get_tank_by_fuel,
    get_tanks_by_fuel,
    refill_tank,
    update_pump_status,
)

router = APIRouter(prefix="/api/doanh-nghiep", tags=["Enterprise Station Management"], dependencies=[Depends(require_doanh_nghiep)])

def _transaction_station_scope(station_id):
    # Historical invoices may have nullable tx_ma. Resolve through the existing
    # request read-only; exclude contradictory explicit station references.
    return (GiaoDich.yeu_cau_do_xang.has(YeuCauDoXang.tx_ma==station_id)
        & or_(GiaoDich.tx_ma==station_id,GiaoDich.tx_ma.is_(None)))

from app.core.operational_mode import POSTGRESQL_OPERATIONS, preserved_request
from app.core.workflow_status import REQUEST_COMPLETED,REQUEST_REJECTED,REQUEST_CANCELLED,REQUEST_EXPIRED,PAYMENT_SUCCEEDED,view as workflow_view
if POSTGRESQL_OPERATIONS:
    from app.services import operational_service as ops
    from app.schemas.operations import Refill as RefillRequest


class UpdatePriceItem(BaseModel):
    nl_ma: str = Field(min_length=1, max_length=8)
    dongia: float = Field(gt=0)


class UpdatePricesRequest(BaseModel):
    prices: list[UpdatePriceItem]


class RefillRequest(BaseModel):
    tx_ma: str = Field(min_length=1, max_length=8)
    tank_id: str
    liters: float = Field(gt=0)
    supplier: Optional[str] = "Xe bồn Petrolimex"


class UpdatePumpStatusRequest(BaseModel):
    status: str = Field(pattern="^(READY|PUMPING|MAINTENANCE|OFFLINE)$")
    version: int | None = Field(default=None,ge=0)

if POSTGRESQL_OPERATIONS:
    from app.schemas.operations import Refill as RefillRequest


def _get_enterprise_single_station(user: NguoiDung, db: Session, requested_tx: Optional[str] = None) -> Optional[TramXang]:
    statement = (
        select(TramXang)
        .options(selectinload(TramXang.bang_gia).selectinload(Gia.nhien_lieu))
        .where(TramXang.nd_tendangnhap == user.nd_tendangnhap)
        .order_by(TramXang.tx_ma)
    )
    if requested_tx:
        statement = statement.where(TramXang.tx_ma == requested_tx.strip())
    return db.scalars(statement).first()


def _require_owned_station(user: NguoiDung, db: Session, tx_ma: str) -> TramXang:
    station = db.get(TramXang, tx_ma.strip())
    if station is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng")
    if station.nd_tendangnhap.strip() != user.nd_tendangnhap.strip():
        raise HTTPException(status_code=403, detail="Bạn không có quyền quản lý trạm xăng này")
    return station


@router.get("/stations")
def get_enterprise_stations(
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Enterprise users only see their own station.
    statement = select(TramXang).options(
        selectinload(TramXang.bang_gia).selectinload(Gia.nhien_lieu)
    ).where(TramXang.nd_tendangnhap == user.nd_tendangnhap).order_by(TramXang.tx_ma)
    stations = db.scalars(statement).all()

    # Get all fuels list
    all_fuels = ordered_fuels(db.scalars(select(NhienLieu)).all(), lambda f:f.nl_ma)

    station_list = []
    for s in stations:
        # Get prices for this station
        price_map = {}
        for g in sorted(s.bang_gia, key=lambda item: item.ngaygio):
            price_map[g.nl_ma.strip()] = float(g.dongia)

        fuel_prices = []
        for f in all_fuels:
            f_ma = f.nl_ma.strip()
            price_val = price_map.get(f_ma)
            fuel_prices.append({
                "nl_ma": f_ma,
                "nl_ten": f.nl_ten,
                "dongia": price_val,
                "dongia_formatted": f"{int(price_val):,} đ/L" if price_val is not None else "Chưa có giá"
            })

        station_list.append({
            "tx_ma": s.tx_ma.strip(),
            "tx_ten": s.tx_ten,
            "tx_diachi": s.tx_diachi,
            "tx_kinhdo": float(s.tx_kinhdo),
            "tx_vido": float(s.tx_vido),
            "tx_trangthai":s.tx_trangthai,"tx_congkhai":s.tx_congkhai,
            "tx_phienban_hientai":s.tx_phienban_hientai,
            "prices": fuel_prices,
        })

    single_station = station_list[0] if station_list else None

    return {
        "status": "success",
        "enterprise": user.nd_ten,
        "total_stations": len(station_list),
        "station": single_station,
        "stations": station_list,
    }


@router.put("/stations/{tx_ma}/prices")
def update_station_prices(
    tx_ma: str,
    payload: UpdatePricesRequest,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    station = _require_owned_station(user, db, tx_ma)

    today = date.today()
    if db.get(ThoiDiem, today) is None:
        db.add(ThoiDiem(ngaygio=today))
        db.flush()

    updated = []
    for item in payload.prices:
        nl_ma = item.nl_ma.strip()
        fuel = db.get(NhienLieu, nl_ma)
        if not fuel:
            continue

        existing_price = db.get(Gia, (today, station.tx_ma, nl_ma))
        price_decimal = Decimal(str(round(item.dongia, 2)))
        if existing_price:
            existing_price.dongia = price_decimal
        else:
            db.add(Gia(
                ngaygio=today,
                tx_ma=station.tx_ma,
                nl_ma=nl_ma,
                dongia=price_decimal
            ))
        updated.append({"nl_ma": nl_ma, "nl_ten": fuel.nl_ten, "dongia": float(price_decimal)})

    db.commit()
    return {
        "status": "success",
        "message": f"Cập nhật giá thành công cho trạm {station.tx_ten}",
        "updated_prices": updated
    }


@router.get("/orders")
def get_enterprise_orders(
    tx_ma: Optional[str] = None,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db),
    history_limit: Optional[int] = Query(default=None, ge=0, le=200),
):
    statement = (
        select(YeuCauDoXang)
        .options(
            selectinload(YeuCauDoXang.tram_xang),
            selectinload(YeuCauDoXang.trang_thai_xac_nhan),
            selectinload(YeuCauDoXang.chitiet_yeucau).selectinload(ChiTietYeuCau.nhien_lieu),
            selectinload(YeuCauDoXang.giao_dich),
        )
        .order_by(asc(YeuCauDoXang.thoi_gian_tao), asc(YeuCauDoXang.yc_ma))
    )

    single_st = _get_enterprise_single_station(user, db, tx_ma)
    if not single_st:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng thuộc doanh nghiệp")
    statement = statement.where(YeuCauDoXang.tx_ma == single_st.tx_ma)

    # Default preserves the historical API. Polling asks for bounded closed history;
    # ALL active/unpaid requests remain eligible and keep the same FIFO ordering.
    if isinstance(history_limit,int):
        closed = or_(YeuCauDoXang.ttxn_ma.in_([REQUEST_REJECTED,REQUEST_CANCELLED,REQUEST_EXPIRED]),
                     YeuCauDoXang.giao_dich.any(GiaoDich.tt_ma==PAYMENT_SUCCEEDED))
        recent_closed = select(YeuCauDoXang.yc_ma).where(YeuCauDoXang.tx_ma==single_st.tx_ma,closed).order_by(
            YeuCauDoXang.thoi_gian_tao.desc(),YeuCauDoXang.yc_ma.desc()).limit(history_limit)
        statement=statement.where(or_(~closed,YeuCauDoXang.yc_ma.in_(recent_closed)))
    requests = db.scalars(statement).all()
    tanks_by_fuel = get_tanks_by_fuel(single_st.tx_ma,db=db) if any(r.chitiet_yeucau for r in requests) else {}

    items = []
    active_items = []
    completed_items = []
    cancelled_items = []
    service_queue_total = 0

    for req in requests:
        ct = req.chitiet_yeucau[0] if req.chitiet_yeucau else None
        fuel_name = ct.nhien_lieu.nl_ten if ct and ct.nhien_lieu else "Nhiên liệu"
        gd = req.giao_dich[0] if req.giao_dich else None

        # Thông tin bồn chứa & chỉ số lít còn lại
        tank = tanks_by_fuel.get(ct.nl_ma.strip()) if ct else None
        tank_remaining = tank.get("current_liters") if tank else None
        tank_name = tank.get("tank_name") if tank else None
        tank_pct = tank.get("percentage") if tank else None

        status_code = req.ttxn_ma.strip()
        is_paid = (gd.tt_ma == PAYMENT_SUCCEEDED) if gd else False
        # Completed dispensing is not a paid sale; keep unpaid/failed invoices visible.
        is_completed = is_paid
        is_cancelled = status_code in (REQUEST_REJECTED,REQUEST_CANCELLED,REQUEST_EXPIRED)

        created_dt = req.thoi_gian_tao
        created_time_str = created_dt.strftime("%H:%M:%S") if created_dt else ""
        created_datetime_str = created_dt.strftime("%H:%M:%S %d/%m/%Y") if created_dt else ""

        order_item = {
            **workflow_view(req,gd),
            "yc_ma": req.yc_ma.strip(),
            "tx_ma": req.tx_ma.strip(),
            "tx_ten": req.tram_xang.tx_ten if req.tram_xang else "",
            "customer_id": req.nd_tendangnhap.strip(),
            "plate": req.pt_bienso.strip() if req.pt_bienso else "--",
            "fuel_name": fuel_name,
            "nl_ma": ct.nl_ma.strip() if ct else None,
            "mode": req.hinh_thuc_do_xang,
            "liters": float(ct.soluong) if ct and ct.soluong else None,
            "amount": float(ct.thanhtien) if ct and ct.thanhtien else (float(gd.gd_sotien) if gd else None),
            "status_code": status_code,
            "status_text": req.trang_thai_xac_nhan.ttxn_ten if req.trang_thai_xac_nhan else "",
            "gd_ma": gd.gd_ma.strip() if gd else None,
            "is_paid": is_paid,
            "operational_read_only": preserved_request(req.yc_ma) if POSTGRESQL_OPERATIONS else False,
            "is_completed": is_completed,
            "is_cancelled": status_code==REQUEST_CANCELLED,
            "is_rejected": status_code==REQUEST_REJECTED,
            "is_expired": status_code==REQUEST_EXPIRED,
            "tank_name": tank_name,
            "tank_remaining": tank_remaining,
            "tank_percentage": tank_pct,
            "created_time": created_time_str,
            "created_datetime": created_datetime_str,
            "created_at_iso": created_dt.isoformat() if created_dt else None,
        }

        items.append(order_item)
        if is_completed:
            completed_items.append(order_item)
        elif is_cancelled:
            cancelled_items.append(order_item)
        else:
            # Keep financial reconciliation visible without treating already-dispensed
            # invoices as vehicles still waiting for physical service.
            in_service_queue = order_item['phase'] in {'WAITING', 'ACCEPTED', 'PUMPING'} and not order_item['operational_read_only']
            if in_service_queue:
                service_queue_total += 1
            order_item['queue_order'] = service_queue_total if in_service_queue else None
            order_item['is_next_in_queue'] = in_service_queue and service_queue_total == 1
            active_items.append(order_item)

    # Đảo ngược completed và cancelled để đơn hoàn thành mới nhất hiện trước ở Tab Hóa đơn
    completed_items.reverse()
    cancelled_items.reverse()

    return {
        "status": "success",
        "total": len(items),
        "orders": items,
        "active_orders": active_items,
        "completed_orders": completed_items,
        "cancelled_orders": [o for o in cancelled_items if o['is_cancelled']],
        "rejected_orders": [o for o in cancelled_items if o['is_rejected']],
        "expired_orders": [o for o in cancelled_items if o['is_expired']],
        "active_total": len(active_items),
        "service_queue_total": service_queue_total,
        "completed_total": len(completed_items),
        "cancelled_total": sum(o['is_cancelled'] for o in cancelled_items),
        "rejected_total": sum(o['is_rejected'] for o in cancelled_items),
    }


# ==========================================================
# 4. Quản lý Bồn chứa & Trụ bơm (Tanks & Pumps Inventory)
# ==========================================================
@router.get("/inventory")
def get_inventory(
    tx_ma: Optional[str] = None,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    single_st = _get_enterprise_single_station(user, db, tx_ma)
    if not single_st:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng thuộc doanh nghiệp")
    station_code = single_st.tx_ma.strip()
    station_name = single_st.tx_ten

    if POSTGRESQL_OPERATIONS:
        return ops.execute(db,lambda:dict(ops.inventory(db,station_code,user),station_name=station_name))

    try:
        inv = get_station_inventory(station_code)
    except ValueError as error:
        raise HTTPException(503, "Dữ liệu kho tạm thời không khả dụng") from error
    return {
        "status": "success",
        "station_name": station_name,
        **inv
    }


@router.post("/inventory/refill")
def refill_station_tank(
    payload: RefillRequest,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if POSTGRESQL_OPERATIONS:
        return ops.execute(db,lambda:ops.refill(db,user,payload.model_dump()))
    _require_owned_station(user, db, payload.tx_ma)
    try:
        res = refill_tank(payload.tx_ma, payload.tank_id, payload.liters, payload.supplier or "Xe bồn Petrolimex")
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/pumps/{tx_ma}/{pump_id}/status")
def change_pump_status(
    tx_ma: str,
    pump_id: str,
    payload: UpdatePumpStatusRequest,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if POSTGRESQL_OPERATIONS:
        if payload.version is None or payload.status=='PUMPING':
            raise HTTPException(409,'Cần phiên bản trụ; trạng thái PUMPING chỉ qua tiếp nhận yêu cầu')
        return ops.execute(db,lambda:dict(status='success',pump=ops.edit_pump(db,tx_ma,pump_id,user,
            {'tb_phienban':payload.version,'tb_trangthai':payload.status})))
    _require_owned_station(user, db, tx_ma)
    try:
        res = update_pump_status(tx_ma, pump_id, payload.status)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================================
# 5. Danh sách Hóa đơn Bán hàng (Invoices)
# ==========================================================
@router.get("/invoices")
def get_enterprise_invoices(
    tx_ma: Optional[str] = None,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    statement = (
        select(GiaoDich)
        .options(
            selectinload(GiaoDich.tram_xang),
            selectinload(GiaoDich.trang_thai),
            selectinload(GiaoDich.yeu_cau_do_xang),
            selectinload(GiaoDich.chi_tiet_giao_dich).selectinload(ChiTietGiaoDich.nhien_lieu),
        )
        .where(GiaoDich.tt_ma == PAYMENT_SUCCEEDED)  # Chỉ lấy các giao dịch đã thanh toán thành công
        .order_by(desc(GiaoDich.gd_ma))
    )

    single_st = _get_enterprise_single_station(user, db, tx_ma)
    if not single_st:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng thuộc doanh nghiệp")
    statement = statement.where(_transaction_station_scope(single_st.tx_ma))

    transactions = db.scalars(statement).all()
    invoices = []

    for gd in transactions:
        ct = gd.chi_tiet_giao_dich[0] if gd.chi_tiet_giao_dich else None
        fuel_name = ct.nhien_lieu.nl_ten if ct and ct.nhien_lieu else "Nhiên liệu"
        liters = float(ct.soluong) if ct and ct.soluong else 0.0
        unit_price = float(ct.dongialucban) if ct and ct.dongialucban is not None else None
        plate = gd.yeu_cau_do_xang.pt_bienso if gd.yeu_cau_do_xang and gd.yeu_cau_do_xang.pt_bienso else "--"

        invoices.append({
            "gd_ma": gd.gd_ma.strip(),
            "yc_ma": gd.yc_ma.strip() if gd.yc_ma else "",
            "tx_ma": single_st.tx_ma,
            "tx_ten": single_st.tx_ten,
            "customer_id": gd.nd_tendangnhap.strip(),
            "plate": plate,
            "fuel_name": fuel_name,
            "liters": liters,
            "unit_price": unit_price,
            "total_amount": float(gd.gd_sotien),
            "payment_method": gd.pttt_ten or "VIETQR",
            "is_paid": gd.tt_ma == PAYMENT_SUCCEEDED,
            "status_text": gd.trang_thai.tt_ten if gd.trang_thai else "Chờ thanh toán",
            "date": gd.ngaygio.strftime("%d/%m/%Y") if gd.ngaygio else "",
            "reference": gd.gd_mathamchieu,
        })

    return {
        "status": "success",
        "total": len(invoices),
        "invoices": invoices,
    }


# ==========================================================
# 6. Báo cáo Doanh thu & Đối soát Tiền mặt vs Điện tử (Reconciliation)
# ==========================================================
@router.get("/reports/reconciliation")
def get_reconciliation_report(
    tx_ma: Optional[str] = None,
    user: NguoiDung = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    statement = (
        select(GiaoDich)
        .options(
            selectinload(GiaoDich.chi_tiet_giao_dich).selectinload(ChiTietGiaoDich.nhien_lieu)
        )
        .where(GiaoDich.tt_ma == PAYMENT_SUCCEEDED)  # Chỉ tính các giao dịch đã thanh toán
    )

    single_st = _get_enterprise_single_station(user, db, tx_ma)
    if not single_st:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng thuộc doanh nghiệp")
    statement = statement.where(_transaction_station_scope(single_st.tx_ma))

    txs = db.scalars(statement).all()

    total_revenue = 0.0
    total_liters = 0.0

    cash_revenue = 0.0
    cash_liters = 0.0
    cash_orders = 0

    digital_revenue = 0.0
    digital_liters = 0.0
    digital_orders = 0

    fuel_breakdown: Dict[str, Dict[str, float]] = {}

    for gd in txs:
        amount = float(gd.gd_sotien)
        total_revenue += amount

        liters = 0.0
        fuel_name = "Khác"
        if gd.chi_tiet_giao_dich:
            ct = gd.chi_tiet_giao_dich[0]
            liters = float(ct.soluong) if ct.soluong else 0.0
            fuel_name = ct.nhien_lieu.nl_ten if ct.nhien_lieu else "Khác"

        total_liters += liters

        # Phân loại phương thức
        method = (gd.pttt_ten or "VIETQR").upper()
        if "TIEN_MAT" in method or "CASH" in method:
            cash_revenue += amount
            cash_liters += liters
            cash_orders += 1
        else:
            digital_revenue += amount
            digital_liters += liters
            digital_orders += 1

        # Phân loại theo nhiên liệu
        if fuel_name not in fuel_breakdown:
            fuel_breakdown[fuel_name] = {"liters": 0.0, "amount": 0.0, "count": 0}
        fuel_breakdown[fuel_name]["liters"] += liters
        fuel_breakdown[fuel_name]["amount"] += amount
        fuel_breakdown[fuel_name]["count"] += 1

    cash_pct = round((cash_revenue / total_revenue * 100), 1) if total_revenue > 0 else 0.0
    digital_pct = round((digital_revenue / total_revenue * 100), 1) if total_revenue > 0 else 0.0

    return {
        "status": "success",
        "total_revenue": round(total_revenue, 2),
        "total_liters": round(total_liters, 2),
        "total_transactions": len(txs),
        "cash": {
            "revenue": round(cash_revenue, 2),
            "liters": round(cash_liters, 2),
            "order_count": cash_orders,
            "percentage": cash_pct,
        },
        "digital": {
            "revenue": round(digital_revenue, 2),
            "liters": round(digital_liters, 2),
            "order_count": digital_orders,
            "percentage": digital_pct,
        },
        "fuel_breakdown": [
            {
                "fuel_name": k,
                "liters": round(v["liters"], 2),
                "amount": round(v["amount"], 2),
                "count": v["count"],
            }
            for k, v in fuel_breakdown.items()
        ],
    }
