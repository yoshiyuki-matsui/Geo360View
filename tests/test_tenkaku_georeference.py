"""georeference.py tests for semantic_targets_360 -> poi_candidates_360."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import georeference, projection, schema, sqlite_io


class GeoreferenceDbTests(unittest.TestCase):
    """semantic targetをGPKG軌跡と合わせて緯度経度化する流れを確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.gpkg = self.root / "tmp.gpkg"
        self._create_position_database()

        self.work_db = self.root / "semantic_work.sqlite"
        self.conn = sqlite_io.initialize(self.work_db)
        self.run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            source_gpkg=self.gpkg,
            work_dir=self.root,
            config={"purpose": "georeference_test"},
        )
        self.model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
        )
        self.plane_id = sqlite_io.insert_image_plane(
            self.conn,
            run_id=self.run_id,
            frame_index=30,
            plane_name="front",
            face_name="front",
            image_path="cubemap/0000/frame_0000030_front.jpg",
        )
        self.ground_detection_id = sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.plane_id,
            frame_index=30,
            bbox=(10, 10, 20, 20),
            class_name="traffic_cone",
            confidence=0.8,
        )
        self.elevated_detection_id = sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.plane_id,
            frame_index=30,
            bbox=(30, 10, 40, 20),
            class_name="traffic_sign",
            confidence=0.9,
        )
        self.ground_target_id = sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            detection_id=self.ground_detection_id,
            frame_index=30,
            target_source="yolo_cubemap",
            semantic_class="traffic_cone",
            confidence=0.8,
            target_yaw_to_camera_heading=90.0,
            target_pitch_deg=20.0,
            ground_distance_m=5.0,
            projection="ground_plane",
            quality="trusted",
            evidence_face="front",
            payload={"model_run_id": self.model_run_id, "model_name": "assets"},
        )
        self.elevated_target_id = sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            detection_id=self.elevated_detection_id,
            frame_index=30,
            target_source="yolo_cubemap",
            semantic_class="traffic_sign",
            confidence=0.9,
            target_yaw_to_camera_heading=180.0,
            target_pitch_deg=-5.0,
            ground_distance_m=None,
            projection="elevated_object",
            quality="unknown",
            evidence_face="front",
            payload={"model_run_id": self.model_run_id, "model_name": "assets"},
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def _create_position_database(self):
        center = projection.GeoPoint(lat=35.0, lon=135.0)
        before = projection.destination_point(center.lat, center.lon, 180.0, 2.0)
        after = projection.destination_point(center.lat, center.lon, 0.0, 2.0)

        conn = sqlite3.connect(self.gpkg)
        try:
            conn.execute(
                """
                CREATE TABLE video_gpx_points (
                    frame INTEGER PRIMARY KEY,
                    latitude REAL,
                    longitude REAL,
                    aligned_latitude REAL,
                    aligned_longitude REAL
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO video_gpx_points
                (frame, latitude, longitude, aligned_latitude, aligned_longitude)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (20, before.lat, before.lon, before.lat, before.lon),
                    (30, center.lat, center.lon, center.lat, center.lon),
                    (40, after.lat, after.lon, after.lat, after.lon),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def test_generate_poi_candidates_uses_ground_and_fixed_distance(self):
        """地面対象はground_distance、空中対象は固定距離で候補点化する。"""
        result = georeference.generate_poi_candidates(
            georeference.GeoreferenceConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                fallback_distance_m=10.0,
                clear_existing=True,
            )
        )

        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["ground_distance_candidate_count"], 1)
        self.assertEqual(result["fixed_distance_candidate_count"], 1)
        self.assertEqual(result["skipped_count"], 0)

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.POI_CANDIDATES_TABLE,
            order_by="semantic_class",
        )
        by_class = {row["semantic_class"]: row for row in rows}

        cone = by_class["traffic_cone"]
        self.assertEqual(cone["position_method"], georeference.POSITION_METHOD_GROUND_PLANE)
        self.assertEqual(cone["distance_method"], georeference.DISTANCE_METHOD_GROUND)
        self.assertEqual(cone["quality"], "trusted")
        self.assertAlmostEqual(cone["bearing_deg"], 90.0, places=4)
        self.assertAlmostEqual(cone["distance_m"], 5.0, places=6)
        dx, dy = projection.local_vector_meters(
            cone["camera_lat"],
            cone["camera_lon"],
            cone["object_lat"],
            cone["object_lon"],
        )
        self.assertAlmostEqual(dx, 5.0, places=3)
        self.assertAlmostEqual(dy, 0.0, places=3)

        sign = by_class["traffic_sign"]
        self.assertEqual(sign["position_method"], georeference.POSITION_METHOD_FIXED_DISTANCE)
        self.assertEqual(sign["distance_method"], georeference.DISTANCE_METHOD_FIXED)
        self.assertEqual(sign["quality"], georeference.QUALITY_DIRECTION_ONLY)
        self.assertAlmostEqual(sign["bearing_deg"], 180.0, places=4)
        self.assertAlmostEqual(sign["distance_m"], 10.0, places=6)
        self.assertIn("fixed_distance_for_direction_only", sign["payload_json"])

    def test_generate_poi_candidates_can_filter_by_model_name(self):
        """同じDBに複数モデルがある前提でmodel_name filterを使える。"""
        result = georeference.generate_poi_candidates(
            georeference.GeoreferenceConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                model_names=("assets",),
                clear_existing=True,
            )
        )

        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["candidate_count"], 2)

    def test_generate_poi_candidates_skips_far_ground_targets(self):
        """地面対象でも最大距離を超えるものは候補化しない。"""
        sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            detection_id=None,
            frame_index=30,
            target_source="yolo_cubemap",
            semantic_class="pothole",
            confidence=0.7,
            target_yaw_to_camera_heading=0.0,
            target_pitch_deg=4.0,
            ground_distance_m=30.0,
            projection="ground_plane",
            quality="far",
        )
        self.conn.commit()

        result = georeference.generate_poi_candidates(
            georeference.GeoreferenceConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                projections=("ground_plane",),
                max_ground_distance_m=10.0,
                clear_existing=True,
            )
        )

        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["skipped"][0]["reason"], "ground_distance_exceeds_max")

    def test_generate_poi_candidates_can_skip_stationary_camera(self):
        """停止中など軌跡移動量が小さいtargetは候補化から外せる。"""
        center = projection.GeoPoint(lat=35.0, lon=135.0)
        before = projection.destination_point(center.lat, center.lon, 180.0, 0.05)
        after = projection.destination_point(center.lat, center.lon, 0.0, 0.05)
        conn = sqlite3.connect(self.gpkg)
        try:
            conn.execute(
                """
                UPDATE video_gpx_points
                SET latitude = ?, longitude = ?, aligned_latitude = ?, aligned_longitude = ?
                WHERE frame = ?
                """,
                (before.lat, before.lon, before.lat, before.lon, 20),
            )
            conn.execute(
                """
                UPDATE video_gpx_points
                SET latitude = ?, longitude = ?, aligned_latitude = ?, aligned_longitude = ?
                WHERE frame = ?
                """,
                (center.lat, center.lon, center.lat, center.lon, 30),
            )
            conn.execute(
                """
                UPDATE video_gpx_points
                SET latitude = ?, longitude = ?, aligned_latitude = ?, aligned_longitude = ?
                WHERE frame = ?
                """,
                (after.lat, after.lon, after.lat, after.lon, 40),
            )
            conn.commit()
        finally:
            conn.close()

        result = georeference.generate_poi_candidates(
            georeference.GeoreferenceConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                exclude_stationary=True,
                stationary_distance_m=0.5,
                clear_existing=True,
            )
        )

        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual({item["reason"] for item in result["skipped"]}, {"stationary_camera"})


if __name__ == "__main__":
    unittest.main()
