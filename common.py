import csv
import os
import re
import unicodedata

from qgis.PyQt.QtCore import QDate, QDateTime, QTime, Qt


def _utc_time_spec():
    if hasattr(Qt, "TimeSpec"):
        return Qt.TimeSpec.UTC
    return Qt.UTC


def _to_qdatetime(value):
    return QDateTime(
        QDate(value.year, value.month, value.day),
        QTime(value.hour, value.minute, value.second, value.microsecond // 1000),
        _utc_time_spec()
    )


def _format_timestamp(value):
    return value.isoformat(timespec="milliseconds") + "Z"


def _format_distance(value):
    if value is None:
        return ""
    return f"{value:.3f}"


def _base_output_name(video_path, gpx_path):
    source_path = video_path or gpx_path or "video_gpx"
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", base_name).strip("_") or "video_gpx"


def _frame_image_name(frame_num):
    return f"frames_{frame_num:06d}.jpg"


def _normalize_field_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"[\s:./()（）\[\]-]+", "_", value).strip("_")


def _find_field(fieldnames, candidates):
    normalized = [(field, _normalize_field_name(field)) for field in fieldnames or []]
    candidate_names = {_normalize_field_name(candidate) for candidate in candidates}

    for field, normalized_field in normalized:
        if normalized_field in candidate_names:
            return field

    for field, normalized_field in normalized:
        if any(candidate and candidate in normalized_field for candidate in candidate_names):
            return field

    return None


def _safe_gpkg_layer_name(value):
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_").lower()
    if not value:
        value = "video_gpx_points"
    if value[0].isdigit():
        value = f"layer_{value}"
    return value[:63]


def _looks_like_python_launcher(path):
    name = os.path.basename(str(path or "")).lower()
    return name.startswith("python")


def _parse_float(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    value = value.replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _open_csv_dict_reader(path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            handle = open(path, "r", encoding=encoding, newline="")
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            return handle, csv.DictReader(handle, dialect=dialect)
        except UnicodeDecodeError as e:
            last_error = e
        except OSError:
            raise
    raise ValueError(f"Could not read CSV encoding: {last_error}")
