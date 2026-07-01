"""Export semantic POI candidates from semantic_work.sqlite to GeoPackage."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import struct
import re
import time

try:
    from . import job_guard, schema, sqlite_io
except ImportError:
    import job_guard
    import schema
    import sqlite_io


DEFAULT_LAYER_NAME = "poi_candidates_360"
DEFAULT_OUTPUT_GPKG_NAME = "auto_poi.gpkg"
DEFAULT_SRS_ID = 4326
GEOMETRY_COLUMN = "geom"
ALL_CLASSES_LAYER_NAME = "All_Classes"
CLUSTER_LAYER_PREFIX = "poi_clusters"


@dataclass(frozen=True)
class GpkgMergeConfig:
    """CLI arguments normalized for GeoPackage export."""

    work_db: Path
    database: Path | None = None
    run_id: str | None = None
    layer_name: str | None = None
    source: str = "candidates"
    replace: bool = False
    limit: int | None = None
    model_run_ids: tuple[str, ...] = ()
    model_names: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    qualities: tuple[str, ...] = ()
    position_methods: tuple[str, ...] = ()


GPKG_COLUMNS = (
    ("fid", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    (GEOMETRY_COLUMN, "POINT"),
    ("run_id", "TEXT"),
    ("candidate_id", "TEXT"),
    ("cluster_id", "TEXT"),
    ("representative_candidate_id", "TEXT"),
    ("target_id", "TEXT"),
    ("frame", "INTEGER"),
    ("record_type", "TEXT"),
    ("review_status", "TEXT"),
    ("target_source", "TEXT"),
    ("semantic_class", "TEXT"),
    ("confidence", "REAL"),
    ("projection", "TEXT"),
    ("model_run_id", "TEXT"),
    ("model_name", "TEXT"),
    ("detection_id", "TEXT"),
    ("evidence_face", "TEXT"),
    ("evidence_plane_id", "TEXT"),
    ("evidence_image_path", "TEXT"),
    ("evidence_bbox_json", "TEXT"),
    ("bbox_anchor", "TEXT"),
    ("anchor_x_px", "REAL"),
    ("anchor_y_px", "REAL"),
    ("cubemap_u", "REAL"),
    ("cubemap_v", "REAL"),
    ("target_yaw", "REAL"),
    ("target_pitch", "REAL"),
    ("ground_distance_m", "REAL"),
    ("viewer_marker", "TEXT"),
    ("latitude", "REAL"),
    ("longitude", "REAL"),
    ("object_lat", "REAL"),
    ("object_lon", "REAL"),
    ("camera_lat", "REAL"),
    ("camera_lon", "REAL"),
    ("bearing_deg", "REAL"),
    ("distance_m", "REAL"),
    ("position_method", "TEXT"),
    ("distance_method", "TEXT"),
    ("quality", "TEXT"),
    ("observation_count", "INTEGER"),
    ("cluster_score", "REAL"),
    ("cluster_radius_m", "REAL"),
    ("min_frame", "INTEGER"),
    ("max_frame", "INTEGER"),
    ("created_at", "TEXT"),
    ("payload_json", "TEXT"),
)


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


def safe_layer_name(value: str) -> str:
    """Validate a simple GeoPackage layer name."""

    text = str(value or "").strip()
    if not text:
        raise ValueError("Layer name is empty.")
    if len(text) > 63:
        raise ValueError("Layer name must be 63 characters or shorter.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if any(char not in allowed for char in text):
        raise ValueError("Layer name may contain only ASCII letters, digits, and underscore.")
    if text[0].isdigit():
        raise ValueError("Layer name must not start with a digit.")
    return text


def slug_token(value: str, fallback: str = "poi") -> str:
    """Return a compact ASCII token for layer names."""

    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:40] or fallback


def normalize_semantic_class(value: str | None) -> str:
    """Normalize semantic class text for display and grouping."""

    text = str(value or "").strip()
    return text or ALL_CLASSES_LAYER_NAME


def source_display_label(source: str) -> str:
    """Return the user-facing family label for exported layers."""

    return "360 POI Clusters" if source == "clusters" else "360 Detection Candidates"


def resolve_combined_layer_name(config: GpkgMergeConfig) -> str:
    """Return the combined layer table name for this export."""

    if config.layer_name:
        return safe_layer_name(config.layer_name)
    if config.source == "clusters":
        return ALL_CLASSES_LAYER_NAME
    return DEFAULT_LAYER_NAME


def class_layer_name(source: str, semantic_class: str) -> str:
    """Return a stable per-class layer table name."""

    prefix = CLUSTER_LAYER_PREFIX if source == "clusters" else "poi_candidates"
    return safe_layer_name(f"{prefix}_{slug_token(semantic_class)}")


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a table exists."""

    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def connect_readonly_work_db(path: str | Path) -> sqlite3.Connection:
    """Open semantic_work.sqlite in read-only mode."""

    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def gpkg_point_blob(lon: float, lat: float, srs_id: int = DEFAULT_SRS_ID) -> bytes:
    """Return a GeoPackageBinary POINT geometry blob for EPSG:4326."""

    return b"GP" + struct.pack(
        "<BBiBIdd",
        0,  # version
        1,  # little endian, no envelope
        int(srs_id),
        1,  # WKB little endian
        1,  # WKB Point
        float(lon),
        float(lat),
    )


