#!/usr/bin/env python3
"""Build a clean QGIS plugin distribution zip for Geo360View."""

from __future__ import annotations

import argparse
import configparser
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PLUGIN_DIR_NAME = "Geo360View"

EXCLUDE_EXACT = {
    ".gitignore",
    "360viewer/session.json",
    "DESIGN.md",
    "DESIGN.ja.md",
    "realize_rader.md",
}

EXCLUDE_PREFIXES = (
    ".github/",
    "scripts/",
    "tests/",
    "docs/",
    "samples/",
)

REQUIRED_FILES = {
    f"{PLUGIN_DIR_NAME}/metadata.txt",
    f"{PLUGIN_DIR_NAME}/__init__.py",
    f"{PLUGIN_DIR_NAME}/LICENSE",
}

FORBIDDEN_MARKERS = (
    ".git/",
    "__pycache__/",
    ".pyc",
    ".github/",
    "scripts/",
    "tests/",
    "360view_output/",
    "viewer_config.qgis_runtime.json",
    "session.json",
    "krpano/",
    "Thumbs.db",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_git_ls_files(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"failed to list tracked files with git: {exc}") from exc
    return [line for line in result.stdout.splitlines() if line]


def read_version(root: Path) -> str:
    metadata_path = root / "metadata.txt"
    parser = configparser.ConfigParser()
    parser.read(metadata_path, encoding="utf-8")
    try:
        version = parser["general"]["version"].strip()
    except KeyError as exc:
        raise SystemExit("metadata.txt must contain [general] version") from exc
    if not version:
        raise SystemExit("metadata.txt version must not be empty")
    return version


def should_include(relative_path: str) -> bool:
    if relative_path in EXCLUDE_EXACT:
        return False
    return not relative_path.startswith(EXCLUDE_PREFIXES)


def copy_files(root: Path, stage_root: Path, files: list[str]) -> None:
    plugin_root = stage_root / PLUGIN_DIR_NAME
    plugin_root.mkdir(parents=True, exist_ok=True)
    for relative_path in files:
        source = root / relative_path
        target = plugin_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def create_zip(stage_root: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted((stage_root / PLUGIN_DIR_NAME).rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(stage_root).as_posix())


def validate_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()

    roots = {name.split("/", 1)[0] for name in names if name}
    if roots != {PLUGIN_DIR_NAME}:
        raise SystemExit(f"zip must contain only {PLUGIN_DIR_NAME}/, got: {sorted(roots)}")

    missing = REQUIRED_FILES - set(names)
    if missing:
        raise SystemExit(f"zip is missing required files: {sorted(missing)}")

    forbidden = [
        name
        for name in names
        if any(marker in name for marker in FORBIDDEN_MARKERS)
    ]
    if forbidden:
        sample = "\n".join(forbidden[:20])
        raise SystemExit(f"zip contains forbidden files:\n{sample}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a clean Geo360View QGIS plugin zip.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=repo_root() / "dist",
        help="directory where the zip will be written",
    )
    parser.add_argument(
        "--keep-stage",
        action="store_true",
        help="keep the temporary staging directory for inspection",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = repo_root()
    version = read_version(root)
    zip_path = args.output_dir / f"{PLUGIN_DIR_NAME}-{version}.zip"
    tracked_files = run_git_ls_files(root)
    package_files = [path for path in tracked_files if should_include(path)]

    with tempfile.TemporaryDirectory(prefix="geo360view-package-") as tmp:
        stage_root = Path(tmp)
        copy_files(root, stage_root, package_files)
        create_zip(stage_root, zip_path)
        validate_zip(zip_path)
        if args.keep_stage:
            kept_stage = args.output_dir / f"{PLUGIN_DIR_NAME}-{version}-stage"
            if kept_stage.exists():
                shutil.rmtree(kept_stage)
            shutil.copytree(stage_root / PLUGIN_DIR_NAME, kept_stage)
            print(f"stage: {kept_stage}")

    print(f"created: {zip_path}")
    print(f"files: {len(package_files)}")
    print(f"size: {zip_path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
