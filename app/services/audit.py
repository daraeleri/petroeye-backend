"""Activity log writer. The caller commits."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.db.models import AuditLog


def record(
    session: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    truck_id: str | None = None,
    details: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> AuditLog:
    entry = AuditLog(
        ts=ts or utcnow(),
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        truck_id=truck_id,
        details=details,
    )
    session.add(entry)
    return entry
