"""YOLO inference for CubeMap image_planes.

This module reads selected CubeMap faces from semantic_work.sqlite, runs an
Ultralytics YOLO model, and stores raw detections in yolo_detections_raw.  It is
intended to run in a separate venv_yolo environment, not inside QGIS Python.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import time

try:
    from . import job_guard, schema, sqlite_io
    from .cubemap import normalize_faces
except ImportError:
    import job_guard
    import schema
    import sqlite_io
    from cubemap import normalize_faces


@dataclass(frozen=True)
class YoloDetectConfig:
    """CLI arguments normalized for YOLO detection."""

    work_db: Path
    model: Path
    run_id: str | None
    faces: tuple[str, ...]
    conf: float
    imgsz: int | None
    device: str
    limit: int | None
    model_name: str
    model_version: str
    model_run_id: str | None
    progress_interval: int
    chunk_size: int
    batch: int | str | None
    auto_batch_candidates: tuple[int, ...]
    auto_batch_probe_images: int
    auto_batch_target_vram_fraction: float
    auto_batch_safety_margin: float
    stream: bool
    resume: bool


@dataclass(frozen=True)
class DetectionPrediction:
    """One normalized YOLO detection for insertion into SQLite."""

    plane_id: str
    frame_index: int
    bbox: tuple[float, float, float, float]
    class_id: int | None
    class_name: str
    confidence: float | None
    raw: dict


def import_ultralytics():
    """Import Ultralytics lazily so tests and QGIS do not need it."""

    try:
        import ultralytics
        from ultralytics import YOLO
    except ImportError as e:
        raise RuntimeError(
            "Ultralytics is not available. Run this command in venv_yolo "
            "or install ultralytics in the active environment."
        ) from e
    return ultralytics, YOLO


def ultralytics_version_text(ultralytics_module) -> str:
    """Return the installed Ultralytics version when available."""

    return str(getattr(ultralytics_module, "__version__", "") or "")


def resolve_run(conn, requested_run_id: str | None = None) -> dict:
    """Resolve the run used for YOLO detection."""

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


def select_image_planes(conn, run_id: str, faces: tuple[str, ...], limit: int | None = None) -> list[dict]:
    """Return CubeMap image_planes selected for YOLO inference."""

    faces = normalize_faces(faces or ("all",))
    placeholders = ", ".join("?" for _ in faces)
    where = (
        "run_id = ? "
        "AND projection_type = 'cubemap_face' "
        f"AND face_name IN ({placeholders})"
    )
    params = [run_id, *faces]
    order = "frame_index, face_name, plane_id"
    if limit is None:
        return sqlite_io.fetch_rows(
            conn,
            schema.IMAGE_PLANES_TABLE,
            where=where,
            params=params,
            order_by=order,
        )

    rows = sqlite_io.fetch_rows(
        conn,
        schema.IMAGE_PLANES_TABLE,
        where=where,
        params=params,
        order_by=order,
    )
    return rows[: max(0, int(limit))]


def resolve_image_path(work_db: Path, run_row: dict, plane_row: dict) -> Path:
    """Resolve image_planes.image_path against runs.work_dir."""

    image_path = Path(str(plane_row.get("image_path") or ""))
    if image_path.is_absolute():
        return image_path
    work_dir = str(run_row.get("work_dir") or "").strip()
    base = Path(work_dir) if work_dir else Path(work_db).parent
    return base / image_path


def existing_model_run(conn, model_run_id: str | None) -> dict | None:
    """Return an existing model_run row when an explicit id already exists."""

    if not model_run_id:
        return None
    rows = sqlite_io.fetch_rows(
        conn,
        schema.MODEL_RUNS_TABLE,
        where="model_run_id = ?",
        params=(model_run_id,),
    )
    return rows[0] if rows else None


def ensure_model_run(conn, run_id: str, config: YoloDetectConfig, ultralytics_version: str) -> tuple[str, bool]:
    """Create or reuse the model_runs row for this YOLO execution."""

    existing = existing_model_run(conn, config.model_run_id)
    if existing:
        if str(existing["run_id"]) != str(run_id):
            raise ValueError(f"model_run_id belongs to another run: {config.model_run_id}")
        if not config.resume:
            raise ValueError(f"model_run_id already exists. Use --resume or choose a new id: {config.model_run_id}")
        return str(existing["model_run_id"]), False

    model_run_id = sqlite_io.insert_model_run(
        conn,
        run_id=run_id,
        model_name=config.model_name or config.model.stem,
        model_path=config.model,
        model_version=config.model_version,
        ultralytics_version=ultralytics_version,
        conf=config.conf,
        imgsz=config.imgsz,
        device=config.device,
        params={
            "faces": list(config.faces),
            "limit": config.limit,
            "chunk_size": config.chunk_size,
            "batch": config.batch,
            "auto_batch_candidates": list(config.auto_batch_candidates),
            "auto_batch_probe_images": config.auto_batch_probe_images,
            "auto_batch_target_vram_fraction": config.auto_batch_target_vram_fraction,
            "auto_batch_safety_margin": config.auto_batch_safety_margin,
            "stream": config.stream,
        },
        model_run_id=config.model_run_id,
    )
    return model_run_id, True


def existing_detection_plane_ids(conn, model_run_id: str) -> set[str]:
    """Return plane_ids that already have at least one detection for model_run_id."""

    rows = conn.execute(
        f"""
        SELECT DISTINCT plane_id
        FROM {schema.quote_identifier(schema.YOLO_DETECTIONS_TABLE)}
        WHERE model_run_id = ?
        """,
        (model_run_id,),
    ).fetchall()
    return {str(row["plane_id"]) for row in rows}


def filter_planes_for_resume(
    conn,
    model_run_id: str,
    planes: list[dict],
    resume: bool,
) -> tuple[list[dict], int]:
    """Skip already checkpointed or detection-bearing planes when resuming."""

    if not resume:
        return planes, 0
    checkpoint = sqlite_io.get_metadata(
        conn,
        "model_run",
        "yolo_detection_checkpoint",
        scope_id=model_run_id,
        default={},
    )
    checkpoint_processed = max(0, int((checkpoint or {}).get("processed_plane_count") or 0))
    checkpoint_processed = min(checkpoint_processed, len(planes))
    selected = list(planes[checkpoint_processed:])
    skipped_count = checkpoint_processed

    existing_plane_ids = existing_detection_plane_ids(conn, model_run_id)
    if existing_plane_ids:
        selected = [plane for plane in selected if str(plane["plane_id"]) not in existing_plane_ids]
        skipped_count = len(planes) - len(selected)
    return selected, skipped_count


def detection_count_for_model_run(conn, model_run_id: str) -> int:
    """Return current detection count for a model_run_id."""

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM {schema.quote_identifier(schema.YOLO_DETECTIONS_TABLE)}
        WHERE model_run_id = ?
        """,
        (model_run_id,),
    ).fetchone()
    return int(row["count"] if row else 0)


