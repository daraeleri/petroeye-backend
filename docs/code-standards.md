# Code Standards

## General

- Keep MQTT ingestion, the AI/rule engine, and the Web3 anchoring service decoupled — each is a swappable module behind a small interface.
- Favor small, single-purpose functions for domain logic (e.g. `find_containing_fence()`, `volume_from_level()`, `alert_digest()`).
- No hardware actuation code anywhere in the backend. This system reads; it does not write to the truck.

## Python / FastAPI

- Full type hints everywhere; Pydantic models for every MQTT payload and API request/response (e.g. `TelemetryPayload`, `AlertOut`).
- All I/O-bound endpoints and services are `async`. Use dependency injection for DB sessions.
- Long-running or external-call work (blockchain anchoring, ML inference over large windows) runs as a background task or queue worker — never inline in the request/ingestion path.
- Avoid bare `except:`; catch specific exceptions and log with truck/device context.

## MQTT

- Topic convention: `petrotwin/{truck_id}/telemetry`, `petrotwin/{truck_id}/status`. Device → backend only; the backend never publishes to device topics.
- Every payload is JSON and includes a `schema_version` field.
- Telemetry: QoS 1 minimum. Status/heartbeat: QoS 1.
- Reject and log (never silently drop) any payload that fails schema validation; do not guess missing fields.

## Web3

- Never commit private keys, mnemonics, or `.env` files containing them. The anchoring service key is injected via secret manager/env at deploy time only.
- Contract ABI is checked into `contracts/abi/` (when contracts are added to this repo) and treated as generated/protected — regenerate, don't hand-edit.
- The anchoring service retries on failure with backoff and persists a pending queue; a dropped chain write is a bug, not an acceptable outcome (it should retry, not disappear).
- Distinguish testnet vs mainnet config explicitly; default to testnet everywhere until a mainnet decision is made and recorded in `progress-tracker.md`.

## AI / ML

- Phase 1 rule thresholds live in a versioned config file (e.g. `rules.yaml`), not hardcoded in Python — thresholds change often during hardware calibration.
- Phase 2 ML models are loaded from a model registry path/version, never a hardcoded local path with no version tag.
- Every anomaly decision (rule or ML) logs the feature values that triggered it, for explainability and later debugging with the hardware team.
- The AI module never mutates truck state directly; it only produces `Anomaly`/`Alert` objects that the orchestration layer persists and broadcasts.

## Data and State

- Truck status transitions (`Idle → Loading → In Transit → Delivered/Alert`) are written to the DB first, then broadcast — clients never manage phase locally.
- Alerts are append-only once created; resolving an alert creates a new linked resolution record rather than mutating the original.
- Any change to the MQTT payload schema or DB schema must be reflected the same PR in `architecture.md` and, if it affects the physical device, `hardware-integration-guide.md`.
