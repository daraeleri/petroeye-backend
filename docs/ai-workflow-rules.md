# AI Workflow Rules

## Approach

Build this project incrementally using a spec-driven workflow. We are integrating MQTT-based IoT ingestion, a FastAPI backend, a Next.js dashboard, a phased AI anomaly module, and a Web3 audit/trigger layer — while a physical truck prototype is being built remotely and in parallel. Context files in `docs/` define what to build, how to build it, and current progress. Always implement against these specs — do not infer sensor types, thresholds, network choices, or product behavior from scratch.

## Scoping Rules

- Work on one system boundary at a time: MQTT ingestion, REST API, WebSocket relay, AI rule/ML logic, Web3 anchoring, frontend widgets, and simulation are each separate units of work.
- Prefer small, verifiable increments over large speculative changes.
- Do not combine unrelated boundaries in a single implementation step (e.g. do not touch DB schema and frontend chart styling in the same change).

## When to Split Work

Split an implementation step if it combines:

- MQTT subscriber changes and WebSocket broadcast changes.
- Database schema changes and frontend UI/animation changes.
- AI rule/model logic changes and alert-notification UI changes.
- Smart contract changes and the off-chain anchoring service changes.

If a change cannot be verified end to end quickly (ideally against the simulator), the scope is too broad — split it.

## Handling Missing Requirements

- Do not invent sensor types, units, thresholds, truck capacities, or blockchain network choices that are not defined in the context files.
- If a survival-critical detail is ambiguous — e.g. an anomaly threshold, or which network to anchor to — ask for clarification before writing the logic.
- If a requirement is missing, add it as an Open Question in `progress-tracker.md` before continuing, rather than guessing.

## Protected Files

Do not modify the following unless explicitly instructed:

- (Frontend protected files are listed in the frontend repo's `AGENTS.md`.)
- `app/mqtt/client.py` — the core MQTT connection loop, once established and stable.
- `contracts/*` and `contracts/abi/*` — once a contract is deployed and its address recorded, changing it invalidates all prior anchored history.

## Keeping Docs in Sync

Update the relevant context file whenever implementation changes:

- `architecture.md` — system boundaries, storage model, or invariants.
- `docs/hardware-integration-guide.md` — **any** change to the MQTT topic naming or telemetry payload schema. This file is the contract with the remote hardware team; it must never drift from what the backend actually expects.
- `ui-context.md` — new design tokens or layout patterns.
- `progress-tracker.md` — after every meaningful implementation change, without exception.

## Before Moving to the Next Unit

1. The current unit works end to end within its defined scope, verified against the simulator where applicable.
2. No invariant defined in `architecture.md` was violated.
3. `progress-tracker.md` reflects the completed work.
4. `uv run uvicorn app.main:app` boots. If the REST/WS API shape changed, the frontend repo has been told (note in `progress-tracker.md`).
5. If the MQTT payload schema changed, `docs/hardware-integration-guide.md` was updated in the same change.