def yolo_checkpoint_summary(
    run_id: str,
    model_run_id: str,
    faces: tuple[str, ...],
    processed_planes: int,
    total_planes: int,
    detection_count: int,
    skipped_existing_planes: int,
    status: str,
    started_at: float,
) -> dict:
    """Return YOLO checkpoint metadata."""

    elapsed = time.perf_counter() - started_at
    return {
        "run_id": run_id,
        "model_run_id": model_run_id,
        "faces": list(faces),
        "status": status,
        "processed_plane_count": int(processed_planes),
        "total_plane_count": int(total_planes),
        "detection_count": int(detection_count),
        "skipped_existing_plane_count": int(skipped_existing_planes),
        "elapsed_seconds": round(elapsed, 3),
    }


def persist_yolo_checkpoint(
    conn,
    run_id: str,
    model_run_id: str,
    faces: tuple[str, ...],
    processed_planes: int,
    total_planes: int,
    detection_count: int,
    skipped_existing_planes: int,
    status: str,
    started_at: float,
):
    """Persist YOLO checkpoint metadata and commit."""

    summary = yolo_checkpoint_summary(
        run_id=run_id,
        model_run_id=model_run_id,
        faces=faces,
        processed_planes=processed_planes,
        total_planes=total_planes,
        detection_count=detection_count,
        skipped_existing_planes=skipped_existing_planes,
        status=status,
        started_at=started_at,
    )
    sqlite_io.set_metadata(conn, "model_run", "yolo_detection_checkpoint", summary, scope_id=model_run_id)
    sqlite_io.set_metadata(conn, "model_run", "yolo_detection_summary", summary, scope_id=model_run_id)
    sqlite_io.update_run_status(conn, run_id, f"yolo_{status}")
    sqlite_io.commit_with_retry(conn)
    return summary


