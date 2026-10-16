"""
Pydantic schemas mirroring the payload contract in
docs/hardware-integration-guide.md EXACTLY. If you change a field here,
update that doc in the same change — it's the physical prototype team's
source of truth.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class TelemetryPayload(BaseModel):
    schema_version: int = 1
    truck_id: str
    ts: datetime
    fuel_level_pct: float = Field(ge=0, le=100)
    temperature_c: float
    pressure_kpa: float = Field(ge=0)
    lat: float
    lon: float
    tilt_deg: float = Field(ge=0, le=90)
    flow_rate_lpm: float = Field(ge=0)
    hatch_open: bool = False


class StatusPayload(BaseModel):
    schema_version: int = 1
    truck_id: str
    ts: datetime
    online: bool
    battery_pct: int | None = None
    firmware_version: str | None = None
