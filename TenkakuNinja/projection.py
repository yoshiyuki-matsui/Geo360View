"""QGIS-independent projection helpers for 360 semantic targets."""

from __future__ import annotations

from dataclasses import dataclass
import math


EARTH_RADIUS_M = 6378137.0
DEFAULT_TRAJECTORY_WINDOW_FRAMES = 10
MIN_TRAJECTORY_DISTANCE_M = 0.05


@dataclass(frozen=True)
class GeoPoint:
    """WGS84 latitude/longitude point."""

    lat: float
    lon: float


@dataclass(frozen=True)
class HeadingResult:
    """Trajectory-derived heading and the baseline used to calculate it."""

    heading_deg: float
    distance_m: float
    method: str
    before_frame: int | None = None
    after_frame: int | None = None


def normalize_angle_deg(value: float) -> float:
    """Normalize an angle to 0..360 degrees."""

    return float(value) % 360.0


def signed_angle_delta_deg(angle_a: float, angle_b: float) -> float:
    """Return signed delta from angle_a to angle_b in -180..180 degrees."""

    return (float(angle_b) - float(angle_a) + 180.0) % 360.0 - 180.0


def heading_delta_deg(heading_a: float, heading_b: float) -> float:
    """Return absolute shortest difference between two headings."""

    return abs(signed_angle_delta_deg(heading_b, heading_a))


def destination_point(
    lat: float,
    lon: float,
    bearing_deg: float,
    distance_m: float,
) -> GeoPoint:
    """Return WGS84 point reached from lat/lon by bearing and distance."""

    bearing = math.radians(float(bearing_deg))
    angular_distance = float(distance_m) / EARTH_RADIUS_M
    lat1 = math.radians(float(lat))
    lon1 = math.radians(float(lon))

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return GeoPoint(lat=math.degrees(lat2), lon=math.degrees(lon2))


def local_vector_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> tuple[float, float]:
    """Return short-distance local vector as east dx and north dy meters."""

    mean_lat = math.radians((float(lat1) + float(lat2)) / 2.0)
    dx = math.radians(float(lon2) - float(lon1)) * EARTH_RADIUS_M * math.cos(mean_lat)
    dy = math.radians(float(lat2) - float(lat1)) * EARTH_RADIUS_M
    return dx, dy


def heading_from_vector(dx: float, dy: float) -> float:
    """Return heading where north is 0 degrees and clockwise is positive."""

    return normalize_angle_deg(math.degrees(math.atan2(float(dx), float(dy))))


def distance_between_points_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return approximate short-distance between two WGS84 points."""

    dx, dy = local_vector_meters(lat1, lon1, lat2, lon2)
    return math.hypot(dx, dy)


def _valid_point(value: GeoPoint | None) -> bool:
    return value is not None and value.lat is not None and value.lon is not None


def _heading_from_points(
    before_frame: int,
    before: GeoPoint,
    after_frame: int,
    after: GeoPoint,
    method: str,
) -> HeadingResult | None:
    dx, dy = local_vector_meters(before.lat, before.lon, after.lat, after.lon)
    distance_m = math.hypot(dx, dy)
    if distance_m < MIN_TRAJECTORY_DISTANCE_M:
        return None
    return HeadingResult(
        heading_deg=heading_from_vector(dx, dy),
        distance_m=distance_m,
        method=method,
        before_frame=before_frame,
        after_frame=after_frame,
    )


def trajectory_heading(
    positions_by_frame: dict[int, GeoPoint],
    frame_index: int,
    window_frames: int = DEFAULT_TRAJECTORY_WINDOW_FRAMES,
) -> HeadingResult | None:
    """Return trajectory heading around a frame, matching radar.py behavior."""

    frame_index = int(frame_index)
    window_frames = max(1, int(window_frames))
    center = positions_by_frame.get(frame_index)
    has_center = _valid_point(center)

    for offset in range(window_frames, 0, -1):
        before_frame = frame_index - offset
        after_frame = frame_index + offset
        before = positions_by_frame.get(before_frame)
        after = positions_by_frame.get(after_frame)
        if not _valid_point(before) or not _valid_point(after):
            continue
        result = _heading_from_points(
            before_frame,
            before,
            after_frame,
            after,
            "before_after",
        )
        if result is not None:
            return result

    if not has_center:
        return None

    assert center is not None
    for offset in range(window_frames, 0, -1):
        after_frame = frame_index + offset
        after = positions_by_frame.get(after_frame)
        if _valid_point(after):
            result = _heading_from_points(
                frame_index,
                center,
                after_frame,
                after,
                "center_after",
            )
            if result is not None:
                return result

        before_frame = frame_index - offset
        before = positions_by_frame.get(before_frame)
        if _valid_point(before):
            result = _heading_from_points(
                before_frame,
                before,
                frame_index,
                center,
                "before_center",
            )
            if result is not None:
                return result

    return None