def progress_text(processed: int, total: int, started_at: float) -> str:
    """Return compact progress text with rate and ETA."""

    elapsed = max(0.001, time.perf_counter() - started_at)
    rate = float(processed) / elapsed
    remaining = max(0, int(total) - int(processed))
    eta = remaining / rate if rate > 0 else 0.0
    return f"{processed}/{total} image planes ({rate:.2f} img/s, eta {eta:.0f}s, elapsed {elapsed:.0f}s)"


def bytes_to_gb(value: int | float) -> float:
    """Convert bytes to GiB for logs and metadata."""

    return float(value) / (1024 ** 3)


def load_yolo_model(model_path: Path):
    """Load an Ultralytics YOLO model once for chunked prediction."""

    ultralytics_module, YOLO = import_ultralytics()
    model = YOLO(str(model_path))
    return ultralytics_module, model


def yolo_predict_kwargs(config: YoloDetectConfig) -> dict:
    """Return common Ultralytics predict keyword arguments."""

    kwargs = {
        "conf": float(config.conf),
        "verbose": False,
    }
    if config.imgsz is not None:
        kwargs["imgsz"] = int(config.imgsz)
    if config.device:
        kwargs["device"] = config.device
    if isinstance(config.batch, int):
        kwargs["batch"] = int(config.batch)
    return kwargs


@contextmanager
def temporary_yolo_source_file(image_paths: list[Path]):
    """Write image paths to a temporary Ultralytics source file."""

    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".txt",
        prefix="gpxvp_yolo_source_",
        delete=False,
    )
    source_path = Path(handle.name)
    try:
        with handle:
            for path in image_paths:
                handle.write(f"{path}\n")
        yield source_path
    finally:
        source_path.unlink(missing_ok=True)


def yolo_predict(model, image_paths: list[Path], config: YoloDetectConfig):
    """Run Ultralytics YOLO over image paths and yield raw Results objects."""

    kwargs = yolo_predict_kwargs(config)
    if config.stream:
        with temporary_yolo_source_file(image_paths) as source_path:
            yield from model.predict(
                source=str(source_path),
                stream=True,
                **kwargs,
            )
        return

    yield from model.predict(
        source=[str(path) for path in image_paths],
        stream=False,
        **kwargs,
    )


def plane_for_yolo_result(result, path_to_plane: dict[str, dict], fallback_plane: dict) -> dict:
    """Return the image plane that produced a YOLO result."""

    raw_path = str(getattr(result, "path", "") or "")
    if not raw_path:
        return fallback_plane
    result_path = str(Path(raw_path).absolute())
    plane = path_to_plane.get(result_path)
    if plane is None:
        raise RuntimeError(f"YOLO result path was not in the current chunk: {raw_path}")
    return plane


def cuda_device_index(device: str) -> int:
    """Return a torch CUDA device index from a CLI device string."""

    text = str(device or "").strip().lower()
    if not text:
        return 0
    if text.startswith("cuda:"):
        text = text.split(":", 1)[1]
    if text.isdigit():
        return int(text)
    return 0


def is_cpu_device(device: str) -> bool:
    """Return True when the requested device is CPU-like."""

    return str(device or "").strip().lower() in {"cpu", "mps"}


def make_probe_paths(image_paths: list[Path], batch_size: int, probe_images: int) -> list[Path]:
    """Return a bounded set of paths for auto batch benchmarking."""

    if not image_paths:
        return []
    sample_count = min(len(image_paths), max(1, int(probe_images)))
    sample = image_paths[:sample_count]
    if len(sample) >= batch_size:
        return sample
    return [sample[index % len(sample)] for index in range(batch_size)]


