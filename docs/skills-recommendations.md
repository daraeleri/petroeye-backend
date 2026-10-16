# Recommended OpenCode Skills for PetroTwin

Beyond the subagents in `.opencode/agent/`, the following reusable **skills** (SKILL.md-style reference docs the agent loads before doing specific kinds of work) will meaningfully improve build quality and consistency. Create these under `.opencode/skill/` (or wherever your OpenCode setup expects skills) as the project matures — they encode patterns that are easy to get subtly wrong on the first pass.

## 1. `fastapi-mqtt-bridge`
Patterns for running an MQTT client (paho-mqtt/gmqtt) alongside FastAPI's async event loop without blocking it: recommended library, asyncio task wiring, reconnect/backoff handling, and how to hand a validated message off to the DB-write + WebSocket-broadcast path cleanly.

## 2. `timescaledb-telemetry-schema`
How to design and migrate a TimescaleDB hypertable for high-frequency sensor data: chunking/retention policy choices, indexing for per-truck time-range queries, and Alembic migration patterns that play nicely with the Timescale extension.

## 3. `nextjs-realtime-dashboard`
Patterns for a Next.js dashboard consuming a WebSocket stream: where the socket connection lives (client component boundary), how to avoid re-render storms on high-frequency updates, and recommended charting setup with `recharts` for live + historical data in the same component.

## 4. `web3py-event-anchoring`
Patterns for an async, queued, retrying anchoring service using `web3.py`: nonce management under concurrent writes, gas estimation on a testnet, and safely handling a transaction that fails or is dropped without losing the underlying alert.

## 5. `anomaly-rule-engine-config`
How to structure a versioned, human-editable rules config (e.g. `rules.yaml`) for threshold-based anomaly detection, plus the Python loader/evaluator pattern that keeps rule logic testable in isolation from MQTT/DB code.

## 6. `mqtt-scenario-simulator`
How to extend `simulation/truck_simulator.py` with a new fault scenario: the expected shape of a scenario definition, how to make drift/noise realistic without hardcoding results, and how to keep new scenarios in lockstep with `docs/hardware-integration-guide.md`.

## 7. `docker-compose-local-stack`
Reference `docker-compose.yml` patterns for local dev: Mosquitto + TimescaleDB + backend + frontend, with sane defaults so a new contributor (or the hardware team, when testing MQTT connectivity) can run `docker compose up` and have a working broker in under a minute.

## 8. `docs-sync-checklist`
A short, mechanical checklist (used by the `docs-sync` agent) enumerating exactly which `docs/*.md` file needs updating for a given class of change — schema change → `hardware-integration-guide.md` + `architecture.md`; new scope → `project-overview.md`; every change → `progress-tracker.md`.

---

**Priority order for creating these**: `fastapi-mqtt-bridge` and `timescaledb-telemetry-schema` first (they unblock the very first working slice), then `mqtt-scenario-simulator` and `docker-compose-local-stack` (needed to demo without hardware), then `nextjs-realtime-dashboard`, then `anomaly-rule-engine-config`, then `web3py-event-anchoring` last (Web3 anchoring is the highest-risk, lowest-urgency piece for an initial demo).
