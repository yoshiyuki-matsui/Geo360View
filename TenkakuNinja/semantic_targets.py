"""Convert YOLO CubeMap detections into click-compatible semantic targets.

This module is intentionally QGIS-independent.  It reads yolo_detections_raw,
uses the CubeMap face convention to convert bbox anchors into camera yaw/pitch,
and writes semantic_targets_360 rows that can be consumed by the existing
viewer click projection flow.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import time

try:
    from . import job_guard, schema, sqlite_io
except ImportError:
    import job_guard
    import schema
    import sqlite_io


TARGET_SOURCE = "yolo_cubemap"
FACE_CONVENTION = "normalized_f_r_b_l_u_d_v1"

PROJECTION_GROUND_PLANE = "ground_plane"
PROJECTION_DIRECTION_ONLY = "direction_only"
PROJECTION_ELEVATED_OBJECT = "elevated_object"

ANCHOR_CENTER = "center"
ANCHOR_BOTTOM_CENTER = "bottom_center"
ANCHOR_TOP_CENTER = "top_center"


@dataclass(frozen=True)
class TargetPolicy:
    """Class-specific rule for turning a bbox into a target point."""

    bbox_anchor: str
    projection: str
    reason: str


@dataclass(frozen=True)
class SemanticTargetConfig:
    """CLI arguments normalized for semantic target generation."""

    work_db: Path
    run_id: str | None
    camera_height_m: float
    hud_height_scale: float
    limit: int | None
    clear_existing: bool
    model_run_ids: tuple[str, ...] = ()
    model_names: tuple[str, ...] = ()
    max_bbox_area_ratio: float | None = None


@dataclass(frozen=True)
class CubemapTarget:
    """Pure geometric result for one bbox anchor on a CubeMap face."""

    bbox_anchor: str
    anchor_x_px: float
    anchor_y_px: float
    cubemap_u: float
    cubemap_v: float
    ray_x: float
    ray_y: float
    ray_z: float
    target_yaw_to_camera_heading: float
    target_pitch_deg: float


DEFAULT_POLICY = TargetPolicy(
    bbox_anchor=ANCHOR_CENTER,
    projection=PROJECTION_DIRECTION_ONLY,
    reason="unknown_class",
)

CLASS_POLICIES = {
    "road_surface_damage": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "road_damage": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "pothole": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "crack": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "manhole": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "road_marking": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "pavement_marking": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "lane_marking": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "crosswalk": TargetPolicy(ANCHOR_CENTER, PROJECTION_GROUND_PLANE, "surface_object"),
    "traffic_cone": TargetPolicy(ANCHOR_BOTTOM_CENTER, PROJECTION_GROUND_PLANE, "ground_contact_object"),
    "cone": TargetPolicy(ANCHOR_BOTTOM_CENTER, PROJECTION_GROUND_PLANE, "ground_contact_object"),
    "pole": TargetPolicy(ANCHOR_BOTTOM_CENTER, PROJECTION_GROUND_PLANE, "ground_contact_object"),
    "utility_pole": TargetPolicy(ANCHOR_BOTTOM_CENTER, PROJECTION_GROUND_PLANE, "ground_contact_object"),
    "sign_post": TargetPolicy(ANCHOR_BOTTOM_CENTER, PROJECTION_GROUND_PLANE, "ground_contact_object"),
    "traffic_sign": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "elevated_object"),
    "sign": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "elevated_object"),
    "signal": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "elevated_object"),
    "traffic_light": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "elevated_object"),
    "green_light": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "traffic_light"),
    "red_light": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "traffic_light"),
    "stop": TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "traffic_sign"),
}


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a numeric value."""

    return max(float(low), min(float(high), float(value)))


def normalize_yaw(value: float) -> float:
    """Normalize yaw to 0..360 degrees."""

    return float(value) % 360.0


def normalize_pitch(value: float) -> float:
    """Clamp pitch to the viewer-compatible -90..90 degree range."""

    return clamp(value, -90.0, 90.0)


