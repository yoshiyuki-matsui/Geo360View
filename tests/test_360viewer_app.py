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
            },
        })

        self.assertEqual(state["frame_index"], 12)
        self.assertEqual(state["yaw_to_camera_heading"], 10.0)
        self.assertEqual(state["pitch"], -3.5)
        self.assertEqual(state["zoom"], 2.0)
        self.assertEqual(state["target"]["x_ratio"], 1.0)
        self.assertEqual(state["target"]["y_ratio"], 0.0)
        self.assertEqual(state["target"]["yaw_delta_deg"], -170.0)
        self.assertEqual(state["target"]["pitch_delta_deg"], 90.0)
        self.assertEqual(state["target"]["target_yaw_to_camera_heading"], 350.0)
        self.assertEqual(state["target"]["view_yaw_to_camera_heading"], 5.0)
        self.assertEqual(state["target"]["view_pitch"], -90.0)
        self.assertEqual(state["target"]["view_zoom"], 0.01)
        self.assertEqual(state["target"]["projection"], "center_plane")

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
        self.assertIn("updated_at", stored)
        self.assertEqual(state, stored)

    def test_navigation_payload_preserves_existing_view_when_omitted(self):
        """QGISナビゲーションpayloadが視点値を省略した場合は直近視点を継承する。"""
        self.app.write_session({
            "video": "abc.mp4",
            "frame_index": 10,
            "yaw_to_camera_heading": 88.0,
            "pitch": -12.0,
            "zoom": 1.5,
        })

        state = self.app.state_from_navigation_payload({
            "video": "abc.mp4",
            "frame_index": 11,
        })

        self.assertEqual(state["frame_index"], 11)
        self.assertEqual(state["yaw_to_camera_heading"], 88.0)
        self.assertEqual(state["pitch"], -12.0)
        self.assertEqual(state["zoom"], 1.5)


if __name__ == "__main__":
    unittest.main()