def json_loads(value, default=None):
    """Parse JSON text with a quiet default."""

    return sqlite_io.json_loads(value, default)


def list_item(value, index: int):
    """Return list item when available."""

    if isinstance(value, (list, tuple)) and len(value) > index:
        return value[index]
    return None


def ensure_gpkg_core(conn: sqlite3.Connection):
    """Create minimal GeoPackage metadata tables when missing."""

    conn.execute("PRAGMA application_id = 1196437808")
    conn.execute("PRAGMA user_version = 10300")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys
        (srs_name, srs_id, organization, organization_coordsys_id, definition, description)
        VALUES
        (
            'WGS 84 geodetic',
            4326,
            'EPSG',
            4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
            || 'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],'
            || 'AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]',
            'longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            PRIMARY KEY (table_name, column_name)
        )
        """
    )


def drop_existing_layer(conn: sqlite3.Connection, layer_name: str):
    """Drop one generated GeoPackage feature layer and related metadata."""

    quoted_layer = schema.quote_identifier(layer_name)
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND (tbl_name = ? OR name LIKE ?)",
        (layer_name, f"rtree_{layer_name}_{GEOMETRY_COLUMN}%"),
    ).fetchall():
        conn.execute(f"DROP TRIGGER IF EXISTS {schema.quote_identifier(row[0])}")

    rtree_name = f"rtree_{layer_name}_{GEOMETRY_COLUMN}"
    if table_exists(conn, rtree_name):
        conn.execute(f"DROP TABLE IF EXISTS {schema.quote_identifier(rtree_name)}")

    conn.execute(f"DROP TABLE IF EXISTS {quoted_layer}")
    conn.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (layer_name,))
    conn.execute("DELETE FROM gpkg_geometry_columns WHERE table_name = ?", (layer_name,))
    if table_exists(conn, "gpkg_ogr_contents"):
        conn.execute("DELETE FROM gpkg_ogr_contents WHERE table_name = ?", (layer_name,))
    if table_exists(conn, "gpkg_extensions"):
        conn.execute("DELETE FROM gpkg_extensions WHERE table_name = ?", (layer_name,))


def create_feature_layer(conn: sqlite3.Connection, layer_name: str):
    """Create GeoPackage feature table for POI candidates."""

    body = ",\n            ".join(
        f"{schema.quote_identifier(name)} {column_type}" for name, column_type in GPKG_COLUMNS
    )
    conn.execute(
        f"""
        CREATE TABLE {schema.quote_identifier(layer_name)} (
            {body}
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {schema.quote_identifier(f"idx_{layer_name}_candidate")}
        ON {schema.quote_identifier(layer_name)} ("candidate_id")
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {schema.quote_identifier(f"idx_{layer_name}_frame")}
        ON {schema.quote_identifier(layer_name)} ("frame")
        """
    )


def register_feature_layer(
    conn: sqlite3.Connection,
    layer_name: str,
    feature_count: int,
    extent: tuple[float, float, float, float] | None,
    identifier: str | None = None,
):
    """Register a feature table in GeoPackage metadata tables."""

    now = sqlite_io.utc_now_text()
    identifier_text = str(identifier or layer_name)
    if extent is None:
        min_x = min_y = max_x = max_y = None
    else:
        min_x, min_y, max_x, max_y = extent
    conn.execute(
        """
        INSERT OR REPLACE INTO gpkg_contents
        (table_name, data_type, identifier, description, last_change, min_x, min_y, max_x, max_y, srs_id)
        VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            layer_name,
            identifier_text,
            "YOLO-derived 360 POI candidates generated from semantic_work.sqlite",
            now,
            min_x,
            min_y,
            max_x,
            max_y,
            DEFAULT_SRS_ID,
        ),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO gpkg_geometry_columns
        (table_name, column_name, geometry_type_name, srs_id, z, m)
        VALUES (?, ?, 'POINT', ?, 0, 0)
        """,
        (layer_name, GEOMETRY_COLUMN, DEFAULT_SRS_ID),
    )
    if table_exists(conn, "gpkg_ogr_contents"):
        conn.execute(
            """
            INSERT OR REPLACE INTO gpkg_ogr_contents (table_name, feature_count)
            VALUES (?, ?)
            """,
            (layer_name, int(feature_count)),
        )


def resolve_run(conn: sqlite3.Connection, requested_run_id: str | None = None) -> dict:
    """Resolve run row used for export."""

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


def resolve_database_path(config: GpkgMergeConfig, run_row: dict) -> Path:
    """Resolve output GeoPackage path from CLI or the run's project root."""

    if config.database is not None:
        path = config.database.expanduser().resolve()
    else:
        source_gpkg_text = str(run_row.get("source_gpkg") or "").strip()
        if not source_gpkg_text:
            raise ValueError(
                "--database is required because runs.source_gpkg is empty."
            )
        path = (
            Path(source_gpkg_text)
            .expanduser()
            .resolve()
            .with_name(DEFAULT_OUTPUT_GPKG_NAME)
        )
    if not path.parent.exists():
        raise FileNotFoundError(f"GeoPackage parent directory not found: {path.parent}")
    return path


