"""GPXVideoProcessor QGISプラグインのUIと全体制御。"""

import csv
from datetime import datetime, timezone
import json
import os

from qgis.PyQt import QtGui, QtWidgets
from qgis.PyQt.QtWidgets import (
    QWidget, QPushButton, QFileDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox
)
from qgis.PyQt.QtCore import (
    QEvent, QTimer, QVariant, Qt
)
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsField, QgsVectorFileWriter, QgsCoordinateTransform
)

from .common import (
    _base_output_name,
    _format_distance,
    _format_timestamp,
    _frame_image_relative_path,
    _frame_image_relative_posix,
    _open_csv_dict_reader,
    _parse_float,
    _safe_gpkg_layer_name,
    _to_qdatetime,
)
from .constants import (
    FRAMES_CSV_SUFFIX,
    MATCHED_FRAMES_CSV_SUFFIX,
    NAVIGATION_JSON_SUFFIX,
    PLUGIN_TITLE,
)
from .frame_extract import FrameExtractMixin
from .kp import build_kp_matches
from .map_tools import FrameIdentifyTool
from .processor import GPXVideoProcessor
from .radar import RadarMixin
from .viewer_controller import ViewerControllerMixin

QAction = getattr(QtWidgets, "QAction", None) or QtGui.QAction



