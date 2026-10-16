"""Schemas for geofences, alerts, discharges and the activity log."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AlertSeverity

# --- Geofences ----------------------------------------------------------------


class GeofenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Total depot — Mvan"])
    description: str | None = Field(default=None, max_length=500)
    lat: float = Field(ge=-90, le=90, description="Centre latitude (WGS84).", examples=[3.8667])
    lon: float = Field(ge=-180, le=180, description="Centre longitude (WGS84).", examples=[11.5167])
    radius_m: float = Field(gt=0, le=50_000, description="Radius in metres.", examples=[150])
    truck_id: str | None = Field(
        default=None, description="Restrict to one truck. Omit/null to apply the geofence to every truck.",
        examples=["truck-001"],
    )


class GeofenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float | None = Field(default=None, gt=0, le=50_000)
    truck_id: str | None = Field(
        default=None,
        description="A truck ID, or `null` to apply the geofence to every truck. Omit to leave unchanged.",
    )
    is_active: bool | None = Field(default=None, description="Re-activate a deactivated geofence.")


class GeofenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    lat: float
    lon: float
    radius_m: float
    truck_id: str | None = Field(description="null = applies to every truck.")
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class GeofenceCheckOut(BaseModel):
    inside: bool = Field(description="Whether the point is inside an active geofence for the truck.")
    geofence: GeofenceOut | None = Field(description="The containing geofence (closest one if several overlap).")
    nearest_distance_m: float | None = Field(description="Distance to the nearest geofence centre.")


# --- Alerts -------------------------------------------------------------------


class AcknowledgementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    user_email: str | None = None
    note: str | None
    created_at: datetime


class AlertOut(BaseModel):
    id: uuid.UUID
    truck_id: str
    type: str = Field(examples=["valve_open_outside_geofence"],
                      description="Rule that fired — see `app/ai/rules.yaml`.")
    severity: AlertSeverity
    message: str
    triggered_by: dict[str, Any] | None = Field(description="Values that caused the alert, for explainability.")
    lat: float | None
    lon: float | None
    created_at: datetime
    digest: str | None = Field(description="SHA-256 of the canonical alert record (Web3 anchoring).")
    onchain_tx_hash: str | None
    acknowledgement: AcknowledgementOut | None


class AcknowledgeIn(BaseModel):
    note: str | None = Field(default=None, max_length=500, examples=["Driver confirmed: test button pressed at depot."])


# --- Discharges ----------------------------------------------------------------


class DischargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    truck_id: str
    opened_at: datetime
    closed_at: datetime | None = Field(description="null while the valve is still open.")
    open_lat: float | None
    open_lon: float | None
    close_lat: float | None
    close_lon: float | None
    geofence_id: uuid.UUID | None = Field(description="Geofence the valve opened in; null if outside.")
    authorized: bool = Field(description="true if the valve opened inside an approved geofence.")
    volume_start_l: float | None
    volume_end_l: float | None
    litres: float | None = Field(description="Volume discharged (start − end), once closed and calibrated.")
    alert_id: uuid.UUID | None = Field(description="Alert raised for an unauthorized opening.")


# --- Activity / audit ---------------------------------------------------------


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    user_id: uuid.UUID | None
    action: str = Field(examples=["geofence.create"])
    entity_type: str | None
    entity_id: str | None
    truck_id: str | None
    details: dict[str, Any] | None


class ActivityEntry(BaseModel):
    ts: datetime
    truck_id: str | None
    category: str = Field(description="`discharge`, `alert`, `acknowledgement`, `device` or `user`.")
    event: str = Field(examples=["discharge.opened", "alert.valve_open_outside_geofence", "device.offline"])
    description: str
    ref_id: str | None = Field(description="ID of the discharge/alert/audit row.")


class ReportSummary(BaseModel):
    start: datetime | None
    end: datetime | None
    truck_id: str | None
    discharges_total: int
    discharges_authorized: int
    discharges_unauthorized: int
    litres_discharged: float = Field(description="Sum over closed, calibrated discharges.")
    alerts_total: int
    alerts_by_severity: dict[str, int]
    alerts_by_type: dict[str, int]
    alerts_unacknowledged: int
    telemetry_points: int
