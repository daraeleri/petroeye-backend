"""Pure geodesy helpers. No DB/MQTT access here."""
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class FenceHit:
    fence: Any  # any object with .lat, .lon, .radius_m (ORM Geofence in practice)
    distance_m: float


def find_containing_fence(lat: float | None, lon: float | None, fences: Iterable[Any]) -> FenceHit | None:
    """Return the closest fence whose circle contains the point, or None.

    A point with no position (no GPS fix) is never inside a fence — the
    valve may only open where the location is confirmed.
    """
    if lat is None or lon is None:
        return None
    best: FenceHit | None = None
    for fence in fences:
        d = haversine_m(lat, lon, fence.lat, fence.lon)
        if d <= fence.radius_m and (best is None or d < best.distance_m):
            best = FenceHit(fence=fence, distance_m=d)
    return best


def nearest_fence(lat: float | None, lon: float | None, fences: Iterable[Any]) -> FenceHit | None:
    """Closest fence regardless of radius (used to explain alerts)."""
    if lat is None or lon is None:
        return None
    best: FenceHit | None = None
    for fence in fences:
        d = haversine_m(lat, lon, fence.lat, fence.lon)
        if best is None or d < best.distance_m:
            best = FenceHit(fence=fence, distance_m=d)
    return best
