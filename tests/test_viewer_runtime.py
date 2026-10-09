"""Regression checks for stale-server rejection and owned-process cleanup."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from viewer_runtime import matching_server, server_build


ROOT = Path(__file__).resolve().parents[1]


def controller_methods(*names):
    tree = ast.parse((ROOT / "viewer_controller.py").read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    namespace = {"matching_server": matching_server}
    module = ast.Module(body=[node for node in owner.body
                             if isinstance(node, ast.FunctionDef) and node.name in names],
                        type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "viewer_controller.py", "exec"), namespace)
    return namespace


class ViewerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.root = Path(self.context.name)
        (self.root / "360viewer").mkdir()
        self.app = self.root / "360viewer" / "app.py"
        for path in (self.app, self.root / "video_frames.py", self.root / "viewer_runtime.py"):
            path.write_text("original", encoding="utf-8")
        self.config = self.root / "runtime.json"
        self.payload = dict(app="360viewer", status="ok", app_path=str(self.app),
                            config=str(self.config), owner_token="owned",
                            server_build=server_build(self.app))

    def matches(self):
        return matching_server(self.payload, self.app, self.config, "owned")

    def test_owned_current_server_matches(self):
        self.assertTrue(self.matches())

    def test_old_health_payload_is_rejected(self):
        self.payload = dict(app="360viewer", status="ok", config=str(self.config))
        self.assertFalse(self.matches())

    def test_separate_instance_is_rejected(self):
        self.payload["owner_token"] = "another-instance"
        self.assertFalse(self.matches())

    def test_different_plugin_is_rejected(self):
        self.payload["app_path"] = str(self.root / "GPXVideoProcessor" / "app.py")
        self.assertFalse(self.matches())

    def test_different_config_is_rejected(self):
        self.payload["config"] = str(self.root / "other.json")
        self.assertFalse(self.matches())

    def test_replaced_reader_rejects_already_running_generation(self):
        (self.root / "video_frames.py").write_text("updated", encoding="utf-8")
        self.assertFalse(self.matches())

    def test_replaced_server_rejects_already_running_generation(self):
        self.app.write_text("updated", encoding="utf-8")
        self.assertFalse(self.matches())

    def test_unknown_owner_is_rejected(self):
        self.assertFalse(matching_server(self.payload, self.app, self.config, None))


class ViewerStopTests(unittest.TestCase):
    def test_launch_selects_parent_pipe_monitoring_for_platform(self):
        for platform_name, expected in (("nt", "0"), ("posix", "1")):
            with self.subTest(platform=platform_name):
                environment = Mock()
                process = Mock()
                process.waitForStarted.return_value = True
                target = SimpleNamespace(
                    loadViewerSessionCameraHeight=lambda: None,
                    viewerHealthPayload=lambda: None, viewerHealth=lambda: False,
                    writeViewerRuntimeConfig=lambda: True, viewerProcessRunning=lambda: False,
                    checkViewerDependencies=lambda: True, viewerAppPath=lambda: "app.py",
                    viewerRuntimeConfigPath=lambda: "runtime.json", viewerDir=lambda: "viewer",
                    viewerPythonCommand=lambda: ("python.exe", [], "python.exe"),
                    viewerBaseUrl=lambda: "http://127.0.0.1:8182",
                    logViewerStderr=Mock(), logViewerStdout=Mock(),
                    onViewerFinished=Mock(), onViewerProcessError=Mock(),
                    iface=SimpleNamespace(messageBar=lambda: Mock()),
                )
                namespace = controller_methods("ensureViewerStarted")
                namespace.update(
                    os=SimpleNamespace(name=platform_name, path=SimpleNamespace(isfile=lambda path: True)),
                    uuid=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="owned")),
                    QProcess=Mock(return_value=process),
                    QProcessEnvironment=SimpleNamespace(systemEnvironment=lambda: environment),
                    PLUGIN_TITLE="Geo360View",
                )
                self.assertTrue(namespace["ensureViewerStarted"](target))
                environment.insert.assert_any_call("VIEWER_WATCH_STDIN", expected)
                environment.insert.assert_any_call("VIEWER_OWNER_TOKEN", "owned")
                process.start.assert_called_once_with("python.exe", ["app.py"])

    def stop(self, results):
        process = Mock()
        process.waitForFinished.side_effect = results
        warnings = Mock()
        target = SimpleNamespace(viewer_process=process, viewer_browser_opened=True,
                                 viewerProcessRunning=lambda: True,
                                 iface=SimpleNamespace(messageBar=lambda: warnings))
        method = controller_methods("stopViewerProcess")
        method["PLUGIN_TITLE"] = "Geo360View"
        method["stopViewerProcess"](target)
        return target, process, warnings

    def test_pipe_close_allows_graceful_exit(self):
        target, process, _ = self.stop([True])
        process.closeWriteChannel.assert_called_once()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        self.assertIsNone(target.viewer_process)

    def test_stop_escalates_when_server_is_unresponsive(self):
        target, process, _ = self.stop([False, False, True])
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertIsNone(target.viewer_process)

    def test_failed_kill_keeps_reference_and_warns(self):
        target, process, warnings = self.stop([False, False, False])
        self.assertIs(target.viewer_process, process)
        warnings.pushWarning.assert_called_once()

    def test_no_owned_process_is_not_killed(self):
        target = SimpleNamespace(viewerProcessRunning=lambda: False)
        controller_methods("stopViewerProcess")["stopViewerProcess"](target)

    def test_stale_server_is_rejected_before_rewriting_runtime_config(self):
        writes = Mock()
        warnings = Mock()
        target = SimpleNamespace(loadViewerSessionCameraHeight=lambda: None,
                                 viewerHealthPayload=lambda: {"app": "360viewer"},
                                 viewerHealth=lambda: False,
                                 writeViewerRuntimeConfig=writes,
                                 viewerBaseUrl=lambda: "http://127.0.0.1:8182",
                                 iface=SimpleNamespace(messageBar=lambda: warnings))
        namespace = controller_methods("ensureViewerStarted")
        namespace["PLUGIN_TITLE"] = "Geo360View"
        self.assertFalse(namespace["ensureViewerStarted"](target))
        writes.assert_not_called()
        warnings.pushWarning.assert_called_once()

    def test_server_main_exits_when_owner_pipe_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"host": "127.0.0.1", "port": 0,
                                          "video_dir": directory}), encoding="utf-8")
            environment = dict(os.environ, VIEWER_CONFIG=str(config), VIEWER_WATCH_STDIN="1")
            # Exercise the real subprocess stdin and app.main lifetime. Replace
            # only the network server because sandbox runners may forbid bind.
            script = """
import importlib.util
import sys
import threading
spec = importlib.util.spec_from_file_location('viewer_pipe_test', sys.argv[1])
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
class Server:
    def __init__(self, *args):
        self.stopped = threading.Event()
    def serve_forever(self):
        self.stopped.wait()
    def shutdown(self):
        self.stopped.set()
    def server_close(self):
        pass
app.ThreadingHTTPServer = Server
app.main()
"""
            process = subprocess.Popen([sys.executable, "-c", script,
                                        str(ROOT / "360viewer" / "app.py")],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=environment)
            try:
                line = process.stdout.readline()
                self.assertIn(b"360Viewer serving", line,
                              process.stderr.read().decode() if not line else "")
                process.stdin.close()
                process.wait(timeout=5)
                self.assertEqual(process.returncode, 0, process.stderr.read().decode())
                self.assertIn(b"owner input pipe closed", process.stdout.read())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
                if not process.stdin.closed:
                    process.stdin.close()


if __name__ == "__main__":
    unittest.main()
