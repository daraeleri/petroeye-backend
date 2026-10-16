# Architecture Context

## Stack

| Layer          | Technology                              | Role |
| -------------- | ---------------------------------------- | ---- |
| Backend        | FastAPI (Python 3.11, async), SQLAlchemy 2 + Alembic, paho-mqtt 2 | REST + WebSocket API, MQTT ingestion, rule engine, reports, anchoring queue |
| Auth           | Email + password (bcrypt), JWT bearer tokens | Dashboard login, roles admin/operator/viewer |
| Device         | ESP32 firmware (planned: PlatformIO, `firmware/`) | Reads NEO-6M GPS + HC-SR04 ultrasonic, drives the FDP-270A valve locally, publishes MQTT |
| Protocol       | MQTT (QoS 1) — Mosquitto locally, managed broker in staging | Truck sensor unit → backend telemetry transport (one direction only) |
| Frontend       | Next.js + TypeScript                     | Digital twin dashboard, fleet views, alert feed |
| UI             | Tailwind CSS + shadcn/ui + recharts      | HUD, charts, alert cards |
| Database       | Postgres (plain; TimescaleDB optional, not required) | Telemetry history + relational fleet/alert/tank-calibration data |
| Realtime relay | In-process WebSocket broadcast (single backend instance) | Bridges MQTT-ingested events to connected dashboard clients |
| AI (Phase 1)   | Rule engine (pure Python, versioned config) | Threshold-based anomaly detection |
| AI (Phase 2)   | scikit-learn / PyTorch model service     | Learned anomaly scoring over rolling telemetry windows |
| Web3           | Solidity contract + web3.py, public testnet (e.g. Polygon Amoy) | Immutable audit anchoring, smart-contract-triggered alerts |
| Simulation     | Python (paho-mqtt)                       | Synthetic truck publishers for dev/test without hardware |

## Hardware Sensing Model

Besides the ESP32, the prototype truck has exactly three devices (see `hardware-integration-guide.md` §0):

| Device | Raw signal sent | Derived on the backend |
| ------ | --------------- | ---------------------- |
| NEO-6M GPS | fix, lat/lon, speed, course, sats, hdop | position on the map, moving/parked, which geofence the truck is in |
| HC-SR04 ultrasonic | `distance_cm` (median of 5 pings) | liquid level → volume (L) via the truck's tank calibration |
| FDP-270A solenoid valve | `valve_open` (state only) | discharge events (start/end, litres discharged, location) |

The device sends raw measurements; all unit conversion and calibration happen on the backend, so tank geometry can change without a firmware reflash. Alert logic combines these signals (e.g. volume falling while the valve is closed = possible leak/theft; valve opened outside an approved geofence = unauthorised discharge).

## Deployment (free tiers — `render.yaml`)

| Piece | Host | Notes |
| ----- | ---- | ----- |
| Frontend | Vercel | Talks only to the backend over HTTPS + WSS. |
| Backend (FastAPI + MQTT subscriber) | Render free web service | Sleeps after ~15 min without HTTP traffic → kept awake by an external `/health` pinger; single instance. |
| MQTT broker | EMQX Cloud Serverless (free quota: 1M session-minutes + 1 GB traffic per month, TLS 8883) | Render can't host a broker (HTTP only). Spend limit 0 → the deployment pauses instead of billing if the quota runs out. |
| Database | Neon (project petroEye, AWS us-east-1) | Render's free Postgres expires, so it isn't used. |

Local development keeps `docker-compose.yml` (Mosquitto + Postgres).

## Ingestion Pipeline

For every telemetry message (`app/services/ingestion.py`, one asyncio lock per truck so readings are processed in order):

