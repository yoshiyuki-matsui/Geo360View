"""QGISプラグインからローカル360Viewerを起動・制御するMixin。"""

import importlib
import json
import os
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl

from .common import _looks_like_python_launcher
from .constants import PLUGIN_TITLE


class ViewerControllerMixin:
    """360Viewerプロセス、HTTP API、外部ブラウザ起動をまとめて扱う。"""

    def viewerDir(self):
        """360Viewerアプリケーションディレクトリを返す。"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "360viewer")

    def viewerAppPath(self):
        """360ViewerのHTTPサーバ実装ファイルを返す。"""
        return os.path.join(self.viewerDir(), "app.py")

    def viewerRuntimeConfigPath(self):
        """QGIS実行時に生成するビューア設定JSONのパスを返す。"""
        return os.path.join(self.viewerDir(), "viewer_config.qgis_runtime.json")

    def viewerSessionPath(self):
        """WEBビューアとQGISが共有する視点状態JSONのパスを返す。"""
        return os.path.join(self.resolvedOutputDir(), "viewer_session.json")

    def viewerCommandPath(self):
        """QGISからWEBビューアへ送る表示指示JSONのパスを返す。"""
        return os.path.join(self.resolvedOutputDir(), "viewer_command.json")

    def viewerCacheDir(self):
        """WEBビューア専用の軽量JPEGキャッシュディレクトリを返す。"""
        return os.path.join(self.resolvedOutputDir(), "viewer_cache")

    def viewerVideoDir(self):
        """ビューアが参照できる動画ディレクトリを返す。"""
        if self.video_file:
            return os.path.dirname(os.path.abspath(self.video_file))
        return os.path.join(self.viewerDir(), "sample_videos")

    def loadViewerDefaults(self):
        """静的設定JSONからビューア既定値を読み込み、plugin状態へ反映する。"""
        config_path = os.path.join(self.viewerDir(), "viewer_config.json")
        host = "127.0.0.1"
        port = 8181
        jpeg_quality = 70
        progressive_jpeg = True
        max_width = 3072
        browser_app_window = True
        browser_path = ""
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
            browser_app_window = self.parseViewerBool(
                config.get("viewer_browser_app_window", browser_app_window)
            )
            browser_path = str(config.get("viewer_browser_path", browser_path) or "").strip()
        except Exception:
            pass
        self.viewer_host = host
        self.viewer_port = port
        self.viewer_jpeg_quality = jpeg_quality
        self.viewer_progressive_jpeg = progressive_jpeg
        self.viewer_max_width = max_width
        self.viewer_browser_app_window = browser_app_window
        self.viewer_browser_path = browser_path
        return host, port

    def parseViewerBool(self, value):
        """JSONや文字列由来の真偽値を安全にboolへ変換する。"""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return False

    def writeViewerRuntimeConfig(self, show_error=True):
        """現在の動画/出力先に合わせたビューア実行時設定を書き出す。"""
        viewer_config = self.collectViewerConfig(show_errors=show_error)
        if viewer_config is None:
            return False

        config = {
            "host": viewer_config.host,
            "port": viewer_config.port,
            "video_dir": viewer_config.video_dir,
            "session_json_path": viewer_config.session_json_path,
            "command_json_path": self.viewerCommandPath(),
            "viewer_jpeg_quality": viewer_config.jpeg_quality,
            "viewer_progressive_jpeg": viewer_config.progressive_jpeg,
            "viewer_max_width": viewer_config.max_width,
            "viewer_cache_dir": viewer_config.cache_dir,
            "viewer_camera_height_m": viewer_config.camera_height_m,
            "viewer_hud_height_scale": viewer_config.hud_height_scale,
            "viewer_debug_log_enabled": self.viewerDebugLogEnabled(),
            "viewer_projection": self.viewerProjectionValue(),
            "viewer_flat_hfov_deg": self.viewerFlatHfovValue(),
            "viewer_flat_vfov_deg": self.viewerFlatVfovValue(),
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
        """現在設定のhost/portからビューア基底URLを組み立てる。"""
        self.loadViewerDefaults()
        return f"http://{self.viewer_host}:{self.viewer_port}"

    def viewerDebugLogEnabled(self):
        """プラグイン本体の詳細ログ設定を、Viewer制御側から参照する。"""
        checker = getattr(self, "debugLogEnabled", None)
        if callable(checker):
            return bool(checker())
        return False

    def viewerDebugPrint(self, message):
        """詳細ログON時だけQGIS Pythonコンソール側へ補助ログを出す。"""
        if self.viewerDebugLogEnabled():
            print(message)

    def viewerUrl(self, frame_num=None):
        """ブラウザで開くビューアURLを返す。フレーム指定なしならトップURL。"""
        base_url = self.viewerBaseUrl()
        if frame_num is None or not self.video_file:
            return base_url

        query = urlencode({
            "video": os.path.basename(self.video_file),
            "frame_index": int(frame_num),
            "viewer_camera_height_m": self.viewerCameraHeightValue(),
            "viewer_hud_height_scale": self.viewerHudHeightScaleValue(),
            "viewer_projection": self.viewerProjectionValue(),
            "viewer_flat_hfov_deg": self.viewerFlatHfovValue(),
            "viewer_flat_vfov_deg": self.viewerFlatVfovValue(),
        })
        return f"{base_url}/viewer?{query}"

    def browserCandidatePaths(self):
        """独立アプリ窓で開けるEdge/Chrome候補を返す。"""
        candidates = []

        def add(path):
            if path and path not in candidates:
                candidates.append(path)

        add(getattr(self, "viewer_browser_path", ""))
        for root in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LocalAppData"),
        ):
            if not root:
                continue
            add(os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"))
            add(os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"))
        return candidates

    def browserAppCommand(self):
        """アプリ窓起動に使うブラウザ実行ファイルを返す。"""
        for candidate in self.browserCandidatePaths():
            if os.path.isfile(candidate):
                return candidate
        return ""

    def openViewerUrl(self, url):
        """可能なら独立アプリ窓でビューアURLを開き、失敗時は既定ブラウザへ渡す。"""
        self.loadViewerDefaults()
        if getattr(self, "viewer_browser_app_window", True):
            browser = self.browserAppCommand()
            if browser:
                if QProcess.startDetached(browser, [f"--app={url}"]):
                    return True
        return QtGui.QDesktopServices.openUrl(QUrl(url))

    def viewerHealth(self, timeout=0.4):
        """ローカル360Viewerが応答しているかHTTP health APIで確認する。"""
        try:
            with urlopen(f"{self.viewerBaseUrl()}/api/health", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("app") == "360viewer"
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            return False

    def viewerProcessRunning(self):
        """このプラグインが起動したQProcessが生存しているか返す。"""
        if self.viewer_process is None:
            return False
        return self.viewer_process.state() != QProcess.NotRunning

    def checkViewerDependencies(self):
        """ビューア起動に必要なPythonモジュールがQGIS Pythonへ入っているか確認する。"""
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
        """360Viewer起動に使えそうなPythonランチャー候補を列挙する。"""
        candidates = []
        seen = set()

        def add(path):
            """重複を除いて候補パスを追加する。"""
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

        # QGISではsys.executableがqgis.exeを指す場合があるため、同階層のpythonを探す。
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
        """QProcess.startへ渡せるPython起動コマンドと表示名を決定する。"""
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
        """Start時に360Viewerの起動状態をQGISメッセージバーへ出す。"""
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
        """ビューア設定を書き出し、必要ならローカルHTTPサーバを起動する。"""
        self.loadViewerSessionCameraHeight()
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

        # QGISのプロセスと環境を共有しつつ、設定だけVIEWER_CONFIGで明示的に渡す。
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
        """360Viewer標準出力をQGIS Pythonコンソールへ中継する。"""
        if not self.viewer_process:
            return
        text = bytes(self.viewer_process.readAllStandardOutput()).decode("utf-8", "replace").strip()
        if text:
            print(f"360Viewer stdout: {text}")

    def logViewerStderr(self):
        """360Viewer標準エラーをQGIS Pythonコンソールへ中継する。"""
        if not self.viewer_process:
            return
        text = bytes(self.viewer_process.readAllStandardError()).decode("utf-8", "replace").strip()
        if text:
            print(f"360Viewer stderr: {text}")

    def onViewerFinished(self, exit_code, exit_status):
        """360Viewerプロセス終了時にプラグイン側状態をリセットする。"""
        print(f"360Viewer finished: exit_code={exit_code}, exit_status={exit_status}")
        self.viewer_process = None
        self.viewer_browser_opened = False

    def onViewerProcessError(self, error):
        """QProcess起動/実行エラーをログへ出す。"""
        print(f"360Viewer process error: {error}")

    def openViewer(self):
        """メニュー操作から360Viewerを起動し、ブラウザを開く。"""
        self.startViewerSessionPolling()
        frame_num = self.extract_frame.value() if self.video_file else None
        if not self.ensureViewerStarted():
            return
        self.openViewerWhenReady(frame_num)

    def openViewerWhenReady(self, frame_num=None, attempts=20):
        """ビューア応答を待ってからブラウザを開く。起動直後の遅延を吸収する。"""
        if self.viewerHealth(timeout=0.75):
            opens_viewer_page = frame_num is not None and bool(self.video_file)
            if not opens_viewer_page:
                url = self.viewerUrl()
                self.openViewerUrl(url)
                self.viewer_browser_opened = True
                self.iface.messageBar().pushMessage(
                    PLUGIN_TITLE,
                    f"360Viewer opened: {url}"
                )
                return
            self.postViewerNavigation(frame_num)
            url = self.viewerUrl(frame_num)
            self.openViewerUrl(url)
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

    def updateViewerWhenReady(self, frame_num, attempts=8):
        """既存ビューアページが一時的にbusyな場合、開き直さず更新だけをリトライする。"""
        frame_num = int(frame_num)
        if getattr(self, "pending_viewer_update_frame", frame_num) != frame_num:
            return

        if self.viewerHealth(timeout=0.75) and self.postViewerNavigation(frame_num):
            self.notifyDebugText(f"360Viewer frame updated: {frame_num}")
            return

        if attempts <= 0:
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                f"360Viewer navigation did not respond: {self.viewerBaseUrl()}"
            )
            return

        QTimer.singleShot(350, lambda: self.updateViewerWhenReady(frame_num, attempts - 1))

    def postViewerNavigation(self, frame_num):
        """既存ビューアページへHTTP APIで表示フレーム変更を通知する。"""
        if not self.video_file:
            return False

        payload = {
            "command_id": uuid.uuid4().hex,
            "video": os.path.basename(self.video_file),
            "frame_index": int(frame_num),
            "viewer_camera_height_m": self.viewerCameraHeightValue(),
            "viewer_hud_height_scale": self.viewerHudHeightScaleValue(),
            "viewer_projection": self.viewerProjectionValue(),
            "viewer_flat_hfov_deg": self.viewerFlatHfovValue(),
            "viewer_flat_vfov_deg": self.viewerFlatVfovValue(),
        }
        radar_payload = self.viewerRadarHudPayload(frame_num)
        if radar_payload:
            payload["radar"] = radar_payload
        try:
            nav_mode = self.nav_mode.currentData() if getattr(self, "nav_mode", None) is not None else None
        except Exception:
            nav_mode = None

        targets_payload = []
        if nav_mode == "detect":
            target_payload_getter = getattr(self, "viewerDetectionTargetsForFrame", None)
        else:
            target_payload_getter = getattr(self, "viewerTargetsForFrame", None)
        if callable(target_payload_getter):
            try:
                targets_payload = target_payload_getter(frame_num)
            except Exception as e:
                self.viewerDebugPrint(f"360Viewer target restore payload failed: {e}")
        if nav_mode in ("detect", "picked"):
            # Explicitly clear stale targets when the active review mode has no
            # target on this frame. Otherwise a previous click/POI can flash.
            payload["targets"] = targets_payload
            payload["target"] = targets_payload[0] if nav_mode == "detect" and targets_payload else None
        if targets_payload:
            payload["targets"] = targets_payload
            flat_auto = False
            if self.video_file and not getattr(self, "viewer_projection_dirty", False):
                try:
                    flat_auto = self.inferViewerProjectionFromVideo(self.video_file)[0] == "flat"
                except Exception:
                    flat_auto = False
            if (
                self.viewerProjectionValue() == "flat"
                or flat_auto
                or any(str(target.get("target_source") or "").lower() == "yolo_pinhole" for target in targets_payload)
            ):
                payload["viewer_projection"] = "flat"
                payload["viewer_flat_hfov_deg"] = self.viewerFlatHfovValue()
                payload["viewer_flat_vfov_deg"] = self.viewerFlatVfovValue()
                payload["yaw_to_camera_heading"] = 0.0
                payload["pitch"] = 0.0
            heading_getter = getattr(self, "radarHeadingAndRadius", None)
            offset_getter = getattr(self, "viewerBearingOffsetFromTargets", None)
            if callable(heading_getter) and callable(offset_getter):
                try:
                    heading, _radius_m = heading_getter(frame_num)
                    viewer_front_offset = offset_getter(heading, {"targets": targets_payload})
                except Exception as e:
                    self.viewerDebugPrint(f"360Viewer front offset payload failed: {e}")
                    viewer_front_offset = None
                if viewer_front_offset is not None:
                    payload["viewer_front_offset_deg"] = viewer_front_offset

        if nav_mode == "picked":
            view_getter = getattr(self, "viewerViewForPickedFrame", None)
            if callable(view_getter):
                try:
                    picked_view = view_getter(frame_num)
                except Exception as e:
                    self.viewerDebugPrint(f"360Viewer picked view restore failed: {e}")
                    picked_view = None
                if picked_view:
                    payload.update(picked_view)
        elif nav_mode == "detect":
            view_getter = getattr(self, "viewerViewForDetectionFrame", None)
            if callable(view_getter):
                try:
                    detection_view = view_getter(frame_num)
                except Exception as e:
                    self.viewerDebugPrint(f"360Viewer detection view restore failed: {e}")
                    detection_view = None
                if detection_view:
                    payload.update(detection_view)
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
            self.viewerDebugPrint(f"360Viewer navigation failed: {e}")
            return False

    def showFrameInViewer(self, frame_num):
        """QGIS側のフレーム選択に合わせて360Viewer表示を更新する。"""
        if not self.video_file:
            return
        frame_num = int(frame_num)
        self.pending_viewer_update_frame = frame_num
        self.startViewerSessionPolling()
        if not self.ensureViewerStarted():
            return

        if not self.viewerHealth(timeout=0.75):
            if self.viewer_browser_opened:
                self.updateViewerWhenReady(frame_num)
            else:
                self.openViewerWhenReady(frame_num)
            return

        if self.viewer_browser_opened and self.postViewerNavigation(frame_num):
            self.notifyDebugText(f"360Viewer frame updated: {frame_num}")
            return

        if self.viewer_browser_opened:
            self.updateViewerWhenReady(frame_num)
        else:
            self.openViewerWhenReady(frame_num)

    def stopViewerProcess(self):
        """このプラグインが起動した360Viewerプロセスを停止する。"""
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
