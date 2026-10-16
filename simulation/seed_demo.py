#!/usr/bin/env python3
"""
Prepares a running backend for the simulator demo through the REST API:
registers the fleet trucks, sets their tank calibration to the simulator's
demo tank, and creates the fleet-wide "Demo depot" geofence.

Safe to run repeatedly (existing trucks/geofence are reused).

Usage (from the backend repo root, backend running):
    uv run python simulation/seed_demo.py --api http://localhost:8000 --email admin@example.com --password ...
"""

import argparse
import sys

import httpx

from fleet_runner import FLEET
from truck_simulator import (
    DEPOT_LAT,
    DEPOT_LON,
    DEPOT_RADIUS_M,
    SENSOR_OFFSET_CM,
    TANK_HEIGHT_CM,
    TANK_LENGTH_CM,
    TANK_WIDTH_CM,
)

DEPOT_NAME = "Demo depot"


def main():
    parser = argparse.ArgumentParser(description="Seed the backend for the simulator demo")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", required=True, help="Admin email")
    parser.add_argument("--password", required=True, help="Admin password")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=15) as api:
        r = api.post("/auth/login", data={"username": args.email, "password": args.password})
        if r.status_code != 200:
            sys.exit(f"Login failed ({r.status_code}): {r.text}")
        api.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

        for truck in FLEET:
            tid = truck["truck_id"]
            r = api.post("/trucks", json={"truck_id": tid, "notes": f"Simulator: {truck['scenario']}"})
            print(f"truck {tid}: {'registered' if r.status_code == 201 else 'exists' if r.status_code == 409 else r.text}")
            r = api.put(f"/trucks/{tid}/tank", json={
                "shape": "rectangular", "length_cm": TANK_LENGTH_CM, "width_cm": TANK_WIDTH_CM,
                "height_cm": TANK_HEIGHT_CM, "sensor_offset_cm": SENSOR_OFFSET_CM,
            })
            r.raise_for_status()
            print(f"  tank calibrated: {r.json()['capacity_l']} L")

        fences = api.get("/geofences").json()
        if any(f["name"] == DEPOT_NAME for f in fences):
            print(f"geofence '{DEPOT_NAME}' exists")
        else:
            r = api.post("/geofences", json={
                "name": DEPOT_NAME, "description": "Approved discharge point for the simulated fleet",
                "lat": DEPOT_LAT, "lon": DEPOT_LON, "radius_m": DEPOT_RADIUS_M,
            })
            r.raise_for_status()
            print(f"geofence '{DEPOT_NAME}' created ({DEPOT_RADIUS_M} m)")


if __name__ == "__main__":
    main()
