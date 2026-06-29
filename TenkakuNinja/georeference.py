"""Georeference semantic 360 targets into POI candidate coordinates.

This module is QGIS-independent.  It reads click-compatible
semantic_targets_360 rows, combines them with camera positions from the
GPXVideoProcessor GeoPackage, and writes poi_candidates_360.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sqlite3
import time

try:
    from . import projection as geo_projection
    from . import job_guard, schema, sqlite_io
except ImportError:
    import job_guard
    import projection as geo_projection
    import schema
    import sqlite_io


DEFAULT_GPX_LAYER = "video_gpx_points"
DEFAULT_FALLBACK_DISTANCE_M = 10.0
DEFAULT_MAX_GROUND_DISTANCE_M = 10.0
DEFAULT_TRAJECTORY_WINDOW_FRAMES = 60
GPKG_JOB_METADATA_TABLE = "gpx_video_processor_job_metadata"

POSITION_METHOD_GROUND_PLANE = "ground_plane_bearing"
POSITION_METHOD_FIXED_DISTANCE = "fixed_distance_bearing"
DISTANCE_METHOD_GROUND = "semantic_ground_distance"
DISTANCE_METHOD_FIXED = "fixed_distance_for_direction_only"
QUALITY_DIRECTION_ONLY = "direction_only"


@dataclass(frozen=True)
class GeoreferenceConfig:
    """CLI arguments normalized for POI candidate generation."""

    work_db: Path
    run_id: str | None = None
    database: Path | None = None
    gpx_layer: str = DEFAULT_GPX_LAYER
    frame_column: str | None = None
    trajectory_window_frames: int = DEFAULT_TRAJECTORY_WINDOW_FRAMES
    video_front_offset_deg: float | None = None
    fallback_distance_m: float = DEFAULT_FALLBACK_DISTANCE_M
    max_ground_distance_m: float | None = DEFAULT_MAX_GROUND_DISTANCE_M
    exclude_stationary: bool = False
    stationary_distance_m: float = 0.5
    limit: int | None = None
    clear_existing: bool = False
    target_sources: tuple[str, ...] = ()
    model_run_ids: tuple[str, ...] = ()
    model_names: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    projections: tuple[str, ...] = ()


def parse_float(value, default: float | None = None) -> float | None:
    """Parse a loose SQLite value into float."""

    if value is None:
        return default
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_int(value, default: int | None = None) -> int | None:
    """Parse a loose SQLite value into int."""

    if value is None:
        return default
    try:
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def normalize_text_values(values) -> tuple[str, ...]:
    """Normalize optional text filters while preserving order."""

    if not values:
        return ()
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def read_gpkg_job_metadata(database: Path) -> dict:
    """Read GPXVideoProcessor job metadata from tmp.gpkg when available."""

    try:
        with sqlite3.connect(database) as conn:
            rows = conn.execute(
                f"SELECT key, value FROM {GPKG_JOB_METADATA_TABLE}"
            ).fetchall()
    except sqlite3.Error:
        return {}

    metadata = {}
    for key, raw_value in rows:
        try:
            metadata[str(key)] = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            metadata[str(key)] = raw_value
    return metadata


def resolve_video_front_offset_deg(config: GeoreferenceConfig, database_path: Path) -> float:
    """Use the CLI value if supplied, otherwise use tmp.gpkg metadata."""

    if config.video_front_offset_deg is not None:
        return float(config.video_front_offset_deg)
    metadata = read_gpkg_job_metadata(database_path)
    for key in ("video_front_offset_deg", "viewer_front_offset_deg"):
        value = metadata.get(key)
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def normalize_optional_max_distance(value: float | None) -> float | None:
    """Treat non-positive max distance as no maximum."""

    if value is None:
        return None
    value = float(value)
    if value <= 0:
        return None
    return value


def connect_readonly_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite/GeoPackage database as read-only."""

    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a SQLite table exists."""

    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Return column names for a SQLite table."""

    rows = conn.execute(
        f"PRAGMA table_info({schema.quote_identifier(table_name)})"
    ).fetchall()
    return [str(row["name"]) for row in rows]


