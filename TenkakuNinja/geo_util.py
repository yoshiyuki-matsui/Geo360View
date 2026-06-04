"""GPX読込、時刻表記ゆれ吸収、フレーム補間のユーティリティ。"""

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
    """XML名前空間を除いたローカルタグ名を返す。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _field_name(name):
    """タグ名・属性名を候補名比較用の正規化フィールド名へ変換する。"""
    name = _local_name(str(name)).strip()
    name = unicodedata.normalize("NFKC", name).lower()
    return re.sub(r"[\s:./-]+", "_", name).strip("_")


def _clean_text(value):
    """XMLテキスト/属性値をNFKC正規化し、空文字はNoneにする。"""
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", str(value)).strip()
    return value or None


def _values_by_field_names(element, names):
    """指定候補名に一致する属性・子要素テキストを再帰的に集める。"""
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
    """trkpt/rtept配下の全テキスト・属性値を時刻候補探索用に集める。"""
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
    """任意文字列が日時らしい形式かを粗く判定する。"""
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
    """順序を保ったまま重複値を取り除く。"""
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _time_candidates(point):
    """GPXポイントから時刻として解釈できそうな候補文字列を列挙する。"""
    candidates = []
    candidates.extend(_values_by_field_names(point, TIME_FIELD_NAMES))

    # date列とclock列が分かれている独自GPXもあるため、組み合わせて試す。
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
    """timezone付きdatetimeをUTCのnaive datetimeへ統一する。"""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_epoch(value):
    """Unix epoch秒/ミリ秒/マイクロ秒らしい数値をdatetimeへ変換する。"""
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
    """JST/日本語日時/区切り文字違いをISO8601へ近づける。"""
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
    """GPX時刻候補をUTC naive datetimeへ変換する。失敗時はNone。"""
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
        # 20250324130849 のようなコンパクト表記をISO文字列へ組み直す。
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
    """GPXファイルから時刻付きtrkpt/rteptを読み込む。

    標準GPXの `<time>` だけでなく、extensions配下や属性値にある独自時刻も候補として扱う。
    """
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

        # 候補は複数あり得るため、最初に解釈できた値を採用する。
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
    """2つの緯度経度間の概算距離をメートルで返す。"""
    r = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def time_to_frame(seconds, fps, drop_frame=None, rounding="round"):
    """経過秒を動画フレーム番号へ変換する。"""
    if drop_frame is None:
        drop_frame = is_drop_frame_fps(fps)

    if rounding == "floor":
        frame_num = math.floor(seconds * fps)
    elif rounding == "ceil":
        frame_num = math.ceil(seconds * fps)
    else:
        frame_num = round(seconds * fps)

    return int(frame_num)


def is_drop_frame_fps(fps):
    """簡易的に30fps近傍をドロップフレーム系FPSとして扱う。"""
    return abs(fps - 30) < 0.03


def interpolate_gpx_to_frames(gpx_points, fps):
    """時刻付きGPX点列をFPS間隔のフレーム位置へ線形補間する。"""
    gpx_points.sort()
    times, lats, lons = zip(*gpx_points)
    times = list(times)
    lats = list(lats)
    lons = list(lons)
    start_time = times[0]

    interpolated = []
    for point_index in range(len(times) - 1):
        time_diff = (times[point_index + 1] - times[point_index]).total_seconds()
        if time_diff <= 0:
            continue

        lat_diff = lats[point_index + 1] - lats[point_index]
        lon_diff = lons[point_index + 1] - lons[point_index]
        start_frame = time_to_frame((times[point_index] - start_time).total_seconds(), fps)
        end_frame = time_to_frame((times[point_index + 1] - start_time).total_seconds(), fps)

        for source_frame in range(start_frame, end_frame):
            # 29.97fpsで1秒区間をint(time_diff * fps)にすると毎秒1フレーム落ちる。
            # フレーム番号範囲から逆算して補間し、DB側の欠番を発生させない。
            interpolated_time = start_time + timedelta(seconds=source_frame / fps)
            fraction = (interpolated_time - times[point_index]).total_seconds() / time_diff
            fraction = max(0.0, min(1.0, fraction))
            interpolated_lat = lats[point_index] + fraction * lat_diff
            interpolated_lon = lons[point_index] + fraction * lon_diff
            interpolated.append((interpolated_time, interpolated_lat, interpolated_lon))

    return interpolated
