from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.ai.rule_engine import ReadingContext, evaluate_reading, evaluate_status
from app.domain.geo import FenceHit
from app.mqtt.schemas import StatusPayload, TelemetryPayload

FENCE = SimpleNamespace(id="f1", name="Depot", lat=3.0, lon=11.0, radius_m=100)
INSIDE = FenceHit(fence=FENCE, distance_m=10)


def reading(valve_open=False, gps_fix=True, distance_cm=10.0):
    return SimpleNamespace(valve_open=valve_open, gps_fix=gps_fix, lat=3.0 if gps_fix else None,
                           lon=11.0 if gps_fix else None, distance_cm=distance_cm)


def ctx(inside=None, previous_inside=False, volume=None, prev_volume=None, capacity=None):
    return ReadingContext(volume_l=volume, previous_volume_l=prev_volume, capacity_l=capacity,
                          inside=inside, previous_inside=previous_inside, nearest=INSIDE)


def types(anomalies):
    return [a.type for a in anomalies]


def test_valve_open_inside_geofence_is_fine():
    assert evaluate_reading(reading(valve_open=True), reading(), ctx(inside=INSIDE)) == []


def test_valve_open_outside_geofence_alerts_once():
    first = evaluate_reading(reading(valve_open=True), reading(), ctx())
    assert types(first) == ["valve_open_outside_geofence"]
    assert first[0].severity == "critical"
    assert first[0].triggered_by["reason"] == "outside_geofence"
    assert first[0].triggered_by["nearest_geofence_name"] == "Depot"
    # Still open, still outside → no duplicate alert.
    assert evaluate_reading(reading(valve_open=True), reading(valve_open=True), ctx()) == []


def test_valve_open_without_gps_fix_alerts():
    a = evaluate_reading(reading(valve_open=True, gps_fix=False), reading(gps_fix=False), ctx())
    assert types(a) == ["valve_open_outside_geofence"]
    assert a[0].triggered_by["reason"] == "no_gps_fix"


def test_leaving_geofence_with_valve_open_alerts():
    a = evaluate_reading(reading(valve_open=True), reading(valve_open=True), ctx(previous_inside=True))
    assert a[0].triggered_by["reason"] == "left_geofence_with_valve_open"


def test_first_ever_reading_with_valve_open_outside_alerts():
    assert types(evaluate_reading(reading(valve_open=True), None, ctx())) == ["valve_open_outside_geofence"]


def test_volume_drop_with_valve_closed():
    # 15 L tank, 2% = 0.3 L allowed per reading.
    assert types(evaluate_reading(reading(), reading(), ctx(volume=9.0, prev_volume=10.0, capacity=15))) == [
        "volume_drop_valve_closed"]
    assert evaluate_reading(reading(), reading(), ctx(volume=9.9, prev_volume=10.0, capacity=15)) == []
    # Exactly at the limit is not a leak (13.5 - 13.2 is 0.30000000000000071 in floats).
    assert evaluate_reading(reading(), reading(), ctx(volume=13.2, prev_volume=13.5, capacity=15)) == []
    # Valve open: a drop is expected.
    assert evaluate_reading(reading(valve_open=True), reading(valve_open=True),
                            ctx(inside=INSIDE, volume=9.0, prev_volume=10.0, capacity=15)) == []


def test_gps_lost_and_no_echo_transitions():
    assert types(evaluate_reading(reading(gps_fix=False), reading(), ctx())) == ["gps_fix_lost"]
    assert types(evaluate_reading(reading(distance_cm=None), reading(), ctx())) == ["level_sensor_no_echo"]
    assert evaluate_reading(reading(gps_fix=False), reading(gps_fix=False), ctx()) == []


def test_device_offline_status():
    assert types(evaluate_status(True, False, unexpected=True)) == ["device_offline"]
    assert evaluate_status(True, False, unexpected=False) == []  # clean shutdown
    assert evaluate_status(False, False, unexpected=True) == []
    assert evaluate_status(False, True, unexpected=False) == []


VALID = {
    "schema_version": 2, "truck_id": "truck-001", "ts": "2026-10-16T10:32:05Z",
    "gps_fix": True, "lat": 3.848, "lon": 11.502, "speed_kmh": 42.5, "course_deg": 187.0,
    "sats": 8, "hdop": 1.1, "distance_cm": 37.4, "valve_open": False,
}


def test_valid_payload():
    assert TelemetryPayload.model_validate(VALID).valve_open is False


@pytest.mark.parametrize("change", [
    {"schema_version": 1},  # old schema
    {"temperature_c": 20.0},  # unknown field
    {"lat": None},  # fix without position
    {"gps_fix": False},  # position without fix
    {"ts": "2026-10-16T10:32:05"},  # no timezone
    {"distance_cm": 900},  # out of sensor range
    {"truck_id": "truck/001"},  # not topic-safe
])
def test_invalid_payloads_rejected(change):
    with pytest.raises(ValidationError):
        TelemetryPayload.model_validate({**VALID, **change})


def test_no_fix_payload():
    p = TelemetryPayload.model_validate({**VALID, "gps_fix": False, "lat": None, "lon": None, "speed_kmh": None,
                                         "course_deg": None, "hdop": None, "sats": 0})
    assert p.lat is None


def test_lwt_status_without_ts():
    s = StatusPayload.model_validate({"schema_version": 2, "truck_id": "truck-001", "online": False})
    assert s.ts is None
