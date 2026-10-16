import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import TankShape
from app.mqtt.schemas import TRUCK_ID_PATTERN


class TruckActivity(str, Enum):
    offline = "offline"
    parked = "parked"
    moving = "moving"
    discharging = "discharging"


class TankCalibrationIn(BaseModel):
    shape: TankShape = Field(description="Tank shape; decides which dimensions are required.")
    length_cm: float | None = Field(default=None, gt=0, description="Required for `rectangular` and `horizontal_cylinder`.")
    width_cm: float | None = Field(default=None, gt=0, description="Required for `rectangular`.")
    height_cm: float | None = Field(default=None, gt=0, description="Inner height. Required for `rectangular` and `vertical_cylinder`.")
    diameter_cm: float | None = Field(default=None, gt=0, description="Inner diameter. Required for both cylinder shapes.")
    sensor_offset_cm: float = Field(
        default=0.0, ge=0,
        description="What the ultrasonic sensor reads when the tank is completely full (sensor face → full liquid surface).",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"shape": "rectangular", "length_cm": 30, "width_cm": 20, "height_cm": 25, "sensor_offset_cm": 3},
        {"shape": "horizontal_cylinder", "diameter_cm": 180, "length_cm": 650, "sensor_offset_cm": 5},
    ]})


class TankCalibrationOut(TankCalibrationIn):
    model_config = ConfigDict(from_attributes=True)

    truck_id: str
    capacity_l: float = Field(description="Full-tank volume computed from the geometry.")
    updated_at: datetime


class TruckCreate(BaseModel):
    truck_id: str = Field(pattern=TRUCK_ID_PATTERN, description="ID used in the MQTT topic `petrotwin/{truck_id}/...`.",
                          examples=["truck-001"])
    plate: str | None = Field(default=None, max_length=32, examples=["LT 123 AB"])
    driver_name: str | None = Field(default=None, max_length=120, examples=["Jean Fotso"])
    notes: str | None = Field(default=None, max_length=500)


class TruckUpdate(BaseModel):
    plate: str | None = Field(default=None, max_length=32)
    driver_name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)


class LatestReading(BaseModel):
    """Most recent telemetry for the truck, with derived values."""

    ts: datetime
    gps_fix: bool
    lat: float | None
    lon: float | None
    speed_kmh: float | None
    course_deg: float | None
    sats: int
    hdop: float | None
    distance_cm: float | None = Field(description="Raw ultrasonic distance (sensor → liquid surface).")
    level_cm: float | None = Field(description="Liquid level; null until the tank is calibrated.")
    volume_l: float | None = Field(description="Liquid volume in litres; null until the tank is calibrated.")
    valve_open: bool
    geofence_id: uuid.UUID | None = Field(description="Geofence the truck is inside, if any.")


class TruckOut(BaseModel):
    truck_id: str
    plate: str | None
    driver_name: str | None
    notes: str | None
    created_at: datetime
    online: bool = Field(description="Device connected (last status/telemetry within the offline timeout).")
    activity: TruckActivity = Field(description="`offline`, `parked`, `moving` or `discharging` (valve open).")
    last_seen_at: datetime | None
    firmware_version: str | None
    rssi_dbm: int | None
    uptime_s: int | None
    open_alerts: int = Field(description="Alerts not yet acknowledged.")
    capacity_l: float | None = Field(description="Tank capacity, if calibrated.")
    fill_pct: float | None = Field(description="Current volume as % of capacity, if calibrated.")
    latest: LatestReading | None


class TelemetryOut(LatestReading):
    model_config = ConfigDict(from_attributes=True)

    received_at: datetime
