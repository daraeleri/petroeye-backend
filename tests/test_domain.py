from types import SimpleNamespace

import pytest

from app.domain.geo import find_containing_fence, haversine_m, nearest_fence
from app.domain.tank import (
    InvalidGeometry,
    TankGeometry,
    capacity_litres,
    level_from_distance,
    measure,
    validate_geometry,
    volume_from_level,
)


def test_haversine_known_distance():
    # 0.001° of latitude ≈ 111.2 m
    assert haversine_m(3.0, 11.0, 3.001, 11.0) == pytest.approx(111.2, abs=0.5)


def test_fence_containment_and_nearest():
    a = SimpleNamespace(id="a", name="A", lat=3.0, lon=11.0, radius_m=100)
    b = SimpleNamespace(id="b", name="B", lat=3.01, lon=11.0, radius_m=100)
    hit = find_containing_fence(3.0005, 11.0, [a, b])  # ~55 m from A
    assert hit is not None and hit.fence is a
    assert find_containing_fence(3.005, 11.0, [a, b]) is None  # ~550 m from both
    assert nearest_fence(3.008, 11.0, [a, b]).fence is b
    assert find_containing_fence(None, None, [a, b]) is None  # no GPS fix → never inside


RECT = TankGeometry(shape="rectangular", length_cm=30, width_cm=20, height_cm=25, sensor_offset_cm=3)


def test_rectangular_tank():
    assert capacity_litres(RECT) == pytest.approx(15.0)
    # Full: sensor reads the offset.
    assert level_from_distance(RECT, 3) == 25
    # Empty or beyond: clamped to 0.
    assert level_from_distance(RECT, 28) == 0
    assert level_from_distance(RECT, 40) == 0
    # Closer than the offset (splash/foam): clamped to full.
    assert level_from_distance(RECT, 1) == 25
    level, volume = measure(RECT, 15.5)  # 12.5 cm of liquid
    assert level == 12.5 and volume == pytest.approx(7.5)


def test_horizontal_cylinder_half_full_is_half_capacity():
    g = TankGeometry(shape="horizontal_cylinder", diameter_cm=100, length_cm=200)
    assert volume_from_level(g, 50) == pytest.approx(capacity_litres(g) / 2, rel=1e-9)


def test_vertical_cylinder():
    g = TankGeometry(shape="vertical_cylinder", diameter_cm=20, height_cm=50)
    assert capacity_litres(g) == pytest.approx(3.14159 * 10 * 10 * 50 / 1000, rel=1e-4)


def test_measure_without_calibration_or_echo():
    assert measure(None, 10) == (None, None)
    assert measure(RECT, None) == (None, None)


def test_validate_geometry():
    validate_geometry(RECT)
    with pytest.raises(InvalidGeometry):
        validate_geometry(TankGeometry(shape="rectangular", length_cm=30, width_cm=20))
    with pytest.raises(InvalidGeometry):
        validate_geometry(TankGeometry(shape="sphere"))
