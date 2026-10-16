from datetime import UTC, datetime, timedelta

from app.mqtt.schemas import StatusPayload, TelemetryPayload
from app.services.ingestion import ingest_status, ingest_telemetry
from tests.conftest import ADMIN, login

DEPOT = (3.8667, 11.5167)
FAR = (3.8480, 11.5021)  # ~2.6 km from the depot
T0 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


# --- Auth & users -------------------------------------------------------------


async def test_endpoints_require_auth(client):
    for path in ("/trucks", "/alerts", "/geofences", "/reports/summary", "/users"):
        assert (await client.get(path)).status_code == 401, path
    assert (await client.get("/health")).status_code == 200


async def test_login_wrong_password(client):
    r = await client.post("/auth/login", data={"username": ADMIN[0], "password": "nope-nope"})
    assert r.status_code == 401


async def test_login_is_case_insensitive_on_email(client):
    await login(client, ADMIN[0].upper(), ADMIN[1])


async def test_roles(client, admin_headers):
    r = await client.post("/users", headers=admin_headers, json={
        "email": "viewer@example.com", "full_name": "Viewer", "password": "viewer-pass-1", "role": "viewer"})
    assert r.status_code == 201, r.text
    assert (await client.post("/users", headers=admin_headers, json={
        "email": "viewer@example.com", "full_name": "Dup", "password": "viewer-pass-1"})).status_code == 409

    viewer = await login(client, "viewer@example.com", "viewer-pass-1")
    assert (await client.get("/auth/me", headers=viewer)).json()["role"] == "viewer"
    assert (await client.get("/trucks", headers=viewer)).status_code == 200
    assert (await client.post("/geofences", headers=viewer, json={
        "name": "x", "lat": 1, "lon": 1, "radius_m": 10})).status_code == 403
    assert (await client.get("/users", headers=viewer)).status_code == 403
    assert (await client.get("/reports/export/audit", headers=viewer)).status_code == 403

    # Deactivated users can't log in.
    uid = r.json()["id"]
    await client.patch(f"/users/{uid}", headers=admin_headers, json={"is_active": False})
    assert (await client.post("/auth/login", data={"username": "viewer@example.com",
                                                   "password": "viewer-pass-1"})).status_code == 401


async def test_admin_cannot_demote_self(client, admin_headers):
    me = (await client.get("/auth/me", headers=admin_headers)).json()
    r = await client.patch(f"/users/{me['id']}", headers=admin_headers, json={"role": "viewer"})
    assert r.status_code == 400


async def test_change_own_password(client, admin_headers):
    await client.post("/users", headers=admin_headers, json={
        "email": "op@example.com", "full_name": "Op", "password": "op-pass-123", "role": "operator"})
    op = await login(client, "op@example.com", "op-pass-123")
    assert (await client.post("/auth/me/password", headers=op, json={
        "current_password": "wrong-pass", "new_password": "op-pass-456"})).status_code == 400
    assert (await client.post("/auth/me/password", headers=op, json={
        "current_password": "op-pass-123", "new_password": "op-pass-456"})).status_code == 204
    await login(client, "op@example.com", "op-pass-456")


# --- End-to-end ingestion: geofence, discharges, alerts, reports --------------


def telemetry(truck_id, ts, pos, valve_open=False, distance_cm=5.0, speed=0.0):
    lat, lon = pos if pos else (None, None)
    return TelemetryPayload.model_validate({
        "schema_version": 2, "truck_id": truck_id, "ts": ts.isoformat().replace("+00:00", "Z"),
        "gps_fix": pos is not None, "lat": lat, "lon": lon,
        "speed_kmh": speed if pos else None, "course_deg": 0.0 if pos else None,
        "sats": 8 if pos else 0, "hdop": 1.0 if pos else None,
        "distance_cm": distance_cm, "valve_open": valve_open,
    })


async def ingest(session, payload):
    result = await ingest_telemetry(session, payload)
    await session.commit()
    return result


