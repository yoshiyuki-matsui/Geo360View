"""Cluster georeferenced POI candidates into likely real-world POIs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import sqlite3
import time

try:
    from . import projection as geo_projection
    from . import schema, sqlite_io
except ImportError:
    import projection as geo_projection
    import schema
    import sqlite_io


DEFAULT_CLUSTER_RADIUS_M = 3.0
DEFAULT_DIRECTION_CLUSTER_RADIUS_M = 10.0


@dataclass(frozen=True)
class PoiClusterConfig:
    """CLI arguments normalized for POI clustering."""

    work_db: Path
    run_id: str | None = None
    cluster_radius_m: float = DEFAULT_CLUSTER_RADIUS_M
    direction_cluster_radius_m: float = DEFAULT_DIRECTION_CLUSTER_RADIUS_M
    min_observations: int = 1
    limit: int | None = None
    clear_existing: bool = False
    group_by_model_run: bool = False
    ignore_model: bool = False
    model_run_ids: tuple[str, ...] = ()
    model_names: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    qualities: tuple[str, ...] = ()
    position_methods: tuple[str, ...] = ()


@dataclass
class WorkingCluster:
    """In-memory cluster accumulator."""

    key: tuple[str, str]
    members: list[dict] = field(default_factory=list)
    center_lat: float = 0.0
    center_lon: float = 0.0
    weight_sum: float = 0.0

    def add(self, candidate: dict):
        """Append a candidate and update weighted center."""

        lat = float(candidate["object_lat"])
        lon = float(candidate["object_lon"])
        weight = max(0.05, float(candidate.get("_weight") or 0.05))
        if not self.members:
            self.center_lat = lat
            self.center_lon = lon
            self.weight_sum = weight
        else:
            total = self.weight_sum + weight
            self.center_lat = (self.center_lat * self.weight_sum + lat * weight) / total
            self.center_lon = (self.center_lon * self.weight_sum + lon * weight) / total
            self.weight_sum = total
        self.members.append(candidate)
        refresh_cluster_center(self)


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


def slug_token(value: str, fallback: str = "poi") -> str:
    """Return a compact ASCII token for deterministic cluster IDs."""

    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:40] or fallback


def resolve_run(conn: sqlite3.Connection, requested_run_id: str | None = None) -> dict:
    """Resolve run row used for clustering."""

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


def select_poi_candidates(
    conn: sqlite3.Connection,
    run_id: str,
    config: PoiClusterConfig,
) -> list[dict]:
    """Read georeferenced candidate rows to be clustered."""

    where = [
        f"p.{schema.quote_identifier('run_id')} = ?",
        f"p.{schema.quote_identifier('object_lat')} IS NOT NULL",
        f"p.{schema.quote_identifier('object_lon')} IS NOT NULL",
    ]
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
            t.evidence_bbox_json AS target_evidence_bbox_json,
            t.payload_json AS target_payload_json
        FROM {schema.quote_identifier(schema.POI_CANDIDATES_TABLE)} AS p
        LEFT JOIN {schema.quote_identifier(schema.SEMANTIC_TARGETS_TABLE)} AS t
            ON t.target_id = p.target_id
        WHERE {" AND ".join(where)}
        ORDER BY p.semantic_class, p.model_name, p.model_run_id, p.frame_index, p.candidate_id
    """
    if config.limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, int(config.limit)))
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def candidate_group_key(candidate: dict, config: PoiClusterConfig) -> tuple[str, str]:
    """Return the semantic/model key that must match before spatial clustering."""

    semantic_class = str(candidate.get("semantic_class") or "")
    if config.ignore_model:
        model_key = ""
    elif config.group_by_model_run:
        model_key = str(candidate.get("model_run_id") or candidate.get("model_name") or "")
    else:
        model_key = str(candidate.get("model_name") or candidate.get("model_run_id") or "")
    return model_key, semantic_class