def normalize_class_name(value: str | None) -> str:
    """Normalize model class names for policy lookup."""

    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


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


def policy_for_class(class_name: str | None) -> TargetPolicy:
    """Return the anchor/projection policy for a semantic class."""

    normalized = normalize_class_name(class_name)
    if normalized in CLASS_POLICIES:
        return CLASS_POLICIES[normalized]
    if normalized.startswith("speed_limit_"):
        return TargetPolicy(ANCHOR_CENTER, PROJECTION_ELEVATED_OBJECT, "speed_limit_sign")
    return DEFAULT_POLICY


def bbox_values(row: dict) -> tuple[float, float, float, float]:
    """Extract xyxy bbox values from a detection row."""

    return (
        float(row["bbox_x1"]),
        float(row["bbox_y1"]),
        float(row["bbox_x2"]),
        float(row["bbox_y2"]),
    )


def bbox_anchor_point(
    bbox: tuple[float, float, float, float],
    anchor: str,
) -> tuple[float, float]:
    """Return the selected anchor point for an xyxy bbox."""

    x1, y1, x2, y2 = bbox
    anchor = str(anchor or ANCHOR_CENTER).strip().lower()
    if anchor == ANCHOR_CENTER:
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0
    if anchor == ANCHOR_BOTTOM_CENTER:
        return (x1 + x2) / 2.0, y2
    if anchor == ANCHOR_TOP_CENTER:
        return (x1 + x2) / 2.0, y1
    raise ValueError(f"Unsupported bbox anchor: {anchor}")


def pixel_to_cubemap_uv(
    x_px: float,
    y_px: float,
    width_px: int,
    height_px: int,
) -> tuple[float, float]:
    """Convert image pixel coordinates to CubeMap u/v in -1..1."""

    width_px = int(width_px)
    height_px = int(height_px)
    if width_px <= 1 or height_px <= 1:
        raise ValueError("Image plane width_px/height_px must be greater than 1.")

    x_px = clamp(x_px, 0.0, float(width_px - 1))
    y_px = clamp(y_px, 0.0, float(height_px - 1))
    u = (x_px / float(width_px - 1)) * 2.0 - 1.0
    v = (y_px / float(height_px - 1)) * 2.0 - 1.0
    return u, v


def face_uv_to_ray(face_name: str, u: float, v: float) -> tuple[float, float, float]:
    """Convert normalized face coordinates to a normalized camera ray."""

    face = str(face_name or "").strip().lower()
    if face == "front":
        x, y, z = u, -v, 1.0
    elif face == "right":
        x, y, z = 1.0, -v, -u
    elif face == "back":
        x, y, z = -u, -v, -1.0
    elif face == "left":
        x, y, z = -1.0, -v, u
    elif face == "up":
        x, y, z = u, 1.0, v
    elif face == "down":
        x, y, z = u, -1.0, -v
    else:
        raise ValueError(f"Unsupported CubeMap face: {face_name}")

    length = math.sqrt(x * x + y * y + z * z)
    if length <= 0:
        raise ValueError("CubeMap ray length is zero.")
    return x / length, y / length, z / length


def ray_to_target_yaw_pitch(ray: tuple[float, float, float]) -> tuple[float, float]:
    """Convert a camera ray to viewer-compatible target yaw and pitch.

    The CubeMap ray uses +Y upward.  The existing viewer projection treats
    positive target_pitch_deg as downward, so the vertical sign is inverted.
    """

    x, y, z = ray
    yaw = normalize_yaw(math.degrees(math.atan2(x, z)))
    horizontal = math.sqrt(x * x + z * z)
    pitch_up_deg = math.degrees(math.atan2(y, horizontal))
    target_pitch_deg = normalize_pitch(-pitch_up_deg)
    return yaw, target_pitch_deg


