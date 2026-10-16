# PetroTwin: Digital Twin Monitoring System for Petrol Tanker Trucks

## Overview

A real-time digital twin monitoring platform for petrol tanker trucks. The physical prototype truck is an **ESP32** with a **NEO-6M GPS**, an **HC-SR04 ultrasonic** sensor that measures the liquid level in the tank, and an **FDP-270A solenoid valve** for discharging. It publishes telemetry over MQTT. The backend ingests, validates, stores and analyzes this telemetry, and serves a live, login-protected "digital twin" dashboard.

The core safety rule is the **geofence**: operators mark approved discharge locations on the map, and the valve must not open anywhere else. If it does (the prototype has a test button that forces it open), the system raises a critical alert and records an unauthorized discharge. Critical events are hashed and (later) anchored on a blockchain as a tamper-evident audit trail.

## Goals

1. Real-time ingestion and visualization of truck telemetry — GPS position, valve state (open/closed), and tank volume from the ultrasonic distance — via MQTT → FastAPI → Next.js dashboard.
2. Enforce approved discharge locations: detect and alert on any valve opening outside a geofence.
3. Detect other anomalies (volume dropping with the valve closed = leak/theft, GPS loss, sensor failure, device dropping offline) with rules first, ML later.
4. Keep an exportable record of activity: discharges, alerts, acknowledgements, device and user events.
5. Build and test the whole software stack via simulation, independently of the physical prototype.

## Core Data Flow

1. The ESP32 publishes JSON telemetry (schema v2) to `petrotwin/{truck_id}/telemetry` and heartbeats to `petrotwin/{truck_id}/status`.
2. The backend's MQTT subscriber validates the payload, computes tank level/volume from the truck's calibration, checks which geofence the truck is in, and stores the reading in Postgres.
3. The rule engine compares the reading with the previous one: valve opened outside a geofence, volume drop with valve closed, GPS fix lost, etc.
4. Valve open → close sessions are recorded as discharges (authorized or not, litres).
5. Alerts are stored (append-only), hashed, and critical ones are queued for on-chain anchoring.
6. Everything is pushed to logged-in dashboards over WebSocket; history and reports come from the REST API.

## Features

- **Login**: email + password, roles admin / operator / viewer. Admins create accounts; no public sign-up.
- **Live map & twin**: each truck's position, moving/parked/discharging state, valve open/closed, tank volume and fill %.
- **Geofences**: draw approved discharge points (centre + radius) per truck or for the whole fleet.
- **Alerts**: critical alert when the valve opens outside a geofence; leak/theft, GPS loss, sensor no-echo, device offline. Operators acknowledge with a note.
- **Discharges**: every valve session with location, geofence, authorized flag and litres.
- **Reports**: summary, activity timeline, CSV/JSON export (discharges, alerts, telemetry, audit log).
- **Tank calibration**: per-truck tank shape and dimensions turn the raw ultrasonic distance into litres.
- **Blockchain audit log** (stubbed): SHA-256 digests of critical alerts, ready for testnet anchoring.
- **Simulation mode**: synthetic trucks (delivery, forced opening, leak, GPS loss…) so the stack runs with no hardware.

## Scope

### In Scope

- FastAPI backend (REST + WebSocket) with async MQTT subscriber, JWT auth.
- Managed MQTT broker in production (HiveMQ Cloud proposed), Mosquitto locally.
- Next.js dashboard (separate repo, Vercel).
- Postgres (Neon proposed in production) with Alembic migrations.
- Rule-based anomaly detection (Phase 1) and a pluggable ML service (Phase 2).
- Web3 anchoring service + minimal smart contract on a public testnet (later phase).
- Truck simulator covering normal operation and fault scenarios.
- ESP32 firmware and the hardware integration guide (MQTT topics, payload schema, auth).

### Out of Scope

- Remote control of the truck. The ESP32 controls the valve locally; the software only monitors (read path, never write-to-hardware).
- Mainnet blockchain deployment.
- Payment/insurance system implementation itself (only the on-chain trigger/event hook).

## Success Criteria

1. Multiple simulated trucks publish telemetry and appear live on the dashboard simultaneously.
2. Forcing the valve open outside a geofence produces a critical alert on the dashboard within one reading.
3. A discharge inside a geofence is recorded as authorized with the litres discharged.
4. Discharges, alerts and activity for a period can be exported as CSV.
5. The whole stack runs and is demoable using only the simulator — no physical hardware required.
6. The prototype team can connect the real ESP32 by following `docs/hardware-integration-guide.md` with no additional clarification needed.
