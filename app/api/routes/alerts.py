from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import Alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    truck_id: str | None = None,
    unresolved_only: bool = False,
    limit: int = Query(default=100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if truck_id:
        stmt = stmt.where(Alert.truck_id == truck_id)
    if unresolved_only:
        stmt = stmt.where(Alert.resolved_at.is_(None))

    result = await db.execute(stmt)
    alerts = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "truck_id": a.truck_id,
            "type": a.type,
            "severity": a.severity,
            "message": a.message,
            "triggered_by": a.triggered_by,
            "created_at": a.created_at,
            "resolved_at": a.resolved_at,
            "onchain_tx_hash": a.onchain_tx_hash,
        }
        for a in alerts
    ]