def bbox_to_cubemap_target(
    bbox: tuple[float, float, float, float],
    face_name: str,
    width_px: int,
    height_px: int,
    bbox_anchor: str,
) -> CubemapTarget:
    """Convert one bbox into the click-compatible geometric target values."""

    anchor_x, anchor_y = bbox_anchor_point(bbox, bbox_anchor)
    u, v = pixel_to_cubemap_uv(anchor_x, anchor_y, width_px, height_px)
    ray = face_uv_to_ray(face_name, u, v)
    target_yaw, target_pitch = ray_to_target_yaw_pitch(ray)
    return CubemapTarget(
        bbox_anchor=bbox_anchor,
        anchor_x_px=anchor_x,
        anchor_y_px=anchor_y,
        cubemap_u=u,
        cubemap_v=v,
        ray_x=ray[0],
        ray_y=ray[1],
        ray_z=ray[2],
        target_yaw_to_camera_heading=target_yaw,
        target_pitch_deg=target_pitch,
    )


def effective_camera_height_m(camera_height_m: float, hud_height_scale: float) -> float:
    """Return the CamH/HudH effective height used by ground-plane projection."""

    return clamp(camera_height_m, 0.1, 20.0) * clamp(hud_height_scale, 0.1, 5.0)


def ground_distance_from_pitch(
    target_pitch_deg: float | None,
    camera_height_m: float,
    hud_height_scale: float,
) -> float | None:
    """Estimate horizontal ground distance from viewer pitch and effective height."""

    if target_pitch_deg is None:
        return None
    pitch = float(target_pitch_deg)
    if pitch <= 0.1 or pitch >= 89.9:
        return None
    tangent = math.tan(math.radians(pitch))
    if abs(tangent) < 1e-9:
        return None
    return effective_camera_height_m(camera_height_m, hud_height_scale) / tangent


def quality_from_distance(distance_m: float | None) -> str:
    """Return semantic target quality bucket from ground distance."""

    if distance_m is None or distance_m <= 0:
        return "unknown"
    if distance_m <= 5.0:
        return "trusted"
    if distance_m <= 10.0:
        return "usable"
    return "far"


def actual_projection(policy: TargetPolicy, ground_distance_m: float | None) -> str:
    """Return the actual projection type to store for a target."""

    if policy.projection == PROJECTION_GROUND_PLANE:
        return PROJECTION_GROUND_PLANE if ground_distance_m is not None else PROJECTION_DIRECTION_ONLY
    return policy.projection


def bbox_area_ratio(
    detection: dict,
    width_key: str = "evidence_width_px",
    height_key: str = "evidence_height_px",
) -> float | None:
    """Return bbox/image area ratio when dimensions are available."""

    bbox_area = detection.get("bbox_area")
    width_px = detection.get(width_key)
    height_px = detection.get(height_key)
    if bbox_area is None or width_px is None or height_px is None:
        return None
    width = float(width_px)
    height = float(height_px)
    image_area = width * height
    if image_area <= 0:
        return None
    return float(bbox_area) / image_area


def resolve_run(conn, requested_run_id: str | None = None) -> dict:
    """Resolve the run used for semantic target generation."""

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


