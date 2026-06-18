"""360 semantic pipeline SQLite schema tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import schema, sqlite_io


class SemanticWorkSchemaTests(unittest.TestCase):
    """semantic_work.sqliteの初期スキーマを固定する。"""

    def test_create_schema_creates_expected_tables_and_metadata(self):
        """全テーブルとschema_versionメタデータを作成する。"""
        conn = sqlite3.connect(":memory:")
        try:
            schema.create_schema(conn)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            for table_name in schema.table_names():
                self.assertIn(table_name, tables)

            self.assertEqual(schema.read_schema_version(conn), schema.SCHEMA_VERSION)
        finally:
            conn.close()

    def test_semantic_targets_have_click_compatible_columns(self):
        """semantic_targets_360は既存クリック点投影へ渡す最小列を持つ。"""
        columns = set(schema.column_names(schema.SEMANTIC_TARGETS_TABLE))

        self.assertIn("frame_index", columns)
        self.assertIn("target_yaw_to_camera_heading", columns)
        self.assertIn("target_pitch_deg", columns)
        self.assertIn("ground_distance_m", columns)
        self.assertIn("projection", columns)
        self.assertIn("quality", columns)
        self.assertIn("payload_json", columns)

    def test_poi_candidates_have_semantic_filter_columns(self):
        """poi_candidates_360は地図表示・抽出に使う意味列を持つ。"""
        columns = set(schema.column_names(schema.POI_CANDIDATES_TABLE))

        self.assertIn("target_source", columns)
        self.assertIn("semantic_class", columns)
        self.assertIn("confidence", columns)
        self.assertIn("projection", columns)
        self.assertIn("model_run_id", columns)
        self.assertIn("model_name", columns)
        self.assertIn("evidence_face", columns)
        self.assertIn("payload_json", columns)

    def test_cubemap_default_export_faces_are_all_six_faces(self):
        """CubeMap生成は既定で6面を定義する。YOLO対象面は後段で絞る。"""
        self.assertEqual(
            schema.CUBEMAP_FACE_NAMES,
            ("front", "right", "back", "left", "up", "down"),
        )
        self.assertEqual(schema.DEFAULT_CUBEMAP_EXPORT_FACES, schema.CUBEMAP_FACE_NAMES)


class SemanticWorkIoTests(unittest.TestCase):
    """SQLite IOヘルパーでrunからsemantic targetまで保存できることを確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_context.name) / "semantic_work.sqlite"
        self.conn = sqlite_io.initialize(self.database)

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def test_insert_minimum_pipeline_rows(self):
        """run, image_plane, model_run, detection, semantic_targetを関連付けて保存する。"""
        run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            source_gpkg="tmp.gpkg",
            config={
                "cubemap_faces": list(schema.DEFAULT_CUBEMAP_EXPORT_FACES),
                "yolo_faces": ["front", "left", "right"],
            },
        )
        plane_id = sqlite_io.insert_image_plane(
            self.conn,
            run_id=run_id,
            frame_index=30,
            plane_name="right",
            face_name="right",
            image_path="cubemap/0000/frame_0000030_right.jpg",
            width_px=1024,
            height_px=1024,
            converter="py360convert",
            face_convention="normalized_f_r_b_l_u_d_v1",
        )
        model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=run_id,
            model_name="road_assets",
            model_path="models/road_assets.pt",
            conf=0.35,
        )
        detection_id = sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=run_id,
            model_run_id=model_run_id,
            plane_id=plane_id,
            frame_index=30,
            bbox=(120, 80, 260, 340),
            class_id=1,
            class_name="traffic_cone",
            confidence=0.86,
            bbox_anchor_default="bottom_center",
        )
        target_id = sqlite_io.insert_semantic_target(
            self.conn,
            run_id=run_id,
            detection_id=detection_id,
            frame_index=30,
            target_source="yolo_cubemap",
            target_yaw_to_camera_heading=92.4,
            target_pitch_deg=18.7,
            ground_distance_m=5.8,
            projection="ground_plane",
            quality="usable",
            evidence_plane_id=plane_id,
            evidence_image_path="cubemap/0000/frame_0000030_right.jpg",
            evidence_face="right",
            evidence_bbox=[120, 80, 260, 340],
            bbox_anchor="bottom_center",
            payload={"source": "yolo_cubemap", "class_name": "traffic_cone"},
        )
        self.conn.commit()

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.SEMANTIC_TARGETS_TABLE,
            where="target_id = ?",
            params=(target_id,),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_source"], "yolo_cubemap")
        self.assertEqual(rows[0]["projection"], "ground_plane")
        self.assertEqual(rows[0]["quality"], "usable")
        self.assertIn("traffic_cone", rows[0]["payload_json"])

        runs = sqlite_io.fetch_rows(self.conn, schema.RUNS_TABLE)
        self.assertIn('"front"', runs[0]["config_json"])
        self.assertIn('"down"', runs[0]["config_json"])

    def test_insert_poi_candidate_row(self):
        """緯度経度化したPOI候補をsemantic属性付きで保存する。"""
        run_id = sqlite_io.create_run(self.conn, source_video="source.mp4")
        candidate_id = sqlite_io.insert_poi_candidate(
            self.conn,
            run_id=run_id,
            target_id="target_001",
            frame_index=30,
            target_source="yolo_cubemap",
            semantic_class="traffic_sign",
            confidence=0.91,
            projection="elevated_object",
            model_run_id="model_001",
            model_name="traffic_sign_detector",
            evidence_face="front",
            camera_lat=34.0,
            camera_lon=136.0,
            object_lat=34.00001,
            object_lon=136.00002,
            bearing_deg=42.0,
            distance_m=10.0,
            position_method="fixed_distance_bearing",
            distance_method="fixed_distance_for_direction_only",
            quality="direction_only",
            payload={"reason": "elevated_object"},
            candidate_id="poi_target_001",
            replace=True,
        )
        self.conn.commit()

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.POI_CANDIDATES_TABLE,
            where="candidate_id = ?",
            params=(candidate_id,),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["semantic_class"], "traffic_sign")
        self.assertEqual(rows[0]["model_name"], "traffic_sign_detector")
        self.assertEqual(rows[0]["quality"], "direction_only")
        self.assertIn("elevated_object", rows[0]["payload_json"])


if __name__ == "__main__":
    unittest.main()
