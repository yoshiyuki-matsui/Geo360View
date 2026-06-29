"""CubeMap face generation for the 360 semantic pipeline.

This module is a QGIS-independent CLI component.  It reads frame selections from
the same GeoPackage rules as the existing Exporter, generates CubeMap face JPEGs,
and registers generated image planes in semantic_work.sqlite.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time

try:
    from . import exporter, job_guard, schema, sqlite_io
except ImportError:
    import exporter
    import job_guard
    import schema
    import sqlite_io


FACE_CONVENTION = "normalized_f_r_b_l_u_d_v1"
DEFAULT_FACE_SIZE_PX = 1024
DEFAULT_JPEG_QUALITY = 92
DEFAULT_CONVERTER = "auto"
OPENCV_CONVERTER = "opencv_remap"
PY360_CONVERTER = "py360convert"
GPKG_JOB_METADATA_TABLE = "gpx_video_processor_job_metadata"


@dataclass(frozen=True)
class CubemapConfig:
    """CLI arguments normalized for CubeMap generation."""

    database: Path
    video: Path
    work_db: Path
    output_dir: Path
    layer: str | None
    frame_column: str | None
    frame_start: int | None
    frame_end: int | None
    frames: tuple[int, ...]
    conditions: tuple[str, ...]
    where: str | None
    matched_only: bool
    limit: int | None
    faces: tuple[str, ...]
    face_size_px: int
    jpeg_quality: int
    overwrite: bool
    frames_per_folder: int
    progress_interval: int
    checkpoint_interval: int
    converter: str
    run_id: str | None


@dataclass(frozen=True)
class GeneratedFace:
    """One generated CubeMap face and its metadata."""

    frame_index: int
    face_name: str
    image_path: Path
    relative_image_path: str
    parent_image_path: str
    width_px: int
    height_px: int
    converter: str
    converter_version: str
    status: str
    message: str = ""


def utc_now_text() -> str:
    """Return current UTC time as ISO-8601 text."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_faces(faces) -> tuple[str, ...]:
    """Normalize face names, accepting `all` as the six-face set."""

    if not faces:
        return schema.DEFAULT_CUBEMAP_EXPORT_FACES
    normalized = []
    for face in faces:
        face_text = str(face).strip().lower()
        if not face_text:
            continue
        if face_text == "all":
            for candidate in schema.CUBEMAP_FACE_NAMES:
                if candidate not in normalized:
                    normalized.append(candidate)
            continue
        if face_text not in schema.CUBEMAP_FACE_NAMES:
            raise ValueError(
                f"Unsupported CubeMap face: {face}. "
                f"Use one of: {', '.join(schema.CUBEMAP_FACE_NAMES)}"
            )
        if face_text not in normalized:
            normalized.append(face_text)
    return tuple(normalized) or schema.DEFAULT_CUBEMAP_EXPORT_FACES


def cubemap_frame_dir(output_dir: Path, frame_index: int, frames_per_folder: int = 1000) -> Path:
    """Return the 1000-frame bucket directory for CubeMap faces."""

    return (
        Path(output_dir)
        / "cubemap"
        / f"{int(frame_index) // int(frames_per_folder):04d}"
    )


def cubemap_face_path(
    output_dir: Path,
    frame_index: int,
    face_name: str,
    frames_per_folder: int = 1000,
) -> Path:
    """Return the JPEG path for one CubeMap face."""

    face = str(face_name).strip().lower()
    return cubemap_frame_dir(output_dir, frame_index, frames_per_folder) / f"frame_{int(frame_index):07d}_{face}.jpg"


def relative_to(path: Path, base: Path) -> str:
    """Return a portable relative path when possible."""

    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def py360convert_version(module) -> str:
    """Return py360convert version when exposed."""

    return str(getattr(module, "__version__", "") or "")


def try_import_py360convert():
    """Import py360convert, returning None when unavailable."""

    try:
        import py360convert
    except ImportError:
        return None
    return py360convert


