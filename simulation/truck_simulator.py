#!/usr/bin/env python3
"""
PetroTwin truck telemetry simulator.

Publishes JSON telemetry to an MQTT broker exactly as a real truck device
should, per docs/hardware-integration-guide.md. Use this to develop and
demo the entire stack without physical hardware.

Usage:
    python truck_simulator.py --truck-id truck-001 --scenario normal
    python truck_simulator.py --truck-id truck-002 --scenario fuel_leak --broker localhost --port 1883
    python truck_simulator.py --truck-id truck-003 --scenario overheat --interval 2

Requires: pip install paho-mqtt
"""

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise SystemExit("Missing dependency. Run: pip install paho-mqtt")

SCHEMA_VERSION = 1

# A small set of plausible starting points around Yaoundé, Cameroon,
# purely so simulated GPS traces look reasonable on a map.
START_LAT, START_LON = 3.8480, 11.5021


class TruckState:
    """Holds the evolving 'true' state of one simulated truck."""

    def __init__(self, truck_id: str, scenario: str):
        self.truck_id = truck_id
        self.scenario = scenario
        self.fuel_level_pct = 95.0
        self.temperature_c = 50.0
        self.pressure_kpa = 101.3
        self.lat = START_LAT + random.uniform(-0.01, 0.01)
        self.lon = START_LON + random.uniform(-0.01, 0.01)
        self.tilt_deg = 0.5
        self.flow_rate_lpm = 0.0
        self.hatch_open = False
        self.tick = 0

    def step(self):
        """Advance the truck's state by one tick according to its scenario."""
        self.tick += 1
        scenario_fn = SCENARIOS.get(self.scenario, scenario_normal)
        scenario_fn(self)

        # Gentle route drift for every scenario, so the truck always "moves."
        self.lat += random.uniform(-0.0005, 0.0005)
        self.lon += random.uniform(-0.0005, 0.0005)

        # Clamp to physically sane ranges.
        self.fuel_level_pct = max(0.0, min(100.0, self.fuel_level_pct))
        self.temperature_c = max(-10.0, min(150.0, self.temperature_c))
        self.pressure_kpa = max(0.0, min(300.0, self.pressure_kpa))
        self.tilt_deg = max(0.0, min(90.0, self.tilt_deg))
        self.flow_rate_lpm = max(0.0, self.flow_rate_lpm)

    def to_payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "truck_id": self.truck_id,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fuel_level_pct": round(self.fuel_level_pct, 2),
            "temperature_c": round(self.temperature_c, 2),
            "pressure_kpa": round(self.pressure_kpa, 2),
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "tilt_deg": round(self.tilt_deg, 2),
            "flow_rate_lpm": round(self.flow_rate_lpm, 2),
            "hatch_open": self.hatch_open,
        }

    def status_payload(self, online: bool = True) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "truck_id": self.truck_id,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "online": online,
            "battery_pct": max(0, 100 - self.tick // 20),
            "firmware_version": "0.1.0-sim",
        }


# ---------------------------------------------------------------------------
# Scenarios. Each function mutates a TruckState in place for one tick.
# Add new scenarios here AND in docs/skills-recommendations.md's
# mqtt-scenario-simulator notes if the behavior needs documenting further.
# ---------------------------------------------------------------------------

def scenario_normal(s: TruckState):
    """Normal transit: slow fuel burn, stable temp/pressure, no anomalies."""
    s.fuel_level_pct -= 0.03 + random.uniform(0, 0.02)
    s.temperature_c += random.uniform(-0.3, 0.3)
    s.pressure_kpa += random.uniform(-0.2, 0.2)
    s.tilt_deg = abs(random.gauss(1.0, 0.5))
    s.flow_rate_lpm = 0.0
    s.hatch_open = False


def scenario_fuel_leak(s: TruckState):
    """Fuel drops far faster than normal burn rate — should trip a rule alert."""
    s.fuel_level_pct -= 0.6 + random.uniform(0, 0.3)
    s.temperature_c += random.uniform(-0.2, 0.2)
    s.pressure_kpa -= 0.1
    s.tilt_deg = abs(random.gauss(1.0, 0.5))
    s.flow_rate_lpm = round(random.uniform(1.5, 3.0), 2)
    s.hatch_open = False


def scenario_overheat(s: TruckState):
    """Temperature climbs steadily toward a dangerous range."""
    s.temperature_c += 0.7 + random.uniform(0, 0.3)
    s.pressure_kpa += 0.3  # pressure rises with heat
    s.fuel_level_pct -= 0.03
    s.tilt_deg = abs(random.gauss(1.0, 0.5))
    s.flow_rate_lpm = 0.0
    s.hatch_open = False


