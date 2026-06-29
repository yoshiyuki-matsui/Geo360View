"""Generate human-checkable reports for YOLO CubeMap detections.

The report is intentionally file-based: CSV/JSON summaries, an HTML index, and
annotated image copies with bbox labels.  It reads semantic_work.sqlite and does
not depend on QGIS.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
from dataclasses import dataclass
from html import escape
import json
import math
from pathlib import Path
import sqlite3
import time

try:
    from . import job_guard, schema, sqlite_io
    from .cubemap import normalize_faces
    from .yolo_detect import resolve_run, resolve_image_path
except ImportError:
    import job_guard
    import schema
    import sqlite_io
    from cubemap import normalize_faces
    from yolo_detect import resolve_run, resolve_image_path


DEFAULT_REPORT_DIR_NAME = "yolo_report"
DEFAULT_JPEG_QUALITY = 92
IMAGE_SAMPLE_MODES = ("first", "even", "class-balanced")
FACE_DISPLAY_ORDER = {
    "front": 0,
    "right": 1,
    "back": 2,
    "left": 3,
    "up": 4,
    "down": 5,
}


@dataclass(frozen=True)
class YoloReportConfig:
    """CLI arguments normalized for YOLO report generation."""

    work_db: Path
    run_id: str | None
    output_dir: Path | None
    min_conf: float
    faces: tuple[str, ...]
    classes: tuple[str, ...]
    max_images: int | None
    write_images: bool
    jpeg_quality: int
    model_run_ids: tuple[str, ...] = ()
    model_names: tuple[str, ...] = ()
    max_bbox_area_ratio: float | None = None
    image_sample_mode: str = "first"
    position_db: Path | None = None
    position_layer: str | None = None
    exclude_stationary: bool = False
    stationary_window_frames: int = 30
    stationary_distance_m: float = 0.5


def normalize_text_values(values) -> tuple[str, ...]:
    """Normalize optional text filters."""

    if not values:
        return ()
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def normalize_classes(values) -> tuple[str, ...]:
    """Normalize optional class filters."""

    return normalize_text_values(values)


def output_dir_for_run(work_db: Path, run_row: dict, requested: Path | None) -> Path:
    """Resolve the report output directory."""

    if requested:
        return requested
    work_dir = str(run_row.get("work_dir") or "").strip()
    base = Path(work_dir) if work_dir else Path(work_db).parent
    return base / DEFAULT_REPORT_DIR_NAME


def open_report_db(path: Path) -> sqlite3.Connection:
    """Open the work DB read-only for report generation."""

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_detection_rows(
    conn: sqlite3.Connection,
    run_id: str,
    min_conf: float = 0.0,
    faces: tuple[str, ...] = (),
    classes: tuple[str, ...] = (),
    model_run_ids: tuple[str, ...] = (),
    model_names: tuple[str, ...] = (),
) -> list[dict]:
    """Fetch detections joined to image plane and semantic target metadata."""

    where = ["d.run_id = ?", "(d.confidence IS NULL OR d.confidence >= ?)"]
    params: list[object] = [run_id, float(min_conf)]
    if faces:
        faces = normalize_faces(faces)
        where.append(f"p.face_name IN ({', '.join('?' for _ in faces)})")
        params.extend(faces)
    if classes:
        where.append(f"d.class_name IN ({', '.join('?' for _ in classes)})")
        params.extend(classes)
    if model_run_ids:
        where.append(f"d.model_run_id IN ({', '.join('?' for _ in model_run_ids)})")
        params.extend(model_run_ids)
    if model_names:
        where.append(f"m.model_name IN ({', '.join('?' for _ in model_names)})")
        params.extend(model_names)

    sql = f"""
        SELECT
            d.detection_id,
            d.run_id,
            d.model_run_id,
            m.model_name,
            m.model_path,
            d.plane_id,
            d.frame_index,
            d.class_id,
            d.class_name,
            d.confidence,
            d.bbox_x1,
            d.bbox_y1,
            d.bbox_x2,
            d.bbox_y2,
            d.bbox_width,
            d.bbox_height,
            d.bbox_area,
            p.face_name,
            p.image_path,
            p.width_px,
            p.height_px,
            t.target_id,
            t.target_yaw_to_camera_heading,
            t.target_pitch_deg,
            t.ground_distance_m,
            t.projection,
            t.quality
        FROM {schema.quote_identifier(schema.YOLO_DETECTIONS_TABLE)} AS d
        JOIN {schema.quote_identifier(schema.IMAGE_PLANES_TABLE)} AS p
            ON p.plane_id = d.plane_id
        JOIN {schema.quote_identifier(schema.MODEL_RUNS_TABLE)} AS m
            ON m.model_run_id = d.model_run_id
        LEFT JOIN {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)} AS t
            ON t.detection_id = d.detection_id
        WHERE {" AND ".join(where)}
        ORDER BY d.frame_index, p.face_name, d.confidence DESC, d.detection_id
    """
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def group_by_plane(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group detection rows by image plane in display order."""

    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        plane_id = str(row["plane_id"])
        if plane_id not in grouped:
            grouped[plane_id] = []
            order.append(plane_id)
        grouped[plane_id].append(row)
    return [(plane_id, grouped[plane_id]) for plane_id in order]


