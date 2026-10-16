# Architecture Context

## Stack

| Layer          | Technology                              | Role |
| -------------- | ---------------------------------------- | ---- |
| Backend        | FastAPI (Python, async)                  | REST + WebSocket API, MQTT subscriber orchestration, rule engine, anchoring service |
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
| NEO-6M GPS | fix, lat/lon, speed, course, sats, hdop | trips, stops, geofence entry/exit, route deviation |
| HC-SR04 ultrasonic | `distance_cm` (median of 5 pings) | liquid level → volume (L) via the truck's tank calibration |
| FDP-270A solenoid valve | `valve_open` (state only) | discharge events (start/end, litres discharged, location) |

The device sends raw measurements; all unit conversion and calibration happen on the backend, so tank geometry can change without a firmware reflash. Alert logic combines these signals (e.g. volume falling while the valve is closed = possible leak/theft; valve opened outside an approved delivery zone = unauthorised discharge).

## Deployment (target — free tiers)

| Piece | Host | Notes |
| ----- | ---- | ----- |
| Frontend | Vercel | Talks only to the backend over HTTPS + WSS. |
| Backend (FastAPI + MQTT subscriber) | Render free web service | Sleeps after ~15 min without HTTP traffic → kept awake by an external `/health` pinger; single instance. |
| MQTT broker | Managed broker — proposed: HiveMQ Cloud Serverless (free, TLS 8883) | Render can't host a broker (HTTP only). Pending confirmation, see `progress-tracker.md`. |
| Database | Managed Postgres — proposed: Neon free tier | Render's free Postgres expires, so it isn't used. Pending confirmation. |

Local development keeps `docker-compose.yml` (Mosquitto + Postgres).

## System Boundaries

- `app/mqtt/` — MQTT client lifecycle, topic subscription, payload validation. Never touches HTTP routing directly.
- `app/api/` — REST endpoints (trucks, alerts, history). Strictly reads from DB / writes commands; no MQTT client code here.
- `app/ws/` — WebSocket connection manager, broadcasts normalized events to subscribed dashboard clients.
- `app/ai/` — `rule_engine.py` (Phase 1) and `ml_model.py` (Phase 2). Pure functions over telemetry in, `Anomaly` objects out. No DB or MQTT calls inside these modules — orchestration happens one layer up.
- `app/web3/` — contract client, event anchoring queue/worker. Anchoring is async and never blocks the ingestion path.
- `app/db/` — SQLAlchemy models, Alembic migrations.
- **Frontend (separate repo, Vercel)** — the Next.js dashboard. Consumes only this service's REST + WebSocket API; never talks to MQTT, the database or a blockchain directly. Its layout and UI rules live in that repo's `docs/`.
- `firmware/` — **(planned; which repo is still open)** ESP32 firmware. Publishes exactly the schema in `hardware-integration-guide.md` and owns all valve logic.
- `simulation/` — independent of the production backend; talks to the MQTT broker exactly like a real truck would.
- `contracts/` — **(planned)** Solidity source + ABI, deployment scripts.

## Storage Model

- **`telemetry` table** (schema v2, target): `truck_id, ts, gps_fix, lat, lon, speed_kmh, course_deg, sats, hdop, distance_cm, valve_open, level_cm, volume_l, schema_version`, unique on `(truck_id, ts)`. `level_cm`/`volume_l` are computed at ingest from the truck's calibration. Source of truth for all sensor history. (The current code still stores the v1 columns until the ingestion rewrite lands.)
- **Postgres relational tables**: `trucks` (id, plate, status, operator), `tank_calibrations` (truck_id, shape, inner dimensions, sensor mounting offset, effective_from), `alerts` (id, truck_id, type, severity, created_at, resolved_at, resolution_note, onchain_tx_hash), `users` (auth), `devices` (per-truck MQTT credentials/cert refs).
- **On-chain**: only a hash digest of the alert/event payload + `alert_id` + timestamp is anchored — never raw telemetry or PII. This keeps gas costs low and avoids putting sensitive operational data on a public chain.

## Auth and Access Model

- **Dashboard users**: JWT-based auth, roles `admin`, `operator`, `viewer`.
- **Truck devices**: per-device MQTT username/password (or client cert in later hardening pass), issued and revocable per truck, never shared across trucks.
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
