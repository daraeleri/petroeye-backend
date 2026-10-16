# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- **Remake around the real hardware** (started 2026-10-16). The v1 stack below was built for sensors the prototype doesn't have (temperature, pressure, tilt, flow, hatch). The real truck has an ESP32 with a NEO-6M GPS, an HC-SR04 ultrasonic level sensor and an FDP-270A solenoid valve.

## Current Goal

- Contract first: telemetry schema v2 is defined in `hardware-integration-guide.md` (docs only, 2026-10-16). Next: port backend ingestion + DB + rules and the simulator to v2, then the frontend, then the ESP32 firmware, then deploy (Render + Vercel).
- **Known drift:** until the backend/simulator port lands, the code still speaks v1 while the hardware guide describes v2. Firmware should target v2.

## Remake Plan (in order, one boundary per step)

1. ~~Repo hygiene~~ — done 2026-10-16 as part of the repo split (see Session Notes).
2. Backend MQTT ingestion → v2 schema; TLS support for the managed broker; resilient startup when the broker is unreachable.
3. DB → v2 telemetry columns + `tank_calibrations`, unique `(truck_id, ts)`, Alembic migrations instead of `create_all`.
4. Rule engine → leak/theft (volume drop with valve closed), discharge outside a zone, GPS fix lost, device offline; alert de-duplication.
5. Simulator → v2 payloads and scenarios matching the real sensors.
6. Frontend → one UI tree (drop the unused `components/hud/` views, plus the Energy/Analytics battery/pricing mock views), tank volume + valve + GPS twin; compress the 48 MB GLB.
7. Firmware → `firmware/` PlatformIO project for the ESP32.
8. Deployment → Render (backend), Vercel (frontend), managed MQTT + Postgres, `/health` keep-alive pinger.

## Completed

### Backend — Verified (2026-07-20)
- **Infrastructure**: `docker-compose.yml` with Mosquitto broker (1883) + TimescaleDB (5432). Verified containers reachable.
- **FastAPI async MQTT subscriber**: `app/mqtt/client.py` — paho-mqtt on background thread, dispatches to async handlers via `asyncio.run_coroutine_threadsafe`. Subscribes to `petrotwin/+/telemetry` and `petrotwin/+/status`.
- **DB schema**: `Telemetry`, `Truck`, `Alert`, `Device` SQLAlchemy models (async, asyncpg). Tables auto-created via `init_db()`.
- **Phase 1 rule engine**: `rules.yaml`-driven thresholds (temp > 60°C, tilt > 25°, fuel < 5%, hatch open, fuel drop rate > 0.4%/reading). Verified: `fuel_leak` scenario produces `critical` alerts.
- **REST endpoints**: `GET /trucks`, `GET /trucks/{id}`, `GET /trucks/{id}/telemetry`, `GET /alerts` — returning real data from Postgres.
- **WebSocket relay**: `/ws` endpoint + `ConnectionManager` broadcasting telemetry/status/alert events.
- **Web3 anchoring stub**: `app/web3/anchoring.py` — async queued worker logging what it would anchor.
- **Truck simulator**: `simulation/truck_simulator.py` (7 scenarios + LWT), `fleet_runner.py`. Publishing confirmed against live broker.

### Frontend — Dashboard (2026-07-20)
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

- Real Alembic migration setup (replacing `init_db()` create_all).
- Real Web3 testnet anchoring (replacing stub) — blocked on network choice Open Question.
- JWT auth on REST/WS endpoints + per-device MQTT credential enforcement.
- 3D digital twin view (`frontend/components/twin-3d/`) — explicitly Phase 2+.
- Battery cluster telemetry fields in backend schema + simulator (SOC, SOH, Vmax/Vmin, Tmax/Tmin per cluster) — currently using static mock data in AnalyticsView/EnergyView.
- Weather and electricity pricing data sources — currently static mock data in AnalyticsView.
- Historical playback mode integration with TimelineScrubber across all views.
- Responsive / tablet layout adaptation for the new sidebar + multi-column views.

## Open Questions

### Remake (2026-10-16)
- **Tank geometry:** shape (rectangular / vertical cylinder / horizontal cylinder) and inner dimensions of the prototype tank, plus the HC-SR04 mounting offset. Needed for distance → volume.
- **Connectivity:** how does the ESP32 get online while the truck moves — WiFi (phone hotspot) or a cellular modem (e.g. SIM800L / A7670)? This affects firmware and TLS memory budget.
- **Broker + DB hosting:** proposed HiveMQ Cloud Serverless (MQTT, TLS 8883) and Neon (Postgres), both free. Render can't host a broker, and its free Postgres expires. Confirm.
- **Delivery zones:** are approved discharge locations defined per trip or per truck, and who enters them? Needed for the "discharge outside zone" rule.
- **Scope:** keep Web3 anchoring for a later phase? Keep the 3D truck view at all?

