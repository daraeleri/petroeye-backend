"""Read helpers shared by the REST API and the ingestion pipeline."""
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time import as_utc, utcnow
from app.db.models import Alert, AlertAcknowledgement, Geofence, TankCalibration, Telemetry, Truck
from app.domain.tank import TankGeometry, capacity_litres
from app.schemas.trucks import LatestReading, TruckActivity, TruckOut


def geometry_of(cal: TankCalibration | None) -> TankGeometry | None:
    if cal is None:
        return None
    return TankGeometry(
        shape=cal.shape,
        length_cm=cal.length_cm,
        width_cm=cal.width_cm,
        height_cm=cal.height_cm,
        diameter_cm=cal.diameter_cm,
        sensor_offset_cm=cal.sensor_offset_cm,
    )


async def active_geofences_for(session: AsyncSession, truck_id: str) -> list[Geofence]:
    """Active geofences that apply to this truck (its own + fleet-wide ones)."""
    result = await session.execute(
        select(Geofence).where(
            Geofence.is_active.is_(True),
            or_(Geofence.truck_id == truck_id, Geofence.truck_id.is_(None)),
        )
    )
    return list(result.scalars())


async def latest_telemetry(session: AsyncSession, truck_id: str) -> Telemetry | None:
    result = await session.execute(
        select(Telemetry).where(Telemetry.truck_id == truck_id).order_by(Telemetry.ts.desc()).limit(1)
    )
    return result.scalar_one_or_none()


def is_online(truck: Truck) -> bool:
    last = as_utc(truck.last_seen_at)
    if not truck.online or last is None:
        return False
    return utcnow() - last <= timedelta(seconds=settings.offline_after_seconds)


def activity_of(truck: Truck, latest: Telemetry | None) -> TruckActivity:
    if not is_online(truck):
        return TruckActivity.offline
    if latest is not None and latest.valve_open:
        return TruckActivity.discharging
    if latest is not None and (latest.speed_kmh or 0) > settings.moving_speed_kmh:
        return TruckActivity.moving
    return TruckActivity.parked


def build_truck_out(
    truck: Truck, latest: Telemetry | None, cal: TankCalibration | None, open_alerts: int
) -> TruckOut:
    geometry = geometry_of(cal)
    capacity = round(capacity_litres(geometry), 2) if geometry else None
    fill = None
    if capacity and latest is not None and latest.volume_l is not None:
        fill = round(100 * latest.volume_l / capacity, 1)
    return TruckOut(
        truck_id=truck.truck_id,
        plate=truck.plate,
        driver_name=truck.driver_name,
        notes=truck.notes,
        created_at=truck.created_at,
        online=is_online(truck),
        activity=activity_of(truck, latest),
        last_seen_at=truck.last_seen_at,
        firmware_version=truck.firmware_version,
        rssi_dbm=truck.rssi_dbm,
        uptime_s=truck.uptime_s,
        open_alerts=open_alerts,
        capacity_l=capacity,
        fill_pct=fill,
        latest=LatestReading.model_validate(latest, from_attributes=True) if latest else None,
    )


async def open_alert_counts(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(Alert.truck_id, func.count())
        .outerjoin(AlertAcknowledgement, AlertAcknowledgement.alert_id == Alert.id)
        .where(AlertAcknowledgement.id.is_(None))
        .group_by(Alert.truck_id)
    )
    return {truck_id: n for truck_id, n in result.all()}


async def truck_snapshot(session: AsyncSession, truck: Truck) -> TruckOut:
    latest = await latest_telemetry(session, truck.truck_id)
    cal = await session.get(TankCalibration, truck.truck_id)
    counts = await open_alert_counts(session)
    return build_truck_out(truck, latest, cal, counts.get(truck.truck_id, 0))


async def all_truck_snapshots(session: AsyncSession) -> list[TruckOut]:
    trucks = list((await session.execute(select(Truck).order_by(Truck.truck_id))).scalars())
    latest_ts = (
        select(Telemetry.truck_id, func.max(Telemetry.ts).label("max_ts"))
        .group_by(Telemetry.truck_id)
        .subquery()
    )
    latest_rows = (
        await session.execute(
            select(Telemetry).join(
                latest_ts,
                (Telemetry.truck_id == latest_ts.c.truck_id) & (Telemetry.ts == latest_ts.c.max_ts),
            )
        )
    ).scalars()
    latest_by_truck = {t.truck_id: t for t in latest_rows}
    cals = {c.truck_id: c for c in (await session.execute(select(TankCalibration))).scalars()}
    counts = await open_alert_counts(session)
    return [
        build_truck_out(t, latest_by_truck.get(t.truck_id), cals.get(t.truck_id), counts.get(t.truck_id, 0))
        for t in trucks
    ]
