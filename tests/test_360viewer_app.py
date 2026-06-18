"""360Viewer HTTPアプリの純Python部分を検証する退行テスト。"""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "360viewer" / "app.py"


def load_viewer_app(temp_dir):
    """一時設定ファイルを使って360viewer/app.pyを読み込む。"""
    config = {
        "host": "127.0.0.1",
        "port": 8181,
        "video_dir": str(temp_dir / "videos"),
        "session_json_path": str(temp_dir / "viewer_session.json"),
        "viewer_cache_dir": str(temp_dir / "viewer_cache"),
        "viewer_jpeg_quality": 70,
        "viewer_progressive_jpeg": True,
        "viewer_max_width": 3072,
        "viewer_camera_height_m": 1.5,
        "viewer_hud_height_scale": 1.0,
    }
    config_path = temp_dir / "viewer_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    module_name = f"viewer_app_test_{os.getpid()}_{id(temp_dir)}"
    spec = importlib.util.spec_from_file_location(module_name, APP_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"VIEWER_CONFIG": str(config_path)}):
        spec.loader.exec_module(module)
    return module


class ViewerAppValidationTests(unittest.TestCase):
    """外部HTTP入力を安全に正規化できることを確認する。"""

    def setUp(self):
        """各テストで独立したviewer設定を使う。"""
        self.temp_context = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_context.name)
        self.app = load_viewer_app(self.temp_dir)

    def tearDown(self):
        """一時ディレクトリを破棄する。"""
        self.temp_context.cleanup()

    def test_safe_video_name_rejects_paths_and_non_mp4(self):
        """動画名はvideo_dir直下のMP4ファイル名だけを許可する。"""
        self.assertEqual(self.app.safe_video_name("abc.mp4"), "abc.mp4")

        for value in ("../abc.mp4", "sub/abc.mp4", r"C:\tmp\abc.mp4", "abc.mov"):
            with self.subTest(value=value):
                with self.assertRaises(self.app.ApiError):
                    self.app.safe_video_name(value)

    def test_validate_state_payload_normalizes_view_and_target(self):
        """ビューア状態とクリックtargetを範囲内へ正規化する。"""
        state = self.app.validate_state_payload({
            "video": "abc.mp4",
            "frame_index": "12",
            "yaw_to_camera_heading": "370",
            "pitch": "-3.5",
            "zoom": "2",
            "viewer_camera_height_m": "1.2",
            "viewer_hud_height_scale": "1.3",
            "target": {
                "x_ratio": "1.5",
                "y_ratio": "-0.5",
                "yaw_delta_deg": "190",
                "pitch_delta_deg": "120",
                "target_yaw_to_camera_heading": "-10",
                "view_yaw_to_camera_heading": "725",
                "view_pitch": "-95",
                "view_zoom": "0",
                "projection": "unknown",
                "ground_distance_m": "3.4",
                "quality": "trusted",
            },
        })

        self.assertEqual(state["frame_index"], 12)
        self.assertEqual(state["yaw_to_camera_heading"], 10.0)
        self.assertEqual(state["pitch"], -3.5)
        self.assertEqual(state["zoom"], 2.0)
        self.assertEqual(state["viewer_camera_height_m"], 1.2)
        self.assertEqual(state["viewer_hud_height_scale"], 1.3)
        self.assertEqual(state["target"]["x_ratio"], 1.0)
        self.assertEqual(state["target"]["y_ratio"], 0.0)
        self.assertEqual(state["target"]["yaw_delta_deg"], -170.0)
        self.assertEqual(state["target"]["pitch_delta_deg"], 90.0)
        self.assertEqual(state["target"]["target_yaw_to_camera_heading"], 350.0)
        self.assertEqual(state["target"]["target_pitch_deg"], 0.0)
        self.assertEqual(state["target"]["view_yaw_to_camera_heading"], 5.0)
        self.assertEqual(state["target"]["view_pitch"], -90.0)
        self.assertEqual(state["target"]["view_zoom"], 0.01)
        self.assertEqual(state["target"]["projection"], "ground_plane")
        self.assertEqual(state["target"]["ground_distance_m"], 3.4)
        self.assertEqual(state["target"]["quality"], "trusted")

    def test_validate_state_payload_accepts_multiple_targets(self):
        """ダブルクリック複数点は順序ID付きtargetsとして保存する。"""
        state = self.app.validate_state_payload({
            "video": "abc.mp4",
            "frame_index": 12,
            "yaw_to_camera_heading": 10,
            "pitch": 0,
            "zoom": 1,
            "targets": [
                {
                    "x_ratio": 0.25,
                    "y_ratio": 0.5,
                    "yaw_delta_deg": -3,
                    "target_pitch_deg": 6,
                    "target_yaw_to_camera_heading": 7,
                    "view_zoom": 1,
                },
                {
                    "id": 8,
                    "order": 8,
                    "x_ratio": 0.75,
                    "y_ratio": 0.5,
                    "yaw_delta_deg": 4,
                    "target_yaw_to_camera_heading": 14,
                    "view_zoom": 1,
                },
            ],
        })

        self.assertEqual(len(state["targets"]), 2)
        self.assertEqual(state["targets"][0]["id"], 1)
        self.assertEqual(state["targets"][0]["order"], 1)
        self.assertEqual(state["targets"][0]["target_pitch_deg"], 6.0)
        self.assertEqual(state["targets"][1]["id"], 8)
        self.assertEqual(state["targets"][1]["order"], 8)
        self.assertEqual(state["target"], state["targets"][1])

    def test_validate_target_payload_accepts_restored_target_without_screen_ratio(self):
        """QGIS側で復元したtargetは画面クリック比率が無くても受け取れる。"""
        state = self.app.validate_state_payload({
            "video": "abc.mp4",
            "frame_index": 12,
            "yaw_to_camera_heading": 10,
            "pitch": 0,
            "zoom": 1,
            "targets": [
                {
                    "id": 3,
                    "order": 3,
                    "yaw_delta_deg": 4,
                    "target_yaw_to_camera_heading": 14,
                    "target_pitch_deg": -2,
                    "view_yaw_to_camera_heading": 10,
                    "view_pitch": 0,
                    "view_zoom": 1.2,
                },
            ],
        })

        self.assertEqual(len(state["targets"]), 1)
        self.assertEqual(state["targets"][0]["x_ratio"], 0.5)
        self.assertEqual(state["targets"][0]["y_ratio"], 0.5)
        self.assertEqual(state["targets"][0]["target_yaw_to_camera_heading"], 14.0)

    def test_write_session_is_atomic_json_write(self):
        """viewer_session.jsonは一時ファイルから置換され、有効なJSONとして残る。"""
        state = self.app.write_session({
            "video": "abc.mp4",
            "frame_index": 3,
            "yaw_to_camera_heading": 45.0,
            "pitch": 0.0,
            "zoom": 1.0,
        })

        session_path = self.app.load_config()["session_json_path"]
        self.assertTrue(session_path.is_file())
        self.assertFalse(session_path.with_name(f"{session_path.name}.tmp").exists())
        stored = json.loads(session_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["video"], "abc.mp4")
        self.assertEqual(stored["frame_index"], 3)
        self.assertEqual(stored["viewer_camera_height_m"], 1.5)
        self.assertEqual(stored["viewer_hud_height_scale"], 1.0)
        self.assertIn("updated_at", stored)
        self.assertEqual(state, stored)

    def test_request_args_accepts_camera_height_from_url(self):
        """初回表示URLのカメラ高さをviewer_session.jsonへ引き渡す。"""
        state = self.app.state_from_request_args({
            "viewer_camera_height_m": ["2.3"],
            "viewer_hud_height_scale": ["1.3"],
        }, "abc.mp4", 8)

        self.assertEqual(state["video"], "abc.mp4")
        self.assertEqual(state["frame_index"], 8)
        self.assertEqual(state["viewer_camera_height_m"], 2.3)
        self.assertEqual(state["viewer_hud_height_scale"], 1.3)

    def test_request_args_preserves_camera_height_from_existing_session(self):
        """既存ジョブsessionのカメラ高さを初回表示状態へ復元する。"""
        self.app.write_session({
            "video": "abc.mp4",
            "frame_index": 7,
            "yaw_to_camera_heading": 0.0,
            "pitch": 0.0,
            "zoom": 1.0,
            "viewer_camera_height_m": 1.9,
            "viewer_hud_height_scale": 1.25,
        })

        state = self.app.state_from_request_args({}, "abc.mp4", 8)

        self.assertEqual(state["viewer_camera_height_m"], 1.9)
        self.assertEqual(state["viewer_hud_height_scale"], 1.25)

    def test_navigation_payload_preserves_existing_view_when_omitted(self):
        """QGISナビゲーションpayloadが視点値やカメラ高を省略した場合は直近値を継承する。"""
        self.app.write_session({
            "video": "abc.mp4",
            "frame_index": 10,
            "yaw_to_camera_heading": 88.0,
            "pitch": -12.0,
            "zoom": 1.5,
            "viewer_camera_height_m": 1.8,
            "viewer_hud_height_scale": 1.2,
        })

        state = self.app.state_from_navigation_payload({
            "video": "abc.mp4",
            "frame_index": 11,
        })

        self.assertEqual(state["frame_index"], 11)
        self.assertEqual(state["yaw_to_camera_heading"], 88.0)
        self.assertEqual(state["pitch"], -12.0)
        self.assertEqual(state["zoom"], 1.5)
        self.assertEqual(state["viewer_camera_height_m"], 1.8)
        self.assertEqual(state["viewer_hud_height_scale"], 1.2)

    def test_navigation_payload_accepts_camera_height_from_qgis(self):
        """QGISから渡されたカメラ高さをviewer_session.jsonへ保存する。"""
        state = self.app.state_from_navigation_payload({
            "video": "abc.mp4",
            "frame_index": 11,
            "viewer_camera_height_m": "2.4",
            "viewer_hud_height_scale": "1.3",
        })

        self.assertEqual(state["viewer_camera_height_m"], 2.4)
        self.assertEqual(state["viewer_hud_height_scale"], 1.3)

    def test_navigation_payload_accepts_restored_targets_from_qgis(self):
        """QGISから渡された保存済みクリック点をviewer_session.jsonへ復元する。"""
        state = self.app.state_from_navigation_payload({
            "video": "abc.mp4",
            "frame_index": 11,
            "targets": [
                {
                    "id": 2,
                    "order": 2,
                    "yaw_delta_deg": -6,
                    "target_yaw_to_camera_heading": 82,
                    "target_pitch_deg": -4,
                    "view_yaw_to_camera_heading": 88,
                    "view_pitch": -2,
                    "view_zoom": 1.5,
                },
            ],
        })

        self.assertEqual(len(state["targets"]), 1)
        self.assertEqual(state["target"], state["targets"][0])
        self.assertEqual(state["targets"][0]["id"], 2)
        self.assertEqual(state["targets"][0]["x_ratio"], 0.5)

    def test_navigation_payload_preserves_detection_candidate_metadata(self):
        """YOLO候補targetの確認用メタデータをviewer_session.jsonへ残す。"""
        state = self.app.state_from_navigation_payload({
            "video": "abc.mp4",
            "frame_index": 11,
            "targets": [
                {
                    "id": 1,
                    "order": 1,
                    "yaw_delta_deg": 0,
                    "target_yaw_to_camera_heading": 82,
                    "target_pitch_deg": -4,
                    "view_yaw_to_camera_heading": 82,
                    "view_pitch": -4,
                    "view_zoom": 1.35,
                    "projection": "direction_only",
                    "quality": "direction_only",
                    "target_source": "yolo_candidate",
                    "viewer_marker": "target_point",
                    "candidate_id": "target_001",
                    "semantic_class": "traffic_sign",
                    "confidence": "0.87",
                    "review_status": "candidate",
                },
            ],
        })

        target = state["targets"][0]
        self.assertEqual(target["projection"], "direction_only")
        self.assertEqual(target["quality"], "direction_only")
        self.assertEqual(target["target_source"], "yolo_candidate")
        self.assertEqual(target["viewer_marker"], "target_point")
        self.assertEqual(target["candidate_id"], "target_001")
        self.assertEqual(target["semantic_class"], "traffic_sign")
        self.assertEqual(target["confidence"], 0.87)
        self.assertEqual(target["review_status"], "candidate")


if __name__ == "__main__":
    unittest.main()
