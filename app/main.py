"""
FastAPI entrypoint. Wires together the REST API, WebSocket relay, MQTT
subscriber and Web3 anchoring queue via the app lifespan — this is the
only place all boundaries appear together.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, auth, discharges, geofences, reports, system, trucks, users
from app.config import settings
from app.mqtt.client import mqtt_subscriber
from app.services.bootstrap import ensure_admin
from app.web3.anchoring import anchoring_queue
from app.ws.routes import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("petrotwin.main")

DESCRIPTION = """
Backend of **PetroTwin**, the digital twin of a petrol tanker truck.

The truck is an **ESP32** with a **NEO-6M GPS**, an **HC-SR04 ultrasonic** level
sensor in the tank and an **FDP-270A solenoid valve**. It publishes telemetry over
MQTT; this service stores it, computes the tank volume, checks geofences, raises
alerts and serves the dashboard.

## Getting a token

1. `POST /auth/login` with your **email** in the `username` field and your password
   (or click **Authorize** above and log in there).
2. Send `Authorization: Bearer <access_token>` on every request.

There is no public sign-up: an admin creates accounts with `POST /users`. The very
first admin comes from the `ADMIN_EMAIL` / `ADMIN_PASSWORD` environment variables.

| Role | Can |
|---|---|
| `viewer` | See everything, export reports (except the audit log) |
| `operator` | + create/edit geofences, acknowledge alerts |
| `admin` | + manage users, register trucks, set tank calibration, export the audit log |

## The geofence rule

An admin/operator marks approved discharge locations on the map (`POST /geofences`:
a point and a radius). The valve may only open **inside an active geofence that
applies to the truck**. If the device reports `valve_open: true` anywhere else — or
without a GPS fix — a **critical `valve_open_outside_geofence` alert** is raised and
the discharge is recorded as unauthorized. The prototype's test button forces the
valve open to exercise exactly this path.

The system is **read-only towards the truck**: the ESP32 controls the valve
locally; this API never sends commands to the device.

## Live updates (WebSocket)

Connect to `wss://<host>/ws?token=<access_token>`. Every message is JSON:
`{"type": ..., "truck_id": ..., "data": {...}}`

| type | data |
|---|---|
| `truck.update` | same shape as `GET /trucks/{truck_id}` (after every telemetry/status message) |
| `alert.created` | same shape as `GET /alerts/{id}` |
| `alert.acknowledged` | same shape as `GET /alerts/{id}` |
| `discharge.started` / `discharge.ended` | same shape as `GET /discharges/{id}` |

## Device contract (MQTT)

Devices publish to `petrotwin/{truck_id}/telemetry` and `petrotwin/{truck_id}/status`
(QoS 1, schema v2). The full payload contract is in the repo at
`docs/hardware-integration-guide.md`.
"""

TAGS = [
    {"name": "Authentication", "description": "Log in with email + password and manage your own password."},
    {"name": "Users", "description": "Dashboard accounts and roles. **Admin only.**"},
    {"name": "Trucks", "description": "Registered trucks, their live state, tank calibration and telemetry history."},
    {"name": "Geofences", "description": "Approved discharge locations (point + radius) drawn on the map."},
    {"name": "Alerts", "description": "Rule-engine alerts (append-only) and their acknowledgements."},
    {"name": "Discharges", "description": "Valve open → close sessions: where, authorized or not, litres."},
    {"name": "Reports", "description": "Activity summary/timeline and CSV/JSON exports."},
    {"name": "System", "description": "Health check."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_admin()
    anchoring_queue.start()
    if settings.mqtt_enabled:
        mqtt_subscriber.start(asyncio.get_running_loop())
    if settings.jwt_secret == "change-me-in-production":
        logger.warning("JWT_SECRET is the default value — set a long random secret before deploying")
    logger.info("PetroTwin backend started")
    yield
    if settings.mqtt_enabled:
        mqtt_subscriber.stop()
    anchoring_queue.stop()
    logger.info("PetroTwin backend stopped")


app = FastAPI(
    title="PetroTwin API",
    version="2.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for module in (auth, users, trucks, geofences, alerts, discharges, reports, system):
    app.include_router(module.router)
app.include_router(ws_router)
