#!/usr/bin/env python3
"""
Runs several truck_simulator.py instances at once as subprocesses, so you
can demo a live fleet on the dashboard without opening N terminals.

Usage (from the backend repo root):
    uv run python simulation/fleet_runner.py --broker localhost --port 1883

Run `simulation/seed_demo.py` once first so the tanks are calibrated and the
depot geofence exists. Edit FLEET below to change trucks/scenarios.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SIMULATOR = Path(__file__).with_name("truck_simulator.py")

FLEET = [
    {"truck_id": "truck-001", "scenario": "delivery"},
    {"truck_id": "truck-002", "scenario": "unauthorized_discharge"},
    {"truck_id": "truck-003", "scenario": "leak"},
    {"truck_id": "truck-004", "scenario": "gps_loss"},
]


def main():
    parser = argparse.ArgumentParser(description="Run a simulated PetroTwin fleet")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()

    procs = []
    for truck in FLEET:
        cmd = [
            sys.executable, str(SIMULATOR),
            "--truck-id", truck["truck_id"],
            "--scenario", truck["scenario"],
            "--broker", args.broker,
            "--port", str(args.port),
            "--interval", str(args.interval),
        ]
        if args.tls:
            cmd.append("--tls")
        if args.username:
            cmd += ["--username", args.username, "--password", args.password or ""]
        print(f"[fleet] Launching {truck['truck_id']} ({truck['scenario']})")
        procs.append(subprocess.Popen(cmd))
        time.sleep(0.3)

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n[fleet] Stopping fleet...")
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
