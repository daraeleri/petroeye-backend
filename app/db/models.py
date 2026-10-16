"""
SQLAlchemy models for PetroTwin, matching the storage model defined in
docs/architecture.md.

Note: `telemetry` is designed to become a TimescaleDB hypertable later
(convert via `SELECT create_hypertable('telemetry', 'ts')` once the
Timescale extension is available) — the schema below works as plain
Postgres in the meantime.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TruckStatus(str, enum.Enum):
    idle = "idle"
    loading = "loading"
    in_transit = "in_transit"
    delivered = "delivered"
    alert = "alert"
    offline = "offline"


class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class Truck(Base):
    __tablename__ = "trucks"

    # truck_id is the human-assigned ID used in MQTT topics (e.g. "truck-001"),
    # NOT a surrogate UUID — it must match docs/hardware-integration-guide.md exactly.
    truck_id: Mapped[str] = mapped_column(String, primary_key=True)
    plate: Mapped[str | None] = mapped_column(String, nullable=True)
    operator: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[TruckStatus] = mapped_column(
        String, default=TruckStatus.idle, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    fuel_level_pct: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    pressure_kpa: Mapped[float] = mapped_column(Float, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    tilt_deg: Mapped[float] = mapped_column(Float, nullable=False)
    flow_rate_lpm: Mapped[float] = mapped_column(Float, nullable=False)
    hatch_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    schema_version: Mapped[int] = mapped_column(default=1)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "fuel_leak", "overheat"
    severity: Mapped[AlertSeverity] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    triggered_by: Mapped[dict | None] = mapped_column(  # feature values that caused this alert, for explainability
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Append-only per code-standards.md: resolution is recorded here, the
    # original alert row is never deleted or overwritten with new facts.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)

    # Populated asynchronously by the Web3 anchoring service. Null until anchored.
    onchain_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class Device(Base):
    """Per-truck MQTT device identity, per docs/hardware-integration-guide.md."""
    __tablename__ = "devices"

    truck_id: Mapped[str] = mapped_column(ForeignKey("trucks.truck_id"), primary_key=True)
    mqtt_username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
