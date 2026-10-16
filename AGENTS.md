# AGENTS.md — PetroTwin Backend

Entry point for any AI coding agent working in this repo. Read this first, then every file in `docs/` before writing code.

## What this repo is

The backend for PetroTwin, a digital twin of a petrol tanker truck. The physical truck is an ESP32 with a NEO-6M GPS, an HC-SR04 ultrasonic tank level sensor and an FDP-270A solenoid valve, publishing over MQTT. This repo holds the FastAPI service (MQTT ingestion, REST + WebSocket API, rule engine, Web3 anchoring stub), the truck simulator, the local dev infrastructure, and the system-wide docs. It is deployed on Render.

The dashboard lives in a separate **frontend** repo (Next.js, Vercel) and only talks to this service over REST + WebSocket.

## Required reading (in order)

1. `docs/project-overview.md` — what we're building and why.
2. `docs/architecture.md` — stack, boundaries, storage model, invariants.
3. `docs/code-standards.md` — how code in this repo is written.
4. `docs/ai-workflow-rules.md` — how work is scoped and sequenced. **Follow this strictly.**
5. `docs/progress-tracker.md` — current state and remake plan; update after every change.
6. `docs/hardware-integration-guide.md` — the contract with the ESP32 firmware. Never let it drift from the actual MQTT payload schema.

## Ground rules

- Never invent product behavior, sensor fields, thresholds, or a blockchain network that isn't defined in `docs/`. If it's ambiguous, add it to Open Questions in `progress-tracker.md` and ask.
- One system boundary per change (MQTT ingestion, REST API, WebSocket relay, AI logic, Web3 anchoring, simulation).
- The whole stack is read-only towards the truck: the ESP32 controls the valve locally, and the backend never publishes to device topics.
- Raw telemetry never goes on-chain — only hashed event digests.
- If a change touches MQTT topics or the payload schema, update `docs/hardware-integration-guide.md` and the simulator in the same change.
- If a change touches the REST/WebSocket response shapes, note it in `progress-tracker.md` so the frontend repo can follow.

## Layout

| Path | Contents |
| ---- | -------- |
| `app/` | FastAPI service |
| `simulation/` | Truck simulator; publishes to MQTT exactly like the ESP32 |
| `docker-compose.yml`, `mosquitto/` | Local broker + Postgres |
| `docs/` | System docs and the device contract |

## Before calling a unit of work done

See `docs/ai-workflow-rules.md` → "Before Moving to the Next Unit": it works end to end against the simulator, no invariant is violated, docs are updated, and `uv run uvicorn app.main:app` boots.