async def test_full_flow(client, admin_headers, session):
    h = admin_headers
    assert (await client.post("/trucks", headers=h, json={"truck_id": "t-e2e", "plate": "CE 001 AA"})).status_code == 201
    r = await client.put("/trucks/t-e2e/tank", headers=h, json={
        "shape": "rectangular", "length_cm": 30, "width_cm": 20, "height_cm": 25, "sensor_offset_cm": 3})
    assert r.json()["capacity_l"] == 15.0
    assert (await client.put("/trucks/t-e2e/tank", headers=h, json={"shape": "rectangular"})).status_code == 422
    r = await client.post("/geofences", headers=h, json={
        "name": "Depot", "lat": DEPOT[0], "lon": DEPOT[1], "radius_m": 100, "truck_id": "t-e2e"})
    assert r.status_code == 201, r.text
    fence_id = r.json()["id"]

    chk = (await client.get("/geofences/check", headers=h,
                            params={"truck_id": "t-e2e", "lat": FAR[0], "lon": FAR[1]})).json()
    assert chk["inside"] is False and chk["nearest_distance_m"] > 2000

    # 1. Driving, valve closed. distance 4 cm → level 24 cm → 14.4 L
    res = await ingest(session, telemetry("t-e2e", T0, FAR, distance_cm=4.0, speed=50))
    assert res.accepted and res.telemetry.volume_l == 14.4 and res.alerts == []
    # Duplicate (QoS 1 re-delivery) is skipped.
    assert (await ingest(session, telemetry("t-e2e", T0, FAR, distance_cm=4.0))).reason == "duplicate"

    # 2. Test button: valve forced open far from the depot → critical alert + unauthorized discharge.
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(seconds=3), FAR, valve_open=True, distance_cm=4.5))
    assert [a.type for a in res.alerts] == ["valve_open_outside_geofence"]
    assert res.discharge_started is not None and res.discharge_started.authorized is False
    # Still open → no second alert.
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(seconds=6), FAR, valve_open=True, distance_cm=5.0))
    assert res.alerts == []
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(seconds=9), FAR, valve_open=False, distance_cm=5.0))
    assert res.discharge_ended is not None and res.discharge_ended.litres == 0.3  # 14.1 L → 13.8 L

    # 3. At the depot: authorized discharge, no alert.
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(minutes=5), DEPOT, distance_cm=5.0))
    assert res.telemetry.geofence_id is not None and res.alerts == []
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(minutes=5, seconds=3), DEPOT, valve_open=True,
                                          distance_cm=10.0))
    assert res.alerts == [] and res.discharge_started.authorized is True
    assert str(res.discharge_started.geofence_id) == fence_id
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(minutes=5, seconds=6), DEPOT, distance_cm=20.0))
    assert res.discharge_ended.litres == 6.0  # opened at 10 cm (10.8 L), closed at 20 cm (4.8 L)

    # 4. Leak while parked: volume drops with the valve closed → one warning (cooldown).
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(minutes=6), DEPOT, distance_cm=22.0))
    assert [a.type for a in res.alerts] == ["volume_drop_valve_closed"]
    res = await ingest(session, telemetry("t-e2e", T0 + timedelta(minutes=6, seconds=3), DEPOT, distance_cm=24.0))
    assert res.alerts == []

    # 5. Device drops off (LWT).
    _, alerts = await ingest_status(session, StatusPayload.model_validate(
        {"schema_version": 2, "truck_id": "t-e2e", "online": False}))
    await session.commit()
    assert [a.type for a in alerts] == ["device_offline"]

    # --- Read it back through the API ---
    truck = (await client.get("/trucks/t-e2e", headers=h)).json()
    assert truck["online"] is False and truck["activity"] == "offline"
    assert truck["capacity_l"] == 15.0 and truck["latest"]["volume_l"] == 2.4
    assert truck["open_alerts"] == 3

    discharges = (await client.get("/discharges", headers=h, params={"truck_id": "t-e2e"})).json()
    assert [d["authorized"] for d in discharges] == [True, False]
    assert discharges[0]["litres"] == 6.0

    alerts = (await client.get("/alerts", headers=h, params={"truck_id": "t-e2e", "severity": "critical"})).json()
    assert len(alerts) == 1 and alerts[0]["digest"]
    aid = alerts[0]["id"]
    r = await client.post(f"/alerts/{aid}/acknowledge", headers=h, json={"note": "Test button at the yard"})
    assert r.status_code == 201 and r.json()["acknowledgement"]["note"] == "Test button at the yard"
    assert (await client.post(f"/alerts/{aid}/acknowledge", headers=h, json={})).status_code == 409

    summary = (await client.get("/reports/summary", headers=h, params={"truck_id": "t-e2e"})).json()
    assert summary["discharges_total"] == 2 and summary["discharges_unauthorized"] == 1
    assert summary["litres_discharged"] == 6.3
    assert summary["alerts_by_type"]["valve_open_outside_geofence"] == 1
    assert summary["alerts_unacknowledged"] == 2

    activity = (await client.get("/reports/activity", headers=h, params={"truck_id": "t-e2e"})).json()
    events = [e["event"] for e in activity]
    assert "discharge.opened" in events and "alert.acknowledged" in events and "device.offline" in events

    r = await client.get("/reports/export/discharges", headers=h, params={"truck_id": "t-e2e", "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.lstrip("﻿").splitlines()[0].startswith("id,truck_id,opened_at")
    r = await client.get("/reports/export/telemetry", headers=h, params={"truck_id": "t-e2e", "format": "json"})
    assert len(r.json()) == 9

    tel = (await client.get("/trucks/t-e2e/telemetry", headers=h, params={"order": "asc", "limit": 2})).json()
    assert tel[0]["volume_l"] == 14.4


async def test_unknown_geofence_truck_rejected(client, admin_headers):
    r = await client.post("/geofences", headers=admin_headers, json={
        "name": "x", "lat": 1, "lon": 1, "radius_m": 10, "truck_id": "nope"})
    assert r.status_code == 422


async def test_geofence_deactivate_and_reactivate(client, admin_headers):
    h = admin_headers
    fid = (await client.post("/geofences", headers=h, json={"name": "Tmp", "lat": 1, "lon": 1,
                                                            "radius_m": 10})).json()["id"]
    assert (await client.delete(f"/geofences/{fid}", headers=h)).json()["is_active"] is False
    assert fid not in [f["id"] for f in (await client.get("/geofences", headers=h)).json()]
    assert (await client.patch(f"/geofences/{fid}", headers=h, json={"is_active": True})).json()["is_active"]


async def test_openapi_documents_security(client):
    spec = (await client.get("/openapi.json")).json()
    assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]
    assert spec["paths"]["/geofences"]["post"]["description"]
