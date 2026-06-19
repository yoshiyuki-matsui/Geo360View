"""SQLite IO helpers for semantic_work.sqlite."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
import uuid

try:
    from . import schema
except ImportError:
    import schema


JSON_COLUMNS = {
    "config_json",
    "transform_json",
    "classes_json",
    "params_json",
    "raw_json",
    "evidence_bbox_json",
    "payload_json",
    "value_json",
}


def utc_now_text() -> str:
    """Return current UTC time as an ISO-8601 text."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Create a compact stable-enough identifier for pipeline rows."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def json_dumps(value) -> str:
    """Serialize a value for SQLite JSON text columns."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")) or stripped in ("null", "true", "false"):
            return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value, default=None):
    """Parse a JSON text value with a default fallback."""

    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def encode_column_value(column: str, value):
    """Encode Python values for SQLite columns."""

    if value is None:
        return None
    if column in JSON_COLUMNS:
        return json_dumps(value)
    if isinstance(value, Path):
        return str(value)
    return value


def connect(path: str | Path, timeout: float = 60.0) -> sqlite3.Connection:
    """Open a semantic work DB and return a row-dict capable connection."""

    conn = sqlite3.connect(Path(path), timeout=float(timeout))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(float(timeout) * 1000)}")
    return conn


def is_lock_error(error: sqlite3.OperationalError) -> bool:
    """Return True when SQLite reports a transient database lock."""

    text = str(error).lower()
    return "database is locked" in text or "database is busy" in text or "locked" == text.strip()


def commit_with_retry(
    conn: sqlite3.Connection,
    attempts: int = 6,
    delay_seconds: float = 5.0,
):
    """Commit, retrying transient SQLite lock failures without losing the transaction."""

    max_attempts = max(1, int(attempts))
    for attempt in range(1, max_attempts + 1):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if not is_lock_error(e) or attempt >= max_attempts:
                raise
            time.sleep(max(0.0, float(delay_seconds)) * attempt)


@contextmanager
def open_work_db(path: str | Path):
    """Context manager that opens and initializes a semantic work DB."""

    conn = connect(path)
    try:
        schema.create_schema(conn)
        yield conn
        commit_with_retry(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(path: str | Path) -> sqlite3.Connection:
    """Open a DB, create schema, commit, and return the connection."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    schema.create_schema(conn)
    commit_with_retry(conn)
    return conn


def insert_row(conn: sqlite3.Connection, table_name: str, values: dict):
    """Insert a row into a known schema table."""

    columns = [column for column in schema.column_names(table_name) if column in values]
    if not columns:
        raise ValueError(f"No known columns supplied for {table_name}.")
    placeholders = ", ".join(["?"] * len(columns))
    sql = (
        f"INSERT INTO {schema.quote_identifier(table_name)} "
        f"({', '.join(schema.quote_identifier(column) for column in columns)}) "
        f"VALUES ({placeholders})"
    )
    params = [encode_column_value(column, values[column]) for column in columns]
    conn.execute(sql, params)


def upsert_row(conn: sqlite3.Connection, table_name: str, values: dict):
    """Insert or replace a row in a known schema table."""

    columns = [column for column in schema.column_names(table_name) if column in values]
    if not columns:
        raise ValueError(f"No known columns supplied for {table_name}.")
    placeholders = ", ".join(["?"] * len(columns))
    sql = (
        f"INSERT OR REPLACE INTO {schema.quote_identifier(table_name)} "
        f"({', '.join(schema.quote_identifier(column) for column in columns)}) "
        f"VALUES ({placeholders})"
    )
    params = [encode_column_value(column, values[column]) for column in columns]
    conn.execute(sql, params)


def create_run(
    conn: sqlite3.Connection,
    source_video: str | Path = "",
    source_gpkg: str | Path = "",
    work_dir: str | Path = "",
    config: dict | None = None,
    run_id: str | None = None,
    status: str = "created",
    notes: str = "",
) -> str:
    """Create a pipeline run row and return run_id."""

    run_id = run_id or new_id("run")
    now = utc_now_text()
    insert_row(
        conn,
        schema.RUNS_TABLE,
        {
            "run_id": run_id,
            "schema_version": schema.SCHEMA_VERSION,
            "created_at": now,
            "updated_at": now,
            "status": status,
            "source_video": str(source_video or ""),
            "source_gpkg": str(source_gpkg or ""),
            "work_dir": str(work_dir or ""),
            "config_json": config or {},
            "notes": notes,
        },
    )
    return run_id


