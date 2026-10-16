from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import Truck

router = APIRouter(prefix="/trucks", tags=["trucks"])


@router.get("")
async def list_trucks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Truck))
    trucks = result.scalars().all()
    return [
        {
            "truck_id": t.truck_id,
            "plate": t.plate,
            "operator": t.operator,
            "status": t.status,
            "last_seen_at": t.last_seen_at,
        }
        for t in trucks
    ]


@router.get("/{truck_id}")
async def get_truck(truck_id: str, db: AsyncSession = Depends(get_db)):
    truck = await db.get(Truck, truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail="Truck not found")
    return {
        "truck_id": truck.truck_id,
        "plate": truck.plate,
        "operator": truck.operator,
        "status": truck.status,
        "last_seen_at": truck.last_seen_at,
    }