def benchmark_batch_size(model, image_paths: list[Path], config: YoloDetectConfig, torch_module, device_index: int, batch_size: int) -> dict:
    """Benchmark one YOLO inference batch candidate."""

    probe_paths = make_probe_paths(image_paths, batch_size, config.auto_batch_probe_images)
    if not probe_paths:
        return {
            "batch": int(batch_size),
            "throughput": 0.0,
            "elapsed_seconds": 0.0,
            "image_count": 0,
            "allocated_delta_gb": 0.0,
            "reserved_delta_gb": 0.0,
        }

    torch_module.cuda.empty_cache()
    torch_module.cuda.reset_peak_memory_stats(device_index)
    start_allocated = torch_module.cuda.memory_allocated(device_index)
    start_reserved = torch_module.cuda.memory_reserved(device_index)
    probe_config = replace(config, batch=int(batch_size), stream=True)
    started_at = time.perf_counter()
    result_count = 0
    for result_count, _ in enumerate(yolo_predict(model, probe_paths, probe_config), start=1):
        pass
    torch_module.cuda.synchronize(device_index)
    elapsed = max(0.001, time.perf_counter() - started_at)
    peak_allocated = torch_module.cuda.max_memory_allocated(device_index)
    peak_reserved = torch_module.cuda.max_memory_reserved(device_index)
    torch_module.cuda.empty_cache()
    return {
        "batch": int(batch_size),
        "throughput": float(result_count) / elapsed,
        "elapsed_seconds": round(elapsed, 3),
        "image_count": int(result_count),
        "allocated_delta_bytes": int(max(0, peak_allocated - start_allocated)),
        "reserved_delta_bytes": int(max(0, peak_reserved - start_reserved)),
        "allocated_delta_gb": round(bytes_to_gb(max(0, peak_allocated - start_allocated)), 3),
        "reserved_delta_gb": round(bytes_to_gb(max(0, peak_reserved - start_reserved)), 3),
    }


def select_auto_batch_candidate(successful: list[dict], safety_margin: float) -> dict:
    """Select a benchmarked batch with a margin below the fastest candidate."""

    if not successful:
        raise ValueError("No successful batch candidates were provided.")
    best = max(successful, key=lambda item: item["throughput"])
    margin = min(0.95, max(0.0, float(safety_margin)))
    batch_ceiling = max(1, int(best["batch"] * (1.0 - margin)))
    eligible = [item for item in successful if int(item["batch"]) <= batch_ceiling]
    if not eligible:
        eligible = [successful[0]]
    selected = max(eligible, key=lambda item: item["throughput"])
    return {
        "selected_batch": int(selected["batch"]),
        "best_batch": int(best["batch"]),
        "best_throughput": float(best["throughput"]),
        "safety_margin": margin,
        "batch_ceiling": batch_ceiling,
        "selected": selected,
    }


