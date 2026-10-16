"""Report building: each kind returns a list of flat dict rows, ready for
CSV or JSON export."""
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_utc
from app.db.models import Alert, AuditLog, Discharge, Geofence, Telemetry, User
from app.schemas.operations import ActivityEntry, ReportSummary
from app.services.alerts import alerts_with_acks_query

TELEMETRY_EXPORT_MAX = 100_000


def _range(stmt, column, start: datetime | None, end: datetime | None):
    if start is not None:
        stmt = stmt.where(column >= start)
    if end is not None:
        stmt = stmt.where(column <= end)
    return stmt


def _iso(dt: datetime | None) -> str | None:
    return as_utc(dt).isoformat() if dt else None


async def discharge_rows(db: AsyncSession, start, end, truck_id) -> list[dict[str, Any]]:
    stmt = select(Discharge, Geofence.name).outerjoin(Geofence, Geofence.id == Discharge.geofence_id)
    stmt = _range(stmt, Discharge.opened_at, start, end)
    if truck_id:
        stmt = stmt.where(Discharge.truck_id == truck_id)
    rows = []
    for d, fence_name in (await db.execute(stmt.order_by(Discharge.opened_at))).all():
        rows.append({
            "id": str(d.id),
            "truck_id": d.truck_id,
            "opened_at": _iso(d.opened_at),
            "closed_at": _iso(d.closed_at),
            "duration_s": (int((as_utc(d.closed_at) - as_utc(d.opened_at)).total_seconds())
                           if d.closed_at else None),
            "authorized": d.authorized,
            "geofence": fence_name,
            "open_lat": d.open_lat,
            "open_lon": d.open_lon,
            "close_lat": d.close_lat,
            "close_lon": d.close_lon,
            "volume_start_l": d.volume_start_l,
            "volume_end_l": d.volume_end_l,
            "litres": d.litres,
            "alert_id": str(d.alert_id) if d.alert_id else None,
        })
    return rows


async def alert_rows(db: AsyncSession, start, end, truck_id) -> list[dict[str, Any]]:
    stmt = _range(alerts_with_acks_query(), Alert.created_at, start, end)
    if truck_id:
        stmt = stmt.where(Alert.truck_id == truck_id)
    rows = []
    for a, ack, email in (await db.execute(stmt.order_by(Alert.created_at))).all():
        rows.append({
            "id": str(a.id),
            "truck_id": a.truck_id,
            "created_at": _iso(a.created_at),
            "type": a.type,
            "severity": a.severity,
            "message": a.message,
            "lat": a.lat,
            "lon": a.lon,
            "details": a.triggered_by,
            "acknowledged_at": _iso(ack.created_at) if ack else None,
            "acknowledged_by": email,
            "ack_note": ack.note if ack else None,
            "digest": a.digest,
            "onchain_tx_hash": a.onchain_tx_hash,
        })
    return rows


async def telemetry_rows(db: AsyncSession, start, end, truck_id) -> list[dict[str, Any]]:
    stmt = _range(select(Telemetry), Telemetry.ts, start, end)
    if truck_id:
        stmt = stmt.where(Telemetry.truck_id == truck_id)
    stmt = stmt.order_by(Telemetry.ts).limit(TELEMETRY_EXPORT_MAX)
    return [{
        "truck_id": t.truck_id,
        "ts": _iso(t.ts),
        "gps_fix": t.gps_fix,
        "lat": t.lat,
        "lon": t.lon,
        "speed_kmh": t.speed_kmh,
        "course_deg": t.course_deg,
        "sats": t.sats,
        "hdop": t.hdop,
        "distance_cm": t.distance_cm,
        "level_cm": t.level_cm,
        "volume_l": t.volume_l,
        "valve_open": t.valve_open,
        "geofence_id": str(t.geofence_id) if t.geofence_id else None,
    } for t in (await db.execute(stmt)).scalars()]


