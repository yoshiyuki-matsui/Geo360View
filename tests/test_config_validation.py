"""Config/Validation層の退行テスト。"""

from pathlib import Path
import tempfile
import unittest

import config


class ConfigValidationTests(unittest.TestCase):
    """UI入力を処理前に止めるための純Python検証を確認する。"""

    def setUp(self):
        """テストごとに一時ファイル群を用意する。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.gpx = root / "sample.gpx"
        self.video = root / "sample.mp4"
        self.kp = root / "kp.csv"
        self.gpx.write_text("<gpx />", encoding="utf-8")
        self.video.write_bytes(b"mp4")
        self.kp.write_text("kp,lat,lon\n1,35,135\n", encoding="utf-8")
        self.output_dir = root / "360view_output"

    def tearDown(self):
        """一時ファイル群を削除する。"""
        self.temp_dir.cleanup()

    def test_process_config_accepts_valid_inputs(self):
        """GPX/MP4/参照点CSV/出力先/Shift/許容距離を正規化してConfig化する。"""
        result, errors = config.validate_process_config({
            "gpx_file": str(self.gpx),
            "video_file": str(self.video),
            "kp_file": str(self.kp),
            "output_dir": str(self.output_dir),
            "frame_shift": "200",
            "kp_tolerance_m": "5.5",
        })

        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        self.assertEqual(result.frame_shift, 200)
        self.assertEqual(result.kp_tolerance_m, 5.5)

    def test_process_config_rejects_missing_files_and_bad_extension(self):
        """存在しないファイルや拡張子違いをProcessへ渡さない。"""
        result, errors = config.validate_process_config({
            "gpx_file": str(self.gpx.with_suffix(".txt")),
            "video_file": str(self.video.with_suffix(".mov")),
            "output_dir": str(self.output_dir),
            "frame_shift": 0,
            "kp_tolerance_m": 5.0,
        })

        self.assertIsNone(result)
        self.assertTrue(any(".gpx" in error for error in errors))
        self.assertTrue(any(".mp4" in error for error in errors))
        self.assertTrue(any("not found" in error for error in errors))

    def test_process_config_rejects_negative_kp_tolerance(self):
        """参照点マッチング許容距離は負数にしない。"""
        result, errors = config.validate_process_config({
            "gpx_file": str(self.gpx),
            "video_file": str(self.video),
            "output_dir": str(self.output_dir),
            "kp_tolerance_m": -0.1,
        })

        self.assertIsNone(result)
        self.assertIn("Reference tolerance must be greater than or equal to 0.", errors)

    def test_frame_extract_config_rejects_negative_frame(self):
        """負のフレーム番号をOpenCVへ渡さない。"""
        result, errors = config.validate_frame_extract_config({
            "video_file": str(self.video),
            "output_dir": str(self.output_dir),
            "frame_number": -1,
        })

        self.assertIsNone(result)
        self.assertIn("Frame number must be greater than or equal to 0.", errors)

    def test_navigation_config_rejects_bad_mode_and_zero_step(self):
        """不正なナビゲーションモードや0ステップを拒否する。"""
        result, errors = config.validate_navigation_config({
            "mode": "unknown",
            "step": 0,
            "fast_step": 0,
            "follow": True,
        })

        self.assertIsNone(result)
        self.assertTrue(any("Navigation mode is invalid" in error for error in errors))
        self.assertIn("Navigation step must be greater than or equal to 1.", errors)
        self.assertIn("Fast navigation step must be greater than or equal to 1.", errors)

    def test_navigation_config_accepts_detection_mode(self):
        """YOLO候補確認用のナビゲーションモードを許可する。"""
        result, errors = config.validate_navigation_config({
            "mode": "detect",
            "step": 1,
            "fast_step": 30,
            "follow": True,
        })

        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        self.assertEqual(result.mode, "detect")

    def test_navigation_config_accepts_marking_mode(self):
        """保存済みMarking確認用のナビゲーションモードを許可する。"""
        result, errors = config.validate_navigation_config({
            "mode": "marking",
            "step": 1,
            "fast_step": 30,
            "follow": True,
        })

        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        self.assertEqual(result.mode, "marking")

    def test_radar_config_rejects_unusable_calibration(self):
        """FOV/距離/offsetの破綻値をレーダ描画へ渡さない。"""
        result, errors = config.validate_radar_config({
            "range_m": 0,
            "scale": 0,
            "cal_fov_deg": 180,
            "cal_dist_m": 0,
            "offset_deg": 45,
        })

        self.assertIsNone(result)
        self.assertIn("Radar range must be between 1.0 and 500.0 m.", errors)
        self.assertIn("Radar scale must be between 0.1 and 20.0.", errors)
        self.assertIn("Calibration FOV must be between 1.0 and 179.0 degrees.", errors)
        self.assertIn("Calibration distance must be between 0.1 and 500.0 m.", errors)
        self.assertIn("Radar offset must be one of 0, 90, 180, or 270 degrees.", errors)

    def test_viewer_config_accepts_creatable_session_and_cache_paths(self):
        """初回起動前の未作成session/cacheディレクトリを許容する。"""
        root = Path(self.temp_dir.name)
        result, errors = config.validate_viewer_config({
            "host": "127.0.0.1",
            "port": 8181,
            "video_dir": str(root),
            "session_json_path": str(root / "360view_output" / "viewer_session.json"),
            "cache_dir": str(root / "360view_output" / "viewer_cache"),
            "jpeg_quality": 70,
            "progressive_jpeg": True,
            "max_width": 3072,
            "camera_height_m": 1.5,
            "hud_height_scale": 1.3,
        })

        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        self.assertEqual(result.port, 8181)
        self.assertEqual(result.camera_height_m, 1.5)
        self.assertEqual(result.hud_height_scale, 1.3)

    def test_viewer_config_rejects_bad_port_and_quality(self):
        """HTTP portとJPEG品質の範囲外値を拒否する。"""
        root = Path(self.temp_dir.name)
        result, errors = config.validate_viewer_config({
            "host": "127.0.0.1",
            "port": 0,
            "video_dir": str(root),
            "session_json_path": str(root / "viewer_session.json"),
            "cache_dir": str(root / "viewer_cache"),
            "jpeg_quality": 101,
            "progressive_jpeg": True,
            "max_width": -1,
            "camera_height_m": 0,
            "hud_height_scale": 0,
        })

        self.assertIsNone(result)
        self.assertIn("Viewer port must be between 1 and 65535.", errors)
        self.assertIn("Viewer JPEG quality must be between 1 and 100.", errors)
        self.assertIn("Viewer maximum width must be greater than or equal to 0.", errors)
        self.assertIn("Viewer camera height must be between 0.1 and 20.0 m.", errors)
        self.assertIn("Viewer HUD height scale must be between 0.1 and 5.0.", errors)


if __name__ == "__main__":
    unittest.main()
