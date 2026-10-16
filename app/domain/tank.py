"""
Tank geometry: ultrasonic distance → liquid level → volume. Pure functions.

The HC-SR04 is mounted at the top of the tank pointing down. It measures
the distance from the sensor face to the liquid surface:

    level_cm = inner_height_cm - (distance_cm - sensor_offset_cm)

where `sensor_offset_cm` is what the sensor reads when the tank is full.
Level is clamped to [0, inner_height]. For a horizontal cylinder the
inner height is the diameter.
"""
import math
from dataclasses import dataclass

CM3_PER_LITRE = 1000.0


@dataclass(frozen=True)
class TankGeometry:
    shape: str  # rectangular | vertical_cylinder | horizontal_cylinder
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    diameter_cm: float | None = None
    sensor_offset_cm: float = 0.0


class InvalidGeometry(ValueError):
    pass


def validate_geometry(g: TankGeometry) -> None:
    """Raise InvalidGeometry if the dimensions needed for the shape are missing."""
    required = {
        "rectangular": ("length_cm", "width_cm", "height_cm"),
        "vertical_cylinder": ("diameter_cm", "height_cm"),
        "horizontal_cylinder": ("diameter_cm", "length_cm"),
    }.get(g.shape)
    if required is None:
        raise InvalidGeometry(f"Unknown tank shape '{g.shape}'")
    missing = [f for f in required if not getattr(g, f) or getattr(g, f) <= 0]
    if missing:
        raise InvalidGeometry(f"Shape '{g.shape}' needs positive values for: {', '.join(missing)}")
    if g.sensor_offset_cm < 0:
        raise InvalidGeometry("sensor_offset_cm must be >= 0")


def inner_height_cm(g: TankGeometry) -> float:
    return g.diameter_cm if g.shape == "horizontal_cylinder" else g.height_cm  # type: ignore[return-value]


def level_from_distance(g: TankGeometry, distance_cm: float) -> float:
    h = inner_height_cm(g)
    level = h - (distance_cm - g.sensor_offset_cm)
    return max(0.0, min(h, level))


def volume_from_level(g: TankGeometry, level_cm: float) -> float:
    """Liquid volume in litres for a given level."""
    if g.shape == "rectangular":
        cm3 = g.length_cm * g.width_cm * level_cm  # type: ignore[operator]
    elif g.shape == "vertical_cylinder":
        r = g.diameter_cm / 2  # type: ignore[operator]
        cm3 = math.pi * r * r * level_cm
    elif g.shape == "horizontal_cylinder":
        # Area of a circular segment of height `level` times the length.
        r = g.diameter_cm / 2  # type: ignore[operator]
        h = max(0.0, min(2 * r, level_cm))
        area = r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(max(0.0, 2 * r * h - h * h))
        cm3 = area * g.length_cm  # type: ignore[operator]
    else:
        raise InvalidGeometry(f"Unknown tank shape '{g.shape}'")
    return cm3 / CM3_PER_LITRE


def capacity_litres(g: TankGeometry) -> float:
    return volume_from_level(g, inner_height_cm(g))


def measure(g: TankGeometry | None, distance_cm: float | None) -> tuple[float | None, float | None]:
    """(level_cm, volume_l) for a reading; (None, None) if not computable."""
    if g is None or distance_cm is None:
        return None, None
    level = level_from_distance(g, distance_cm)
    return round(level, 2), round(volume_from_level(g, level), 2)