def build_output_layers(
    source: str,
    combined_layer_name: str,
    feature_rows: list[dict],
) -> list[tuple[str, str, list[dict]]]:
    """Build output layer specs as (table_name, identifier, rows)."""

    family = source_display_label(source)
    if source != "clusters":
        return [
            (
                combined_layer_name,
                f"{family}: {ALL_CLASSES_LAYER_NAME}",
                feature_rows,
            )
        ]

    grouped: dict[str, list[dict]] = {}
    for row in feature_rows:
        semantic_class = normalize_semantic_class(row.get("semantic_class"))
        grouped.setdefault(semantic_class, []).append(row)

    layers: list[tuple[str, str, list[dict]]] = [
        (
            combined_layer_name,
            f"{family}: {ALL_CLASSES_LAYER_NAME}",
            feature_rows,
        )
    ]
    for semantic_class in sorted(grouped):
        layers.append(
            (
                class_layer_name(source, semantic_class),
                f"{family}: {semantic_class}",
                grouped[semantic_class],
            )
        )
    return layers


def select_poi_candidates(
    conn: sqlite3.Connection,
    run_id: str,
    config: GpkgMergeConfig,
) -> list[dict]:
    """Read POI candidates with optional filters."""

    where = [f"p.{schema.quote_identifier('run_id')} = ?"]
    params: list[object] = [run_id]
    filters = (
        ("model_run_id", config.model_run_ids),
        ("model_name", config.model_names),
        ("semantic_class", config.classes),
        ("quality", config.qualities),
        ("position_method", config.position_methods),
    )
    for column, values in filters:
        if not values:
            continue
        where.append(f"p.{schema.quote_identifier(column)} IN ({', '.join('?' for _ in values)})")
        params.extend(values)

    sql = f"""
        SELECT
            p.*,
            t.detection_id AS target_detection_id,
            t.target_yaw_to_camera_heading AS target_yaw,
            t.target_pitch_deg AS target_pitch,
            t.ground_distance_m AS target_ground_distance_m,
            t.evidence_plane_id AS target_evidence_plane_id,
            t.evidence_image_path AS target_evidence_image_path,
            t.evidence_bbox_json AS target_evidence_bbox_json,
            t.bbox_anchor AS target_bbox_anchor,
            t.payload_json AS target_payload_json
        FROM {schema.quote_identifier(schema.POI_CANDIDATES_TABLE)} AS p
        LEFT JOIN {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)} AS t
            ON t.target_id = p.target_id
        WHERE {" AND ".join(where)}
        ORDER BY p.frame_index, p.semantic_class, p.candidate_id
    """
    if config.limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, int(config.limit)))
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def select_poi_clusters(
    conn: sqlite3.Connection,
    run_id: str,
    config: GpkgMergeConfig,
) -> list[dict]:
    """Read clustered POIs with optional filters, shaped like candidate rows."""

    where = [f"c.{schema.quote_identifier('run_id')} = ?"]
    params: list[object] = [run_id]
    filters = (
        ("model_run_id", config.model_run_ids),
        ("model_name", config.model_names),
        ("semantic_class", config.classes),
        ("quality", config.qualities),
        ("position_method", config.position_methods),
    )
    for column, values in filters:
        if not values:
            continue
        where.append(f"c.{schema.quote_identifier(column)} IN ({', '.join('?' for _ in values)})")
        params.extend(values)

    sql = f"""
        SELECT
            c.cluster_id AS cluster_id,
            c.cluster_id AS candidate_id,
            c.representative_candidate_id AS representative_candidate_id,
            c.target_id AS target_id,
            c.run_id AS run_id,
            c.frame_index AS frame_index,
            c.target_source AS target_source,
            c.semantic_class AS semantic_class,
            c.confidence AS confidence,
            c.projection AS projection,
            c.model_run_id AS model_run_id,
            c.model_name AS model_name,
            c.evidence_face AS evidence_face,
            c.camera_lat AS camera_lat,
            c.camera_lon AS camera_lon,
            c.object_lat AS object_lat,
            c.object_lon AS object_lon,
            c.bearing_deg AS bearing_deg,
            c.distance_m AS distance_m,
            c.position_method AS position_method,
            c.distance_method AS distance_method,
            c.quality AS quality,
            c.observation_count AS observation_count,
            c.cluster_score AS cluster_score,
            c.cluster_radius_m AS cluster_radius_m,
            c.min_frame_index AS min_frame_index,
            c.max_frame_index AS max_frame_index,
            c.created_at AS created_at,
            c.payload_json AS payload_json,
            t.detection_id AS target_detection_id,
            t.target_yaw_to_camera_heading AS target_yaw,
            t.target_pitch_deg AS target_pitch,
            t.ground_distance_m AS target_ground_distance_m,
            t.evidence_plane_id AS target_evidence_plane_id,
            t.evidence_image_path AS target_evidence_image_path,
            t.evidence_bbox_json AS target_evidence_bbox_json,
            t.bbox_anchor AS target_bbox_anchor,
            t.payload_json AS target_payload_json
        FROM {schema.quote_identifier(schema.POI_CLUSTERS_TABLE)} AS c
        LEFT JOIN {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)} AS t
            ON t.target_id = c.target_id
        WHERE {" AND ".join(where)}
        ORDER BY c.semantic_class, c.model_name, c.frame_index, c.cluster_id
    """
    if config.limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, int(config.limit)))
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def gpkg_row_from_candidate(candidate: dict) -> dict | None:
    """Convert a poi_candidates_360 row to a GeoPackage feature row."""

    lat = candidate.get("object_lat")
    lon = candidate.get("object_lon")
    if lat is None or lon is None:
        return None
    lat = float(lat)
    lon = float(lon)
    target_payload = json_loads(candidate.get("target_payload_json"), {}) or {}
    anchor_xy = target_payload.get("anchor_xy_px")
    cubemap_uv = target_payload.get("cubemap_uv") or {}
    evidence_bbox_json = candidate.get("target_evidence_bbox_json")
    if evidence_bbox_json in (None, ""):
        bbox = target_payload.get("bbox")
        evidence_bbox_json = json.dumps(bbox, ensure_ascii=False) if bbox is not None else None
    return {
        GEOMETRY_COLUMN: gpkg_point_blob(lon, lat),
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "cluster_id": candidate.get("cluster_id"),
        "representative_candidate_id": candidate.get("representative_candidate_id"),
        "target_id": candidate.get("target_id"),
        "frame": candidate.get("frame_index"),
        "record_type": "poi_cluster" if candidate.get("cluster_id") else "yolo_candidate",
        "review_status": "unreviewed",
        "target_source": candidate.get("target_source"),
        "semantic_class": candidate.get("semantic_class"),
        "confidence": candidate.get("confidence"),
        "projection": candidate.get("projection"),
        "model_run_id": candidate.get("model_run_id"),
        "model_name": candidate.get("model_name"),
        "detection_id": candidate.get("target_detection_id"),
        "evidence_face": candidate.get("evidence_face"),
        "evidence_plane_id": candidate.get("target_evidence_plane_id"),
        "evidence_image_path": candidate.get("target_evidence_image_path"),
        "evidence_bbox_json": evidence_bbox_json,
        "bbox_anchor": candidate.get("target_bbox_anchor"),
        "anchor_x_px": list_item(anchor_xy, 0),
        "anchor_y_px": list_item(anchor_xy, 1),
        "cubemap_u": cubemap_uv.get("u") if isinstance(cubemap_uv, dict) else None,
        "cubemap_v": cubemap_uv.get("v") if isinstance(cubemap_uv, dict) else None,
        "target_yaw": candidate.get("target_yaw"),
        "target_pitch": candidate.get("target_pitch"),
        "ground_distance_m": candidate.get("target_ground_distance_m"),
        "viewer_marker": "target_point",
        "latitude": lat,
        "longitude": lon,
        "object_lat": lat,
        "object_lon": lon,
        "camera_lat": candidate.get("camera_lat"),
        "camera_lon": candidate.get("camera_lon"),
        "bearing_deg": candidate.get("bearing_deg"),
        "distance_m": candidate.get("distance_m"),
        "position_method": candidate.get("position_method"),
        "distance_method": candidate.get("distance_method"),
        "quality": candidate.get("quality"),
        "observation_count": candidate.get("observation_count"),
        "cluster_score": candidate.get("cluster_score"),
        "cluster_radius_m": candidate.get("cluster_radius_m"),
        "min_frame": candidate.get("min_frame_index"),
        "max_frame": candidate.get("max_frame_index"),
        "created_at": candidate.get("created_at"),
        "payload_json": candidate.get("payload_json"),
    }


