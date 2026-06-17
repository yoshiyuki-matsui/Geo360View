"""GPXVideoProcessor QGISプラグインのUIと全体制御。"""

import csv
from datetime import datetime, timezone
import json
import os
import sqlite3

from qgis.PyQt import QtGui, QtWidgets
from qgis.PyQt.QtWidgets import (
    QWidget, QPushButton, QFileDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox
)
from qgis.PyQt.QtCore import (
    QEvent, QSettings, QTimer, QVariant, Qt
)
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsField, QgsVectorFileWriter, QgsCoordinateTransform
)
try:
    from qgis.core import QgsEditorWidgetSetup
except ImportError:
    QgsEditorWidgetSetup = None

from .config import (
    validate_frame_extract_config,
    validate_navigation_config,
    validate_process_config,
    validate_radar_config,
    validate_viewer_config,
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
from .messages import message_text, ui_text
from .processor import GPXVideoProcessor
from .radar import RadarMixin
from .viewer_controller import ViewerControllerMixin

QAction = getattr(QtWidgets, "QAction", None) or QtGui.QAction

GPKG_FRAME_LAYER_NAME = "video_gpx_points"
GPKG_TARGET_LAYER_NAME = "click_targets_360"
GPKG_JOB_METADATA_TABLE = "gpx_video_processor_job_metadata"

VIEWER_TARGET_HIDDEN_COLUMNS = (
    "target_id",
    "forward_m",
    "bearing_deg",
    "yaw_delta",
    "target_yaw",
    "target_pitch",
    "view_yaw",
    "view_pitch",
    "view_zoom",
    "source_lat",
    "source_lon",
    "projection",
)



class GPXVideoPlugin(ViewerControllerMixin, RadarMixin, FrameExtractMixin, QWidget):
    """GPX/動画同期、360Viewer連携、QGISレイヤ生成を統括するプラグイン本体。"""

    def __init__(self, iface, parent=None):
        """QGIS ifaceと、セッション中に共有する状態を初期化する。"""
        super().__init__(parent)
        self.iface = iface
        self.message_locale = os.environ.get("GPX_VIDEO_PROCESSOR_LOCALE", "ja")
        self.gpx_file = ""
        self.video_file = ""
        self.kp_file = ""
        self.database_file = ""
        self.database_restore_mode = False
        self.output_dir = ""
        self.output_dir_user_selected = False
        self.last_rows = []
        self.last_process_config = None
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
        self.viewer_camera_height_m = 1.5
        self.viewer_camera_height_dirty = False
        self.viewer_hud_height_scale_value = 1.0
        self.viewer_hud_height_scale_dirty = False
        self.created_layer_ids = []
        self.frame_layer_id = None
        self.target_layer_id = None
        self.loaded_gpkg_path = ""
        self.saved_viewer_target_keys = set()
        self.session_closing = False
        self.current_frame = None
        self.viewer_session_timer = None
        self.last_viewer_session_signature = None
        self.radar_grid_band = None
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

    def uiMessage(self, key, **params):
        """現在localeでユーザ向けメッセージを組み立てる。"""
        return message_text(key, self.message_locale, **params)

    def uiText(self, key, **params):
        """現在localeでUIラベル/tooltip文言を組み立てる。"""
        return ui_text(key, self.message_locale, **params)

    def applyHelp(self, help_key, *widgets):
        """同じ説明文を関連UI部品のtooltip/What's Thisへ付与する。"""
        text = self.uiText(help_key)
        for widget in widgets:
            widget.setToolTip(text)
            widget.setWhatsThis(text)

    def notifyInfo(self, key, **params):
        """QGIS messageBarへ正常系メッセージを表示する。"""
        self.iface.messageBar().pushMessage(PLUGIN_TITLE, self.uiMessage(key, **params))

    def notifyWarning(self, key, **params):
        """QGIS messageBarへ警告メッセージを表示する。"""
        self.iface.messageBar().pushWarning(PLUGIN_TITLE, self.uiMessage(key, **params))

    def notifyInfoText(self, text):
        """既存の詳細文字列をそのまま正常系メッセージとして表示する移行用入口。"""
        self.iface.messageBar().pushMessage(PLUGIN_TITLE, text)

    def notifyWarningText(self, text):
        """既存の詳細文字列をそのまま警告メッセージとして表示する移行用入口。"""
        self.iface.messageBar().pushWarning(PLUGIN_TITLE, text)

    def validationErrorText(self, errors, limit=5):
        """複数のvalidationエラーをmessageBar向けの短い文へまとめる。"""
        visible = [str(error) for error in errors[:limit]]
        if len(errors) > limit:
            visible.append(f"and {len(errors) - limit} more")
        return "; ".join(visible)

    def notifyValidationErrors(self, errors):
        """入力検証エラーをユーザ向け警告として表示する。"""
        self.notifyWarning("input_validation_failed", errors=self.validationErrorText(errors))

    def collectProcessConfig(self, show_errors=True):
        """Load/Processタブの入力をProcessConfigへ束ね、処理前に検証する。"""
        config, errors = validate_process_config({
            "gpx_file": self.gpx_file,
            "video_file": self.video_file,
            "output_dir": self.resolvedOutputDir(),
            "kp_file": self.kp_file,
            "frame_shift": self.frame_shift.value(),
            "kp_tolerance_m": self.kp_tolerance.value(),
        })
        if errors:
            if show_errors:
                self.notifyValidationErrors(errors)
            return None
        return config

    def collectFrameExtractConfig(self, frame_num, show_errors=True):
        """単一フレーム抽出の入力をFrameExtractConfigへ束ねる。"""
        config, errors = validate_frame_extract_config({
            "video_file": self.video_file,
            "frame_number": frame_num,
            "output_dir": self.resolvedOutputDir(),
        })
        if errors:
            if show_errors:
                self.notifyValidationErrors(errors)
            return None
        return config

    def collectNavigationConfig(self, show_errors=True):
        """ナビゲーション入力をNavigationConfigへ束ねる。"""
        config, errors = validate_navigation_config({
            "mode": self.nav_mode.currentData(),
            "step": self.nav_step.value(),
            "fast_step": self.nav_fast_step.value(),
            "follow": self.follow_frame_checkbox.isChecked(),
        })
        if errors:
            if show_errors:
                self.notifyValidationErrors(errors)
            return None
        return config

    def collectRadarConfig(self, show_errors=True):
        """レーダ距離校正入力をRadarConfigへ束ねる。"""
        config, errors = validate_radar_config({
            "range_m": self.radar_radius.value(),
            "scale": self.radar_scale.value(),
            "cal_fov_deg": self.radar_cal_fov.value(),
            "cal_dist_m": self.radar_cal_distance.value(),
            "offset_deg": self.radar_offset.currentData(),
        })
        if errors:
            if show_errors:
                self.notifyValidationErrors(errors)
            return None
        return config

    def collectViewerConfig(self, show_errors=True):
        """360Viewer実行時設定をViewerConfigへ束ねる。"""
        self.loadViewerDefaults()
        config, errors = validate_viewer_config({
            "host": self.viewer_host,
            "port": self.viewer_port,
            "video_dir": self.viewerVideoDir(),
            "session_json_path": self.viewerSessionPath(),
            "cache_dir": self.viewerCacheDir(),
            "jpeg_quality": self.viewer_jpeg_quality,
            "progressive_jpeg": self.viewer_progressive_jpeg,
            "max_width": self.viewer_max_width,
            "camera_height_m": self.viewerCameraHeightValue(),
            "hud_height_scale": self.viewerHudHeightScaleValue(),
        })
        if errors:
            if show_errors:
                self.notifyValidationErrors(errors)
            return None
        return config

    def processFrameShiftValue(self):
        """実行中Processのframe shiftを、後続レイヤ/CSV出力で一貫利用する。"""
        config = getattr(self, "last_process_config", None)
        if config is not None:
            return int(config.frame_shift)
        return int(self.frame_shift.value())

    def processKpFileValue(self):
        """実行中ProcessのKP CSVパスを返す。未指定なら空文字を返す。"""
        config = getattr(self, "last_process_config", None)
        if config is not None:
            return config.kp_file or ""
        return self.kp_file

    def processKpToleranceValue(self):
        """実行中ProcessのKP許容距離を返す。"""
        config = getattr(self, "last_process_config", None)
        if config is not None:
            return float(config.kp_tolerance_m)
        return float(self.kp_tolerance.value())

    def initGui(self):
        """QGISメニュー/ツールバー/パネルUIを一度だけ構築する。"""
        if self._gui_initialized:
            return

        self.setWindowTitle(self.uiText("ui.window.title"))
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
        self.gpx_path = self.makePathLabel(self.uiText("ui.path.no_gpx"))
        self.gpx_button = QPushButton(self.uiText("ui.button.browse"))
        self.gpx_button.clicked.connect(self.selectGPX)
        self.applyHelp("ui.help.gpx", self.gpx_label, self.gpx_button)
        set_fixed_width(self.gpx_button, 72)

        self.video_label = QLabel("Video:")
        self.video_path = self.makePathLabel(self.uiText("ui.path.no_video"))
        self.video_button = QPushButton(self.uiText("ui.button.browse"))
        self.video_button.clicked.connect(self.selectVideo)
        self.applyHelp("ui.help.video", self.video_label, self.video_button)
        set_fixed_width(self.video_button, 72)

        self.database_label = QLabel("GPKG:")
        self.database_path = self.makePathLabel(self.uiText("ui.path.no_database"))
        self.database_button = QPushButton(self.uiText("ui.button.load_database"))
        self.database_button.clicked.connect(self.selectDatabase)
        self.applyHelp("ui.help.database", self.database_label, self.database_button)
        set_fixed_width(self.database_button, 72)

        self.kp_label = QLabel("KP CSV:")
        self.kp_path = self.makePathLabel(self.uiText("ui.path.no_kp"))
        self.kp_button = QPushButton(self.uiText("ui.button.browse"))
        self.kp_button.clicked.connect(self.selectKP)
        self.applyHelp("ui.help.kp", self.kp_label, self.kp_button)
        set_fixed_width(self.kp_button, 72)

        for label in (self.gpx_label, self.video_label, self.database_label, self.kp_label):
            label.setMinimumWidth(52)

        self.kp_tolerance_label = QLabel("KP tol:")
        self.kp_tolerance = QDoubleSpinBox()
        self.kp_tolerance.setRange(0.0, 10000.0)
        self.kp_tolerance.setDecimals(1)
        self.kp_tolerance.setSingleStep(0.5)
        self.kp_tolerance.setValue(5.0)
        self.kp_tolerance.setSuffix(" m")
        self.applyHelp("ui.help.kp_tolerance", self.kp_tolerance_label, self.kp_tolerance)
        set_fixed_width(self.kp_tolerance, 82)

        self.frame_shift_label = QLabel("Shift:")
        self.frame_shift = QSpinBox()
        self.frame_shift.setRange(-1000000, 1000000)
        self.frame_shift.setSingleStep(1)
        self.frame_shift.setValue(0)
        self.frame_shift.setSuffix(" fr")
        self.applyHelp("ui.help.frame_shift", self.frame_shift_label, self.frame_shift)
        set_fixed_width(self.frame_shift, 92)

        self.output_label = QLabel("Output:")
        self.output_path = self.makePathLabel(self.uiText("ui.path.default_output"))
        self.output_button = QPushButton(self.uiText("ui.button.browse"))
        self.output_button.clicked.connect(self.selectOutputDir)
        self.output_label.setMinimumWidth(52)
        self.applyHelp("ui.help.output", self.output_label, self.output_button)
        set_fixed_width(self.output_button, 72)

        self.extract_frame_label = QLabel("Frame:")
        self.extract_frame = QSpinBox()
        self.extract_frame.setRange(0, 1000000000)
        self.extract_frame.setSingleStep(1)
        self.extract_frame.setValue(0)
        self.applyHelp("ui.help.frame", self.extract_frame_label, self.extract_frame)
        set_fixed_width(self.extract_frame, 92)
        self.extract_button = QPushButton(self.uiText("ui.button.extract"))
        self.extract_button.clicked.connect(self.extractTestFrame)
        self.applyHelp("ui.help.extract", self.extract_button)
        set_fixed_width(self.extract_button, 72)
        self.follow_frame_checkbox = QCheckBox(self.uiText("ui.checkbox.follow"))
        self.follow_frame_checkbox.setChecked(True)
        self.applyHelp("ui.help.follow", self.follow_frame_checkbox)

        self.nav_label = QLabel("Nav:")
        self.current_frame_label = QLabel(self.uiText("ui.status.current_empty"))
        self.nav_mode = QComboBox()
        self.nav_mode.addItem("Frame step", "frame")
        self.nav_mode.addItem("Layer point", "layer")
        self.nav_mode.addItem("Picked point", "picked")
        self.nav_mode.addItem("KP matched CSV", "kp")
        self.applyHelp("ui.help.nav_mode", self.nav_label, self.nav_mode)
        set_fixed_width(self.nav_mode, 126)
        self.nav_step_label = QLabel("Step:")
        self.nav_step = QSpinBox()
        self.nav_step.setRange(1, 1000000)
        self.nav_step.setValue(1)
        self.applyHelp("ui.help.nav_step", self.nav_step_label, self.nav_step)
        set_fixed_width(self.nav_step, 76)
        self.nav_fast_label = QLabel("Fast:")
        self.nav_fast_step = QSpinBox()
        self.nav_fast_step.setRange(1, 1000000)
        self.nav_fast_step.setValue(30)
        self.applyHelp("ui.help.nav_fast", self.nav_fast_label, self.nav_fast_step)
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
        self.applyHelp("ui.help.radar_range", self.radar_radius_label, self.radar_radius)
        set_fixed_width(self.radar_radius, 82)
        self.radar_scale_label = QLabel("Scale:")
        self.radar_scale = QDoubleSpinBox()
        self.radar_scale.setRange(0.1, 20.0)
        self.radar_scale.setDecimals(1)
        self.radar_scale.setSingleStep(0.1)
        self.radar_scale.setValue(1.0)
        self.radar_scale.setSuffix(" x")
        self.applyHelp("ui.help.radar_scale", self.radar_scale_label, self.radar_scale)
        set_fixed_width(self.radar_scale, 78)
        self.viewer_camera_height_label = QLabel("CamH:")
        self.viewer_camera_height = QDoubleSpinBox()
        self.viewer_camera_height.setRange(0.1, 20.0)
        self.viewer_camera_height.setDecimals(1)
        self.viewer_camera_height.setSingleStep(0.1)
        self.viewer_camera_height.setValue(self.viewer_camera_height_m)
        self.viewer_camera_height.setSuffix(" m")
        self.viewer_camera_height.valueChanged.connect(self.onViewerCameraHeightChanged)
        self.applyHelp("ui.help.camera_height", self.viewer_camera_height_label, self.viewer_camera_height)
        set_fixed_width(self.viewer_camera_height, 78)
        self.viewer_hud_height_scale_label = QLabel("HudH:")
        self.viewer_hud_height_scale = QDoubleSpinBox()
        self.viewer_hud_height_scale.setRange(0.1, 5.0)
        self.viewer_hud_height_scale.setDecimals(2)
        self.viewer_hud_height_scale.setSingleStep(0.05)
        self.viewer_hud_height_scale.setValue(self.viewer_hud_height_scale_value)
        self.viewer_hud_height_scale.setSuffix(" x")
        self.viewer_hud_height_scale.valueChanged.connect(self.onViewerHudHeightScaleChanged)
        self.applyHelp("ui.help.hud_height_scale", self.viewer_hud_height_scale_label, self.viewer_hud_height_scale)
        set_fixed_width(self.viewer_hud_height_scale, 76)
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
        self.applyHelp("ui.help.cal_fov", self.radar_cal_fov_label, self.radar_cal_fov)
        set_fixed_width(self.radar_cal_fov, 92)
        self.radar_cal_distance_label = QLabel("CalDist:")
        self.radar_cal_distance = QDoubleSpinBox()
        self.radar_cal_distance.setRange(0.1, 500.0)
        self.radar_cal_distance.setDecimals(1)
        self.radar_cal_distance.setSingleStep(0.5)
        self.radar_cal_distance.setValue(5.0)
        self.radar_cal_distance.setSuffix(" m")
        self.applyHelp("ui.help.cal_dist", self.radar_cal_distance_label, self.radar_cal_distance)
        set_fixed_width(self.radar_cal_distance, 84)
        self.use_current_fov_button = QPushButton(self.uiText("ui.button.use_fov"))
        self.use_current_fov_button.clicked.connect(self.useCurrentFovForCalibration)
        self.applyHelp("ui.help.use_fov", self.use_current_fov_button)
        set_fixed_width(self.use_current_fov_button, 74)
        self.radar_offset_label = QLabel("Offset:")
        self.radar_offset = QComboBox()
        for offset in (0, 90, 180, 270):
            self.radar_offset.addItem(f"{offset}deg", offset)
        self.applyHelp("ui.help.offset", self.radar_offset_label, self.radar_offset)
        set_fixed_width(self.radar_offset, 78)

        self.click_mode_button = QPushButton(self.uiText("ui.button.click_layer"))
        self.click_mode_button.clicked.connect(self.activateClickMode)
        self.applyHelp("ui.help.click_layer", self.click_mode_button)
        self.stop_click_mode_button = QPushButton(self.uiText("ui.button.stop_click"))
        self.stop_click_mode_button.clicked.connect(self.deactivateClickMode)
        self.applyHelp("ui.help.stop_click", self.stop_click_mode_button)
        set_fixed_width(self.click_mode_button, 96)
        set_fixed_width(self.stop_click_mode_button, 82)

        self.preview_info = QLabel(self.uiText("ui.preview.empty"))
        self.preview_info.setWordWrap(True)
        self.preview_info.setMinimumHeight(38)
        self.preview_info.setMaximumHeight(44)
        self.preview_info.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        self.preview_label.setMaximumHeight(190)
        self.preview_label.setText(self.uiText("ui.preview.title"))

        self.process_button = QPushButton(self.uiText("ui.button.process"))
        self.process_button.clicked.connect(self.processData)
        self.applyHelp("ui.help.process", self.process_button)
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

        compact_row(load_layout, self.database_label, self.database_path, self.database_button)
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
            self.nav_step_label,
            self.nav_step,
            self.nav_fast_label,
            self.nav_fast_step,
            "stretch",
        )
        compact_row(
            control_layout,
            self.radar_radius_label,
            self.radar_radius,
            self.radar_scale_label,
            self.radar_scale,
            self.viewer_camera_height_label,
            self.viewer_camera_height,
            self.viewer_hud_height_scale_label,
            self.viewer_hud_height_scale,
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
        self.move_label = QLabel(self.uiText("ui.label.move"))
        compact_row(control_layout, self.move_label, self.nav_button_layout, "stretch")
        control_layout.addStretch(1)

        tabs.addTab(load_tab, self.uiText("ui.tab.load"))
        tabs.addTab(control_tab, self.uiText("ui.tab.control"))
        layout.addWidget(tabs)

        self.setLayout(layout)

        # アクションを定義
        self.action = QAction(self.uiText("ui.action.start"), self)
        self.action.setStatusTip(self.uiText("ui.help.process"))
        self.action.triggered.connect(self.run)
        self.viewer_action = QAction(self.uiText("ui.action.open_viewer"), self)
        self.viewer_action.setStatusTip(self.uiText("ui.help.video"))
        self.viewer_action.triggered.connect(self.openViewer)
        self.exit_action = QAction(self.uiText("ui.action.exit"), self)
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
        self.installKeyboardFilter()
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

    def setInputWidgetsEnabled(self, enabled):
        """通常処理入力系UIの有効/無効をまとめて切り替える。"""
        for widget in (
            self.gpx_button,
            self.video_button,
            self.kp_button,
            self.output_button,
            self.frame_shift,
            self.kp_tolerance,
            self.process_button,
        ):
            widget.setEnabled(bool(enabled))

    def setDatabaseRestoreMode(self, enabled):
        """GPKG復元後は段取り替え系操作を禁止する。"""
        self.database_restore_mode = bool(enabled)
        if getattr(self, "_gui_initialized", False):
            self.setInputWidgetsEnabled(not self.database_restore_mode)
            self.database_button.setEnabled(not self.database_restore_mode)

    def dialogSettingsKey(self, name):
        """ファイル選択ダイアログの最終位置保存キーを返す。"""
        return f"{PLUGIN_TITLE}/dialogs/{name}"

    def existingDialogDirectory(self, path):
        """ファイル/フォルダ候補から、存在する開始ディレクトリを返す。"""
        if not path:
            return ""
        text = str(path).strip()
        if not text:
            return ""
        if os.path.isdir(text):
            return text
        parent = os.path.dirname(text)
        if parent and os.path.isdir(parent):
            return parent
        return ""

    def dialogStartDir(self, name, *fallbacks):
        """前回位置と現在状態からファイル選択ダイアログの開始位置を決める。"""
        settings = QSettings()
        candidates = list(fallbacks)
        candidates.append(settings.value(self.dialogSettingsKey(name), ""))
        candidates.append(settings.value(self.dialogSettingsKey("last"), ""))
        candidates.append(os.path.expanduser("~"))
        for candidate in candidates:
            directory = self.existingDialogDirectory(candidate)
            if directory:
                return directory
        return ""

    def rememberDialogPath(self, name, path):
        """選択したファイル/フォルダの親ディレクトリを次回用に保存する。"""
        directory = self.existingDialogDirectory(path)
        if not directory:
            return
        settings = QSettings()
        settings.setValue(self.dialogSettingsKey(name), directory)
        settings.setValue(self.dialogSettingsKey("last"), directory)

    def selectGPX(self):
        """GPXファイルを選択し、入力状態を更新する。"""
        if self.database_restore_mode:
            return
        start_dir = self.dialogStartDir("gpx", self.gpx_file, self.video_file, self.output_dir)
        file_path, _ = QFileDialog.getOpenFileName(self, "Select GPX File", start_dir, "GPX Files (*.gpx)")
        if file_path:
            self.rememberDialogPath("gpx", file_path)
            self.gpx_file = file_path
            self.setPathLabel(self.gpx_path, file_path, self.uiText("ui.path.no_gpx"))

    def selectVideo(self):
        """MP4動画を選択し、出力先既定値とビューア設定を更新する。"""
        if self.database_restore_mode:
            return
        start_dir = self.dialogStartDir("video", self.video_file, self.gpx_file, self.output_dir)
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", start_dir, "MP4 Files (*.mp4)")
        if file_path:
            self.rememberDialogPath("video", file_path)
            self.video_file = file_path
            self.setPathLabel(self.video_path, file_path, self.uiText("ui.path.no_video"))
            self.viewer_browser_opened = False
            self.setCurrentFrame(None)
            if not self.output_dir_user_selected:
                self.setPathLabel(self.output_path, self.defaultOutputDir(), self.uiText("ui.path.default_output"))
            self.setViewerCameraHeightValue(1.5)
            self.viewer_camera_height_dirty = False
            self.setViewerHudHeightScaleValue(1.0)
            self.viewer_hud_height_scale_dirty = False
            self.loadViewerSessionCameraHeight()
            self.writeViewerRuntimeConfig(show_error=False)

    def selectKP(self):
        """KPマスタCSVを選択する。KP未指定でも通常処理は可能。"""
        if self.database_restore_mode:
            return
        start_dir = self.dialogStartDir("kp", self.kp_file, self.gpx_file, self.video_file, self.output_dir)
        file_path, _ = QFileDialog.getOpenFileName(self, "Select KP CSV", start_dir, "CSV Files (*.csv)")
        if file_path:
            self.rememberDialogPath("kp", file_path)
            self.kp_file = file_path
            self.setPathLabel(self.kp_path, file_path, self.uiText("ui.path.no_kp"))

    def selectOutputDir(self):
        """CSV/画像/セッションJSONの出力先ディレクトリを選択する。"""
        if self.database_restore_mode:
            return
        start_dir = self.dialogStartDir("output", self.output_dir, self.defaultOutputDir(), self.video_file)
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory", start_dir)
        if directory:
            self.rememberDialogPath("output", directory)
            self.output_dir = directory
            self.output_dir_user_selected = True
            self.setPathLabel(self.output_path, directory, self.uiText("ui.path.default_output"))
            self.loadViewerSessionCameraHeight(force=True)
            self.writeViewerRuntimeConfig(show_error=False)

    def selectDatabase(self):
        """既存GeoPackageを選択し、標準内部レイヤを作業用メモリレイヤへ読み込む。"""
        if self.database_restore_mode:
            return
        start_dir = self.dialogStartDir("gpkg", self.database_file, self.loaded_gpkg_path, self.resolvedOutputDir())
        file_path, _ = QFileDialog.getOpenFileName(self, "Select GeoPackage", start_dir, "GeoPackage (*.gpkg)")
        if not file_path:
            return
        self.rememberDialogPath("gpkg", file_path)
        self.loadSessionDatabase(file_path)

    def defaultOutputDir(self):
        """選択動画名を既定出力ディレクトリ名にし、動画由来を明示する。"""
        if self.video_file:
            video_dir = os.path.dirname(self.video_file)
            return os.path.join(video_dir, _base_output_name(self.video_file, ""))

        base_path = self.gpx_file or __file__
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
            self.current_frame_label.setText(self.uiText("ui.status.current_empty"))
            return

        self.current_frame = int(frame_num)
        self.extract_frame.setValue(max(0, self.current_frame))
        self.current_frame_label.setText(self.uiText("ui.status.current", frame=self.current_frame))

    def currentFrameValue(self):
        """現在フレーム状態を返す。未設定ならUIのFrame入力値を使う。"""
        if self.current_frame is not None:
            return int(self.current_frame)
        return int(self.extract_frame.value())

    def displayFrame(self, frame_num, feature=None):
        """指定フレームをビューアへ送り、少し遅らせてQGISプレビューを抽出する。"""
        frame_num = int(frame_num)
        if frame_num < 0:
            self.notifyWarning("frame_number_nonnegative")
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
            self.notifyWarning("center_map_failed", error=e)

    def displayCurrentFrame(self):
        """現在フレームを再表示する。キーボードSpace操作からも使う。"""
        frame_num = self.currentFrameValue()
        self.displayFrame(frame_num, feature=self.findFeatureByFrame(frame_num))

    def currentViewerFovFromSession(self):
        """レーダ未描画時でもviewer_session.jsonのzoomから現在FOVを復元する。"""
        path = self.viewerSessionPath()
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict):
            return None
        current_video = os.path.basename(self.video_file or "")
        session_video = state.get("video")
        if current_video and session_video and session_video != current_video:
            return None
        zoom = _parse_float(state.get("zoom"))
        if zoom is None:
            return None
        return self.viewerFov({"zoom": zoom})

    def useCurrentFovForCalibration(self):
        """現在ビューアFOVを距離校正基準FOVへ反映する。"""
        fov = getattr(self, "current_viewer_fov", None)
        if fov is None:
            fov = self.currentViewerFovFromSession()
            if fov is None:
                self.notifyWarning("current_viewer_fov_unavailable")
                return
        self.radar_cal_fov.setValue(float(fov))
        self.notifyInfo("calibration_fov_set", fov=float(fov))

    def viewerCameraHeightValue(self):
        """ジョブ条件として扱うカメラ高さをUIまたは既定値から取得する。"""
        widget = getattr(self, "viewer_camera_height", None)
        if widget is not None:
            value = float(widget.value())
        else:
            value = float(getattr(self, "viewer_camera_height_m", 1.5))
        return max(0.1, min(20.0, value))

    def setViewerCameraHeightValue(self, value, mark_dirty=False):
        """セッション等から読んだカメラ高さをUI状態へ安全に反映する。"""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        numeric = max(0.1, min(20.0, numeric))
        self.viewer_camera_height_m = numeric
        if mark_dirty:
            self.viewer_camera_height_dirty = True

        widget = getattr(self, "viewer_camera_height", None)
        if widget is not None and abs(float(widget.value()) - numeric) > 0.0005:
            previous_blocked = widget.blockSignals(True)
            try:
                widget.setValue(numeric)
            finally:
                widget.blockSignals(previous_blocked)
        return True

    def viewerHudHeightScaleValue(self):
        """WEBビューア地面範囲円だけに使うカメラ高倍率を取得する。"""
        widget = getattr(self, "viewer_hud_height_scale", None)
        if widget is not None:
            value = float(widget.value())
        else:
            value = float(getattr(self, "viewer_hud_height_scale_value", 1.0))
        return max(0.1, min(5.0, value))

    def setViewerHudHeightScaleValue(self, value, mark_dirty=False):
        """セッション等から読んだHUD高さ倍率をUI状態へ安全に反映する。"""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        numeric = max(0.1, min(5.0, numeric))
        self.viewer_hud_height_scale_value = numeric
        if mark_dirty:
            self.viewer_hud_height_scale_dirty = True

        widget = getattr(self, "viewer_hud_height_scale", None)
        if widget is not None and abs(float(widget.value()) - numeric) > 0.0005:
            previous_blocked = widget.blockSignals(True)
            try:
                widget.setValue(numeric)
            finally:
                widget.blockSignals(previous_blocked)
        return True

    def loadViewerSessionCameraHeight(self, force=False):
        """既存viewer_session.jsonがあれば、ジョブ固有のカメラ高さを復元する。"""
        camera_dirty = getattr(self, "viewer_camera_height_dirty", False)
        hud_dirty = getattr(self, "viewer_hud_height_scale_dirty", False)
        if camera_dirty and hud_dirty and not force:
            return False
        path = self.viewerSessionPath()
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(state, dict):
            return False
        current_video = os.path.basename(self.video_file) if self.video_file else ""
        session_video = state.get("video")
        if current_video and session_video and session_video != current_video:
            return False
        restored_camera = False
        restored_hud = False
        if "viewer_camera_height_m" in state and (force or not camera_dirty):
            restored_camera = self.setViewerCameraHeightValue(state.get("viewer_camera_height_m"))
        if "viewer_hud_height_scale" in state and (force or not hud_dirty):
            restored_hud = self.setViewerHudHeightScaleValue(state.get("viewer_hud_height_scale"))
        if restored_camera:
            self.viewer_camera_height_dirty = False
        if restored_hud:
            self.viewer_hud_height_scale_dirty = False
        return restored_camera or restored_hud

    def writeViewerCameraHeightSessionValue(self):
        """動画選択済みならカメラ高さとHUD補正だけでもviewer_session.jsonへ残す。"""
        if not self.video_file:
            return False
        path = self.viewerSessionPath()
        current_video = os.path.basename(self.video_file)
        state = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    state = loaded
            except (OSError, json.JSONDecodeError):
                state = {}

        if state.get("video") not in (None, current_video):
            state = {}

        state["video"] = current_video
        state["viewer_camera_height_m"] = self.viewerCameraHeightValue()
        state["viewer_hud_height_scale"] = self.viewerHudHeightScaleValue()
        state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_path, path)
            return True
        except OSError:
            return False

    def writeViewerSessionState(self, state):
        """QGIS側で補完したビューア状態をviewer_session.jsonへ原子的に書き戻す。"""
        path = self.viewerSessionPath()
        state = dict(state)
        state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_path, path)
            return state
        except OSError:
            return None

    def onViewerCameraHeightChanged(self, _value):
        """カメラ高さ変更をランタイム設定と開いているビューアへ反映する。"""
        self.setViewerCameraHeightValue(self.viewerCameraHeightValue(), mark_dirty=True)
        self.writeViewerRuntimeConfig(show_error=False)
        self.writeViewerCameraHeightSessionValue()
        if self.current_frame is not None and self.viewerHealth(timeout=0.15):
            self.postViewerNavigation(self.current_frame)

    def onViewerHudHeightScaleChanged(self, _value):
        """HUD高さ倍率変更をランタイム設定と開いているビューアへ反映する。"""
        self.setViewerHudHeightScaleValue(self.viewerHudHeightScaleValue(), mark_dirty=True)
        self.writeViewerRuntimeConfig(show_error=False)
        self.writeViewerCameraHeightSessionValue()
        if self.current_frame is not None and self.viewerHealth(timeout=0.15):
            self.postViewerNavigation(self.current_frame)

    def activeFrameLayer(self):
        """ナビゲーション対象のVideo GPX Pointsレイヤを選択状態に依存せず取得する。"""
        project = QgsProject.instance()

        if self.frame_layer_id:
            layer = project.mapLayer(self.frame_layer_id)
            if self.isFrameReferenceLayer(layer):
                return layer

        for layer_id in reversed(self.created_layer_ids):
            layer = project.mapLayer(layer_id)
            if self.isFrameReferenceLayer(layer):
                self.frame_layer_id = layer.id()
                return layer

        if self.frame_click_tool is not None and self.frame_click_tool.layer is not None:
            layer = self.frame_click_tool.layer
            if self.isFrameReferenceLayer(layer):
                return layer

        layer = self.iface.activeLayer()
        if not self.isFrameReferenceLayer(layer):
            return None
        return layer

    def isFrameReferenceLayer(self, layer):
        """フレーム参照に使えるレイヤか確認する。クリック点保存レイヤは除外する。"""
        fields = self.layerFields(layer)
        if fields is None:
            return False
        return fields.indexFromName("frame") >= 0 and fields.indexFromName("target_id") < 0

    def isViewerTargetLayer(self, layer):
        """360クリック投影点レイヤとして扱えるスキーマか確認する。"""
        fields = self.layerFields(layer)
        if fields is None:
            return False
        return (
            fields.indexFromName("frame") >= 0
            and fields.indexFromName("target_id") >= 0
            and fields.indexFromName("target_yaw") >= 0
        )

    def layerFields(self, layer):
        """ベクタレイヤ以外ではNoneを返してfields()アクセスを安全化する。"""
        if layer is None or not hasattr(layer, "fields"):
            return None
        try:
            return layer.fields()
        except Exception:
            return None

    def isMemoryLayer(self, layer):
        """QGISメモリレイヤかを安全に判定する。"""
        try:
            return layer.providerType() == "memory"
        except Exception:
            return False

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

    def gpkgLayer(self, gpkg_path, layer_name, display_name):
        """GeoPackage内の指定レイヤをQGISレイヤとして開く。"""
        layer = QgsVectorLayer(f"{gpkg_path}|layername={layer_name}", display_name, "ogr")
        try:
            return layer if layer.isValid() else None
        except Exception:
            return None

    def cloneLayerToMemory(self, source_layer, display_name):
        """GPKGレイヤを編集用ではない一時メモリレイヤへコピーする。"""
        crs_authid = "EPSG:4326"
        try:
            authid = source_layer.crs().authid()
            if authid:
                crs_authid = authid
        except Exception:
            pass

        layer = QgsVectorLayer(f"Point?crs={crs_authid}", display_name, "memory")
        pr = layer.dataProvider()
        source_fields = source_layer.fields()
        copied_fields = [
            field for field in source_fields
            if str(field.name()).lower() not in ("fid", "ogc_fid")
        ]
        pr.addAttributes(copied_fields)
        layer.updateFields()

        features = []
        for source_feature in source_layer.getFeatures():
            feature = QgsFeature(layer.fields())
            try:
                feature.setGeometry(source_feature.geometry())
            except Exception:
                pass
            attributes = []
            for field in layer.fields():
                attributes.append(self.targetFeatureValue(source_feature, field.name()))
            feature.setAttributes(attributes)
            features.append(feature)

        if features:
            pr.addFeatures(features)
        layer.updateExtents()
        return layer

    def layerFeatureCount(self, layer):
        """featureCountが使えない場合も安全に件数を返す。"""
        if layer is None:
            return 0
        try:
            return int(layer.featureCount())
        except Exception:
            count = 0
            for _feature in layer.getFeatures():
                count += 1
            return count

    def firstLayerValue(self, layer, field_name):
        """指定フィールドの最初の非空値を返す。"""
        if layer is None:
            return None
        for feature in layer.getFeatures():
            value = self.targetFeatureValue(feature, field_name)
            if value not in (None, ""):
                return value
        return None

    def applyHiddenColumns(self, layer, hidden_columns):
        """保持はするが通常は見せない列をQGISレイヤ表示設定へ反映する。"""
        if layer is None:
            return False
        hidden = {str(column) for column in hidden_columns if column}
        if not hidden:
            return False

        applied = False
        try:
            layer.setCustomProperty(
                "gpx_video_processor/hidden_columns",
                json.dumps(sorted(hidden), ensure_ascii=False),
            )
        except Exception:
            pass

        try:
            config = layer.attributeTableConfig()
            try:
                config.update(layer.fields())
            except Exception:
                pass
            columns = config.columns()
            for column in columns:
                name = str(getattr(column, "name", "") or "")
                if not name:
                    continue
                try:
                    column.hidden = name in hidden
                    applied = True
                except Exception:
                    pass
            config.setColumns(columns)
            layer.setAttributeTableConfig(config)
        except Exception:
            pass

        if QgsEditorWidgetSetup is not None:
            for column in hidden:
                try:
                    index = layer.fields().indexFromName(column)
                except Exception:
                    index = -1
                if index < 0:
                    continue
                try:
                    layer.setEditorWidgetSetup(index, QgsEditorWidgetSetup("Hidden", {}))
                    applied = True
                except Exception:
                    pass
        return applied

    def applyViewerTargetHiddenColumns(self, layer):
        """360クリック点レイヤの監査用列を初期非表示にする。"""
        return self.applyHiddenColumns(layer, VIEWER_TARGET_HIDDEN_COLUMNS)

    def jobMetadataPayload(self):
        """GPKGへ残すジョブ入力・校正パラメータを返す。"""
        process_config = getattr(self, "last_process_config", None)
        return {
            "metadata_version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "gpx_file": process_config.gpx_file if process_config else self.gpx_file,
            "video_file": process_config.video_file if process_config else self.video_file,
            "kp_file": (process_config.kp_file or "") if process_config else self.kp_file,
            "output_dir": self.resolvedOutputDir(),
            "frame_shift": int(process_config.frame_shift) if process_config else int(self.frame_shift.value()),
            "kp_tolerance_m": float(process_config.kp_tolerance_m) if process_config else float(self.kp_tolerance.value()),
            "radar_range_m": float(self.radar_radius.value()),
            "radar_scale": float(self.radar_scale.value()),
            "radar_cal_fov_deg": float(self.radar_cal_fov.value()),
            "radar_cal_dist_m": float(self.radar_cal_distance.value()),
            "radar_offset_deg": int(self.radar_offset.currentData() or 0),
            "viewer_camera_height_m": float(self.viewerCameraHeightValue()),
            "viewer_hud_height_scale": float(self.viewerHudHeightScaleValue()),
            "nav_step": int(self.nav_step.value()),
            "nav_fast_step": int(self.nav_fast_step.value()),
            "follow_frame": bool(self.follow_frame_checkbox.isChecked()),
            "hidden_columns": {
                GPKG_TARGET_LAYER_NAME: list(VIEWER_TARGET_HIDDEN_COLUMNS),
            },
        }

    def writeJobMetadataToGpkg(self, gpkg_path):
        """GPKG内のプラグイン専用テーブルへジョブ状態を保存する。"""
        payload = self.jobMetadataPayload()
        with sqlite3.connect(gpkg_path) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {GPKG_JOB_METADATA_TABLE} (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(f"DELETE FROM {GPKG_JOB_METADATA_TABLE}")
            conn.executemany(
                f"INSERT INTO {GPKG_JOB_METADATA_TABLE} (key, value) VALUES (?, ?)",
                [(str(key), json.dumps(value, ensure_ascii=False)) for key, value in payload.items()],
            )
            conn.commit()

    def readJobMetadataFromGpkg(self, gpkg_path):
        """GPKG内のジョブメタデータを読む。未対応GPKGでは空dictを返す。"""
        try:
            with sqlite3.connect(gpkg_path) as conn:
                rows = conn.execute(
                    f"SELECT key, value FROM {GPKG_JOB_METADATA_TABLE}"
                ).fetchall()
        except sqlite3.Error:
            return {}

        metadata = {}
        for key, raw_value in rows:
            try:
                metadata[str(key)] = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError):
                metadata[str(key)] = raw_value
        return metadata

    def metadataText(self, metadata, key):
        """メタデータの文字列値を取得する。"""
        value = metadata.get(key) if isinstance(metadata, dict) else None
        return str(value).strip() if value not in (None, "") else ""

    def setComboData(self, combo, value):
        """指定dataを持つcombo項目へ切り替える。"""
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return True
        return False

    def setSpinValueFromMetadata(self, widget, metadata, key, as_int=False):
        """メタデータの数値をspin boxへ反映する。"""
        value = metadata.get(key) if isinstance(metadata, dict) else None
        numeric = _parse_float(value)
        if numeric is None:
            return False
        widget.setValue(int(round(numeric)) if as_int else float(numeric))
        return True

    def applyJobMetadata(self, metadata):
        """GPKGメタデータからパネル上の入力状態を復元する。"""
        if not metadata:
            return False

        self.setSpinValueFromMetadata(self.frame_shift, metadata, "frame_shift", as_int=True)
        self.setSpinValueFromMetadata(self.kp_tolerance, metadata, "kp_tolerance_m")
        self.setSpinValueFromMetadata(self.radar_radius, metadata, "radar_range_m")
        self.setSpinValueFromMetadata(self.radar_scale, metadata, "radar_scale")
        self.setSpinValueFromMetadata(self.radar_cal_fov, metadata, "radar_cal_fov_deg")
        self.setSpinValueFromMetadata(self.radar_cal_distance, metadata, "radar_cal_dist_m")
        self.setSpinValueFromMetadata(self.nav_step, metadata, "nav_step", as_int=True)
        self.setSpinValueFromMetadata(self.nav_fast_step, metadata, "nav_fast_step", as_int=True)

        offset = _parse_float(metadata.get("radar_offset_deg"))
        if offset is not None:
            self.setComboData(self.radar_offset, int(offset))

        if "viewer_camera_height_m" in metadata:
            self.setViewerCameraHeightValue(metadata.get("viewer_camera_height_m"))
        if "viewer_hud_height_scale" in metadata:
            self.setViewerHudHeightScaleValue(metadata.get("viewer_hud_height_scale"))

        if "follow_frame" in metadata:
            self.follow_frame_checkbox.setChecked(self.parseViewerBool(metadata.get("follow_frame")))
        return True

    def inferVideoPathFromDatabase(self, gpkg_path, target_layer=None):
        """GPKGの位置や属性から同じフォルダのMP4候補を推定する。"""
        video_name = self.firstLayerValue(target_layer, "video")
        output_dir = os.path.dirname(os.path.abspath(gpkg_path))
        parent_dir = os.path.dirname(output_dir)
        if not video_name:
            video_name = os.path.basename(output_dir) + ".mp4"
        candidate = os.path.join(parent_dir, str(video_name))
        return candidate if os.path.isfile(candidate) else ""

    def inferGpxPathFromDatabase(self, gpkg_path):
        """GPKGの位置から同名GPX候補だけを控えめに推定する。"""
        output_dir = os.path.dirname(os.path.abspath(gpkg_path))
        parent_dir = os.path.dirname(output_dir)
        candidate = os.path.join(parent_dir, os.path.basename(output_dir) + ".gpx")
        return candidate if os.path.isfile(candidate) else ""

    def rebuildFramePositionCacheFromLayer(self, layer):
        """読み込んだ撮影点レイヤからframe->緯度経度キャッシュを復元する。"""
        self.frame_position_by_frame = {}
        if layer is None:
            return
        for feature in layer.getFeatures():
            frame_value = self.targetFeatureFloat(feature, "frame")
            if frame_value is None:
                continue
            lat = self.targetFeatureFloat(feature, "aligned_latitude")
            lon = self.targetFeatureFloat(feature, "aligned_longitude")
            if lat is None or lon is None:
                lat = self.targetFeatureFloat(feature, "latitude")
                lon = self.targetFeatureFloat(feature, "longitude")
            if lat is None or lon is None:
                try:
                    point = feature.geometry().asPoint()
                    lon = float(point.x())
                    lat = float(point.y())
                except Exception:
                    continue
            self.frame_position_by_frame[int(frame_value)] = (float(lat), float(lon))

    def firstFrameInLayer(self, layer):
        """撮影点レイヤ内の最小frameを返す。"""
        frames = self.layerFrames(layer)
        return frames[0] if frames else None

    def saveAndRemoveGeneratedLayersBeforeDatabaseLoad(self):
        """DB読込前に既存の一時レイヤを退避してから取り除く。"""
        if not self.generatedLayers():
            return True
        saved_path, _saved_count, save_error = self.saveGeneratedLayers()
        if save_error:
            self.notifyWarning("save_generated_layers_failed", path=saved_path, error=save_error)
            return False
        self.removeGeneratedLayers()
        return True

    def loadSessionDatabase(self, gpkg_path):
        """GPKGの標準内部レイヤを一時レイヤへ読み替えて作業状態を復元する。"""
        gpkg_path = os.path.abspath(str(gpkg_path))
        if not os.path.isfile(gpkg_path):
            self.notifyWarning("database_load_failed", error=f"file not found: {gpkg_path}")
            return False
        if not self.saveAndRemoveGeneratedLayersBeforeDatabaseLoad():
            return False
        job_metadata = self.readJobMetadataFromGpkg(gpkg_path)

        frame_source = self.gpkgLayer(gpkg_path, GPKG_FRAME_LAYER_NAME, "Video GPX Points")
        if frame_source is None:
            self.notifyWarning("database_load_failed", error=f"layer not found: {GPKG_FRAME_LAYER_NAME}")
            return False
        target_source = self.gpkgLayer(gpkg_path, GPKG_TARGET_LAYER_NAME, "360 Click Targets")

        frame_layer = self.cloneLayerToMemory(frame_source, "Video GPX Points")
        target_layer = self.cloneLayerToMemory(target_source, "360 Click Targets") if target_source is not None else None

        project = QgsProject.instance()
        project.addMapLayer(frame_layer)
        self.created_layer_ids = [frame_layer.id()]
        self.frame_layer_id = frame_layer.id()

        if target_layer is not None:
            self.applyViewerTargetHiddenColumns(target_layer)
            project.addMapLayer(target_layer)
            self.created_layer_ids.append(target_layer.id())
            self.target_layer_id = target_layer.id()
        else:
            self.target_layer_id = None

        self.database_file = gpkg_path
        self.loaded_gpkg_path = gpkg_path
        self.output_dir = os.path.dirname(gpkg_path)
        self.output_dir_user_selected = True
        self.setPathLabel(self.database_path, gpkg_path, self.uiText("ui.path.no_database"))
        self.setPathLabel(self.output_path, self.output_dir, self.uiText("ui.path.default_output"))

        metadata_video = self.metadataText(job_metadata, "video_file")
        restored_video = metadata_video if metadata_video and os.path.isfile(metadata_video) else ""
        if not restored_video:
            restored_video = self.inferVideoPathFromDatabase(gpkg_path, target_layer)
        restored_gpx = self.metadataText(job_metadata, "gpx_file") or self.inferGpxPathFromDatabase(gpkg_path)
        restored_kp = self.metadataText(job_metadata, "kp_file")
        self.video_file = restored_video
        self.gpx_file = restored_gpx
        self.kp_file = restored_kp
        self.setPathLabel(self.video_path, restored_video, self.uiText("ui.path.no_video"))
        self.setPathLabel(self.gpx_path, restored_gpx, self.uiText("ui.path.no_gpx"))
        self.setPathLabel(self.kp_path, restored_kp, self.uiText("ui.path.no_kp"))
        self.applyJobMetadata(job_metadata)

        self.last_rows = []
        self.saved_viewer_target_keys = set()
        self.rebuildFramePositionCacheFromLayer(frame_layer)
        picked_frames = self.pickedFrames()
        first_frame = picked_frames[0] if picked_frames else self.firstFrameInLayer(frame_layer)
        self.setCurrentFrame(first_frame)
        self.setNavigationModeByData("picked" if picked_frames else "layer")
        if "viewer_camera_height_m" not in job_metadata or "viewer_hud_height_scale" not in job_metadata:
            self.loadViewerSessionCameraHeight(force=True)
        self.writeViewerRuntimeConfig(show_error=False)
        if first_frame is not None and self.video_file:
            initial_state = {
                "video": os.path.basename(self.video_file),
                "frame_index": int(first_frame),
                "yaw_to_camera_heading": 0.0,
                "pitch": 0.0,
                "zoom": 1.0,
                "viewer_camera_height_m": self.viewerCameraHeightValue(),
                "viewer_hud_height_scale": self.viewerHudHeightScaleValue(),
            }
            picked_view = self.viewerViewForPickedFrame(first_frame) if picked_frames else None
            if picked_view:
                initial_state.update(picked_view)
            self.writeViewerSessionState(initial_state)
        else:
            self.writeViewerCameraHeightSessionValue()
        self.setDatabaseRestoreMode(True)

        self.notifyInfo(
            "database_loaded",
            frame_layer=self.layerFeatureCount(frame_layer),
            target_layer=self.layerFeatureCount(target_layer),
            path=gpkg_path,
        )
        return True

    def viewerTargetLayer(self):
        """360クリック投影点を書き込む自前メモリレイヤを返す。"""
        project = QgsProject.instance()
        if self.target_layer_id:
            layer = project.mapLayer(self.target_layer_id)
            if self.isViewerTargetLayer(layer) and self.isMemoryLayer(layer):
                self.ensureViewerTargetLayerFields(layer)
                self.applyViewerTargetHiddenColumns(layer)
                return layer

        for layer_id in reversed(self.created_layer_ids):
            layer = project.mapLayer(layer_id)
            if self.isViewerTargetLayer(layer) and self.isMemoryLayer(layer):
                self.target_layer_id = layer.id()
                self.ensureViewerTargetLayerFields(layer)
                self.applyViewerTargetHiddenColumns(layer)
                return layer
        return None

    def ensureViewerTargetLayerFields(self, layer):
        """クリック点レイヤの後方互換フィールドを補う。"""
        if layer is None:
            return False
        fields = layer.fields()
        missing_fields = []
        if fields.indexFromName("quality") < 0:
            missing_fields.append(QgsField("quality", QVariant.String))
        if not missing_fields:
            self.applyViewerTargetHiddenColumns(layer)
            return False
        layer.dataProvider().addAttributes(missing_fields)
        layer.updateFields()
        self.applyViewerTargetHiddenColumns(layer)
        return True

    def ensureViewerTargetLayer(self):
        """360クリック投影点保存用のメモリレイヤを必要に応じて作成する。"""
        layer = self.viewerTargetLayer()
        if layer is not None:
            return layer

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "360 Click Targets", "memory")
        pr = layer.dataProvider()
        pr.addAttributes([
            QgsField("video", QVariant.String),
            QgsField("frame", QVariant.Int),
            QgsField("target_id", QVariant.Int),
            QgsField("target_order", QVariant.Int),
            QgsField("latitude", QVariant.Double),
            QgsField("longitude", QVariant.Double),
            QgsField("distance_m", QVariant.Double),
            QgsField("forward_m", QVariant.Double),
            QgsField("bearing_deg", QVariant.Double),
            QgsField("yaw_delta", QVariant.Double),
            QgsField("target_yaw", QVariant.Double),
            QgsField("target_pitch", QVariant.Double),
            QgsField("view_yaw", QVariant.Double),
            QgsField("view_pitch", QVariant.Double),
            QgsField("view_zoom", QVariant.Double),
            QgsField("source_lat", QVariant.Double),
            QgsField("source_lon", QVariant.Double),
            QgsField("projection", QVariant.String),
            QgsField("quality", QVariant.String),
            QgsField("created_at", QVariant.String),
        ])
        layer.updateFields()
        self.applyViewerTargetHiddenColumns(layer)
        QgsProject.instance().addMapLayer(layer)
        self.created_layer_ids.append(layer.id())
        self.target_layer_id = layer.id()
        return layer

    def targetFeatureValue(self, feature, field_name):
        """フィールドが無い/読めない場合はNoneとして扱って属性値を返す。"""
        try:
            return feature[field_name]
        except Exception:
            return None

    def targetFeatureFloat(self, feature, field_name):
        """クリックターゲット属性からfloat値を安全に取り出す。"""
        return _parse_float(self.targetFeatureValue(feature, field_name))

    def normalizedPath(self, path):
        """レイヤsource比較用にパス表記を正規化する。"""
        if not path:
            return ""
        try:
            return os.path.normcase(os.path.abspath(str(path)))
        except (TypeError, ValueError):
            return ""

    def layerSourcePath(self, layer):
        """QGISレイヤsourceからGeoPackageファイル部分だけを取り出す。"""
        try:
            source = layer.source()
        except Exception:
            return ""
        return str(source).split("|", 1)[0]

    def isCurrentGpkgTargetLayer(self, layer):
        """現在ジョブのtmp.gpkg内click_targets_360レイヤかを判定する。"""
        if not self.isViewerTargetLayer(layer):
            return False
        source = ""
        try:
            source = str(layer.source())
        except Exception:
            source = ""
        if GPKG_TARGET_LAYER_NAME not in source and GPKG_TARGET_LAYER_NAME not in str(layer.name()):
            return False
        return self.normalizedPath(self.layerSourcePath(layer)) == self.normalizedPath(self.generatedLayerBackupPath())

    def isNamedViewerTargetLayer(self, layer):
        """表示名/source上もclick_targets_360相当と判断できるか確認する。"""
        if not self.isViewerTargetLayer(layer):
            return False
        try:
            name = str(layer.name())
        except Exception:
            name = ""
        try:
            source = str(layer.source())
        except Exception:
            source = ""
        text = f"{name}\n{source}".lower()
        return "360 click targets" in text or GPKG_TARGET_LAYER_NAME.lower() in text

    def layerHasVideoFrameTarget(self, layer, video_name, frame_num=None):
        """指定動画/任意フレームのクリック点を持つレイヤか確認する。"""
        if not self.isViewerTargetLayer(layer):
            return False
        if not video_name:
            return True

        for feature in layer.getFeatures():
            feature_video = self.targetFeatureValue(feature, "video")
            if str(feature_video) != str(video_name):
                continue
            if frame_num is None:
                return True
            frame_value = self.targetFeatureFloat(feature, "frame")
            if frame_value is not None and int(frame_value) == int(frame_num):
                return True
        return False

    def viewerTargetReadLayers(self, frame_num=None):
        """復元参照に使うクリック点レイヤを現在ジョブに絞って返す。"""
        project = QgsProject.instance()
        current_video = os.path.basename(self.video_file or "")
        if not current_video:
            return []
        layers = []
        seen = set()

        def add_layer(layer):
            """重複とスキーマ不一致を避けて候補へ追加する。"""
            if not self.isViewerTargetLayer(layer):
                return
            layer_id = layer.id()
            if layer_id in seen:
                return
            layers.append(layer)
            seen.add(layer_id)

        write_layer = self.viewerTargetLayer()
        if write_layer is not None and self.layerHasVideoFrameTarget(write_layer, current_video, frame_num):
            add_layer(write_layer)

        for layer in reversed(list(project.mapLayers().values())):
            if self.isCurrentGpkgTargetLayer(layer):
                add_layer(layer)

        for layer in reversed(list(project.mapLayers().values())):
            if not self.isNamedViewerTargetLayer(layer):
                continue
            if not self.layerHasVideoFrameTarget(layer, current_video, frame_num):
                continue
            add_layer(layer)

        return layers

    def restoredViewerTargetPayload(self, feature, fallback_order):
        """保存済みクリック点レコードをviewer_session.jsonのtarget形式へ戻す。"""
        target_yaw = self.targetFeatureFloat(feature, "target_yaw")
        target_pitch = self.targetFeatureFloat(feature, "target_pitch")
        if target_yaw is None or target_pitch is None:
            return None

        view_yaw = self.targetFeatureFloat(feature, "view_yaw")
        if view_yaw is None:
            view_yaw = target_yaw
        view_pitch = self.targetFeatureFloat(feature, "view_pitch")
        if view_pitch is None:
            view_pitch = target_pitch
        view_zoom = self.targetFeatureFloat(feature, "view_zoom")
        if view_zoom is None:
            view_zoom = 1.0

        yaw_delta = self.targetFeatureFloat(feature, "yaw_delta")
        if yaw_delta is None:
            yaw_delta = self.signedAngleDelta(view_yaw, target_yaw)

        target_id = self.targetFeatureFloat(feature, "target_id")
        target_order = self.targetFeatureFloat(feature, "target_order")
        target_id = int(target_id) if target_id is not None else int(fallback_order)
        target_order = int(target_order) if target_order is not None else target_id
        projection = self.targetFeatureValue(feature, "projection") or "ground_plane"
        distance_m = self.targetFeatureFloat(feature, "distance_m")
        quality = self.targetFeatureValue(feature, "quality")

        target = {
            "id": target_id,
            "order": target_order,
            "x_ratio": 0.5,
            "y_ratio": 0.5,
            "yaw_delta_deg": self.signedAngleDelta(0.0, yaw_delta),
            "pitch_delta_deg": max(-90.0, min(90.0, float(target_pitch) - float(view_pitch))),
            "target_yaw_to_camera_heading": float(target_yaw) % 360.0,
            "target_pitch_deg": max(-90.0, min(90.0, float(target_pitch))),
            "view_yaw_to_camera_heading": float(view_yaw) % 360.0,
            "view_pitch": max(-90.0, min(90.0, float(view_pitch))),
            "view_zoom": max(0.01, float(view_zoom)),
            "projection": str(projection),
        }
        if str(projection) == "ground_plane" and distance_m is not None and distance_m > 0:
            target["ground_distance_m"] = float(distance_m)
        if quality:
            target["quality"] = str(quality)
        return target

    def viewerTargetsForFrame(self, frame_num):
        """指定フレームに保存済みのクリック点をビューア復元用payloadとして返す。"""
        target_frame = int(frame_num)
        layers = self.viewerTargetReadLayers(target_frame)
        if not layers:
            return []

        current_video = os.path.basename(self.video_file or "")
        targets = []
        seen_ids = set()

        for layer in layers:
            for feature in layer.getFeatures():
                frame_value = self.targetFeatureFloat(feature, "frame")
                if frame_value is None or int(frame_value) != target_frame:
                    continue

                feature_video = self.targetFeatureValue(feature, "video")
                if current_video and feature_video and str(feature_video) != current_video:
                    continue

                target = self.restoredViewerTargetPayload(feature, len(targets) + 1)
                if not target:
                    continue
                target_id = int(target.get("id") or target.get("order") or 0)
                if target_id in seen_ids:
                    continue
                seen_ids.add(target_id)
                targets.append(target)

        targets.sort(key=lambda item: (int(item.get("order") or 0), int(item.get("id") or 0)))
        return targets

    def viewerViewForPickedFrame(self, frame_num):
        """Picked point移動時に、保存済みクリック時視点をビューア中心へ戻す。"""
        targets = self.viewerTargetsForFrame(frame_num)
        if not targets:
            return None
        target = targets[-1]
        view_yaw = _parse_float(target.get("view_yaw_to_camera_heading"))
        view_pitch = _parse_float(target.get("view_pitch"))
        view_zoom = _parse_float(target.get("view_zoom"))
        if view_yaw is None or view_pitch is None or view_zoom is None:
            return None
        return {
            "yaw_to_camera_heading": float(view_yaw) % 360.0,
            "pitch": max(-90.0, min(90.0, float(view_pitch))),
            "zoom": max(0.01, float(view_zoom)),
        }

    def restoreViewerTargetsForState(self, state):
        """現在sessionに点が無ければ、保存済みクリック点を補完して返す。"""
        if not isinstance(state, dict):
            return state
        current_video = os.path.basename(self.video_file or "")
        if not current_video or state.get("video") != current_video:
            return state
        if isinstance(state.get("targets"), list) and state.get("targets"):
            return state
        if isinstance(state.get("target"), dict):
            return state

        frame_index = self.sessionFrameIndex(state)
        if frame_index is None:
            return state
        targets = self.viewerTargetsForFrame(frame_index)
        if not targets:
            return state

        restored_state = dict(state)
        restored_state["targets"] = targets
        restored_state["target"] = targets[-1]
        written_state = self.writeViewerSessionState(restored_state)
        return written_state if isinstance(written_state, dict) else restored_state

    def viewerTargetKey(self, video_name, frame_index, projection):
        """同一クリック点の重複登録を避けるためのキーを返す。"""
        target_id = projection.get("id")
        if target_id is None:
            target_id = projection.get("order")
        if target_id is not None:
            try:
                return (str(video_name), int(frame_index), int(target_id))
            except (TypeError, ValueError):
                pass

        point = projection.get("point")
        lon = round(float(point.x()), 8) if point is not None else 0.0
        lat = round(float(point.y()), 8) if point is not None else 0.0
        yaw = round(float(projection.get("target_yaw_to_camera_heading") or 0.0), 3)
        return (str(video_name), int(frame_index), yaw, lon, lat)

    def registeredViewerTargetKeys(self, layer):
        """既存レイヤ内容から登録済みキー集合を復元する。"""
        keys = set(getattr(self, "saved_viewer_target_keys", set()))
        if keys:
            return keys

        frame_idx = layer.fields().indexFromName("frame")
        video_idx = layer.fields().indexFromName("video")
        target_idx = layer.fields().indexFromName("target_id")
        if frame_idx < 0 or video_idx < 0 or target_idx < 0:
            return keys

        for feature in layer.getFeatures():
            try:
                keys.add((
                    str(feature.attribute(video_idx)),
                    int(feature.attribute(frame_idx)),
                    int(feature.attribute(target_idx)),
                ))
            except Exception:
                continue
        self.saved_viewer_target_keys = keys
        return keys

    def storeViewerTargetProjections(self, state, source_lat, source_lon, target_projections):
        """360クリック投影点を緯度経度geometryと属性として自前レイヤへ保存する。"""
        storable_projections = [
            projection for projection in target_projections
            if projection.get("id") is not None or projection.get("order") is not None
        ]
        if not storable_projections:
            return

        frame_index = self.sessionFrameIndex(state)
        if frame_index is None:
            return
        video_name = state.get("video") or os.path.basename(self.video_file or "")

        layer = self.ensureViewerTargetLayer()
        existing_keys = self.registeredViewerTargetKeys(layer)
        features = []
        now_text = datetime.now().astimezone().isoformat(timespec="seconds")

        for projection in storable_projections:
            point = projection.get("point")
            if point is None:
                continue
            key = self.viewerTargetKey(video_name, frame_index, projection)
            if key in existing_keys:
                continue
            target_id = projection.get("id")
            target_order = projection.get("order", target_id)
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point.x(), point.y())))
            values = {
                "video": str(video_name),
                "frame": int(frame_index),
                "target_id": int(target_id) if target_id is not None else None,
                "target_order": int(target_order) if target_order is not None else None,
                "latitude": float(point.y()),
                "longitude": float(point.x()),
                "distance_m": float(projection.get("distance_m")) if projection.get("distance_m") is not None else None,
                "forward_m": float(projection.get("forward_distance_m")) if projection.get("forward_distance_m") is not None else None,
                "bearing_deg": float(projection.get("bearing")) if projection.get("bearing") is not None else None,
                "yaw_delta": float(projection.get("yaw_delta_deg")) if projection.get("yaw_delta_deg") is not None else None,
                "target_yaw": float(projection.get("target_yaw_to_camera_heading")) if projection.get("target_yaw_to_camera_heading") is not None else None,
                "target_pitch": float(projection.get("target_pitch_deg")) if projection.get("target_pitch_deg") is not None else None,
                "view_yaw": float(projection.get("view_yaw_to_camera_heading")) if projection.get("view_yaw_to_camera_heading") is not None else None,
                "view_pitch": float(projection.get("view_pitch")) if projection.get("view_pitch") is not None else None,
                "view_zoom": float(projection.get("view_zoom")) if projection.get("view_zoom") is not None else None,
                "source_lat": float(source_lat),
                "source_lon": float(source_lon),
                "projection": str(projection.get("projection") or "ground_plane"),
                "quality": str(projection.get("quality") or ""),
                "created_at": now_text,
            }
            feat.setAttributes([values.get(field.name()) for field in layer.fields()])
            features.append(feat)
            existing_keys.add(key)

        if not features:
            return
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()
        self.saved_viewer_target_keys = existing_keys

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

    def pickedFrames(self):
        """360クリック点が存在するframe一覧を返す。"""
        frames = []
        for layer in self.viewerTargetReadLayers():
            for feature in layer.getFeatures():
                frame_value = self.targetFeatureFloat(feature, "frame")
                if frame_value is None:
                    continue
                video_name = os.path.basename(self.video_file or "")
                feature_video = self.targetFeatureValue(feature, "video")
                if video_name and feature_video and str(feature_video) != video_name:
                    continue
                frames.append(int(frame_value))
        return sorted(set(frames))

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

    def setNavigationModeByData(self, mode):
        """指定dataを持つナビゲーションモードへUI選択を切り替える。"""
        for index in range(self.nav_mode.count()):
            if self.nav_mode.itemData(index) == mode:
                self.nav_mode.setCurrentIndex(index)
                return True
        return False

    def frameStepNavigationTarget(self, current_frame, direction, step_count):
        """Frame stepモードとして次フレームを決める。"""
        target = max(0, int(current_frame) + int(direction) * int(step_count))
        return target, self.findFeatureByFrame(target)

    def navigationTargetFrame(self, direction, fast=False):
        """UIのナビモードに応じて、次に表示すべきフレームと地物を決める。"""
        config = self.collectNavigationConfig()
        if config is None:
            return None, None

        current_frame = self.currentFrameValue()
        step_count = config.fast_step if fast else config.step
        mode = config.mode

        if mode == "frame":
            return self.frameStepNavigationTarget(current_frame, direction, step_count)

        if mode == "kp":
            frames, path = self.matchedFrames()
            if not frames:
                self.setNavigationModeByData("frame")
                self.notifyWarning("kp_navigation_fallback_frame")
                return self.frameStepNavigationTarget(current_frame, direction, step_count)
            target = self.steppedFrame(frames, current_frame, direction, step_count)
            if target is None:
                self.notifyWarning("no_kp_frame", direction="next" if direction > 0 else "previous")
                return None, None
            return target, self.findFeatureByFrame(target)

        if mode == "picked":
            frames = self.pickedFrames()
            if not frames:
                self.notifyWarning("no_picked_frame", direction="next" if direction > 0 else "previous")
                return None, None
            target = self.steppedFrame(frames, current_frame, direction, step_count)
            if target is None:
                self.notifyWarning("no_picked_frame", direction="next" if direction > 0 else "previous")
                return None, None
            return target, self.findFeatureByFrame(target)

        layer = self.activeFrameLayer()
        if layer is None:
            self.notifyWarning("video_gpx_layer_missing")
            return None, None

        frames = self.layerFrames(layer)
        target = self.steppedFrame(frames, current_frame, direction, step_count)
        if target is None:
            self.notifyWarning("no_layer_frame", direction="next" if direction > 0 else "previous")
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
            self.notifyWarning("processing_still_running")
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
            if layer_id == self.target_layer_id:
                self.target_layer_id = None

        self.created_layer_ids = remaining_layer_ids
        self.saved_viewer_target_keys = set()
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

    def generatedLayerBackupName(self, layer, base_layer_name, index):
        """tmp.gpkg内の保存レイヤ名を役割に応じて決める。"""
        fields = self.layerFields(layer)
        if fields is None:
            return _safe_gpkg_layer_name(f"{base_layer_name}_{index:02d}")
        if fields.indexFromName("target_id") >= 0:
            return GPKG_TARGET_LAYER_NAME
        if fields.indexFromName("frame") >= 0:
            return GPKG_FRAME_LAYER_NAME
        return _safe_gpkg_layer_name(f"{base_layer_name}_{index:02d}")

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
                layer_name = self.generatedLayerBackupName(layer, base_layer_name, index)
                self.writeLayerToGpkg(
                    layer,
                    gpkg_path,
                    layer_name,
                    overwrite_file=(index == 1 and not os.path.isfile(gpkg_path))
                )
            self.writeJobMetadataToGpkg(gpkg_path)
        except Exception as e:
            return gpkg_path, 0, str(e)

        return gpkg_path, len(layers), None

    def resetPanelState(self):
        """セッション終了後にパネル上の一時状態を初期化する。"""
        self.last_rows = []
        self.frame_position_by_frame = {}
        self.frame_layer_id = None
        self.target_layer_id = None
        self.database_file = ""
        self.loaded_gpkg_path = ""
        self.setDatabaseRestoreMode(False)
        self.saved_viewer_target_keys = set()
        self.setCurrentFrame(None)
        self.progress_bar.setValue(0)
        self.process_button.setEnabled(True)
        self.preview_info.setText(self.uiText("ui.preview.empty"))
        self.preview_info.setToolTip("")
        self.preview_label.clear()
        self.preview_label.setText(self.uiText("ui.preview.title"))
        self.preview_label.setToolTip("")

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
                self.notifyWarning("save_generated_layers_failed", path=saved_path, error=save_error)
        else:
            removed_count = self.removeGeneratedLayers() if remove_layers else 0

        self.resetPanelState()

        if close_panel:
            self.close()

        if show_message and not save_error:
            if worker_stopped:
                self.notifyInfo("session_closed", saved_count=saved_count, removed_count=removed_count)
            else:
                self.notifyWarning("session_close_requested")

    def exitSession(self):
        """Exitメニューから現在セッションを終了する。"""
        self.cleanupSession(close_panel=True, remove_layers=True, show_message=True)

    def activateClickMode(self):
        """参照用Video GPX Pointsレイヤをクリック待ち受け状態にする。"""
        layer = self.activeFrameLayer()
        if layer is None:
            self.notifyWarning("video_gpx_layer_missing")
            return
        if layer.fields().indexFromName("frame") < 0:
            self.notifyWarning("selected_layer_no_frame")
            return

        self.deactivateClickMode(show_message=False)
        canvas = self.iface.mapCanvas()
        self.frame_click_tool = FrameIdentifyTool(canvas, layer, self)
        canvas.setMapTool(self.frame_click_tool)
        self.notifyInfo("click_mode_active", layer=layer.name())

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
            self.notifyInfo("click_mode_stopped")


    def processData(self):
        """GPX/動画同期workerを開始する。結果はaddLayerで受け取る。"""
        if self.database_restore_mode:
            return
        config = self.collectProcessConfig()
        if config is None:
            print("Error: Process input validation failed.")
            return

        self.session_closing = False
        self.last_process_config = config
        print(f"Processing GPX: {config.gpx_file}")
        print(f"Processing Video: {config.video_file}")

        self.progress_bar.setValue(0)
        self.process_button.setEnabled(False)

        self.worker = GPXVideoProcessor(
            config.gpx_file,
            config.video_file,
            frame_shift=config.frame_shift
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
                self.notifyWarning("kp_match_failed", error=match_error)

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
                    self.processFrameShiftValue(),
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
            self.notifyInfo("layer_added", count=len(features))
            self.exportFrameData(rows, matches=matches, match_count=match_count)
        else:
            print("No rows. Could not add layer.")
            self.notifyWarning("no_rows_layer")

    def buildKpMatches(self, rows):
        """現在UIのKPファイル/許容距離を使ってKPマッチングを実行する。"""
        return build_kp_matches(rows, self.processKpFileValue(), self.processKpToleranceValue())

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
            self.notifyWarning("output_dir_failed", error=e)
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
                self.notifyWarning("kp_match_failed", error=match_error)

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

                frame_shift = self.processFrameShiftValue()
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

            if self.processKpFileValue():
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
                    "kp_csv": self.processKpFileValue(),
                    "kp_tolerance_m": self.processKpToleranceValue(),
                    "frame_shift": self.processFrameShiftValue(),
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
            self.notifyWarning("output_files_failed", error=e)
            return

        self.notifyInfo("saved_frame_csv", path=csv_path)
        if self.processKpFileValue():
            if match_count == 0:
                self.notifyWarning("no_kp_matches", distance=self.processKpToleranceValue())
            self.notifyInfo("saved_navigation_json", path=json_path)
            self.notifyInfo("saved_viewer_matched_csv", path=matched_csv_paths[-1])

    def showError(self, error):
        """workerからのエラーをUIへ反映し、必要に応じてmessageBarへ表示する。"""
        self.process_button.setEnabled(True)
        self.progress_bar.setValue(0)
        if self.session_closing and error == "Processing cancelled.":
            print(f"Error: {error}")
            return

        print(f"Error: {error}")
        self.notifyWarning("worker_error", error=error)

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