def update_run_status(conn: sqlite3.Connection, run_id: str, status: str):
    """Update run status and timestamp."""

    conn.execute(
        f"""
        UPDATE {schema.quote_identifier(schema.RUNS_TABLE)}
        SET status = ?, updated_at = ?
        WHERE run_id = ?
        """,
        (str(status), utc_now_text(), str(run_id)),
    )


def set_metadata(
    conn: sqlite3.Connection,
    scope: str,
    key: str,
    value,
    scope_id: str = "",
):
    """Set generic self-describing metadata."""

    upsert_row(
        conn,
        schema.METADATA_TABLE,
        {
            "scope": scope,
            "scope_id": scope_id,
            "key": key,
            "value_json": value,
        },
    )


def get_metadata(
    conn: sqlite3.Connection,
    scope: str,
    key: str,
    scope_id: str = "",
    default=None,
):
    """Get generic metadata as a decoded JSON value."""

    row = conn.execute(
        f"""
        SELECT value_json
        FROM {schema.quote_identifier(schema.METADATA_TABLE)}
        WHERE scope = ? AND scope_id = ? AND key = ?
        """,
        (scope, scope_id, key),
    ).fetchone()
    if row is None:
        return default
    return json_loads(row["value_json"], default)


def insert_image_plane(
    conn: sqlite3.Connection,
    run_id: str,
    frame_index: int,
    plane_name: str,
    image_path: str | Path,
    projection_type: str = "cubemap_face",
    source_type: str = "equirectangular_360",
    face_name: str | None = None,
    parent_image_path: str | Path | None = None,
    width_px: int | None = None,
    height_px: int | None = None,
    converter: str = "",
    converter_version: str = "",
    face_convention: str = "",
    transform: dict | None = None,
    plane_id: str | None = None,
) -> str:
    """Insert an image plane row and return plane_id."""

    plane_id = plane_id or new_id("plane")
    insert_row(
        conn,
        schema.IMAGE_PLANES_TABLE,
        {
            "plane_id": plane_id,
            "run_id": run_id,
            "frame_index": int(frame_index),
            "source_type": source_type,
            "projection_type": projection_type,
            "plane_name": plane_name,
            "face_name": face_name,
            "image_path": str(image_path),
            "parent_image_path": str(parent_image_path) if parent_image_path else None,
            "width_px": width_px,
            "height_px": height_px,
            "converter": converter,
            "converter_version": converter_version,
            "face_convention": face_convention,
            "transform_json": transform or {},
            "created_at": utc_now_text(),
        },
    )
    return plane_id


def insert_model_run(
    conn: sqlite3.Connection,
    run_id: str,
    model_name: str = "",
    model_path: str | Path = "",
    model_version: str = "",
    ultralytics_version: str = "",
    conf: float | None = None,
    imgsz: int | None = None,
    device: str = "",
    classes: list | tuple | None = None,
    params: dict | None = None,
    model_run_id: str | None = None,
) -> str:
    """Insert a YOLO model run row and return model_run_id."""

    model_run_id = model_run_id or new_id("model")
    insert_row(
        conn,
        schema.MODEL_RUNS_TABLE,
        {
            "model_run_id": model_run_id,
            "run_id": run_id,
            "model_name": model_name,
            "model_path": str(model_path or ""),
            "model_version": model_version,
            "ultralytics_version": ultralytics_version,
            "conf": conf,
            "imgsz": imgsz,
            "device": device,
            "classes_json": list(classes or []),
            "params_json": params or {},
            "created_at": utc_now_text(),
        },
    )
    return model_run_id


def insert_yolo_detection(
    conn: sqlite3.Connection,
    run_id: str,
    model_run_id: str,
    plane_id: str,
    frame_index: int,
    bbox: tuple[float, float, float, float],
    class_id: int | None = None,
    class_name: str = "",
    confidence: float | None = None,
    bbox_anchor_default: str = "center",
    raw: dict | None = None,
    detection_id: str | None = None,
) -> str:
    """Insert one raw YOLO detection and return detection_id."""

    x1, y1, x2, y2 = [float(value) for value in bbox]
    width = x2 - x1
    height = y2 - y1
    detection_id = detection_id or new_id("det")
    insert_row(
        conn,
        schema.YOLO_DETECTIONS_TABLE,
        {
            "detection_id": detection_id,
            "run_id": run_id,
            "model_run_id": model_run_id,
            "plane_id": plane_id,
            "frame_index": int(frame_index),
            "class_id": class_id,
            "class_name": class_name,
            "confidence": confidence,
            "bbox_x1": x1,
            "bbox_y1": y1,
            "bbox_x2": x2,
            "bbox_y2": y2,
            "bbox_width": width,
            "bbox_height": height,
            "bbox_area": max(0.0, width) * max(0.0, height),
            "bbox_anchor_default": bbox_anchor_default,
            "raw_json": raw or {},
            "created_at": utc_now_text(),
        },
    )
    return detection_id


