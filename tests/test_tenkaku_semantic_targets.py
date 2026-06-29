"""semantic_targets.py tests for CubeMap YOLO -> click-compatible targets."""

import math
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import schema, semantic_targets, sqlite_io


class SemanticTargetGeometryTests(unittest.TestCase):
    """CubeMap face/bboxからviewer互換yaw/pitchへの変換を確認する。"""

    def test_right_face_center_points_to_90_degrees_yaw(self):
        """右面中央はカメラheadingから右90度のtargetになる。"""
        target = semantic_targets.bbox_to_cubemap_target(
            bbox=(40.0, 40.0, 60.0, 60.0),
            face_name="right",
            width_px=101,
            height_px=101,
            bbox_anchor="center",
        )

        self.assertAlmostEqual(target.target_yaw_to_camera_heading, 90.0, places=6)
        self.assertAlmostEqual(target.target_pitch_deg, 0.0, places=6)
        self.assertAlmostEqual(target.cubemap_u, 0.0, places=6)
        self.assertAlmostEqual(target.cubemap_v, 0.0, places=6)

    def test_front_face_lower_anchor_produces_positive_down_pitch(self):
        """前面下寄りのbbox下端は下向き正pitchになる。"""
        target = semantic_targets.bbox_to_cubemap_target(
            bbox=(40.0, 40.0, 60.0, 80.0),
            face_name="front",
            width_px=101,
            height_px=101,
            bbox_anchor="bottom_center",
        )

        expected_pitch = math.degrees(math.atan2(0.6, 1.0))
        self.assertAlmostEqual(target.target_yaw_to_camera_heading, 0.0, places=6)
        self.assertAlmostEqual(target.target_pitch_deg, expected_pitch, places=6)

    def test_traffic_sign_detector_classes_are_elevated_objects(self):
        """拾ってきたtraffic sign detectorのクラス名を高さあり対象として扱う。"""
        for class_name in ("Speed Limit 30", "Speed Limit 100", "Stop", "Green Light", "Red Light"):
            with self.subTest(class_name=class_name):
                policy = semantic_targets.policy_for_class(class_name)

                self.assertEqual(policy.bbox_anchor, "center")
                self.assertEqual(policy.projection, "elevated_object")

    def test_road_marking_classes_are_ground_plane_objects(self):
        """路面標示系クラスは地面上の意味として扱う。"""
        for class_name in ("road_marking", "pavement marking", "lane-marking", "crosswalk"):
            with self.subTest(class_name=class_name):
                policy = semantic_targets.policy_for_class(class_name)

                self.assertEqual(policy.bbox_anchor, "center")
                self.assertEqual(policy.projection, "ground_plane")