def insert_gpkg_rows(conn: sqlite3.Connection, layer_name: str, rows: list[dict]) -> int:
    """Insert feature rows into a GeoPackage table."""

    if not rows:
        return 0
    columns = [name for name, _type in GPKG_COLUMNS if name != "fid"]
    sql = (
        f"INSERT INTO {schema.quote_identifier(layer_name)} "
        f"({', '.join(schema.quote_identifier(column) for column in columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )
    conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])
    return len(rows)


def extent_for_rows(rows: list[dict]) -> tuple[float, float, float, float] | None:
    """Return min_x, min_y, max_x, max_y for feature rows."""

    if not rows:
        return None
    xs = [float(row["longitude"]) for row in rows if row.get("longitude") is not None]
    ys = [float(row["latitude"]) for row in rows if row.get("latitude") is not None]
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def export_poi_candidates(config: GpkgMergeConfig) -> dict:
    """Export poi_candidates_360 from semantic_work.sqlite into a GeoPackage layer."""

    if not config.work_db.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {config.work_db}")

    work_conn = connect_readonly_work_db(config.work_db)
    try:
        run_row = resolve_run(work_conn, config.run_id)
        run_id = str(run_row["run_id"])
        gpkg_path = resolve_database_path(config, run_row)
        job_guard.ensure_run_matches_job(
            config.work_db,
            run_row,
            gpkg_path,
            require_database_match=False,
        )
        if config.source == "clusters":
            candidates = select_poi_clusters(work_conn, run_id, config)
        else:
            candidates = select_poi_candidates(work_conn, run_id, config)
    finally:
        work_conn.close()

    feature_rows = []
    skipped = []
    for candidate in candidates:
        row = gpkg_row_from_candidate(candidate)
        if row is None:
            skipped.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": "missing_object_lat_lon",
                }
            )
            continue
        feature_rows.append(row)

    combined_layer_name = resolve_combined_layer_name(config)
    output_layers = build_output_layers(config.source, combined_layer_name, feature_rows)

    gpkg_conn = sqlite3.connect(gpkg_path)
    try:
        ensure_gpkg_core(gpkg_conn)
        for layer_name, _identifier, _rows in output_layers:
            if table_exists(gpkg_conn, layer_name):
                if not config.replace:
                    raise ValueError(
                        f"Layer already exists: {layer_name}. Use --replace to overwrite it."
                    )
                drop_existing_layer(gpkg_conn, layer_name)
        for layer_name, identifier, rows in output_layers:
            create_feature_layer(gpkg_conn, layer_name)
            insert_gpkg_rows(gpkg_conn, layer_name, rows)
            register_feature_layer(
                gpkg_conn,
                layer_name=layer_name,
                feature_count=len(rows),
                extent=extent_for_rows(rows),
                identifier=identifier,
            )
        gpkg_conn.commit()
    except Exception:
        gpkg_conn.rollback()
        raise
    finally:
        gpkg_conn.close()

    return {
        "run_id": run_id,
        "database": str(gpkg_path),
        "layer_name": combined_layer_name,
        "layer_names": [layer_name for layer_name, _identifier, _rows in output_layers],
        "source": config.source,
        "candidate_count": len(candidates),
        "feature_count": len(feature_rows),
        "inserted_count": len(feature_rows),
        "skipped_count": len(skipped),
        "skipped": skipped[:50],
    }


