# PetroTwin: Digital Twin Monitoring System for Petrol Tanker Trucks

## Overview

A real-time digital twin monitoring platform for petrol tanker trucks. A physical truck (built in parallel by a remote hardware team) is fitted with IoT sensors that publish telemetry over MQTT. The backend ingests, validates, stores, and analyzes this telemetry, exposing it to a live "digital twin" dashboard. Critical events (leaks, overheating, tampering, rollover risk) are detected by an AI module and anchored to a blockchain as an immutable, tamper-evident audit trail, with smart contracts able to trigger downstream actions (alerts, compliance/insurance workflows).

## Goals

1. Real-time ingestion and visualization of truck telemetry (fuel level, temperature, pressure, GPS, tilt, flow rate) via MQTT → FastAPI → Next.js dashboard.
2. Detect operational anomalies (leaks, overheating, tampering, rollover risk, route deviation) using a phased approach: rule-based thresholds first, ML-based prediction later.
3. Provide a tamper-evident audit trail of critical events using blockchain anchoring, with smart-contract-triggered actions for high-severity events.
4. Let the software stack be built and fully tested via simulation, independent of and in parallel with the physical prototype.

## Core Data Flow

1. Truck sensor unit publishes JSON telemetry to the MQTT broker on a per-truck topic.
2. FastAPI's MQTT subscriber validates the payload (Pydantic schema), normalizes units, and persists it to TimescaleDB/Postgres.
3. The persisted reading is broadcast over WebSocket to connected dashboard clients.
4. The rule engine evaluates the reading against configured thresholds in real time.
5. (Phase 2) The ML anomaly service scores a rolling window of readings for the truck.
6. On an anomaly, an Alert record is created, a hash of the event is queued for on-chain anchoring, and — for critical severity — the smart contract emits an event that downstream systems (compliance, insurance, ops) can act on.
7. The Next.js dashboard renders the truck's live digital twin, active alerts, and historical playback via REST + WebSocket.

## Features

- **Digital Twin Dashboard**: live 2D truck schematic with sensor overlays (fuel, temp, pressure, tilt, GPS).
- **MQTT Telemetry Ingestion**: per-truck topics, versioned JSON payloads, QoS-aware handling.
- **Rule-Based Alerts** (Phase 1): configurable thresholds (e.g., fuel drop rate, temp ceiling, tilt angle).
- **ML Anomaly Detection** (Phase 2): model-scored anomaly probability per truck/window.
- **Blockchain Audit Log**: hashed telemetry/alert events anchored on a testnet, queryable proof of integrity.
- **Smart Contract Triggers**: on-chain event emission for critical alerts, consumable by external systems.
- **Fleet Management**: truck roster, status (Idle/Loading/In Transit/Delivered/Alert), operator assignment.
- **Historical Playback**: scrub through past telemetry/alerts for a truck.
- **Simulation Mode**: fully synthetic truck publishers so the whole stack is testable with zero physical hardware.

## Scope

### In Scope

- FastAPI backend (REST + WebSocket) with async MQTT subscriber.
- Mosquitto (or managed MQTT broker) integration.
- Next.js dashboard with real-time widgets.
- TimescaleDB/Postgres for telemetry + relational fleet data.
- Rule-based anomaly detection (Phase 1) and a pluggable ML anomaly service (Phase 2).
- Web3 anchoring service + minimal smart contract on a public testnet.
- Truck telemetry simulator covering normal operation and defined fault scenarios.
- Hardware integration guide for the physical prototype team (MQTT topics, payload schema, auth).

### Out of Scope

- Direct remote control/actuation of the physical truck (monitoring only — read path, never write-to-hardware).
- Mainnet blockchain deployment.
- Full 3D digital twin rendering (Phase 1 uses a 2D schematic; 3D is a stretch goal, not a commitment).
- Payment/insurance system implementation itself (only the on-chain trigger/event hook).

## Success Criteria

1. Multiple simulated trucks can publish telemetry and appear live on the dashboard simultaneously.
2. A fault scenario (e.g., simulated leak) triggers a rule-based alert and an on-chain anchor within a few seconds.
3. Historical telemetry and alerts for a truck are queryable and scrubbable in the UI.
4. The entire stack runs and is demoable using only the simulator — no physical hardware required.
5. The physical prototype team can connect a real device by following `docs/hardware-integration-guide.md` with no additional clarification needed.
