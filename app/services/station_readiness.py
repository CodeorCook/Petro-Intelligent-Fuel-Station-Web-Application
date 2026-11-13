"""Safe customer summary. No equipment IDs, quantities or enterprise internals."""
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from sqlalchemy import select, func
from app.core.operational_mode import POSTGRESQL_OPERATIONS

MESSAGES = {
    'UNAVAILABLE': 'Không thể xác minh điều kiện tiếp nhận lúc này.',
    'NO_PRICE': 'Chưa có giá nhiên liệu này tại trạm.',
    'NO_TANK': 'Trạm đang cấu hình bồn cho nhiên liệu này.',
    'NO_READY_PUMP': 'Chưa có trụ sẵn sàng cho nhiên liệu này.',
    'INSUFFICIENT_STOCK': 'Chưa đủ nhiên liệu khả dụng cho yêu cầu này.',
    'INVALID_QUANTITY': 'Vui lòng nhập định mức tiền/lít hợp lệ.',
    'READY': 'Có thể gửi yêu cầu; trạm sẽ kiểm tra lại khi tiếp nhận.',
}

def customer_readiness(db, station_id, fuel_id, mode='DO_DAY_BINH', liters=None, budget=None):
    def result(code):
        return dict(orderable=code=='READY', reason_code=code, message=MESSAGES[code],
                    fuel_id=fuel_id, mode=mode,
                    maximum_confirmation_required=mode=='DO_DAY_BINH')
    if not POSTGRESQL_OPERATIONS:
        return result('UNAVAILABLE')
    from app.models import BonChua, TruBom, TruBomNhienLieu, Gia
    price=db.scalar(select(Gia.dongia).where(Gia.tx_ma==station_id, Gia.nl_ma==fuel_id)
                    .order_by(Gia.ngaygio.desc()).limit(1))
    if price is None or not Decimal(price).is_finite() or price<=0:
        return result('NO_PRICE')
    required=None
    if mode not in ('SO_LIT','SO_TIEN','DO_DAY_BINH'):
        return result('INVALID_QUANTITY')
    if mode!='DO_DAY_BINH':
        try:
            amount=Decimal(str(liters if mode=='SO_LIT' else budget))
            if not amount.is_finite() or amount<=0:
                return result('INVALID_QUANTITY')
            required=amount if mode=='SO_LIT' else (amount/price).quantize(Decimal('.01'),rounding=ROUND_DOWN)
            if required<=0 or required>=1000000 or (mode=='SO_LIT' and required!=required.quantize(Decimal('.01'))):
                return result('INVALID_QUANTITY')
        except (InvalidOperation, ValueError, TypeError):
            return result('INVALID_QUANTITY')
    tank=db.scalar(select(BonChua.bc_ma).where(BonChua.tx_ma==station_id,
                   BonChua.nl_ma==fuel_id,BonChua.bc_hoatdong.is_(True)).limit(1))
    if tank is None:
        return result('NO_TANK')
    pump=db.scalar(select(TruBom.tb_ma).join(TruBomNhienLieu,TruBom.tb_ma==TruBomNhienLieu.tb_ma)
                   .where(TruBom.tx_ma==station_id,TruBomNhienLieu.nl_ma==fuel_id,
                          TruBom.tb_trangthai=='READY',TruBom.yc_dang_bom.is_(None)).limit(1))
    if pump is None:
        return result('NO_READY_PUMP')
    available=db.scalar(select(func.coalesce(func.sum(BonChua.bc_ton-BonChua.bc_giucho),0))
                        .where(BonChua.tx_ma==station_id,BonChua.nl_ma==fuel_id,BonChua.bc_hoatdong.is_(True)))
    if available<=0 or (required is not None and available<required):
        return result('INSUFFICIENT_STOCK')
    return result('READY')