def select_evenly(items: list, max_count: int) -> list:
    """Return up to max_count items spread across the input order."""

    count = max(0, int(max_count))
    if count <= 0:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[0]]

    last_index = len(items) - 1
    indices: list[int] = []
    seen: set[int] = set()
    for index in range(count):
        selected = round(index * last_index / (count - 1))
        if selected in seen:
            continue
        seen.add(selected)
        indices.append(selected)

    if len(indices) < count:
        for selected in range(len(items)):
            if selected in seen:
                continue
            seen.add(selected)
            indices.append(selected)
            if len(indices) >= count:
                break
    return [items[index] for index in sorted(indices[:count])]


def dominant_class_name(rows: list[dict]) -> str:
    """Return the strongest class name on one image plane."""

    if not rows:
        return ""
    strongest = max(rows, key=lambda row: numeric(row.get("confidence"), default=-1.0))
    return str(strongest.get("class_name") or "")


def select_class_balanced_grouped_rows(
    grouped_rows: list[tuple[str, list[dict]]],
    max_count: int,
) -> list[tuple[str, list[dict]]]:
    """Return image planes balanced by dominant class and spread across frames."""

    limit = max(0, int(max_count))
    if limit <= 0:
        return []
    if limit >= len(grouped_rows):
        return list(grouped_rows)

    buckets: dict[str, list[tuple[int, tuple[str, list[dict]]]]] = {}
    for index, item in enumerate(grouped_rows):
        buckets.setdefault(dominant_class_name(item[1]), []).append((index, item))

    keys = sorted(buckets, key=lambda key: (-len(buckets[key]), key))
    quotas = {key: 0 for key in keys}
    active = list(keys)
    selected_count = 0
    while selected_count < limit and active:
        for key in list(active):
            if quotas[key] < len(buckets[key]):
                quotas[key] += 1
                selected_count += 1
            if quotas[key] >= len(buckets[key]):
                active.remove(key)
            if selected_count >= limit:
                break

    selected: list[tuple[int, tuple[str, list[dict]]]] = []
    for key in keys:
        quota = quotas[key]
        if quota <= 0:
            continue
        selected.extend(select_evenly(buckets[key], quota))
    selected.sort(key=lambda item: item[0])
    return [item for _, item in selected[:limit]]


def select_grouped_rows_for_images(
    grouped_rows: list[tuple[str, list[dict]]],
    max_images: int | None,
    image_sample_mode: str = "first",
) -> list[tuple[str, list[dict]]]:
    """Select image planes for annotation according to the requested sampling mode."""

    if max_images is None:
        return list(grouped_rows)

    limit = max(0, int(max_images))
    mode = str(image_sample_mode or "first").strip().lower()
    if mode == "even":
        return select_evenly(grouped_rows, limit)
    if mode == "class-balanced":
        return select_class_balanced_grouped_rows(grouped_rows, limit)
    return list(grouped_rows[:limit])


def numeric(value, default=0.0) -> float:
    """Return a float fallback for optional SQLite values."""

    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def optional_numeric(value) -> float | None:
    """Return a float or None for optional database values."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return approximate WGS84 great-circle distance in meters."""

    radius_m = 6371000.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return radius_m * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a SQLite table exists."""

    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
        (str(table_name),),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return column names for one SQLite table."""

    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({schema.quote_identifier(table_name)})")}
    except sqlite3.Error:
        return set()


