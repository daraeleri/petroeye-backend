#!/usr/bin/env python3
"""
Runs multiple truck_simulator.py instances at once as subprocesses, so you
can demo a live fleet on the dashboard without opening N terminals.

Usage:
    python fleet_runner.py --broker localhost --port 1883

Edit FLEET below to control how many trucks and which scenarios run.
"""

import subprocess
import sys
import time
import argparse
from pathlib import Path

SIMULATOR = Path(__file__).with_name("truck_simulator.py")

FLEET = [
    {"truck_id": "truck-001", "scenario": "normal"},
    {"truck_id": "truck-002", "scenario": "normal"},
    {"truck_id": "truck-003", "scenario": "fuel_leak"},
    {"truck_id": "truck-004", "scenario": "overheat"},
    {"truck_id": "truck-005", "scenario": "tamper"},
]


def main():
    parser = argparse.ArgumentParser(description="Run a simulated PetroTwin fleet")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
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
        print(f"[fleet] Launching {truck['truck_id']} ({truck['scenario']})")
        procs.append(subprocess.Popen(cmd))
        time.sleep(0.5)  # stagger connects slightly

    print(f"[fleet] {len(procs)} simulated trucks running. Ctrl+C to stop all.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[fleet] Stopping all simulated trucks...")
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait()
        print("[fleet] Done.")


if __name__ == "__main__":
    main()