### Earlier (v1)
- Which testnet should anchoring target (Polygon Amoy vs. Sepolia vs. other)? Not yet confirmed.
- Has the hardware team finalized the sensor list and units (e.g. is tilt in degrees or raw accelerometer g-values)? Battery cluster monitoring (SOC, SOH, Vmax/Vmin, Tmax/Tmin) has been designed into the UI but needs hardware confirmation.
- MQTT broker hosting: self-hosted Mosquitto vs. managed (HiveMQ Cloud / EMQX Cloud)?
- Phase 2 ML model type and training data source — not yet scoped.
- Weather forecast and electricity pricing data — what is the source/API for real data? Currently mocked in AnalyticsView.
- Battery cluster fields (SOC, SOH, per-cluster voltages/temps) — are these per-truck or per-station? Currently shown in AnalyticsView as independent battery clusters.

## Architecture Decisions

- **2026-10-16 — Valve is local-only.** The ESP32 opens and closes the FDP-270A valve itself. The software stack stays read-only towards the truck: no command topic, and the dashboard only shows the reported `valve_open` state.
- **2026-10-16 — Device sends raw `distance_cm`**; the backend converts it to level/volume using a per-truck tank calibration, so recalibration never needs a reflash.
- **2026-10-16 — Free hosting target:** Vercel (frontend) + Render (backend). Redis and the TimescaleDB requirement were dropped as unnecessary at this scale.

- MQTT chosen for device telemetry: lightweight pub/sub, widely supported on embedded hardware.
- TimescaleDB (Postgres extension) for time-series + relational data in one database.
- Blockchain anchors event **hashes** only, never raw telemetry or PII.
- Rule-based detection (Phase 1) ships first; ML is Phase 2.
- Dashboard visual direction: HighTopo-style industrial HUD (radial gauges, corner brackets, glow backdrop, timeline scrubber). 2D/SVG only for v1. 3D is explicitly additive/optional later.
- **Sidebar navigation** chosen over top header nav: persistent vertical icon rail (w-14) keeps all views one click away without consuming vertical space. Active tab is visually anchored by a left-edge indicator. This matches industrial HUD conventions where screen real estate is precious and the operator stays in a single view for long periods.
- **Tab-based view switching** (single page, conditional rendering) instead of Next.js routes for the dashboard: avoids layout remount, preserves WebSocket connection and DashboardContext state across view changes, and keeps the operator in a single-page flow. Each view component receives context directly rather than URL params.
- **Mock data in AnalyticsView/EnergyView**: battery cluster, weather, pricing, and strategy execution data are currently static mocks. These are UI prototypes until the backend schema and data sources are finalized. The component boundaries are clean — swapping mock arrays for WS-fed or REST-fetched data requires no structural changes.

## Session Notes

- **2026-10-16 — Split into two repos.** The monorepo became two independent repos: **backend** (FastAPI, simulator, docker-compose + Mosquitto config, system docs; Render) and **frontend** (Next.js, `ui-context.md`, frontend code standards; Vercel). The simulator now runs from the backend's uv environment (`uv run python simulation/truck_simulator.py`). Removed the uv workspace root, hello-world `main.py` files, `_check_db.py` (hardcoded DB credentials) and an empty `contracts/`. Each repo has its own `.gitignore` that excludes `.env` files. The old root git history (one commit) is no longer used.
- **Cross-repo rule:** the frontend's `lib/types.ts` mirrors this API. Any REST/WS shape change here gets a note in this file so the frontend can follow.

- **2026-07-20 — Full-stack E2E verified**: Backend confirmed against live Mosquitto + Postgres. Frontend built and build-verified (`npm run build` passes). Dashboard renders with live WebSocket data (truck list, telemetry, alerts flowing from simulator).
- **2026-07-20 — UI redesign complete**: Sidebar navigation replaced HeaderNav. All 6 views (Dashboard, Map, Fleet, Analytics, Energy, Alerts) rendered via tab switching in page.tsx. DashboardView redesigned with three-column KPI/center/right panel layout. AnalyticsView and EnergyView added with battery cluster monitoring, strategy execution, weather/pricing, and lifespan prediction panels. MapView and FleetView refactored into cleaned-up dedicated views. Build passes (`npx next build` succeeds). `docs/ui-context.md` remains accurate — the redesign stays within existing design tokens and HUD visual language. `docs/hardware-integration-guide.md` unchanged (no MQTT schema changes).
- Any change to the MQTT payload schema must be mirrored in `docs/hardware-integration-guide.md` in the same change.
- Mock data patterns in AnalyticsView and EnergyView for battery clusters, weather, and pricing — these will need real data sources in a follow-up pass.