def select_converter(requested: str):
    """Resolve converter name, module, and version."""

    requested = str(requested or DEFAULT_CONVERTER).lower()
    if requested not in (DEFAULT_CONVERTER, PY360_CONVERTER, OPENCV_CONVERTER):
        raise ValueError(f"Unsupported converter: {requested}")

    if requested in (DEFAULT_CONVERTER, PY360_CONVERTER):
        module = try_import_py360convert()
        if module is not None:
            return PY360_CONVERTER, module, py360convert_version(module)
        if requested == PY360_CONVERTER:
            raise RuntimeError("py360convert is not available in this Python environment.")

    return OPENCV_CONVERTER, None, ""


def opencv_face_maps(face_name: str, size_px: int, pano_width: int, pano_height: int):
    """Build OpenCV remap arrays for one normalized CubeMap face."""

    import numpy as np

    axis = np.linspace(-1.0, 1.0, int(size_px), dtype=np.float32)
    u, v = np.meshgrid(axis, axis)
    face = str(face_name).lower()
    if face == "front":
        x, y, z = u, -v, np.ones_like(u)
    elif face == "right":
        x, y, z = np.ones_like(u), -v, -u
    elif face == "back":
        x, y, z = -u, -v, -np.ones_like(u)
    elif face == "left":
        x, y, z = -np.ones_like(u), -v, u
    elif face == "up":
        x, y, z = u, np.ones_like(u), v
    elif face == "down":
        x, y, z = u, -np.ones_like(u), -v
    else:
        raise ValueError(f"Unsupported CubeMap face: {face_name}")

    length = np.sqrt(x * x + y * y + z * z)
    x = x / length
    y = y / length
    z = z / length
    yaw = np.arctan2(x, z)
    pitch = np.arcsin(y)
    map_x = ((yaw + np.pi) / (2.0 * np.pi)) * float(pano_width - 1)
    map_y = ((np.pi / 2.0 - pitch) / np.pi) * float(pano_height - 1)
    return map_x.astype("float32"), map_y.astype("float32")


def convert_with_opencv(equirectangular_image, faces: tuple[str, ...], face_size_px: int) -> dict[str, object]:
    """Convert an equirectangular OpenCV image to CubeMap faces with remap."""

    import cv2

    height, width = equirectangular_image.shape[:2]
    result = {}
    for face_name in faces:
        map_x, map_y = opencv_face_maps(face_name, face_size_px, width, height)
        result[face_name] = cv2.remap(
            equirectangular_image,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_WRAP,
        )
    return result


def convert_with_py360convert(module, equirectangular_image, faces: tuple[str, ...], face_size_px: int) -> dict[str, object]:
    """Convert an equirectangular image to CubeMap faces with py360convert."""

    face_keys = {
        "front": "F",
        "right": "R",
        "back": "B",
        "left": "L",
        "up": "U",
        "down": "D",
    }
    cube = module.e2c(
        equirectangular_image,
        face_w=int(face_size_px),
        mode="bilinear",
        cube_format="dict",
    )
    result = {}
    for face_name in faces:
        key = face_keys[face_name]
        if key not in cube:
            raise RuntimeError(f"py360convert did not return face {key}.")
        result[face_name] = cube[key]
    return result


def convert_equirectangular_to_faces(
    equirectangular_image,
    faces: tuple[str, ...],
    face_size_px: int,
    converter: str = DEFAULT_CONVERTER,
):
    """Convert one equirectangular image into requested CubeMap face images."""

    actual_converter, module, version = select_converter(converter)
    if actual_converter == PY360_CONVERTER:
        face_images = convert_with_py360convert(module, equirectangular_image, faces, face_size_px)
    else:
        face_images = convert_with_opencv(equirectangular_image, faces, face_size_px)
    return actual_converter, version, face_images


def encode_jpeg(image, jpeg_quality: int):
    """Encode one OpenCV image as JPEG bytes."""

    import cv2

    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
    )
    if not ok:
        raise RuntimeError("Failed to encode CubeMap JPEG.")
    return encoded.tobytes()


