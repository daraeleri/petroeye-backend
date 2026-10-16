"""
Ingestion orchestration: takes a validated MQTT payload, derives tank
volume and geofence status, runs the rule engine, tracks discharge
sessions, persists everything, then broadcasts over WebSocket.

This is where the MQTT, DB, AI and WS boundaries meet — none of those
modules call each other directly. Nothing here ever sends anything back to
the truck: the system is read-only towards the device.
"""
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rule_engine import (
    RULES,
    VALVE_OPEN_OUTSIDE_GEOFENCE,
    ReadingContext,
    evaluate_event,
    evaluate_reading,
    evaluate_status,
)
from app.config import settings
from app.core.time import as_utc, utcnow
from app.db.base import AsyncSessionLocal
from app.db.models import Alert, Discharge, TankCalibration, Telemetry, Truck
from app.domain.geo import FenceHit, find_containing_fence, nearest_fence
from app.domain.tank import capacity_litres, measure
from app.mqtt.schemas import EventPayload, StatusPayload, TelemetryPayload
from app.schemas.operations import DischargeOut
from app.services import audit
from app.services.alerts import alert_out, new_alert
from app.services.fleet import active_geofences_for, geometry_of, latest_telemetry, truck_snapshot

logger = logging.getLogger("petrotwin.ingestion")


@dataclass
class IngestResult:
    accepted: bool
    reason: str | None = None
    telemetry: Telemetry | None = None
    alerts: list[Alert] = field(default_factory=list)
    discharge_started: Discharge | None = None
    discharge_ended: Discharge | None = None


async def _get_or_register_truck(session: AsyncSession, truck_id: str) -> Truck | None:
    truck = await session.get(Truck, truck_id)
    if truck is not None:
        return truck
    if not settings.auto_register_trucks:
        logger.warning("Rejected message from unregistered truck '%s' (AUTO_REGISTER_TRUCKS=false)", truck_id)
        return None
    truck = Truck(truck_id=truck_id, online=False)
    session.add(truck)
    await session.flush()
    audit.record(session, "truck.auto_registered", entity_type="truck", entity_id=truck_id, truck_id=truck_id)
    logger.info("Auto-registered truck '%s'", truck_id)
    return truck


