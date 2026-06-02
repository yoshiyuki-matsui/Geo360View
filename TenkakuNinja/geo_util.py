# TenkakuNinja/geo_util.py
from datetime import datetime, timedelta, timezone
import math
import re
import unicodedata
import xml.etree.ElementTree as ET


TIME_FIELD_NAMES = {
    "time",
    "timestamp",
    "datetime",
    "date_time",
    "gps_time",
    "gpstime",
    "utc_time",
    "utctime",
    "utc",
    "jst",
    "recorded_at",
    "created_at",
    "capture_time",
    "日時",
    "日付時刻",
    "撮影日時",
}

DATE_FIELD_NAMES = {
    "date",
    "gps_date",
    "gpsdate",
    "day",
    "ymd",
    "capture_date",
    "日付",
    "撮影日",
}

CLOCK_FIELD_NAMES = {
    "time",
    "clock",
    "hms",
    "gps_time",
    "gpstime",
    "capture_clock",
    "時刻",
    "撮影時刻",
}


def _local_name(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _field_name(name):
    name = _local_name(str(name)).strip()
    name = unicodedata.normalize("NFKC", name).lower()
    return re.sub(r"[\s:./-]+", "_", name).strip("_")


def _clean_text(value):
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", str(value)).strip()
    return value or None


def _values_by_field_names(element, names):
    values = []

    for attr_name, attr_value in element.attrib.items():
        if _field_name(attr_name) in names:
            value = _clean_text(attr_value)
            if value:
                values.append(value)

    for child in element.iter():
        if child is element:
            continue
        if _field_name(child.tag) in names:
            value = _clean_text(child.text)
            if value:
                values.append(value)

        for attr_name, attr_value in child.attrib.items():
            if _field_name(attr_name) in names:
                value = _clean_text(attr_value)
                if value:
                    values.append(value)

    return values


def _all_point_values(element):
    values = []
    for value in element.attrib.values():
        cleaned = _clean_text(value)
        if cleaned:
            values.append(cleaned)

    for child in element.iter():
        if child is element:
            continue

        cleaned = _clean_text(child.text)
        if cleaned:
            values.append(cleaned)

        for value in child.attrib.values():
            cleaned = _clean_text(value)
            if cleaned:
                values.append(cleaned)

    return values


def _looks_like_datetime(value):
    value = _clean_text(value)
    if not value:
        return False
    if re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value):
        return True
    if re.fullmatch(r"\d{8}([T _-]?\d{6}(\.\d+)?)?", value):
        return True
    if re.fullmatch(r"\d{10}|\d{13}", value):
        return True
    return False


def _unique(values):
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _time_candidates(point):
    candidates = []
    candidates.extend(_values_by_field_names(point, TIME_FIELD_NAMES))

    date_values = _values_by_field_names(point, DATE_FIELD_NAMES)
    clock_values = _values_by_field_names(point, CLOCK_FIELD_NAMES)
    for date_value in date_values:
        for clock_value in clock_values:
            if date_value != clock_value:
                candidates.append(f"{date_value} {clock_value}")

    for value in _all_point_values(point):
        if _looks_like_datetime(value):
            candidates.append(value)

    return _unique(candidates)


def _to_utc_naive(value):
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_epoch(value):
    if not re.fullmatch(r"\d+(\.\d+)?", value):
        return None

    if re.fullmatch(r"\d{8}|\d{12}|\d{14}", value):
        return None

    try:
        epoch = float(value)
    except ValueError:
        return None

    if epoch > 10_000_000_000_000:
        epoch /= 1_000_000
    elif epoch > 10_000_000_000:
        epoch /= 1000

    try:
        return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)
    except (OSError, OverflowError, ValueError):
        return None