def first_existing_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate column present in a table."""

    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def coalesce_expression(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    """Return a SQL expression that chooses the first non-null candidate column."""

    existing = [schema.quote_identifier(candidate) for candidate in candidates if candidate in columns]
    if not existing:
        return None
    if len(existing) == 1:
        return existing[0]
    return f"COALESCE({', '.join(existing)})"


def read_frame_positions_from_db(
    db_path: Path,
    preferred_layer: str | None = None,
) -> dict[int, tuple[float, float]]:
    """Read frame-indexed camera positions from a work DB or GeoPackage."""

    candidates = []
    if preferred_layer:
        candidates.append(str(preferred_layer))
    candidates.extend(["source_frames", "video_gpx_points"])

    positions: dict[int, tuple[float, float]] = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        for layer in dict.fromkeys(candidates):
            if not table_exists(conn, layer):
                continue
            columns = table_columns(conn, layer)
            frame_column = first_existing_column(columns, ("frame", "frame_index", "source_frame"))
            lat_expr = coalesce_expression(columns, ("aligned_latitude", "camera_lat", "latitude", "lat"))
            lon_expr = coalesce_expression(columns, ("aligned_longitude", "camera_lon", "longitude", "lon", "lng"))
            if not frame_column or not lat_expr or not lon_expr:
                continue

            sql = f"""
                SELECT
                    {schema.quote_identifier(frame_column)} AS frame_index,
                    {lat_expr} AS latitude,
                    {lon_expr} AS longitude
                FROM {schema.quote_identifier(layer)}
                WHERE {schema.quote_identifier(frame_column)} IS NOT NULL
                ORDER BY {schema.quote_identifier(frame_column)}
            """
            for row in conn.execute(sql):
                frame = optional_numeric(row["frame_index"])
                lat = optional_numeric(row["latitude"])
                lon = optional_numeric(row["longitude"])
                if frame is None or lat is None or lon is None:
                    continue
                positions[int(frame)] = (float(lat), float(lon))
            if positions:
                return positions
    finally:
        conn.close()
    return positions


def nearest_position_at_or_before(frames: list[int], positions: dict[int, tuple[float, float]], frame: int):
    """Return nearest known position at or before frame."""

    index = bisect_left(frames, int(frame))
    if index < len(frames) and frames[index] == int(frame):
        return frames[index], positions[frames[index]]
    if index <= 0:
        return None
    selected = frames[index - 1]
    return selected, positions[selected]


def nearest_position_at_or_after(frames: list[int], positions: dict[int, tuple[float, float]], frame: int):
    """Return nearest known position at or after frame."""

    index = bisect_left(frames, int(frame))
    if index >= len(frames):
        return None
    selected = frames[index]
    return selected, positions[selected]


def is_stationary_frame(
    frame_index: int,
    frames: list[int],
    positions: dict[int, tuple[float, float]],
    window_frames: int,
    distance_m: float,
) -> bool:
    """Return True when the camera barely moved around a frame."""

    if not frames or not positions:
        return False
    frame = int(frame_index)
    window = max(1, int(window_frames))
    before = nearest_position_at_or_before(frames, positions, frame - window)
    after = nearest_position_at_or_after(frames, positions, frame + window)
    if before is None or after is None:
        return False
    before_frame, before_pos = before
    after_frame, after_pos = after
    if before_frame == after_frame:
        return False
    moved_m = haversine_m(before_pos[0], before_pos[1], after_pos[0], after_pos[1])
    return moved_m <= max(0.0, float(distance_m))


def filter_stationary_rows(
    rows: list[dict],
    positions: dict[int, tuple[float, float]],
    window_frames: int,
    distance_m: float,
) -> tuple[list[dict], list[dict]]:
    """Split detection rows into moving and stationary-frame rows."""

    if not positions:
        return rows, []
    frames = sorted(positions)
    moving_rows = []
    stationary_rows = []
    stationary_cache: dict[int, bool] = {}
    for row in rows:
        frame = int(numeric(row.get("frame_index"), default=-1))
        if frame not in stationary_cache:
            stationary_cache[frame] = is_stationary_frame(frame, frames, positions, window_frames, distance_m)
        if stationary_cache[frame]:
            stationary_rows.append(row)
        else:
            moving_rows.append(row)
    return moving_rows, stationary_rows


def html_image_sort_key(row: dict) -> tuple:
    """Return gallery order: frame number, face, then strongest detection first."""

    frame = int(numeric(row.get("frame_index"), default=0))
    face = str(row.get("face_name") or "")
    face_order = FACE_DISPLAY_ORDER.get(face, 99)
    return (frame, face_order, face, -numeric(row.get("confidence")), str(row.get("annotated_image") or ""))


def summary_by_class(rows: list[dict]) -> list[dict]:
    """Return class-level summary records."""

    stats: dict[str, dict] = {}
    for row in rows:
        name = str(row.get("class_name") or "")
        confidence = row.get("confidence")
        item = stats.setdefault(
            name,
            {
                "class_name": name,
                "count": 0,
                "confidence_sum": 0.0,
                "confidence_count": 0,
                "min_confidence": None,
                "max_confidence": None,
                "first_frame": row.get("frame_index"),
                "last_frame": row.get("frame_index"),
            },
        )
        item["count"] += 1
        frame = row.get("frame_index")
        if frame is not None:
            item["first_frame"] = min(item["first_frame"], frame)
            item["last_frame"] = max(item["last_frame"], frame)
        if confidence is not None:
            conf = float(confidence)
            item["confidence_sum"] += conf
            item["confidence_count"] += 1
            item["min_confidence"] = conf if item["min_confidence"] is None else min(item["min_confidence"], conf)
            item["max_confidence"] = conf if item["max_confidence"] is None else max(item["max_confidence"], conf)

    result = []
    for item in stats.values():
        count = item.pop("confidence_count")
        total = item.pop("confidence_sum")
        item["avg_confidence"] = total / count if count else None
        result.append(item)
    return sorted(result, key=lambda value: (-int(value["count"]), str(value["class_name"])))


def summary_by_face(rows: list[dict]) -> list[dict]:
    """Return face-level summary records."""

    stats: dict[str, int] = {}
    for row in rows:
        face = str(row.get("face_name") or "")
        stats[face] = stats.get(face, 0) + 1
    return [{"face_name": face, "count": count} for face, count in sorted(stats.items())]


def summary_by_model_run(rows: list[dict]) -> list[dict]:
    """Return model-run-level summary records."""

    stats: dict[str, dict] = {}
    for row in rows:
        model_run_id = str(row.get("model_run_id") or "")
        item = stats.setdefault(
            model_run_id,
            {
                "model_run_id": model_run_id,
                "model_name": row.get("model_name") or "",
                "count": 0,
                "first_frame": row.get("frame_index"),
                "last_frame": row.get("frame_index"),
            },
        )
        item["count"] += 1
        frame = row.get("frame_index")
        if frame is not None:
            item["first_frame"] = min(item["first_frame"], frame)
            item["last_frame"] = max(item["last_frame"], frame)
    return sorted(stats.values(), key=lambda value: (str(value["model_name"]), str(value["model_run_id"])))


def write_csv(path: Path, rows: list[dict], columns: list[str]):
    """Write dictionaries to a UTF-8 CSV file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def detection_csv_rows(rows: list[dict], annotated_by_plane: dict[str, str]) -> list[dict]:
    """Return normalized detection rows for detections.csv."""

    result = []
    for row in rows:
        width_px = numeric(row.get("width_px"))
        height_px = numeric(row.get("height_px"))
        image_area = width_px * height_px
        bbox_area_ratio = numeric(row.get("bbox_area")) / image_area if image_area > 0 else None
        result.append(
            {
                "detection_id": row.get("detection_id"),
                "model_run_id": row.get("model_run_id"),
                "model_name": row.get("model_name"),
                "frame_index": row.get("frame_index"),
                "face_name": row.get("face_name"),
                "class_id": row.get("class_id"),
                "class_name": row.get("class_name"),
                "confidence": row.get("confidence"),
                "bbox_x1": row.get("bbox_x1"),
                "bbox_y1": row.get("bbox_y1"),
                "bbox_x2": row.get("bbox_x2"),
                "bbox_y2": row.get("bbox_y2"),
                "bbox_width": row.get("bbox_width"),
                "bbox_height": row.get("bbox_height"),
                "bbox_area": row.get("bbox_area"),
                "bbox_area_ratio": bbox_area_ratio,
                "image_path": row.get("image_path"),
                "annotated_image": annotated_by_plane.get(str(row.get("plane_id"))),
                "target_id": row.get("target_id"),
                "target_yaw_to_camera_heading": row.get("target_yaw_to_camera_heading"),
                "target_pitch_deg": row.get("target_pitch_deg"),
                "ground_distance_m": row.get("ground_distance_m"),
                "projection": row.get("projection"),
                "quality": row.get("quality"),
            }
        )
    return result


