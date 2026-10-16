# Hardware Integration Guide (For the Physical Prototype Team)

This is the contract between the physical truck prototype and the PetroTwin software stack. If you are building/wiring the truck's sensor unit, this file tells you exactly what to publish, where, and in what format. **If anything here needs to change, flag it — don't silently deviate**, since the backend validates against this schema and will reject anything else.

> **Status: schema v2 (target).** v2 replaces the original v1 draft, which assumed temperature/pressure/tilt/flow/hatch sensors the prototype does not have. The backend and simulator still only accept v1 until the ingestion rewrite lands — see `progress-tracker.md`. Firmware should be written against v2.

## 0. Hardware on the Truck

| Component | Part | Role |
| --------- | ---- | ---- |
| Controller | ESP32 | Reads sensors, drives the valve, publishes over MQTT |
| Positioning | u-blox NEO-6M (`neo-6m-0-001`) | GPS position, speed, course, fix quality |
| Tank level | HC-SR04 ultrasonic | Distance from the sensor (top of tank) down to the liquid surface |
| Discharge valve | FDP-270A solenoid valve | Opened/closed **locally by the ESP32 only** |

**Valve control is local.** The ESP32 decides when the valve opens or closes. The backend never sends commands to the truck, and there is no command topic — the dashboard only displays the valve state the device reports.

**Safety (prototype only):** the HC-SR04 is not sealed or intrinsically safe. Test with water, not petrol. A real fuel tank needs a sealed/ATEX-rated level sensor.

## 1. Connecting to the MQTT Broker

| Setting            | Dev / simulation | Staging (proposed — see Open Questions) |
| ------------------ | ---------------- | --------------------------------------- |
| Host               | `localhost` (or the dev machine IP given to you) | HiveMQ Cloud cluster host (given to you by the project admin) |
| Port               | `1883` (plain)   | `8883` (TLS required) |
| TLS                | off              | on — use `WiFiClientSecure` with the broker's root CA certificate |
| Client ID          | `truck-{truck_id}` (unique per device) | same |
| Username / Password | Issued per device by the project admin | same |
| Keep-alive         | 60 seconds       | same |
| Clean session      | `false` recommended, so the broker can hold QoS 1 messages across short disconnects | same |

Each truck gets its own device credentials. Do not reuse credentials across trucks — the backend maps device identity to a specific `truck_id`, and shared credentials break the audit trail.

## 2. Topics

| Topic | Direction | QoS | Purpose |
| ----- | --------- | --- | ------- |
| `petrotwin/{truck_id}/telemetry` | Device → Backend | 1 | Regular sensor readings |
| `petrotwin/{truck_id}/status` | Device → Backend | 1 | Heartbeat / online-offline / device health (also the LWT topic) |

There are no Backend → Device topics. The device must not subscribe to anything to receive commands.

`{truck_id}` is the ID assigned to your unit when it's registered in the system (ask the project admin — do not invent your own ID scheme).

## 3. Telemetry Payload Schema (v2)

Publish JSON to `petrotwin/{truck_id}/telemetry`. Field names are flat (no nested objects) to keep ArduinoJson code simple.

```json
{
  "schema_version": 2,
  "truck_id": "truck-001",
  "ts": "2026-10-16T10:32:05Z",
  "gps_fix": true,
  "lat": 3.848012,
  "lon": 11.502134,
  "speed_kmh": 42.5,
  "course_deg": 187.0,
  "sats": 8,
  "hdop": 1.1,
  "distance_cm": 37.4,
  "valve_open": false
}
```

| Field | Type | Required | Unit / Notes |
| ----- | ---- | -------- | ------------ |
| `schema_version` | int | yes | `2`. Bump only after coordinating with the backend team. |
| `truck_id` | string | yes | Must match the topic's `{truck_id}`. |
| `ts` | string (ISO 8601, UTC, `Z` suffix) | yes | Time the readings were taken. Source: NTP sync at boot, or GPS time once there's a fix. If the device has no valid time from either, don't publish telemetry yet. |
| `gps_fix` | bool | yes | `true` only when the NEO-6M reports a valid location fix. |
| `lat`, `lon` | float \| null | yes | WGS84 decimal degrees, 6 decimals. `null` when `gps_fix` is `false` — never send `0,0` or a stale position. |
| `speed_kmh` | float \| null | yes | Ground speed from GPS. `null` without a fix. |
| `course_deg` | float \| null | yes | Heading 0–360 from GPS. `null` without a fix. |
| `sats` | int | yes | Satellites in use (0 without a fix). |
| `hdop` | float \| null | yes | Horizontal dilution of precision. `null` without a fix. |
| `distance_cm` | float \| null | yes | HC-SR04 distance from the sensor face to the liquid surface, **median of 5 pings** taken ≥ 60 ms apart. `null` if the echo times out or is outside 2–400 cm. Send raw distance — do **not** convert to level or volume on the device. |
| `valve_open` | bool | yes | Current commanded state of the solenoid valve (`true` = energised/open). |

