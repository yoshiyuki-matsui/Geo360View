"""YOLO detection DB stage tests for the 360 semantic pipeline."""

import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import schema, sqlite_io, yolo_detect


class YoloDetectDbTests(unittest.TestCase):
    """yolo_detect.pyのDB選択・保存ロジックを確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.database = self.work_dir / "semantic_work.sqlite"
        self.conn = sqlite_io.initialize(self.database)
        self.run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            work_dir=self.work_dir,
            config={
                "cubemap_faces": list(schema.DEFAULT_CUBEMAP_EXPORT_FACES),
                "yolo_faces": ["front", "left", "right"],
            },
        )
        for face in schema.CUBEMAP_FACE_NAMES:
            sqlite_io.insert_image_plane(
                self.conn,
                run_id=self.run_id,
                frame_index=30,
                plane_name=face,
                face_name=face,
                image_path=f"cubemap/0000/frame_0000030_{face}.jpg",
                width_px=1024,
                height_px=1024,
                converter="opencv_remap",
                face_convention="normalized_f_r_b_l_u_d_v1",
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def test_select_image_planes_filters_requested_faces(self):
        """6面のimage_planesからYOLO対象面だけを選ぶ。"""
        rows = yolo_detect.select_image_planes(
            self.conn,
            self.run_id,
            ("front", "right"),
        )

        self.assertEqual([row["face_name"] for row in rows], ["front", "right"])
        self.assertEqual([row["frame_index"] for row in rows], [30, 30])

    def test_resolve_image_path_uses_run_work_dir(self):
        """image_planes.image_pathはruns.work_dir基準で解決する。"""
        run_row = yolo_detect.resolve_run(self.conn, self.run_id)
        plane = yolo_detect.select_image_planes(self.conn, self.run_id, ("left",))[0]

        path = yolo_detect.resolve_image_path(self.database, run_row, plane)

        self.assertEqual(path, self.work_dir / "cubemap/0000/frame_0000030_left.jpg")

    def test_chunked_splits_work_without_loading_all_images(self):
        """YOLO対象画像を小さなchunkに分けられる。"""
        chunks = list(yolo_detect.chunked(list(range(5)), 2))

        self.assertEqual(chunks, [(0, [0, 1]), (2, [2, 3]), (4, [4])])

    def test_insert_predictions_writes_raw_detections(self):
        """正規化済みpredictionをyolo_detections_rawへ保存する。"""
        model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
            conf=0.35,
        )
        plane = yolo_detect.select_image_planes(self.conn, self.run_id, ("right",))[0]
        prediction = yolo_detect.DetectionPrediction(
            plane_id=plane["plane_id"],
            frame_index=30,
            bbox=(120.0, 80.0, 260.0, 340.0),
            class_id=1,
            class_name="traffic_cone",
            confidence=0.86,
            raw={"source": "test", "face": "right"},
        )

        detection_ids = yolo_detect.insert_predictions(
            self.conn,
            self.run_id,
            model_run_id,
            [prediction],
        )
        self.conn.commit()

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.YOLO_DETECTIONS_TABLE,
            where="detection_id = ?",
            params=(detection_ids[0],),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plane_id"], plane["plane_id"])
        self.assertEqual(rows[0]["class_name"], "traffic_cone")
        self.assertEqual(rows[0]["bbox_width"], 140.0)
        self.assertEqual(rows[0]["bbox_height"], 260.0)
        self.assertIn('"face": "right"', rows[0]["raw_json"])

    def test_filter_planes_for_resume_skips_planes_with_existing_detections(self):
        """resume時は既に検出があるplaneを再処理対象から外す。"""
        model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
            conf=0.35,
        )
        planes = yolo_detect.select_image_planes(self.conn, self.run_id, ("front", "right"))
        sqlite_io.insert_yolo_detection(
            self.conn,
            run_id=self.run_id,
            model_run_id=model_run_id,
            plane_id=planes[0]["plane_id"],
            frame_index=30,
            bbox=(10.0, 10.0, 30.0, 40.0),
            class_id=1,
            class_name="traffic_sign",
            confidence=0.8,
        )
        self.conn.commit()

        selected, skipped_count = yolo_detect.filter_planes_for_resume(
            self.conn,
            model_run_id,
            planes,
            resume=True,
        )

        self.assertEqual(skipped_count, 1)
        self.assertEqual([row["plane_id"] for row in selected], [planes[1]["plane_id"]])

    def test_filter_planes_for_resume_skips_checkpointed_planes_without_detections(self):
        """checkpoint済みなら検出ゼロのplaneも再処理対象から外す。"""
        model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
            conf=0.35,
        )
        planes = yolo_detect.select_image_planes(self.conn, self.run_id, ("front", "left", "right"))
        sqlite_io.set_metadata(
            self.conn,
            "model_run",
            "yolo_detection_checkpoint",
            {
                "processed_plane_count": 2,
                "total_plane_count": 3,
                "status": "running",
            },
            scope_id=model_run_id,
        )
        self.conn.commit()

        selected, skipped_count = yolo_detect.filter_planes_for_resume(
            self.conn,
            model_run_id,
            planes,
            resume=True,
        )

        self.assertEqual(skipped_count, 2)
        self.assertEqual([row["plane_id"] for row in selected], [planes[2]["plane_id"]])

    def test_persist_yolo_checkpoint_writes_metadata(self):
        """YOLO checkpoint metadataをmodel_run単位で保存する。"""
        model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
            conf=0.35,
        )

        summary = yolo_detect.persist_yolo_checkpoint(
            self.conn,
            run_id=self.run_id,
            model_run_id=model_run_id,
            faces=("front", "right"),
            processed_planes=2,
            total_planes=6,
            detection_count=4,
            skipped_existing_planes=1,
            status="running",
            started_at=0.0,
        )

        metadata = sqlite_io.get_metadata(
            self.conn,
            "model_run",
            "yolo_detection_checkpoint",
            scope_id=model_run_id,
        )
        self.assertEqual(summary["processed_plane_count"], 2)
        self.assertEqual(metadata["status"], "running")
        self.assertEqual(metadata["skipped_existing_plane_count"], 1)

    def test_ensure_model_run_requires_resume_for_existing_id(self):
        """既存model_run_idの再利用は明示resumeを要求する。"""
        model_run_id = sqlite_io.insert_model_run(
            self.conn,
            run_id=self.run_id,
            model_name="assets",
            model_path="models/assets.pt",
            conf=0.35,
        )
        base = {
            "work_db": self.database,
            "model": Path("models/assets.pt"),
            "run_id": self.run_id,
            "faces": ("front",),
            "conf": 0.35,
            "imgsz": None,
            "device": "",
            "limit": None,
            "model_name": "assets",
            "model_version": "",
            "model_run_id": model_run_id,
            "progress_interval": 100,
            "chunk_size": 100,
            "batch": None,
            "auto_batch_candidates": (16, 32, 64),
            "auto_batch_probe_images": 256,
            "auto_batch_target_vram_fraction": 0.85,
            "auto_batch_safety_margin": 0.40,
            "stream": True,
        }

        with self.assertRaises(ValueError):
            yolo_detect.ensure_model_run(
                self.conn,
                self.run_id,
                yolo_detect.YoloDetectConfig(**base, resume=False),
                ultralytics_version="test",
            )

        reused_id, created = yolo_detect.ensure_model_run(
            self.conn,
            self.run_id,
            yolo_detect.YoloDetectConfig(**base, resume=True),
            ultralytics_version="test",
        )
        self.assertEqual(reused_id, model_run_id)
        self.assertFalse(created)

    def test_temporary_yolo_source_file_writes_paths_and_cleans_up(self):
        """stream用のsource fileへ画像パスを書き、利用後に削除する。"""
        image_paths = [
            self.work_dir / "cubemap/0000/frame_0000030_front.jpg",
            self.work_dir / "cubemap/0000/frame_0000030_right.jpg",
        ]

        with yolo_detect.temporary_yolo_source_file(image_paths) as source_path:
            self.assertTrue(source_path.is_file())
            lines = source_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines, [str(path) for path in image_paths])

        self.assertFalse(source_path.exists())

    def test_yolo_predict_stream_uses_source_file_and_batch(self):
        """stream時はPython listではなくsource fileをUltralyticsへ渡す。"""

        class FakeModel:
            def __init__(self):
                self.source = None
                self.kwargs = None

            def predict(self, source, **kwargs):
                self.source = source
                self.kwargs = kwargs
                return iter(["result"])

        config = yolo_detect.YoloDetectConfig(
            work_db=self.database,
            model=Path("models/assets.pt"),
            run_id=self.run_id,
            faces=("front",),
            conf=0.35,
            imgsz=640,
            device="0",
            limit=None,
            model_name="assets",
            model_version="",
            model_run_id=None,
            progress_interval=100,
            chunk_size=100,
            batch=32,
            auto_batch_candidates=(16, 32, 64),
            auto_batch_probe_images=256,
            auto_batch_target_vram_fraction=0.85,
            auto_batch_safety_margin=0.40,
            stream=True,
            resume=False,
        )
        model = FakeModel()
        image_paths = [
            self.work_dir / "cubemap/0000/frame_0000030_front.jpg",
            self.work_dir / "cubemap/0000/frame_0000030_right.jpg",
        ]

        results = list(yolo_detect.yolo_predict(model, image_paths, config))

        self.assertEqual(results, ["result"])
        self.assertIsInstance(model.source, str)
        self.assertTrue(model.source.endswith(".txt"))
        self.assertFalse(Path(model.source).exists())
        self.assertTrue(model.kwargs["stream"])
        self.assertEqual(model.kwargs["batch"], 32)
        self.assertEqual(model.kwargs["imgsz"], 640)
        self.assertEqual(model.kwargs["device"], "0")

    def test_stream_result_paths_map_back_to_planes_when_sorted(self):
        """source file内の順序が変わってもresult.pathでplaneへ戻せる。"""
        planes = yolo_detect.select_image_planes(self.conn, self.run_id, ("front", "right"))
        path_chunk = [self.work_dir / str(plane["image_path"]) for plane in planes]
        path_to_plane = {str(path.absolute()): plane for path, plane in zip(path_chunk, planes)}

        class Result:
            def __init__(self, path):
                self.path = str(path)
                self.boxes = None

        sorted_results = [Result(path_chunk[1]), Result(path_chunk[0])]
        mapped_plane_ids = [
            yolo_detect.plane_for_yolo_result(result, path_to_plane, planes[index])["plane_id"]
            for index, result in enumerate(sorted_results)
        ]

        self.assertEqual(mapped_plane_ids, [planes[1]["plane_id"], planes[0]["plane_id"]])

    def test_stream_result_without_path_falls_back_to_order(self):
        """result.pathがないテスト用結果は従来通り順序で扱う。"""

        class Result:
            path = ""

        fallback_plane = {"plane_id": "fallback"}
        plane = yolo_detect.plane_for_yolo_result(Result(), {}, fallback_plane)

        self.assertEqual(plane["plane_id"], "fallback")

    def test_stream_result_unknown_path_raises(self):
        """現在chunk外のresult.pathは誤登録せずエラーにする。"""

        class Result:
            path = "/tmp/not_in_chunk.jpg"

        with self.assertRaises(RuntimeError):
            yolo_detect.plane_for_yolo_result(Result(), {}, {"plane_id": "fallback"})

    def test_parse_batch_argument_accepts_int_or_auto(self):
        """--batchは整数またはautoを受け付ける。"""
        self.assertEqual(yolo_detect.parse_batch_argument("32"), 32)
        self.assertEqual(yolo_detect.parse_batch_argument("auto"), "auto")
        with self.assertRaises(Exception):
            yolo_detect.parse_batch_argument("0")

    def test_parse_int_csv_accepts_commas(self):
        """auto batch候補をカンマ区切りで指定できる。"""
        self.assertEqual(yolo_detect.parse_int_csv("16,32,64"), (16, 32, 64))

    def test_select_auto_batch_candidate_applies_safety_margin(self):
        """最速batchから安全マージンを取った候補を選ぶ。"""
        successful = [
            {"batch": 16, "throughput": 20.0},
            {"batch": 32, "throughput": 26.0},
            {"batch": 64, "throughput": 30.0},
        ]

        selected = yolo_detect.select_auto_batch_candidate(successful, safety_margin=0.40)

        self.assertEqual(selected["best_batch"], 64)
        self.assertEqual(selected["batch_ceiling"], 38)
        self.assertEqual(selected["selected_batch"], 32)


if __name__ == "__main__":
    unittest.main()
