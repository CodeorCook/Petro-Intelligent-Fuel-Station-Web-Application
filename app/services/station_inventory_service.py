import json
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

DATA_FILE = os.path.join(os.path.dirname(__file__), "inventory_data.json")
logger = logging.getLogger(__name__)


def _get_default_inventory() -> Dict[str, Any]:
    """Legacy demo fixture factory; never called by production read/write paths."""
    default_stations = [f"TX00000{i}" if i < 10 else f"TX0000{i}" for i in range(1, 11)]
    data: Dict[str, Any] = {}

    for tx in default_stations:
        data[tx] = {
            "tanks": [
                {
                    "tank_id": f"{tx}_T01",
                    "tank_name": "Bồn B01 - Xăng E10 RON 95-III",
                    "nl_ma": "NL000001",
                    "fuel_name": "Xăng E10 RON 95-III",
                    "capacity": 25000.0,
                    "current_liters": 18450.0,
                    "min_alert_liters": 5000.0,
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "tank_id": f"{tx}_T02",
                    "tank_name": "Bồn B02 - Xăng E5 RON 92",
                    "nl_ma": "NL000002",
                    "fuel_name": "Xăng E5 RON92",
                    "capacity": 20000.0,
                    "current_liters": 12300.0,
                    "min_alert_liters": 4000.0,
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "tank_id": f"{tx}_T03",
                    "tank_name": "Bồn B03 - Dầu Diesel DO 0.05S",
                    "nl_ma": "NL000003",
                    "fuel_name": "Dầu DO 0.05S",
                    "capacity": 30000.0,
                    "current_liters": 21800.0,
                    "min_alert_liters": 6000.0,
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            ],
            "pumps": [
                {
                    "pump_id": f"{tx}_P01",
                    "pump_code": "TRU_01",
                    "pump_name": "Trụ bơm 01 (Cửa Bắc)",
                    "status": "READY",  # READY, PUMPING, MAINTENANCE, OFFLINE
                    "fuels": ["Xăng E10 RON 95-III", "Xăng E5 RON92"],
                    "totalizer_liters": 54230.5,
                    "current_session": None,
                },
                {
                    "pump_id": f"{tx}_P02",
                    "pump_code": "TRU_02",
                    "pump_name": "Trụ bơm 02 (Cửa Nam)",
                    "status": "READY",
                    "fuels": ["Xăng E10 RON 95-III", "Dầu DO 0.05S"],
                    "totalizer_liters": 42110.0,
                    "current_session": None,
                },
                {
                    "pump_id": f"{tx}_P03",
                    "pump_code": "TRU_03",
                    "pump_name": "Trụ bơm 03 (Trung tâm)",
                    "status": "READY",
                    "fuels": ["Xăng E5 RON92", "Dầu DO 0.05S"],
                    "totalizer_liters": 38900.0,
                    "current_session": None,
                },
                {
                    "pump_id": f"{tx}_P04",
                    "pump_code": "TRU_04",
                    "pump_name": "Trụ bơm 04 (Cao tốc)",
                    "status": "READY",
                    "fuels": ["Xăng E10 RON 95-III", "Dầu DO 0.05S"],
                    "totalizer_liters": 61450.0,
                    "current_session": None,
                },
            ],
            "refill_history": [
                {
                    "refill_id": f"RF_{tx}_01",
                    "tank_name": "Bồn B01 - Xăng E10 RON 95-III",
                    "liters": 8000.0,
                    "supplier": "Petrolimex Cần Thơ - Xe bồn 65C-11223",
                    "created_at": datetime.now().strftime("%Y-%m-%d 08:30:00"),
                }
            ],
        }
    return data


def _load_data() -> Dict[str, Any]:
    from app.core.operational_mode import POSTGRESQL_OPERATIONS
    if POSTGRESQL_OPERATIONS:
        raise ValueError('JSON inventory is disabled in PostgreSQL mode; use request-scoped Session')
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as error:
        logger.error("Unable to read configured station inventory")
        raise ValueError("Không thể đọc dữ liệu kho của trạm") from error


def _save_data(data: Dict[str, Any]) -> None:
    from app.core.operational_mode import POSTGRESQL_OPERATIONS
    if POSTGRESQL_OPERATIONS:
        raise ValueError('JSON inventory writes are forbidden in PostgreSQL mode')
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, ValueError) as error:
        logger.error("Unable to save configured station inventory")
        raise ValueError("Không thể lưu dữ liệu kho của trạm") from error


def get_station_inventory(tx_ma: str) -> Dict[str, Any]:
    """Lấy dữ liệu bồn chứa và trụ bơm của một trạm xăng."""
    tx_ma = tx_ma.strip()
    data = _load_data()

    # Reading an unconfigured station must never manufacture stock or pumps.
    st_data = data.get(tx_ma, {})
    tanks = []
    total_capacity = 0.0
    total_current = 0.0

    for t in st_data.get("tanks", []):
        cap = float(t["capacity"])
        cur = float(t["current_liters"])
        total_capacity += cap
        total_current += cur
        pct = round((cur / cap) * 100, 1) if cap > 0 else 0.0

        alert_status = "SAFE"
        if cur <= float(t.get("min_alert_liters", 5000)):
            alert_status = "CRITICAL"
        elif pct <= 35:
            alert_status = "WARNING"

        tanks.append({
            **t,
            "percentage": pct,
            "alert_status": alert_status,
        })

    overall_pct = round((total_current / total_capacity) * 100, 1) if total_capacity > 0 else 0.0

    return {
        "tx_ma": tx_ma,
        "total_capacity": total_capacity,
        "total_current_liters": round(total_current, 2),
        "overall_percentage": overall_pct,
        "tanks": tanks,
        "pumps": st_data.get("pumps", []),
        "refill_history": st_data.get("refill_history", []),
    }