def bbox_area_ratio_for_row(row: dict) -> float | None:
    """Return bbox/image area ratio when image dimensions are available."""

    width_px = numeric(row.get("width_px"))
    height_px = numeric(row.get("height_px"))
    image_area = width_px * height_px
    if image_area <= 0:
        return None
    return numeric(row.get("bbox_area")) / image_area


def filter_large_bbox_rows(
    rows: list[dict],
    max_bbox_area_ratio: float | None,
) -> tuple[list[dict], list[dict]]:
    """Split detection rows into accepted rows and large-bbox skips."""

    if max_bbox_area_ratio is None:
        return rows, []
    threshold = float(max_bbox_area_ratio)
    accepted = []
    skipped = []
    for row in rows:
        ratio = bbox_area_ratio_for_row(row)
        if ratio is not None and ratio > threshold:
            skipped.append(
                {
                    "detection_id": row.get("detection_id"),
                    "frame_index": row.get("frame_index"),
                    "face_name": row.get("face_name"),
                    "class_name": row.get("class_name"),
                    "confidence": row.get("confidence"),
                    "bbox_area_ratio": ratio,
                    "max_bbox_area_ratio": threshold,
                    "image_path": row.get("image_path"),
                }
            )
            continue
        accepted.append(row)
    return accepted, skipped