def write_bytes_atomic(path: Path, data: bytes):
    """Write bytes through a temporary file and replace atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def exporter_config_from_cubemap_config(config: CubemapConfig):
    """Build an Exporter config only for frame selection."""

    return exporter.ExportConfig(
        database=config.database,
        video=config.video,
        output_dir=config.output_dir,
        layer=config.layer,
        frame_column=config.frame_column,
        frame_start=config.frame_start,
        frame_end=config.frame_end,
        frames=config.frames,
        conditions=config.conditions,
        where=config.where,
        matched_only=config.matched_only,
        scale=1.0,
        jpeg_quality=config.jpeg_quality,
        progressive_jpeg=False,
        overwrite=config.overwrite,
        no_exif=True,
        frames_per_folder=config.frames_per_folder,
        progress_interval=config.progress_interval,
        limit=config.limit,
        interpolation="area",
    )


def read_video_frame(cap, frame_index: int):
    """Read one video frame from an OpenCV VideoCapture."""

    import cv2  # noqa: F401  # imported to make dependency failure explicit here

    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError(f"Failed to read frame {frame_index}.")
    return frame


def parent_image_reference(record, config: CubemapConfig) -> str:
    """Return the known equirectangular evidence image path for a frame if present."""

    raw_path = record.attrs.get("image_path")
    if raw_path:
        return str(raw_path)
    return exporter.frame_output_path(
        Path("images"),
        int(record.frame),
        int(config.frames_per_folder),
    ).as_posix()


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


def metadata_float(metadata: dict, *keys: str, default: float = 0.0) -> float:
    """Return the first numeric metadata value found for the given keys."""

    for key in keys:
        value = metadata.get(key)
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return float(default)


def create_run_config(config: CubemapConfig, layer: str, frame_column: str, record_count: int) -> dict:
    """Create self-describing run config for semantic_work.sqlite."""

    job_metadata = read_gpkg_job_metadata(config.database)
    return {
        "step": "cubemap",
        "database": str(config.database),
        "video": str(config.video),
        "layer": layer,
        "frame_column": frame_column,
        "record_count": int(record_count),
        "cubemap_faces": list(config.faces),
        "face_size_px": int(config.face_size_px),
        "jpeg_quality": int(config.jpeg_quality),
        "converter": config.converter,
        "face_convention": FACE_CONVENTION,
        "frames_per_folder": int(config.frames_per_folder),
        "checkpoint_interval": int(config.checkpoint_interval),
        "video_front_offset_deg": metadata_float(
            job_metadata,
            "video_front_offset_deg",
            "viewer_front_offset_deg",
        ),
    }


def generated_face_to_image_plane_values(run_id: str, face: GeneratedFace, plane_id: str | None = None) -> dict:
    """Return image_planes column values for one generated face."""

    values = {
        "run_id": run_id,
        "frame_index": int(face.frame_index),
        "source_type": "equirectangular_360",
        "projection_type": "cubemap_face",
        "plane_name": face.face_name,
        "face_name": face.face_name,
        "image_path": face.relative_image_path,
        "parent_image_path": face.parent_image_path,
        "width_px": int(face.width_px),
        "height_px": int(face.height_px),
        "converter": face.converter,
        "converter_version": face.converter_version,
        "face_convention": FACE_CONVENTION,
        "transform_json": {
            "face_convention": FACE_CONVENTION,
            "u_direction": "image_right",
            "v_direction": "image_down",
        },
        "created_at": utc_now_text(),
    }
    if plane_id:
        values["plane_id"] = plane_id
    return values


def existing_image_plane_id(conn, run_id: str, frame_index: int, face_name: str) -> str | None:
    """Return an existing image_plane id for run/frame/face when available."""

    row = conn.execute(
        f"""
        SELECT plane_id
        FROM {schema.quote_identifier(schema.IMAGE_PLANES_TABLE)}
        WHERE run_id = ?
            AND frame_index = ?
            AND projection_type = 'cubemap_face'
            AND face_name = ?
        ORDER BY created_at, plane_id
        LIMIT 1
        """,
        (run_id, int(frame_index), str(face_name)),
    ).fetchone()
    return str(row["plane_id"]) if row else None


def register_generated_faces(conn, run_id: str, generated_faces: list[GeneratedFace]):
    """Register generated CubeMap faces as image_planes rows.

    Existing run/frame/face rows are updated instead of duplicated.  This makes
    CubeMap generation resumable when the same run_id is used after interruption.
    """

    plane_ids = []
    for face in generated_faces:
        if face.status not in ("generated", "existing"):
            continue
        plane_id = existing_image_plane_id(conn, run_id, face.frame_index, face.face_name)
        if plane_id:
            values = generated_face_to_image_plane_values(run_id, face, plane_id=plane_id)
            sqlite_io.upsert_row(conn, schema.IMAGE_PLANES_TABLE, values)
        else:
            values = generated_face_to_image_plane_values(run_id, face)
            plane_id = sqlite_io.new_id("plane")
            values["plane_id"] = plane_id
            sqlite_io.insert_row(conn, schema.IMAGE_PLANES_TABLE, values)
        plane_ids.append(plane_id)
    return plane_ids


def elapsed_text(started_at: float) -> str:
    """Return elapsed seconds text for progress logs."""

    return f"{time.perf_counter() - started_at:.1f}s"


def progress_text(processed_records: int, total_records: int, started_at: float) -> str:
    """Return compact progress text with rate and ETA."""

    elapsed = max(0.001, time.perf_counter() - started_at)
    rate = float(processed_records) / elapsed
    remaining = max(0, int(total_records) - int(processed_records))
    eta = remaining / rate if rate > 0 else 0.0
    return (
        f"{processed_records}/{total_records} records "
        f"({rate:.2f} rec/s, eta {eta:.0f}s, elapsed {elapsed:.0f}s)"
    )


def cubemap_progress_summary(
    generated_faces: list[GeneratedFace],
    processed_records: int,
    total_records: int,
    status: str,
    started_at: float,
) -> dict:
    """Return checkpoint metadata for CubeMap generation."""

    summary = summarize_results(generated_faces)
    summary.update(
        {
            "status": status,
            "processed_records": int(processed_records),
            "total_records": int(total_records),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }
    )
    return summary


def flush_cubemap_checkpoint(
    conn,
    run_id: str,
    pending_faces: list[GeneratedFace],
    generated_faces: list[GeneratedFace],
    processed_records: int,
    total_records: int,
    status: str,
    started_at: float,
):
    """Persist pending image_planes and run checkpoint metadata."""

    registered_count = len(register_generated_faces(conn, run_id, pending_faces))
    summary = cubemap_progress_summary(
        generated_faces,
        processed_records=processed_records,
        total_records=total_records,
        status=status,
        started_at=started_at,
    )
    sqlite_io.set_metadata(conn, "run", "cubemap_checkpoint", summary, scope_id=run_id)
    sqlite_io.set_metadata(conn, "run", "cubemap_summary", summary, scope_id=run_id)
    sqlite_io.update_run_status(conn, run_id, f"cubemap_{status}")
    sqlite_io.commit_with_retry(conn)
    pending_faces.clear()
    return registered_count, summary


def generate_cubemaps(config: CubemapConfig):
    """Generate CubeMap faces and register them in semantic_work.sqlite."""

    try:
        import cv2
    except ImportError as e:
        raise RuntimeError(f"OpenCV (cv2) is not available: {e}")

    if not config.video.is_file():
        raise FileNotFoundError(f"Video not found: {config.video}")
    if config.face_size_px <= 0:
        raise ValueError("--size must be greater than 0.")
    if not (1 <= config.jpeg_quality <= 100):
        raise ValueError("--jpeg-quality must be between 1 and 100.")
    if config.frames_per_folder <= 0:
        raise ValueError("--frames-per-folder must be greater than 0.")

    layer, frame_column, records = exporter.read_frame_records(exporter_config_from_cubemap_config(config))
    if not records:
        raise RuntimeError("No frame records matched the given condition.")

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config.work_db.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite_io.initialize(config.work_db)
    started_at = time.perf_counter()
    try:
        if config.run_id:
            rows = sqlite_io.fetch_rows(
                conn,
                schema.RUNS_TABLE,
                where="run_id = ?",
                params=(config.run_id,),
            )
            if not rows:
                raise ValueError(f"run_id not found: {config.run_id}")
            job_guard.ensure_run_matches_job(config.work_db, rows[0], config.database)
            run_id = config.run_id
        else:
            run_id = sqlite_io.create_run(
                conn,
                source_video=config.video,
                source_gpkg=config.database,
                work_dir=output_dir,
                config=create_run_config(config, layer, frame_column, len(records)),
                status="cubemap_running",
            )
        sqlite_io.update_run_status(conn, run_id, "cubemap_running")
        sqlite_io.commit_with_retry(conn)

        cap = cv2.VideoCapture(str(config.video))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {config.video}")

        generated_faces: list[GeneratedFace] = []
        pending_registration: list[GeneratedFace] = []
        processed_records = 0
        interrupted = False
        checkpoint_interval = max(1, int(config.checkpoint_interval or config.progress_interval or 100))
        try:
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            for index, record in enumerate(records, start=1):
                processed_records = index
                if record.frame < 0 or (frame_count > 0 and record.frame >= frame_count):
                    for face_name in config.faces:
                        path = cubemap_face_path(output_dir, record.frame, face_name, config.frames_per_folder)
                        generated_face = GeneratedFace(
                            frame_index=record.frame,
                            face_name=face_name,
                            image_path=path,
                            relative_image_path=relative_to(path, output_dir),
                            parent_image_path=parent_image_reference(record, config),
                            width_px=config.face_size_px,
                            height_px=config.face_size_px,
                            converter=config.converter,
                            converter_version="",
                            status="error",
                            message="frame out of range",
                        )
                        generated_faces.append(generated_face)
                    continue

                pending_face_names = [
                    face_name
                    for face_name in config.faces
                    if config.overwrite
                    or not cubemap_face_path(output_dir, record.frame, face_name, config.frames_per_folder).exists()
                ]
                existing_face_names = [
                    face_name
                    for face_name in config.faces
                    if face_name not in pending_face_names
                ]

                parent_image = parent_image_reference(record, config)
                for face_name in existing_face_names:
                    path = cubemap_face_path(output_dir, record.frame, face_name, config.frames_per_folder)
                    generated_face = GeneratedFace(
                        frame_index=record.frame,
                        face_name=face_name,
                        image_path=path,
                        relative_image_path=relative_to(path, output_dir),
                        parent_image_path=parent_image,
                        width_px=config.face_size_px,
                        height_px=config.face_size_px,
                        converter=config.converter,
                        converter_version="",
                        status="existing",
                    )
                    generated_faces.append(generated_face)
                    pending_registration.append(generated_face)

                if pending_face_names:
                    frame = read_video_frame(cap, record.frame)
                    actual_converter, converter_version, face_images = convert_equirectangular_to_faces(
                        frame,
                        tuple(pending_face_names),
                        config.face_size_px,
                        config.converter,
                    )
                    for face_name, face_image in face_images.items():
                        path = cubemap_face_path(output_dir, record.frame, face_name, config.frames_per_folder)
                        write_bytes_atomic(path, encode_jpeg(face_image, config.jpeg_quality))
                        generated_face = GeneratedFace(
                            frame_index=record.frame,
                            face_name=face_name,
                            image_path=path,
                            relative_image_path=relative_to(path, output_dir),
                            parent_image_path=parent_image,
                            width_px=int(face_image.shape[1]),
                            height_px=int(face_image.shape[0]),
                            converter=actual_converter,
                            converter_version=converter_version,
                            status="generated",
                        )
                        generated_faces.append(generated_face)
                        pending_registration.append(generated_face)

                if index % checkpoint_interval == 0:
                    registered_count, summary = flush_cubemap_checkpoint(
                        conn,
                        run_id,
                        pending_registration,
                        generated_faces,
                        processed_records=index,
                        total_records=len(records),
                        status="running",
                        started_at=started_at,
                    )
                    print(
                        f"CubeMap checkpoint {progress_text(index, len(records), started_at)}; "
                        f"registered={registered_count}; counts={summary['counts']}",
                        flush=True,
                    )
                elif config.progress_interval and index % config.progress_interval == 0:
                    print(
                        f"CubeMap progress {progress_text(index, len(records), started_at)}",
                        flush=True,
                    )
        except KeyboardInterrupt:
            interrupted = True
            registered_count, summary = flush_cubemap_checkpoint(
                conn,
                run_id,
                pending_registration,
                generated_faces,
                processed_records=processed_records,
                total_records=len(records),
                status="interrupted",
                started_at=started_at,
            )
            print(
                f"CubeMap interrupted at {progress_text(processed_records, len(records), started_at)}; "
                f"registered={registered_count}; counts={summary['counts']}",
                flush=True,
            )
        finally:
            cap.release()

        if not interrupted:
            registered_count, summary = flush_cubemap_checkpoint(
                conn,
                run_id,
                pending_registration,
                generated_faces,
                processed_records=processed_records,
                total_records=len(records),
                status="complete",
                started_at=started_at,
            )
            print(
                f"CubeMap checkpoint complete {progress_text(processed_records, len(records), started_at)}; "
                f"registered={registered_count}; counts={summary['counts']}",
                flush=True,
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "run_id": run_id,
        "layer": layer,
        "frame_column": frame_column,
        "record_count": len(records),
        "faces": generated_faces,
        "summary": cubemap_progress_summary(
            generated_faces,
            processed_records=processed_records,
            total_records=len(records),
            status="interrupted" if interrupted else "complete",
            started_at=started_at,
        ),
        "interrupted": interrupted,
    }


def summarize_results(generated_faces: list[GeneratedFace]) -> dict:
    """Summarize generated face statuses."""

    counts = {}
    for face in generated_faces:
        counts[face.status] = counts.get(face.status, 0) + 1
    return {
        "generated_at": utc_now_text(),
        "face_count": len(generated_faces),
        "counts": counts,
    }


def write_manifest(output_dir: Path, result: dict):
    """Write a small CSV/JSON manifest for the CubeMap step."""

    manifest_path = Path(output_dir) / "cubemap_manifest.csv"
    summary_path = Path(output_dir) / "cubemap_summary.json"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "frame_index",
            "face_name",
            "status",
            "path",
            "parent_image_path",
            "converter",
            "message",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for face in result["faces"]:
            writer.writerow(
                {
                    "frame_index": face.frame_index,
                    "face_name": face.face_name,
                    "status": face.status,
                    "path": face.relative_image_path,
                    "parent_image_path": face.parent_image_path,
                    "converter": face.converter,
                    "message": face.message,
                }
            )

    summary = dict(result["summary"])
    summary.update(
        {
            "run_id": result["run_id"],
            "layer": result["layer"],
            "frame_column": result["frame_column"],
            "record_count": result["record_count"],
            "manifest": manifest_path.name,
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path, summary_path


def build_arg_parser():
    """Build CubeMap CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Generate six CubeMap faces and register image_planes in semantic_work.sqlite."
    )
    parser.add_argument("--database", default="tmp.gpkg", help="Input GeoPackage. Default: tmp.gpkg")
    parser.add_argument("--video", required=True, help="Source equirectangular MP4 video path.")
    parser.add_argument("--work-db", help="semantic_work.sqlite path. Default: <database parent>/semantic_work.sqlite")
    parser.add_argument("--output-dir", help="Work/output directory. Default: <database parent>")
    parser.add_argument("--layer", help="GeoPackage layer/table name. Default: first feature layer.")
    parser.add_argument("--frame-column", help="Frame column name. Default: frame/frame_number/frame_index auto.")
    parser.add_argument("--frame-start", "--start", dest="frame_start", type=int, help="Inclusive start frame.")
    parser.add_argument("--frame-end", "--end", dest="frame_end", type=int, help="Inclusive end frame.")
    parser.add_argument("--frames", default="", help="Comma/space separated frame list.")
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Column condition such as kp_match=1 or kp_distance_m<=5. Can be repeated.",
    )
    parser.add_argument("--where", help="Advanced raw SQL WHERE fragment appended with AND.")
    parser.add_argument("--matched-only", action="store_true", help="Keep rows with kp_match=1 or non-empty kp.")
    parser.add_argument("--limit", type=int, help="Limit selected records for testing.")
    parser.add_argument("--faces", nargs="+", default=["all"], help="CubeMap faces to export. Default: all six faces.")
    parser.add_argument("--size", type=int, default=DEFAULT_FACE_SIZE_PX, help="CubeMap face size in px.")
    parser.add_argument("--jpeg-quality", type=int, default=DEFAULT_JPEG_QUALITY, help="JPEG quality 1-100.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing face images.")
    parser.add_argument("--frames-per-folder", type=int, default=exporter.DEFAULT_FRAMES_PER_FOLDER)
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=100,
        help="Persist image_planes and checkpoint metadata every N frame records.",
    )
    parser.add_argument(
        "--converter",
        choices=[DEFAULT_CONVERTER, PY360_CONVERTER, OPENCV_CONVERTER],
        default=DEFAULT_CONVERTER,
        help="CubeMap converter. Default: auto.",
    )
    parser.add_argument("--run-id", help="Existing run_id to append to. Default: create a new run.")
    return parser