def get_tanks_by_fuel(tx_ma: str, *, db=None) -> Dict[str, Dict[str, Any]]:
    """Request-local display snapshot. One guard/query, no cross-request cache."""
    from app.core.operational_mode import POSTGRESQL_OPERATIONS
    if POSTGRESQL_OPERATIONS:
        from app.services import operational_service as ops
        from app.models import BonChua
        from sqlalchemy import select
        if db is None:
            raise ValueError('Request-scoped PostgreSQL session is required')
        ops.guard(db)
        rows=list(db.scalars(select(BonChua).where(BonChua.tx_ma==tx_ma,BonChua.bc_hoatdong.is_(True)).order_by(BonChua.bc_ma)))
        groups={}
        for row in rows:
            groups.setdefault(row.nl_ma.strip(),[]).append(row)
        result={}
        for fuel,tanks in groups.items():
            item=ops.tank_dict(tanks[0])
            item['current_liters']=sum(r.bc_ton for r in tanks)
            item['capacity']=sum(r.bc_dungtich for r in tanks)
            item['percentage']=item['current_liters']/item['capacity']*100 if item['capacity'] else 0
            result[fuel]=item
        return result
    result={}
    for tank in get_station_inventory(tx_ma)['tanks']:
        result.setdefault(tank['nl_ma'].strip(),tank)
    return result


def get_tank_by_fuel(tx_ma: str, nl_ma: str, *, db=None) -> Optional[Dict[str, Any]]:
    return get_tanks_by_fuel(tx_ma,db=db).get(nl_ma.strip())


def deduct_tank_fuel(tx_ma: str, nl_ma: str, liters: float) -> Dict[str, Any]:
    """
    Trừ số lít xăng trong bồn tương ứng khi thực hiện bơm xăng.
    Đồng thời cập nhật đồng hồ lũy kế của trụ bơm.
    """
    tx_ma = tx_ma.strip()
    nl_ma = nl_ma.strip()
    liters = round(float(liters), 2)
    data = _load_data()

    if tx_ma not in data:
        raise ValueError("Trạm chưa cấu hình kho nhiên liệu")

    st_data = data[tx_ma]
    matched_tank = None
    remaining = 0.0
    capacity = 25000.0

    for t in st_data.get("tanks", []):
        if t["nl_ma"].strip() == nl_ma:
            matched_tank = t
            old_val = float(t["current_liters"])
            new_val = max(0.0, round(old_val - liters, 2))
            t["current_liters"] = new_val
            t["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            remaining = new_val
            capacity = float(t["capacity"])
            break

    if matched_tank is None:
        raise ValueError("Trạm chưa cấu hình bồn nhiên liệu này")

    # Cập nhật lũy kế trụ bơm
    pumps = st_data.get("pumps", [])
    if pumps:
        pumps[0]["totalizer_liters"] = round(float(pumps[0].get("totalizer_liters", 0)) + liters, 2)

    _save_data(data)

    pct = round((remaining / capacity) * 100, 1) if capacity > 0 else 0.0

    return {
        "status": "success",
        "tank_name": matched_tank["tank_name"] if matched_tank else "Bồn chứa",
        "liters_deducted": liters,
        "liters_remaining": remaining,
        "capacity": capacity,
        "percentage": pct,
    }


def refill_tank(tx_ma: str, tank_id: str, liters: float, supplier: str = "Xe bồn Petrolimex") -> Dict[str, Any]:
    """Nhập thêm nhiên liệu vào bồn từ xe bồn."""
    tx_ma = tx_ma.strip()
    tank_id = tank_id.strip()
    liters = round(float(liters), 2)
    data = _load_data()

    if tx_ma not in data:
        raise ValueError("Trạm chưa cấu hình kho nhiên liệu")

    st_data = data[tx_ma]
    matched_tank = None
    new_val = 0.0

    for t in st_data.get("tanks", []):
        if t["tank_id"] == tank_id:
            matched_tank = t
            cap = float(t["capacity"])
            old_val = float(t["current_liters"])
            new_val = min(cap, round(old_val + liters, 2))
            t["current_liters"] = new_val
            t["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break

    if not matched_tank:
        raise ValueError("Không tìm thấy bồn chứa yêu cầu")

    refill_log = {
        "refill_id": f"RF_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "tank_name": matched_tank["tank_name"],
        "liters": liters,
        "supplier": supplier,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    history = st_data.setdefault("refill_history", [])
    history.insert(0, refill_log)
    if len(history) > 20:
        st_data["refill_history"] = history[:20]

    _save_data(data)

    return {
        "status": "success",
        "message": f"Nhập kho thành công {liters:,.2f} Lít vào {matched_tank['tank_name']}",
        "tank": matched_tank,
        "new_liters": new_val,
    }


def update_pump_status(tx_ma: str, pump_id: str, new_status: str) -> Dict[str, Any]:
    """Cập nhật trạng thái trụ bơm (READY, PUMPING, MAINTENANCE, OFFLINE)."""
    tx_ma = tx_ma.strip()
    pump_id = pump_id.strip()
    data = _load_data()

    if tx_ma not in data:
        raise ValueError("Trạm chưa cấu hình trụ bơm")

    st_data = data[tx_ma]
    matched = None
    for p in st_data.get("pumps", []):
        if p["pump_id"] == pump_id or p["pump_code"] == pump_id:
            p["status"] = new_status
            matched = p
            break

    if not matched:
        raise ValueError("Không tìm thấy trụ bơm yêu cầu")

    _save_data(data)
    return {
        "status": "success",
        "message": f"Cập nhật trạng thái {matched['pump_name']} thành {new_status}",
        "pump": matched,
    }
