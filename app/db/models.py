"""
SQLAlchemy models for PetroTwin, matching the storage model in
docs/architecture.md. Every schema change needs an Alembic migration
(`uv run alembic revision --autogenerate -m "..."`).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# BIGINT identity on Postgres; SQLite (tests) only autoincrements INTEGER.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class UserRole(str, enum.Enum):
    admin = "admin"  # manages users, trucks and tank calibration, plus everything below
    operator = "operator"  # manages geofences and acknowledges alerts
    viewer = "viewer"  # read-only dashboard + report export


class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class TankShape(str, enum.Enum):
    rectangular = "rectangular"
    vertical_cylinder = "vertical_cylinder"
    horizontal_cylinder = "horizontal_cylinder"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=UserRole.viewer.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Truck(Base):
    __tablename__ = "trucks"

    # truck_id is the human-assigned ID used in MQTT topics (e.g. "truck-001"),
    # NOT a surrogate key — it must match docs/hardware-integration-guide.md.
    truck_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Device connectivity, from the status topic / LWT and any telemetry.
    online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rssi_dbm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uptime_s: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TankCalibration(Base):
    """Tank geometry used to turn the ultrasonic distance into litres.

    `sensor_offset_cm` is the distance the sensor reads when the tank is
    completely full (sensor face → maximum liquid surface).
    """

    __tablename__ = "tank_calibrations"

    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), primary_key=True)
    shape: Mapped[str] = mapped_column(String(32), nullable=False)
    length_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    diameter_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensor_offset_cm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Geofence(Base):
    """An approved discharge location: a point on the map plus a radius.

    `truck_id` NULL means the geofence applies to every truck.
    Geofences are deactivated, never deleted, so discharge history keeps
    pointing at the zone it happened in.
    """

    __tablename__ = "geofences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    truck_id: Mapped[str | None] = mapped_column(ForeignKey("trucks.truck_id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Telemetry(Base):
    __tablename__ = "telemetry"
    # Idempotent ingestion: a re-delivered MQTT message (QoS 1 allows
    # duplicates) maps to the same (truck_id, ts) and is skipped.
    __table_args__ = (UniqueConstraint("truck_id", "ts", name="uq_telemetry_truck_ts"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Raw device values (schema v2).
    gps_fix: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    course_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    sats: Mapped[int] = mapped_column(Integer, nullable=False)
    hdop: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    valve_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Derived at ingest time.
    level_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    geofence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("geofences.id"), nullable=True)


class Discharge(Base):
    """One valve-open → valve-closed session."""

    __tablename__ = "discharges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), nullable=False, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    geofence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("geofences.id"), nullable=True)
    authorized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    volume_start_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_end_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alerts.id"), nullable=True)


class Alert(Base):
    """Append-only. Acknowledging an alert adds an AlertAcknowledgement row."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    # Feature values that caused this alert, for explainability.
    triggered_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Filled asynchronously by the Web3 anchoring service. Null until anchored.
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    onchain_tx_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AlertAcknowledgement(Base):
    __tablename__ = "alert_acknowledgements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id"), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Activity log: user actions and device connectivity changes.

    `user_id` is NULL for system/device events (e.g. a truck going offline).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    truck_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
