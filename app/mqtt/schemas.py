"""
Pydantic schemas mirroring the payload contract in
docs/hardware-integration-guide.md (schema v2) EXACTLY. If you change a
field here, update that doc and the simulator in the same change — it's the
ESP32 firmware's source of truth.

Unknown fields are rejected (`extra="forbid"`), so a firmware typo shows
up as a logged rejection instead of silently missing data.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TRUCK_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class TelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    truck_id: str = Field(pattern=TRUCK_ID_PATTERN)
    ts: datetime
    gps_fix: bool
    lat: float | None = Field(ge=-90, le=90)
    lon: float | None = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(ge=0, le=300)
    course_deg: float | None = Field(ge=0, le=360)
    sats: int = Field(ge=0, le=50)
    hdop: float | None = Field(ge=0)
    distance_cm: float | None = Field(ge=0, le=500)
    valve_open: bool

    @model_validator(mode="after")
    def _fix_consistency(self) -> "TelemetryPayload":
        if self.gps_fix and (self.lat is None or self.lon is None):
            raise ValueError("gps_fix is true but lat/lon are null")
        if not self.gps_fix and (self.lat is not None or self.lon is not None):
            raise ValueError("gps_fix is false but lat/lon are set — send null without a fix")
        if self.ts.tzinfo is None:
            raise ValueError("ts must be UTC with a 'Z' suffix (timezone-aware)")
        return self


class EventPayload(BaseModel):
    """Something the device decided locally that the dashboard must know about.

    `valve_open_denied`: someone asked the truck to open the valve and the
    firmware's interlock refused (the valve stayed closed).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    truck_id: str = Field(pattern=TRUCK_ID_PATTERN)
    ts: datetime
    type: Literal["valve_open_denied"]
    reason: Literal["outside_geofence", "no_gps_fix", "moving", "control_disabled"]
    gps_fix: bool
    lat: float | None = Field(ge=-90, le=90)
    lon: float | None = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _consistency(self) -> "EventPayload":
        if self.gps_fix and (self.lat is None or self.lon is None):
            raise ValueError("gps_fix is true but lat/lon are null")
        if not self.gps_fix and (self.lat is not None or self.lon is not None):
            raise ValueError("gps_fix is false but lat/lon are set")
        if self.ts.tzinfo is None:
            raise ValueError("ts must be UTC with a 'Z' suffix (timezone-aware)")
        return self


class StatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    truck_id: str = Field(pattern=TRUCK_ID_PATTERN)
    # Optional only so the MQTT Last Will (composed at connect time) can omit it.
    ts: datetime | None = None
    online: bool
    firmware_version: str | None = Field(default=None, max_length=32)
    rssi_dbm: int | None = Field(default=None, ge=-150, le=0)
    uptime_s: int | None = Field(default=None, ge=0)