def build_arg_parser():
    """Build CLI argument parser."""

    parser = argparse.ArgumentParser(
        description="Export poi_candidates_360 from semantic_work.sqlite to auto_poi.gpkg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--work-db", required=True, help="semantic_work.sqlite path.")
    parser.add_argument("--database", help="Output GeoPackage path. Default: <runs.source_gpkg parent>/auto_poi.gpkg.")
    parser.add_argument("--run-id", help="Run id. Default: latest run in work DB.")
    parser.add_argument(
        "--layer-name",
        default="",
        help="Combined GeoPackage layer name. Default: All_Classes for clusters, poi_candidates_360 for candidates.",
    )
    parser.add_argument(
        "--source",
        choices=("candidates", "clusters"),
        default="candidates",
        help="Source table to export.",
    )
    parser.add_argument("--replace", action="store_true", help="Replace the output layer when it exists.")
    parser.add_argument("--limit", type=int, help="Limit selected candidates for testing.")
    parser.add_argument("--model-run-ids", nargs="+", default=[], help="Optional model_run_id filters.")
    parser.add_argument("--model-names", nargs="+", default=[], help="Optional model_name filters.")
    parser.add_argument("--classes", nargs="+", default=[], help="Optional semantic_class filters.")
    parser.add_argument("--qualities", nargs="+", default=[], help="Optional quality filters.")
    parser.add_argument("--position-methods", nargs="+", default=[], help="Optional position_method filters.")
    return parser


