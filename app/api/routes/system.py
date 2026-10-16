from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.base import AsyncSessionLocal
from app.mqtt.client import mqtt_subscriber

router = APIRouter(tags=["System"])


class HealthOut(BaseModel):
    status: str = Field(description="`ok` when the database answers, `degraded` otherwise.", examples=["ok"])
    database: bool
    mqtt_connected: bool = Field(description="Whether the backend is currently connected to the MQTT broker.")


@router.get("/health", response_model=HealthOut, summary="Health check (no auth)")
async def health() -> HealthOut:
    """Liveness/readiness probe. Point an uptime pinger here every ~10 minutes
    to keep a free Render instance awake. No authentication required."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except (SQLAlchemyError, OSError):
        db_ok = False
    return HealthOut(status="ok" if db_ok else "degraded", database=db_ok,
                     mqtt_connected=mqtt_subscriber.connected)