1. **Validate** (`app/mqtt/schemas.py`, on paho's thread): schema v2, unknown fields rejected, body `truck_id` must match the topic. Invalid messages are logged and dropped.
2. **Register** the truck if unknown and `AUTO_REGISTER_TRUCKS=true`; otherwise reject.
3. **De-duplicate** on `(truck_id, ts)` (QoS 1 can redeliver). Out-of-order readings are stored but don't drive state transitions.
4. **Derive** level/volume from the tank calibration (`app/domain/tank.py`) and the containing geofence (`app/domain/geo.py`).
5. **Evaluate rules** (`app/ai/rule_engine.py` + `rules.yaml`) against the previous reading. Rules fire on transitions, with an optional per-rule cooldown.
6. **Track discharges**: valve closed→open starts a `discharges` row (authorized = inside a geofence), open→closed ends it with litres.
7. **Commit**, then broadcast `truck.update`, `alert.created`, `discharge.started/ended` over the WebSocket and queue critical alerts for anchoring.

Status messages update connectivity. An `online:false` **without** `ts` is the MQTT Last Will → `device_offline` alert; with `ts` it's a clean shutdown → activity log only.

## Alert Rules

| Type | Severity | Fires when |
| ---- | -------- | ---------- |
| `valve_open_outside_geofence` | critical | Valve becomes open while not inside an active geofence for the truck (or with no GPS fix), or the truck leaves the geofence with the valve open. A GPS dropout *during* a discharge that started inside a geofence keeps the last known geofence (no alert); if the fix returns outside with the valve still open, it alerts as `left_geofence_with_valve_open`. |
| `volume_drop_valve_closed` | warning | Volume falls by more than 2% of capacity between two readings with the valve closed (provisional threshold; 10-min cooldown) |
| `level_sensor_no_echo` | warning | `distance_cm` goes from a value to `null` |
| `device_offline` | warning | MQTT Last Will received |
| `gps_fix_lost` | info | `gps_fix` goes true → false |

## REST API (summary — full docs at `/docs`)

| Area | Endpoints | Who |
| ---- | --------- | --- |
| Auth | `POST /auth/login` (form: email in `username`), `GET /auth/me`, `POST /auth/me/password` | everyone |
| Users | `GET/POST /users`, `GET/PATCH /users/{id}` | admin |
| Trucks | `GET /trucks`, `GET /trucks/{id}`, `GET /trucks/{id}/telemetry`, `GET /trucks/{id}/tank` | everyone |
| | `POST /trucks`, `PATCH /trucks/{id}`, `PUT /trucks/{id}/tank` | admin |
| Geofences | `GET /geofences`, `GET /geofences/{id}`, `GET /geofences/check` | everyone |
| | `POST /geofences`, `PATCH/DELETE /geofences/{id}` (DELETE = deactivate) | operator, admin |
| Alerts | `GET /alerts`, `GET /alerts/{id}` | everyone |
| | `POST /alerts/{id}/acknowledge` | operator, admin |
| Discharges | `GET /discharges`, `GET /discharges/{id}` | everyone |
| Reports | `GET /reports/summary`, `GET /reports/activity`, `GET /reports/export/{activity,discharges,alerts,telemetry}` | everyone |
| | `GET /reports/export/audit` | admin |
| System | `GET /health` | no auth |
| Live | `WS /ws?token=<JWT>` | everyone |

## System Boundaries

- `app/mqtt/` — MQTT client lifecycle, topic subscription, payload validation. Never touches HTTP routing directly.
- `app/api/` — REST endpoints and auth dependencies. Reads/writes the DB through `app/services/`; no MQTT client code here.
- `app/services/` — orchestration: `ingestion.py` (MQTT → DB → rules → WS), `fleet.py` (truck snapshots), `alerts.py`, `reports.py`, `audit.py`, `bootstrap.py` (first admin).
- `app/domain/` — pure maths: geofence distance/containment, tank level/volume. No I/O.
- `app/ws/` — WebSocket connection manager, broadcasts normalized events to subscribed dashboard clients.
- `app/ai/` — `rule_engine.py` (Phase 1) and `ml_model.py` (Phase 2). Pure functions over telemetry in, `Anomaly` objects out. No DB or MQTT calls inside these modules — orchestration happens one layer up.
- `app/web3/` — contract client, event anchoring queue/worker. Anchoring is async and never blocks the ingestion path.
- `app/db/` — SQLAlchemy models. Schema changes via Alembic (`migrations/`).
- **Frontend (separate repo, Vercel)** — the Next.js dashboard. Consumes only this service's REST + WebSocket API; never talks to MQTT, the database or a blockchain directly. Its layout and UI rules live in that repo's `docs/`.
- `firmware/` — **(planned; which repo is still open)** ESP32 firmware. Publishes exactly the schema in `hardware-integration-guide.md` and owns all valve logic.
- `simulation/` — independent of the production backend; talks to the MQTT broker exactly like a real truck would.
- `contracts/` — **(planned)** Solidity source + ABI, deployment scripts.

## Storage Model

- **`telemetry`**: `truck_id, ts, received_at, gps_fix, lat, lon, speed_kmh, course_deg, sats, hdop, distance_cm, valve_open, schema_version` (raw) + `level_cm, volume_l, geofence_id` (derived at ingest). Unique on `(truck_id, ts)`. Source of truth for sensor history.
- **`trucks`**: `truck_id` (the MQTT topic ID), plate, driver_name, notes, connectivity (`online`, `last_seen_at`, firmware, RSSI, uptime). Activity (`offline/parked/moving/discharging`) is derived, not stored.
- **`tank_calibrations`**: one per truck — shape (`rectangular`, `vertical_cylinder`, `horizontal_cylinder`), inner dimensions, `sensor_offset_cm`. Applies to readings received after it's set.
- **`geofences`**: name, centre lat/lon, `radius_m`, optional `truck_id` (null = all trucks), `is_active`. Deactivated, never deleted.
- **`discharges`**: valve sessions — opened/closed at, positions, `geofence_id`, `authorized`, volume start/end, `litres`, linked alert.
- **`alerts`** (append-only): type, severity, message, `triggered_by` (explainability), position, `digest` (SHA-256 for anchoring), `onchain_tx_hash`. **`alert_acknowledgements`**: one per alert, user + note.
- **`users`**: email (unique, lower-case), bcrypt hash, role, `is_active`. Never deleted.
- **`audit_log`**: user actions (logins, user/truck/geofence/calibration changes, acknowledgements, exports) and device online/offline events. Feeds the activity report.
- **On-chain**: only a hash digest of the alert/event payload + `alert_id` + timestamp is anchored — never raw telemetry or PII. This keeps gas costs low and avoids putting sensitive operational data on a public chain.

## Auth and Access Model

- **Dashboard users**: email + password (bcrypt) → JWT bearer token (`ACCESS_TOKEN_MINUTES`, default 12 h). No public sign-up: admins create users; the first admin comes from `ADMIN_EMAIL`/`ADMIN_PASSWORD` on an empty database. Roles: `viewer` (read + export), `operator` (+ geofences, acknowledge alerts), `admin` (+ users, trucks, tank calibration, audit export). The WebSocket takes the token as `?token=`.
- **Truck devices**: per-device MQTT username/password managed on the broker (EMQX deployment → Access Control → Authentication), issued and revocable per truck, never shared across trucks. With `AUTO_REGISTER_TRUCKS=false` the backend also ignores trucks not registered via the API.
- **Blockchain writes**: signed by a single backend-held anchoring service key (never a user key); this key is never committed to the repo — see Invariants.

## Invariants

- The MQTT subscriber must run as its own asyncio task/thread and must never block the FastAPI event loop.
- The telemetry write path must be idempotent (safe to reprocess the same message without duplicating rows).
- Raw telemetry is never sent to the blockchain — only hashed digests of alert/event records.
- The AI module (rule engine or ML) is **read-only monitoring**; it must never issue commands back to the truck. Any future actuation feature is a separate, explicitly-scoped effort.
- The whole software stack is **read-only towards the truck**. The solenoid valve is controlled locally by the ESP32; the backend never publishes to device topics, and the dashboard only displays the reported `valve_open` state. (Decided 2026-10-16.)
- Frontend components never connect to MQTT or the blockchain directly — everything flows through the backend's REST/WebSocket API.
- Blockchain anchoring is asynchronous/queued (e.g. background task or worker); a failed or slow chain write must never delay ingestion or dashboard updates.
- Contract addresses and ABI, once deployed, are treated as protected (see `ai-workflow-rules.md`) — redeploying changes the source of truth for all anchored history.
- The 3D truck view in the frontend repo, if built, is strictly additive: the 2D dashboard must remain the default, fully functional path with or without the 3D view present. No dashboard feature (alerts, gauges, history) may be built to depend on the 3D view existing.