def _normalize_time_text(value):
    value = _clean_text(value)
    if not value:
        return ""

    value = value.strip("\"'")
    value = value.replace("年", "-").replace("月", "-").replace("日", " ")
    value = value.replace("時", ":").replace("分", ":").replace("秒", "")
    value = value.replace("/", "-")
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\bJST\b", "+09:00", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(UTC|GMT)\b", "+00:00", value, flags=re.IGNORECASE)
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    value = re.sub(r"([+-]\d{2})$", r"\1:00", value)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return value.strip()


def _parse_gpx_time(value):
    value = _normalize_time_text(value)
    if not value:
        return None

    parsed = _parse_epoch(value)
    if parsed is not None:
        return parsed

    compact = re.fullmatch(
        r"(\d{4})(\d{2})(\d{2})[T -]?(\d{2})(\d{2})(\d{2})(?:\.(\d+))?(?:([+-]\d{2}:\d{2}))?",
        value,
    )
    if compact:
        year, month, day, hour, minute, second, micros, offset = compact.groups()
        micros = (micros or "")[:6].ljust(6, "0")
        iso_value = f"{year}-{month}-{day}T{hour}:{minute}:{second}.{micros}"
        if offset:
            iso_value += offset
        try:
            return _to_utc_naive(datetime.fromisoformat(iso_value))
        except ValueError:
            return None

    try:
        return _to_utc_naive(datetime.fromisoformat(value))
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
            "%Y%m%d %H%M%S",
            "%Y%m%d%H%M%S",
        ):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def read_gpx(gpx_path, diagnostics=False):
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    gpx_points = []
    point_count = 0
    missing_time_count = 0
    bad_time_count = 0
    time_samples = []
    for point in root.iter():
        if _local_name(point.tag) not in ("trkpt", "rtept"):
            continue
        point_count += 1

        try:
            lat = float(point.get("lat"))
            lon = float(point.get("lon"))
        except (TypeError, ValueError):
            continue

        candidates = _time_candidates(point)
        if not candidates:
            missing_time_count += 1
            continue

        time_value = None
        for candidate in candidates:
            time_value = _parse_gpx_time(candidate)
            if time_value is not None:
                break

        if time_value is None:
            bad_time_count += 1
            if len(time_samples) < 5:
                time_samples.append(candidates[0])
            continue

        gpx_points.append((time_value, lat, lon))

    gpx_points.sort()
    if diagnostics:
        return gpx_points, {
            "point_count": point_count,
            "missing_time_count": missing_time_count,
            "bad_time_count": bad_time_count,
            "time_samples": time_samples,
        }
    return gpx_points


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def time_to_frame(seconds, fps, drop_frame=None, rounding="round"):
    if drop_frame is None:
        drop_frame = is_drop_frame_fps(fps)

    frame_num = round(seconds * fps)
    if rounding == "floor":
        frame_num = math.floor(frame_num)
    elif rounding == "ceil":
        frame_num = math.ceil(frame_num)

    return int(frame_num)


def is_drop_frame_fps(fps):
    return abs(fps - 30) < 0.03


def interpolate_gpx_to_frames(gpx_points, fps):
    gpx_points.sort()
    times, lats, lons = zip(*gpx_points)
    times = list(times)
    lats = list(lats)
    lons = list(lons)

    interpolated = []
    for frame_num in range(len(times) - 1):
        time_diff = (times[frame_num + 1] - times[frame_num]).total_seconds()
        if time_diff <= 0:
            continue

        lat_diff = lats[frame_num + 1] - lats[frame_num]
        lon_diff = lons[frame_num + 1] - lons[frame_num]

        steps = int(time_diff * fps)
        for i in range(steps):
            fraction = i / (time_diff * fps)
            interpolated_time = times[frame_num] + timedelta(seconds=fraction * time_diff)
            interpolated_lat = lats[frame_num] + fraction * lat_diff
            interpolated_lon = lons[frame_num] + fraction * lon_diff
            interpolated.append((interpolated_time, interpolated_lat, interpolated_lon))

    return interpolated