def scenario_rollover_risk(s: TruckState):
    """Tilt angle climbs sharply — simulates a sharp turn / uneven terrain risk."""
    s.tilt_deg += random.uniform(1.0, 4.0)
    s.fuel_level_pct -= 0.03
    s.temperature_c += random.uniform(-0.2, 0.2)
    s.flow_rate_lpm = 0.0
    s.hatch_open = False


def scenario_tamper(s: TruckState):
    """Hatch opens unexpectedly while stationary — simulates unauthorized access."""
    s.hatch_open = True if s.tick % 5 != 0 else False
    s.fuel_level_pct -= random.uniform(0.1, 0.4)  # possible siphoning
    s.temperature_c += random.uniform(-0.2, 0.2)
    s.tilt_deg = abs(random.gauss(0.5, 0.3))
    s.flow_rate_lpm = round(random.uniform(0.5, 1.5), 2)


def scenario_sensor_dropout(s: TruckState):
    """Occasionally emits clearly-flagged stale/frozen-looking readings.

    Note: real dropouts usually mean *no message at all*. This scenario
    instead sends repeated identical values to exercise "stale data" style
    detection separately from a true connection loss (use --offline for that).
    """
    if s.tick % 10 < 3:
        pass  # freeze state this tick (don't update anything)
    else:
        scenario_normal(s)


def scenario_gps_route_deviation(s: TruckState):
    """Truck drifts far from the expected corridor — simulates route deviation."""
    s.lat += random.uniform(0.01, 0.02) * random.choice([-1, 1])
    s.lon += random.uniform(0.01, 0.02) * random.choice([-1, 1])
    s.fuel_level_pct -= 0.05
    s.temperature_c += random.uniform(-0.2, 0.5)
    s.tilt_deg = abs(random.gauss(1.0, 0.5))
    s.flow_rate_lpm = 0.0
    s.hatch_open = False


SCENARIOS = {
    "normal": scenario_normal,
    "fuel_leak": scenario_fuel_leak,
    "overheat": scenario_overheat,
    "rollover_risk": scenario_rollover_risk,
    "tamper": scenario_tamper,
    "sensor_dropout": scenario_sensor_dropout,
    "gps_route_deviation": scenario_gps_route_deviation,
}


def main():
    parser = argparse.ArgumentParser(description="PetroTwin truck telemetry simulator")
    parser.add_argument("--truck-id", default="truck-001", help="Truck ID (matches the MQTT topic)")
    parser.add_argument("--scenario", default="normal", choices=sorted(SCENARIOS.keys()),
                         help="Fault scenario to simulate")
    parser.add_argument("--broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--username", default=None, help="Device MQTT username")
    parser.add_argument("--password", default=None, help="Device MQTT password")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between telemetry publishes")
    parser.add_argument("--status-every", type=int, default=10,
                         help="Publish a status/heartbeat message every N telemetry ticks")
    parser.add_argument("--offline-after", type=int, default=None,
                         help="If set, simulate a hard disconnect (no LWT) after N ticks, to test offline detection")
    args = parser.parse_args()

    state = TruckState(args.truck_id, args.scenario)

    client = mqtt.Client(client_id=f"truck-{args.truck_id}-sim")
    if args.username:
        client.username_pw_set(args.username, args.password)

    # Last Will and Testament: if this simulator dies uncleanly, the broker
    # publishes an offline status on our behalf, matching what real hardware
    # should also configure per docs/hardware-integration-guide.md.
    lwt_payload = json.dumps({
        "schema_version": SCHEMA_VERSION,
        "truck_id": args.truck_id,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "online": False,
        "battery_pct": None,
        "firmware_version": "0.1.0-sim",
    })
    client.will_set(f"petrotwin/{args.truck_id}/status", lwt_payload, qos=1, retain=False)

    print(f"[sim] Connecting to {args.broker}:{args.port} as {args.truck_id} (scenario={args.scenario})")
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    telemetry_topic = f"petrotwin/{args.truck_id}/telemetry"
    status_topic = f"petrotwin/{args.truck_id}/status"

    try:
        while True:
            if args.offline_after and state.tick >= args.offline_after:
                print(f"[sim] Simulating hard disconnect after {state.tick} ticks.")
                client.loop_stop()
                client._sock_close() if hasattr(client, "_sock_close") else None
                break

            state.step()
            payload = state.to_payload()
            client.publish(telemetry_topic, json.dumps(payload), qos=1)
            print(f"[sim] {telemetry_topic} -> {payload}")

            if state.tick % args.status_every == 0:
                status = state.status_payload(online=True)
                client.publish(status_topic, json.dumps(status), qos=1)
                print(f"[sim] {status_topic} -> {status}")

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[sim] Stopped by user. Publishing clean offline status.")
        client.publish(status_topic, json.dumps(state.status_payload(online=False)), qos=1)
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
