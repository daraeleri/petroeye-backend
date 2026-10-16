import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentUser, OperatorUser
from app.db.models import Alert, AlertAcknowledgement, AlertSeverity
from app.schemas.operations import AcknowledgeIn, AlertOut
from app.services import audit
from app.services.alerts import alert_out, alerts_with_acks_query
from app.ws.manager import ws_manager

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[AlertOut], summary="List alerts")
async def list_alerts(
    db: DB,
    _: CurrentUser,
    truck_id: str | None = None,
    severity: AlertSeverity | None = None,
    type: Annotated[str | None, Query(description="Rule name, e.g. `valve_open_outside_geofence`.")] = None,
    acknowledged: Annotated[bool | None, Query(description="true = only acknowledged, false = only open.")] = None,
    start: Annotated[datetime | None, Query(description="Created at or after (ISO 8601).")] = None,
    end: Annotated[datetime | None, Query(description="Created at or before (ISO 8601).")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AlertOut]:
    """Alerts newest first. Alert types:

    | type | severity | when |
    |---|---|---|
    | `valve_open_outside_geofence` | critical | valve opened (or still open) outside an approved geofence, or with no GPS fix |
    | `volume_drop_valve_closed` | warning | volume fell between readings while the valve was closed (leak/theft) |
    | `level_sensor_no_echo` | warning | ultrasonic sensor stopped returning a distance |
    | `device_offline` | warning | the ESP32 dropped off unexpectedly (MQTT Last Will; a clean shutdown is not an alert) |
    | `gps_fix_lost` | info | GPS lost its fix |
    """
    stmt = alerts_with_acks_query()
    if truck_id:
        stmt = stmt.where(Alert.truck_id == truck_id)
    if severity:
        stmt = stmt.where(Alert.severity == severity.value)
    if type:
        stmt = stmt.where(Alert.type == type)
    if acknowledged is True:
        stmt = stmt.where(AlertAcknowledgement.id.is_not(None))
    elif acknowledged is False:
        stmt = stmt.where(AlertAcknowledgement.id.is_(None))
    if start:
        stmt = stmt.where(Alert.created_at >= start)
    if end:
        stmt = stmt.where(Alert.created_at <= end)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
    return [alert_out(a, ack, email) for a, ack, email in (await db.execute(stmt)).all()]


async def _load(db, alert_id: uuid.UUID):
    row = (await db.execute(alerts_with_acks_query().where(Alert.id == alert_id))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return row


@router.get("/{alert_id}", response_model=AlertOut, summary="Get an alert",
            responses={404: {"description": "Alert not found."}})
async def get_alert(alert_id: uuid.UUID, db: DB, _: CurrentUser) -> AlertOut:
    return alert_out(*await _load(db, alert_id))


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertOut,
    status_code=status.HTTP_201_CREATED,
    summary="Acknowledge an alert (operator/admin)",
    responses={404: {"description": "Alert not found."}, 409: {"description": "Already acknowledged."}},
)
async def acknowledge_alert(alert_id: uuid.UUID, body: AcknowledgeIn, db: DB, user: OperatorUser) -> AlertOut:
    """Record that someone has seen and handled the alert, with an optional
    note. Alerts are append-only: the alert itself never changes; the
    acknowledgement is stored separately and is final."""
    alert, ack, _ = await _load(db, alert_id)
    if ack is not None:
        raise HTTPException(status_code=409, detail="Alert already acknowledged")
    ack = AlertAcknowledgement(alert_id=alert.id, user_id=user.id, note=body.note)
    db.add(ack)
    audit.record(db, "alert.acknowledge", user_id=user.id, entity_type="alert", entity_id=str(alert.id),
                 truck_id=alert.truck_id, details={"note": body.note, "type": alert.type})
    await db.commit()
    out = alert_out(*await _load(db, alert_id))
    await ws_manager.broadcast({"type": "alert.acknowledged", "truck_id": alert.truck_id,
                                "data": out.model_dump(mode="json")})
    return out