async def audit_rows(db: AsyncSession, start, end, truck_id) -> list[dict[str, Any]]:
    stmt = _range(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id), AuditLog.ts, start, end)
    if truck_id:
        stmt = stmt.where(AuditLog.truck_id == truck_id)
    return [{
        "id": e.id,
        "ts": _iso(e.ts),
        "user": email,
        "action": e.action,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "truck_id": e.truck_id,
        "details": e.details,
    } for e, email in (await db.execute(stmt.order_by(AuditLog.ts))).all()]


async def activity_entries(db: AsyncSession, start, end, truck_id) -> list[ActivityEntry]:
    """One chronological timeline: discharges, alerts, acknowledgements,
    device online/offline and user changes (logins excluded)."""
    entries: list[ActivityEntry] = []

    for d in await discharge_rows(db, start, end, truck_id):
        where = f"inside '{d['geofence']}'" if d["authorized"] else "OUTSIDE any approved geofence"
        entries.append(ActivityEntry(
            ts=d["opened_at"], truck_id=d["truck_id"], category="discharge", event="discharge.opened",
            description=f"Valve opened {where}", ref_id=d["id"]))
        if d["closed_at"]:
            litres = f" — {d['litres']} L discharged" if d["litres"] is not None else ""
            entries.append(ActivityEntry(
                ts=d["closed_at"], truck_id=d["truck_id"], category="discharge", event="discharge.closed",
                description=f"Valve closed{litres}", ref_id=d["id"]))

    for a in await alert_rows(db, start, end, truck_id):
        entries.append(ActivityEntry(
            ts=a["created_at"], truck_id=a["truck_id"], category="alert", event=f"alert.{a['type']}",
            description=f"[{a['severity']}] {a['message']}", ref_id=a["id"]))
        if a["acknowledged_at"]:
            note = f": {a['ack_note']}" if a["ack_note"] else ""
            entries.append(ActivityEntry(
                ts=a["acknowledged_at"], truck_id=a["truck_id"], category="acknowledgement",
                event="alert.acknowledged", description=f"{a['acknowledged_by']} acknowledged {a['type']}{note}",
                ref_id=a["id"]))

    for e in await audit_rows(db, start, end, truck_id):
        if e["action"].startswith("auth.") or e["action"] == "alert.acknowledge":
            continue  # logins are audit-only; acks are already listed above
        category = "device" if e["action"].startswith("device.") else "user"
        who = e["user"] or "system"
        entries.append(ActivityEntry(
            ts=e["ts"], truck_id=e["truck_id"], category=category, event=e["action"],
            description=f"{e['action']} by {who}" if category == "user" else e["action"].replace(".", " "),
            ref_id=str(e["id"])))

    entries.sort(key=lambda x: x.ts)
    return entries


async def summary(db: AsyncSession, start, end, truck_id) -> ReportSummary:
    discharges = await discharge_rows(db, start, end, truck_id)
    alerts = await alert_rows(db, start, end, truck_id)
    tel_stmt = _range(select(func.count()).select_from(Telemetry), Telemetry.ts, start, end)
    if truck_id:
        tel_stmt = tel_stmt.where(Telemetry.truck_id == truck_id)
    by_sev: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for a in alerts:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1
    authorized = sum(1 for d in discharges if d["authorized"])
    return ReportSummary(
        start=start, end=end, truck_id=truck_id,
        discharges_total=len(discharges),
        discharges_authorized=authorized,
        discharges_unauthorized=len(discharges) - authorized,
        litres_discharged=round(sum(d["litres"] or 0 for d in discharges if d["litres"] and d["litres"] > 0), 2),
        alerts_total=len(alerts),
        alerts_by_severity=by_sev,
        alerts_by_type=by_type,
        alerts_unacknowledged=sum(1 for a in alerts if not a["acknowledged_at"]),
        telemetry_points=await db.scalar(tel_stmt) or 0,
    )


