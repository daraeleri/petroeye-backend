"""Creating and serialising alerts."""
import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rule_engine import Anomaly
from app.db.models import Alert, AlertAcknowledgement, User
from app.schemas.operations import AcknowledgementOut, AlertOut


def alert_digest(alert: Alert) -> str:
    """SHA-256 of the canonical alert record — what Web3 anchoring puts on-chain.

    Raw telemetry is never anchored; only this digest.
    """
    canonical = {
        "id": str(alert.id),
        "truck_id": alert.truck_id,
        "type": alert.type,
        "severity": alert.severity,
        "created_at": alert.created_at.isoformat(),
        "triggered_by": alert.triggered_by,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


def new_alert(
    session: AsyncSession, truck_id: str, anomaly: Anomaly, created_at: datetime,
    lat: float | None = None, lon: float | None = None,
) -> Alert:
    alert = Alert(
        id=uuid.uuid4(),
        truck_id=truck_id,
        type=anomaly.type,
        severity=anomaly.severity,
        message=anomaly.message,
        triggered_by=anomaly.triggered_by,
        lat=lat,
        lon=lon,
        created_at=created_at,
    )
    alert.digest = alert_digest(alert)
    session.add(alert)
    return alert


def alert_out(alert: Alert, ack: AlertAcknowledgement | None = None, ack_email: str | None = None) -> AlertOut:
    return AlertOut(
        id=alert.id,
        truck_id=alert.truck_id,
        type=alert.type,
        severity=alert.severity,
        message=alert.message,
        triggered_by=alert.triggered_by,
        lat=alert.lat,
        lon=alert.lon,
        created_at=alert.created_at,
        digest=alert.digest,
        onchain_tx_hash=alert.onchain_tx_hash,
        acknowledgement=(
            AcknowledgementOut(user_id=ack.user_id, user_email=ack_email, note=ack.note, created_at=ack.created_at)
            if ack else None
        ),
    )


def alerts_with_acks_query():
    """SELECT alert, acknowledgement, acknowledging user's email."""
    return (
        select(Alert, AlertAcknowledgement, User.email)
        .outerjoin(AlertAcknowledgement, AlertAcknowledgement.alert_id == Alert.id)
        .outerjoin(User, User.id == AlertAcknowledgement.user_id)
    )