def config_from_args(args) -> CubemapConfig:
    """Normalize argparse Namespace into CubemapConfig."""

    database = Path(args.database).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else database.parent
    )
    work_db = (
        Path(args.work_db).expanduser().resolve()
        if args.work_db
        else database.parent / "semantic_work.sqlite"
    )
    video = Path(args.video).expanduser().resolve()
    job_root = job_guard.ensure_cubemap_job_root(database, video, work_db)
    if output_dir != job_root and not output_dir.is_relative_to(job_root):
        raise ValueError(
            "CubeMap output_dir must be under the project directory containing MP4, "
            f"tmp.gpkg, and semantic_work.sqlite ({output_dir} != {job_root})."
        )
    return CubemapConfig(
        database=database,
        video=video,
        work_db=work_db,
        output_dir=output_dir,
        layer=args.layer,
        frame_column=args.frame_column,
        frame_start=args.frame_start,
        frame_end=args.frame_end,
        frames=exporter.parse_frame_list(args.frames),
        conditions=tuple(args.condition or []),
        where=args.where,
        matched_only=bool(args.matched_only),
        limit=args.limit,
        faces=normalize_faces(args.faces),
        face_size_px=int(args.size),
        jpeg_quality=int(args.jpeg_quality),
        overwrite=bool(args.overwrite),
        frames_per_folder=int(args.frames_per_folder),
        progress_interval=int(args.progress_interval),
        checkpoint_interval=int(args.checkpoint_interval),
        converter=args.converter,
        run_id=args.run_id,
    )


def main(argv=None):
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    start = time.perf_counter()
    result = generate_cubemaps(config)
    manifest_path, summary_path = write_manifest(config.output_dir, result)
    elapsed = time.perf_counter() - start

    print(f"Database: {config.database}")
    print(f"Video: {config.video}")
    print(f"Work DB: {config.work_db}")
    print(f"Run ID: {result['run_id']}")
    print(f"Frames: {result['record_count']}")
    print(f"Faces: {', '.join(config.faces)}")
    print(f"Status: {result['summary'].get('status')}")
    print(f"Done in {elapsed:.2f}s. Counts: {result['summary']['counts']}")
    print(f"Manifest: {manifest_path}")
    print(f"Summary: {summary_path}")
    return 130 if result.get("interrupted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