def candidate_score(candidate: dict) -> float:
    """Score one observation as representative evidence."""

    confidence = parse_float(candidate.get("confidence"), 0.0) or 0.0
    score = float(confidence)

    quality = str(candidate.get("quality") or "").lower()
    quality_bonus = {
        "trusted": 0.15,
        "usable": 0.10,
        "direction_only": 0.00,
        "unknown": 0.00,
        "far": -0.10,
    }
    score += quality_bonus.get(quality, 0.0)

    position_method = str(candidate.get("position_method") or "")
    if position_method == "ground_plane_bearing":
        score += 0.10

    face = str(candidate.get("evidence_face") or "").lower()
    face_bonus = {
        "down": 0.10,
        "front": 0.10,
        "back": 0.05,
        "left": 0.03,
        "right": 0.03,
        "up": 0.02,
    }
    score += face_bonus.get(face, 0.0)

    distance_m = parse_float(candidate.get("distance_m"))
    if distance_m is not None and distance_m > 0:
        score += max(0.0, min(0.05, (12.0 - distance_m) / 120.0))

    return round(score, 6)


def candidate_uses_direction_ray(candidate: dict) -> bool:
    """Return whether candidate geometry is a direction-only/fixed-distance estimate."""

    projection = str(candidate.get("projection") or "").lower()
    position_method = str(candidate.get("position_method") or "").lower()
    distance_method = str(candidate.get("distance_method") or "").lower()
    return (
        projection in ("elevated_object", "direction_only")
        or position_method == "fixed_distance_bearing"
        or distance_method == "fixed_distance_for_direction_only"
    )


def cluster_uses_direction_ray(cluster: WorkingCluster) -> bool:
    """Return whether a cluster should use ray geometry rather than object point distance."""

    return any(candidate_uses_direction_ray(member) for member in cluster.members)


def ray_unit_vector(bearing_deg: float) -> tuple[float, float]:
    """Return east/north unit vector for bearing where north is 0 degrees."""

    radians = math.radians(float(bearing_deg))
    return math.sin(radians), math.cos(radians)


def candidate_ray(candidate: dict) -> tuple[float, float, float, float] | None:
    """Return camera lat/lon and east/north ray direction for a candidate."""

    camera_lat = parse_float(candidate.get("camera_lat"))
    camera_lon = parse_float(candidate.get("camera_lon"))
    bearing_deg = parse_float(candidate.get("bearing_deg"))
    if camera_lat is None or camera_lon is None or bearing_deg is None:
        return None
    dx, dy = ray_unit_vector(bearing_deg)
    return camera_lat, camera_lon, dx, dy


def geo_from_local_meters(ref_lat: float, ref_lon: float, dx_m: float, dy_m: float) -> geo_projection.GeoPoint:
    """Return WGS84 point from short-distance east/north meters."""

    lat = float(ref_lat) + math.degrees(float(dy_m) / geo_projection.EARTH_RADIUS_M)
    lon_scale = geo_projection.EARTH_RADIUS_M * math.cos(math.radians(float(ref_lat)))
    if abs(lon_scale) < 1e-9:
        lon = float(ref_lon)
    else:
        lon = float(ref_lon) + math.degrees(float(dx_m) / lon_scale)
    return geo_projection.GeoPoint(lat=lat, lon=lon)


def weighted_object_center(members: list[dict]) -> geo_projection.GeoPoint | None:
    """Return weighted center of candidate object_lat/lon values."""

    lat_sum = 0.0
    lon_sum = 0.0
    weight_sum = 0.0
    for member in members:
        lat = parse_float(member.get("object_lat"))
        lon = parse_float(member.get("object_lon"))
        if lat is None or lon is None:
            continue
        weight = max(0.05, float(member.get("_weight") or 0.05))
        lat_sum += lat * weight
        lon_sum += lon * weight
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return geo_projection.GeoPoint(lat=lat_sum / weight_sum, lon=lon_sum / weight_sum)