**Why raw distance:** the backend converts `distance_cm` → liquid level → volume (litres) using each truck's tank shape, dimensions and sensor mounting offset, stored per truck. Recalibration then never needs a firmware reflash.

**Publish frequency:**
- Every 2–5 seconds while moving (`speed_kmh` > ~3) or while the valve is open.
- Every 30 seconds while parked with the valve closed.
- **Immediately** whenever `valve_open` changes state (don't wait for the next interval).

If your hardware can't hit these rates yet, publish at whatever interval you have and flag it as an open question — don't fake a faster rate.

## 4. Status / Heartbeat Payload

Publish to `petrotwin/{truck_id}/status` on connect, at least every 60 seconds, and before a clean disconnect:

```json
{
  "schema_version": 2,
  "truck_id": "truck-001",
  "ts": "2026-10-16T10:32:00Z",
  "online": true,
  "firmware_version": "0.1.0",
  "rssi_dbm": -67,
  "uptime_s": 3600
}
```

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `schema_version` | int | yes | `2` |
| `truck_id` | string | yes | Must match the topic. |
| `ts` | string (ISO 8601 UTC) | yes | As for telemetry. |
| `online` | bool | yes | `true` on heartbeats; `false` in the LWT message. |
| `firmware_version` | string | no | Semver of the running firmware. |
| `rssi_dbm` | int | no | Signal strength of the network link (WiFi or cellular). |
| `uptime_s` | int | no | Seconds since boot — helps spot brown-out resets. |

Configure MQTT **Last Will and Testament** on this topic with `{"schema_version":2,"truck_id":"truck-001","online":false}` (retain = false, QoS 1). The LWT is the one message allowed to omit `ts`, since it's composed at connect time. This lets the dashboard show "offline" accurately instead of just going stale.

## 5. What NOT to Do

- Don't publish single raw ultrasonic pings — always the median of several; the rule engine treats jumps in volume as real leaks.
- Don't send `lat`/`lon` of `0,0` or a last-known position when there's no fix — send `null` and `gps_fix: false`.
- Don't invent new fields without coordinating — the backend validates strictly and will reject unknown/malformed payloads (and log the rejection).
- Don't hardcode broker credentials into firmware that gets committed anywhere public — keep them in an untracked `secrets.h`.
- Don't skip `schema_version` — it's how we evolve the format without breaking either side.
- Don't add a command/control subscription for the valve. Valve logic stays on the ESP32.

## 6. Testing Before You Wire Real Firmware

Validate your payload format against the dev broker with `mosquitto_pub` before writing firmware:

```bash
mosquitto_pub -h localhost -p 1883 \
  -u "truck-001" -P "<device-password>" \
  -t "petrotwin/truck-001/telemetry" \
  -m '{"schema_version":2,"truck_id":"truck-001","ts":"2026-10-16T10:32:05Z","gps_fix":true,"lat":3.848012,"lon":11.502134,"speed_kmh":42.5,"course_deg":187.0,"sats":8,"hdop":1.1,"distance_cm":37.4,"valve_open":false}'
```

If it's accepted, you'll see the truck update live on the dashboard. If it's rejected, the backend logs show which field failed validation — check there first before asking.

## 7. Checklist Before Connecting Real Hardware

- [ ] Device credentials issued and confirmed working against the dev broker.
- [ ] `truck_id` registered on the backend (ask project admin — not self-assigned).
- [ ] Tank shape, inner dimensions and sensor mounting offset sent to the backend team for calibration.
- [ ] Telemetry payload validated via the `mosquitto_pub` test above.
- [ ] Heartbeat/status topic publishing on the expected interval.
- [ ] LWT configured.
- [ ] Valve state change triggers an immediate telemetry publish.
- [ ] Confirmed with the software team which `schema_version` is currently expected.

## Escalation

If you need a field added/changed, a different publish frequency, or a different auth model — don't just change it on your end. Open it as a question against `progress-tracker.md` (or ping the project admin directly) so the backend schema and this document get updated together.