class SemanticTargetDbTests(unittest.TestCase):
    """YOLO検出結果をsemantic_targets_360へ加工保存する流れを確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.work_db = self.root / "semantic_work.sqlite"
        self.conn = sqlite_io.initialize(self.work_db)
        self.run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            source_gpkg="tmp.gpkg",
            work_dir=self.root,
            config={"cubemap_faces": list(schema.DEFAULT_CUBEMAP_EXPORT_FACES)},
        )
        self.model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
            conf=0.35,
        )
        self.front_plane_id = sqlite_io.insert_image_plane(
            self.conn,
            run_id=self.run_id,
            frame_index=30,
            plane_name="front",
            face_name="front",
            image_path="cubemap/0000/frame_0000030_front.jpg",
            width_px=101,
            height_px=101,
            converter="opencv_remap",
            face_convention="normalized_f_r_b_l_u_d_v1",
        )
        self.right_plane_id = sqlite_io.insert_image_plane(
            self.conn,
            run_id=self.run_id,
            frame_index=30,
            plane_name="right",
            face_name="right",
            image_path="cubemap/0000/frame_0000030_right.jpg",
            width_px=101,
            height_px=101,
            converter="opencv_remap",
            face_convention="normalized_f_r_b_l_u_d_v1",
        )
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.right_plane_id,
            frame_index=30,
            bbox=(40.0, 40.0, 60.0, 60.0),
            class_id=99,
            class_name="unknown_asset",
            confidence=0.7,
        )
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.front_plane_id,
            frame_index=30,
            bbox=(40.0, 40.0, 60.0, 80.0),
            class_id=1,
            class_name="traffic_cone",
            confidence=0.86,
        )
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.front_plane_id,
            frame_index=30,
            bbox=(20.0, 20.0, 40.0, 60.0),
            class_id=2,
            class_name="traffic_sign",
            confidence=0.91,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def test_generate_semantic_targets_writes_click_compatible_rows(self):
        """YOLO検出をクリック点互換targetへ変換して保存する。"""
        result = semantic_targets.generate_semantic_targets(
            semantic_targets.SemanticTargetConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                camera_height_m=2.0,
                hud_height_scale=1.0,
                limit=None,
                clear_existing=True,
            )
        )

        self.assertEqual(result["detection_count"], 3)
        self.assertEqual(result["target_count"], 3)
        self.assertEqual(result["skipped_count"], 0)

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.SEMANTIC_TARGETS_TABLE,
            order_by="semantic_class",
        )
        by_class = {row["semantic_class"]: row for row in rows}

        unknown = by_class["unknown_asset"]
        self.assertAlmostEqual(unknown["target_yaw_to_camera_heading"], 90.0, places=6)
        self.assertEqual(unknown["projection"], "direction_only")
        self.assertIsNone(unknown["ground_distance_m"])
        self.assertEqual(unknown["quality"], "unknown")

        cone = by_class["traffic_cone"]
        self.assertEqual(cone["bbox_anchor"], "bottom_center")
        self.assertEqual(cone["projection"], "ground_plane")
        self.assertEqual(cone["quality"], "trusted")
        self.assertAlmostEqual(cone["target_pitch_deg"], math.degrees(math.atan2(0.6, 1.0)), places=6)
        self.assertAlmostEqual(cone["ground_distance_m"], 2.0 / 0.6, places=6)
        self.assertIn('"effective_camera_height_m": 2.0', cone["payload_json"])

        sign = by_class["traffic_sign"]
        self.assertEqual(sign["projection"], "elevated_object")
        self.assertIsNone(sign["ground_distance_m"])
        self.assertEqual(sign["quality"], "unknown")

    def test_generate_semantic_targets_can_skip_large_bbox_area_ratio(self):
        """bbox面積率が大きすぎる検出はtarget化しない。"""
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.front_plane_id,
            frame_index=30,
            bbox=(0.0, 0.0, 101.0, 101.0),
            class_id=14,
            class_name="Stop",
            confidence=0.99,
        )
        self.conn.commit()

        result = semantic_targets.generate_semantic_targets(
            semantic_targets.SemanticTargetConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                camera_height_m=2.0,
                hud_height_scale=1.0,
                limit=None,
                clear_existing=True,
                max_bbox_area_ratio=0.30,
            )
        )

        self.assertEqual(result["detection_count"], 4)
        self.assertEqual(result["processed_detection_count"], 3)
        self.assertEqual(result["target_count"], 3)
        self.assertEqual(result["large_bbox_skipped_count"], 1)
        rows = sqlite_io.fetch_rows(self.conn, schema.SEMANTIC_TARGETS_TABLE)
        self.assertEqual(len(rows), 3)

    def test_generate_semantic_targets_can_filter_by_model_name(self):
        """複数model_runが同じDBにあっても特定モデルだけtarget化できる。"""
        pothole_model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="pothole_detector",
            model_path="models/pothole.pt",
            conf=0.4,
        )
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=pothole_model_run_id,
            plane_id=self.front_plane_id,
            frame_index=30,
            bbox=(30.0, 70.0, 68.0, 95.0),
            class_id=0,
            class_name="pothole",
            confidence=0.88,
        )
        sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            detection_id="det_not_selected",
            frame_index=30,
            target_source=semantic_targets.TARGET_SOURCE,
            semantic_class="legacy_sign",
            confidence=0.5,
            target_yaw_to_camera_heading=0.0,
            target_pitch_deg=0.0,
            projection="elevated_object",
            quality="unknown",
        )
        self.conn.commit()

        result = semantic_targets.generate_semantic_targets(
            semantic_targets.SemanticTargetConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                camera_height_m=2.0,
                hud_height_scale=1.0,
                limit=None,
                clear_existing=True,
                model_names=("pothole_detector",),
            )
        )

        self.assertEqual(result["detection_count"], 1)
        self.assertEqual(result["processed_detection_count"], 1)
        self.assertEqual(result["target_count"], 1)
        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.SEMANTIC_TARGETS_TABLE,
            order_by="semantic_class",
        )
        self.assertEqual([row["semantic_class"] for row in rows], ["legacy_sign", "pothole"])
        pothole = [row for row in rows if row["semantic_class"] == "pothole"][0]
        self.assertIn('"model_name": "pothole_detector"', pothole["payload_json"])


if __name__ == "__main__":
    unittest.main()
