from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import Telemetry

router = APIRouter(prefix="/trucks", tags=["telemetry"])


@router.get("/{truck_id}/telemetry")
async def get_telemetry_history(
    truck_id: str,
    limit: int = Query(default=200, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """Historical telemetry for playback/charts. Newest first."""
    result = await db.execute(
        select(Telemetry)
        .where(Telemetry.truck_id == truck_id)
        .order_by(Telemetry.ts.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        {
            "ts": r.ts,
            "fuel_level_pct": r.fuel_level_pct,
            "temperature_c": r.temperature_c,
            "pressure_kpa": r.pressure_kpa,
            "lat": r.lat,
            "lon": r.lon,
            "tilt_deg": r.tilt_deg,
            "flow_rate_lpm": r.flow_rate_lpm,
            "hatch_open": r.hatch_open,
        }
        for r in rows
    ]
