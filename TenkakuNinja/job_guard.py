"""Guard rails that keep one semantic job inside one project directory."""

from __future__ import annotations

from pathlib import Path


def resolve_path(value: str | Path) -> Path:
    """Return a normalized absolute path without requiring the file to exist."""

    return Path(value).expanduser().resolve()


def resolve_path_from_root(value: str | Path, root: Path) -> Path:
    """Resolve a possibly relative path from a known project root."""

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def job_root_from_database(database: str | Path) -> Path:
    """Use the GeoPackage parent directory as the project/job root."""

    return resolve_path(database).parent


def ensure_same_job_root(paths: dict[str, str | Path | None]) -> Path:
    """Require all supplied files to live directly under the same directory."""

    roots: dict[str, Path] = {}
    for label, value in paths.items():
        if value in (None, ""):
            continue
        path = resolve_path(value)
        roots[label] = path.parent

    if not roots:
        raise ValueError("No job paths were supplied for same-root validation.")

    first_label, expected_root = next(iter(roots.items()))
    mismatches = [
        f"{label}={root}"
        for label, root in roots.items()
        if root != expected_root
    ]
    if mismatches:
        details = "; ".join([f"{first_label}={expected_root}", *mismatches])
        raise ValueError(
            "Job path mismatch: MP4, tmp.gpkg, and semantic_work.sqlite must be "
            f"in the same project directory ({details})."
        )
    return expected_root


def ensure_cubemap_job_root(database: str | Path, video: str | Path, work_db: str | Path) -> Path:
    """Validate the first semantic stage, where all three canonical files are known."""

    return ensure_same_job_root(
        {
            "database": database,
            "video": video,
            "work_db": work_db,
        }
    )


def ensure_run_matches_job(
    work_db: str | Path,
    run_row: dict,
    database: str | Path | None = None,
) -> Path:
    """Validate a later stage against the run provenance stored in SQLite."""

    if not isinstance(run_row, dict):
        raise ValueError("Run row is missing; cannot validate job paths.")

    source_gpkg_text = str(run_row.get("source_gpkg") or "").strip()
    source_video_text = str(run_row.get("source_video") or "").strip()
    if not source_gpkg_text:
        raise ValueError("runs.source_gpkg is empty; cannot validate job paths.")
    if not source_video_text:
        raise ValueError("runs.source_video is empty; cannot validate job paths.")

    work_db_path = resolve_path(work_db)
    root = work_db_path.parent
    source_gpkg = resolve_path_from_root(source_gpkg_text, root)
    source_video = resolve_path_from_root(source_video_text, root)
    database_path = resolve_path_from_root(database, root) if database not in (None, "") else None

    root = ensure_same_job_root(
        {
            "work_db": work_db_path,
            "source_gpkg": source_gpkg,
            "source_video": source_video,
            "database": database_path,
        }
    )

    if database_path is not None and database_path != source_gpkg:
        raise ValueError(
            "Job GeoPackage mismatch: CLI --database must match runs.source_gpkg "
            f"({database_path} != {source_gpkg})."
        )

    return root
