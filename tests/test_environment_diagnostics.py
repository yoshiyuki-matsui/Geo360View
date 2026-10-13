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
    def test_diagnostics_reject_nonlocal_or_non_http_urls_before_connecting(self):
        urls = (
            "file:///tmp/report", "ftp://127.0.0.1:8182", "https://127.0.0.1:8182",
            "http://example.com:8182", "http://192.168.0.1:8182",
            "http://user:password@127.0.0.1:8182", "http://127.0.0.1:8182/path",
            "http://127.0.0.1:8182?redirect=example.com", "http://127.0.0.1:8182#fragment",
            "http://127.0.0.1:0", "http://127.0.0.1:65536",
        )
        with patch.object(diagnostics, "HTTPConnection") as connect:
            for url in urls:
                with self.subTest(url=url):
                    report = diagnostics.collect_viewer_environment(url)
                    self.assertIn("unavailable", report["identity"])
                    self.assertIn("unavailable", report["environment"])
            connect.assert_not_called()

    def connection(self, status=200, data=b'{"pid": 42}'):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = data
        return connection

    def test_local_http_uses_fixed_endpoint_and_closes_connection(self):
        for url, host in (("http://127.0.0.1:8182", "127.0.0.1"),
                          ("http://localhost:8182/", "127.0.0.1"),
                          ("http://[::1]:8182", "::1")):
            with self.subTest(url=url):
                connection = self.connection()
                with patch.object(diagnostics, "HTTPConnection", return_value=connection) as connect:
                    self.assertEqual(diagnostics._read_local_viewer_json(url, "health"), {"pid": 42})
                connect.assert_called_once_with(host, 8182, timeout=1)
                connection.request.assert_called_once_with("GET", "/api/health")
                connection.close.assert_called_once()

    def test_http_redirect_is_rejected_without_following_location(self):
        connection = self.connection(status=302)
        connection.getresponse.return_value.getheader.return_value = "http://example.com"
        with patch.object(diagnostics, "HTTPConnection", return_value=connection) as connect:
            with self.assertRaisesRegex(ValueError, "redirects are not followed"):
                diagnostics._read_local_viewer_json("http://127.0.0.1:8182", "health")
        connect.assert_called_once()
        connection.getresponse.return_value.read.assert_not_called()
        connection.close.assert_called_once()

    def test_oversized_or_non_object_diagnostics_are_rejected(self):
        for data in (b"x" * (diagnostics.DIAGNOSTIC_RESPONSE_LIMIT + 1), b"[]"):
            connection = self.connection(data=data)
            with patch.object(diagnostics, "HTTPConnection", return_value=connection):
                with self.assertRaises(ValueError):
                    diagnostics._read_local_viewer_json("http://127.0.0.1:8182", "diagnostics")
            connection.close.assert_called_once()

    def test_arbitrary_endpoint_is_rejected_before_connecting(self):
        with patch.object(diagnostics, "HTTPConnection") as connect:
            with self.assertRaises(ValueError):
                diagnostics._read_local_viewer_json("http://127.0.0.1:8182", "../secret")
            connect.assert_not_called()

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
        responses = [{"app": "360viewer", "pid": 42, "owner_token": "private", "config": "job.json"},
                     {"pid": 42, "opencv": {"version": "4.6.0"}}]
        with patch.object(diagnostics, "_read_local_viewer_json", side_effect=responses):
            data = diagnostics.collect_viewer_environment("http://127.0.0.1:8182")
        self.assertEqual(data["environment"]["opencv"]["version"], "4.6.0")
        self.assertNotIn("owner_token", data["identity"])
        self.assertNotIn("config", data["identity"])

    def test_unreachable_viewer_is_reported_without_aborting(self):
        with patch.object(diagnostics, "_read_local_viewer_json", side_effect=OSError("connection refused")):
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
        payload = {"app": "360viewer", "status": "ok", "pid": 34404, "owner_token": "private"}
        with patch.object(diagnostics, "_read_local_viewer_json", return_value=payload):
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
        with patch.object(diagnostics, "_read_local_viewer_json", side_effect=OSError("connection refused")):
            data = diagnostics.collect_viewer_startup(plugin)
        self.assertFalse(data["managed_process_running"])
        self.assertIn("connection refused", data["direct_health"]["unavailable"])


if __name__ == "__main__":
    unittest.main()
