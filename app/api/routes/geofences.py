import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser, OperatorUser
from app.db.models import Geofence, Truck
from app.domain.geo import find_containing_fence, nearest_fence
from app.schemas.operations import GeofenceCheckOut, GeofenceCreate, GeofenceOut, GeofenceUpdate
from app.services import audit
from app.services.fleet import active_geofences_for

router = APIRouter(prefix="/geofences", tags=["Geofences"])

_NOT_FOUND = {404: {"description": "Geofence not found."}}


async def _get_fence(db, fence_id: uuid.UUID) -> Geofence:
    fence = await db.get(Geofence, fence_id)
    if fence is None:
        raise HTTPException(status_code=404, detail="Geofence not found")
    return fence


async def _check_truck(db, truck_id: str | None) -> None:
    if truck_id is not None and await db.get(Truck, truck_id) is None:
        raise HTTPException(status_code=422, detail=f"Unknown truck '{truck_id}'")


@router.get("", response_model=list[GeofenceOut], summary="List geofences")
async def list_geofences(
    db: DB,
    _: CurrentUser,
    truck_id: Annotated[str | None, Query(description="Only geofences that apply to this truck "
                                                     "(its own + fleet-wide).")] = None,
    include_inactive: Annotated[bool, Query(description="Also return deactivated geofences.")] = False,
) -> list[Geofence]:
    stmt = select(Geofence).order_by(Geofence.created_at)
    if truck_id is not None:
        stmt = stmt.where(or_(Geofence.truck_id == truck_id, Geofence.truck_id.is_(None)))
    if not include_inactive:
        stmt = stmt.where(Geofence.is_active.is_(True))
    return list((await db.execute(stmt)).scalars())


@router.post(
    "",
    response_model=GeofenceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a geofence (operator/admin)",
    responses={422: {"description": "Invalid coordinates/radius or unknown truck."}},
)
async def create_geofence(body: GeofenceCreate, db: DB, user: OperatorUser) -> Geofence:
    """Mark an approved discharge location on the map: a centre point plus a
    radius in metres.

    The valve may only open while the truck is **inside an active geofence
    that applies to it** (assigned to that truck, or fleet-wide when
    `truck_id` is null). Opening it anywhere else — including with the
    prototype's test button — raises a critical `valve_open_outside_geofence`
    alert.
    """
    await _check_truck(db, body.truck_id)
    fence = Geofence(**body.model_dump(), is_active=True, created_by=user.id)
    db.add(fence)
    await db.flush()
    audit.record(db, "geofence.create", user_id=user.id, entity_type="geofence", entity_id=str(fence.id),
                 truck_id=body.truck_id, details=body.model_dump())
    await db.commit()
    await db.refresh(fence)
    return fence


@router.get(
    "/check",
    response_model=GeofenceCheckOut,
    summary="Is a point inside a geofence?",
    responses={404: {"description": "Truck not found."}},
)
async def check_point(
    db: DB,
    _: CurrentUser,
    truck_id: Annotated[str, Query(description="Truck whose geofences apply.")],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> GeofenceCheckOut:
    """Same check the ingestion pipeline runs on every reading. Handy for the
    map UI and for testing a geofence before the truck gets there."""
    if await db.get(Truck, truck_id) is None:
        raise HTTPException(status_code=404, detail="Truck not found")
    fences = await active_geofences_for(db, truck_id)
    hit = find_containing_fence(lat, lon, fences)
    near = nearest_fence(lat, lon, fences)
    return GeofenceCheckOut(
        inside=hit is not None,
        geofence=GeofenceOut.model_validate(hit.fence) if hit else None,
        nearest_distance_m=round(near.distance_m, 1) if near else None,
    )


@router.get("/{fence_id}", response_model=GeofenceOut, summary="Get a geofence", responses=_NOT_FOUND)
async def get_geofence(fence_id: uuid.UUID, db: DB, _: CurrentUser) -> Geofence:
    return await _get_fence(db, fence_id)


@router.patch("/{fence_id}", response_model=GeofenceOut, summary="Update a geofence (operator/admin)",
              responses=_NOT_FOUND)
async def update_geofence(fence_id: uuid.UUID, body: GeofenceUpdate, db: DB, user: OperatorUser) -> Geofence:
    """Move, resize, rename, re-assign or re-activate a geofence. Only the
    fields you send are changed; send `"truck_id": null` to make it fleet-wide."""
    fence = await _get_fence(db, fence_id)
    changes = body.model_dump(exclude_unset=True)
    if "truck_id" in changes:
        await _check_truck(db, changes["truck_id"])
    for key, value in changes.items():
        setattr(fence, key, value)
    audit.record(db, "geofence.update", user_id=user.id, entity_type="geofence", entity_id=str(fence.id),
                 truck_id=fence.truck_id, details=changes)
    await db.commit()
    await db.refresh(fence)
    return fence


@router.delete(
    "/{fence_id}",
    response_model=GeofenceOut,
    summary="Deactivate a geofence (operator/admin)",
    responses=_NOT_FOUND,
)
async def deactivate_geofence(fence_id: uuid.UUID, db: DB, user: OperatorUser) -> Geofence:
    """Deactivates the geofence (it stops authorizing discharges immediately).
    It isn't erased, so past discharges keep their reference; re-activate it
    with `PATCH {"is_active": true}`."""
    fence = await _get_fence(db, fence_id)
    fence.is_active = False
    audit.record(db, "geofence.deactivate", user_id=user.id, entity_type="geofence", entity_id=str(fence.id),
                 truck_id=fence.truck_id)
    await db.commit()
    await db.refresh(fence)
    return fence