def config_from_args(args) -> GpkgMergeConfig:
    """Normalize argparse Namespace into GpkgMergeConfig."""

    database = Path(args.database).expanduser().resolve() if args.database else None
    layer_name = str(args.layer_name or "").strip() or None
    return GpkgMergeConfig(
        work_db=Path(args.work_db).expanduser().resolve(),
        database=database,
        run_id=args.run_id,
        layer_name=layer_name,
        source=args.source,
        replace=bool(args.replace),
        limit=args.limit,
        model_run_ids=normalize_text_values(args.model_run_ids),
        model_names=normalize_text_values(args.model_names),
        classes=normalize_text_values(args.classes),
        qualities=normalize_text_values(args.qualities),
        position_methods=normalize_text_values(args.position_methods),
    )


def main(argv=None):
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    start = time.perf_counter()
    result = export_poi_candidates(config)
    elapsed = time.perf_counter() - start
    print(f"Work DB: {config.work_db}")
    print(f"GeoPackage: {result['database']}")
    print(f"Run ID: {result['run_id']}")
    print(f"Layer: {result['layer_name']}")
    if len(result.get("layer_names", [])) > 1:
        print(f"Layers: {', '.join(result['layer_names'])}")
    print(f"Source: {result['source']}")
    print(f"Candidates: {result['candidate_count']}")
    print(f"Features: {result['feature_count']}")
    print(f"Skipped: {result['skipped_count']}")
    print(f"Done in {elapsed:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