def resolve_auto_batch(model, image_paths: list[Path], config: YoloDetectConfig) -> tuple[YoloDetectConfig, dict | None]:
    """Resolve --batch auto into a concrete inference batch."""

    if str(config.batch).lower() != "auto":
        return config, None
    if is_cpu_device(config.device):
        summary = {
            "status": "skipped",
            "reason": "CPU device requested",
            "selected_batch": None,
        }
        print("YOLO auto batch skipped: CPU device requested.", flush=True)
        return replace(config, batch=None), summary

    try:
        import torch
    except ImportError as e:
        raise RuntimeError("--batch auto requires torch in the active environment.") from e

    if not torch.cuda.is_available():
        summary = {
            "status": "skipped",
            "reason": "CUDA is not available",
            "selected_batch": None,
        }
        print("YOLO auto batch skipped: CUDA is not available.", flush=True)
        return replace(config, batch=None), summary

    device_index = cuda_device_index(config.device)
    free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
    current_usage_bytes = total_bytes - free_bytes
    target_fraction = min(0.98, max(0.1, float(config.auto_batch_target_vram_fraction)))
    budget_bytes = max(0, int(total_bytes * target_fraction) - current_usage_bytes)
    print(
        "YOLO auto batch started: "
        f"candidates={list(config.auto_batch_candidates)} "
        f"target_vram={target_fraction:.2f} "
        f"used={bytes_to_gb(current_usage_bytes):.2f}GB "
        f"free={bytes_to_gb(free_bytes):.2f}GB "
        f"budget={bytes_to_gb(budget_bytes):.2f}GB "
        f"safety_margin={config.auto_batch_safety_margin:.2f}",
        flush=True,
    )

    successful: list[dict] = []
    attempted: list[dict] = []
    for candidate in config.auto_batch_candidates:
        batch_size = int(candidate)
        if batch_size <= 0:
            continue
        try:
            result = benchmark_batch_size(model, image_paths, config, torch, device_index, batch_size)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"YOLO auto batch candidate={batch_size} failed: CUDA OOM", flush=True)
            break
        except RuntimeError as e:
            if "out of memory" not in str(e).lower():
                raise
            torch.cuda.empty_cache()
            print(f"YOLO auto batch candidate={batch_size} failed: CUDA OOM", flush=True)
            break

        within_budget = int(result["reserved_delta_bytes"]) <= budget_bytes if budget_bytes > 0 else False
        result["within_budget"] = within_budget
        attempted.append(result)
        print(
            "YOLO auto batch "
            f"candidate={batch_size} "
            f"throughput={result['throughput']:.2f} img/s "
            f"reserved_delta={result['reserved_delta_gb']:.2f}GB "
            f"within_budget={within_budget}",
            flush=True,
        )
        if not within_budget:
            break
        successful.append(result)

    if not successful:
        fallback = int(config.auto_batch_candidates[0]) if config.auto_batch_candidates else 16
        summary = {
            "status": "fallback",
            "selected_batch": fallback,
            "attempted": attempted,
            "target_vram_fraction": target_fraction,
            "safety_margin": float(config.auto_batch_safety_margin),
        }
        print(f"YOLO auto batch selected fallback batch={fallback}", flush=True)
        return replace(config, batch=fallback), summary

    selection = select_auto_batch_candidate(successful, config.auto_batch_safety_margin)
    selected_batch = int(selection["selected_batch"])
    summary = {
        "status": "complete",
        "selected_batch": selected_batch,
        "attempted": attempted,
        "target_vram_fraction": target_fraction,
        "safety_margin": float(config.auto_batch_safety_margin),
        "best_batch": selection["best_batch"],
        "best_throughput": round(selection["best_throughput"], 3),
        "batch_ceiling": selection["batch_ceiling"],
    }
    print(
        "YOLO auto batch selected: "
        f"batch={selected_batch} "
        f"best_batch={selection['best_batch']} "
        f"best_throughput={selection['best_throughput']:.2f} img/s "
        f"batch_ceiling={selection['batch_ceiling']}",
        flush=True,
    )
    return replace(config, batch=selected_batch), summary


def chunked(items: list, chunk_size: int):
    """Yield a list in bounded chunks."""

    size = max(1, int(chunk_size))
    for start in range(0, len(items), size):
        yield start, items[start : start + size]


def predictions_from_ultralytics_result(plane: dict, result) -> list[DetectionPrediction]:
    """Normalize one Ultralytics Result into DetectionPrediction rows."""

    predictions: list[DetectionPrediction] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return predictions
    names = getattr(result, "names", {}) or {}
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    classes = boxes.cls.cpu().numpy().astype(int)
    for bbox, confidence, class_id in zip(xyxy, confs, classes):
        class_id = int(class_id)
        class_name = str(names.get(class_id, class_id))
        bbox_values = tuple(float(value) for value in bbox[:4])
        predictions.append(
            DetectionPrediction(
                plane_id=str(plane["plane_id"]),
                frame_index=int(plane["frame_index"]),
                bbox=bbox_values,
                class_id=class_id,
                class_name=class_name,
                confidence=float(confidence),
                raw={
                    "source": "ultralytics",
                    "plane_id": str(plane["plane_id"]),
                    "image_path": str(plane.get("image_path") or ""),
                },
            )
        )
    return predictions