def select_yolo_detections(
    conn,
    run_id: str,
    limit: int | None = None,
    model_run_ids: tuple[str, ...] = (),
    model_names: tuple[str, ...] = (),
) -> list[dict]:
    """Return YOLO detections joined with their CubeMap image plane metadata."""

    where = ["d.run_id = ?"]
    params: list[object] = [run_id]
    if model_run_ids:
        where.append(f"d.model_run_id IN ({', '.join('?' for _ in model_run_ids)})")
        params.extend(model_run_ids)
    if model_names:
        where.append(f"m.model_name IN ({', '.join('?' for _ in model_names)})")
        params.extend(model_names)

    sql = f"""
        SELECT
            d.*,
            m.model_name AS model_name,
            m.model_path AS model_path,
            p.face_name AS evidence_face,
            p.image_path AS evidence_image_path,
            p.width_px AS evidence_width_px,
            p.height_px AS evidence_height_px,
            p.face_convention AS evidence_face_convention,
            p.transform_json AS evidence_transform_json
        FROM {schema.quote_identifier(schema.YOLO_DETECTIONS_TABLE)} AS d
        JOIN {schema.quote_identifier(schema.IMAGE_PLANES_TABLE)} AS p
            ON p.plane_id = d.plane_id
        JOIN {schema.quote_identifier(schema.MODEL_RUNS_TABLE)} AS m
            ON m.model_run_id = d.model_run_id
        WHERE {" AND ".join(where)}
        ORDER BY d.frame_index, p.face_name, d.detection_id
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, int(limit)))
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def filter_large_bbox_detections(
    detections: list[dict],
    max_bbox_area_ratio: float | None,
) -> tuple[list[dict], list[dict]]:
    """Split detections into accepted rows and large-bbox skips."""

    if max_bbox_area_ratio is None:
        return detections, []
    threshold = float(max_bbox_area_ratio)
    accepted = []
    skipped = []
    for detection in detections:
        ratio = bbox_area_ratio(detection)
        if ratio is not None and ratio > threshold:
            skipped.append(
                {
                    "detection_id": detection.get("detection_id"),
                    "reason": "bbox_area_ratio_exceeds_threshold",
                    "bbox_area_ratio": ratio,
                    "max_bbox_area_ratio": threshold,
                }
            )
            continue
        accepted.append(detection)
    return accepted, skipped


def clear_semantic_targets(
    conn,
    run_id: str,
    target_source: str = TARGET_SOURCE,
    detection_ids: tuple[str, ...] | None = None,
) -> int:
    """Delete generated semantic targets for a run/source and return count."""

    before = conn.total_changes
    if detection_ids is None:
        conn.execute(
            f"""
            DELETE FROM {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)}
            WHERE run_id = ? AND target_source = ?
            """,
            (run_id, target_source),
        )
    elif detection_ids:
        ids = tuple(str(value) for value in detection_ids)
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            conn.execute(
                f"""
                DELETE FROM {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)}
                WHERE run_id = ? AND target_source = ?
                    AND detection_id IN ({placeholders})
                """,
                (run_id, target_source, *chunk),
            )
    return conn.total_changes - before


def semantic_target_payload(
    detection: dict,
    policy: TargetPolicy,
    target: CubemapTarget,
    bbox: tuple[float, float, float, float],
    projection: str,
    ground_distance_m: float | None,
    camera_height_m: float,
    hud_height_scale: float,
) -> dict:
    """Build the verbose self-describing payload for a semantic target."""

    return {
        "source": TARGET_SOURCE,
        "detection_id": detection.get("detection_id"),
        "model_run_id": detection.get("model_run_id"),
        "model_name": detection.get("model_name") or "",
        "class_id": detection.get("class_id"),
        "class_name": detection.get("class_name") or "",
        "confidence": detection.get("confidence"),
        "face": detection.get("evidence_face"),
        "face_convention": detection.get("evidence_face_convention") or FACE_CONVENTION,
        "bbox": [float(value) for value in bbox],
        "bbox_anchor": target.bbox_anchor,
        "anchor_xy_px": [target.anchor_x_px, target.anchor_y_px],
        "cubemap_uv": {"u": target.cubemap_u, "v": target.cubemap_v},
        "camera_ray": {"x": target.ray_x, "y": target.ray_y, "z": target.ray_z},
        "target_yaw_to_camera_heading": target.target_yaw_to_camera_heading,
        "target_pitch_deg": target.target_pitch_deg,
        "ground_distance_m": ground_distance_m,
        "projection": projection,
        "policy": {
            "bbox_anchor": policy.bbox_anchor,
            "requested_projection": policy.projection,
            "reason": policy.reason,
        },
        "camera_height_m": camera_height_m,
        "hud_height_scale": hud_height_scale,
        "effective_camera_height_m": effective_camera_height_m(camera_height_m, hud_height_scale),
    }


def semantic_target_from_detection(
    detection: dict,
    camera_height_m: float,
    hud_height_scale: float,
) -> dict:
    """Build one insertable semantic_targets_360 row from a joined detection row."""

    class_name = detection.get("class_name") or ""
    policy = policy_for_class(class_name)
    bbox = bbox_values(detection)
    target = bbox_to_cubemap_target(
        bbox=bbox,
        face_name=str(detection.get("evidence_face") or ""),
        width_px=int(detection.get("evidence_width_px") or 0),
        height_px=int(detection.get("evidence_height_px") or 0),
        bbox_anchor=policy.bbox_anchor,
    )
    ground_distance_m = None
    if policy.projection == PROJECTION_GROUND_PLANE:
        ground_distance_m = ground_distance_from_pitch(
            target.target_pitch_deg,
            camera_height_m,
            hud_height_scale,
        )
    projection = actual_projection(policy, ground_distance_m)
    quality = quality_from_distance(ground_distance_m)
    payload = semantic_target_payload(
        detection=detection,
        policy=policy,
        target=target,
        bbox=bbox,
        projection=projection,
        ground_distance_m=ground_distance_m,
        camera_height_m=camera_height_m,
        hud_height_scale=hud_height_scale,
    )
    return {
        "run_id": str(detection["run_id"]),
        "detection_id": detection.get("detection_id"),
        "frame_index": int(detection["frame_index"]),
        "target_source": TARGET_SOURCE,
        "semantic_class": class_name,
        "confidence": detection.get("confidence"),
        "target_yaw_to_camera_heading": target.target_yaw_to_camera_heading,
        "target_pitch_deg": target.target_pitch_deg,
        "ground_distance_m": ground_distance_m,
        "projection": projection,
        "quality": quality,
        "evidence_plane_id": detection.get("plane_id"),
        "evidence_image_path": detection.get("evidence_image_path"),
        "evidence_face": detection.get("evidence_face"),
        "evidence_bbox": list(bbox),
        "bbox_anchor": target.bbox_anchor,
        "payload": payload,
    }


def insert_semantic_target_row(conn, row: dict) -> str:
    """Insert one semantic target dict via sqlite_io."""

    return sqlite_io.insert_semantic_target(
        conn,
        run_id=row["run_id"],
        detection_id=row.get("detection_id"),
        frame_index=row["frame_index"],
        target_source=row["target_source"],
        semantic_class=row.get("semantic_class") or "",
        confidence=row.get("confidence"),
        target_yaw_to_camera_heading=row.get("target_yaw_to_camera_heading"),
        target_pitch_deg=row.get("target_pitch_deg"),
        ground_distance_m=row.get("ground_distance_m"),
        projection=row.get("projection") or PROJECTION_DIRECTION_ONLY,
        quality=row.get("quality") or "unknown",
        evidence_plane_id=row.get("evidence_plane_id"),
        evidence_image_path=row.get("evidence_image_path"),
        evidence_face=row.get("evidence_face"),
        evidence_bbox=row.get("evidence_bbox"),
        bbox_anchor=row.get("bbox_anchor") or ANCHOR_CENTER,
        payload=row.get("payload"),
    )


def generate_semantic_targets(config: SemanticTargetConfig) -> dict:
    """Generate semantic_targets_360 rows from YOLO detections."""

    if not config.work_db.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {config.work_db}")

    conn = sqlite_io.initialize(config.work_db)
    try:
        run_row = resolve_run(conn, config.run_id)
        job_guard.ensure_run_matches_job(config.work_db, run_row)
        run_id = str(run_row["run_id"])
        input_detections = select_yolo_detections(
            conn,
            run_id,
            config.limit,
            model_run_ids=config.model_run_ids,
            model_names=config.model_names,
        )
        deleted_count = 0
        if config.clear_existing:
            selected_detection_ids = tuple(str(row.get("detection_id")) for row in input_detections)
            delete_ids = selected_detection_ids if (config.model_run_ids or config.model_names) else None
            deleted_count = clear_semantic_targets(conn, run_id, detection_ids=delete_ids)

        detections, large_bbox_skipped = filter_large_bbox_detections(
            input_detections,
            config.max_bbox_area_ratio,
        )
        target_ids = []
        skipped = list(large_bbox_skipped)
        for detection in detections:
            try:
                row = semantic_target_from_detection(
                    detection,
                    camera_height_m=config.camera_height_m,
                    hud_height_scale=config.hud_height_scale,
                )
            except (TypeError, ValueError, KeyError) as e:
                skipped.append(
                    {
                        "detection_id": detection.get("detection_id"),
                        "reason": str(e),
                    }
                )
                continue
            target_ids.append(insert_semantic_target_row(conn, row))

        sqlite_io.set_metadata(
            conn,
            "run",
            "semantic_target_summary",
            {
                "run_id": run_id,
                "source": TARGET_SOURCE,
                "detection_count": len(input_detections),
                "processed_detection_count": len(detections),
                "target_count": len(target_ids),
                "skipped_count": len(skipped),
                "large_bbox_skipped_count": len(large_bbox_skipped),
                "deleted_count": deleted_count,
                "camera_height_m": config.camera_height_m,
                "hud_height_scale": config.hud_height_scale,
                "model_run_ids": list(config.model_run_ids),
                "model_names": list(config.model_names),
                "max_bbox_area_ratio": config.max_bbox_area_ratio,
                "skipped": skipped[:20],
            },
            scope_id=run_id,
        )
        sqlite_io.update_run_status(conn, run_id, "semantic_targets_generated")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "run_id": run_id,
        "detection_count": len(input_detections),
        "processed_detection_count": len(detections),
        "target_count": len(target_ids),
        "skipped_count": len(skipped),
        "large_bbox_skipped_count": len(large_bbox_skipped),
        "deleted_count": deleted_count,
    }


def build_arg_parser():
    """Build semantic-target CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Convert YOLO CubeMap detections into semantic_targets_360."
    )
    parser.add_argument("--work-db", required=True, help="semantic_work.sqlite path.")
    parser.add_argument("--run-id", help="Run id. Default: latest run in work DB.")
    parser.add_argument("--camera-height-m", type=float, default=2.0, help="Measured camera height.")
    parser.add_argument("--hud-height-scale", type=float, default=1.0, help="HudH scale used by projection.")
    parser.add_argument("--limit", type=int, help="Limit detections for testing.")
    parser.add_argument("--clear-existing", action="store_true", help="Delete generated targets for the run first.")
    parser.add_argument("--model-run-ids", nargs="+", default=[], help="Optional model_run_id values to target.")
    parser.add_argument("--model-names", nargs="+", default=[], help="Optional model names to target.")
    parser.add_argument(
        "--max-bbox-area-ratio",
        type=float,
        help="Skip detections whose bbox covers more than this ratio of the CubeMap face, e.g. 0.30.",
    )
    return parser


