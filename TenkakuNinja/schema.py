"""SQLite schema for the 360 semantic pipeline work database."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3


SCHEMA_VERSION = 2

CUBEMAP_FACE_NAMES = ("front", "right", "back", "left", "up", "down")
DEFAULT_CUBEMAP_EXPORT_FACES = CUBEMAP_FACE_NAMES

RUNS_TABLE = "runs"
SOURCE_FRAMES_TABLE = "source_frames"
IMAGE_PLANES_TABLE = "image_planes"
MODEL_RUNS_TABLE = "model_runs"
YOLO_DETECTIONS_TABLE = "yolo_detections_raw"
SEMANTIC_TARGETS_TABLE = "semantic_targets_360"
POI_CANDIDATES_TABLE = "poi_candidates_360"
METADATA_TABLE = "metadata"


@dataclass(frozen=True)
class Column:
    """SQLite column definition."""

    name: str
    type: str
    constraints: str = ""

    def ddl(self) -> str:
        """Return this column as a DDL fragment."""

        parts = [quote_identifier(self.name), self.type]
        if self.constraints:
            parts.append(self.constraints)
        return " ".join(parts)


@dataclass(frozen=True)
class Table:
    """SQLite table definition used to create semantic_work.sqlite."""

    name: str
    columns: tuple[Column, ...]
    table_constraints: tuple[str, ...] = ()

    def ddl(self) -> str:
        """Return CREATE TABLE DDL for this table."""

        parts = [column.ddl() for column in self.columns]
        parts.extend(self.table_constraints)
        body = ",\n            ".join(parts)
        return (
            f"CREATE TABLE IF NOT EXISTS {quote_identifier(self.name)} (\n"
            f"            {body}\n"
            f"        )"
        )

    def column_names(self) -> tuple[str, ...]:
        """Return column names in table order."""

        return tuple(column.name for column in self.columns)


def quote_identifier(value: str) -> str:
    """Safely quote a SQLite identifier."""

    return '"' + str(value).replace('"', '""') + '"'


TABLES = (
    Table(
        RUNS_TABLE,
        (
            Column("run_id", "TEXT", "PRIMARY KEY"),
            Column("schema_version", "INTEGER", "NOT NULL"),
            Column("created_at", "TEXT", "NOT NULL"),
            Column("updated_at", "TEXT", "NOT NULL"),
            Column("status", "TEXT", "NOT NULL"),
            Column("source_video", "TEXT", "NOT NULL DEFAULT ''"),
            Column("source_gpkg", "TEXT", "NOT NULL DEFAULT ''"),
            Column("work_dir", "TEXT", "NOT NULL DEFAULT ''"),
            Column("config_json", "TEXT", "NOT NULL DEFAULT '{}'"),
            Column("notes", "TEXT", "NOT NULL DEFAULT ''"),
        ),
    ),
    Table(
        SOURCE_FRAMES_TABLE,
        (
            Column("run_id", "TEXT", "NOT NULL"),
            Column("frame_index", "INTEGER", "NOT NULL"),
            Column("source_frame", "INTEGER"),
            Column("frame_shift", "INTEGER"),
            Column("timestamp", "TEXT"),
            Column("camera_lat", "REAL"),
            Column("camera_lon", "REAL"),
            Column("aligned_latitude", "REAL"),
            Column("aligned_longitude", "REAL"),
            Column("kp", "TEXT"),
            Column("kp_distance_m", "REAL"),
            Column("image_path", "TEXT"),
        ),
        ('PRIMARY KEY ("run_id", "frame_index")',),
    ),
    Table(
        IMAGE_PLANES_TABLE,
        (
            Column("plane_id", "TEXT", "PRIMARY KEY"),
            Column("run_id", "TEXT", "NOT NULL"),
            Column("frame_index", "INTEGER", "NOT NULL"),
            Column("source_type", "TEXT", "NOT NULL"),
            Column("projection_type", "TEXT", "NOT NULL"),
            Column("plane_name", "TEXT", "NOT NULL"),
            Column("face_name", "TEXT"),
            Column("image_path", "TEXT", "NOT NULL"),
            Column("parent_image_path", "TEXT"),
            Column("width_px", "INTEGER"),
            Column("height_px", "INTEGER"),
            Column("converter", "TEXT"),
            Column("converter_version", "TEXT"),
            Column("face_convention", "TEXT"),
            Column("transform_json", "TEXT", "NOT NULL DEFAULT '{}'"),
            Column("created_at", "TEXT", "NOT NULL"),
        ),
    ),
    Table(
        MODEL_RUNS_TABLE,
        (
            Column("model_run_id", "TEXT", "PRIMARY KEY"),
            Column("run_id", "TEXT", "NOT NULL"),
            Column("model_name", "TEXT", "NOT NULL DEFAULT ''"),
            Column("model_path", "TEXT", "NOT NULL DEFAULT ''"),
            Column("model_version", "TEXT", "NOT NULL DEFAULT ''"),
            Column("ultralytics_version", "TEXT", "NOT NULL DEFAULT ''"),
            Column("conf", "REAL"),
            Column("imgsz", "INTEGER"),
            Column("device", "TEXT", "NOT NULL DEFAULT ''"),
            Column("classes_json", "TEXT", "NOT NULL DEFAULT '[]'"),
            Column("params_json", "TEXT", "NOT NULL DEFAULT '{}'"),
            Column("created_at", "TEXT", "NOT NULL"),
        ),
    ),
    Table(
        YOLO_DETECTIONS_TABLE,
        (
            Column("detection_id", "TEXT", "PRIMARY KEY"),
            Column("run_id", "TEXT", "NOT NULL"),
            Column("model_run_id", "TEXT", "NOT NULL"),
            Column("plane_id", "TEXT", "NOT NULL"),
            Column("frame_index", "INTEGER", "NOT NULL"),
            Column("class_id", "INTEGER"),
            Column("class_name", "TEXT", "NOT NULL DEFAULT ''"),
            Column("confidence", "REAL"),
            Column("bbox_x1", "REAL"),
            Column("bbox_y1", "REAL"),
            Column("bbox_x2", "REAL"),
            Column("bbox_y2", "REAL"),
            Column("bbox_width", "REAL"),
            Column("bbox_height", "REAL"),
            Column("bbox_area", "REAL"),
            Column("bbox_anchor_default", "TEXT", "NOT NULL DEFAULT 'center'"),
            Column("raw_json", "TEXT", "NOT NULL DEFAULT '{}'"),
            Column("created_at", "TEXT", "NOT NULL"),
        ),
    ),
    Table(
        SEMANTIC_TARGETS_TABLE,
        (
            Column("target_id", "TEXT", "PRIMARY KEY"),
            Column("run_id", "TEXT", "NOT NULL"),
            Column("detection_id", "TEXT"),
            Column("frame_index", "INTEGER", "NOT NULL"),
            Column("target_source", "TEXT", "NOT NULL"),
            Column("semantic_class", "TEXT", "NOT NULL DEFAULT ''"),
            Column("confidence", "REAL"),
            Column("target_yaw_to_camera_heading", "REAL"),
            Column("target_pitch_deg", "REAL"),
            Column("ground_distance_m", "REAL"),
            Column("projection", "TEXT", "NOT NULL DEFAULT 'direction_only'"),
            Column("quality", "TEXT", "NOT NULL DEFAULT 'unknown'"),
            Column("evidence_plane_id", "TEXT"),
            Column("evidence_image_path", "TEXT"),
            Column("evidence_face", "TEXT"),
            Column("evidence_bbox_json", "TEXT", "NOT NULL DEFAULT '[]'"),
            Column("bbox_anchor", "TEXT", "NOT NULL DEFAULT 'center'"),
            Column("payload_json", "TEXT", "NOT NULL DEFAULT '{}'"),
            Column("created_at", "TEXT", "NOT NULL"),
        ),
    ),
    Table(
        POI_CANDIDATES_TABLE,
        (
            Column("candidate_id", "TEXT", "PRIMARY KEY"),
            Column("run_id", "TEXT", "NOT NULL"),
            Column("target_id", "TEXT", "NOT NULL"),
            Column("frame_index", "INTEGER", "NOT NULL"),
            Column("target_source", "TEXT", "NOT NULL DEFAULT ''"),
            Column("semantic_class", "TEXT", "NOT NULL DEFAULT ''"),
            Column("confidence", "REAL"),
            Column("projection", "TEXT", "NOT NULL DEFAULT ''"),
            Column("model_run_id", "TEXT", "NOT NULL DEFAULT ''"),
            Column("model_name", "TEXT", "NOT NULL DEFAULT ''"),
            Column("evidence_face", "TEXT"),
            Column("camera_lat", "REAL"),
            Column("camera_lon", "REAL"),
            Column("object_lat", "REAL"),
            Column("object_lon", "REAL"),
            Column("bearing_deg", "REAL"),
            Column("distance_m", "REAL"),
            Column("position_method", "TEXT", "NOT NULL DEFAULT ''"),
            Column("distance_method", "TEXT", "NOT NULL DEFAULT ''"),
            Column("quality", "TEXT", "NOT NULL DEFAULT 'unknown'"),
            Column("payload_json", "TEXT", "NOT NULL DEFAULT '{}'"),
            Column("created_at", "TEXT", "NOT NULL"),
        ),
    ),
    Table(
        METADATA_TABLE,
        (
            Column("scope", "TEXT", "NOT NULL"),
            Column("scope_id", "TEXT", "NOT NULL DEFAULT ''"),
            Column("key", "TEXT", "NOT NULL"),
            Column("value_json", "TEXT", "NOT NULL"),
        ),
        ('PRIMARY KEY ("scope", "scope_id", "key")',),
    ),
)

TABLE_BY_NAME = {table.name: table for table in TABLES}

INDEX_DDLS = (
    f'CREATE INDEX IF NOT EXISTS "idx_source_frames_frame" ON {quote_identifier(SOURCE_FRAMES_TABLE)} ("frame_index")',
    f'CREATE INDEX IF NOT EXISTS "idx_image_planes_run_frame" ON {quote_identifier(IMAGE_PLANES_TABLE)} ("run_id", "frame_index")',
    f'CREATE INDEX IF NOT EXISTS "idx_yolo_detections_plane" ON {quote_identifier(YOLO_DETECTIONS_TABLE)} ("plane_id")',
    f'CREATE INDEX IF NOT EXISTS "idx_yolo_detections_run_frame" ON {quote_identifier(YOLO_DETECTIONS_TABLE)} ("run_id", "frame_index")',
    f'CREATE INDEX IF NOT EXISTS "idx_semantic_targets_detection" ON {quote_identifier(SEMANTIC_TARGETS_TABLE)} ("detection_id")',
    f'CREATE INDEX IF NOT EXISTS "idx_semantic_targets_run_frame" ON {quote_identifier(SEMANTIC_TARGETS_TABLE)} ("run_id", "frame_index")',
    f'CREATE INDEX IF NOT EXISTS "idx_poi_candidates_target" ON {quote_identifier(POI_CANDIDATES_TABLE)} ("target_id")',
    f'CREATE INDEX IF NOT EXISTS "idx_poi_candidates_run_frame" ON {quote_identifier(POI_CANDIDATES_TABLE)} ("run_id", "frame_index")',
)


def table_names() -> tuple[str, ...]:
    """Return all semantic work DB table names."""

    return tuple(table.name for table in TABLES)


def column_names(table_name: str) -> tuple[str, ...]:
    """Return column names for a known table."""

    return TABLE_BY_NAME[table_name].column_names()


def create_schema(conn: sqlite3.Connection):
    """Create all semantic work DB tables and indexes."""

    conn.execute("PRAGMA foreign_keys = ON")
    for table in TABLES:
        conn.execute(table.ddl())
        ensure_table_columns(conn, table)
    for ddl in INDEX_DDLS:
        conn.execute(ddl)
    set_schema_metadata(conn)


def ensure_table_columns(conn: sqlite3.Connection, table: Table):
    """Add newly defined columns to an existing semantic work table."""

    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({quote_identifier(table.name)})").fetchall()
    }
    for column in table.columns:
        if column.name in existing:
            continue
        conn.execute(
            f"ALTER TABLE {quote_identifier(table.name)} "
            f"ADD COLUMN {column.ddl()}"
        )


def set_schema_metadata(conn: sqlite3.Connection):
    """Store schema-level metadata in the generic metadata table."""

    conn.execute(
        f"""
        INSERT OR REPLACE INTO {quote_identifier(METADATA_TABLE)}
        (scope, scope_id, key, value_json)
        VALUES ('database', '', 'schema_version', ?)
        """,
        (str(SCHEMA_VERSION),),
    )


def read_schema_version(conn: sqlite3.Connection) -> int | None:
    """Read schema version from the metadata table."""

    try:
        row = conn.execute(
            f"""
            SELECT value_json
            FROM {quote_identifier(METADATA_TABLE)}
            WHERE scope = 'database' AND scope_id = '' AND key = 'schema_version'
            """
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        return int(str(row[0]).strip('"'))
    except (TypeError, ValueError):
        return None
