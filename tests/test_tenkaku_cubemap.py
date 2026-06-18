"""CubeMap generation helpers for the 360 semantic pipeline."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from TenkakuNinja import cubemap, schema, sqlite_io


class CubemapPathAndFaceTests(unittest.TestCase):
    """CubeMap face naming and output paths are stable."""

    def test_normalize_faces_accepts_all_as_six_faces(self):
        """`all` expands to the normalized six-face convention."""
        self.assertEqual(cubemap.normalize_faces(["all"]), schema.CUBEMAP_FACE_NAMES)

    def test_normalize_faces_dedupes_and_preserves_order(self):
        """Explicit face lists keep user order without duplicates."""
        self.assertEqual(
            cubemap.normalize_faces(["right", "front", "right"]),
            ("right", "front"),
        )

    def test_cubemap_face_path_uses_flat_face_names_in_frame_buckets(self):
        """CubeMap output uses 1000-frame folders and frame_face filenames."""
        path = cubemap.cubemap_face_path(Path("work"), 1001, "left", 1000)
        self.assertEqual(path, Path("work/cubemap/0001/frame_0001001_left.jpg"))


class CubemapConversionTests(unittest.TestCase):
    """OpenCV fallback converter produces all requested square faces."""

    def test_opencv_converter_returns_six_square_faces(self):
        """The fallback converter works without py360convert."""
        image = np.zeros((32, 64, 3), dtype=np.uint8)
        image[:, :, 0] = np.linspace(0, 255, 64, dtype=np.uint8)
        actual_converter, version, faces = cubemap.convert_equirectangular_to_faces(
            image,
            schema.CUBEMAP_FACE_NAMES,
            16,
            converter=cubemap.OPENCV_CONVERTER,
        )

        self.assertEqual(actual_converter, cubemap.OPENCV_CONVERTER)
        self.assertEqual(version, "")
        self.assertEqual(set(faces), set(schema.CUBEMAP_FACE_NAMES))
        for face_image in faces.values():
            self.assertEqual(face_image.shape, (16, 16, 3))


class CubemapSqliteRegistrationTests(unittest.TestCase):
    """Generated CubeMap faces are registered as image_planes."""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_context.name) / "semantic_work.sqlite"
        self.conn = sqlite_io.initialize(self.database)

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def test_register_generated_faces_inserts_image_planes(self):
        """All six generated faces are saved as image_planes rows."""
        run_id = sqlite_io.create_run(self.conn, source_video="source.mp4")
        generated_faces = [
            cubemap.GeneratedFace(
                frame_index=30,
                face_name=face_name,
                image_path=Path(f"work/cubemap/0000/frame_0000030_{face_name}.jpg"),
                relative_image_path=f"cubemap/0000/frame_0000030_{face_name}.jpg",
                parent_image_path="images/0000/frame_0000030.jpg",
                width_px=1024,
                height_px=1024,
                converter=cubemap.OPENCV_CONVERTER,
                converter_version="",
                status="generated",
            )
            for face_name in schema.CUBEMAP_FACE_NAMES
        ]

        plane_ids = cubemap.register_generated_faces(self.conn, run_id, generated_faces)
        self.conn.commit()

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.IMAGE_PLANES_TABLE,
            where="run_id = ?",
            params=(run_id,),
            order_by="plane_name",
        )

        self.assertEqual(len(plane_ids), 6)
        self.assertEqual(len(rows), 6)
        self.assertEqual({row["face_name"] for row in rows}, set(schema.CUBEMAP_FACE_NAMES))
        self.assertTrue(all(row["projection_type"] == "cubemap_face" for row in rows))
        self.assertTrue(all(row["face_convention"] == cubemap.FACE_CONVENTION for row in rows))

    def test_register_generated_faces_updates_existing_image_plane(self):
        """同じrun/frame/faceを再登録してもimage_planesを重複させない。"""
        run_id = sqlite_io.create_run(self.conn, source_video="source.mp4")
        first = cubemap.GeneratedFace(
            frame_index=30,
            face_name="front",
            image_path=Path("work/cubemap/0000/frame_0000030_front.jpg"),
            relative_image_path="cubemap/0000/frame_0000030_front.jpg",
            parent_image_path="images/0000/frame_0000030.jpg",
            width_px=512,
            height_px=512,
            converter=cubemap.OPENCV_CONVERTER,
            converter_version="",
            status="generated",
        )
        second = cubemap.GeneratedFace(
            frame_index=30,
            face_name="front",
            image_path=Path("work/cubemap/0000/frame_0000030_front.jpg"),
            relative_image_path="cubemap/0000/frame_0000030_front.jpg",
            parent_image_path="images/0000/frame_0000030.jpg",
            width_px=1024,
            height_px=1024,
            converter=cubemap.PY360_CONVERTER,
            converter_version="1.0.4",
            status="generated",
        )

        first_ids = cubemap.register_generated_faces(self.conn, run_id, [first])
        second_ids = cubemap.register_generated_faces(self.conn, run_id, [second])
        self.conn.commit()

        rows = sqlite_io.fetch_rows(self.conn, schema.IMAGE_PLANES_TABLE, where="run_id = ?", params=(run_id,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(rows[0]["width_px"], 1024)
        self.assertEqual(rows[0]["converter"], cubemap.PY360_CONVERTER)

    def test_flush_cubemap_checkpoint_persists_metadata(self):
        """checkpointごとにimage_planesと進捗metadataを保存する。"""
        run_id = sqlite_io.create_run(self.conn, source_video="source.mp4")
        generated_face = cubemap.GeneratedFace(
            frame_index=30,
            face_name="front",
            image_path=Path("work/cubemap/0000/frame_0000030_front.jpg"),
            relative_image_path="cubemap/0000/frame_0000030_front.jpg",
            parent_image_path="images/0000/frame_0000030.jpg",
            width_px=1024,
            height_px=1024,
            converter=cubemap.OPENCV_CONVERTER,
            converter_version="",
            status="generated",
        )
        pending = [generated_face]

        registered_count, summary = cubemap.flush_cubemap_checkpoint(
            self.conn,
            run_id,
            pending,
            [generated_face],
            processed_records=1,
            total_records=10,
            status="running",
            started_at=0.0,
        )

        metadata = sqlite_io.get_metadata(self.conn, "run", "cubemap_checkpoint", scope_id=run_id)
        rows = sqlite_io.fetch_rows(self.conn, schema.IMAGE_PLANES_TABLE, where="run_id = ?", params=(run_id,))
        self.assertEqual(registered_count, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(pending, [])
        self.assertEqual(summary["processed_records"], 1)
        self.assertEqual(metadata["status"], "running")
        self.assertEqual(metadata["total_records"], 10)


if __name__ == "__main__":
    unittest.main()
