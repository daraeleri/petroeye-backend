# PetroTwin Simulation

Publishes synthetic truck telemetry to the MQTT broker so the whole stack
(backend, dashboard, AI rules, Web3 anchoring) can be built and demoed before
the physical prototype exists — and continues to be useful afterward for
regression-testing fault scenarios that are hard to trigger on a real truck.

## Quick start

```bash
# From the backend repo root (uses the backend uv environment, which includes paho-mqtt):

# Bring up a local broker first, e.g.:
docker compose up -d

# One truck, normal operation:
uv run python simulation/truck_simulator.py --truck-id truck-001 --scenario normal

# One truck, faulty:
uv run python simulation/truck_simulator.py --truck-id truck-003 --scenario fuel_leak

# A whole simulated fleet at once (edit FLEET in fleet_runner.py to customize):
uv run python simulation/fleet_runner.py
```

## Available scenarios

| Scenario | What it simulates | Should trigger |
| -------- | ------------------ | ---------------- |
| `normal` | Steady transit, slow fuel burn | No alerts |
| `fuel_leak` | Fuel drops far faster than normal burn rate | Fuel-drop-rate rule alert |
| `overheat` | Temperature climbs steadily | Temperature-ceiling rule alert |
| `rollover_risk` | Tilt angle climbs sharply | Tilt-angle rule alert |
| `tamper` | Hatch opens unexpectedly while stationary, fuel drains | Hatch/tamper rule alert |
| `sensor_dropout` | Readings freeze/repeat for several ticks | Stale-data detection (if implemented) |
| `gps_route_deviation` | Truck drifts far off its expected path | Route-deviation rule alert |

Use `--offline-after N` on `truck_simulator.py` to simulate a hard, unclean
disconnect after N ticks (tests the broker's Last Will and Testament path
and the dashboard's "truck went offline" handling) — separate from a graceful
Ctrl+C, which publishes a clean offline status.

## Adding a new scenario

1. Confirm the anomaly type is defined in the Phase 1 rules config (`ai-anomaly` agent's scope) — don't add a simulator scenario for a rule that doesn't exist yet.
2. Add a `scenario_*` function in `truck_simulator.py` following the existing pattern (mutate a `TruckState` in place for one tick).
3. Register it in the `SCENARIOS` dict.
4. Add a row to the table above.
5. If it requires a new telemetry field, that's a `docs/hardware-integration-guide.md` change first — coordinate with the backend/hardware contract, don't just add a field to the simulator.
