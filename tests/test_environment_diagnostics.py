"""Environment reports must survive missing dependencies and omit ownership tokens."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch


spec = importlib.util.spec_from_file_location(
    "environment_diagnostics_under_test",
    Path(__file__).resolve().parents[1] / "environment_diagnostics.py",
)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class EnvironmentDiagnosticTests(unittest.TestCase):
    def fake_cv2(self):
        return SimpleNamespace(
            __version__="4.8.0", __file__="/example/cv2.so", CAP_PROP_N_THREADS=70,
            getBuildInformation=lambda: "  Video I/O:\n    FFMPEG: YES\n      avcodec: 60.31\n\n"
                                        "  Parallel framework: TBB\n  Other: not needed\n",
            getNumThreads=lambda: 20, VideoCapture=Mock(),
        )

    def test_build_information_is_not_confused_with_decoder_thread_count(self):
        cv2 = self.fake_cv2()
        with patch.dict(sys.modules, {"cv2": cv2}), patch("builtins.open", mock_open(read_data="")):
            data = diagnostics.collect_environment()
        info = data["opencv"]
        self.assertIn("avcodec: 60.31", info["video_io_build"])
        self.assertNotIn("Parallel", info["video_io_build"])
        self.assertEqual(info["configured_decoder_thread_limit"], 8)
        self.assertEqual(info["opencv_processing_threads"], 20)
        cv2.VideoCapture.assert_not_called()

    def test_legacy_build_does_not_claim_enforced_thread_limit(self):
        cv2 = self.fake_cv2()
        del cv2.CAP_PROP_N_THREADS
        with patch.dict(sys.modules, {"cv2": cv2}), patch("builtins.open", mock_open(read_data="")):
            data = diagnostics.collect_environment()
        self.assertFalse(data["opencv"]["decoder_thread_api"])
        self.assertIsNone(data["opencv"]["configured_decoder_thread_limit"])

    def test_missing_opencv_and_proc_maps_still_produce_report(self):
        with patch.dict(sys.modules, {"cv2": None}), patch("builtins.open", side_effect=OSError):
            data = diagnostics.collect_environment()
        self.assertIn("error", data["opencv"])
        self.assertIn("python", data)
        self.assertIn("unavailable", data["loaded_video_libraries"])

    def test_loaded_video_libraries_are_deduplicated(self):
        maps = "1 2 3 /lib/libavcodec.so.60\n1 2 3 /lib/libavcodec.so.60\n1 2 3 /lib/other.so\n"
        with patch.dict(sys.modules, {"cv2": self.fake_cv2()}), \
                patch("builtins.open", mock_open(read_data=maps)):
            data = diagnostics.collect_environment()
        self.assertEqual(data["loaded_video_libraries"], ["/lib/libavcodec.so.60"])

    def test_only_selected_environment_variables_are_collected(self):
        with patch.dict(diagnostics.os.environ, {"SECRET_TOKEN": "secret", "GEO360_PROBE_THREADS": "8"}), \
                patch.dict(sys.modules, {"cv2": None}):
            data = diagnostics.collect_environment()
        self.assertNotIn("SECRET_TOKEN", data["environment"])
        self.assertEqual(data["environment"]["GEO360_PROBE_THREADS"], "8")

    def test_viewer_identity_excludes_owner_token_and_config(self):
        responses = []
        for payload in ({"app": "360viewer", "pid": 42, "owner_token": "private", "config": "job.json"},
                        {"pid": 42, "opencv": {"version": "4.6.0"}}):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = json.dumps(payload).encode()
            responses.append(response)
        with patch.object(diagnostics, "urlopen", side_effect=responses):
            data = diagnostics.collect_viewer_environment("http://127.0.0.1:8182")
        self.assertEqual(data["environment"]["opencv"]["version"], "4.6.0")
        self.assertNotIn("owner_token", data["identity"])
        self.assertNotIn("config", data["identity"])

    def test_unreachable_viewer_is_reported_without_aborting(self):
        with patch.object(diagnostics, "urlopen", side_effect=OSError("connection refused")):
            data = diagnostics.collect_viewer_environment("http://127.0.0.1:8182")
        self.assertIn("connection refused", data["environment"]["unavailable"])

    def test_format_preserves_original_data_and_readable_build_text(self):
        data = {"current_process": {"opencv": {"video_io_build": "FFMPEG: YES\navcodec: 60"}}}
        text = diagnostics.format_environment_report(data)
        self.assertIn("```json", text)
        self.assertIn("FFMPEG: YES\navcodec: 60", text)
        self.assertIn("video_io_build", data["current_process"]["opencv"])

    def test_console_entry_point_inspects_enabled_plugin_server(self):
        plugin = SimpleNamespace(viewerBaseUrl=lambda: "http://127.0.0.1:8182")
        output = io.StringIO()
        with patch.dict(sys.modules, {"qgis.utils": SimpleNamespace(plugins={"Geo360View": plugin})}), \
                patch.object(diagnostics, "collect_environment", return_value={"pid": 1}), \
                patch.object(diagnostics, "collect_viewer_startup", return_value={}), \
                patch.object(diagnostics, "collect_viewer_environment", return_value={"environment": {"pid": 2}}) as collect, \
                contextlib.redirect_stdout(output):
            diagnostics.print_environment_report()
        collect.assert_called_once_with("http://127.0.0.1:8182")
        self.assertIn('"pid": 1', output.getvalue())
        self.assertIn('"pid": 2', output.getvalue())

    def test_startup_report_compares_live_process_and_direct_server_without_token(self):
        process = SimpleNamespace(processId=lambda: 34404, errorString=lambda: "Unknown error")
        plugin = SimpleNamespace(viewer_process=process, _viewer_owner_token="private",
                                 viewerProcessRunning=lambda: True,
                                 viewerPythonCommand=lambda: ("python.exe", [], "python.exe"),
                                 viewerHealth=lambda: False,
                                 viewerBaseUrl=lambda: "http://127.0.0.1:8182")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"app": "360viewer", "status": "ok",
                                                "pid": 34404, "owner_token": "private"}).encode()
        with patch.object(diagnostics, "build_opener", return_value=SimpleNamespace(open=lambda *args, **kw: response)):
            data = diagnostics.collect_viewer_startup(plugin)
        self.assertEqual(data["managed_pid"], 34404)
        self.assertFalse(data["plugin_health_check"])
        self.assertTrue(data["direct_owner_matches"])
        self.assertNotIn("private", json.dumps(data))

    def test_startup_report_keeps_process_state_when_http_is_refused(self):
        plugin = SimpleNamespace(viewer_process=None, viewerProcessRunning=lambda: False,
                                 viewerPythonCommand=lambda: ("python.exe", [], "python.exe"),
                                 viewerHealth=lambda: False,
                                 viewerBaseUrl=lambda: "http://127.0.0.1:8182")
        opener = SimpleNamespace(open=Mock(side_effect=OSError("connection refused")))
        with patch.object(diagnostics, "build_opener", return_value=opener):
            data = diagnostics.collect_viewer_startup(plugin)
        self.assertFalse(data["managed_process_running"])
        self.assertIn("connection refused", data["direct_health"]["unavailable"])


if __name__ == "__main__":
    unittest.main()
