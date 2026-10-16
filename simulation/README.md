# PetroTwin Simulation

Publishes synthetic truck telemetry (schema v2) to the MQTT broker exactly like the
ESP32 prototype, so the whole stack can be run and demoed without hardware — and keeps
being useful afterwards for faults that are hard to trigger on the real truck.

## Quick start

From the backend repo root (uses the backend's uv environment):

```bash
# Broker + DB running, backend running, then once:
uv run python simulation/seed_demo.py --api http://localhost:8000 --email <admin> --password <pw>

# One truck:
uv run python simulation/truck_simulator.py --truck-id truck-001 --scenario delivery

# The demo fleet (edit FLEET in fleet_runner.py to customise):
uv run python simulation/fleet_runner.py
```

`seed_demo.py` registers the fleet trucks, calibrates each tank to the simulator's demo
tank (rectangular 30 × 20 × 25 cm, sensor reads 3 cm when full → 15 L), and creates the
fleet-wide **Demo depot** geofence (100 m) the trucks drive to.

## Scenarios

| Scenario | What it simulates | Expected result |
|---|---|---|
| `delivery` | Drive to the depot, open the valve inside the geofence, return, refill | Authorized discharge, no alerts |
| `unauthorized_discharge` | Stops halfway and the valve is **forced open** (the prototype's test button), then a normal delivery | Critical `valve_open_outside_geofence` + an unauthorized discharge, then an authorized one |
| `denied_attempt` | Stops halfway and TRIANGLE is pressed twice; the truck's interlock **refuses** (like the real firmware), then a normal delivery | One critical `valve_open_denied` alert (cooldown absorbs the 2nd press), no discharge at the stop |
| `leak` | Parked, valve closed, volume keeps dropping | One `volume_drop_valve_closed` warning (10-minute cooldown) |
| `gps_loss` | Delivery cycle with periodic GPS fix loss | `gps_fix_lost` info alerts |
| `sensor_dropout` | Delivery cycle where the ultrasonic sensor stops echoing | `level_sensor_no_echo` warnings |
| `parked` | Stationary, nothing happening | No alerts |

Options: `--interval` (seconds between readings, default 3), `--speed-kmh` (default 60;
the schema rejects > 300), `--ticks N` (stop after N readings), `--tls --port 8883
--username --password` for a managed broker.

`--offline-after N` simulates an abrupt disconnect after N readings: the broker
publishes the truck's Last Will, which raises `device_offline`. Stopping with Ctrl+C is a
clean shutdown (`online: false` with a timestamp) — logged as activity, no alert.