class GPXVideoPlugin(ViewerControllerMixin, RadarMixin, FrameExtractMixin, QWidget):
    """GPX/動画同期、360Viewer連携、QGISレイヤ生成を統括するプラグイン本体。"""

    def __init__(self, iface, parent=None):
        """QGIS ifaceと、セッション中に共有する状態を初期化する。"""
        super().__init__(parent)
        self.iface = iface
        self.gpx_file = ""
        self.video_file = ""
        self.kp_file = ""
        self.output_dir = ""
        self.output_dir_user_selected = False
        self.last_rows = []
        self.worker = None
        self.frame_click_tool = None
        self.action = None
        self.viewer_action = None
        self.exit_action = None
        self.viewer_process = None
        self.viewer_browser_opened = False
        self.viewer_host = "127.0.0.1"
        self.viewer_port = 8181
        self.viewer_jpeg_quality = 70
        self.viewer_progressive_jpeg = True
        self.viewer_max_width = 3072
        self.created_layer_ids = []
        self.frame_layer_id = None
        self.session_closing = False
        self.current_frame = None
        self.viewer_session_timer = None
        self.last_viewer_session_signature = None
        self.radar_circle_band = None
        self.radar_outer_circle_band = None
        self.radar_sector_band = None
        self.radar_direction_band = None
        self.radar_perpendicular_band = None
        self.radar_target_line_band = None
        self.radar_target_point_band = None
        self.last_radar_heading = None
        self.last_radar_sector_radius_m = None
        self.last_radar_frame_index = None
        self.current_viewer_fov = None
        self.current_marker_distance_m = None
        self.frame_position_by_frame = {}
        self.toolbar = None
        self._gui_initialized = False
        self._keyboard_filter_installed = False

    def initGui(self):
        """QGISメニュー/ツールバー/パネルUIを一度だけ構築する。"""
        if self._gui_initialized:
            return

        self.setWindowTitle("GPX Video Processor")
        self.applyPanelWindowFlags()

        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        def compact_row(target_layout, *items):
            """関連するUI部品を1行にまとめて、パネルの縦方向を節約する。"""
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            for item in items:
                if item == "stretch":
                    row.addStretch(1)
                elif isinstance(item, QHBoxLayout):
                    row.addLayout(item)
                else:
                    row.addWidget(item)
            target_layout.addLayout(row)

        def set_fixed_width(widget, width):
            """ボタンや数値入力の幅を固定し、行内レイアウトの崩れを防ぐ。"""
            widget.setMinimumWidth(width)
            widget.setMaximumWidth(width)

        self.gpx_label = QLabel("GPX:")
        self.gpx_path = self.makePathLabel("No GPX")
        self.gpx_button = QPushButton("Browse")
        self.gpx_button.clicked.connect(self.selectGPX)
        set_fixed_width(self.gpx_button, 72)

        self.video_label = QLabel("Video:")
        self.video_path = self.makePathLabel("No video")
        self.video_button = QPushButton("Browse")
        self.video_button.clicked.connect(self.selectVideo)
        set_fixed_width(self.video_button, 72)

        self.kp_label = QLabel("KP CSV:")
        self.kp_path = self.makePathLabel("No KP CSV")
        self.kp_button = QPushButton("Browse")
        self.kp_button.clicked.connect(self.selectKP)
        set_fixed_width(self.kp_button, 72)

        for label in (self.gpx_label, self.video_label, self.kp_label):
            label.setMinimumWidth(52)

        self.kp_tolerance_label = QLabel("KP tol:")
        self.kp_tolerance = QDoubleSpinBox()
        self.kp_tolerance.setRange(0.0, 10000.0)
        self.kp_tolerance.setDecimals(1)
        self.kp_tolerance.setSingleStep(0.5)
        self.kp_tolerance.setValue(5.0)
        self.kp_tolerance.setSuffix(" m")
        set_fixed_width(self.kp_tolerance, 82)

        self.frame_shift_label = QLabel("Shift:")
        self.frame_shift = QSpinBox()
        self.frame_shift.setRange(-1000000, 1000000)
        self.frame_shift.setSingleStep(1)
        self.frame_shift.setValue(0)
        self.frame_shift.setSuffix(" fr")
        self.frame_shift.setToolTip(
            "Keeps video frame numbers fixed. Position source frame = video frame - shift."
        )
        set_fixed_width(self.frame_shift, 92)

        self.output_label = QLabel("Output:")
        self.output_path = self.makePathLabel("Default output")
        self.output_button = QPushButton("Browse")
        self.output_button.clicked.connect(self.selectOutputDir)
        self.output_label.setMinimumWidth(52)
        set_fixed_width(self.output_button, 72)

        self.extract_frame_label = QLabel("Frame:")
        self.extract_frame = QSpinBox()
        self.extract_frame.setRange(0, 1000000000)
        self.extract_frame.setSingleStep(1)
        self.extract_frame.setValue(0)
        set_fixed_width(self.extract_frame, 92)
        self.extract_button = QPushButton("Extract")
        self.extract_button.clicked.connect(self.extractTestFrame)
        set_fixed_width(self.extract_button, 72)
        self.follow_frame_checkbox = QCheckBox("Follow")
        self.follow_frame_checkbox.setChecked(False)
        self.follow_frame_checkbox.setToolTip(
            "Center the QGIS map on the displayed frame point without changing zoom."
        )

        self.nav_label = QLabel("Nav:")
        self.current_frame_label = QLabel("Current: -")
        self.nav_mode = QComboBox()
        self.nav_mode.addItem("Frame step", "frame")
        self.nav_mode.addItem("Layer point", "layer")
        self.nav_mode.addItem("KP matched CSV", "kp")
        self.nav_mode.setToolTip(
            "Frame step moves by frame number. Layer point moves through the GPXVideoProcessor frame layer. "
            "KP matched CSV moves through matched frame_index values."
        )
        set_fixed_width(self.nav_mode, 126)
        self.nav_step = QSpinBox()
        self.nav_step.setRange(1, 1000000)
        self.nav_step.setValue(1)
        set_fixed_width(self.nav_step, 76)
        self.nav_fast_step = QSpinBox()
        self.nav_fast_step.setRange(1, 1000000)
        self.nav_fast_step.setValue(30)
        set_fixed_width(self.nav_fast_step, 76)

        self.nav_back_fast_button = QPushButton("<<")
        self.nav_back_button = QPushButton("<")
        self.nav_forward_button = QPushButton(">")
        self.nav_forward_fast_button = QPushButton(">>")
        self.nav_back_fast_button.clicked.connect(lambda _checked=False: self.navigateRelative(-1, fast=True))
        self.nav_back_button.clicked.connect(lambda _checked=False: self.navigateRelative(-1, fast=False))
        self.nav_forward_button.clicked.connect(lambda _checked=False: self.navigateRelative(1, fast=False))
        self.nav_forward_fast_button.clicked.connect(lambda _checked=False: self.navigateRelative(1, fast=True))
        for button in (
            self.nav_back_fast_button,
            self.nav_back_button,
            self.nav_forward_button,
            self.nav_forward_fast_button,
        ):
            set_fixed_width(button, 34)

        self.nav_button_layout = QHBoxLayout()
        self.nav_button_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_button_layout.setSpacing(2)
        self.nav_button_layout.addWidget(self.nav_back_fast_button)
        self.nav_button_layout.addWidget(self.nav_back_button)
        self.nav_button_layout.addWidget(self.nav_forward_button)
        self.nav_button_layout.addWidget(self.nav_forward_fast_button)

        self.radar_radius_label = QLabel("Range:")
        self.radar_radius = QDoubleSpinBox()
        self.radar_radius.setRange(1.0, 500.0)
        self.radar_radius.setDecimals(1)
        self.radar_radius.setSingleStep(1.0)
        self.radar_radius.setValue(5.0)
        self.radar_radius.setSuffix(" m")
        self.radar_radius.setToolTip(
            "Fixed map range circle. A second circle is drawn at twice this distance."
        )
        set_fixed_width(self.radar_radius, 82)
        self.radar_scale_label = QLabel("Scale:")
        self.radar_scale = QDoubleSpinBox()
        self.radar_scale.setRange(0.1, 20.0)
        self.radar_scale.setDecimals(1)
        self.radar_scale.setSingleStep(0.1)
        self.radar_scale.setValue(1.0)
        self.radar_scale.setSuffix(" x")
        self.radar_scale.setToolTip(
            "Manual multiplier for the calibrated radar marker distance."
        )
        set_fixed_width(self.radar_scale, 78)
        self.current_fov_label = QLabel("FOV: -")
        self.marker_distance_label = QLabel("Marker: -")
        self.target_projection_label = QLabel("Click: -")
        self.radar_cal_fov_label = QLabel("CalFOV:")
        self.radar_cal_fov = QDoubleSpinBox()
        self.radar_cal_fov.setRange(1.0, 179.0)
        self.radar_cal_fov.setDecimals(1)
        self.radar_cal_fov.setSingleStep(1.0)
        self.radar_cal_fov.setValue(90.0)
        self.radar_cal_fov.setSuffix(" deg")
        self.radar_cal_fov.setToolTip(
            "Reference field of view used when the marker distance was calibrated."
        )
        set_fixed_width(self.radar_cal_fov, 92)
        self.radar_cal_distance_label = QLabel("CalDist:")
        self.radar_cal_distance = QDoubleSpinBox()
        self.radar_cal_distance.setRange(0.1, 500.0)
        self.radar_cal_distance.setDecimals(1)
        self.radar_cal_distance.setSingleStep(0.5)
        self.radar_cal_distance.setValue(5.0)
        self.radar_cal_distance.setSuffix(" m")
        self.radar_cal_distance.setToolTip(
            "Calibrated center-view marker distance at CalFOV before Scale is applied."
        )
        set_fixed_width(self.radar_cal_distance, 84)
        self.use_current_fov_button = QPushButton("Use FOV")
        self.use_current_fov_button.clicked.connect(self.useCurrentFovForCalibration)
        self.use_current_fov_button.setToolTip("Set CalFOV to the current viewer FOV.")
        set_fixed_width(self.use_current_fov_button, 74)
        self.radar_offset_label = QLabel("Offset:")
        self.radar_offset = QComboBox()
        for offset in (0, 90, 180, 270):
            self.radar_offset.addItem(f"{offset}deg", offset)
        self.radar_offset.setToolTip(
            "Clockwise bearing correction for videos whose visual front is not the travel direction."
        )
        set_fixed_width(self.radar_offset, 78)

        self.click_mode_button = QPushButton("Click Layer")
        self.click_mode_button.clicked.connect(self.activateClickMode)
        self.stop_click_mode_button = QPushButton("Stop Click")
        self.stop_click_mode_button.clicked.connect(self.deactivateClickMode)
        set_fixed_width(self.click_mode_button, 92)
        set_fixed_width(self.stop_click_mode_button, 82)

        self.preview_info = QLabel("No frame extracted")
        self.preview_info.setWordWrap(False)
        self.preview_info.setMaximumHeight(22)
        self.preview_info.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        self.preview_label.setMaximumHeight(190)
        self.preview_label.setText("Preview")

        self.process_button = QPushButton("Process")
        self.process_button.clicked.connect(self.processData)
        set_fixed_width(self.process_button, 86)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        tabs = QtWidgets.QTabWidget()
        tabs.setDocumentMode(True)

        load_tab = QWidget()
        load_layout = QVBoxLayout(load_tab)
        load_layout.setContentsMargins(4, 4, 4, 4)
        load_layout.setSpacing(4)

        control_tab = QWidget()
        control_layout = QVBoxLayout(control_tab)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(4)

        compact_row(load_layout, self.gpx_label, self.gpx_path, self.gpx_button)
        compact_row(load_layout, self.video_label, self.video_path, self.video_button)
        compact_row(load_layout, self.kp_label, self.kp_path, self.kp_button)
        compact_row(load_layout, self.output_label, self.output_path, self.output_button)
        compact_row(
            load_layout,
            self.frame_shift_label,
            self.frame_shift,
            self.kp_tolerance_label,
            self.kp_tolerance,
            "stretch",
        )
        compact_row(load_layout, self.process_button, self.progress_bar)
        load_layout.addStretch(1)

        compact_row(
            control_layout,
            self.extract_frame_label,
            self.extract_frame,
            self.extract_button,
            self.click_mode_button,
            self.stop_click_mode_button,
            self.follow_frame_checkbox,
            "stretch",
        )
        compact_row(
            control_layout,
            self.nav_label,
            self.current_frame_label,
            self.nav_mode,
            QLabel("Step:"),
            self.nav_step,
            QLabel("Fast:"),
            self.nav_fast_step,
            "stretch",
        )
        compact_row(
            control_layout,
            self.radar_radius_label,
            self.radar_radius,
            self.radar_scale_label,
            self.radar_scale,
            self.radar_offset_label,
            self.radar_offset,
            "stretch",
        )
        compact_row(
            control_layout,
            self.current_fov_label,
            self.marker_distance_label,
            self.target_projection_label,
            self.radar_cal_fov_label,
            self.radar_cal_fov,
            self.radar_cal_distance_label,
            self.radar_cal_distance,
            self.use_current_fov_button,
            "stretch",
        )
        control_layout.addWidget(self.preview_info)
        control_layout.addWidget(self.preview_label)
        compact_row(control_layout, QLabel("Move:"), self.nav_button_layout, "stretch")
        control_layout.addStretch(1)

        tabs.addTab(load_tab, "Load / Process")
        tabs.addTab(control_tab, "Control / Preview")
        layout.addWidget(tabs)

        self.setLayout(layout)

        # アクションを定義
        self.action = QAction("Start", self)
        self.action.triggered.connect(self.run)
        self.viewer_action = QAction("360ViewerOpen", self)
        self.viewer_action.triggered.connect(self.openViewer)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.exitSession)

        # メニューにアクションを追加
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.viewer_action)
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.action)
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.exit_action)

        # ツールバーにアクションを追加
        self.toolbar = self.iface.addToolBar(PLUGIN_TITLE)
        self.toolbar.addAction(self.viewer_action)
        self.toolbar.addAction(self.action)
        self.toolbar.addAction(self.exit_action)
        self.startViewerSessionPolling()
        self.installKeyboardFilter()
        self._gui_initialized = True

    def installKeyboardFilter(self):
        """クリックモード中のフレーム移動キーをQGISアプリ全体で拾えるようにする。"""
        if self._keyboard_filter_installed:
            return
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._keyboard_filter_installed = True

    def removeKeyboardFilter(self):
        """アンロード時にQGISアプリケーションイベントフィルタを外す。"""
        if not self._keyboard_filter_installed:
            return
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._keyboard_filter_installed = False

    def frameKeyboardNavigationActive(self):
        """現在のQGIS状態でキーボードフレーム移動を有効にしてよいかを返す。"""
        if self.panelHasKeyboardFocus():
            return True
        try:
            return self.frame_click_tool is not None and self.iface.mapCanvas().mapTool() is self.frame_click_tool
        except Exception:
            return False

    def panelHasKeyboardFocus(self):
        """操作パネルまたはその子ウィジェットにフォーカスがあるかを返す。"""
        focus = QtWidgets.QApplication.focusWidget()
        if focus is None:
            return False
        return focus is self or self.isAncestorOf(focus) or focus.window() is self

    def shouldIgnoreNavigationKeyTarget(self):
        """入力ウィジェット操作中は左右キーをフレーム移動に使わない。"""
        focus = QtWidgets.QApplication.focusWidget()
        ignored_types = (
            QtWidgets.QAbstractSpinBox,
            QtWidgets.QComboBox,
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
        )
        return isinstance(focus, ignored_types)

    def eventFilter(self, watched, event):
        """MapToolへ届かないキー操作も、クリックモード中だけ補助的に処理する。"""
        if event.type() == QEvent.KeyPress and self.frameKeyboardNavigationActive():
            if self.shouldIgnoreNavigationKeyTarget():
                return False

            key = event.key()
            fast = bool(event.modifiers() & Qt.ShiftModifier)
            if key == Qt.Key_Left:
                self.navigateRelative(-1, fast=fast)
                return True
            if key == Qt.Key_Right:
                self.navigateRelative(1, fast=fast)
                return True
            if key == Qt.Key_Space:
                self.displayCurrentFrame()
                return True
            if key == Qt.Key_Escape:
                self.deactivateClickMode()
                return True

        return super().eventFilter(watched, event)

    def applyPanelWindowFlags(self):
        """操作パネルをQGIS操作中も前面へ出しやすいウィンドウにする。"""
        flags = self.windowFlags()
        if not (flags & Qt.WindowStaysOnTopHint):
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)

    def showWindow(self):
        """プラグインパネルを前面に表示する。"""
        self.applyPanelWindowFlags()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    def run(self):
        """Startメニューからパネルを開き、ビューア状態監視を開始する。"""
        self.showWindow()
        self.startViewerSessionPolling()
        self.reportViewerStatus()

    def makePathLabel(self, text):
        """長いパスでパネル幅が広がらないファイル表示ラベルを作る。"""
        label = QLabel(text)
        label.setMinimumWidth(160)
        label.setWordWrap(False)
        label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        return label

    def compactPathText(self, path, fallback):
        """表示用にはbasenameだけを返し、空ならfallbackを返す。"""
        if not path:
            return fallback
        name = os.path.basename(os.path.normpath(path))
        return name or path

    def setPathLabel(self, label, path, fallback):
        """ファイル表示ラベルを短縮表示にし、フルパスをツールチップへ保持する。"""
        label.setText(self.compactPathText(path, fallback))
        label.setToolTip(path or "")

    def selectGPX(self):
        """GPXファイルを選択し、入力状態を更新する。"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select GPX File", "", "GPX Files (*.gpx)")
        if file_path:
            self.gpx_file = file_path
            self.setPathLabel(self.gpx_path, file_path, "No GPX")

    def selectVideo(self):
        """MP4動画を選択し、出力先既定値とビューア設定を更新する。"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", "MP4 Files (*.mp4)")
        if file_path:
            self.video_file = file_path
            self.setPathLabel(self.video_path, file_path, "No video")
            self.viewer_browser_opened = False
            self.setCurrentFrame(None)
            if not self.output_dir_user_selected:
                self.setPathLabel(self.output_path, self.defaultOutputDir(), "Default output")
            self.writeViewerRuntimeConfig(show_error=False)

    def selectKP(self):
        """KPマスタCSVを選択する。KP未指定でも通常処理は可能。"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select KP CSV", "", "CSV Files (*.csv)")
        if file_path:
            self.kp_file = file_path
            self.setPathLabel(self.kp_path, file_path, "No KP CSV")

    def selectOutputDir(self):
        """CSV/画像/セッションJSONの出力先ディレクトリを選択する。"""
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.defaultOutputDir())
        if directory:
            self.output_dir = directory
            self.output_dir_user_selected = True
            self.setPathLabel(self.output_path, directory, "Default output")
            self.writeViewerRuntimeConfig(show_error=False)

    def defaultOutputDir(self):
        """動画またはGPXと同じ場所に置く既定出力ディレクトリを返す。"""
        base_path = self.video_file or self.gpx_file or __file__
        return os.path.join(os.path.dirname(base_path), "360view_output")

    def resolvedOutputDir(self):
        """ユーザ指定があればそれを優先した実出力先ディレクトリを返す。"""
        return self.output_dir or self.defaultOutputDir()

    def imagesDir(self):
        """QGIS側プレビューJPEGの保存ディレクトリを返す。"""
        return os.path.join(self.resolvedOutputDir(), "images")

    def frameImagePath(self, frame_num):
        """指定フレームのQGIS側プレビューJPEGパスを返す。"""
        return os.path.join(self.imagesDir(), _frame_image_relative_path(frame_num))

    def frameImageRelativePath(self, frame_num, base_dir=None):
        """CSV/JSONから参照するフレームJPEGの相対パスを返す。"""
        if base_dir:
            try:
                relative_path = os.path.relpath(self.frameImagePath(frame_num), base_dir)
                return relative_path.replace(os.sep, "/").replace("\\", "/")
            except ValueError:
                return self.frameImagePath(frame_num).replace(os.sep, "/").replace("\\", "/")
        return f"images/{_frame_image_relative_posix(frame_num)}"

    def setCurrentFrame(self, frame_num):
        """現在フレーム状態とUI表示を同期する。"""
        if frame_num is None:
            self.current_frame = None
            self.current_frame_label.setText("Current: -")
            return

        self.current_frame = int(frame_num)
        self.extract_frame.setValue(max(0, self.current_frame))
        self.current_frame_label.setText(f"Current: {self.current_frame}")

    def currentFrameValue(self):
        """現在フレーム状態を返す。未設定ならUIのFrame入力値を使う。"""
        if self.current_frame is not None:
            return int(self.current_frame)
        return int(self.extract_frame.value())

    def displayFrame(self, frame_num, feature=None):
        """指定フレームをビューアへ送り、少し遅らせてQGISプレビューを抽出する。"""
        frame_num = int(frame_num)
        if frame_num < 0:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Frame number must be greater than or equal to 0.")
            return

        self.setCurrentFrame(frame_num)
        if feature is not None and self.frame_click_tool is not None:
            try:
                self.frame_click_tool.highlightFeature(feature)
            except Exception:
                pass
        self.centerMapOnFeature(feature)
        self.showFrameInViewer(frame_num)
        # ブラウザ表示を先に走らせ、重いJPEG抽出が体感レスポンスを邪魔しないようにする。
        QTimer.singleShot(150, lambda: self.extractFrame(frame_num, feature=feature))

    def centerMapOnFeature(self, feature):
        """Follow有効時、表示フレーム地物を地図中心へ移動する。"""
        if feature is None:
            return
        if not getattr(self, "follow_frame_checkbox", None) or not self.follow_frame_checkbox.isChecked():
            return

        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            return

        try:
            layer = self.activeFrameLayer()
            canvas = self.iface.mapCanvas()
            point = geom.asPoint()
            if layer is not None and layer.crs() != canvas.mapSettings().destinationCrs():
                transform = QgsCoordinateTransform(
                    layer.crs(),
                    canvas.mapSettings().destinationCrs(),
                    QgsProject.instance()
                )
                point = transform.transform(QgsPointXY(point))

            canvas.setCenter(QgsPointXY(point))
            canvas.refresh()
        except Exception as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to center map on frame: {e}")

    def displayCurrentFrame(self):
        """現在フレームを再表示する。キーボードSpace操作からも使う。"""
        frame_num = self.currentFrameValue()
        self.displayFrame(frame_num, feature=self.findFeatureByFrame(frame_num))

    def useCurrentFovForCalibration(self):
        """現在ビューアFOVを距離校正基準FOVへ反映する。"""
        fov = getattr(self, "current_viewer_fov", None)
        if fov is None:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Current viewer FOV is not available yet.")
            return
        self.radar_cal_fov.setValue(float(fov))
        self.iface.messageBar().pushMessage(PLUGIN_TITLE, f"Calibration FOV set to {float(fov):.1f} deg.")

    def activeFrameLayer(self):
        """ナビゲーション対象のVideo GPX Pointsレイヤを選択状態に依存せず取得する。"""
        project = QgsProject.instance()

        if self.frame_layer_id:
            layer = project.mapLayer(self.frame_layer_id)
            if layer is not None and layer.fields().indexFromName("frame") >= 0:
                return layer

        for layer_id in reversed(self.created_layer_ids):
            layer = project.mapLayer(layer_id)
            if layer is not None and layer.fields().indexFromName("frame") >= 0:
                self.frame_layer_id = layer.id()
                return layer

        if self.frame_click_tool is not None and self.frame_click_tool.layer is not None:
            layer = self.frame_click_tool.layer
            if layer.fields().indexFromName("frame") >= 0:
                return layer

        layer = self.iface.activeLayer()
        if layer is None:
            return None
        if layer.fields().indexFromName("frame") < 0:
            return None
        return layer

    def layerFrames(self, layer):
        """指定レイヤからframe属性を集め、重複排除して昇順で返す。"""
        frames = []
        if layer is None:
            return frames

        for feature in layer.getFeatures():
            try:
                value = feature["frame"]
                if value is None:
                    continue
                frames.append(int(value))
            except Exception:
                continue
        return sorted(set(frames))

    def findFeatureByFrame(self, frame_num):
        """現在の対象レイヤから指定frameの地物を探す。"""
        layer = self.activeFrameLayer()
        if layer is None:
            return None

        target = int(frame_num)
        for feature in layer.getFeatures():
            try:
                if int(feature["frame"]) == target:
                    return feature
            except Exception:
                continue
        return None

    def matchedFrameCsvPaths(self):
        """KPマッチ済みフレームCSVの探索候補パスを返す。"""
        if not self.video_file:
            return []

        base_name = _base_output_name(self.video_file, self.gpx_file)
        paths = [
            os.path.join(os.path.dirname(self.video_file), base_name + MATCHED_FRAMES_CSV_SUFFIX),
            os.path.join(self.resolvedOutputDir(), base_name + MATCHED_FRAMES_CSV_SUFFIX),
        ]

        unique_paths = []
        seen = set()
        for path in paths:
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(path)
        return unique_paths

    def matchedFrames(self):
        """KPマッチ済みCSVからナビゲーション用frame_index一覧を読み込む。"""
        for path in self.matchedFrameCsvPaths():
            if not os.path.isfile(path):
                continue

            handle, reader = _open_csv_dict_reader(path)
            with handle:
                if not reader.fieldnames or "frame_index" not in reader.fieldnames:
                    continue
                frames = []
                for row in reader:
                    value = _parse_float(row.get("frame_index"))
                    if value is None:
                        continue
                    frames.append(int(value))
                if frames:
                    return sorted(set(frames)), path

        return [], None

    def steppedFrame(self, frames, current_frame, direction, step_count):
        """ソート済みフレーム列から、現在位置を基準に指定ステップ先を返す。"""
        if not frames:
            return None

        current_frame = int(current_frame)
        step_count = max(1, int(step_count))

        if direction > 0:
            greater = [frame for frame in frames if frame > current_frame]
            if not greater:
                return None
            if current_frame in frames:
                index = frames.index(current_frame) + step_count
            else:
                index = frames.index(greater[0]) + step_count - 1
            return frames[min(index, len(frames) - 1)]

        # 現在フレームがリスト外でも、直前側のフレームを起点に自然に戻れるようにする。
        smaller = [frame for frame in frames if frame < current_frame]
        if not smaller:
            return None
        if current_frame in frames:
            index = frames.index(current_frame) - step_count
        else:
            index = frames.index(smaller[-1]) - step_count + 1
        return frames[max(index, 0)]

    def navigationTargetFrame(self, direction, fast=False):
        """UIのナビモードに応じて、次に表示すべきフレームと地物を決める。"""
        current_frame = self.currentFrameValue()
        step_count = self.nav_fast_step.value() if fast else self.nav_step.value()
        mode = self.nav_mode.currentData()

        if mode == "frame":
            target = max(0, current_frame + direction * step_count)
            return target, self.findFeatureByFrame(target)

        if mode == "kp":
            frames, path = self.matchedFrames()
            if not frames:
                self.iface.messageBar().pushWarning(
                    PLUGIN_TITLE,
                    "Matched frame CSV was not found. Run Process with KP CSV or choose another navigation mode."
                )
                return None, None
            target = self.steppedFrame(frames, current_frame, direction, step_count)
            if target is None:
                self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"No {'next' if direction > 0 else 'previous'} KP frame.")
                return None, None
            return target, self.findFeatureByFrame(target)

        layer = self.activeFrameLayer()
        if layer is None:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "No Video GPX Points layer is available. Run Process first.")
            return None, None

        frames = self.layerFrames(layer)
        target = self.steppedFrame(frames, current_frame, direction, step_count)
        if target is None:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"No {'next' if direction > 0 else 'previous'} layer frame.")
            return None, None
        return target, self.findFeatureByFrame(target)

    def navigateRelative(self, direction, fast=False):
        """現在フレームから相対移動し、対象フレームを表示する。"""
        target, feature = self.navigationTargetFrame(direction, fast=fast)
        if target is None:
            return
        self.displayFrame(target, feature=feature)


    def stopWorker(self, wait_ms=1000, show_message=True):
        """実行中workerへ中断要求を出し、一定時間だけ終了を待つ。"""
        if self.worker is None:
            return True

        if not self.worker.isRunning():
            self.worker = None
            self.process_button.setEnabled(True)
            return True

        self.worker.requestInterruption()
        if self.worker.wait(wait_ms):
            self.worker = None
            self.process_button.setEnabled(True)
            self.progress_bar.setValue(0)
            return True

        if show_message:
            self.iface.messageBar().pushWarning(
                PLUGIN_TITLE,
                "Processing is still running. Exit will finish after the worker stops."
            )
        return False

    def removeGeneratedLayers(self):
        """このプラグインが生成したメモリレイヤだけをQGISプロジェクトから削除する。"""
        project = QgsProject.instance()
        removed_count = 0
        remaining_layer_ids = []

        for layer_id in self.created_layer_ids:
            if project.mapLayer(layer_id) is None:
                continue
            project.removeMapLayer(layer_id)
            removed_count += 1
            if layer_id == self.frame_layer_id:
                self.frame_layer_id = None

        self.created_layer_ids = remaining_layer_ids
        return removed_count

    def generatedLayerBackupPath(self):
        """Exit時に生成レイヤを退避保存するGeoPackageパスを返す。"""
        return os.path.join(self.resolvedOutputDir(), "tmp.gpkg")

    def generatedLayers(self):
        """現在QGISに残っている、プラグイン生成レイヤだけを取得する。"""
        project = QgsProject.instance()
        layers = []
        for layer_id in self.created_layer_ids:
            layer = project.mapLayer(layer_id)
            if layer is not None:
                layers.append(layer)
        return layers

    def gpkgOverwriteAction(self, overwrite_file):
        """QGISバージョン差を吸収してGeoPackage上書きアクションを返す。"""
        action_name = "CreateOrOverwriteFile" if overwrite_file else "CreateOrOverwriteLayer"
        action_enum = getattr(QgsVectorFileWriter, "ActionOnExistingFile", None)
        if action_enum is not None:
            return getattr(action_enum, action_name)
        return getattr(QgsVectorFileWriter, action_name)

    def writeLayerToGpkg(self, layer, gpkg_path, layer_name, overwrite_file):
        """単一QGISレイヤをGeoPackageへ書き出す。"""
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.actionOnExistingFile = self.gpkgOverwriteAction(overwrite_file)

        transform_context = QgsProject.instance().transformContext()
        if hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3"):
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                transform_context,
                options
            )
        elif hasattr(QgsVectorFileWriter, "writeAsVectorFormatV2"):
            result = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer,
                gpkg_path,
                transform_context,
                options
            )
        else:
            result = QgsVectorFileWriter.writeAsVectorFormat(
                layer,
                gpkg_path,
                "utf-8",
                layer.crs(),
                "GPKG"
            )

        error_code = result[0] if isinstance(result, tuple) else result
        message = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
        if error_code != QgsVectorFileWriter.NoError:
            raise RuntimeError(message or f"QgsVectorFileWriter error code: {error_code}")

    def saveGeneratedLayers(self):
        """生成済みメモリレイヤをtmp.gpkgへ保存する。失敗時はエラー文字列を返す。"""
        layers = self.generatedLayers()
        if not layers:
            return None, 0, None

        output_dir = self.resolvedOutputDir()
        gpkg_path = self.generatedLayerBackupPath()
        base_layer_name = _safe_gpkg_layer_name(_base_output_name(self.video_file, self.gpx_file))

        try:
            os.makedirs(output_dir, exist_ok=True)
            for index, layer in enumerate(layers, start=1):
                layer_name = base_layer_name if index == 1 else f"{base_layer_name}_{index:02d}"
                self.writeLayerToGpkg(
                    layer,
                    gpkg_path,
                    layer_name,
                    overwrite_file=(index == 1)
                )
        except Exception as e:
            return gpkg_path, 0, str(e)

        return gpkg_path, len(layers), None

    def resetPanelState(self):
        """セッション終了後にパネル上の一時状態を初期化する。"""
        self.last_rows = []
        self.frame_position_by_frame = {}
        self.frame_layer_id = None
        self.setCurrentFrame(None)
        self.progress_bar.setValue(0)
        self.process_button.setEnabled(True)
        self.preview_info.setText("No frame extracted")
        self.preview_info.setToolTip("")
        self.preview_label.clear()
        self.preview_label.setText("Preview")

    def cleanupSession(self, close_panel=True, remove_layers=True, show_message=True):
        """クリックモード、worker、ビューア、生成レイヤをまとめて終了処理する。"""
        self.session_closing = True
        self.deactivateClickMode(show_message=False)
        worker_stopped = self.stopWorker(show_message=show_message)
        self.stopViewerProcess()
        self.stopViewerSessionPolling()
        self.clearRadar()

        saved_path = None
        saved_count = 0
        save_error = None
        if remove_layers:
            saved_path, saved_count, save_error = self.saveGeneratedLayers()

        # 保存に失敗した場合は、データ消失を避けるためレイヤ削除を行わない。
        if save_error:
            removed_count = 0
            if show_message:
                self.iface.messageBar().pushWarning(
                    PLUGIN_TITLE,
                    f"Failed to save generated layer(s) to {saved_path}. Layers were not removed: {save_error}"
                )
        else:
            removed_count = self.removeGeneratedLayers() if remove_layers else 0

        self.resetPanelState()

        if close_panel:
            self.close()

        if show_message and not save_error:
            if worker_stopped:
                backup_message = (
                    f" Saved {saved_count} layer(s) to {saved_path}."
                    if saved_path and saved_count
                    else ""
                )
                self.iface.messageBar().pushMessage(
                    PLUGIN_TITLE,
                    f"Session closed.{backup_message} "
                    f"Removed {removed_count} generated layer(s); 360Viewer process stopped."
                )
            else:
                self.iface.messageBar().pushWarning(
                    PLUGIN_TITLE,
                    "Session close requested. Generated layers/viewer were cleaned up where possible."
                )

    def exitSession(self):
        """Exitメニューから現在セッションを終了する。"""
        self.cleanupSession(close_panel=True, remove_layers=True, show_message=True)

    def activateClickMode(self):
        """参照用Video GPX Pointsレイヤをクリック待ち受け状態にする。"""
        layer = self.activeFrameLayer()
        if layer is None:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "No Video GPX Points layer is available. Run Process first.")
            return
        if layer.fields().indexFromName("frame") < 0:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Selected layer has no frame field.")
            return

        self.deactivateClickMode(show_message=False)
        canvas = self.iface.mapCanvas()
        self.frame_click_tool = FrameIdentifyTool(canvas, layer, self)
        canvas.setMapTool(self.frame_click_tool)
        self.iface.messageBar().pushMessage(
            PLUGIN_TITLE,
            f"Click mode active for layer: {layer.name()}"
        )

    def deactivateClickMode(self, show_message=True):
        """地図クリックモードを解除し、一時ハイライトも消す。"""
        if self.frame_click_tool is None:
            return

        canvas = self.iface.mapCanvas()
        if canvas.mapTool() == self.frame_click_tool:
            canvas.unsetMapTool(self.frame_click_tool)
        self.frame_click_tool.clearHighlight()
        self.frame_click_tool = None
        if show_message:
            self.iface.messageBar().pushMessage(PLUGIN_TITLE, "Click mode stopped.")


    def processData(self):
        """GPX/動画同期workerを開始する。結果はaddLayerで受け取る。"""
        if not self.gpx_file or not self.video_file:
            print("Error: GPX or video file not selected.")
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Select both a GPX file and a video file.")
            return

        self.session_closing = False
        print(f"Processing GPX: {self.gpx_file}")
        print(f"Processing Video: {self.video_file}")

        self.progress_bar.setValue(0)
        self.process_button.setEnabled(False)

        self.worker = GPXVideoProcessor(
            self.gpx_file,
            self.video_file,
            frame_shift=self.frame_shift.value()
        )
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self.addLayer)
        self.worker.error.connect(self.showError)
        self.worker.start()


    def addLayer(self, rows):
        """workerが生成したフレーム位置行をQGISレイヤへ変換して追加する。"""
        self.process_button.setEnabled(True)
        self.progress_bar.setValue(100)
        if self.session_closing:
            return

        self.last_rows = rows
        self.frame_position_by_frame = {}
        for frame_num, _source_frame, _time, lat, lon in rows:
            self.frame_position_by_frame[int(frame_num)] = (float(lat), float(lon))

        if rows:
            matches, match_count, match_error = self.resolveKpMatches(rows)
            if match_error:
                self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to match KP CSV: {match_error}")

            # 生成レイヤは一時メモリレイヤ。Exit時にtmp.gpkgへ保存してから削除する。
            layer = QgsVectorLayer("Point?crs=EPSG:4326", "Video GPX Points", "memory")
            pr = layer.dataProvider()

            pr.addAttributes([
                QgsField("frame", QVariant.Int),
                QgsField("source_frame", QVariant.Int),
                QgsField("frame_shift", QVariant.Int),
                QgsField("timestamp", QVariant.DateTime),
                QgsField("latitude", QVariant.Double),
                QgsField("longitude", QVariant.Double),
                QgsField("aligned_latitude", QVariant.Double),
                QgsField("aligned_longitude", QVariant.Double),
                QgsField("kp", QVariant.String),
                QgsField("kp_distance_m", QVariant.Double),
                QgsField("kp_latitude", QVariant.Double),
                QgsField("kp_longitude", QVariant.Double),
                QgsField("kp_match", QVariant.Int),
            ])
            layer.updateFields()

            features = []
            for row_index, (frame_num, source_frame, time, lat, lon) in enumerate(rows):
                match = matches[row_index]
                aligned_lat = match["lat"] if match else lat
                aligned_lon = match["lon"] if match else lon
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
                feat.setAttributes([
                    frame_num,
                    source_frame,
                    self.frame_shift.value(),
                    _to_qdatetime(time),
                    lat,
                    lon,
                    aligned_lat,
                    aligned_lon,
                    match["kp"] if match else "",
                    round(match["distance_m"], 3) if match else None,
                    match["lat"] if match else None,
                    match["lon"] if match else None,
                    1 if match else 0,
                ])
                features.append(feat)

            pr.addFeatures(features)
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)
            self.created_layer_ids.append(layer.id())
            self.frame_layer_id = layer.id()
            print("Layer added successfully.")
            self.iface.messageBar().pushMessage(PLUGIN_TITLE, "Layer added successfully.")
            self.exportFrameData(rows, matches=matches, match_count=match_count)
        else:
            print("No rows. Could not add layer.")
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "No rows. Could not add layer.")

    def buildKpMatches(self, rows):
        """現在UIのKPファイル/許容距離を使ってKPマッチングを実行する。"""
        return build_kp_matches(rows, self.kp_file, self.kp_tolerance.value())

    def resolveKpMatches(self, rows):
        """KPマッチングを安全に実行し、レイヤ属性とCSV出力で共有する。"""
        try:
            matches, match_count = self.buildKpMatches(rows)
            return matches, match_count, None
        except Exception as e:
            return [None] * len(rows), 0, str(e)

    def exportFrameData(self, rows, matches=None, match_count=None):
        """全フレーム同期CSV、KPナビゲーションJSON/CSVを出力する。"""
        output_dir = self.resolvedOutputDir()
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to create output directory: {e}")
            return

        base_name = _base_output_name(self.video_file, self.gpx_file)
        csv_path = os.path.join(output_dir, base_name + FRAMES_CSV_SUFFIX)
        json_path = os.path.join(output_dir, base_name + NAVIGATION_JSON_SUFFIX)
        matched_csv_paths = [os.path.join(output_dir, base_name + MATCHED_FRAMES_CSV_SUFFIX)]
        if self.video_file:
            # WEBビューア単体でも見つけやすいよう、動画ディレクトリ側にもmatched CSVを置く。
            video_dir_matched_csv = os.path.join(
                os.path.dirname(self.video_file),
                base_name + MATCHED_FRAMES_CSV_SUFFIX
            )
            if video_dir_matched_csv not in matched_csv_paths:
                matched_csv_paths.append(video_dir_matched_csv)

        if matches is None or match_count is None:
            matches, match_count, match_error = self.resolveKpMatches(rows)
            if match_error:
                self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to match KP CSV: {match_error}")

        fieldnames = [
            "frame",
            "source_frame",
            "frame_shift",
            "image_path",
            "timestamp",
            "latitude",
            "longitude",
            "aligned_latitude",
            "aligned_longitude",
            "kp",
            "kp_distance_m",
            "kp_latitude",
            "kp_longitude",
            "kp_match",
        ]

        navigation_nodes = []
        try:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()

                frame_shift = self.frame_shift.value()
                for row_index, (frame_num, source_frame, time, lat, lon) in enumerate(rows):
                    match = matches[row_index]
                    aligned_lat = match["lat"] if match else lat
                    aligned_lon = match["lon"] if match else lon
                    image_path = self.frameImageRelativePath(frame_num, output_dir)

                    writer.writerow({
                        "frame": frame_num,
                        "source_frame": source_frame,
                        "frame_shift": frame_shift,
                        "image_path": image_path,
                        "timestamp": _format_timestamp(time),
                        "latitude": f"{lat:.9f}",
                        "longitude": f"{lon:.9f}",
                        "aligned_latitude": f"{aligned_lat:.9f}",
                        "aligned_longitude": f"{aligned_lon:.9f}",
                        "kp": match["kp"] if match else "",
                        "kp_distance_m": _format_distance(match["distance_m"] if match else None),
                        "kp_latitude": f"{match['lat']:.9f}" if match else "",
                        "kp_longitude": f"{match['lon']:.9f}" if match else "",
                        "kp_match": "1" if match else "0",
                    })

                    if match:
                        # KPマッチ済み点だけをWEBビューアPrev/Next用ノードにする。
                        navigation_nodes.append({
                            "index": len(navigation_nodes),
                            "frame": frame_num,
                            "source_frame": source_frame,
                            "frame_shift": frame_shift,
                            "image_path": image_path,
                            "timestamp": _format_timestamp(time),
                            "kp": match["kp"],
                            "kp_distance_m": round(match["distance_m"], 3),
                            "latitude": match["lat"],
                            "longitude": match["lon"],
                        })

            if self.kp_file:
                for index, node in enumerate(navigation_nodes):
                    previous_node = navigation_nodes[index - 1] if index > 0 else None
                    next_node = navigation_nodes[index + 1] if index < len(navigation_nodes) - 1 else None
                    node["previous_index"] = previous_node["index"] if previous_node else None
                    node["previous_frame"] = previous_node["frame"] if previous_node else None
                    node["next_index"] = next_node["index"] if next_node else None
                    node["next_frame"] = next_node["frame"] if next_node else None

                # navigation.jsonはWEB版360ビューアが前後移動情報を読むための構造化出力。
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "video": self.video_file,
                    "gpx": self.gpx_file,
                    "kp_csv": self.kp_file,
                    "kp_tolerance_m": self.kp_tolerance.value(),
                    "frame_shift": self.frame_shift.value(),
                    "frames_csv": os.path.basename(csv_path),
                    "matched_frames_csv": [os.path.basename(path) for path in matched_csv_paths],
                    "node_count": len(navigation_nodes),
                    "nodes": navigation_nodes,
                }
                with open(json_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)

                matched_fieldnames = [
                    "frame_index",
                    "frame",
                    "source_frame",
                    "image_path",
                    "kp",
                    "kp_distance_m",
                    "latitude",
                    "longitude",
                ]
                for matched_csv_path in matched_csv_paths:
                    with open(matched_csv_path, "w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=matched_fieldnames)
                        writer.writeheader()
                        for node in navigation_nodes:
                            writer.writerow({
                                "frame_index": node["frame"],
                                "frame": node["frame"],
                                "source_frame": node["source_frame"],
                                "image_path": self.frameImageRelativePath(
                                    node["frame"],
                                    os.path.dirname(matched_csv_path)
                                ),
                                "kp": node["kp"],
                                "kp_distance_m": f"{node['kp_distance_m']:.3f}",
                                "latitude": f"{node['latitude']:.9f}",
                                "longitude": f"{node['longitude']:.9f}",
                            })
        except OSError as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to save output files: {e}")
            return

        self.iface.messageBar().pushMessage(
            PLUGIN_TITLE,
            f"Saved frame CSV: {csv_path}"
        )
        if self.kp_file:
            if match_count == 0:
                self.iface.messageBar().pushWarning(
                    PLUGIN_TITLE,
                    f"No KP matches within {self.kp_tolerance.value():.1f} m."
                )
            self.iface.messageBar().pushMessage(
                PLUGIN_TITLE,
                f"Saved navigation JSON: {json_path}"
            )
            self.iface.messageBar().pushMessage(
                PLUGIN_TITLE,
                f"Saved viewer matched CSV: {matched_csv_paths[-1]}"
            )

    def showError(self, error):
        """workerからのエラーをUIへ反映し、必要に応じてmessageBarへ表示する。"""
        self.process_button.setEnabled(True)
        self.progress_bar.setValue(0)
        if self.session_closing and error == "Processing cancelled.":
            print(f"Error: {error}")
            return

        print(f"Error: {error}")
        self.iface.messageBar().pushWarning(PLUGIN_TITLE, error)

    def unload(self):
        """QGISがプラグインをアンロードする際に、メニューとツールバーを片付ける。"""
        self.removeKeyboardFilter()
        self.cleanupSession(close_panel=True, remove_layers=True, show_message=False)

        # アクションをメニューから削除
        if self.action is not None:
            self.iface.removePluginMenu(PLUGIN_TITLE, self.action)
        if self.viewer_action is not None:
            self.iface.removePluginMenu(PLUGIN_TITLE, self.viewer_action)
        if self.exit_action is not None:
            self.iface.removePluginMenu(PLUGIN_TITLE, self.exit_action)

        # ツールバーを削除
        if self.toolbar and self.toolbar.parent() is not None:
            self.toolbar.parent().removeToolBar(self.toolbar)
        self.action = None
        self.viewer_action = None
        self.exit_action = None
        self.toolbar = None

    def closeEvent(self, event):
        """パネル右上の閉じる操作ではセッション終了までは行わず、UIだけ閉じる。"""
        event.accept()

def classFactory(iface):
    """QGISがプラグインインスタンスを生成するためのエントリポイント。"""
    return GPXVideoPlugin(iface)