def ray_estimated_center(members: list[dict]) -> geo_projection.GeoPoint | None:
    """Estimate object point from multiple camera bearing rays."""

    rays = [(member, candidate_ray(member)) for member in members if candidate_uses_direction_ray(member)]
    rays = [(member, ray) for member, ray in rays if ray is not None]
    if len(rays) < 2:
        return None

    ref_lat, ref_lon = rays[0][1][0], rays[0][1][1]
    axx = axy = ayy = bx = by = 0.0
    for member, ray in rays:
        camera_lat, camera_lon, ux, uy = ray
        px, py = geo_projection.local_vector_meters(ref_lat, ref_lon, camera_lat, camera_lon)
        weight = max(0.05, float(member.get("_weight") or 0.05))

        mxx = 1.0 - ux * ux
        mxy = -ux * uy
        myy = 1.0 - uy * uy
        axx += weight * mxx
        axy += weight * mxy
        ayy += weight * myy
        bx += weight * (mxx * px + mxy * py)
        by += weight * (mxy * px + myy * py)

    det = axx * ayy - axy * axy
    if abs(det) < 1e-9:
        return None

    x = (bx * ayy - by * axy) / det
    y = (axx * by - axy * bx) / det

    forward_count = 0
    residuals = []
    for _member, ray in rays:
        camera_lat, camera_lon, ux, uy = ray
        px, py = geo_projection.local_vector_meters(ref_lat, ref_lon, camera_lat, camera_lon)
        vx = x - px
        vy = y - py
        forward_m = vx * ux + vy * uy
        if forward_m >= -2.0:
            forward_count += 1
        residuals.append(abs(vx * uy - vy * ux))

    if forward_count < max(1, len(rays) // 2):
        return None
    if residuals and sum(residuals) / len(residuals) > 30.0:
        return None

    return geo_from_local_meters(ref_lat, ref_lon, x, y)


def refresh_cluster_center(cluster: WorkingCluster):
    """Update cluster center from either ground points or direction rays."""

    center = ray_estimated_center(cluster.members) if cluster_uses_direction_ray(cluster) else None
    if center is None:
        center = weighted_object_center(cluster.members)
    if center is None:
        return
    cluster.center_lat = center.lat
    cluster.center_lon = center.lon


def json_loads(value, default=None):
    """Parse JSON text with a quiet default."""

    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def bbox_area(candidate: dict) -> float | None:
    """Return evidence bbox area when available."""

    target_payload = json_loads(candidate.get("target_payload_json"), {}) or {}
    bbox = target_payload.get("bbox") if isinstance(target_payload, dict) else None
    if bbox is None:
        bbox = json_loads(candidate.get("target_evidence_bbox_json"), None)
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def temporal_preference(candidate: dict, min_frame: int, max_frame: int) -> float:
    """Return face-aware timing preference in 0..1 within one cluster."""

    if max_frame <= min_frame:
        return 0.5
    frame_index = int(candidate.get("frame_index") or min_frame)
    position = (frame_index - min_frame) / float(max_frame - min_frame)
    position = max(0.0, min(1.0, position))

    face = str(candidate.get("evidence_face") or "").lower()
    if face in ("front", "left", "right"):
        return position
    if face == "back":
        return 1.0 - position
    if face in ("up", "down"):
        return 1.0 - min(1.0, abs(position - 0.5) * 2.0)
    return 0.5


def frame_position_ratio(candidate: dict, min_frame: int, max_frame: int) -> float:
    """Return normalized frame position in one cluster."""

    if max_frame <= min_frame:
        return 0.5
    frame_index = int(candidate.get("frame_index") or min_frame)
    return max(0.0, min(1.0, (frame_index - min_frame) / float(max_frame - min_frame)))


def face_time_policy(face: str) -> str:
    """Return expected best timing policy for a CubeMap face."""

    face = str(face or "").lower()
    if face in ("front", "left", "right"):
        return "late_larger"
    if face == "back":
        return "early_larger"
    if face in ("up", "down"):
        return "center_time"
    return "neutral"


def representative_eval(candidate: dict, cluster: WorkingCluster) -> dict:
    """Return face/time/bbox evaluation used to choose representative evidence."""

    if not cluster.members:
        return {
            "base_score": float(candidate.get("_score") or 0.0),
            "representative_score": float(candidate.get("_score") or 0.0),
        }
    frames = [int(member["frame_index"]) for member in cluster.members]
    min_frame = min(frames)
    max_frame = max(frames)
    face = str(candidate.get("evidence_face") or "").lower()
    policy = face_time_policy(face)
    time_position = frame_position_ratio(candidate, min_frame, max_frame)
    time_score = temporal_preference(candidate, min_frame, max_frame)

    area_values = [bbox_area(member) for member in cluster.members]
    area_values = [area for area in area_values if area is not None and area > 0]
    max_area = max(area_values) if area_values else None
    area = bbox_area(candidate)
    area_score = 0.0
    if area is not None and max_area:
        area_score = max(0.0, min(1.0, area / max_area))

    if policy in ("late_larger", "early_larger"):
        movement_bonus = 0.18 * time_score + 0.10 * area_score + 0.08 * time_score * area_score
    elif policy == "center_time":
        movement_bonus = 0.24 * time_score + 0.02 * area_score
    else:
        movement_bonus = 0.05 * time_score + 0.05 * area_score

    base_score = float(candidate.get("_score") or 0.0)
    score = base_score + movement_bonus
    return {
        "base_score": base_score,
        "face": face,
        "time_policy": policy,
        "min_frame_index": min_frame,
        "max_frame_index": max_frame,
        "frame_position_ratio": time_position,
        "temporal_preference": time_score,
        "bbox_area": area,
        "bbox_area_score": area_score,
        "movement_bonus": movement_bonus,
        "representative_score": score,
    }


def representative_score(candidate: dict, cluster: WorkingCluster) -> float:
    """Score one observation as representative evidence with face/time policy."""

    return float(representative_eval(candidate, cluster).get("representative_score") or 0.0)


def distance_to_cluster(candidate: dict, cluster: WorkingCluster) -> float:
    """Distance between candidate object point and cluster center."""

    if candidate_uses_direction_ray(candidate) or cluster_uses_direction_ray(cluster):
        ray = candidate_ray(candidate)
        if ray is not None:
            camera_lat, camera_lon, ux, uy = ray
            vx, vy = geo_projection.local_vector_meters(
                camera_lat,
                camera_lon,
                float(cluster.center_lat),
                float(cluster.center_lon),
            )
            forward_m = vx * ux + vy * uy
            perpendicular_m = abs(vx * uy - vy * ux)
            behind_penalty_m = abs(forward_m) if forward_m < -2.0 else 0.0
            return math.hypot(perpendicular_m, behind_penalty_m)

    return geo_projection.distance_between_points_m(
        float(candidate["object_lat"]),
        float(candidate["object_lon"]),
        float(cluster.center_lat),
        float(cluster.center_lon),
    )


def cluster_radius_for_candidate(candidate: dict, config: PoiClusterConfig) -> float:
    """Return clustering radius for a candidate geometry mode."""

    if candidate_uses_direction_ray(candidate):
        return max(0.0, float(config.direction_cluster_radius_m))
    return max(0.0, float(config.cluster_radius_m))


def build_clusters(
    candidates: list[dict],
    config: PoiClusterConfig,
) -> list[WorkingCluster]:
    """Cluster candidates by model/class key and spatial radius."""

    clusters_by_key: dict[tuple[str, str], list[WorkingCluster]] = {}
    for candidate in candidates:
        candidate["_score"] = candidate_score(candidate)
        candidate["_weight"] = max(0.05, candidate["_score"])
        key = candidate_group_key(candidate, config)
        clusters = clusters_by_key.setdefault(key, [])
        radius_m = cluster_radius_for_candidate(candidate, config)

        best_cluster = None
        best_distance = None
        for cluster in clusters:
            distance_m = distance_to_cluster(candidate, cluster)
            if distance_m <= radius_m and (best_distance is None or distance_m < best_distance):
                best_cluster = cluster
                best_distance = distance_m

        if best_cluster is None:
            best_cluster = WorkingCluster(key=key)
            clusters.append(best_cluster)
        best_cluster.add(candidate)

    result = []
    for key in sorted(clusters_by_key):
        result.extend(clusters_by_key[key])
    return result


def representative_member(cluster: WorkingCluster) -> dict:
    """Return the strongest member used as viewer evidence."""

    def sort_key(candidate: dict):
        distance_m = parse_float(candidate.get("distance_m"))
        return (
            -representative_score(candidate, cluster),
            -(parse_float(candidate.get("confidence"), 0.0) or 0.0),
            distance_m if distance_m is not None else 999999.0,
            int(candidate.get("frame_index") or 0),
            str(candidate.get("candidate_id") or ""),
        )

    return sorted(cluster.members, key=sort_key)[0]


def confidence_stats(members: list[dict]) -> tuple[float | None, float | None, float | None]:
    """Return min/max/mean confidence, ignoring NULLs."""

    values = [parse_float(member.get("confidence")) for member in members]
    values = [value for value in values if value is not None]
    if not values:
        return None, None, None
    return min(values), max(values), sum(values) / len(values)


def member_ids(members: list[dict]) -> list[str]:
    """Return member candidate IDs."""

    return [str(member.get("candidate_id") or "") for member in members if member.get("candidate_id")]


def make_cluster_id(run_id: str, cluster: WorkingCluster, index: int) -> str:
    """Return deterministic cluster id for a run/key/order."""

    model_key, semantic_class = cluster.key
    token = slug_token("_".join(part for part in (model_key, semantic_class) if part), "poi")
    return f"cluster_{token}_{index:06d}"


def cluster_payload(
    cluster: WorkingCluster,
    representative: dict,
    config: PoiClusterConfig,
) -> dict:
    """Build transparent cluster metadata."""

    return {
        "source": "poi_cluster",
        "algorithm": "radius_centroid_v1",
        "cluster_radius_m": float(config.cluster_radius_m),
        "direction_cluster_radius_m": float(config.direction_cluster_radius_m),
        "group_key": {
            "model": cluster.key[0],
            "semantic_class": cluster.key[1],
        },
        "representative_candidate_id": representative.get("candidate_id"),
        "representative_eval": representative_eval(representative, cluster),
        "member_candidate_ids": member_ids(cluster.members),
    }


def cluster_row(
    run_id: str,
    cluster_id: str,
    cluster: WorkingCluster,
    config: PoiClusterConfig,
) -> dict:
    """Build one insertable poi_clusters_360 row."""

    representative = representative_member(cluster)
    effective_radius_m = cluster_radius_for_candidate(representative, config)
    frames = [int(member["frame_index"]) for member in cluster.members]
    min_confidence, max_confidence, mean_confidence = confidence_stats(cluster.members)
    return {
        "cluster_id": cluster_id,
        "run_id": run_id,
        "representative_candidate_id": str(representative["candidate_id"]),
        "target_id": str(representative["target_id"]),
        "frame_index": int(representative["frame_index"]),
        "target_source": str(representative.get("target_source") or ""),
        "semantic_class": str(representative.get("semantic_class") or ""),
        "confidence": parse_float(representative.get("confidence")),
        "projection": str(representative.get("projection") or ""),
        "model_run_id": str(representative.get("model_run_id") or ""),
        "model_name": str(representative.get("model_name") or ""),
        "evidence_face": representative.get("evidence_face"),
        "camera_lat": parse_float(representative.get("camera_lat")),
        "camera_lon": parse_float(representative.get("camera_lon")),
        "object_lat": float(cluster.center_lat),
        "object_lon": float(cluster.center_lon),
        "bearing_deg": parse_float(representative.get("bearing_deg")),
        "distance_m": parse_float(representative.get("distance_m")),
        "position_method": str(representative.get("position_method") or ""),
        "distance_method": str(representative.get("distance_method") or ""),
        "quality": str(representative.get("quality") or "unknown"),
        "observation_count": len(cluster.members),
        "min_frame_index": min(frames),
        "max_frame_index": max(frames),
        "min_confidence": min_confidence,
        "max_confidence": max_confidence,
        "mean_confidence": mean_confidence,
        "cluster_score": representative_score(representative, cluster),
        "cluster_radius_m": effective_radius_m,
        "member_candidate_ids": member_ids(cluster.members),
        "payload": cluster_payload(cluster, representative, config),
    }


def clear_poi_clusters(conn: sqlite3.Connection, run_id: str, config: PoiClusterConfig) -> int:
    """Delete existing clusters for this run and selected filters."""

    where = ["run_id = ?"]
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
        where.append(f"{schema.quote_identifier(column)} IN ({', '.join('?' for _ in values)})")
        params.extend(values)

    cluster_ids = [
        str(row["cluster_id"])
        for row in conn.execute(
            f"""
            SELECT cluster_id
            FROM {schema.quote_identifier(schema.POI_CLUSTERS_TABLE)}
            WHERE {" AND ".join(where)}
            """,
            tuple(params),
        ).fetchall()
    ]
    if not cluster_ids:
        return 0

    before = conn.total_changes
    for start in range(0, len(cluster_ids), 500):
        chunk = cluster_ids[start : start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        conn.execute(
            f"""
            DELETE FROM {schema.quote_identifier(schema.POI_CLUSTER_MEMBERS_TABLE)}
            WHERE cluster_id IN ({placeholders})
            """,
            tuple(chunk),
        )
        conn.execute(
            f"""
            DELETE FROM {schema.quote_identifier(schema.POI_CLUSTERS_TABLE)}
            WHERE cluster_id IN ({placeholders})
            """,
            tuple(chunk),
        )
    return conn.total_changes - before


def insert_cluster(conn: sqlite3.Connection, row: dict, members: list[dict]):
    """Insert one cluster and its member rows."""

    cluster_id = sqlite_io.insert_poi_cluster(
        conn,
        run_id=row["run_id"],
        cluster_id=row["cluster_id"],
        representative_candidate_id=row["representative_candidate_id"],
        target_id=row["target_id"],
        frame_index=row["frame_index"],
        target_source=row["target_source"],
        semantic_class=row["semantic_class"],
        confidence=row["confidence"],
        projection=row["projection"],
        model_run_id=row["model_run_id"],
        model_name=row["model_name"],
        evidence_face=row["evidence_face"],
        camera_lat=row["camera_lat"],
        camera_lon=row["camera_lon"],
        object_lat=row["object_lat"],
        object_lon=row["object_lon"],
        bearing_deg=row["bearing_deg"],
        distance_m=row["distance_m"],
        position_method=row["position_method"],
        distance_method=row["distance_method"],
        quality=row["quality"],
        observation_count=row["observation_count"],
        min_frame_index=row["min_frame_index"],
        max_frame_index=row["max_frame_index"],
        min_confidence=row["min_confidence"],
        max_confidence=row["max_confidence"],
        mean_confidence=row["mean_confidence"],
        cluster_score=row["cluster_score"],
        cluster_radius_m=row["cluster_radius_m"],
        member_candidate_ids=row["member_candidate_ids"],
        payload=row["payload"],
    )

    score_cluster = WorkingCluster(key=("", ""), members=members)
    sorted_members = sorted(
        members,
        key=lambda member: (
            -representative_score(member, score_cluster),
            int(member.get("frame_index") or 0),
            str(member.get("candidate_id") or ""),
        ),
    )
    for index, member in enumerate(sorted_members, start=1):
        distance_to_center_m = geo_projection.distance_between_points_m(
            float(member["object_lat"]),
            float(member["object_lon"]),
            float(row["object_lat"]),
            float(row["object_lon"]),
        )
        sqlite_io.insert_poi_cluster_member(
            conn,
            cluster_id=cluster_id,
            candidate_id=str(member["candidate_id"]),
            run_id=str(row["run_id"]),
            member_rank=index,
            is_representative=str(member["candidate_id"]) == row["representative_candidate_id"],
            member_score=representative_score(member, score_cluster),
            distance_to_center_m=distance_to_center_m,
        )


def generate_poi_clusters(config: PoiClusterConfig) -> dict:
    """Cluster poi_candidates_360 rows into poi_clusters_360."""

    if not config.work_db.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {config.work_db}")

    conn = sqlite_io.initialize(config.work_db)
    try:
        run_row = resolve_run(conn, config.run_id)
        run_id = str(run_row["run_id"])
        candidates = select_poi_candidates(conn, run_id, config)
        deleted_count = clear_poi_clusters(conn, run_id, config) if config.clear_existing else 0
        clusters = build_clusters(candidates, config)

        inserted = 0
        skipped = []
        for index, cluster in enumerate(clusters, start=1):
            if len(cluster.members) < max(1, int(config.min_observations)):
                skipped.append(
                    {
                        "reason": "below_min_observations",
                        "member_count": len(cluster.members),
                        "member_candidate_ids": member_ids(cluster.members),
                    }
                )
                continue
            cluster_id = make_cluster_id(run_id, cluster, index)
            row = cluster_row(run_id, cluster_id, cluster, config)
            insert_cluster(conn, row, cluster.members)
            inserted += 1

        summary = {
            "run_id": run_id,
            "candidate_count": len(candidates),
            "cluster_count": inserted,
            "raw_cluster_count": len(clusters),
            "skipped_count": len(skipped),
            "deleted_count": deleted_count,
            "cluster_radius_m": float(config.cluster_radius_m),
            "direction_cluster_radius_m": float(config.direction_cluster_radius_m),
            "min_observations": int(config.min_observations),
            "group_by_model_run": bool(config.group_by_model_run),
            "ignore_model": bool(config.ignore_model),
            "model_run_ids": list(config.model_run_ids),
            "model_names": list(config.model_names),
            "classes": list(config.classes),
            "qualities": list(config.qualities),
            "position_methods": list(config.position_methods),
            "skipped": skipped[:50],
        }
        sqlite_io.set_metadata(conn, "run", "poi_cluster_summary", summary, scope_id=run_id)
        sqlite_io.update_run_status(conn, run_id, "poi_clusters_generated")
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
        description="Cluster poi_candidates_360 rows into likely real-world POIs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--work-db", required=True, help="semantic_work.sqlite path.")
    parser.add_argument("--run-id", help="Run id. Default: latest run in work DB.")
    parser.add_argument("--cluster-radius-m", type=float, default=DEFAULT_CLUSTER_RADIUS_M)
    parser.add_argument(
        "--direction-cluster-radius-m",
        type=float,
        default=DEFAULT_DIRECTION_CLUSTER_RADIUS_M,
        help="Radius for elevated/direction-only fixed-distance observations.",
    )
    parser.add_argument("--min-observations", type=int, default=1)
    parser.add_argument("--limit", type=int, help="Limit selected candidates for testing.")
    parser.add_argument("--clear-existing", action="store_true", help="Delete matching existing clusters first.")
    parser.add_argument(
        "--group-by-model-run",
        action="store_true",
        help="Keep different model_run_id values in separate cluster groups.",
    )
    parser.add_argument(
        "--ignore-model",
        action="store_true",
        help="Cluster by semantic_class only, ignoring model names and model_run_id.",
    )
    parser.add_argument("--model-run-ids", nargs="+", default=[], help="Optional model_run_id filters.")
    parser.add_argument("--model-names", nargs="+", default=[], help="Optional model_name filters.")
    parser.add_argument("--classes", nargs="+", default=[], help="Optional semantic_class filters.")
    parser.add_argument("--qualities", nargs="+", default=[], help="Optional quality filters.")
    parser.add_argument("--position-methods", nargs="+", default=[], help="Optional position_method filters.")
    return parser


def config_from_args(args) -> PoiClusterConfig:
    """Normalize argparse Namespace into PoiClusterConfig."""

    return PoiClusterConfig(
        work_db=Path(args.work_db).expanduser().resolve(),
        run_id=args.run_id,
        cluster_radius_m=max(0.0, float(args.cluster_radius_m)),
        direction_cluster_radius_m=max(0.0, float(args.direction_cluster_radius_m)),
        min_observations=max(1, int(args.min_observations)),
        limit=args.limit,
        clear_existing=bool(args.clear_existing),
        group_by_model_run=bool(args.group_by_model_run),
        ignore_model=bool(args.ignore_model),
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
    result = generate_poi_clusters(config)
    elapsed = time.perf_counter() - start
    print(f"Work DB: {config.work_db}")
    print(f"Run ID: {result['run_id']}")
    print(f"Candidates: {result['candidate_count']}")
    print(f"Clusters: {result['cluster_count']}")
    print(f"Raw clusters: {result['raw_cluster_count']}")
    print(f"Skipped: {result['skipped_count']}")
    print(f"Cluster radius: {result['cluster_radius_m']:.2f}m")
    print(f"Direction cluster radius: {result['direction_cluster_radius_m']:.2f}m")
    print(f"Min observations: {result['min_observations']}")
    if result["deleted_count"]:
        print(f"Deleted existing clusters/members: {result['deleted_count']}")
    print(f"Done in {elapsed:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