def predictions_from_ultralytics_results(planes: list[dict], results) -> list[DetectionPrediction]:
    """Normalize Ultralytics Results into DetectionPrediction rows."""

    predictions: list[DetectionPrediction] = []
    for plane, result in zip(planes, results):
        predictions.extend(predictions_from_ultralytics_result(plane, result))
    return predictions


def insert_predictions(conn, run_id: str, model_run_id: str, predictions: list[DetectionPrediction]) -> list[str]:
    """Insert normalized predictions into yolo_detections_raw."""

    detection_ids = []
    for prediction in predictions:
        detection_id = sqlite_io.insert_yolo_detection(
            conn,
            run_id=run_id,
            model_run_id=model_run_id,
            plane_id=prediction.plane_id,
            frame_index=prediction.frame_index,
            bbox=prediction.bbox,
            class_id=prediction.class_id,
            class_name=prediction.class_name,
            confidence=prediction.confidence,
            raw=prediction.raw,
        )
        detection_ids.append(detection_id)
    return detection_ids


def run_yolo_detection(config: YoloDetectConfig) -> dict:
    """Run YOLO detection for selected image_planes and persist raw detections."""

    if not config.work_db.is_file():
        raise FileNotFoundError(f"semantic_work.sqlite not found: {config.work_db}")
    if not config.model.is_file():
        raise FileNotFoundError(f"YOLO model not found: {config.model}")

    conn = sqlite_io.initialize(config.work_db)
    started_at = time.perf_counter()
    try:
        run_row = resolve_run(conn, config.run_id)
        job_guard.ensure_run_matches_job(config.work_db, run_row)
        run_id = str(run_row["run_id"])
        planes = select_image_planes(conn, run_id, config.faces, config.limit)
        if not planes:
            raise RuntimeError("No image_planes matched the given run/faces.")

        ultralytics_module, model = load_yolo_model(config.model)
        model_run_id, model_run_created = ensure_model_run(
            conn,
            run_id,
            config,
            ultralytics_version_text(ultralytics_module),
        )
        planes, skipped_existing_planes = filter_planes_for_resume(conn, model_run_id, planes, config.resume)
        total_selected_plane_count = len(planes) + skipped_existing_planes
        image_paths = [resolve_image_path(config.work_db, run_row, plane) for plane in planes]
        missing = [str(path) for path in image_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Image plane file not found: {missing[0]}")

        config, batch_tune_summary = resolve_auto_batch(model, image_paths, config)
        if batch_tune_summary is not None:
            sqlite_io.set_metadata(
                conn,
                "model_run",
                "yolo_batch_autotune",
                batch_tune_summary,
                scope_id=model_run_id,
            )
            sqlite_io.commit_with_retry(conn)

        detection_ids = []
        pending_predictions: list[DetectionPrediction] = []
        processed_planes = 0
        interrupted = False
        summary = persist_yolo_checkpoint(
            conn,
            run_id,
            model_run_id,
            config.faces,
            processed_planes=skipped_existing_planes,
            total_planes=total_selected_plane_count,
            detection_count=detection_count_for_model_run(conn, model_run_id),
            skipped_existing_planes=skipped_existing_planes,
            status="running",
            started_at=started_at,
        )

        try:
            for start, plane_chunk in chunked(planes, config.chunk_size):
                path_chunk = image_paths[start : start + len(plane_chunk)]
                path_to_plane = {
                    str(path.absolute()): plane
                    for path, plane in zip(path_chunk, plane_chunk)
                }
                result_count = 0
                for result_count, result in enumerate(yolo_predict(model, path_chunk, config), start=1):
                    plane = plane_for_yolo_result(result, path_to_plane, plane_chunk[result_count - 1])
                    pending_predictions.extend(predictions_from_ultralytics_result(plane, result))
                    processed_planes = start + result_count
                    should_checkpoint = processed_planes == len(planes) or result_count == len(plane_chunk)
                    should_print = False
                    if config.progress_interval > 0:
                        should_print = processed_planes == len(planes) or processed_planes % config.progress_interval == 0
                        should_checkpoint = should_checkpoint or processed_planes % config.progress_interval == 0
                    if should_checkpoint:
                        if pending_predictions:
                            detection_ids.extend(insert_predictions(conn, run_id, model_run_id, pending_predictions))
                            pending_predictions.clear()
                        summary = persist_yolo_checkpoint(
                            conn,
                            run_id,
                            model_run_id,
                            config.faces,
                            processed_planes=skipped_existing_planes + processed_planes,
                            total_planes=total_selected_plane_count,
                            detection_count=detection_count_for_model_run(conn, model_run_id),
                            skipped_existing_planes=skipped_existing_planes,
                            status="running",
                            started_at=started_at,
                        )
                        if should_print:
                            print(
                                f"YOLO checkpoint "
                                f"{progress_text(skipped_existing_planes + processed_planes, total_selected_plane_count, started_at)}; "
                                f"detections={summary['detection_count']}",
                                flush=True,
                            )
                if result_count != len(plane_chunk):
                    raise RuntimeError(
                        f"YOLO returned {result_count} results for {len(plane_chunk)} image planes."
                    )
        except KeyboardInterrupt:
            interrupted = True
            if pending_predictions:
                detection_ids.extend(insert_predictions(conn, run_id, model_run_id, pending_predictions))
                pending_predictions.clear()
            summary = persist_yolo_checkpoint(
                conn,
                run_id,
                model_run_id,
                config.faces,
                processed_planes=skipped_existing_planes + processed_planes,
                total_planes=total_selected_plane_count,
                detection_count=detection_count_for_model_run(conn, model_run_id),
                skipped_existing_planes=skipped_existing_planes,
                status="interrupted",
                started_at=started_at,
            )
            print(
                f"YOLO interrupted at "
                f"{progress_text(skipped_existing_planes + processed_planes, total_selected_plane_count, started_at)}; "
                f"detections={summary['detection_count']}",
                flush=True,
            )

        if not interrupted:
            summary = persist_yolo_checkpoint(
                conn,
                run_id,
                model_run_id,
                config.faces,
                processed_planes=skipped_existing_planes + processed_planes,
                total_planes=total_selected_plane_count,
                detection_count=detection_count_for_model_run(conn, model_run_id),
                skipped_existing_planes=skipped_existing_planes,
                status="complete",
                started_at=started_at,
            )
            print(
                f"YOLO checkpoint complete "
                f"{progress_text(skipped_existing_planes + processed_planes, total_selected_plane_count, started_at)}; "
                f"detections={summary['detection_count']}",
                flush=True,
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "run_id": run_id,
        "model_run_id": model_run_id,
        "model_run_created": model_run_created,
        "plane_count": total_selected_plane_count,
        "processed_plane_count": skipped_existing_planes + processed_planes,
        "skipped_existing_plane_count": skipped_existing_planes,
        "detection_count": summary["detection_count"],
        "batch": config.batch,
        "batch_tune_summary": batch_tune_summary,
        "interrupted": interrupted,
        "summary": summary,
    }


def parse_batch_argument(value: str) -> int | str:
    """Parse --batch as a positive integer or auto."""

    text = str(value or "").strip().lower()
    if text == "auto":
        return "auto"
    try:
        batch = int(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError("--batch must be a positive integer or 'auto'.") from e
    if batch <= 0:
        raise argparse.ArgumentTypeError("--batch must be a positive integer or 'auto'.")
    return batch


def parse_int_csv(value: str) -> tuple[int, ...]:
    """Parse comma-separated positive integers."""

    parts = [part.strip() for part in str(value or "").replace(" ", ",").split(",")]
    values = []
    for part in parts:
        if not part:
            continue
        try:
            number = int(part)
        except ValueError as e:
            raise argparse.ArgumentTypeError("Expected comma-separated positive integers.") from e
        if number <= 0:
            raise argparse.ArgumentTypeError("Expected comma-separated positive integers.")
        values.append(number)
    if not values:
        raise argparse.ArgumentTypeError("Expected at least one positive integer.")
    return tuple(values)


def build_arg_parser():
    """Build yolo-detect CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Run YOLO on selected semantic_work.sqlite image_planes."
    )
    parser.add_argument("--work-db", required=True, help="semantic_work.sqlite path.")
    parser.add_argument("--model", required=True, help="Ultralytics YOLO model path.")
    parser.add_argument("--run-id", help="Run id. Default: latest run in work DB.")
    parser.add_argument("--faces", nargs="+", default=["front", "left", "right"], help="Faces to run YOLO on.")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int)
    parser.add_argument("--device", default="")
    parser.add_argument("--limit", type=int, help="Limit selected image planes for testing.")
    parser.add_argument("--model-name", default="")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--model-run-id", help="Explicit model_run_id. Default: generated.")
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100,
        help="Number of image planes per streamed source file/checkpoint chunk.",
    )
    parser.add_argument("--batch", type=parse_batch_argument, help="Ultralytics inference batch size or 'auto'.")
    parser.add_argument(
        "--auto-batch-candidates",
        type=parse_int_csv,
        default=(16, 32, 64),
        help="Comma-separated batch candidates used when --batch auto is set.",
    )
    parser.add_argument(
        "--auto-batch-probe-images",
        type=int,
        default=256,
        help="Number of images used for each --batch auto probe.",
    )
    parser.add_argument(
        "--auto-batch-target-vram-fraction",
        type=float,
        default=0.85,
        help="Maximum target CUDA VRAM fraction used by --batch auto.",
    )
    parser.add_argument(
        "--auto-batch-safety-margin",
        type=float,
        default=0.40,
        help="Safety margin below the fastest batch candidate used by --batch auto.",
    )
    parser.set_defaults(stream=True)
    parser.add_argument(
        "--stream",
        dest="stream",
        action="store_true",
        help="Use a temporary source file and stream YOLO results. This is the default.",
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Pass each chunk as a Python list and collect results before insertion.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="With an existing --model-run-id, skip image planes that already have detections.",
    )
    return parser


def config_from_args(args) -> YoloDetectConfig:
    """Normalize argparse Namespace into YoloDetectConfig."""

    return YoloDetectConfig(
        work_db=Path(args.work_db).expanduser().resolve(),
        model=Path(args.model).expanduser().resolve(),
        run_id=args.run_id,
        faces=normalize_faces(args.faces),
        conf=float(args.conf),
        imgsz=args.imgsz,
        device=str(args.device or ""),
        limit=args.limit,
        model_name=str(args.model_name or ""),
        model_version=str(args.model_version or ""),
        model_run_id=args.model_run_id,
        progress_interval=int(args.progress_interval),
        chunk_size=int(args.chunk_size),
        batch=args.batch,
        auto_batch_candidates=tuple(args.auto_batch_candidates),
        auto_batch_probe_images=int(args.auto_batch_probe_images),
        auto_batch_target_vram_fraction=float(args.auto_batch_target_vram_fraction),
        auto_batch_safety_margin=float(args.auto_batch_safety_margin),
        stream=bool(args.stream),
        resume=bool(args.resume),
    )


def main(argv=None):
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    start = time.perf_counter()
    result = run_yolo_detection(config)
    elapsed = time.perf_counter() - start
    print(f"Work DB: {config.work_db}")
    print(f"Run ID: {result['run_id']}")
    print(f"Model run ID: {result['model_run_id']}")
    print(f"Image planes: {result['plane_count']}")
    print(f"Processed image planes: {result['processed_plane_count']}")
    print(f"Skipped existing planes: {result['skipped_existing_plane_count']}")
    print(f"Batch: {result['batch'] if result['batch'] is not None else 'ultralytics-default'}")
    if result.get("batch_tune_summary"):
        tune_summary = result["batch_tune_summary"]
        print(
            "Auto batch: "
            f"{tune_summary.get('status')} "
            f"selected={tune_summary.get('selected_batch')} "
            f"best={tune_summary.get('best_batch')}"
        )
    print(f"Stream: {config.stream}")
    print(f"Detections: {result['detection_count']}")
    print(f"Status: {result['summary'].get('status')}")
    print(f"Done in {elapsed:.2f}s.")
    return 130 if result.get("interrupted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