def class_color(class_name: str) -> tuple[int, int, int]:
    """Return a deterministic RGB color for an annotation class."""

    normalized = str(class_name or "").lower()
    if "red" in normalized or "stop" in normalized:
        return (230, 64, 64)
    if "green" in normalized:
        return (48, 180, 92)
    if "speed" in normalized:
        return (52, 118, 220)
    value = sum(ord(ch) for ch in normalized)
    return (
        64 + (value * 37) % 160,
        64 + (value * 67) % 160,
        64 + (value * 97) % 160,
    )


def annotated_image_path(output_dir: Path, image_path: str | Path) -> Path:
    """Return report path for an annotated image copy."""

    source = Path(str(image_path))
    bucket = source.parent.name if source.parent.name else "images"
    return output_dir / "annotated" / bucket / f"{source.stem}_annotated.jpg"


def draw_annotated_image(source_path: Path, output_path: Path, rows: list[dict], jpeg_quality: int):
    """Draw bbox annotations on one image plane."""

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:
        raise RuntimeError("Pillow is required to write annotated images.") from e

    image = Image.open(source_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    image_width, image_height = image.size

    for row in rows:
        x1 = max(0.0, min(float(image_width - 1), numeric(row.get("bbox_x1"))))
        y1 = max(0.0, min(float(image_height - 1), numeric(row.get("bbox_y1"))))
        x2 = max(0.0, min(float(image_width - 1), numeric(row.get("bbox_x2"))))
        y2 = max(0.0, min(float(image_height - 1), numeric(row.get("bbox_y2"))))
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        color = class_color(str(row.get("class_name") or ""))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        label = f"{row.get('class_name') or ''} {numeric(row.get('confidence')):.2f}".strip()
        bbox = draw.textbbox((x1, y1), label, font=font)
        label_height = bbox[3] - bbox[1]
        label_width = bbox[2] - bbox[0]
        label_y = max(0, int(y1) - label_height - 6)
        draw.rectangle((int(x1), label_y, int(x1) + label_width + 8, label_y + label_height + 6), fill=color)
        draw.text((int(x1) + 4, label_y + 3), label, fill=(255, 255, 255), font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=int(jpeg_quality))


def write_annotated_images(
    work_db: Path,
    run_row: dict,
    output_dir: Path,
    grouped_rows: list[tuple[str, list[dict]]],
    max_images: int | None,
    jpeg_quality: int,
    image_sample_mode: str = "first",
) -> tuple[dict[str, str], int, int]:
    """Write annotated images and return plane_id -> relative output path."""

    annotated_by_plane: dict[str, str] = {}
    written = 0
    missing = 0
    selected = select_grouped_rows_for_images(grouped_rows, max_images, image_sample_mode)

    for plane_id, rows in selected:
        image_path = resolve_image_path(work_db, run_row, rows[0])
        if not image_path.is_file():
            missing += 1
            continue
        output_path = annotated_image_path(output_dir, rows[0]["image_path"])
        draw_annotated_image(image_path, output_path, rows, jpeg_quality)
        try:
            relative = output_path.relative_to(output_dir).as_posix()
        except ValueError:
            relative = output_path.as_posix()
        annotated_by_plane[str(plane_id)] = relative
        written += 1

    return annotated_by_plane, written, missing


def write_summary_text(path: Path, summary: dict):
    """Write a compact human-readable summary."""

    lines = [
        f"Run ID: {summary['run_id']}",
        f"Model run count: {summary['model_run_count']}",
        f"Input detection count: {summary['input_detection_count']}",
        f"Detection count: {summary['detection_count']}",
        f"Large bbox filtered: {summary['large_bbox_filtered_count']}",
        f"Stationary filtered: {summary['stationary_filtered_count']}",
        f"Annotated images: {summary['annotated_image_count']}",
        f"Missing image planes: {summary['missing_image_count']}",
        "",
        "By model run:",
    ]
    for item in summary["model_run_summary"]:
        lines.append(
            f"  {item['model_name'] or item['model_run_id']}: {item['count']} "
            f"({item['model_run_id']})"
        )
    lines.extend([
        "",
        "By class:",
    ])
    for item in summary["class_summary"]:
        avg = item.get("avg_confidence")
        max_conf = item.get("max_confidence")
        lines.append(
            f"  {item['class_name']}: {item['count']} "
            f"(avg={avg:.3f}, max={max_conf:.3f})"
            if avg is not None and max_conf is not None
            else f"  {item['class_name']}: {item['count']}"
        )
    lines.append("")
    lines.append("By face:")
    for item in summary["face_summary"]:
        lines.append(f"  {item['face_name']}: {item['count']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html_index(path: Path, summary: dict, detection_rows: list[dict]):
    """Write a lightweight HTML gallery for visual checking."""

    unique_images = []
    seen = set()
    for row in sorted(detection_rows, key=html_image_sort_key):
        annotated = row.get("annotated_image")
        if not annotated or annotated in seen:
            continue
        seen.add(annotated)
        unique_images.append(row)

    cards = []
    for row in unique_images:
        label = (
            f"frame {row.get('frame_index')} {row.get('face_name')} "
            f"{row.get('class_name')} {numeric(row.get('confidence')):.2f}"
        )
        cards.append(
            "<figure>"
            f"<a href=\"{escape(str(row.get('annotated_image')))}\">"
            f"<img src=\"{escape(str(row.get('annotated_image')))}\" loading=\"lazy\"></a>"
            f"<figcaption>{escape(label)}</figcaption>"
            "</figure>"
        )

    class_rows = "\n".join(
        f"<tr><td>{escape(str(item['class_name']))}</td><td>{item['count']}</td>"
        f"<td>{numeric(item.get('avg_confidence')):.3f}</td><td>{numeric(item.get('max_confidence')):.3f}</td></tr>"
        for item in summary["class_summary"]
    )
    face_rows = "\n".join(
        f"<tr><td>{escape(str(item['face_name']))}</td><td>{item['count']}</td></tr>"
        for item in summary["face_summary"]
    )
    model_rows = "\n".join(
        f"<tr><td>{escape(str(item['model_name']))}</td><td>{escape(str(item['model_run_id']))}</td>"
        f"<td>{item['count']}</td><td>{item.get('first_frame')}</td><td>{item.get('last_frame')}</td></tr>"
        for item in summary["model_run_summary"]
    )
    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>YOLO Detection Report {escape(str(summary['run_id']))}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #222; }}
table {{ border-collapse: collapse; margin: 12px 0 24px; }}
td, th {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
figure {{ margin: 0; border: 1px solid #ddd; padding: 6px; background: #fafafa; }}
img {{ width: 100%; height: auto; display: block; }}
figcaption {{ font-size: 12px; margin-top: 4px; }}
</style>
</head>
<body>
<h1>YOLO Detection Report</h1>
<p>Run ID: {escape(str(summary['run_id']))}</p>
<p>Detections: {summary['detection_count']} / Annotated images: {summary['annotated_image_count']}</p>
<p>Input detections: {summary['input_detection_count']} / Large bbox filtered: {summary['large_bbox_filtered_count']} / Stationary filtered: {summary['stationary_filtered_count']}</p>
<h2>Model Run Summary</h2>
<table><tr><th>Model</th><th>Model run ID</th><th>Count</th><th>First frame</th><th>Last frame</th></tr>{model_rows}</table>
<h2>Class Summary</h2>
<table><tr><th>Class</th><th>Count</th><th>Avg conf</th><th>Max conf</th></tr>{class_rows}</table>
<h2>Face Summary</h2>
<table><tr><th>Face</th><th>Count</th></tr>{face_rows}</table>
<h2>Annotated Images</h2>
<div class="grid">
{''.join(cards)}
</div>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_report(config: YoloReportConfig) -> dict:
    """Generate report files and return a summary dictionary."""

    if not config.work_db.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {config.work_db}")

    conn = open_report_db(config.work_db)
    try:
        run_row = resolve_run(conn, config.run_id)
        job_guard.ensure_run_matches_job(config.work_db, run_row)
        run_id = str(run_row["run_id"])
        output_dir = output_dir_for_run(config.work_db, run_row, config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        input_rows = fetch_detection_rows(
            conn,
            run_id=run_id,
            min_conf=config.min_conf,
            faces=config.faces,
            classes=config.classes,
            model_run_ids=config.model_run_ids,
            model_names=config.model_names,
        )
        rows, large_bbox_skipped = filter_large_bbox_rows(input_rows, config.max_bbox_area_ratio)
        stationary_skipped: list[dict] = []
        position_count = 0
        if config.exclude_stationary:
            position_db = config.position_db or config.work_db
            positions = read_frame_positions_from_db(position_db, config.position_layer)
            position_count = len(positions)
            rows, stationary_skipped = filter_stationary_rows(
                rows,
                positions,
                config.stationary_window_frames,
                config.stationary_distance_m,
            )
        grouped_rows = group_by_plane(rows)
        if config.write_images:
            annotated_by_plane, annotated_count, missing_count = write_annotated_images(
                config.work_db,
                run_row,
                output_dir,
                grouped_rows,
                config.max_images,
                config.jpeg_quality,
                config.image_sample_mode,
            )
        else:
            annotated_by_plane, annotated_count, missing_count = {}, 0, 0

        detections = detection_csv_rows(rows, annotated_by_plane)
        class_summary = summary_by_class(rows)
        face_summary = summary_by_face(rows)
        model_run_summary = summary_by_model_run(rows)
        model_run_count = len({str(row.get("model_run_id")) for row in rows if row.get("model_run_id")})
        summary = {
            "run_id": run_id,
            "output_dir": str(output_dir),
            "input_detection_count": len(input_rows),
            "detection_count": len(rows),
            "large_bbox_filtered_count": len(large_bbox_skipped),
            "stationary_filtered_count": len(stationary_skipped),
            "stationary_position_count": int(position_count),
            "stationary_window_frames": int(config.stationary_window_frames),
            "stationary_distance_m": float(config.stationary_distance_m),
            "image_plane_with_detection_count": len(grouped_rows),
            "annotated_image_count": annotated_count,
            "missing_image_count": missing_count,
            "model_run_count": model_run_count,
            "min_conf": config.min_conf,
            "max_bbox_area_ratio": config.max_bbox_area_ratio,
            "image_sample_mode": config.image_sample_mode,
            "faces": list(config.faces),
            "classes": list(config.classes),
            "model_run_ids": list(config.model_run_ids),
            "model_names": list(config.model_names),
            "large_bbox_skipped": large_bbox_skipped[:50],
            "stationary_skipped": stationary_skipped[:50],
            "model_run_summary": model_run_summary,
            "class_summary": class_summary,
            "face_summary": face_summary,
        }

        write_csv(
            output_dir / "detections.csv",
            detections,
            [
                "detection_id",
                "model_run_id",
                "model_name",
                "frame_index",
                "face_name",
                "class_id",
                "class_name",
                "confidence",
                "bbox_x1",
                "bbox_y1",
                "bbox_x2",
                "bbox_y2",
                "bbox_width",
                "bbox_height",
                "bbox_area",
                "bbox_area_ratio",
                "image_path",
                "annotated_image",
                "target_id",
                "target_yaw_to_camera_heading",
                "target_pitch_deg",
                "ground_distance_m",
                "projection",
                "quality",
            ],
        )
        write_csv(
            output_dir / "class_summary.csv",
            class_summary,
            [
                "class_name",
                "count",
                "min_confidence",
                "avg_confidence",
                "max_confidence",
                "first_frame",
                "last_frame",
            ],
        )
        write_csv(output_dir / "face_summary.csv", face_summary, ["face_name", "count"])
        write_csv(
            output_dir / "model_run_summary.csv",
            model_run_summary,
            ["model_run_id", "model_name", "count", "first_frame", "last_frame"],
        )
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        write_summary_text(output_dir / "summary.txt", summary)
        write_html_index(output_dir / "index.html", summary, detections)
    finally:
        conn.close()

    return summary


def build_arg_parser():
    """Build yolo-report CLI arguments."""

    parser = argparse.ArgumentParser(description="Generate YOLO detection summaries and annotated images.")
    parser.add_argument("--work-db", required=True, help="semantic_work.sqlite path.")
    parser.add_argument("--run-id", help="Run id. Default: latest run in work DB.")
    parser.add_argument("--output-dir", help="Report output directory. Default: <run work_dir>/yolo_report.")
    parser.add_argument("--min-conf", type=float, default=0.0)
    parser.add_argument("--faces", nargs="+", default=[], help="Optional faces to include.")
    parser.add_argument("--classes", nargs="+", default=[], help="Optional class names to include.")
    parser.add_argument("--model-run-ids", nargs="+", default=[], help="Optional model_run_id values to include.")
    parser.add_argument("--model-names", nargs="+", default=[], help="Optional model_names to include.")
    parser.add_argument("--max-images", type=int, help="Limit number of annotated image planes.")
    parser.add_argument(
        "--image-sample-mode",
        choices=IMAGE_SAMPLE_MODES,
        default="first",
        help="How to choose annotated image planes when --max-images is set.",
    )
    parser.add_argument("--no-images", action="store_true", help="Write summaries only.")
    parser.add_argument("--jpeg-quality", type=int, default=DEFAULT_JPEG_QUALITY)
    parser.add_argument(
        "--position-db",
        help="Optional SQLite/GeoPackage path containing frame positions for stationary filtering.",
    )
    parser.add_argument(
        "--position-layer",
        help="Optional frame position layer/table. Default: auto-detect source_frames or video_gpx_points.",
    )
    parser.add_argument(
        "--exclude-stationary",
        action="store_true",
        help="Exclude detections from frames where the camera barely moved around the frame.",
    )
    parser.add_argument(
        "--stationary-window-frames",
        type=int,
        default=30,
        help="Frame window on each side used by --exclude-stationary.",
    )
    parser.add_argument(
        "--stationary-distance-m",
        type=float,
        default=0.5,
        help="Maximum movement across the stationary window treated as stationary.",
    )
    parser.add_argument(
        "--max-bbox-area-ratio",
        type=float,
        help="Exclude detections whose bbox covers more than this ratio of the image plane, e.g. 0.30.",
    )
    return parser


def config_from_args(args) -> YoloReportConfig:
    """Normalize argparse Namespace into YoloReportConfig."""

    return YoloReportConfig(
        work_db=Path(args.work_db).expanduser().resolve(),
        run_id=args.run_id,
        output_dir=Path(args.output_dir).expanduser().resolve() if args.output_dir else None,
        min_conf=float(args.min_conf),
        faces=normalize_faces(args.faces) if args.faces else (),
        classes=normalize_classes(args.classes),
        model_run_ids=normalize_text_values(args.model_run_ids),
        model_names=normalize_text_values(args.model_names),
        max_images=args.max_images,
        write_images=not bool(args.no_images),
        jpeg_quality=int(args.jpeg_quality),
        max_bbox_area_ratio=args.max_bbox_area_ratio,
        image_sample_mode=str(args.image_sample_mode or "first"),
        position_db=Path(args.position_db).expanduser().resolve() if args.position_db else None,
        position_layer=str(args.position_layer).strip() if args.position_layer else None,
        exclude_stationary=bool(args.exclude_stationary),
        stationary_window_frames=max(1, int(args.stationary_window_frames)),
        stationary_distance_m=max(0.0, float(args.stationary_distance_m)),
    )


def main(argv=None):
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    start = time.perf_counter()
    summary = build_report(config)
    elapsed = time.perf_counter() - start
    print(f"Work DB: {config.work_db}")
    print(f"Run ID: {summary['run_id']}")
    print(f"Output: {summary['output_dir']}")
    print(f"Input detections: {summary['input_detection_count']}")
    print(f"Detections: {summary['detection_count']}")
    if config.max_bbox_area_ratio is not None:
        print(f"Large bbox filtered: {summary['large_bbox_filtered_count']}")
    if config.exclude_stationary:
        print(
            "Stationary filtered: "
            f"{summary['stationary_filtered_count']} "
            f"(positions={summary['stationary_position_count']}, "
            f"window={summary['stationary_window_frames']}, "
            f"distance={summary['stationary_distance_m']:.2f}m)"
        )
    print(f"Annotated images: {summary['annotated_image_count']}")
    print(f"Done in {elapsed:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
