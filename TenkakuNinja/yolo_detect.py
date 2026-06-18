"""YOLO inference for CubeMap image_planes.

This module reads selected CubeMap faces from semantic_work.sqlite, runs an
Ultralytics YOLO model, and stores raw detections in yolo_detections_raw.  It is
intended to run in a separate venv_yolo environment, not inside QGIS Python.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import time

try:
    from . import schema, sqlite_io
    from .cubemap import normalize_faces
except ImportError:
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
    """Skip planes already represented by detections when resuming a model run."""

    if not resume:
        return planes, 0
    existing_plane_ids = existing_detection_plane_ids(conn, model_run_id)
    if not existing_plane_ids:
        return planes, 0
    selected = [plane for plane in planes if str(plane["plane_id"]) not in existing_plane_ids]
    return selected, len(planes) - len(selected)


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
    conn.commit()
    return summary


def progress_text(processed: int, total: int, started_at: float) -> str:
    """Return compact progress text with rate and ETA."""

    elapsed = max(0.001, time.perf_counter() - started_at)
    rate = float(processed) / elapsed
    remaining = max(0, int(total) - int(processed))
    eta = remaining / rate if rate > 0 else 0.0
    return f"{processed}/{total} image planes ({rate:.2f} img/s, eta {eta:.0f}s, elapsed {elapsed:.0f}s)"


def load_yolo_model(model_path: Path):
    """Load an Ultralytics YOLO model once for chunked prediction."""

    ultralytics_module, YOLO = import_ultralytics()
    model = YOLO(str(model_path))
    return ultralytics_module, model


def yolo_predict(model, image_paths: list[Path], config: YoloDetectConfig):
    """Run Ultralytics YOLO over image paths and return raw Results objects."""

    kwargs = {
        "conf": float(config.conf),
        "verbose": False,
    }
    if config.imgsz is not None:
        kwargs["imgsz"] = int(config.imgsz)
    if config.device:
        kwargs["device"] = config.device
    return model.predict([str(path) for path in image_paths], **kwargs)


def chunked(items: list, chunk_size: int):
    """Yield a list in bounded chunks."""

    size = max(1, int(chunk_size))
    for start in range(0, len(items), size):
        yield start, items[start : start + size]


def predictions_from_ultralytics_results(planes: list[dict], results) -> list[DetectionPrediction]:
    """Normalize Ultralytics Results into DetectionPrediction rows."""

    predictions: list[DetectionPrediction] = []
    for plane, result in zip(planes, results):
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
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
        image_paths = [resolve_image_path(config.work_db, run_row, plane) for plane in planes]
        missing = [str(path) for path in image_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Image plane file not found: {missing[0]}")

        detection_ids = []
        processed_planes = 0
        interrupted = False
        summary = persist_yolo_checkpoint(
            conn,
            run_id,
            model_run_id,
            config.faces,
            processed_planes=0,
            total_planes=len(planes),
            detection_count=detection_count_for_model_run(conn, model_run_id),
            skipped_existing_planes=skipped_existing_planes,
            status="running",
            started_at=started_at,
        )

        try:
            for start, plane_chunk in chunked(planes, config.chunk_size):
                path_chunk = image_paths[start : start + len(plane_chunk)]
                results = yolo_predict(model, path_chunk, config)
                predictions = predictions_from_ultralytics_results(plane_chunk, results)
                detection_ids.extend(insert_predictions(conn, run_id, model_run_id, predictions))
                processed_planes = start + len(plane_chunk)
                summary = persist_yolo_checkpoint(
                    conn,
                    run_id,
                    model_run_id,
                    config.faces,
                    processed_planes=processed_planes,
                    total_planes=len(planes),
                    detection_count=detection_count_for_model_run(conn, model_run_id),
                    skipped_existing_planes=skipped_existing_planes,
                    status="running",
                    started_at=started_at,
                )
                if config.progress_interval > 0:
                    if processed_planes == len(planes) or processed_planes % config.progress_interval == 0:
                        print(
                            f"YOLO checkpoint {progress_text(processed_planes, len(planes), started_at)}; "
                            f"detections={summary['detection_count']}",
                            flush=True,
                        )
        except KeyboardInterrupt:
            interrupted = True
            summary = persist_yolo_checkpoint(
                conn,
                run_id,
                model_run_id,
                config.faces,
                processed_planes=processed_planes,
                total_planes=len(planes),
                detection_count=detection_count_for_model_run(conn, model_run_id),
                skipped_existing_planes=skipped_existing_planes,
                status="interrupted",
                started_at=started_at,
            )
            print(
                f"YOLO interrupted at {progress_text(processed_planes, len(planes), started_at)}; "
                f"detections={summary['detection_count']}",
                flush=True,
            )

        if not interrupted:
            summary = persist_yolo_checkpoint(
                conn,
                run_id,
                model_run_id,
                config.faces,
                processed_planes=processed_planes,
                total_planes=len(planes),
                detection_count=detection_count_for_model_run(conn, model_run_id),
                skipped_existing_planes=skipped_existing_planes,
                status="complete",
                started_at=started_at,
            )
            print(
                f"YOLO checkpoint complete {progress_text(processed_planes, len(planes), started_at)}; "
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
        "plane_count": len(planes),
        "processed_plane_count": processed_planes,
        "skipped_existing_plane_count": skipped_existing_planes,
        "detection_count": summary["detection_count"],
        "interrupted": interrupted,
        "summary": summary,
    }


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
    parser.add_argument("--chunk-size", type=int, default=100, help="Number of image planes per YOLO predict call.")
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
    print(f"Detections: {result['detection_count']}")
    print(f"Status: {result['summary'].get('status')}")
    print(f"Done in {elapsed:.2f}s.")
    return 130 if result.get("interrupted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
