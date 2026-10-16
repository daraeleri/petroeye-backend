import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.db.models import Discharge
from app.schemas.operations import DischargeOut

router = APIRouter(prefix="/discharges", tags=["Discharges"])


@router.get("", response_model=list[DischargeOut], summary="List discharge sessions")
async def list_discharges(
    db: DB,
    _: CurrentUser,
    truck_id: str | None = None,
    authorized: Annotated[bool | None, Query(description="true = inside a geofence, false = unauthorized.")] = None,
    open_only: Annotated[bool, Query(description="Only sessions where the valve is still open.")] = False,
    start: Annotated[datetime | None, Query(description="Opened at or after (ISO 8601).")] = None,
    end: Annotated[datetime | None, Query(description="Opened at or before (ISO 8601).")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Discharge]:
    """Every valve-open → valve-closed session, newest first: where and when
    it opened/closed, whether it was inside an approved geofence, and how many
    litres left the tank (once the tank is calibrated)."""
    stmt = select(Discharge)
    if truck_id:
        stmt = stmt.where(Discharge.truck_id == truck_id)
    if authorized is not None:
        stmt = stmt.where(Discharge.authorized.is_(authorized))
    if open_only:
        stmt = stmt.where(Discharge.closed_at.is_(None))
    if start:
        stmt = stmt.where(Discharge.opened_at >= start)
    if end:
        stmt = stmt.where(Discharge.opened_at <= end)
    stmt = stmt.order_by(Discharge.opened_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars())


@router.get("/{discharge_id}", response_model=DischargeOut, summary="Get a discharge session",
            responses={404: {"description": "Discharge not found."}})
async def get_discharge(discharge_id: uuid.UUID, db: DB, _: CurrentUser) -> Discharge:
    d = await db.get(Discharge, discharge_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Discharge not found")
    return d
