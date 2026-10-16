"""
Phase 1 anomaly detection: pure functions over telemetry, no DB/MQTT/WS
calls in this module (per docs/architecture.md's system boundaries).

`evaluate_reading` takes the current reading, the truck's previous reading
and the geofence context, and returns Anomaly objects for the orchestration
layer (app/services/ingestion.py) to persist and broadcast. It never
produces commands for the truck — monitoring only.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.domain.geo import FenceHit

RULES_PATH = Path(__file__).parent / "rules.yaml"

VALVE_OPEN_OUTSIDE_GEOFENCE = "valve_open_outside_geofence"
VOLUME_DROP_VALVE_CLOSED = "volume_drop_valve_closed"
GPS_FIX_LOST = "gps_fix_lost"
LEVEL_SENSOR_NO_ECHO = "level_sensor_no_echo"
DEVICE_OFFLINE = "device_offline"


class ReadingLike(Protocol):
    """Anything with these attributes: a validated payload, an ORM row, etc."""

    gps_fix: bool
    lat: float | None
    lon: float | None
    distance_cm: float | None
    valve_open: bool


@dataclass
class Anomaly:
    type: str
    severity: str
    message: str
    triggered_by: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReadingContext:
    """Derived values for the current reading, computed by the caller."""

    volume_l: float | None
    previous_volume_l: float | None
    capacity_l: float | None
    inside: FenceHit | None  # fence containing the current position
    previous_inside: bool  # was the previous reading inside a fence?
    nearest: FenceHit | None = None  # closest fence, for the alert explanation


def load_rules(path: Path = RULES_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# Loaded once at import; thresholds change by editing rules.yaml and
# restarting the service.
RULES = load_rules()


def evaluate_reading(
    current: ReadingLike,
    previous: ReadingLike | None,
    ctx: ReadingContext,
    rules: dict = RULES,
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []

    # --- Valve opened (or still open) outside an approved geofence ----------
    rule = rules.get(VALVE_OPEN_OUTSIDE_GEOFENCE)
    if rule and current.valve_open and ctx.inside is None:
        was_open_outside = previous is not None and previous.valve_open and not ctx.previous_inside
        if not was_open_outside:
            reason = "no_gps_fix" if not current.gps_fix else "outside_geofence"
            if previous is not None and previous.valve_open and ctx.previous_inside:
                reason = "left_geofence_with_valve_open"
            trig: dict[str, Any] = {
                "reason": reason,
                "valve_open": True,
                "gps_fix": current.gps_fix,
                "lat": current.lat,
                "lon": current.lon,
            }
            if ctx.nearest is not None:
                trig["nearest_geofence_id"] = str(ctx.nearest.fence.id)
                trig["nearest_geofence_name"] = ctx.nearest.fence.name
                trig["distance_to_nearest_m"] = round(ctx.nearest.distance_m, 1)
                trig["nearest_radius_m"] = ctx.nearest.fence.radius_m
            anomalies.append(Anomaly(VALVE_OPEN_OUTSIDE_GEOFENCE, rule["severity"], rule["message"], trig))

    if previous is None:
        return anomalies

    # --- Volume drop while the valve stayed closed --------------------------
    rule = rules.get(VOLUME_DROP_VALVE_CLOSED)
    if (
        rule
        and not current.valve_open
        and not previous.valve_open
        and ctx.volume_l is not None
        and ctx.previous_volume_l is not None
        and ctx.capacity_l
    ):
        # Volumes are stored to 0.01 L; round so float error (13.5 - 13.2 =
        # 0.30000000000000071) can't push a drop equal to the limit over it.
        drop_l = round(ctx.previous_volume_l - ctx.volume_l, 2)
        limit_l = round(ctx.capacity_l * rule["max_drop_pct_of_capacity"] / 100, 2)
        if drop_l > limit_l:
            anomalies.append(Anomaly(VOLUME_DROP_VALVE_CLOSED, rule["severity"], rule["message"], {
                "previous_volume_l": ctx.previous_volume_l,
                "current_volume_l": ctx.volume_l,
                "drop_l": round(drop_l, 2),
                "max_drop_l": round(limit_l, 2),
                "valve_open": False,
            }))

    # --- GPS fix lost -------------------------------------------------------
    rule = rules.get(GPS_FIX_LOST)
    if rule and previous.gps_fix and not current.gps_fix:
        anomalies.append(Anomaly(GPS_FIX_LOST, rule["severity"], rule["message"], {
            "last_lat": previous.lat,
            "last_lon": previous.lon,
        }))

    # --- Ultrasonic sensor stopped echoing ----------------------------------
    rule = rules.get(LEVEL_SENSOR_NO_ECHO)
    if rule and previous.distance_cm is not None and current.distance_cm is None:
        anomalies.append(Anomaly(LEVEL_SENSOR_NO_ECHO, rule["severity"], rule["message"], {
            "last_distance_cm": previous.distance_cm,
        }))

    return anomalies


def evaluate_status(was_online: bool, online: bool, unexpected: bool, rules: dict = RULES) -> list[Anomaly]:
    """Anomalies from a status message: an UNEXPECTED online → offline
    transition (the MQTT Last Will). A clean shutdown, where the device itself
    publishes `online: false`, is logged as activity but is not an alert."""
    rule = rules.get(DEVICE_OFFLINE)
    if rule and was_online and not online and unexpected:
        return [Anomaly(DEVICE_OFFLINE, rule["severity"], rule["message"], {"online": False, "source": "last_will"})]
    return []
