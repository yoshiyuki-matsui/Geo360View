"""gpkg_merge.py tests for semantic_work.sqlite -> tmp.gpkg export."""

import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import gpkg_merge, schema, sqlite_io


def decode_gpkg_point(blob: bytes) -> tuple[float, float]:
    """Decode the minimal GeoPackage POINT blob written by gpkg_merge."""

    assert blob[:2] == b"GP"
    version, flags, srs_id, wkb_endian, wkb_type, x, y = struct.unpack(
        "<BBiBIdd",
        blob[2:],
    )
    assert version == 0
    assert flags == 1
    assert srs_id == 4326
    assert wkb_endian == 1
    assert wkb_type == 1
    return x, y


class GpkgMergeTests(unittest.TestCase):
    """POI候補をQGIS表示用GPKGレイヤへ集約する流れを確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.work_db = self.root / "semantic_work.sqlite"
        self.gpkg = self.root / "tmp.gpkg"
        self.conn = sqlite_io.initialize(self.work_db)
        self.run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            source_gpkg=self.gpkg,
            work_dir=self.root,
        )
        sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            target_id="target_001",
            detection_id="det_001",
            frame_index=30,
            target_source="yolo_cubemap",
            semantic_class="traffic_sign",
            confidence=0.91,
            target_yaw_to_camera_heading=12.5,
            target_pitch_deg=-4.25,
            projection="elevated_object",
            quality="unknown",
            evidence_plane_id="plane_001",
            evidence_image_path="cubemap/0000/frame_0000030_front.jpg",
            evidence_face="front",
            evidence_bbox=[10.0, 20.0, 30.0, 40.0],
            bbox_anchor="center",
            payload={
                "anchor_xy_px": [20.0, 30.0],
                "cubemap_uv": {"u": 0.1, "v": -0.2},
                "bbox": [10.0, 20.0, 30.0, 40.0],
            },
        )
        sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            target_id="target_002",
            detection_id="det_002",
            frame_index=31,
            target_source="yolo_cubemap",
            semantic_class="pothole",
            confidence=0.8,
            target_yaw_to_camera_heading=90.0,
            target_pitch_deg=25.0,
            ground_distance_m=4.0,
            projection="ground_plane",
            quality="trusted",
            evidence_plane_id="plane_002",
            evidence_image_path="cubemap/0000/frame_0000031_down.jpg",
            evidence_face="down",
            evidence_bbox=[50.0, 60.0, 70.0, 80.0],
            bbox_anchor="center",
            payload={
                "anchor_xy_px": [60.0, 70.0],
                "cubemap_uv": {"u": 0.3, "v": 0.4},
                "bbox": [50.0, 60.0, 70.0, 80.0],
            },
        )
        sqlite_io.insert_poi_candidate(
            self.conn,
            run_id=self.run_id,
            target_id="target_001",
            frame_index=30,
            target_source="yolo_cubemap",
            semantic_class="traffic_sign",
            confidence=0.91,
            projection="elevated_object",
            model_run_id="model_traffic",
            model_name="traffic_sign_detector",
            evidence_face="front",
            camera_lat=35.0,
            camera_lon=135.0,
            object_lat=35.00001,
            object_lon=135.00002,
            bearing_deg=45.0,
            distance_m=10.0,
            position_method="fixed_distance_bearing",
            distance_method="fixed_distance_for_direction_only",
            quality="direction_only",
            payload={"source": "test"},
            candidate_id="poi_target_001",
            replace=True,
        )
        sqlite_io.insert_poi_candidate(
            self.conn,
            run_id=self.run_id,
            target_id="target_002",
            frame_index=31,
            target_source="yolo_cubemap",
            semantic_class="pothole",
            confidence=0.8,
            projection="ground_plane",
            model_run_id="model_road",
            model_name="pothole_detector",
            evidence_face="down",
            camera_lat=35.0,
            camera_lon=135.0,
            object_lat=35.00003,
            object_lon=135.00004,
            bearing_deg=10.0,
            distance_m=4.0,
            position_method="ground_plane_bearing",
            distance_method="semantic_ground_distance",
            quality="trusted",
            payload={"source": "test"},
            candidate_id="poi_target_002",
            replace=True,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def test_export_poi_candidates_creates_gpkg_feature_layer(self):
        """poi_candidates_360をtmp.gpkgの別レイヤへPOINTとして書き出す。"""
        result = gpkg_merge.export_poi_candidates(
            gpkg_merge.GpkgMergeConfig(
                work_db=self.work_db,
                database=self.gpkg,
                run_id=self.run_id,
                replace=True,
            )
        )

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["feature_count"], 2)
        self.assertEqual(result["skipped_count"], 0)

        conn = sqlite3.connect(self.gpkg)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = ?",
                    ("poi_candidates_360",),
                ).fetchone(),
                ("features", 4326),
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT column_name, geometry_type_name, srs_id
                    FROM gpkg_geometry_columns
                    WHERE table_name = ?
                    """,
                    ("poi_candidates_360",),
                ).fetchone(),
                ("geom", "POINT", 4326),
            )
            rows = conn.execute(
                """
                SELECT geom, record_type, review_status, semantic_class, quality,
                       latitude, longitude, model_name, target_yaw, target_pitch,
                       detection_id, evidence_plane_id, evidence_bbox_json,
                       bbox_anchor, anchor_x_px, anchor_y_px, cubemap_u, cubemap_v,
                       viewer_marker
                FROM poi_candidates_360
                ORDER BY frame
                """
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(len(rows), 2)
        x, y = decode_gpkg_point(rows[0][0])
        self.assertAlmostEqual(x, 135.00002, places=8)
        self.assertAlmostEqual(y, 35.00001, places=8)
        self.assertEqual(rows[0][1], "yolo_candidate")
        self.assertEqual(rows[0][2], "unreviewed")
        self.assertEqual(rows[0][3], "traffic_sign")
        self.assertEqual(rows[0][4], "direction_only")
        self.assertEqual(rows[0][7], "traffic_sign_detector")
        self.assertAlmostEqual(rows[0][8], 12.5)
        self.assertAlmostEqual(rows[0][9], -4.25)
        self.assertEqual(rows[0][10], "det_001")
        self.assertEqual(rows[0][11], "plane_001")
        self.assertIn("10.0", rows[0][12])
        self.assertEqual(rows[0][13], "center")
        self.assertAlmostEqual(rows[0][14], 20.0)
        self.assertAlmostEqual(rows[0][15], 30.0)
        self.assertAlmostEqual(rows[0][16], 0.1)
        self.assertAlmostEqual(rows[0][17], -0.2)
        self.assertEqual(rows[0][18], "target_point")

    def test_export_requires_replace_for_existing_layer(self):
        """既存レイヤがある場合は明示replaceなしに上書きしない。"""
        gpkg_merge.export_poi_candidates(
            gpkg_merge.GpkgMergeConfig(
                work_db=self.work_db,
                database=self.gpkg,
                run_id=self.run_id,
                replace=True,
            )
        )

        with self.assertRaises(ValueError):
            gpkg_merge.export_poi_candidates(
                gpkg_merge.GpkgMergeConfig(
                    work_db=self.work_db,
                    database=self.gpkg,
                    run_id=self.run_id,
                    replace=False,
                )
            )

    def test_export_can_filter_by_model_name(self):
        """モデル別にGPKG出力を切り分けられる。"""
        result = gpkg_merge.export_poi_candidates(
            gpkg_merge.GpkgMergeConfig(
                work_db=self.work_db,
                database=self.gpkg,
                run_id=self.run_id,
                model_names=("pothole_detector",),
                replace=True,
            )
        )

        self.assertEqual(result["candidate_count"], 1)
        conn = sqlite3.connect(self.gpkg)
        try:
            rows = conn.execute(
                "SELECT semantic_class, model_name, quality FROM poi_candidates_360"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(rows, [("pothole", "pothole_detector", "trusted")])

    def test_default_output_gpkg_is_auto_poi(self):
        """--database省略時の出力先はauto_poi.gpkgになる。"""
        resolved = gpkg_merge.resolve_database_path(
            gpkg_merge.GpkgMergeConfig(
                work_db=self.work_db,
                run_id=self.run_id,
            ),
            {
                "source_gpkg": str(self.gpkg),
            },
        )
        self.assertEqual(resolved, self.root / "auto_poi.gpkg")


if __name__ == "__main__":
    unittest.main()
