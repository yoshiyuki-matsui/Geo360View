"""yolo_report.py tests for human-checkable YOLO outputs."""

import json
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import schema, semantic_targets, sqlite_io, yolo_report

try:
    from PIL import Image
except ImportError:  # pragma: no cover - exercised only on minimal envs.
    Image = None


@unittest.skipIf(Image is None, "Pillow is required for annotated image tests.")
class YoloReportTests(unittest.TestCase):
    """YOLO検出結果のサマリー・注釈画像出力を確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.work_dir = self.root / "work"
        self.image_dir = self.work_dir / "cubemap" / "0000"
        self.image_dir.mkdir(parents=True)
        self.image_path = self.image_dir / "frame_0000030_front.jpg"
        Image.new("RGB", (128, 128), (40, 42, 45)).save(self.image_path)

        self.work_db = self.work_dir / "semantic_work.sqlite"
        self.conn = sqlite_io.initialize(self.work_db)
        self.run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            work_dir=self.work_dir,
            config={"cubemap_faces": list(schema.DEFAULT_CUBEMAP_EXPORT_FACES)},
        )
        self.model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="traffic_sign_detector",
            model_path="models/traffic_sign_detector.pt",
            conf=0.25,
        )
        self.plane_id = sqlite_io.insert_image_plane(
            self.conn,
            run_id=self.run_id,
            frame_index=30,
            plane_name="front",
            face_name="front",
            image_path="cubemap/0000/frame_0000030_front.jpg",
            width_px=128,
            height_px=128,
            converter="py360convert",
            face_convention="normalized_f_r_b_l_u_d_v1",
        )
        stop_detection_id = sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.plane_id,
            frame_index=30,
            bbox=(20.0, 18.0, 70.0, 90.0),
            class_id=14,
            class_name="Stop",
            confidence=0.96,
        )
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.plane_id,
            frame_index=30,
            bbox=(80.0, 22.0, 118.0, 65.0),
            class_id=0,
            class_name="Green Light",
            confidence=0.72,
        )
        sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            detection_id=stop_detection_id,
            frame_index=30,
            target_source=semantic_targets.TARGET_SOURCE,
            semantic_class="Stop",
            confidence=0.96,
            target_yaw_to_camera_heading=3.5,
            target_pitch_deg=12.0,
            projection="elevated_object",
            quality="unknown",
            evidence_plane_id=self.plane_id,
            evidence_image_path="cubemap/0000/frame_0000030_front.jpg",
            evidence_face="front",
            evidence_bbox=[20.0, 18.0, 70.0, 90.0],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def test_build_report_writes_summaries_and_annotated_image(self):
        """summary/CSV/HTML/注釈画像を一式生成する。"""
        output_dir = self.root / "report"

        summary = yolo_report.build_report(
            yolo_report.YoloReportConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                output_dir=output_dir,
                min_conf=0.0,
                faces=(),
                classes=(),
                max_images=None,
                write_images=True,
                jpeg_quality=90,
            )
        )

        self.assertEqual(summary["detection_count"], 2)
        self.assertEqual(summary["image_plane_with_detection_count"], 1)
        self.assertEqual(summary["annotated_image_count"], 1)
        self.assertEqual(summary["missing_image_count"], 0)
        self.assertTrue((output_dir / "summary.txt").is_file())
        self.assertTrue((output_dir / "summary.json").is_file())
        self.assertTrue((output_dir / "detections.csv").is_file())
        self.assertTrue((output_dir / "class_summary.csv").is_file())
        self.assertTrue((output_dir / "face_summary.csv").is_file())
        self.assertTrue((output_dir / "index.html").is_file())
        self.assertTrue((output_dir / "annotated" / "0000" / "frame_0000030_front_annotated.jpg").is_file())

        stored_summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {item["class_name"]: item["count"] for item in stored_summary["class_summary"]},
            {"Green Light": 1, "Stop": 1},
        )
        detections_csv = (output_dir / "detections.csv").read_text()
        self.assertIn("bbox_area_ratio", detections_csv)
        self.assertIn("annotated/0000/frame_0000030_front_annotated.jpg", detections_csv)
        self.assertIn("YOLO Detection Report", (output_dir / "index.html").read_text(encoding="utf-8"))

    def test_build_report_can_filter_by_face_and_class(self):
        """face/class filterで対象検出だけをレポート化する。"""
        output_dir = self.root / "filtered_report"

        summary = yolo_report.build_report(
            yolo_report.YoloReportConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                output_dir=output_dir,
                min_conf=0.0,
                faces=("front",),
                classes=("Green Light",),
                max_images=None,
                write_images=False,
                jpeg_quality=90,
            )
        )

        self.assertEqual(summary["detection_count"], 1)
        self.assertEqual(summary["annotated_image_count"], 0)
        self.assertEqual(summary["class_summary"][0]["class_name"], "Green Light")
        self.assertFalse((output_dir / "annotated").exists())

    def test_build_report_can_filter_by_model_name(self):
        """同じDB内の複数model_runから特定モデルだけをレポート化する。"""
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
            plane_id=self.plane_id,
            frame_index=30,
            bbox=(30.0, 70.0, 68.0, 105.0),
            class_id=0,
            class_name="pothole",
            confidence=0.88,
        )
        self.conn.commit()
        output_dir = self.root / "model_filtered_report"

        summary = yolo_report.build_report(
            yolo_report.YoloReportConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                output_dir=output_dir,
                min_conf=0.0,
                faces=(),
                classes=(),
                model_names=("pothole_detector",),
                max_images=None,
                write_images=False,
                jpeg_quality=90,
            )
        )

        self.assertEqual(summary["input_detection_count"], 1)
        self.assertEqual(summary["detection_count"], 1)
        self.assertEqual(summary["model_run_summary"][0]["model_name"], "pothole_detector")
        self.assertEqual(summary["class_summary"][0]["class_name"], "pothole")
        detections_csv = (output_dir / "detections.csv").read_text()
        self.assertIn("model_name", detections_csv)
        self.assertIn("pothole_detector", detections_csv)

    def test_build_report_can_filter_large_bbox_area_ratio(self):
        """bbox面積率が閾値を超える検出をレポート対象から外す。"""
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=self.plane_id,
            frame_index=30,
            bbox=(0.0, 0.0, 128.0, 128.0),
            class_id=14,
            class_name="Stop",
            confidence=0.99,
        )
        self.conn.commit()

        output_dir = self.root / "area_filtered_report"
        summary = yolo_report.build_report(
            yolo_report.YoloReportConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                output_dir=output_dir,
                min_conf=0.0,
                faces=(),
                classes=(),
                max_images=None,
                write_images=False,
                jpeg_quality=90,
                max_bbox_area_ratio=0.30,
            )
        )

        self.assertEqual(summary["input_detection_count"], 3)
        self.assertEqual(summary["detection_count"], 2)
        self.assertEqual(summary["large_bbox_filtered_count"], 1)
        self.assertEqual(summary["large_bbox_skipped"][0]["class_name"], "Stop")
        self.assertIn("Large bbox filtered: 1", (output_dir / "summary.txt").read_text(encoding="utf-8"))

    def test_html_gallery_is_sorted_by_frame_index(self):
        """HTMLギャラリーは信頼度順ではなくframe番号順に並べる。"""
        early_image_path = self.image_dir / "frame_0000010_front.jpg"
        Image.new("RGB", (128, 128), (55, 55, 58)).save(early_image_path)
        early_plane_id = sqlite_io.insert_image_plane(
            self.conn,
            run_id=self.run_id,
            frame_index=10,
            plane_name="front",
            face_name="front",
            image_path="cubemap/0000/frame_0000010_front.jpg",
            width_px=128,
            height_px=128,
            converter="py360convert",
            face_convention="normalized_f_r_b_l_u_d_v1",
        )
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=self.model_run_id,
            plane_id=early_plane_id,
            frame_index=10,
            bbox=(20.0, 20.0, 60.0, 60.0),
            class_id=1,
            class_name="Red Light",
            confidence=0.25,
        )
        self.conn.commit()

        output_dir = self.root / "frame_sorted_report"
        yolo_report.build_report(
            yolo_report.YoloReportConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                output_dir=output_dir,
                min_conf=0.0,
                faces=(),
                classes=(),
                max_images=None,
                write_images=True,
                jpeg_quality=90,
            )
        )

        html = (output_dir / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("frame 10 front"), html.index("frame 30 front"))


if __name__ == "__main__":
    unittest.main()
