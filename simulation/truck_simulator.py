#!/usr/bin/env python3
"""
PetroTwin truck simulator (schema v2).

Publishes telemetry and status over MQTT exactly as the ESP32 prototype
should, per docs/hardware-integration-guide.md: NEO-6M GPS fields, the
HC-SR04 distance (median-filtered), and the solenoid valve state. Use it to
run and demo the whole stack without hardware.

The simulated tank matches the demo calibration set by `seed_demo.py`
(rectangular 30 × 20 × 25 cm, sensor reads 3 cm when full → 15 L).

Usage (from the backend repo root):
    uv run python simulation/truck_simulator.py --truck-id truck-001 --scenario delivery
    uv run python simulation/truck_simulator.py --truck-id truck-002 --scenario unauthorized_discharge
"""

import argparse
import json
import math
import random
import time
from datetime import UTC, datetime

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
except ImportError:
    raise SystemExit("Missing dependency. Run from the backend repo root: uv run python simulation/truck_simulator.py")

SCHEMA_VERSION = 2

# Yaoundé, Cameroon — purely so traces look plausible on the map.
START_LAT, START_LON = 3.8480, 11.5021
# The demo depot; seed_demo.py creates a fleet-wide geofence here.
DEPOT_LAT, DEPOT_LON = 3.8667, 11.5167
DEPOT_RADIUS_M = 100

# Demo tank (must match seed_demo.py's calibration).
TANK_LENGTH_CM, TANK_WIDTH_CM, TANK_HEIGHT_CM = 30.0, 20.0, 25.0
SENSOR_OFFSET_CM = 3.0
TANK_CAPACITY_L = TANK_LENGTH_CM * TANK_WIDTH_CM * TANK_HEIGHT_CM / 1000  # 15 L

