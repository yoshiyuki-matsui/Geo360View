"""Job-root guard tests for semantic processing."""

import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import job_guard


class JobGuardTests(unittest.TestCase):
    """MP4/GPKG/SQLite combinations must stay inside one project root."""

    def test_cubemap_guard_accepts_same_directory(self):
        """The canonical three job files may live directly under one root."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            actual = job_guard.ensure_cubemap_job_root(
                root / "tmp.gpkg",
                root / "source.mp4",
                root / "semantic_work.sqlite",
            )

        self.assertEqual(actual, root.resolve())

    def test_cubemap_guard_rejects_different_sqlite_directory(self):
        """A work DB from another directory is rejected before processing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            other = root / "other"
            other.mkdir()
            with self.assertRaises(ValueError):
                job_guard.ensure_cubemap_job_root(
                    root / "tmp.gpkg",
                    root / "source.mp4",
                    other / "semantic_work.sqlite",
                )

    def test_run_guard_rejects_database_mismatch(self):
        """Later stages cannot combine a run with another GeoPackage."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_row = {
                "source_gpkg": str(root / "tmp.gpkg"),
                "source_video": str(root / "source.mp4"),
            }
            with self.assertRaises(ValueError):
                job_guard.ensure_run_matches_job(
                    root / "semantic_work.sqlite",
                    run_row,
                    root / "other.gpkg",
                )


if __name__ == "__main__":
    unittest.main()