async def _open_discharge(session: AsyncSession, truck_id: str) -> Discharge | None:
    result = await session.execute(
        select(Discharge)
        .where(Discharge.truck_id == truck_id, Discharge.closed_at.is_(None))
        .order_by(Discharge.opened_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _in_cooldown(session: AsyncSession, truck_id: str, alert_type: str, ts) -> bool:
    """True if this rule has a `cooldown_s` and already fired for the truck within it."""
    cooldown = (RULES.get(alert_type) or {}).get("cooldown_s")
    if not cooldown:
        return False
    recent = await session.scalar(
        select(Alert.id).where(
            Alert.truck_id == truck_id,
            Alert.type == alert_type,
            Alert.created_at >= ts - timedelta(seconds=cooldown),
        ).limit(1)
    )
    return recent is not None


def _mark_online(session: AsyncSession, truck: Truck, ts) -> None:
    if not truck.online:
        truck.online = True
        audit.record(session, "device.online", entity_type="truck", entity_id=truck.truck_id,
                     truck_id=truck.truck_id, ts=ts)


async def ingest_telemetry(session: AsyncSession, payload: TelemetryPayload) -> IngestResult:
    """Process one telemetry message inside `session`. The caller commits."""
    truck = await _get_or_register_truck(session, payload.truck_id)
    if truck is None:
        return IngestResult(accepted=False, reason="unregistered_truck")

    duplicate = await session.scalar(
        select(Telemetry.id).where(Telemetry.truck_id == payload.truck_id, Telemetry.ts == payload.ts)
    )
    if duplicate is not None:
        return IngestResult(accepted=False, reason="duplicate")

    previous = await latest_telemetry(session, payload.truck_id)
    out_of_order = previous is not None and payload.ts <= as_utc(previous.ts)

    geometry = geometry_of(await session.get(TankCalibration, payload.truck_id))
    level_cm, volume_l = measure(geometry, payload.distance_cm)
    fences = await active_geofences_for(session, payload.truck_id)
    inside = find_containing_fence(payload.lat, payload.lon, fences)
    if (
        inside is None
        and not payload.gps_fix
        and payload.valve_open
        and previous is not None
        and previous.valve_open
        and previous.geofence_id is not None
    ):
        # GPS dropped out in the middle of a discharge that started inside a
        # geofence: keep the last known geofence instead of treating "no fix"
        # as "left the zone". If the fix comes back outside with the valve
        # still open, the rule engine then reports `left_geofence_with_valve_open`.
        last_fence = next((f for f in fences if f.id == previous.geofence_id), None)
        if last_fence is not None:
            inside = FenceHit(fence=last_fence, distance_m=0.0)

    reading = Telemetry(
        truck_id=payload.truck_id,
        ts=payload.ts,
        gps_fix=payload.gps_fix,
        lat=payload.lat,
        lon=payload.lon,
        speed_kmh=payload.speed_kmh,
        course_deg=payload.course_deg,
        sats=payload.sats,
        hdop=payload.hdop,
        distance_cm=payload.distance_cm,
        valve_open=payload.valve_open,
        schema_version=payload.schema_version,
        level_cm=level_cm,
        volume_l=volume_l,
        geofence_id=inside.fence.id if inside else None,
    )
    session.add(reading)

    last_seen = as_utc(truck.last_seen_at)
    if last_seen is None or payload.ts > last_seen:
        truck.last_seen_at = payload.ts
    _mark_online(session, truck, payload.ts)

    result = IngestResult(accepted=True, telemetry=reading)
    if out_of_order:
        # Late re-delivery: keep it in history, but state transitions were
        # already evaluated against newer readings.
        logger.info("Stored out-of-order reading for %s at %s", payload.truck_id, payload.ts)
        await session.flush()
        return result

    ctx = ReadingContext(
        volume_l=volume_l,
        previous_volume_l=previous.volume_l if previous else None,
        capacity_l=capacity_litres(geometry) if geometry else None,
        inside=inside,
        previous_inside=previous is not None and previous.geofence_id is not None,
        nearest=nearest_fence(payload.lat, payload.lon, fences),
    )
    for anomaly in evaluate_reading(payload, previous, ctx):
        if await _in_cooldown(session, payload.truck_id, anomaly.type, payload.ts):
            continue
        alert = new_alert(session, payload.truck_id, anomaly, payload.ts, payload.lat, payload.lon)
        result.alerts.append(alert)
        logger.warning("Alert %s [%s] on %s: %s", anomaly.type, anomaly.severity,
                       payload.truck_id, anomaly.triggered_by)
    valve_alert = next((a for a in result.alerts if a.type == VALVE_OPEN_OUTSIDE_GEOFENCE), None)

    # --- Discharge sessions (valve open → closed) ---------------------------
    open_discharge = await _open_discharge(session, payload.truck_id)
    if payload.valve_open and open_discharge is None:
        discharge = Discharge(
            truck_id=payload.truck_id,
            opened_at=payload.ts,
            open_lat=payload.lat,
            open_lon=payload.lon,
            geofence_id=inside.fence.id if inside else None,
            authorized=inside is not None,
            volume_start_l=volume_l,
            alert_id=valve_alert.id if valve_alert else None,
        )
        session.add(discharge)
        result.discharge_started = discharge
    elif payload.valve_open and open_discharge is not None and valve_alert is not None:
        # Left the geofence with the valve still open.
        open_discharge.authorized = False
        open_discharge.alert_id = open_discharge.alert_id or valve_alert.id
    elif not payload.valve_open and open_discharge is not None:
        open_discharge.closed_at = payload.ts
        open_discharge.close_lat = payload.lat
        open_discharge.close_lon = payload.lon
        open_discharge.volume_end_l = volume_l
        if open_discharge.volume_start_l is not None and volume_l is not None:
            open_discharge.litres = round(open_discharge.volume_start_l - volume_l, 2)
        result.discharge_ended = open_discharge

    await session.flush()
    return result


async def ingest_status(session: AsyncSession, payload: StatusPayload) -> tuple[Truck | None, list[Alert]]:
    truck = await _get_or_register_truck(session, payload.truck_id)
    if truck is None:
        return None, []
    ts = payload.ts or utcnow()
    was_online = truck.online

    if payload.online:
        last_seen = as_utc(truck.last_seen_at)
        if last_seen is None or ts > last_seen:
            truck.last_seen_at = ts
        _mark_online(session, truck, ts)
    elif was_online:
        truck.online = False
        audit.record(session, "device.offline", entity_type="truck", entity_id=truck.truck_id,
                     truck_id=truck.truck_id, ts=ts)
    if payload.firmware_version is not None:
        truck.firmware_version = payload.firmware_version
    if payload.rssi_dbm is not None:
        truck.rssi_dbm = payload.rssi_dbm
    if payload.uptime_s is not None:
        truck.uptime_s = payload.uptime_s

    # The Last Will is the only status message without `ts` (it's composed at
    # connect time), so a missing ts means the broker reported a dropped device.
    unexpected = payload.ts is None
    alerts = [new_alert(session, truck.truck_id, a, ts)
              for a in evaluate_status(was_online, payload.online, unexpected)]
    await session.flush()
    return truck, alerts


async def ingest_event(session: AsyncSession, payload: EventPayload) -> tuple[Truck | None, list[Alert]]:
    """A device-side decision, e.g. the firmware refused to open the valve."""
    truck = await _get_or_register_truck(session, payload.truck_id)
    if truck is None:
        return None, []
    last_seen = as_utc(truck.last_seen_at)
    if last_seen is None or payload.ts > last_seen:
        truck.last_seen_at = payload.ts
    _mark_online(session, truck, payload.ts)

    fences = await active_geofences_for(session, payload.truck_id)
    alerts: list[Alert] = []
    for anomaly in evaluate_event(payload, nearest_fence(payload.lat, payload.lon, fences)):
        if await _in_cooldown(session, payload.truck_id, anomaly.type, payload.ts):
            continue
        alerts.append(new_alert(session, payload.truck_id, anomaly, payload.ts, payload.lat, payload.lon))
        logger.warning("Alert %s [%s] on %s: %s", anomaly.type, anomaly.severity, payload.truck_id,
                       anomaly.triggered_by)
    await session.flush()
    return truck, alerts


# --- Entry points used by the MQTT client -------------------------------------

# One lock per truck: messages for the same truck are processed in order so
# "previous reading" and discharge state are never raced.
_truck_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _broadcast_after_commit(session: AsyncSession, truck_id: str, alerts: list[Alert],
                                  started: Discharge | None = None, ended: Discharge | None = None) -> None:
    from app.web3.anchoring import anchoring_queue
    from app.ws.manager import ws_manager

    truck = await session.get(Truck, truck_id)
    if truck is not None:
        snapshot = await truck_snapshot(session, truck)
        await ws_manager.broadcast({"type": "truck.update", "truck_id": truck_id,
                                    "data": snapshot.model_dump(mode="json")})
    for alert in alerts:
        await ws_manager.broadcast({"type": "alert.created", "truck_id": truck_id,
                                    "data": alert_out(alert).model_dump(mode="json")})
        if alert.severity == "critical":
            # Queued, never awaited inline: a slow chain can't delay ingestion.
            await anchoring_queue.enqueue(alert_id=str(alert.id), digest=alert.digest or "")
    if started is not None:
        await ws_manager.broadcast({"type": "discharge.started", "truck_id": truck_id,
                                    "data": DischargeOut.model_validate(started).model_dump(mode="json")})
    if ended is not None:
        await ws_manager.broadcast({"type": "discharge.ended", "truck_id": truck_id,
                                    "data": DischargeOut.model_validate(ended).model_dump(mode="json")})


async def handle_telemetry(payload: TelemetryPayload) -> None:
    async with _truck_locks[payload.truck_id]:
        async with AsyncSessionLocal() as session:
            try:
                result = await ingest_telemetry(session, payload)
                if not result.accepted:
                    if result.reason == "duplicate":
                        logger.debug("Skipped duplicate reading %s @ %s", payload.truck_id, payload.ts)
                    return
                await session.commit()
            except IntegrityError:
                # Another backend instance (e.g. overlapping deploys) stored the
                # same (truck_id, ts) between our duplicate check and insert.
                # The unique constraint kept the data correct; nothing to do.
                await session.rollback()
                logger.info("Reading %s @ %s already stored by another instance", payload.truck_id, payload.ts)
                return
            await _broadcast_after_commit(session, payload.truck_id, result.alerts,
                                          result.discharge_started, result.discharge_ended)


async def handle_status(payload: StatusPayload) -> None:
    async with _truck_locks[payload.truck_id]:
        async with AsyncSessionLocal() as session:
            truck, alerts = await ingest_status(session, payload)
            if truck is None:
                return
            await session.commit()
            await _broadcast_after_commit(session, payload.truck_id, alerts)


async def handle_event(payload: EventPayload) -> None:
    async with _truck_locks[payload.truck_id]:
        async with AsyncSessionLocal() as session:
            truck, alerts = await ingest_event(session, payload)
            if truck is None:
                return
            await session.commit()
            await _broadcast_after_commit(session, payload.truck_id, alerts)
