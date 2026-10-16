# PetroTwin Backend

FastAPI backend: REST + WebSocket API, async MQTT ingestion, Phase 1 rule-based
anomaly detection, and a stubbed Web3 anchoring queue. See `docs/architecture.md`
for the full system boundaries this code follows.

## Setup

```bash
uv sync                       # installs dependencies from pyproject.toml
cp .env.example .env          # then edit .env with your real DATABASE_URL / MQTT creds
```

## Run

Make sure Mosquitto and Postgres are running first (`docker compose up -d` in this repo starts both),
then:

```bash
uv run uvicorn app.main:app --reload
```

On startup this will:
1. Create DB tables if they don't exist (`init_db()` — a stand-in for real
   Alembic migrations; run `uv run alembic init alembic` once the schema
   stabilizes and switch over).
2. Connect to the MQTT broker and subscribe to `petrotwin/+/telemetry` and `petrotwin/+/status`.
3. Start the (currently stubbed) Web3 anchoring queue worker.

## Verify it's working end to end

With `simulation/truck_simulator.py` running against the same broker:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/trucks
curl http://localhost:8000/trucks/truck-001/telemetry
curl http://localhost:8000/alerts
```

`/trucks` and `/trucks/truck-001/telemetry` should start returning data within
a few seconds of the simulator running. Try `--scenario fuel_leak` or
`--scenario overheat` on the simulator to see `/alerts` populate — check the
uvicorn console log too, anomaly detections are logged with the feature
values that triggered them.

## What's stubbed / not yet implemented

- **Alembic migrations**: currently using `create_all` on startup. Fine for
  early dev, not for anything with real data you care about.
- **Web3 anchoring**: `app/web3/anchoring.py` logs what it would anchor but
  doesn't submit a real transaction yet — no contract is deployed. See the
  TODO in that file and `@web3-blockchain`'s scope in `AGENTS.md`.
- **Phase 2 ML anomaly scoring**: not started. `app/ai/rule_engine.py` is
  Phase 1 (threshold-based) only, per `docs/progress-tracker.md`.
- **Auth**: no JWT/user auth wired up yet on the REST/WS endpoints.
- **Per-device MQTT credentials**: the `devices` table exists but nothing
  enforces per-truck auth yet — the dev broker currently allows anonymous connections.