def first_existing_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first matching column name by case-insensitive comparison."""

    by_lower = {column.lower(): column for column in columns}
    for candidate in candidates:
        found = by_lower.get(candidate.lower())
        if found:
            return found
    return None


def coalesce_expression(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    """Build a COALESCE expression from existing candidate columns."""

    selected = []
    for candidate in candidates:
        column = first_existing_column(columns, (candidate,))
        if column and column not in selected:
            selected.append(column)
    if not selected:
        return None
    quoted = [schema.quote_identifier(column) for column in selected]
    if len(quoted) == 1:
        return quoted[0]
    return f"COALESCE({', '.join(quoted)})"


def read_camera_positions(
    database: str | Path,
    layer: str = DEFAULT_GPX_LAYER,
    frame_column: str | None = None,
) -> dict[int, geo_projection.GeoPoint]:
    """Read camera frame positions from GPXVideoProcessor GeoPackage."""

    conn = connect_readonly_sqlite(database)
    try:
        if not table_exists(conn, layer):
            raise ValueError(f"Layer/table not found in database: {layer}")
        columns = table_columns(conn, layer)
        frame_column = frame_column or first_existing_column(
            columns,
            ("frame", "frame_index", "frame_number", "source_frame"),
        )
        if not frame_column:
            raise ValueError(f"No frame column was found in {layer}.")

        lat_expr = coalesce_expression(columns, ("aligned_latitude", "latitude", "lat"))
        lon_expr = coalesce_expression(columns, ("aligned_longitude", "longitude", "lon", "lng"))
        if not lat_expr or not lon_expr:
            raise ValueError(f"No latitude/longitude columns were found in {layer}.")

        sql = f"""
            SELECT
                {schema.quote_identifier(frame_column)} AS frame_index,
                {lat_expr} AS latitude,
                {lon_expr} AS longitude
            FROM {schema.quote_identifier(layer)}
            ORDER BY {schema.quote_identifier(frame_column)}
        """
        positions: dict[int, geo_projection.GeoPoint] = {}
        for row in conn.execute(sql).fetchall():
            frame = parse_int(row["frame_index"])
            lat = parse_float(row["latitude"])
            lon = parse_float(row["longitude"])
            if frame is None or lat is None or lon is None:
                continue
            positions[int(frame)] = geo_projection.GeoPoint(lat=float(lat), lon=float(lon))
        return positions
    finally:
        conn.close()


def resolve_run(conn: sqlite3.Connection, requested_run_id: str | None = None) -> dict:
    """Resolve run row used for georeferencing."""

    if requested_run_id:
        rows = sqlite_io.fetch_rows(
            conn,
            schema.RUNS_TABLE,
            where="run_id = ?",
            params=(requested_run_id,),
        )
        if not rows:
            raise ValueError(f"run_id not found: {requested_run_id}")
        return rows[0]

    rows = sqlite_io.fetch_rows(
        conn,
        schema.RUNS_TABLE,
        order_by="created_at DESC, run_id DESC",
    )
    if not rows:
        raise ValueError("No run row was found in semantic_work.sqlite.")
    return rows[0]


def resolve_database_path(config: GeoreferenceConfig, run_row: dict) -> Path:
    """Resolve source GeoPackage path from CLI or run metadata."""

    value = config.database or run_row.get("source_gpkg")
    if not value:
        raise ValueError("--database is required because runs.source_gpkg is empty.")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source GeoPackage not found: {path}")
    return path


def target_payload(row: dict) -> dict:
    """Decode semantic target payload JSON."""

    return sqlite_io.json_loads(row.get("payload_json"), {}) or {}


def target_model_run_id(row: dict, payload: dict | None = None) -> str:
    """Return model_run_id from joined detection or target payload."""

    payload = payload if payload is not None else target_payload(row)
    return str(row.get("model_run_id") or payload.get("model_run_id") or "")


def target_model_name(row: dict, payload: dict | None = None) -> str:
    """Return model_name from joined detection or target payload."""

    payload = payload if payload is not None else target_payload(row)
    return str(row.get("model_name") or payload.get("model_name") or "")


def select_semantic_targets(
    conn: sqlite3.Connection,
    run_id: str,
    config: GeoreferenceConfig,
) -> list[dict]:
    """Return semantic_targets_360 rows with optional model filters."""

    sql = f"""
        SELECT
            t.*,
            d.model_run_id AS model_run_id,
            d.class_name AS detection_class_name,
            m.model_name AS model_name
        FROM {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)} AS t
        LEFT JOIN {schema.quote_identifier(schema.YOLO_DETECTIONS_TABLE)} AS d
            ON d.detection_id = t.detection_id
        LEFT JOIN {schema.quote_identifier(schema.MODEL_RUNS_TABLE)} AS m
            ON m.model_run_id = d.model_run_id
        WHERE t.run_id = ?
        ORDER BY t.frame_index, t.target_id
    """
    rows = [dict(row) for row in conn.execute(sql, (run_id,)).fetchall()]

    target_sources = set(config.target_sources)
    model_run_ids = set(config.model_run_ids)
    model_names = set(config.model_names)
    classes = set(config.classes)
    projections = set(config.projections)

    selected = []
    for row in rows:
        payload = target_payload(row)
        if target_sources and str(row.get("target_source") or "") not in target_sources:
            continue
        if classes and str(row.get("semantic_class") or "") not in classes:
            continue
        if projections and str(row.get("projection") or "") not in projections:
            continue
        if model_run_ids and target_model_run_id(row, payload) not in model_run_ids:
            continue
        if model_names and target_model_name(row, payload) not in model_names:
            continue
        selected.append(row)
        if config.limit is not None and len(selected) >= max(0, int(config.limit)):
            break
    return selected


def clear_poi_candidates(
    conn: sqlite3.Connection,
    run_id: str,
    target_ids: tuple[str, ...],
) -> int:
    """Delete generated POI candidates for selected target IDs."""

    if not target_ids:
        return 0
    before = conn.total_changes
    for start in range(0, len(target_ids), 500):
        chunk = target_ids[start : start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        conn.execute(
            f"""
            DELETE FROM {schema.quote_identifier(schema.POI_CANDIDATES_TABLE)}
            WHERE run_id = ? AND target_id IN ({placeholders})
            """,
            (run_id, *chunk),
        )
    return conn.total_changes - before


def candidate_id_for_target(target_id: str) -> str:
    """Return deterministic candidate id for a semantic target."""

    return f"poi_{target_id}"


def distance_plan_for_target(
    target: dict,
    fallback_distance_m: float,
    max_ground_distance_m: float | None,
) -> tuple[float | None, str, str, str, str | None]:
    """Return distance/method/quality plan or a skip reason."""

    semantic_projection = str(target.get("projection") or "")
    ground_distance_m = parse_float(target.get("ground_distance_m"))
    if semantic_projection == "ground_plane" and ground_distance_m is not None and ground_distance_m > 0:
        if max_ground_distance_m is not None and ground_distance_m > max_ground_distance_m:
            return (
                None,
                POSITION_METHOD_GROUND_PLANE,
                DISTANCE_METHOD_GROUND,
                str(target.get("quality") or "far"),
                "ground_distance_exceeds_max",
            )
        return (
            float(ground_distance_m),
            POSITION_METHOD_GROUND_PLANE,
            DISTANCE_METHOD_GROUND,
            str(target.get("quality") or "unknown"),
            None,
        )

    if fallback_distance_m <= 0:
        return (
            None,
            POSITION_METHOD_FIXED_DISTANCE,
            DISTANCE_METHOD_FIXED,
            QUALITY_DIRECTION_ONLY,
            "fallback_distance_is_not_positive",
        )
    return (
        float(fallback_distance_m),
        POSITION_METHOD_FIXED_DISTANCE,
        DISTANCE_METHOD_FIXED,
        QUALITY_DIRECTION_ONLY,
        None,
    )


def poi_candidate_from_target(
    target: dict,
    camera_position: geo_projection.GeoPoint,
    heading: geo_projection.HeadingResult,
    config: GeoreferenceConfig,
) -> tuple[dict | None, dict | None]:
    """Build one insertable POI candidate row from a semantic target."""

    target_yaw = parse_float(target.get("target_yaw_to_camera_heading"))
    if target_yaw is None:
        return None, {"target_id": target.get("target_id"), "reason": "missing_target_yaw"}

    max_ground_distance_m = normalize_optional_max_distance(config.max_ground_distance_m)
    distance_m, position_method, distance_method, quality, skip_reason = distance_plan_for_target(
        target,
        fallback_distance_m=float(config.fallback_distance_m),
        max_ground_distance_m=max_ground_distance_m,
    )
    if skip_reason:
        return None, {
            "target_id": target.get("target_id"),
            "frame_index": target.get("frame_index"),
            "reason": skip_reason,
            "distance_m": parse_float(target.get("ground_distance_m")),
            "max_ground_distance_m": max_ground_distance_m,
        }
    if distance_m is None:
        return None, {"target_id": target.get("target_id"), "reason": "missing_distance"}

    bearing_deg = geo_projection.normalize_angle_deg(
        heading.heading_deg + float(config.video_front_offset_deg) + target_yaw
    )
    object_point = geo_projection.destination_point(
        camera_position.lat,
        camera_position.lon,
        bearing_deg,
        distance_m,
    )
    payload = target_payload(target)
    model_run_id = target_model_run_id(target, payload)
    model_name = target_model_name(target, payload)
    candidate_payload = {
        "source": "semantic_target_georeference",
        "target_id": target.get("target_id"),
        "detection_id": target.get("detection_id"),
        "target_source": target.get("target_source") or "",
        "semantic_class": target.get("semantic_class") or "",
        "confidence": target.get("confidence"),
        "semantic_projection": target.get("projection") or "",
        "semantic_quality": target.get("quality") or "",
        "target_yaw_to_camera_heading": target_yaw,
        "target_pitch_deg": parse_float(target.get("target_pitch_deg")),
        "ground_distance_m": parse_float(target.get("ground_distance_m")),
        "trajectory_heading_deg": heading.heading_deg,
        "trajectory_distance_m": heading.distance_m,
        "trajectory_method": heading.method,
        "trajectory_before_frame": heading.before_frame,
        "trajectory_after_frame": heading.after_frame,
        "video_front_offset_deg": float(config.video_front_offset_deg),
        "bearing_deg": bearing_deg,
        "distance_m": distance_m,
        "position_method": position_method,
        "distance_method": distance_method,
        "fallback_distance_m": float(config.fallback_distance_m),
        "max_ground_distance_m": max_ground_distance_m,
        "model_run_id": model_run_id,
        "model_name": model_name,
        "evidence_face": target.get("evidence_face"),
        "evidence_plane_id": target.get("evidence_plane_id"),
        "evidence_image_path": target.get("evidence_image_path"),
    }

    return (
        {
            "candidate_id": candidate_id_for_target(str(target["target_id"])),
            "run_id": str(target["run_id"]),
            "target_id": str(target["target_id"]),
            "frame_index": int(target["frame_index"]),
            "target_source": str(target.get("target_source") or ""),
            "semantic_class": str(target.get("semantic_class") or ""),
            "confidence": parse_float(target.get("confidence")),
            "projection": str(target.get("projection") or ""),
            "model_run_id": model_run_id,
            "model_name": model_name,
            "evidence_face": target.get("evidence_face"),
            "camera_lat": camera_position.lat,
            "camera_lon": camera_position.lon,
            "object_lat": object_point.lat,
            "object_lon": object_point.lon,
            "bearing_deg": bearing_deg,
            "distance_m": distance_m,
            "position_method": position_method,
            "distance_method": distance_method,
            "quality": quality,
            "payload": candidate_payload,
        },
        None,
    )


def insert_poi_candidate_row(conn: sqlite3.Connection, row: dict) -> str:
    """Insert or replace one POI candidate row."""

    return sqlite_io.insert_poi_candidate(
        conn,
        run_id=row["run_id"],
        target_id=row["target_id"],
        frame_index=row["frame_index"],
        target_source=row.get("target_source") or "",
        semantic_class=row.get("semantic_class") or "",
        confidence=row.get("confidence"),
        projection=row.get("projection") or "",
        model_run_id=row.get("model_run_id") or "",
        model_name=row.get("model_name") or "",
        evidence_face=row.get("evidence_face"),
        camera_lat=row.get("camera_lat"),
        camera_lon=row.get("camera_lon"),
        object_lat=row.get("object_lat"),
        object_lon=row.get("object_lon"),
        bearing_deg=row.get("bearing_deg"),
        distance_m=row.get("distance_m"),
        position_method=row.get("position_method") or "",
        distance_method=row.get("distance_method") or "",
        quality=row.get("quality") or "unknown",
        payload=row.get("payload"),
        candidate_id=row.get("candidate_id"),
        replace=True,
    )


def generate_poi_candidates(config: GeoreferenceConfig) -> dict:
    """Generate poi_candidates_360 rows from semantic_targets_360."""

    if not config.work_db.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {config.work_db}")

    conn = sqlite_io.initialize(config.work_db)
    try:
        run_row = resolve_run(conn, config.run_id)
        run_id = str(run_row["run_id"])
        database_path = resolve_database_path(config, run_row)
        job_guard.ensure_run_matches_job(config.work_db, run_row, database_path)
        config = replace(
            config,
            video_front_offset_deg=resolve_video_front_offset_deg(config, database_path),
        )
        positions = read_camera_positions(
            database_path,
            layer=config.gpx_layer,
            frame_column=config.frame_column,
        )
        if not positions:
            raise ValueError(f"No camera positions were read from {database_path}.")

        targets = select_semantic_targets(conn, run_id, config)
        target_ids = tuple(str(row["target_id"]) for row in targets)
        deleted_count = clear_poi_candidates(conn, run_id, target_ids) if config.clear_existing else 0

        candidate_ids = []
        skipped = []
        ground_distance_count = 0
        fixed_distance_count = 0
        for target in targets:
            frame_index = int(target["frame_index"])
            camera_position = positions.get(frame_index)
            if camera_position is None:
                skipped.append(
                    {
                        "target_id": target.get("target_id"),
                        "frame_index": frame_index,
                        "reason": "missing_camera_position",
                    }
                )
                continue
            heading = geo_projection.trajectory_heading(
                positions,
                frame_index,
                window_frames=config.trajectory_window_frames,
            )
            if heading is None:
                skipped.append(
                    {
                        "target_id": target.get("target_id"),
                        "frame_index": frame_index,
                        "reason": "missing_trajectory_heading",
                    }
                )
                continue
            if config.exclude_stationary and heading.distance_m <= max(0.0, float(config.stationary_distance_m)):
                skipped.append(
                    {
                        "target_id": target.get("target_id"),
                        "frame_index": frame_index,
                        "reason": "stationary_camera",
                        "trajectory_distance_m": heading.distance_m,
                        "stationary_distance_m": float(config.stationary_distance_m),
                        "trajectory_before_frame": heading.before_frame,
                        "trajectory_after_frame": heading.after_frame,
                    }
                )
                continue
            candidate, skip = poi_candidate_from_target(
                target,
                camera_position=camera_position,
                heading=heading,
                config=config,
            )
            if skip is not None:
                skipped.append(skip)
                continue
            assert candidate is not None
            candidate_ids.append(insert_poi_candidate_row(conn, candidate))
            if candidate.get("distance_method") == DISTANCE_METHOD_GROUND:
                ground_distance_count += 1
            elif candidate.get("distance_method") == DISTANCE_METHOD_FIXED:
                fixed_distance_count += 1

        summary = {
            "run_id": run_id,
            "database": str(database_path),
            "gpx_layer": config.gpx_layer,
            "camera_position_count": len(positions),
            "target_count": len(targets),
            "candidate_count": len(candidate_ids),
            "ground_distance_candidate_count": int(ground_distance_count),
            "fixed_distance_candidate_count": int(fixed_distance_count),
            "skipped_count": len(skipped),
            "deleted_count": deleted_count,
            "trajectory_window_frames": config.trajectory_window_frames,
            "exclude_stationary": bool(config.exclude_stationary),
            "stationary_distance_m": float(config.stationary_distance_m),
            "video_front_offset_deg": config.video_front_offset_deg,
            "fallback_distance_m": config.fallback_distance_m,
            "max_ground_distance_m": normalize_optional_max_distance(config.max_ground_distance_m),
            "target_sources": list(config.target_sources),
            "model_run_ids": list(config.model_run_ids),
            "model_names": list(config.model_names),
            "classes": list(config.classes),
            "projections": list(config.projections),
            "skipped": skipped[:50],
        }
        sqlite_io.set_metadata(
            conn,
            "run",
            "poi_candidate_summary",
            summary,
            scope_id=run_id,
        )
        sqlite_io.update_run_status(conn, run_id, "poi_candidates_generated")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return summary


def build_arg_parser():
    """Build CLI argument parser."""

    parser = argparse.ArgumentParser(
        description="Georeference semantic_targets_360 into poi_candidates_360.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--work-db", required=True, help="semantic_work.sqlite path.")
    parser.add_argument("--run-id", help="Run id. Default: latest run in work DB.")
    parser.add_argument("--database", help="Source GeoPackage path. Default: runs.source_gpkg.")
    parser.add_argument("--gpx-layer", default=DEFAULT_GPX_LAYER, help="Camera position layer/table.")
    parser.add_argument("--frame-column", help="Frame column in the camera position layer.")
    parser.add_argument(
        "--trajectory-window-frames",
        type=int,
        default=DEFAULT_TRAJECTORY_WINDOW_FRAMES,
        help="Frame window used to derive trajectory heading.",
    )
    parser.add_argument(
        "--video-front-offset-deg",
        type=float,
        default=None,
        help="Clockwise offset from trajectory heading to video front direction. Default: tmp.gpkg metadata or 0.",
    )
    parser.add_argument(
        "--fallback-distance-m",
        type=float,
        default=DEFAULT_FALLBACK_DISTANCE_M,
        help="Distance used for elevated/direction-only targets.",
    )
    parser.add_argument(
        "--max-ground-distance-m",
        type=float,
        default=DEFAULT_MAX_GROUND_DISTANCE_M,
        help="Skip ground-plane targets farther than this. Use 0 to disable.",
    )
    parser.add_argument(
        "--exclude-stationary",
        action="store_true",
        help="Skip targets whose trajectory baseline moved less than --stationary-distance-m.",
    )
    parser.add_argument(
        "--stationary-distance-m",
        type=float,
        default=0.5,
        help="Maximum trajectory baseline distance treated as stationary when --exclude-stationary is set.",
    )
    parser.add_argument("--limit", type=int, help="Limit selected semantic targets for testing.")
    parser.add_argument("--clear-existing", action="store_true", help="Delete candidates for selected targets first.")
    parser.add_argument("--target-sources", nargs="+", default=[], help="Optional target_source filters.")
    parser.add_argument("--model-run-ids", nargs="+", default=[], help="Optional model_run_id filters.")
    parser.add_argument("--model-names", nargs="+", default=[], help="Optional model_name filters.")
    parser.add_argument("--classes", nargs="+", default=[], help="Optional semantic_class filters.")
    parser.add_argument("--projections", nargs="+", default=[], help="Optional projection filters.")
    return parser


def config_from_args(args) -> GeoreferenceConfig:
    """Normalize argparse Namespace into GeoreferenceConfig."""

    database = Path(args.database).expanduser().resolve() if args.database else None
    return GeoreferenceConfig(
        work_db=Path(args.work_db).expanduser().resolve(),
        run_id=args.run_id,
        database=database,
        gpx_layer=args.gpx_layer,
        frame_column=args.frame_column,
        trajectory_window_frames=max(1, int(args.trajectory_window_frames)),
        video_front_offset_deg=None if args.video_front_offset_deg is None else float(args.video_front_offset_deg),
        fallback_distance_m=float(args.fallback_distance_m),
        max_ground_distance_m=normalize_optional_max_distance(args.max_ground_distance_m),
        exclude_stationary=bool(args.exclude_stationary),
        stationary_distance_m=max(0.0, float(args.stationary_distance_m)),
        limit=args.limit,
        clear_existing=bool(args.clear_existing),
        target_sources=normalize_text_values(args.target_sources),
        model_run_ids=normalize_text_values(args.model_run_ids),
        model_names=normalize_text_values(args.model_names),
        classes=normalize_text_values(args.classes),
        projections=normalize_text_values(args.projections),
    )


def main(argv=None):
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    start = time.perf_counter()
    result = generate_poi_candidates(config)
    elapsed = time.perf_counter() - start
    print(f"Work DB: {config.work_db}")
    print(f"Run ID: {result['run_id']}")
    print(f"Camera positions: {result['camera_position_count']}")
    print(f"Targets: {result['target_count']}")
    print(f"POI candidates: {result['candidate_count']}")
    print(f"  ground distance: {result['ground_distance_candidate_count']}")
    print(f"  fixed distance: {result['fixed_distance_candidate_count']}")
    print(f"Skipped: {result['skipped_count']}")
    if result.get("exclude_stationary"):
        print(f"Stationary filter: distance<={result['stationary_distance_m']:.2f}m")
    if result["deleted_count"]:
        print(f"Deleted existing candidates: {result['deleted_count']}")
    print(f"Done in {elapsed:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