def insert_semantic_target(
    conn: sqlite3.Connection,
    run_id: str,
    frame_index: int,
    target_source: str,
    target_yaw_to_camera_heading: float | None,
    target_pitch_deg: float | None,
    detection_id: str | None = None,
    semantic_class: str = "",
    confidence: float | None = None,
    ground_distance_m: float | None = None,
    projection: str = "direction_only",
    quality: str = "unknown",
    evidence_plane_id: str | None = None,
    evidence_image_path: str | Path | None = None,
    evidence_face: str | None = None,
    evidence_bbox: list | tuple | None = None,
    bbox_anchor: str = "center",
    payload: dict | None = None,
    target_id: str | None = None,
) -> str:
    """Insert one click-compatible semantic target and return target_id."""

    target_id = target_id or new_id("target")
    insert_row(
        conn,
        schema.SEMANTIC_TARGETS_TABLE,
        {
            "target_id": target_id,
            "run_id": run_id,
            "detection_id": detection_id,
            "frame_index": int(frame_index),
            "target_source": target_source,
            "semantic_class": semantic_class,
            "confidence": confidence,
            "target_yaw_to_camera_heading": target_yaw_to_camera_heading,
            "target_pitch_deg": target_pitch_deg,
            "ground_distance_m": ground_distance_m,
            "projection": projection,
            "quality": quality,
            "evidence_plane_id": evidence_plane_id,
            "evidence_image_path": str(evidence_image_path) if evidence_image_path else None,
            "evidence_face": evidence_face,
            "evidence_bbox_json": list(evidence_bbox or []),
            "bbox_anchor": bbox_anchor,
            "payload_json": payload or {},
            "created_at": utc_now_text(),
        },
    )
    return target_id


def insert_poi_candidate(
    conn: sqlite3.Connection,
    run_id: str,
    target_id: str,
    frame_index: int,
    camera_lat: float | None,
    camera_lon: float | None,
    object_lat: float | None,
    object_lon: float | None,
    bearing_deg: float | None,
    distance_m: float | None,
    position_method: str,
    distance_method: str,
    quality: str = "unknown",
    target_source: str = "",
    semantic_class: str = "",
    confidence: float | None = None,
    projection: str = "",
    model_run_id: str = "",
    model_name: str = "",
    evidence_face: str | None = None,
    payload: dict | None = None,
    candidate_id: str | None = None,
    replace: bool = False,
) -> str:
    """Insert one georeferenced POI candidate and return candidate_id."""

    candidate_id = candidate_id or new_id("candidate")
    writer = upsert_row if replace else insert_row
    writer(
        conn,
        schema.POI_CANDIDATES_TABLE,
        {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "target_id": target_id,
            "frame_index": int(frame_index),
            "target_source": target_source,
            "semantic_class": semantic_class,
            "confidence": confidence,
            "projection": projection,
            "model_run_id": model_run_id,
            "model_name": model_name,
            "evidence_face": evidence_face,
            "camera_lat": camera_lat,
            "camera_lon": camera_lon,
            "object_lat": object_lat,
            "object_lon": object_lon,
            "bearing_deg": bearing_deg,
            "distance_m": distance_m,
            "position_method": position_method,
            "distance_method": distance_method,
            "quality": quality,
            "payload_json": payload or {},
            "created_at": utc_now_text(),
        },
    )
    return candidate_id


def fetch_rows(
    conn: sqlite3.Connection,
    table_name: str,
    where: str = "",
    params: tuple | list = (),
    order_by: str = "",
) -> list[dict]:
    """Fetch rows from a known table as dictionaries."""

    if table_name not in schema.TABLE_BY_NAME:
        raise ValueError(f"Unknown table: {table_name}")
    sql = f"SELECT * FROM {schema.quote_identifier(table_name)}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
