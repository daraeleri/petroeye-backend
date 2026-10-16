# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- **Remake around the real hardware** (started 2026-10-16). The v1 stack below was built for sensors the prototype doesn't have (temperature, pressure, tilt, flow, hatch). The real truck has an ESP32 with a NEO-6M GPS, an HC-SR04 ultrasonic level sensor and an FDP-270A solenoid valve.

## Current Goal

- Backend v2 is built and verified (2026-10-16). Next: frontend on the new API (login, map with geofences, valve/volume twin, alerts, reports), then the ESP32 firmware, then deploy.
- **API break for the frontend:** every REST call now needs `Authorization: Bearer <token>` and the WebSocket needs `?token=`. Response shapes changed completely (see "API changes for the frontend" below). The frontend repo still speaks v1.

## Remake Plan (in order, one boundary per step)

1. ~~Repo hygiene~~ — done 2026-10-16 as part of the repo split.
2. ~~Backend MQTT ingestion → v2, TLS, resilient startup~~ — done 2026-10-16.
3. ~~DB → v2 schema, `tank_calibrations`, unique `(truck_id, ts)`, Alembic~~ — done 2026-10-16.
4. ~~Rule engine → geofence valve rule, leak/theft, GPS lost, no echo, device offline; transition-based + cooldown~~ — done 2026-10-16.
5. ~~Simulator → v2 payloads and scenarios~~ — done 2026-10-16 (+ `seed_demo.py`).
6. ~~Frontend → login, map with geofence drawing, tank/valve/GPS twin, alerts, reports~~ — rebuilt 2026-10-16 (frontend repo); Vercel deploy pending.
7. Firmware → `firmware/` PlatformIO project for the ESP32 (incl. the test button).
8. Deployment → ~~Neon~~ (done 2026-10-16), ~~EMQX Cloud Serverless (MQTT)~~ (done 2026-10-16), ~~Render~~ (done 2026-10-16, https://petroeye-backend.onrender.com), `/health` keep-alive pinger, ~~Vercel~~ (done 2026-10-16, https://petroeye-frontend.vercel.app).

## API changes for the frontend (2026-10-16)

- **Auth:** `POST /auth/login` (form-encoded `username`=email, `password`) → `{access_token, expires_in, user}`. Send the token on every request; 401 → back to login. `GET /auth/me` for the current user and role.
- **Trucks:** `GET /trucks` returns `TruckOut` = identity + `online`, `activity` (`offline|parked|moving|discharging`), `open_alerts`, `capacity_l`, `fill_pct`, `latest` (gps_fix, lat, lon, speed_kmh, course_deg, sats, hdop, distance_cm, level_cm, volume_l, valve_open, geofence_id). Old v1 fields (fuel/temperature/pressure/tilt/flow/hatch) are gone.
- **New resources:** `/geofences` (+ `/geofences/check`), `/discharges`, `/alerts/{id}/acknowledge`, `/reports/summary`, `/reports/activity`, `/reports/export/{kind}?format=csv|json`, `/users` (admin), `/trucks/{id}/tank`.
- **WebSocket** `/ws?token=…` messages: `truck.update` (TruckOut), `alert.created`, `alert.acknowledged` (AlertOut), `discharge.started`, `discharge.ended` (DischargeOut).
- Role-based UI: hide geofence editing/acknowledge for `viewer`, user management for non-admins.

## Completed

### Backend v2 — Built and verified (2026-10-16)
- **Auth**: email + password (bcrypt), JWT bearer, roles admin/operator/viewer, first admin from env, admin user management, change own password, WebSocket token auth.
- **Ingestion** (`app/services/ingestion.py`): schema v2 validation (extra fields rejected), auto-register (configurable), idempotent on `(truck_id, ts)`, per-truck ordering lock, tank level/volume from calibration, geofence containment, rule evaluation, discharge sessions, WebSocket broadcast after commit, critical alerts queued for anchoring.
- **MQTT client**: paho v2 API, TLS (certifi), `connect_async` + auto-reconnect (broker down at startup no longer crashes the app), persistent session (`clean_session=False`, stable client ID), QoS 1.
- **Geofences**: point + radius, per-truck or fleet-wide, deactivate instead of delete, `/geofences/check`.
- **Rules** (`rules.yaml` v2): `valve_open_outside_geofence` (critical), `volume_drop_valve_closed` (warning, provisional 2%, 10-min cooldown), `level_sensor_no_echo`, `device_offline` (Last Will only), `gps_fix_lost`. All transition-based.
- **Reports**: summary, activity timeline (discharges, alerts, acks, device + user events), CSV/JSON export of activity/discharges/alerts/telemetry/audit; every export is audited.
- **DB**: 9 tables, Alembic initial migration `552c2a705a9a`; new local database `petroeye` (old v1 data left untouched in `petrotwin`).
- **Swagger**: overview with login steps, roles table, geofence rule, WebSocket events, MQTT pointer; every endpoint has a summary, description, examples and documented error codes; **Authorize** button logs in with email/password.
- **Deploy**: `render.yaml` (free plan, migrations on start, `/health` check), `.env.example` documents every setting incl. Neon/EMQX.
- **Tests**: 35 pytest tests (domain maths, rules, payload validation, auth/roles, full ingestion → discharges → alerts → reports flow) on SQLite.
- **Verified live** against local Postgres 18 + Mosquitto: seeded via API; simulator delivery → authorized discharge, forced opening 1.26 km from the depot → critical alert + unauthorized discharge, leak → one warning, abrupt disconnect → `device_offline`; WebSocket rejects missing token and streams `truck.update` with one.

### Backend v1 (2026-07-20) — superseded by v2

(historical — v1 sensors, no longer in the code)
- **Infrastructure**: `docker-compose.yml` with Mosquitto broker (1883) + TimescaleDB (5432). Verified containers reachable.
- **FastAPI async MQTT subscriber**: `app/mqtt/client.py` — paho-mqtt on background thread, dispatches to async handlers via `asyncio.run_coroutine_threadsafe`. Subscribes to `petrotwin/+/telemetry` and `petrotwin/+/status`.
- **DB schema**: `Telemetry`, `Truck`, `Alert`, `Device` SQLAlchemy models (async, asyncpg). Tables auto-created via `init_db()`.
- **Phase 1 rule engine**: `rules.yaml`-driven thresholds (temp > 60°C, tilt > 25°, fuel < 5%, hatch open, fuel drop rate > 0.4%/reading). Verified: `fuel_leak` scenario produces `critical` alerts.
- **REST endpoints**: `GET /trucks`, `GET /trucks/{id}`, `GET /trucks/{id}/telemetry`, `GET /alerts` — returning real data from Postgres.
- **WebSocket relay**: `/ws` endpoint + `ConnectionManager` broadcasting telemetry/status/alert events.
- **Web3 anchoring stub**: `app/web3/anchoring.py` — async queued worker logging what it would anchor.
- **Truck simulator**: `simulation/truck_simulator.py` (7 scenarios + LWT), `fleet_runner.py`. Publishing confirmed against live broker.

### Frontend — Dashboard (2026-07-20, frontend repo, v1 API)
- **Scaffold**: Next.js 15 + TypeScript strict mode, Tailwind v4 with PetroTwin design tokens (CSS variables from `docs/ui-context.md`), shadcn/ui primitives (button, card, dialog, badge). `npm run build` passes with zero errors.
- **4 reusable HUD components** in `frontend/components/hud/`:
  - `RadialGauge` — SVG 270° arc, color transitions safe→warning→critical via thresholds. Mono value + unit centered.
  - `PanelFrame` — corner-bracket framing, uppercase letter-spaced header with gradient underline. `active` prop brightens borders.
  - `GlowBackdrop` — CSS radial-gradient ellipse for hero visual underglow.
  - `TimelineScrubber` — horizontal track with draggable playhead, time labels, alert markers.
- **Typed data layer** in `frontend/lib/`:
  - `types.ts` — shared TS types mirroring backend Pydantic shapes.
  - `api.ts` — typed REST fetchers (`fetchTrucks`, `fetchTelemetry`, `fetchAlerts`).
  - `ws.ts` — WebSocket client class with auto-reconnect.
  - `DashboardContext.tsx` — React Context + Provider: WS lifecycle, per-truck telemetry (bounded 200), alert cache, selected truck state.
- **TruckList** — status dot + truck_id + relative last_seen. Click selects truck (updates center panel). Detail button opens slide-in panel. Reused in FleetView.
- **TruckSchematic** — loads `truck-schematic.svg`, reads hotspot positions via DOM, overlays SensorBadge components at hotspot coordinates.
- **SensorBadge** — floating badge with severity-colored border glow at each hotspot (fuel %, temp °C, tilt °, GPS coords, hatch open/closed).
- **SeverityDonut** — standalone SVG donut chart (3 arcs) for alarm severity aggregation. Reused in AlertsView.
- **AlertFeed** — (legacy, kept for reference) — replaced by per-view alert components.
- **TruckDetailPanel** — slide-in panel with full sensor readout table + recent alerts for selected truck.
- **twin-3d/Placeholder** — "3D — Coming Soon" toggle button (additive, Phase 2+).
- **Modals**: shadcn Dialog with backdrop-blur (stub ready for alert resolution + device auth).

### Frontend — UI Redesign (2026-07-20)
- **Sidebar** (`Sidebar.tsx`) — persistent left nav (w-14) replacing old HeaderNav. Icon buttons for Dashboard, Live Map, Fleet, Analytics, Energy, Alerts. Active tab indicator bar, alert count badge on Alerts tab, LIVE indicator with pulse dot + timestamp at bottom. Brand mark (PT logo). Type: `SidebarTabId` union.
- **page.tsx refactored** — flex row layout: Sidebar + content area. Tab-based view switching via `useState<SidebarTabId>`. Six view components rendered conditionally. Alert count and online count derived from DashboardContext.
- **DashboardView** — complete redesign with three-column layout:
  - *Top KPI bar*: Welcome greeting + 4 MiniStat pills (Active Trucks, Est. Daily Revenue, Avg Utilization, Total Volume).
  - *Left floating panel* (w-64): Key Indicators (revenue, utilization with gradient progress bar), Fleet Capacity (max/current/adjustable), Core Telemetry (4x RadialGauges: fuel, temp, pressure, tilt), Battery SOH Trend mini line chart.
  - *Center*: GlowBackdrop + TruckSchematic (or placeholder when no truck selected). Fleet grid overlay (4-column, 2-row truck buttons with status dots) at the bottom — click to select.
  - *Right floating panel* (w-64): System Status (health score 92/100 with mini line chart, online rate, communications %, fire system anomaly badge), Alarm Summary (PieChart donut with Critical/Warning/Info legend), Equipment Status (total/online/offline/alert counts, comm stability, health avg).
  - *Bottom*: TimelineScrubber in themed bar.
- **AnalyticsView** (new) — real-time monitoring with two-row grid layout:
  - *Top row* (1fr / 1.5fr): PCS Operating Parameters (3x RadialGauges: pressure, temp, fuel) + Power Comparison bar chart (real-time vs rated, 6 time slots).
  - *Bottom row* (1fr / 1.2fr / 0.8fr): Environmental Monitoring (smoke/water/fire status boxes + temp/humidity area chart), Battery Cluster Monitoring (data table with SOC/SOH/Vmax/Vmin/Tmax/Tmin columns, 4 clusters), Weather & Pricing (5-day forecast grid + time-of-use electricity pricing area chart with peak/valley summary).
- **EnergyView** (new) — energy/operations with three-row grid layout:
  - *Top row* (1.5fr / 1fr): Strategy Execution Monitoring (active strategy cards: Peak Shaving, Valley Fill, Demand Response — each with revenue + hours) + SOC Equalization (system SOC RadialGauge + per-cluster progress bars for BAT-01 through BAT-04).
  - *Middle row* (1fr / 1fr): Strategy Comparison 24h bar chart (peak/valley/shift stacked bars) + Charge/Discharge Schedule horizontal Gantt bars (planned vs actual per cluster).
  - *Bottom row* (4 equal columns): Battery cluster lifespan predictions — 4 RadialGauge panels (BAT-01 through BAT-04) showing remaining life % with cycle count and estimated life in months.
- **AlertsView** (refactored) — full-page alert management with filter bar (search, severity dropdown, truck dropdown, SeverityDonut), sortable column headers (type, severity, time), alert rows with severity badge + on-chain link icon, and slide-in detail panel (severity, message, triggered_by JSON, on-chain tx hash).
- **MapView** (refactored) — Leaflet map (dynamic import, SSR-disabled) with Leaflet.MarkerCluster, truck marker cluster groups, marker click selects truck. Right info panel (w-72) shows truck details + 2x3 telemetry grid + recent alerts. Toggle sidebar button. `onMarkerClick` callback wired through to `selectTruck`.
- **FleetView** (refactored) — left truck list sidebar (w-56 with search) + main content area. Selected truck shows 3-column layout: gauge column (fuel/temp/pressure RadialGauges), center PanelFrame with GlowBackdrop + TruckSchematic, right quick-stats column (tilt, flow rate, hatch, lat, lon). Bottom TimelineScrubber. Detail button opens TruckDetailPanel slide-in.
- **Old components removed**: `HeaderNav.tsx` (replaced by Sidebar), `FleetHUD.tsx` (absorbed into DashboardView KPI bar), `BottomPanel.tsx` (functionality distributed into DashboardView left panel + bottom bar). `AlertFeed.tsx` kept as legacy reference.

## Next Up

- Frontend on the v2 API (remake step 6).
- ESP32 firmware (step 7), then deployment (step 8).
- Later: real Web3 testnet anchoring (stub today), login rate limiting / token refresh, telemetry retention or downsampling for the free Neon storage limit.

## Open Questions

### Remake (2026-10-16)
- **Leak threshold:** `volume_drop_valve_closed` uses a provisional 2% of capacity per reading. Calibrate it against the real HC-SR04 noise on the prototype tank (sloshing while driving will matter).
- **Should the ESP32 also block the valve outside a geofence?** Today the backend only detects and alerts (the stack is read-only towards the truck). Blocking on the device would need the geofence list on the ESP32 (e.g. the device fetching it over HTTPS), which is a new device-facing interface — decide before the firmware step.
- **Tank geometry:** shape (rectangular / vertical cylinder / horizontal cylinder) and inner dimensions of the prototype tank, plus the HC-SR04 mounting offset. Enter it with `PUT /trucks/{id}/tank`; the simulator's demo tank (30 × 20 × 25 cm) is only a placeholder.
- **Connectivity:** how does the ESP32 get online while the truck moves — WiFi (phone hotspot) or a cellular modem (e.g. SIM800L / A7670)? This affects firmware and TLS memory budget.
- ~~**Broker + DB hosting**~~ — decided 2026-10-16: Neon (Postgres) and EMQX Cloud Serverless (MQTT). HiveMQ was dropped (see Architecture Decisions).
- ~~**Delivery zones**~~ — answered 2026-10-16: geofences are drawn on the map (point + radius) by an operator/admin, per truck or for the whole fleet.
- **Scope:** keep Web3 anchoring for a later phase? Keep the 3D truck view at all?

### Earlier (v1)
- Which testnet should anchoring target (Polygon Amoy vs. Sepolia vs. other)? Not yet confirmed.
- Has the hardware team finalized the sensor list and units (e.g. is tilt in degrees or raw accelerometer g-values)? Battery cluster monitoring (SOC, SOH, Vmax/Vmin, Tmax/Tmin) has been designed into the UI but needs hardware confirmation.
- ~~MQTT broker hosting~~ — EMQX Cloud Serverless (2026-10-16).
- Phase 2 ML model type and training data source — not yet scoped.
- Weather forecast and electricity pricing data — what is the source/API for real data? Currently mocked in AnalyticsView.
- Battery cluster fields (SOC, SOH, per-cluster voltages/temps) — are these per-truck or per-station? Currently shown in AnalyticsView as independent battery clusters.

## Architecture Decisions

- **2026-10-16 — Valve is local-only.** The ESP32 opens and closes the FDP-270A valve itself. The software stack stays read-only towards the truck: no command topic, and the dashboard only shows the reported `valve_open` state.
- **2026-10-16 — Device sends raw `distance_cm`**; the backend converts it to level/volume using a per-truck tank calibration, so recalibration never needs a reflash.
- **2026-10-16 — Free hosting target:** Vercel (frontend) + Render (backend). Redis and the TimescaleDB requirement were dropped as unnecessary at this scale.
- **2026-10-16 — Dashboard login** is email + password with JWT; no public sign-up (admins create users). Roles admin / operator / viewer.
- **2026-10-16 — Geofence rule:** the valve may only open inside an active geofence (point + radius) for the truck. Opening it anywhere else, or without a GPS fix, raises a critical alert and records an unauthorized discharge. The prototype's test button forces the valve open to exercise this. Detection only — the backend never commands the valve.
- **2026-10-16 — Clean vs unexpected offline:** `online:false` with `ts` = clean shutdown (activity log only); without `ts` = MQTT Last Will → `device_offline` alert.
- **2026-10-16 — MQTT broker: EMQX Cloud Serverless.** HiveMQ Cloud stopped selling its free Serverless plan on 2026-09-30 and shuts existing Serverless clusters down on 2026-12-31; its remaining cloud plan (Starter) is ~$249/month. EMQX Serverless has a free monthly quota (1M session-minutes ≈ 23 devices online 24/7, 1 GB traffic, ≤ 1,000 connections), MQTT over TLS 8883 with username/password — no code changes. Spend limit set to 0 so it pauses rather than bills. Traffic budget: ~600 B per reading (in + out), so one truck at 3 s non-stop ≈ 520 MB/month; realistic use is far lower.
- **2026-10-16 — Reports are generated on demand** from stored data (discharges, alerts, telemetry, audit log) as CSV/JSON; nothing is precomputed.

- MQTT chosen for device telemetry: lightweight pub/sub, widely supported on embedded hardware.
- TimescaleDB (Postgres extension) for time-series + relational data in one database.
- Blockchain anchors event **hashes** only, never raw telemetry or PII.
- Rule-based detection (Phase 1) ships first; ML is Phase 2.
- Dashboard visual direction: HighTopo-style industrial HUD (radial gauges, corner brackets, glow backdrop, timeline scrubber). 2D/SVG only for v1. 3D is explicitly additive/optional later.
- **Sidebar navigation** chosen over top header nav: persistent vertical icon rail (w-14) keeps all views one click away without consuming vertical space. Active tab is visually anchored by a left-edge indicator. This matches industrial HUD conventions where screen real estate is precious and the operator stays in a single view for long periods.
- **Tab-based view switching** (single page, conditional rendering) instead of Next.js routes for the dashboard: avoids layout remount, preserves WebSocket connection and DashboardContext state across view changes, and keeps the operator in a single-page flow. Each view component receives context directly rather than URL params.
- **Mock data in AnalyticsView/EnergyView**: battery cluster, weather, pricing, and strategy execution data are currently static mocks. These are UI prototypes until the backend schema and data sources are finalized. The component boundaries are clean — swapping mock arrays for WS-fed or REST-fetched data requires no structural changes.

## Session Notes

- **2026-10-16 — Frontend live on Vercel:** https://petroeye-frontend.vercel.app (built with `NEXT_PUBLIC_API_URL=https://petroeye-backend.onrender.com`, `NEXT_PUBLIC_WS_URL=wss://petroeye-backend.onrender.com/ws`). The backend allows it through `CORS_ORIGIN_REGEX` (default `https://petroeye-frontend(-[a-z0-9-]+)?\.vercel\.app`, so preview deploys work too); `CORS_ORIGINS` only needs `http://localhost:3000`. Added because the Render dashboard was unreachable from the dev network: the ISP resets TLS to Render edge IPs 216.24.57.16/.18 (used by dashboard.render.com and *.onrender.com) while other Render IPs work — Render itself was healthy. Users on that network can't reach the API until it sits behind a custom domain (e.g. via Cloudflare).

- **2026-10-16 — Backend fixes found while building the frontend:** (1) `rules.yaml` is now read as UTF-8 (on Windows the default cp1252 garbled the em dash in alert messages; Linux/Render was unaffected). (2) A GPS dropout in the middle of an authorized discharge no longer raises a critical `valve_open_outside_geofence`: the reading keeps the last known geofence; leaving the zone with the valve open still alerts; `no_gps_fix` now takes priority over `left_geofence` as the reason. (3) Two backend instances inserting the same reading (overlapping deploys, or a stray local server) no longer crash the handler: the unique-constraint `IntegrityError` is treated as "already stored". 39 tests.

- **2026-10-16 — Backend live on Render:** https://petroeye-backend.onrender.com (Blueprint from `render.yaml`, free plan, Virginia). Swagger at `/docs`. Verified: `/health` → database + MQTT connected; production admin login works; one status + one telemetry message from `truck-001` via EMQX reached Neon and the deployed API (truck online, parked, valve closed, no alerts). `truck-001` is now registered in production. Still to do: rotate the EMQX passwords (the shared test password still worked at deploy time) and update `MQTT_PASSWORD` in Render; add an uptime pinger on `/health`; set `CORS_ORIGINS` to the Vercel URL once the frontend is deployed; enter the real tank calibration with `PUT /trucks/truck-001/tank`.

- **2026-10-16 — EMQX broker live.** Serverless deployment `ndf2189d.ala.us-east-1.emqxsl.com` (AWS us-east-1), MQTT over TLS 8883, users `petroeye-backend` and `truck-001`. TLS works with the certifi CA bundle (no custom CA needed on the backend); a wrong password is rejected. Verified: simulator `truck-001` over TLS → EMQX → backend → Postgres, 140/140 readings received; forced opening 1.2 km from the depot → critical alert + unauthorized discharge; depot discharge authorized (8.34 L). That run exposed a float-boundary false positive in `volume_drop_valve_closed` (drop 0.300…07 L vs 0.3 L limit) — fixed by rounding to 0.01 L. Local credentials live in the gitignored `.env.emqx`. **Rotate both user passwords before Render** (the test password was shared in chat and is the same for both users).

- **2026-10-16 — Neon database live.** Project petroEye (`snowy-dust-11819934`, org `org-mute-lab-77362956`, branch `production`, AWS us-east-1) linked with `neon init`, `neon.ts` created, `neon deploy` applied (no changes needed) and pulled `DATABASE_URL` (pooled) + `DATABASE_URL_UNPOOLED` (direct) into the local `.env`. Alembic now uses the direct URL; the app uses the pooled URL with asyncpg configured for PgBouncer. Migration `552c2a705a9a` applied on Neon. Verified: health OK, MQTT → backend → Neon flow (forced valve opening 2.6 km from the depot → critical alert + unauthorized discharge; opening at the depot → authorized). Round trip from the dev machine is ~270 ms, so Render must run in the `virginia` region. Test data was then cleared (all tables truncated, schema kept at `552c2a705a9a`), so Render creates the real admin from its `ADMIN_EMAIL`/`ADMIN_PASSWORD` on first start. The local `.env` points back at the local Postgres; the Neon URLs are kept there as `NEON_DATABASE_URL` / `NEON_DATABASE_URL_UNPOOLED` for reference (the app ignores them). Note: `neon deploy`/`neon env pull` rewrite `DATABASE_URL` in `.env` — run them with `--no-env-pull`, or re-point `.env` afterwards, so local runs don't write to production.

- **2026-10-16 — Backend v2 built.** See "Backend v2 — Built and verified" above. Local `.env` now points at a new `petroeye` database and has dev-only `ADMIN_EMAIL`/`ADMIN_PASSWORD`/`JWT_SECRET`. Run `uv run alembic upgrade head` on any other database before starting. Only one backend may run per `MQTT_CLIENT_ID` (two `--reload` servers kicked each other off the broker during testing).

- **2026-10-16 — Split into two repos.** The monorepo became two independent repos: **backend** (FastAPI, simulator, docker-compose + Mosquitto config, system docs; Render) and **frontend** (Next.js, `ui-context.md`, frontend code standards; Vercel). The simulator now runs from the backend's uv environment (`uv run python simulation/truck_simulator.py`). Removed the uv workspace root, hello-world `main.py` files, `_check_db.py` (hardcoded DB credentials) and an empty `contracts/`. Each repo has its own `.gitignore` that excludes `.env` files. The old root git history (one commit) is no longer used.
- **Cross-repo rule:** the frontend's `lib/types.ts` mirrors this API. Any REST/WS shape change here gets a note in this file so the frontend can follow.

- **2026-07-20 — Full-stack E2E verified**: Backend confirmed against live Mosquitto + Postgres. Frontend built and build-verified (`npm run build` passes). Dashboard renders with live WebSocket data (truck list, telemetry, alerts flowing from simulator).
- **2026-07-20 — UI redesign complete**: Sidebar navigation replaced HeaderNav. All 6 views (Dashboard, Map, Fleet, Analytics, Energy, Alerts) rendered via tab switching in page.tsx. DashboardView redesigned with three-column KPI/center/right panel layout. AnalyticsView and EnergyView added with battery cluster monitoring, strategy execution, weather/pricing, and lifespan prediction panels. MapView and FleetView refactored into cleaned-up dedicated views. Build passes (`npx next build` succeeds). `docs/ui-context.md` remains accurate — the redesign stays within existing design tokens and HUD visual language. `docs/hardware-integration-guide.md` unchanged (no MQTT schema changes).
- Any change to the MQTT payload schema must be mirrored in `docs/hardware-integration-guide.md` in the same change.
- Mock data patterns in AnalyticsView and EnergyView for battery clusters, weather, and pricing — these will need real data sources in a follow-up pass.