EARTH_R = 6_371_008.8


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def utc_ts() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Truck:
    def __init__(self, truck_id: str, scenario: str, interval: float, speed_kmh: float):
        self.truck_id = truck_id
        self.scenario = scenario
        self.interval = interval
        self.cruise_kmh = speed_kmh
        self.lat = START_LAT + random.uniform(-0.002, 0.002)
        self.lon = START_LON + random.uniform(-0.002, 0.002)
        self.home = (self.lat, self.lon)
        self.speed_kmh = 0.0
        self.course = 0.0
        self.volume_l = TANK_CAPACITY_L * 0.95
        self.valve_open = False
        self.gps_fix = True
        self.echo = True
        self.tick = 0
        self.phase = "drive_out"
        self.phase_ticks = 0
        self.forced_open_done = False
        self.pending_events: list[str] = []  # valve_open_denied reasons to publish

    # --- movement ------------------------------------------------------------

    def _drive_towards(self, lat, lon) -> bool:
        """Move one tick towards (lat, lon). Returns True on arrival."""
        dist = haversine_m(self.lat, self.lon, lat, lon)
        step = self.cruise_kmh / 3.6 * self.interval
        self.course = bearing_deg(self.lat, self.lon, lat, lon)
        if dist <= step:
            self.lat, self.lon, self.speed_kmh = lat, lon, 0.0
            return True
        f = step / dist
        self.lat += (lat - self.lat) * f + random.uniform(-0.00002, 0.00002)
        self.lon += (lon - self.lon) * f + random.uniform(-0.00002, 0.00002)
        self.speed_kmh = self.cruise_kmh + random.uniform(-4, 4)
        return False

    def _set_phase(self, phase):
        self.phase, self.phase_ticks = phase, 0

    # --- scenarios -----------------------------------------------------------

    def _delivery_cycle(self, forced_stop_halfway: bool, deny_only: bool = False):
        """Drive to the depot, discharge inside the geofence, return, refill.

        With forced_stop_halfway, the truck first stops halfway and the valve
        is forced open (the prototype's test button) → unauthorized discharge.
        With deny_only, the firmware's interlock refuses instead (the real
        truck's default): the valve stays closed and a valve_open_denied
        event is published.
        """
        self.phase_ticks += 1
        if self.phase == "drive_out":
            if forced_stop_halfway and not self.forced_open_done:
                total = haversine_m(*self.home, DEPOT_LAT, DEPOT_LON)
                if haversine_m(self.lat, self.lon, DEPOT_LAT, DEPOT_LON) < total / 2:
                    self.speed_kmh = 0.0
                    self._set_phase("forced_open")
                    return
            if self._drive_towards(DEPOT_LAT, DEPOT_LON):
                self._set_phase("arrived")
        elif self.phase == "forced_open":
            if deny_only:
                # TRIANGLE pressed twice outside a zone; the firmware refuses.
                if self.phase_ticks in (1, 4):
                    self.pending_events.append("outside_geofence")
            else:
                # Test button pressed: valve forced open outside the geofence.
                self.valve_open = self.phase_ticks <= 4
                if self.valve_open:
                    self.volume_l -= 0.25
            if self.phase_ticks > 6:
                self.forced_open_done = True
                self._set_phase("drive_out")
        elif self.phase == "arrived":
            self.speed_kmh = 0.0
            if self.phase_ticks >= 2:
                self._set_phase("discharging")
        elif self.phase == "discharging":
            self.valve_open = True
            self.volume_l -= 0.6
            if self.volume_l <= TANK_CAPACITY_L * 0.15 or self.phase_ticks >= 15:
                self.valve_open = False
                self._set_phase("drive_back")
        elif self.phase == "drive_back":
            if self._drive_towards(*self.home):
                self._set_phase("refill")
        elif self.phase == "refill":
            self.speed_kmh = 0.0
            self.volume_l = min(TANK_CAPACITY_L * 0.95, self.volume_l + 1.5)
            if self.volume_l >= TANK_CAPACITY_L * 0.95:
                self.forced_open_done = False
                self._set_phase("drive_out")

    def step(self):
        self.tick += 1
        if self.scenario == "delivery":
            self._delivery_cycle(forced_stop_halfway=False)
        elif self.scenario == "unauthorized_discharge":
            self._delivery_cycle(forced_stop_halfway=True)
        elif self.scenario == "denied_attempt":
            self._delivery_cycle(forced_stop_halfway=True, deny_only=True)
        elif self.scenario == "leak":
            # Parked, valve closed, tank slowly emptying.
            self.speed_kmh = 0.0
            self.volume_l -= 0.45 if self.tick > 5 else 0.0
            if self.volume_l < 1:
                self.volume_l = TANK_CAPACITY_L * 0.9
        elif self.scenario == "gps_loss":
            self._delivery_cycle(forced_stop_halfway=False)
            self.gps_fix = (self.tick % 20) < 15
        elif self.scenario == "sensor_dropout":
            self._delivery_cycle(forced_stop_halfway=False)
            self.echo = (self.tick % 25) < 20
        elif self.scenario == "parked":
            self.speed_kmh = 0.0
        self.volume_l = max(0.0, min(TANK_CAPACITY_L, self.volume_l))

    # --- payloads --------------------------------------------------------------

    def distance_cm(self):
        if not self.echo:
            return None
        level = self.volume_l * 1000 / (TANK_LENGTH_CM * TANK_WIDTH_CM)
        # Median of 5 noisy pings, like the firmware does.
        pings = sorted(SENSOR_OFFSET_CM + (TANK_HEIGHT_CM - level) + random.gauss(0, 0.3) for _ in range(5))
        return round(pings[2], 1)

    def telemetry(self) -> dict:
        fix = self.gps_fix
        return {
            "schema_version": SCHEMA_VERSION,
            "truck_id": self.truck_id,
            "ts": utc_ts(),
            "gps_fix": fix,
            "lat": round(self.lat, 6) if fix else None,
            "lon": round(self.lon, 6) if fix else None,
            "speed_kmh": round(max(0.0, self.speed_kmh), 1) if fix else None,
            "course_deg": round(self.course, 1) if fix else None,
            "sats": random.randint(6, 10) if fix else 0,
            "hdop": round(random.uniform(0.8, 1.6), 2) if fix else None,
            "distance_cm": self.distance_cm(),
            "valve_open": self.valve_open,
        }

    def denied_event(self, reason: str) -> dict:
        fix = self.gps_fix
        return {
            "schema_version": SCHEMA_VERSION,
            "truck_id": self.truck_id,
            "ts": utc_ts(),
            "type": "valve_open_denied",
            "reason": reason,
            "gps_fix": fix,
            "lat": round(self.lat, 6) if fix else None,
            "lon": round(self.lon, 6) if fix else None,
        }

    def status(self, online: bool = True) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "truck_id": self.truck_id,
            "ts": utc_ts(),
            "online": online,
            "firmware_version": "0.2.0-sim",
            "rssi_dbm": random.randint(-80, -55),
            "uptime_s": int(self.tick * self.interval),
        }