def config_from_args(args) -> SemanticTargetConfig:
    """Normalize argparse Namespace into SemanticTargetConfig."""

    return SemanticTargetConfig(
        work_db=Path(args.work_db).expanduser().resolve(),
        run_id=args.run_id,
        camera_height_m=float(args.camera_height_m),
        hud_height_scale=float(args.hud_height_scale),
        limit=args.limit,
        clear_existing=bool(args.clear_existing),
        model_run_ids=normalize_text_values(args.model_run_ids),
        model_names=normalize_text_values(args.model_names),
        max_bbox_area_ratio=args.max_bbox_area_ratio,
    )


def main(argv=None):
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    start = time.perf_counter()
    result = generate_semantic_targets(config)
    elapsed = time.perf_counter() - start
    print(f"Work DB: {config.work_db}")
    print(f"Run ID: {result['run_id']}")
    print(f"Detections: {result['detection_count']}")
    if config.max_bbox_area_ratio is not None:
        print(f"Processed detections: {result['processed_detection_count']}")
        print(f"Large bbox skipped: {result['large_bbox_skipped_count']}")
    print(f"Targets: {result['target_count']}")
    print(f"Skipped: {result['skipped_count']}")
    if result["deleted_count"]:
        print(f"Deleted existing targets: {result['deleted_count']}")
    print(f"Done in {elapsed:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
