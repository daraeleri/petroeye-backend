"""
Phase 1 anomaly detection: pure functions over telemetry, no DB/MQTT/WS
calls in this module (per docs/architecture.md's system boundaries).
Given a reading (and optionally the previous one), returns a list of
Anomaly objects for the orchestration layer (app/mqtt/handlers.py) to
persist and broadcast.

Phase 2 (ML-based scoring) will live in app/ai/ml_model.py alongside this,
behind the same evaluate_reading-style interface — not started yet, see
docs/progress-tracker.md Open Questions.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.mqtt.schemas import TelemetryPayload

RULES_PATH = Path(__file__).parent / "rules.yaml"

_OPS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "eq": lambda a, b: a == b,
}


@dataclass
class Anomaly:
    type: str
    severity: str
    message: str
    triggered_by: dict[str, Any]


def _load_rules() -> dict:
    with open(RULES_PATH) as f:
        return yaml.safe_load(f)


# Loaded once at import time. If you need hot-reload during rule tuning,
# call _load_rules() again explicitly rather than caching indefinitely —
# not implemented yet since Phase 1 rules are expected to be edited and
# the service restarted, not live-reloaded, for now.
_RULES = _load_rules()


def evaluate_reading(current: TelemetryPayload, previous: Any | None) -> list[Anomaly]:
    # `previous` is typed loosely (Any) because callers may pass either a
    # TelemetryPayload or a Telemetry ORM row — both expose the same
    # sensor fields by attribute name, which is all this function needs.
    anomalies: list[Anomaly] = []

    for rule in _RULES.get("static_rules", []):
        field_value = getattr(current, rule["field"])
        op = _OPS[rule["op"]]
        if op(field_value, rule["threshold"]):
            anomalies.append(Anomaly(
                type=rule["type"],
                severity=rule["severity"],
                message=rule["message"],
                triggered_by={rule["field"]: field_value, "threshold": rule["threshold"]},
            ))

    if previous is not None:
        fuel_rule = _RULES.get("fuel_drop_rule")
        if fuel_rule:
            drop = previous.fuel_level_pct - current.fuel_level_pct
            if drop > fuel_rule["max_drop_pct_per_reading"]:
                anomalies.append(Anomaly(
                    type=fuel_rule["type"],
                    severity=fuel_rule["severity"],
                    message=fuel_rule["message"],
                    triggered_by={
                        "fuel_drop_pct": round(drop, 3),
                        "max_allowed": fuel_rule["max_drop_pct_per_reading"],
                        "previous_fuel_pct": previous.fuel_level_pct,
                        "current_fuel_pct": current.fuel_level_pct,
                    },
                ))

    return anomalies