SCENARIOS = ["delivery", "unauthorized_discharge", "denied_attempt", "leak", "gps_loss", "sensor_dropout", "parked"]


def main():
    parser = argparse.ArgumentParser(description="PetroTwin truck simulator (schema v2)")
    parser.add_argument("--truck-id", default="truck-001", help="Truck ID (used in the MQTT topic)")
    parser.add_argument("--scenario", default="delivery", choices=SCENARIOS)
    parser.add_argument("--broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port (8883 with --tls)")
    parser.add_argument("--tls", action="store_true", help="Use TLS (managed brokers such as EMQX Cloud Serverless)")
    parser.add_argument("--username", default=None, help="Device MQTT username")
    parser.add_argument("--password", default=None, help="Device MQTT password")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between telemetry publishes")
    parser.add_argument("--speed-kmh", type=float, default=60.0, help="Cruise speed")
    parser.add_argument("--status-every", type=int, default=10, help="Heartbeat every N ticks")
    parser.add_argument("--ticks", type=int, default=None, help="Stop after N ticks (default: run forever)")
    parser.add_argument("--offline-after", type=int, default=None,
                        help="Simulate a hard disconnect (broker fires the Last Will) after N ticks")
    args = parser.parse_args()

    truck = Truck(args.truck_id, args.scenario, args.interval, args.speed_kmh)
    status_topic = f"petrotwin/{args.truck_id}/status"
    telemetry_topic = f"petrotwin/{args.truck_id}/telemetry"

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"truck-{args.truck_id}")
    if args.username:
        client.username_pw_set(args.username, args.password)
    if args.tls:
        client.tls_set()
    client.will_set(status_topic, json.dumps({"schema_version": SCHEMA_VERSION, "truck_id": args.truck_id,
                                              "online": False}), qos=1)
    client.connect(args.broker, args.port, keepalive=15)
    client.loop_start()
    client.publish(status_topic, json.dumps(truck.status(True)), qos=1)
    print(f"[{args.truck_id}] scenario={args.scenario} -> {args.broker}:{args.port}")

    last_valve = truck.valve_open
    try:
        while args.ticks is None or truck.tick < args.ticks:
            truck.step()
            payload = truck.telemetry()
            client.publish(telemetry_topic, json.dumps(payload), qos=1)
            for reason in truck.pending_events:
                client.publish(f"petrotwin/{args.truck_id}/event", json.dumps(truck.denied_event(reason)), qos=1)
                print(f"[{args.truck_id}] valve open REFUSED ({reason}) -> event published")
            truck.pending_events.clear()
            if truck.valve_open != last_valve:
                print(f"[{args.truck_id}] valve {'OPEN' if truck.valve_open else 'closed'} "
                      f"(phase={truck.phase}, {truck.volume_l:.1f} L)")
                last_valve = truck.valve_open
            if truck.tick % args.status_every == 0:
                client.publish(status_topic, json.dumps(truck.status(True)), qos=1)
            if args.offline_after and truck.tick >= args.offline_after:
                print(f"[{args.truck_id}] simulating hard disconnect (LWT)")
                client._sock_close()  # abrupt: no DISCONNECT packet → broker publishes the Last Will
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    client.publish(status_topic, json.dumps(truck.status(False)), qos=1).wait_for_publish(5)
    client.disconnect()
    client.loop_stop()
    print(f"[{args.truck_id}] stopped")


if __name__ == "__main__":
    main()
