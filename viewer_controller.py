import importlib
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl

from .common import _looks_like_python_launcher
from .constants import PLUGIN_TITLE


class ViewerControllerMixin:
    def viewerDir(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "360viewer")

    def viewerAppPath(self):
        return os.path.join(self.viewerDir(), "app.py")

    def viewerRuntimeConfigPath(self):
        return os.path.join(self.viewerDir(), "viewer_config.qgis_runtime.json")

    def viewerSessionPath(self):
        return os.path.join(self.resolvedOutputDir(), "viewer_session.json")

    def viewerCacheDir(self):
        return os.path.join(self.resolvedOutputDir(), "viewer_cache")

    def viewerVideoDir(self):
        if self.video_file:
            return os.path.dirname(os.path.abspath(self.video_file))
        return os.path.join(self.viewerDir(), "sample_videos")

    def loadViewerDefaults(self):
        config_path = os.path.join(self.viewerDir(), "viewer_config.json")
        host = "127.0.0.1"
        port = 8181
        jpeg_quality = 70
        progressive_jpeg = True
        max_width = 3072
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            host = config.get("host", host)
            port = int(config.get("port", port))
            jpeg_quality = max(1, min(100, int(config.get("viewer_jpeg_quality", jpeg_quality))))
            progressive_jpeg = self.parseViewerBool(
                config.get("viewer_progressive_jpeg", progressive_jpeg)
            )
            max_width = max(0, int(config.get("viewer_max_width", max_width)))
        except Exception:
            pass
        self.viewer_host = host
        self.viewer_port = port
        self.viewer_jpeg_quality = jpeg_quality
        self.viewer_progressive_jpeg = progressive_jpeg
        self.viewer_max_width = max_width
        return host, port

    def parseViewerBool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return False

    def writeViewerRuntimeConfig(self, show_error=True):
        host, port = self.loadViewerDefaults()
        config = {
            "host": host,
            "port": port,
            "video_dir": self.viewerVideoDir(),
            "session_json_path": self.viewerSessionPath(),
            "viewer_jpeg_quality": self.viewer_jpeg_quality,
            "viewer_progressive_jpeg": self.viewer_progressive_jpeg,
            "viewer_max_width": self.viewer_max_width,
            "viewer_cache_dir": self.viewerCacheDir(),
        }

        try:
            with open(self.viewerRuntimeConfigPath(), "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return True
        except OSError as e:
            if show_error:
                self.iface.messageBar().pushWarning(
                    PLUGIN_TITLE,
                    f"Failed to write 360Viewer config: {e}"
                )
            return False

    def viewerBaseUrl(self):
        self.loadViewerDefaults()
        return f"http://{self.viewer_host}:{self.viewer_port}"

    def viewerUrl(self, frame_num=None):
        base_url = self.viewerBaseUrl()
        if frame_num is None or not self.video_file:
            return base_url

        query = urlencode({
            "video": os.path.basename(self.video_file),
            "frame_index": int(frame_num),
        })
        return f"{base_url}/viewer?{query}"

    def viewerHealth(self, timeout=0.4):
        try:
            with urlopen(f"{self.viewerBaseUrl()}/api/health", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("app") == "360viewer"
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            return False

    def viewerProcessRunning(self):
        if self.viewer_process is None:
            return False
        return self.viewer_process.state() != QProcess.NotRunning

    def checkViewerDependencies(self):
        missing = []
        for module_name in ("cv2",):
            try:
                importlib.import_module(module_name)
            except ImportError:
                missing.append(module_name)

        if missing:
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                "360Viewer dependencies are not available in QGIS Python: "
                + ", ".join(missing)
            )
            return False
        return True

    def viewerPythonCandidates(self):
        candidates = []
        seen = set()

        def add(path):
            if not path:
                return
            path = os.path.abspath(str(path))
            key = os.path.normcase(path)
            if key in seen:
                return
            seen.add(key)
            candidates.append(path)

        add(sys.executable)
        add(getattr(sys, "_base_executable", ""))

        executable_dir = os.path.dirname(os.path.abspath(sys.executable))
        for name in ("python.exe", "python3.exe", "python-qgis.bat", "python-qgis-ltr.bat"):
            add(os.path.join(executable_dir, name))

        prefixes = [
            getattr(sys, "exec_prefix", ""),
            getattr(sys, "base_exec_prefix", ""),
            getattr(sys, "prefix", ""),
            getattr(sys, "base_prefix", ""),
        ]
        for prefix in prefixes:
            if not prefix:
                continue
            add(os.path.join(prefix, "python.exe"))
            add(os.path.join(prefix, "python3.exe"))
            add(os.path.join(prefix, "Scripts", "python.exe"))

            root = os.path.dirname(os.path.dirname(os.path.abspath(prefix)))
            for name in ("python.exe", "python3.exe", "python-qgis.bat", "python-qgis-ltr.bat"):
                add(os.path.join(root, "bin", name))

        return candidates

    def viewerPythonCommand(self):
        for candidate in self.viewerPythonCandidates():
            if not _looks_like_python_launcher(candidate):
                continue
            if not os.path.isfile(candidate):
                continue

            name = os.path.basename(candidate).lower()
            if name.endswith(".bat") or name.endswith(".cmd"):
                return os.environ.get("COMSPEC", "cmd.exe"), ["/c", candidate], candidate
            return candidate, [], candidate

        return None, [], None

    def reportViewerStatus(self):
        if self.viewerHealth():
            self.iface.messageBar().pushMessage(
                PLUGIN_TITLE,
                f"360Viewer is running: {self.viewerBaseUrl()}"
            )
        else:
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                "360Viewer is not running. Use 360ViewerOpen from the plugin menu."
            )

    def ensureViewerStarted(self):
        if not self.writeViewerRuntimeConfig():
            return False
        if self.viewerHealth():
            return True
        if self.viewerProcessRunning():
            return True
        if not self.checkViewerDependencies():
            return False
        if not os.path.isfile(self.viewerAppPath()):
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                f"360Viewer app.py was not found: {self.viewerAppPath()}"
            )
            return False

        python_program, python_args, python_display = self.viewerPythonCommand()
        if not python_program:
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                "Could not find a Python launcher for 360Viewer. "
                f"sys.executable is {sys.executable}"
            )
            return False

        self.viewer_process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("VIEWER_CONFIG", self.viewerRuntimeConfigPath())
        self.viewer_process.setProcessEnvironment(environment)
        self.viewer_process.setWorkingDirectory(self.viewerDir())
        self.viewer_process.readyReadStandardError.connect(self.logViewerStderr)
        self.viewer_process.readyReadStandardOutput.connect(self.logViewerStdout)
        self.viewer_process.finished.connect(self.onViewerFinished)
        self.viewer_process.errorOccurred.connect(self.onViewerProcessError)
        self.viewer_process.start(python_program, python_args + [self.viewerAppPath()])

        if not self.viewer_process.waitForStarted(3000):
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                "Failed to start 360Viewer process."
            )
            self.viewer_process = None
            return False

        self.iface.messageBar().pushMessage(
            PLUGIN_TITLE,
            f"360Viewer starting: {self.viewerBaseUrl()} ({python_display})"
        )
        return True

    def logViewerStdout(self):
        if not self.viewer_process:
            return
        text = bytes(self.viewer_process.readAllStandardOutput()).decode("utf-8", "replace").strip()
        if text:
            print(f"360Viewer stdout: {text}")

    def logViewerStderr(self):
        if not self.viewer_process:
            return
        text = bytes(self.viewer_process.readAllStandardError()).decode("utf-8", "replace").strip()
        if text:
            print(f"360Viewer stderr: {text}")

    def onViewerFinished(self, exit_code, exit_status):
        print(f"360Viewer finished: exit_code={exit_code}, exit_status={exit_status}")
        self.viewer_process = None
        self.viewer_browser_opened = False

    def onViewerProcessError(self, error):
        print(f"360Viewer process error: {error}")

    def openViewer(self):
        self.startViewerSessionPolling()
        frame_num = self.extract_frame.value() if self.video_file else None
        if not self.ensureViewerStarted():
            return
        self.openViewerWhenReady(frame_num)

    def openViewerWhenReady(self, frame_num=None, attempts=20):
        if self.viewerHealth(timeout=0.25):
            opens_viewer_page = frame_num is not None and bool(self.video_file)
            if opens_viewer_page:
                self.postViewerNavigation(frame_num)
            url = self.viewerUrl(frame_num)
            QtGui.QDesktopServices.openUrl(QUrl(url))
            self.viewer_browser_opened = opens_viewer_page
            self.iface.messageBar().pushMessage(PLUGIN_TITLE, f"360Viewer opened: {url}")
            return

        if attempts <= 0:
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                f"360Viewer did not respond: {self.viewerBaseUrl()}"
            )
            return

        QTimer.singleShot(250, lambda: self.openViewerWhenReady(frame_num, attempts - 1))

    def postViewerNavigation(self, frame_num):
        if not self.video_file:
            return False

        payload = {
            "video": os.path.basename(self.video_file),
            "frame_index": int(frame_num),
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.viewerBaseUrl()}/api/session/navigate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=1.0):
                return True
        except (HTTPError, URLError, OSError) as e:
            print(f"360Viewer navigation failed: {e}")
            return False

    def showFrameInViewer(self, frame_num):
        if not self.video_file:
            return
        self.startViewerSessionPolling()
        if not self.ensureViewerStarted():
            return

        if not self.viewerHealth(timeout=0.25):
            self.openViewerWhenReady(frame_num)
            return

        if self.viewer_browser_opened and self.postViewerNavigation(frame_num):
            self.iface.messageBar().pushMessage(
                PLUGIN_TITLE,
                f"360Viewer frame updated: {frame_num}"
            )
            return

        self.openViewerWhenReady(frame_num)

    def stopViewerProcess(self):
        if not self.viewerProcessRunning():
            return

        process = self.viewer_process
        process.terminate()
        if not process.waitForFinished(2000):
            process.kill()
            process.waitForFinished(1000)
        if self.viewer_process is process:
            self.viewer_process = None
        self.viewer_browser_opened = False
