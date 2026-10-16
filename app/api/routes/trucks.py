from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DB, AdminUser, CurrentUser
from app.db.models import TankCalibration, Telemetry, Truck
from app.domain.tank import InvalidGeometry, TankGeometry, capacity_litres, validate_geometry
from app.schemas.trucks import (
    TankCalibrationIn,
    TankCalibrationOut,
    TelemetryOut,
    TruckCreate,
    TruckOut,
    TruckUpdate,
)
from app.services import audit
from app.services.fleet import all_truck_snapshots, geometry_of, truck_snapshot

router = APIRouter(prefix="/trucks", tags=["Trucks"])

_NOT_FOUND = {404: {"description": "Truck not found."}}


async def _get_truck(db, truck_id: str) -> Truck:
    truck = await db.get(Truck, truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail="Truck not found")
    return truck


@router.get("", response_model=list[TruckOut], summary="List trucks with live state")
async def list_trucks(db: DB, _: CurrentUser) -> list[TruckOut]:
    """Every registered truck with its latest reading: position, valve state,
    tank volume/fill %, online status, current activity and open alert count.

    This is the dashboard's initial load; live changes then arrive over the
    `/ws` WebSocket as `truck.update` events with the same shape.
    """
    return await all_truck_snapshots(db)


@router.post(
    "",
    response_model=TruckOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a truck (admin)",
    responses={409: {"description": "Truck ID already registered."}},
)
async def create_truck(body: TruckCreate, db: DB, admin: AdminUser) -> TruckOut:
    """Register a truck before its ESP32 connects. `truck_id` is the ID the
    device uses in its MQTT topics (`petrotwin/{truck_id}/telemetry`).

    Required when `AUTO_REGISTER_TRUCKS=false`; otherwise unknown trucks are
    registered automatically on their first message.
    """
    if await db.get(Truck, body.truck_id) is not None:
        raise HTTPException(status_code=409, detail="Truck already registered")
    truck = Truck(truck_id=body.truck_id, plate=body.plate, driver_name=body.driver_name, notes=body.notes,
                  online=False)
    db.add(truck)
    audit.record(db, "truck.create", user_id=admin.id, entity_type="truck", entity_id=truck.truck_id,
                 truck_id=truck.truck_id, details=body.model_dump(exclude={"truck_id"}))
    await db.commit()
    await db.refresh(truck)
    return await truck_snapshot(db, truck)


@router.get("/{truck_id}", response_model=TruckOut, summary="Get one truck with live state", responses=_NOT_FOUND)
async def get_truck(truck_id: str, db: DB, _: CurrentUser) -> TruckOut:
    return await truck_snapshot(db, await _get_truck(db, truck_id))


@router.patch("/{truck_id}", response_model=TruckOut, summary="Update truck details (admin)", responses=_NOT_FOUND)
async def update_truck(truck_id: str, body: TruckUpdate, db: DB, admin: AdminUser) -> TruckOut:
    """Edit plate, driver name or notes. Only the fields you send are changed."""
    truck = await _get_truck(db, truck_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(truck, key, value)
    audit.record(db, "truck.update", user_id=admin.id, entity_type="truck", entity_id=truck_id,
                 truck_id=truck_id, details=changes)
    await db.commit()
    await db.refresh(truck)
    return await truck_snapshot(db, truck)


# --- Tank calibration -----------------------------------------------------------


def _calibration_out(cal: TankCalibration) -> TankCalibrationOut:
    return TankCalibrationOut(
        truck_id=cal.truck_id, shape=cal.shape, length_cm=cal.length_cm, width_cm=cal.width_cm,
        height_cm=cal.height_cm, diameter_cm=cal.diameter_cm, sensor_offset_cm=cal.sensor_offset_cm,
        capacity_l=round(capacity_litres(geometry_of(cal)), 2), updated_at=cal.updated_at,
    )


@router.get(
    "/{truck_id}/tank",
    response_model=TankCalibrationOut,
    summary="Get tank calibration",
    responses={404: {"description": "Truck not found or tank not calibrated yet."}},
)
async def get_tank(truck_id: str, db: DB, _: CurrentUser) -> TankCalibrationOut:
    await _get_truck(db, truck_id)
    cal = await db.get(TankCalibration, truck_id)
    if cal is None:
        raise HTTPException(status_code=404, detail="Tank not calibrated")
    return _calibration_out(cal)


@router.put(
    "/{truck_id}/tank",
    response_model=TankCalibrationOut,
    summary="Set tank calibration (admin)",
    responses={**_NOT_FOUND, 422: {"description": "Dimensions missing for the chosen shape."}},
)
async def put_tank(truck_id: str, body: TankCalibrationIn, db: DB, admin: AdminUser) -> TankCalibrationOut:
    """Set the tank geometry used to turn the ultrasonic `distance_cm` into
    litres:

    `level = inner_height − (distance − sensor_offset)`, clamped to the tank, then
    volume from the shape:

    | shape | required |
    |---|---|
    | `rectangular` | `length_cm`, `width_cm`, `height_cm` |
    | `vertical_cylinder` | `diameter_cm`, `height_cm` |
    | `horizontal_cylinder` | `diameter_cm`, `length_cm` |

    Applies to readings received from now on (history is not recomputed).
    """
    await _get_truck(db, truck_id)
    try:
        validate_geometry(TankGeometry(**body.model_dump(mode="json")))
    except InvalidGeometry as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    cal = await db.get(TankCalibration, truck_id)
    if cal is None:
        cal = TankCalibration(truck_id=truck_id)
        db.add(cal)
    for key, value in body.model_dump(mode="json").items():
        setattr(cal, key, value)
    audit.record(db, "tank.calibrate", user_id=admin.id, entity_type="truck", entity_id=truck_id,
                 truck_id=truck_id, details=body.model_dump(mode="json"))
    await db.commit()
    await db.refresh(cal)
    return _calibration_out(cal)


# --- Telemetry history ----------------------------------------------------------


@router.get(
    "/{truck_id}/telemetry",
    response_model=list[TelemetryOut],
    summary="Telemetry history",
    responses=_NOT_FOUND,
)
async def telemetry_history(
    truck_id: str,
    db: DB,
    _: CurrentUser,
    start: Annotated[datetime | None, Query(description="From this time (inclusive, ISO 8601).")] = None,
    end: Annotated[datetime | None, Query(description="Up to this time (inclusive, ISO 8601).")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    order: Annotated[str, Query(pattern="^(asc|desc)$", description="`desc` = newest first.")] = "desc",
) -> list[Telemetry]:
    """Stored readings with derived level/volume and geofence — for the map
    track, volume charts and playback."""
    await _get_truck(db, truck_id)
    stmt = select(Telemetry).where(Telemetry.truck_id == truck_id)
    if start is not None:
        stmt = stmt.where(Telemetry.ts >= start)
    if end is not None:
        stmt = stmt.where(Telemetry.ts <= end)
    stmt = stmt.order_by(Telemetry.ts.asc() if order == "asc" else Telemetry.ts.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())
