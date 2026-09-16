"""Geo360View QGISプラグインのUIと全体制御。"""

import csv
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
import time
import uuid

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
    QgsProject, QgsField, QgsVectorFileWriter, QgsCoordinateTransform,
    QgsFeatureRequest, QgsExpression, QgsCategorizedSymbolRenderer,
    QgsRendererCategory, QgsSingleSymbolRenderer, QgsSymbol,
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
from .processor import Geo360View
from .qt_compat import (
    QT_ACTIVE_WINDOW_FOCUS_REASON,
    QT_ALIGN_CENTER,
    QT_DISPLAY_ROLE,
    QT_EDIT_ROLE,
    QT_KEY_ESCAPE,
    QT_KEY_LEFT,
    QT_KEY_RIGHT,
    QT_KEY_SPACE,
    QT_MESSAGE_BOX_NO,
    QT_MESSAGE_BOX_YES,
    QT_SHIFT_MODIFIER,
    QT_SIZE_POLICY_IGNORED,
    QT_SIZE_POLICY_PREFERRED,
    QT_TEXT_SELECTABLE_BY_MOUSE,
    QT_USER_ROLE,
    QT_WINDOW_STAYS_ON_TOP_HINT,
)
from .radar import RadarMixin
from .viewer_controller import ViewerControllerMixin

QAction = getattr(QtWidgets, "QAction", None) or QtGui.QAction

GPKG_FRAME_LAYER_NAME = "video_gpx_points"
GPKG_TARGET_LAYER_NAME = "click_targets_360"
GPKG_CANDIDATE_LAYER_NAME = "poi_candidates_360"
GPKG_JOB_METADATA_TABLE = "gpx_video_processor_job_metadata"
VIEWER_PROJECTION_SPHERE = "sphere"
VIEWER_PROJECTION_FLAT = "flat"
VIEWER_PROJECTION_VALUES = (VIEWER_PROJECTION_SPHERE, VIEWER_PROJECTION_FLAT)
DEFAULT_VIEWER_FLAT_HFOV_DEG = 70.0
DEFAULT_VIEWER_FLAT_VFOV_DEG = 43.0

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

VIEWER_TARGET_FIELD_DEFS = (
    ("video", QVariant.String),
    ("frame", QVariant.Int),
    ("target_id", QVariant.Int),
    ("target_order", QVariant.Int),
    ("x_ratio", QVariant.Double),
    ("y_ratio", QVariant.Double),
    ("latitude", QVariant.Double),
    ("longitude", QVariant.Double),
    ("distance_m", QVariant.Double),
    ("forward_m", QVariant.Double),
    ("bearing_deg", QVariant.Double),
    ("yaw_delta", QVariant.Double),
    ("target_yaw", QVariant.Double),
    ("target_pitch", QVariant.Double),
    ("view_yaw", QVariant.Double),
    ("view_pitch", QVariant.Double),
    ("view_zoom", QVariant.Double),
    ("source_lat", QVariant.Double),
    ("source_lon", QVariant.Double),
    ("projection", QVariant.String),
    ("quality", QVariant.String),
    ("created_at", QVariant.String),
)

VIEWER_CANDIDATE_HIDDEN_COLUMNS = (
    "candidate_id",
    "record_type",
    "target_id",
    "target_source",
    "run_id",
    "frame_id",
    "source_frame",
    "source_lat",
    "source_lon",
    "source_heading",
    "offset_m",
    "bearing_deg",
    "target_pitch",
    "trajectory_window",
    "fallback_reason",
    "evidence_plane_id",
    "evidence_image_path",
    "evidence_bbox_json",
    "bbox_anchor",
    "anchor_x_px",
    "anchor_y_px",
    "cubemap_u",
    "cubemap_v",
    "viewer_marker",
    "created_at",
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
        self.new_job_action = None
        self.exit_action = None
        self.viewer_process = None
        self.viewer_browser_opened = False
        self.viewer_host = "127.0.0.1"
        self.viewer_port = 8181
        self.viewer_jpeg_quality = 90
        self.viewer_progressive_jpeg = True
        self.viewer_max_width = 3072
        self.viewer_snapshot_jpeg_quality = 96
        self.viewer_snapshot_max_width = 0
        self.viewer_snapshot_output_scale = 2.0
        self.viewer_camera_height_m = 1.5
        self.viewer_camera_height_dirty = False
        self.viewer_hud_height_scale_value = 1.0
        self.viewer_hud_height_scale_dirty = False
        self.video_front_offset_deg = 0.0
        self.viewer_projection = VIEWER_PROJECTION_SPHERE
        self.viewer_projection_dirty = False
        self.viewer_projection_reason = ""
        self.viewer_flat_hfov_deg = DEFAULT_VIEWER_FLAT_HFOV_DEG
        self.viewer_flat_vfov_deg = DEFAULT_VIEWER_FLAT_VFOV_DEG
        self.created_layer_ids = []
        self.save_on_exit_layer_ids = set()
        self.loaded_layer_feature_counts = {}
        self.frame_layer_id = None
        self.target_layer_id = None
        self.candidate_layer_id = None
        self.loaded_gpkg_path = ""
        self.saved_viewer_target_keys = set()
        self.session_closing = False
        self.current_frame = None
        self.viewer_session_timer = None
        self.last_viewer_session_signature = None
        self.verbose_log_enabled = False
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

    def debugLogEnabled(self):
        """高頻度な調査用ログをQGISへ流してよいかを返す。"""
        checkbox = getattr(self, "verbose_log_checkbox", None)
        if checkbox is not None:
            return bool(checkbox.isChecked())
        return bool(getattr(self, "verbose_log_enabled", False))

    def notifyDebug(self, key, **params):
        """詳細ログON時だけQGIS messageBarへ流す。"""
        if self.debugLogEnabled():
            self.notifyInfo(key, **params)

    def notifyDebugText(self, text):
        """詳細ログON時だけ、既存の詳細文字列をQGIS messageBarへ流す。"""
        if self.debugLogEnabled():
            self.notifyInfoText(text)

    def notifyWarningText(self, text):
        """既存の詳細文字列をそのまま警告メッセージとして表示する移行用入口。"""
        self.iface.messageBar().pushWarning(PLUGIN_TITLE, text)

    def onVerboseLogToggled(self, checked):
        """詳細ログON/OFFをセッションをまたいで保持する。"""
        self.verbose_log_enabled = bool(checked)
        QSettings().setValue(f"{PLUGIN_TITLE}/verbose_log", bool(checked))

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
        """実行中Processの参照点CSVパスを返す。未指定なら空文字を返す。"""
        config = getattr(self, "last_process_config", None)
        if config is not None:
            return config.kp_file or ""
        return self.kp_file

    def processKpToleranceValue(self):
        """実行中Processの参照点マッチング許容距離を返す。"""
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
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

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

        self.new_job_button = QPushButton("New Job")
        self.new_job_button.clicked.connect(self.newJobSession)
        self.new_job_button.setToolTip("Clear current GPX/MP4/Reference/Output selections and start a fresh job.")
        set_fixed_width(self.new_job_button, 82)

        self.video_label = QLabel("Video:")
        self.video_path = self.makePathLabel(self.uiText("ui.path.no_video"))
        self.video_button = QPushButton(self.uiText("ui.button.browse"))
        self.video_button.clicked.connect(self.selectVideo)
        self.applyHelp("ui.help.video", self.video_label, self.video_button)
        set_fixed_width(self.video_button, 72)

        self.viewer_projection_label = QLabel("Projection:")
        self.viewer_projection_combo = QComboBox()
        self.viewer_projection_combo.addItem("360 / Equirectangular", VIEWER_PROJECTION_SPHERE)
        self.viewer_projection_combo.addItem("Flat / Normal FOV", VIEWER_PROJECTION_FLAT)
        self.viewer_projection_combo.currentIndexChanged.connect(self.onViewerProjectionChanged)
        set_fixed_width(self.viewer_projection_combo, 168)
        self.viewer_projection_reason_label = QLabel("")
        self.viewer_projection_reason_label.setTextInteractionFlags(QT_TEXT_SELECTABLE_BY_MOUSE)

        self.database_label = QLabel("GPKG:")
        self.database_path = self.makePathLabel(self.uiText("ui.path.no_database"))
        self.database_button = QPushButton(self.uiText("ui.button.load_database"))
        self.database_button.clicked.connect(self.selectDatabase)
        self.applyHelp("ui.help.database", self.database_label, self.database_button)
        set_fixed_width(self.database_button, 72)

        self.kp_label = QLabel("Ref CSV:")
        self.kp_path = self.makePathLabel(self.uiText("ui.path.no_kp"))
        self.kp_button = QPushButton(self.uiText("ui.button.browse"))
        self.kp_button.clicked.connect(self.selectKP)
        self.applyHelp("ui.help.kp", self.kp_label, self.kp_button)
        set_fixed_width(self.kp_button, 72)

        for label in (self.gpx_label, self.video_label, self.viewer_projection_label, self.database_label, self.kp_label):
            label.setMinimumWidth(52)

        self.kp_tolerance_label = QLabel("Ref tol:")
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
        self.verbose_log_checkbox = QCheckBox(self.uiText("ui.checkbox.log"))
        self.verbose_log_enabled = self.parseViewerBool(
            QSettings().value(f"{PLUGIN_TITLE}/verbose_log", False)
        )
        self.verbose_log_checkbox.setChecked(self.verbose_log_enabled)
        self.verbose_log_checkbox.toggled.connect(self.onVerboseLogToggled)
        self.applyHelp("ui.help.log", self.verbose_log_checkbox)

        self.nav_label = QLabel("Nav:")
        self.current_frame_label = QLabel(self.uiText("ui.status.current_empty"))
        self.nav_mode = QComboBox()
        self.nav_mode.addItem("Frame step", "frame")
        self.nav_mode.addItem("Layer point", "layer")
        self.nav_mode.addItem("Reference matched", "kp")
        self.nav_mode.currentIndexChanged.connect(self.onNavigationModeChanged)
        self.applyHelp("ui.help.nav_mode", self.nav_label, self.nav_mode)
        set_fixed_width(self.nav_mode, 146)
        self.nav_scope_label = QLabel("Scope:")
        self.nav_scope = QComboBox()
        self.nav_scope.addItem("Active layer", "active")
        self.nav_scope.addItem("Visible layers", "visible")
        self.nav_scope.addItem("All candidates", "all")
        self.nav_scope.addItem("Selected features", "selected")
        self.nav_scope.setCurrentIndex(1)
        self.nav_scope.setToolTip(
            "Detection check target scope. QGIS visibility, selection, and subset filters can limit Nav targets."
        )
        self.nav_scope_label.setToolTip(self.nav_scope.toolTip())
        self.nav_scope_label.hide()
        self.nav_scope.hide()
        set_fixed_width(self.nav_scope, 132)
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

        self.nav_first_button = QPushButton("|<<")
        self.nav_back_fast_button = QPushButton("<<")
        self.nav_back_button = QPushButton("<")
        self.nav_forward_button = QPushButton(">")
        self.nav_forward_fast_button = QPushButton(">>")
        self.nav_last_button = QPushButton(">>|")
        self.nav_first_button.clicked.connect(lambda _checked=False: self.navigateEdge(-1))
        self.nav_back_fast_button.clicked.connect(lambda _checked=False: self.navigateRelative(-1, fast=True))
        self.nav_back_button.clicked.connect(lambda _checked=False: self.navigateRelative(-1, fast=False))
        self.nav_forward_button.clicked.connect(lambda _checked=False: self.navigateRelative(1, fast=False))
        self.nav_forward_fast_button.clicked.connect(lambda _checked=False: self.navigateRelative(1, fast=True))
        self.nav_last_button.clicked.connect(lambda _checked=False: self.navigateEdge(1))
        for button in (self.nav_first_button, self.nav_last_button):
            set_fixed_width(button, 42)
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
        self.nav_button_layout.addWidget(self.nav_first_button)
        self.nav_button_layout.addWidget(self.nav_back_fast_button)
        self.nav_button_layout.addWidget(self.nav_back_button)
        self.nav_button_layout.addWidget(self.nav_forward_button)
        self.nav_button_layout.addWidget(self.nav_forward_fast_button)
        self.nav_button_layout.addWidget(self.nav_last_button)

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
        self.video_front_offset_label = QLabel("Front:")
        self.video_front_offset = QDoubleSpinBox()
        self.video_front_offset.setRange(-180.0, 180.0)
        self.video_front_offset.setDecimals(1)
        self.video_front_offset.setSingleStep(1.0)
        self.video_front_offset.setValue(self.video_front_offset_deg)
        self.video_front_offset.setSuffix(" deg")
        self.video_front_offset.valueChanged.connect(self.onVideoFrontOffsetChanged)
        set_fixed_width(self.video_front_offset, 92)

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
        self.preview_info.setSizePolicy(QT_SIZE_POLICY_IGNORED, QT_SIZE_POLICY_PREFERRED)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(QT_ALIGN_CENTER)
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
        compact_row(
            load_layout,
            self.viewer_projection_label,
            self.viewer_projection_combo,
            self.viewer_projection_reason_label,
            "stretch",
        )
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
            self.verbose_log_checkbox,
            "stretch",
        )
        compact_row(
            control_layout,
            self.nav_label,
            self.current_frame_label,
            self.nav_mode,
            self.nav_scope_label,
            self.nav_scope,
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
            self.video_front_offset_label,
            self.video_front_offset,
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
        header_layout.addStretch(1)
        header_layout.addWidget(self.new_job_button)
        layout.addLayout(header_layout)
        layout.addWidget(tabs)

        self.setLayout(layout)

        # アクションを定義
        self.action = QAction(self.uiText("ui.action.start"), self)
        self.action.setStatusTip(self.uiText("ui.help.process"))
        self.action.triggered.connect(self.run)
        self.viewer_action = QAction(self.uiText("ui.action.open_viewer"), self)
        self.viewer_action.setStatusTip(self.uiText("ui.help.video"))
        self.viewer_action.triggered.connect(self.openViewer)
        self.new_job_action = QAction("New Job", self)
        self.new_job_action.setStatusTip("Clear current selections and start a fresh job.")
        self.new_job_action.triggered.connect(self.newJobSession)
        self.exit_action = QAction(self.uiText("ui.action.exit"), self)
        self.exit_action.triggered.connect(self.exitSession)

        # メニューにアクションを追加
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.viewer_action)
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.action)
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.new_job_action)
        self.iface.addPluginToMenu(PLUGIN_TITLE, self.exit_action)

        # ツールバーにアクションを追加
        self.toolbar = self.iface.addToolBar(PLUGIN_TITLE)
        self.toolbar.addAction(self.viewer_action)
        self.toolbar.addAction(self.action)
        self.toolbar.addAction(self.new_job_action)
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
            fast = bool(event.modifiers() & QT_SHIFT_MODIFIER)
            if key == QT_KEY_LEFT:
                self.navigateRelative(-1, fast=fast)
                return True
            if key == QT_KEY_RIGHT:
                self.navigateRelative(1, fast=fast)
                return True
            if key == QT_KEY_SPACE:
                self.displayCurrentFrame()
                return True
            if key == QT_KEY_ESCAPE:
                self.deactivateClickMode()
                return True

        return super().eventFilter(watched, event)

    def applyPanelWindowFlags(self):
        """操作パネルをQGIS操作中も前面へ出しやすいウィンドウにする。"""
        flags = self.windowFlags()
        if not (flags & QT_WINDOW_STAYS_ON_TOP_HINT):
            self.setWindowFlags(flags | QT_WINDOW_STAYS_ON_TOP_HINT)

    def showWindow(self):
        """プラグインパネルを前面に表示する。"""
        self.applyPanelWindowFlags()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(QT_ACTIVE_WINDOW_FOCUS_REASON)

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
        label.setSizePolicy(QT_SIZE_POLICY_IGNORED, QT_SIZE_POLICY_PREFERRED)
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
        if getattr(self, "new_job_button", None) is not None:
            self.new_job_button.setEnabled(True)

    def setDatabaseRestoreMode(self, enabled):
        """GPKG復元後は段取り替え系操作を禁止する。"""
        self.database_restore_mode = bool(enabled)
        if getattr(self, "_gui_initialized", False):
            self.setInputWidgetsEnabled(not self.database_restore_mode)
            if self.database_restore_mode:
                # MP4は実行時参照で、GPKGを開くマシンごとに異なる。
                self.video_button.setEnabled(True)
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

    def clearJobInputs(self):
        """次ジョブへ前回入力を持ち越さないよう、選択済みパスとジョブ条件を初期化する。"""
        self.gpx_file = ""
        self.video_file = ""
        self.kp_file = ""
        self.database_file = ""
        self.loaded_gpkg_path = ""
        self.output_dir = ""
        self.output_dir_user_selected = False
        self.last_process_config = None
        self.viewer_browser_opened = False
        self.viewer_projection_dirty = False
        self.setViewerProjectionValue(VIEWER_PROJECTION_SPHERE, reason="", dirty=False)
        self.setVideoFrontOffsetValue(0.0)
        if getattr(self, "_gui_initialized", False):
            self.setPathLabel(self.gpx_path, "", self.uiText("ui.path.no_gpx"))
            self.setPathLabel(self.video_path, "", self.uiText("ui.path.no_video"))
            self.setPathLabel(self.kp_path, "", self.uiText("ui.path.no_kp"))
            self.setPathLabel(self.database_path, "", self.uiText("ui.path.no_database"))
            self.setPathLabel(self.output_path, "", self.uiText("ui.path.default_output"))

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
        restore_mode = self.database_restore_mode
        start_dir = self.dialogStartDir("video", self.video_file, self.gpx_file, self.output_dir)
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", start_dir, "MP4 Files (*.mp4)")
        if file_path:
            self.rememberDialogPath("video", file_path)
            self.video_file = file_path
            self.setPathLabel(self.video_path, file_path, self.uiText("ui.path.no_video"))
            self.applyViewerProjectionAutoSuggestion(file_path, force=not restore_mode)
            self.viewer_browser_opened = False
            if not restore_mode:
                self.setCurrentFrame(None)
            if not restore_mode and not self.output_dir_user_selected:
                self.setPathLabel(self.output_path, self.defaultOutputDir(), self.uiText("ui.path.default_output"))
            if not restore_mode:
                self.setViewerCameraHeightValue(1.5)
                self.viewer_camera_height_dirty = False
                self.setViewerHudHeightScaleValue(1.0)
                self.viewer_hud_height_scale_dirty = False
            self.loadViewerSessionCameraHeight()
            self.writeViewerRuntimeConfig(show_error=False)
            if restore_mode and self.current_frame is not None:
                self.writeViewerCommandState({
                    "video": os.path.basename(self.video_file),
                    "frame_index": int(self.current_frame),
                    "yaw_to_camera_heading": 0.0,
                    "pitch": 0.0,
                    "zoom": 1.0,
                    "viewer_camera_height_m": self.viewerCameraHeightValue(),
                    "viewer_hud_height_scale": self.viewerHudHeightScaleValue(),
                    "viewer_projection": self.viewerProjectionValue(),
                    "viewer_flat_hfov_deg": self.viewerFlatHfovValue(),
                    "viewer_flat_vfov_deg": self.viewerFlatVfovValue(),
                    "viewer_front_offset_deg": self.videoFrontOffsetValue(),
                })

    def selectKP(self):
        """参照点CSVを選択する。未指定でも通常処理は可能。"""
        if self.database_restore_mode:
            return
        start_dir = self.dialogStartDir("kp", self.kp_file, self.gpx_file, self.video_file, self.output_dir)
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Reference CSV", start_dir, "CSV Files (*.csv)")
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
        try:
            nav_mode = self.nav_mode.currentData()
        except Exception:
            nav_mode = None
        selected_picked_target = False
        if nav_mode == "picked":
            selected_picked_target = self.selectViewerTargetFeature(frame_num)
        if feature is not None and self.frame_click_tool is not None:
            try:
                self.frame_click_tool.highlightFeature(feature)
            except Exception:
                pass
        if not selected_picked_target:
            self.centerMapOnFeature(feature)
        self.showFrameInViewer(frame_num)
        # ブラウザ表示を先に走らせ、重いJPEG抽出が体感レスポンスを邪魔しないようにする。
        QTimer.singleShot(150, lambda: self.extractFrame(frame_num, feature=feature))

    def centerMapOnFeature(self, feature, layer=None):
        """Follow有効時、表示フレーム地物を地図中心へ移動する。"""
        if feature is None:
            return
        if not getattr(self, "follow_frame_checkbox", None) or not self.follow_frame_checkbox.isChecked():
            return

        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            return

        try:
            layer = layer or self.activeFrameLayer()
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

    def normalizeViewerProjectionValue(self, value):
        """viewer projectionを現在対応する安全な値へ正規化する。"""
        text = str(value or "").strip().lower()
        aliases = {
            "360": VIEWER_PROJECTION_SPHERE,
            "equirectangular": VIEWER_PROJECTION_SPHERE,
            "pano": VIEWER_PROJECTION_SPHERE,
            "panorama": VIEWER_PROJECTION_SPHERE,
            "normal": VIEWER_PROJECTION_FLAT,
            "front": VIEWER_PROJECTION_FLAT,
            "pinhole": VIEWER_PROJECTION_FLAT,
        }
        text = aliases.get(text, text)
        return text if text in VIEWER_PROJECTION_VALUES else VIEWER_PROJECTION_SPHERE

    def viewerProjectionValue(self):
        """現在選択中のviewer projectionを返す。"""
        combo = getattr(self, "viewer_projection_combo", None)
        if combo is not None:
            value = combo.currentData()
            if value:
                return self.normalizeViewerProjectionValue(value)
        return self.normalizeViewerProjectionValue(getattr(self, "viewer_projection", VIEWER_PROJECTION_SPHERE))

    def viewerFlatHfovValue(self):
        """flat表示の水平FOVを返す。"""
        return float(getattr(self, "viewer_flat_hfov_deg", DEFAULT_VIEWER_FLAT_HFOV_DEG))

    def viewerFlatVfovValue(self):
        """flat表示の垂直FOVを返す。"""
        return float(getattr(self, "viewer_flat_vfov_deg", DEFAULT_VIEWER_FLAT_VFOV_DEG))

    def setViewerProjectionValue(self, value, reason="", dirty=None):
        """投影方式を内部状態とUIへ反映する。"""
        projection = self.normalizeViewerProjectionValue(value)
        self.viewer_projection = projection
        if dirty is not None:
            self.viewer_projection_dirty = bool(dirty)
        if reason is not None:
            self.viewer_projection_reason = str(reason or "")
        combo = getattr(self, "viewer_projection_combo", None)
        if combo is not None:
            index = combo.findData(projection)
            if index >= 0 and combo.currentIndex() != index:
                previous_blocked = combo.blockSignals(True)
                try:
                    combo.setCurrentIndex(index)
                finally:
                    combo.blockSignals(previous_blocked)
        label = getattr(self, "viewer_projection_reason_label", None)
        if label is not None:
            label.setText(self.viewer_projection_reason)
        return True

    def onViewerProjectionChanged(self, _index):
        """ユーザが投影方式を明示変更した時の状態更新。"""
        combo = getattr(self, "viewer_projection_combo", None)
        if combo is None:
            return
        self.viewer_projection = self.normalizeViewerProjectionValue(combo.currentData())
        self.viewer_projection_dirty = True
        self.viewer_projection_reason = "manual override"
        if getattr(self, "viewer_projection_reason_label", None) is not None:
            self.viewer_projection_reason_label.setText(self.viewer_projection_reason)
        self.writeViewerRuntimeConfig(show_error=False)
        self.writeViewerCommandViewerSettings()

    def videoDimensions(self, video_path):
        """OpenCVで動画の幅/高さを読む。読めない場合はNoneを返す。"""
        if not video_path:
            return None
        cap = None
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None
            width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
            height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
            if width <= 0 or height <= 0:
                return None
            return width, height
        except Exception:
            return None
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    def inferViewerProjectionFromVideo(self, video_path):
        """動画サイズから投影方式の初期候補を返す。最終判断はUI選択値を保存する。"""
        dimensions = self.videoDimensions(video_path)
        if not dimensions:
            return VIEWER_PROJECTION_SPHERE, "auto: video size unavailable"
        width, height = dimensions
        ratio = float(width) / float(height)
        projection = VIEWER_PROJECTION_SPHERE if abs(ratio - 2.0) <= 0.03 else VIEWER_PROJECTION_FLAT
        label = "360" if projection == VIEWER_PROJECTION_SPHERE else "flat"
        return projection, f"auto: {width}x{height}, aspect {ratio:.3f} -> {label}"

    def applyViewerProjectionAutoSuggestion(self, video_path, force=False):
        """動画サイズから投影方式を推定し、未手動変更ならUIへ反映する。"""
        projection, reason = self.inferViewerProjectionFromVideo(video_path)
        if force or not getattr(self, "viewer_projection_dirty", False):
            self.setViewerProjectionValue(projection, reason=reason, dirty=False)
        else:
            label = getattr(self, "viewer_projection_reason_label", None)
            if label is not None:
                label.setText(f"{self.viewer_projection_reason}; suggestion: {reason}")
        return projection, reason

    def normalizeVideoFrontOffset(self, value):
        """動画正面補正角を-180..180度へ正規化する。"""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return self.signedAngleDelta(0.0, numeric)

    def videoFrontOffsetValue(self):
        """動画正面と進行方向の補正角を取得する。"""
        widget = getattr(self, "video_front_offset", None)
        if widget is not None:
            value = float(widget.value())
        else:
            value = float(getattr(self, "video_front_offset_deg", 0.0))
        return self.normalizeVideoFrontOffset(value) or 0.0

    def setVideoFrontOffsetValue(self, value):
        """GPKGやviewer_sessionから読んだ動画正面補正角をUIへ反映する。"""
        numeric = self.normalizeVideoFrontOffset(value)
        if numeric is None:
            return False
        self.video_front_offset_deg = numeric

        widget = getattr(self, "video_front_offset", None)
        if widget is not None and abs(float(widget.value()) - numeric) > 0.0005:
            previous_blocked = widget.blockSignals(True)
            try:
                widget.setValue(numeric)
            finally:
                widget.blockSignals(previous_blocked)
        return True

    def loadViewerSessionCameraHeight(self, force=False):
        """既存viewer_session.jsonがあれば、ジョブ固有のviewer条件を復元する。"""
        camera_dirty = getattr(self, "viewer_camera_height_dirty", False)
        hud_dirty = getattr(self, "viewer_hud_height_scale_dirty", False)
        projection_dirty = getattr(self, "viewer_projection_dirty", False)
        if camera_dirty and hud_dirty and projection_dirty and not force:
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
        restored_projection = False
        if "viewer_projection" in state and (force or not projection_dirty):
            restored_projection = self.setViewerProjectionValue(
                state.get("viewer_projection"),
                reason="session",
                dirty=False,
            )
        if "viewer_flat_hfov_deg" in state:
            value = _parse_float(state.get("viewer_flat_hfov_deg"))
            if value is not None:
                self.viewer_flat_hfov_deg = max(1.0, min(179.0, float(value)))
        if "viewer_flat_vfov_deg" in state:
            value = _parse_float(state.get("viewer_flat_vfov_deg"))
            if value is not None:
                self.viewer_flat_vfov_deg = max(1.0, min(179.0, float(value)))
        restored_front = False
        if "viewer_front_offset_deg" in state:
            restored_front = self.setVideoFrontOffsetValue(state.get("viewer_front_offset_deg"))
        if restored_camera:
            self.viewer_camera_height_dirty = False
        if restored_hud:
            self.viewer_hud_height_scale_dirty = False
        if restored_projection:
            self.viewer_projection_dirty = False
        return restored_camera or restored_hud or restored_projection or restored_front

    def writeViewerCommandViewerSettings(self):
        """動画選択済みならviewer条件をviewer_command.jsonへ残す。"""
        if not self.video_file:
            return False
        path = self.viewerCommandPath()
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
        state["viewer_projection"] = self.viewerProjectionValue()
        state["viewer_flat_hfov_deg"] = self.viewerFlatHfovValue()
        state["viewer_flat_vfov_deg"] = self.viewerFlatVfovValue()
        state["viewer_front_offset_deg"] = self.videoFrontOffsetValue()
        state["command_id"] = uuid.uuid4().hex
        state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

        try:
            self.writeJsonFileAtomic(path, state)
            return True
        except OSError:
            return False

    def writeJsonFileAtomic(self, path, state):
        """同時書き込みでもtmp名が衝突しないようJSONを原子的に保存する。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            for attempt in range(5):
                try:
                    os.replace(tmp_path, path)
                    break
                except OSError:
                    if attempt >= 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def writeViewerCommandState(self, state):
        """QGIS側で補完したビューア表示指示をviewer_command.jsonへ原子的に書き込む。"""
        path = self.viewerCommandPath()
        state = dict(state)
        if "viewer_front_offset_deg" in state:
            self.setVideoFrontOffsetValue(state.get("viewer_front_offset_deg"))
        state["command_id"] = str(state.get("command_id") or uuid.uuid4().hex)
        state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            self.writeJsonFileAtomic(path, state)
            return state
        except OSError:
            return None

    def onViewerCameraHeightChanged(self, _value):
        """カメラ高さ変更をランタイム設定と開いているビューアへ反映する。"""
        self.setViewerCameraHeightValue(self.viewerCameraHeightValue(), mark_dirty=True)
        self.writeViewerRuntimeConfig(show_error=False)
        self.writeViewerCommandViewerSettings()
        if self.current_frame is not None and self.viewerHealth(timeout=0.15):
            self.postViewerNavigation(self.current_frame)

    def onViewerHudHeightScaleChanged(self, _value):
        """HUD高さ倍率変更をランタイム設定と開いているビューアへ反映する。"""
        self.setViewerHudHeightScaleValue(self.viewerHudHeightScaleValue(), mark_dirty=True)
        self.writeViewerRuntimeConfig(show_error=False)
        self.writeViewerCommandViewerSettings()
        if self.current_frame is not None and self.viewerHealth(timeout=0.15):
            self.postViewerNavigation(self.current_frame)

    def onVideoFrontOffsetChanged(self, _value):
        """動画正面補正をviewer_commandへ残し、ビューア表示へ反映する。"""
        self.setVideoFrontOffsetValue(self.videoFrontOffsetValue())
        self.writeViewerCommandViewerSettings()
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
        )

    def isCandidateLayer(self, layer):
        """YOLO由来の360候補点レイヤとして扱えるスキーマか確認する。"""
        fields = self.layerFields(layer)
        if fields is None:
            return False
        has_candidate_identity = any(
            fields.indexFromName(name) >= 0
            for name in ("semantic_class", "target_source", "evidence_face", "detection_id")
        )
        return (
            fields.indexFromName("frame") >= 0
            and fields.indexFromName("target_yaw") >= 0
            and fields.indexFromName("target_pitch") >= 0
            and has_candidate_identity
        )

    def isAllClassesCandidateLayer(self, layer):
        """全クラス集約のYOLO候補レイヤか確認する。"""
        if not self.isCandidateLayer(layer):
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
        return "all_classes" in text

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

    def findViewerTargetFeatureByFrame(self, frame_num):
        """指定frameの保存済みクリック点地物と所属レイヤを返す。"""
        target_frame = int(frame_num)
        current_video = os.path.basename(self.video_file or "")
        best_layer = None
        best_feature = None
        best_key = None
        for layer in self.viewerTargetReadLayers(target_frame):
            for feature in layer.getFeatures():
                frame_value = self.targetFeatureFloat(feature, "frame")
                if frame_value is None or int(frame_value) != target_frame:
                    continue
                feature_video = self.targetFeatureValue(feature, "video")
                if current_video and feature_video and str(feature_video) != current_video:
                    continue
                target_order = self.targetFeatureFloat(feature, "target_order")
                target_id = self.targetFeatureFloat(feature, "target_id")
                order_key = int(target_order) if target_order is not None else 0
                id_key = int(target_id) if target_id is not None else 0
                key = (order_key, id_key)
                if best_key is None or key >= best_key:
                    best_layer = layer
                    best_feature = feature
                    best_key = key
        return best_layer, best_feature

    def selectViewerTargetFeature(self, frame_num):
        """Picked pointナビ時に360 Click Targetsの該当点を選択して地図中心へ移動する。"""
        layer, feature = self.findViewerTargetFeatureByFrame(frame_num)
        if layer is None or feature is None:
            return False
        try:
            layer.removeSelection()
            layer.selectByIds([feature.id()])
        except Exception:
            pass
        try:
            if hasattr(self.iface, "setActiveLayer"):
                self.iface.setActiveLayer(layer)
        except Exception:
            pass
        self.centerMapOnFeature(feature, layer=layer)
        return True

    def gpkgLayer(self, gpkg_path, layer_name, display_name):
        """GeoPackage内の指定レイヤをQGISレイヤとして開く。"""
        layer = QgsVectorLayer(f"{gpkg_path}|layername={layer_name}", display_name, "ogr")
        try:
            return layer if layer.isValid() else None
        except Exception:
            return None

    def gpkgCandidateLayer(self, gpkg_path):
        """GeoPackage内のYOLO候補レイヤをQGISレイヤとして開く。"""
        layers = self.gpkgCandidateLayers(gpkg_path)
        return layers[0] if layers else None

    def normalizeCandidateLayerDisplayPrefix(self, display_name):
        """古い候補レイヤ表示prefixを現在の短い表記へ寄せる。"""
        text = str(display_name or "").strip()
        old_prefix = "360 POI Clusters:"
        if text.startswith(old_prefix):
            suffix = text[len(old_prefix):].strip()
            return f"POI: {suffix}" if suffix else "POI"
        return text

    def gpkgCandidateLayerDisplayName(self, layer_name, identifier="", description=""):
        """GPKG候補レイヤ名からQGIS表示名を作る。"""
        text = str(identifier or "").strip()
        if text:
            return self.normalizeCandidateLayerDisplayPrefix(text)
        text = str(layer_name or "").strip()
        if not text or text == GPKG_CANDIDATE_LAYER_NAME:
            return "360 Detection Candidates"
        if text.lower() == "all_classes":
            return "POI: All_Classes"
        if text.startswith("poi_clusters"):
            return f"POI: {text}"
        if text.startswith("poi_candidates"):
            return f"360 Detection Candidates: {text}"
        return f"360 Detection Candidates: {text}"

    def gpkgCandidateLayers(self, gpkg_path):
        """GeoPackage内のYOLO候補レイヤをすべてQGISレイヤとして開く。"""
        try:
            conn = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    """
                    SELECT table_name, identifier, description
                    FROM gpkg_contents
                    WHERE data_type = 'features'
                    ORDER BY table_name
                    """
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []

        layer_entries = []
        seen = set()
        for row in rows:
            layer_name = str(row[0] or "")
            identifier = str(row[1] or "")
            description = str(row[2] or "")
            display_name = self.gpkgCandidateLayerDisplayName(layer_name, identifier, description)
            if not self.isCandidateLayerName(display_name) and not self.isCandidateLayerName(layer_name):
                continue
            if layer_name in seen:
                continue
            seen.add(layer_name)
            layer_entries.append((layer_name, identifier, description))

        if not layer_entries:
            layer_entries.append((GPKG_CANDIDATE_LAYER_NAME, "", ""))

        layers = []
        for layer_name, identifier, description in layer_entries:
            display_name = self.gpkgCandidateLayerDisplayName(layer_name, identifier, description)
            layer = self.gpkgLayer(gpkg_path, layer_name, display_name)
            if layer is not None and self.isCandidateLayer(layer):
                layers.append(layer)
        return layers

    def layerFeatureCountTotal(self, layers):
        """複数レイヤのfeatureCount合計を返す。"""
        total = 0
        for layer in layers or []:
            total += self.layerFeatureCount(layer)
        return total

    def firstLayer(self, layers):
        """レイヤリストの先頭、またはNoneを返す。"""
        for layer in layers or []:
            if layer is not None:
                return layer
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
        inferred_class = ""
        for field_name in ("semantic_class", "semanticClass"):
            values = []
            seen = set()
            for source_feature in source_layer.getFeatures():
                try:
                    value = source_feature[field_name]
                except Exception:
                    value = None
                text = str(value or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                values.append(text)
                if len(values) >= 2:
                    break
            if len(values) == 1:
                inferred_class = values[0]
                break
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
        self.createLayerSpatialIndex(layer)
        if inferred_class:
            try:
                layer.setCustomProperty("tenkaku.semantic_class", inferred_class)
                layer.setCustomProperty("tenkaku.semantic_class_key", self.semanticClassKey(inferred_class))
                layer.setName(self.candidateLayerDisplayNameWithAlias(layer.name(), inferred_class))
            except Exception:
                pass
        return layer

    def createLayerSpatialIndex(self, layer):
        """可能ならメモリレイヤに空間インデックスを作成する。"""
        if layer is None:
            return False
        try:
            provider = layer.dataProvider()
        except Exception:
            return False
        creator = getattr(provider, "createSpatialIndex", None)
        if not callable(creator):
            return False
        try:
            return bool(creator())
        except Exception:
            return False

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

    def applyCandidateHiddenColumns(self, layer):
        """YOLO候補レイヤの証跡列を初期非表示にする。"""
        return self.applyHiddenColumns(layer, VIEWER_CANDIDATE_HIDDEN_COLUMNS)

    def jobMetadataPayload(self):
        """GPKGへ残すジョブ入力・校正パラメータを返す。"""
        process_config = getattr(self, "last_process_config", None)
        video_file = process_config.video_file if process_config else self.video_file
        return {
            "metadata_version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "gpx_file": process_config.gpx_file if process_config else self.gpx_file,
            # GPKGは別マシンへ持ち回るため、MP4の絶対パスは保存しない。
            "video_file": "",
            "video_name": os.path.basename(video_file) if video_file else "",
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
            "viewer_projection": self.viewerProjectionValue(),
            "viewer_projection_reason": str(getattr(self, "viewer_projection_reason", "") or ""),
            "viewer_flat_hfov_deg": float(self.viewerFlatHfovValue()),
            "viewer_flat_vfov_deg": float(self.viewerFlatVfovValue()),
            "video_front_offset_deg": float(self.videoFrontOffsetValue()),
            "viewer_front_offset_deg": float(self.videoFrontOffsetValue()),
            "nav_step": int(self.nav_step.value()),
            "nav_fast_step": int(self.nav_fast_step.value()),
            "follow_frame": bool(self.follow_frame_checkbox.isChecked()),
            "hidden_columns": {
                GPKG_TARGET_LAYER_NAME: list(VIEWER_TARGET_HIDDEN_COLUMNS),
                GPKG_CANDIDATE_LAYER_NAME: list(VIEWER_CANDIDATE_HIDDEN_COLUMNS),
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
        if "viewer_projection" in metadata:
            self.setViewerProjectionValue(
                metadata.get("viewer_projection"),
                reason=self.metadataText(metadata, "viewer_projection_reason") or "metadata",
                dirty=False,
            )
        if "viewer_flat_hfov_deg" in metadata:
            value = _parse_float(metadata.get("viewer_flat_hfov_deg"))
            if value is not None:
                self.viewer_flat_hfov_deg = max(1.0, min(179.0, float(value)))
        if "viewer_flat_vfov_deg" in metadata:
            value = _parse_float(metadata.get("viewer_flat_vfov_deg"))
            if value is not None:
                self.viewer_flat_vfov_deg = max(1.0, min(179.0, float(value)))
        if "video_front_offset_deg" in metadata:
            self.setVideoFrontOffsetValue(metadata.get("video_front_offset_deg"))
        elif "viewer_front_offset_deg" in metadata:
            self.setVideoFrontOffsetValue(metadata.get("viewer_front_offset_deg"))

        if "follow_frame" in metadata:
            self.follow_frame_checkbox.setChecked(self.parseViewerBool(metadata.get("follow_frame")))
        return True

    def inferVideoPathFromDatabase(self, gpkg_path, target_layer=None, metadata=None):
        """GPKGの位置、metadata、属性から関連MP4候補を推定する。"""
        gpkg_dir = os.path.dirname(os.path.abspath(gpkg_path))
        parent_dir = os.path.dirname(gpkg_dir)
        search_dirs = []
        for directory in (gpkg_dir, parent_dir):
            if directory and directory not in search_dirs:
                search_dirs.append(directory)

        video_names = []
        for value in (
            self.metadataText(metadata, "video_name"),
            self.metadataText(metadata, "video_file"),
            self.firstLayerValue(target_layer, "video"),
            os.path.basename(gpkg_dir) + ".mp4",
        ):
            text = str(value or "").strip()
            if not text:
                continue
            name = os.path.basename(os.path.normpath(text))
            if name and name not in video_names:
                video_names.append(name)

        for video_name in video_names:
            for directory in search_dirs:
                candidate = os.path.join(directory, video_name)
                if os.path.isfile(candidate):
                    return candidate

        mp4_candidates = []
        for directory in search_dirs:
            try:
                names = os.listdir(directory)
            except OSError:
                continue
            for name in names:
                if not name.lower().endswith(".mp4"):
                    continue
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate) and candidate not in mp4_candidates:
                    mp4_candidates.append(candidate)
        return mp4_candidates[0] if len(mp4_candidates) == 1 else ""

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
        if self.generatedLayers():
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
        target_source = self.gpkgLayer(gpkg_path, GPKG_TARGET_LAYER_NAME, "360 Click Targets")

        candidate_sources = self.gpkgCandidateLayers(gpkg_path)

        frame_layer = self.cloneLayerToMemory(frame_source, "Video GPX Points") if frame_source is not None else None
        target_layer = self.cloneLayerToMemory(target_source, "360 Click Targets") if target_source is not None else None
        candidate_layers = [
            self.cloneLayerToMemory(source_layer, source_layer.name())
            for source_layer in candidate_sources
        ]
        candidate_layer = self.firstLayer(candidate_layers)

        project = QgsProject.instance()
        self.created_layer_ids = []
        self.save_on_exit_layer_ids = set()
        self.loaded_layer_feature_counts = {}
        self.frame_layer_id = None
        if frame_layer is not None:
            self.addLayerToGroup(frame_layer, "Session", checked=True)
            self.created_layer_ids.append(frame_layer.id())
            self.registerLoadedLayerForChangeTracking(frame_layer)
            self.frame_layer_id = frame_layer.id()

        if target_layer is not None:
            self.applyViewerTargetHiddenColumns(target_layer)
            self.addLayerToGroup(target_layer, "Session", checked=False)
            self.created_layer_ids.append(target_layer.id())
            self.registerLoadedLayerForChangeTracking(target_layer)
            self.target_layer_id = target_layer.id()
        else:
            self.target_layer_id = None

        self.candidate_layer_id = None
        for candidate_layer in candidate_layers:
            self.applyCandidateHiddenColumns(candidate_layer)
            self.addLayerToGroup(candidate_layer, "All_POIs", checked=False)
            self.created_layer_ids.append(candidate_layer.id())
            self.registerLoadedLayerForChangeTracking(candidate_layer)
            if self.candidate_layer_id is None:
                self.candidate_layer_id = candidate_layer.id()
        candidate_layer = self.firstLayer(candidate_layers)
        self.syncCandidateLayerStyles(candidate_layers)

        self.database_file = gpkg_path
        self.loaded_gpkg_path = gpkg_path
        self.output_dir = os.path.dirname(gpkg_path)
        self.output_dir_user_selected = True
        self.setPathLabel(self.database_path, gpkg_path, self.uiText("ui.path.no_database"))
        self.setPathLabel(self.output_path, self.output_dir, self.uiText("ui.path.default_output"))

        # GPKG内のMP4絶対パスは別マシンでは信用しない。
        # 既にユーザが選んだMP4は明示指定として維持し、未選択なら
        # metadataのvideo_nameやGPKG近傍から関連MP4を既定候補として復元する。
        restored_video = self.video_file if self.video_file and os.path.isfile(self.video_file) else ""
        if not restored_video:
            restored_video = self.inferVideoPathFromDatabase(gpkg_path, frame_layer, job_metadata)
        restored_gpx = self.metadataText(job_metadata, "gpx_file") or self.inferGpxPathFromDatabase(gpkg_path)
        restored_kp = self.metadataText(job_metadata, "kp_file")
        self.video_file = restored_video
        self.gpx_file = restored_gpx
        self.kp_file = restored_kp
        self.setPathLabel(self.video_path, restored_video, self.uiText("ui.path.no_video"))
        self.setPathLabel(self.gpx_path, restored_gpx, self.uiText("ui.path.no_gpx"))
        self.setPathLabel(self.kp_path, restored_kp, self.uiText("ui.path.no_kp"))
        self.applyJobMetadata(job_metadata)
        if restored_video and "viewer_projection" not in job_metadata:
            self.applyViewerProjectionAutoSuggestion(restored_video, force=True)

        self.last_rows = []
        self.saved_viewer_target_keys = set()
        self.rebuildFramePositionCacheFromLayer(frame_layer)
        picked_frames = self.pickedFrames()
        detection_frames = self.detectionFrames()
        first_frame = (
            picked_frames[0]
            if picked_frames
            else detection_frames[0] if detection_frames else self.firstFrameInLayer(frame_layer)
        )
        self.setCurrentFrame(first_frame)
        self.setNavigationModeByData("picked" if picked_frames else "detect" if detection_frames else "layer")
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
                "viewer_projection": self.viewerProjectionValue(),
                "viewer_flat_hfov_deg": self.viewerFlatHfovValue(),
                "viewer_flat_vfov_deg": self.viewerFlatVfovValue(),
                "viewer_front_offset_deg": self.videoFrontOffsetValue(),
            }
            initial_targets = []
            picked_view = self.viewerViewForPickedFrame(first_frame) if picked_frames else None
            if picked_frames:
                initial_targets = self.viewerTargetsForFrame(first_frame)
            elif detection_frames:
                initial_targets = self.viewerDetectionTargetsForFrame(first_frame)
                picked_view = self.viewerViewForDetectionFrame(first_frame)
            if picked_view:
                initial_state.update(picked_view)
            if initial_targets:
                initial_state["targets"] = initial_targets
                initial_state["target"] = initial_targets[-1]
            self.writeViewerCommandState(initial_state)
        else:
            self.writeViewerCommandViewerSettings()
        self.setDatabaseRestoreMode(True)

        self.notifyInfo(
            "database_loaded",
            frame_layer=self.layerFeatureCount(frame_layer),
            target_layer=self.layerFeatureCount(target_layer),
            candidate_layer=self.layerFeatureCountTotal(candidate_layers),
            path=gpkg_path,
        )
        return True

    def viewerTargetLayer(self):
        """360クリック投影点を書き込む自前メモリレイヤを返す。"""
        project = QgsProject.instance()
        if self.target_layer_id:
            layer = project.mapLayer(self.target_layer_id)
            if (
                self.isViewerTargetLayer(layer)
                and not self.isCandidateLayer(layer)
                and self.isMemoryLayer(layer)
            ):
                self.ensureViewerTargetLayerFields(layer)
                self.applyViewerTargetHiddenColumns(layer)
                return layer

        for layer_id in reversed(self.created_layer_ids):
            layer = project.mapLayer(layer_id)
            if (
                self.isViewerTargetLayer(layer)
                and not self.isCandidateLayer(layer)
                and self.isMemoryLayer(layer)
            ):
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
        for field_name, field_type in VIEWER_TARGET_FIELD_DEFS:
            if fields.indexFromName(field_name) < 0:
                missing_fields.append(QgsField(field_name, field_type))
        if not missing_fields:
            self.applyViewerTargetHiddenColumns(layer)
            return False
        layer.dataProvider().addAttributes(missing_fields)
        layer.updateFields()
        self.markLayerSaveOnExit(layer)
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
            QgsField(field_name, field_type)
            for field_name, field_type in VIEWER_TARGET_FIELD_DEFS
        ])
        layer.updateFields()
        self.applyViewerTargetHiddenColumns(layer)
        QgsProject.instance().addMapLayer(layer)
        self.created_layer_ids.append(layer.id())
        self.markLayerSaveOnExit(layer)
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
        if not self.isViewerTargetLayer(layer) or self.isCandidateLayer(layer):
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
        if not self.isViewerTargetLayer(layer) or self.isCandidateLayer(layer):
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
        if not self.isViewerTargetLayer(layer) or self.isCandidateLayer(layer):
            return False
        if not video_name:
            return True

        for feature in layer.getFeatures():
            feature_video = self.targetFeatureValue(feature, "video")
            if feature_video and str(feature_video) != str(video_name):
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
            if not self.isViewerTargetLayer(layer) or self.isCandidateLayer(layer):
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
        x_ratio = self.targetFeatureFloat(feature, "x_ratio")
        y_ratio = self.targetFeatureFloat(feature, "y_ratio")
        projection = self.targetFeatureValue(feature, "projection") or "ground_plane"
        distance_m = self.targetFeatureFloat(feature, "distance_m")
        map_bearing = self.targetFeatureFloat(feature, "bearing_deg")
        quality = self.targetFeatureValue(feature, "quality")

        target = {
            "id": target_id,
            "order": target_order,
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
        has_legacy_center_ratio = (
            x_ratio is not None
            and y_ratio is not None
            and abs(float(x_ratio) - 0.5) < 0.000001
            and abs(float(y_ratio) - 0.5) < 0.000001
            and (
                abs(float(yaw_delta)) > 0.001
                or abs(float(target_pitch) - float(view_pitch)) > 0.001
            )
        )
        if x_ratio is not None and not has_legacy_center_ratio:
            target["x_ratio"] = max(0.0, min(1.0, float(x_ratio)))
        if y_ratio is not None and not has_legacy_center_ratio:
            target["y_ratio"] = max(0.0, min(1.0, float(y_ratio)))
        if map_bearing is not None:
            target["map_bearing_deg"] = float(map_bearing) % 360.0
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

    def candidateLayer(self):
        """YOLO候補点の一時メモリレイヤを返す。"""
        project = QgsProject.instance()
        if self.candidate_layer_id:
            layer = project.mapLayer(self.candidate_layer_id)
            if self.isCandidateLayer(layer) and self.isMemoryLayer(layer):
                self.applyCandidateHiddenColumns(layer)
                return layer

        for layer_id in reversed(self.created_layer_ids):
            layer = project.mapLayer(layer_id)
            if self.isCandidateLayer(layer) and self.isMemoryLayer(layer):
                self.candidate_layer_id = layer.id()
                self.applyCandidateHiddenColumns(layer)
                return layer
        return None

    def currentDetectionScope(self):
        """Detection check Navで使う候補レイヤ範囲を返す。"""
        try:
            mode = self.nav_mode.currentData()
        except Exception:
            mode = None
        try:
            value = self.nav_scope.currentData()
        except Exception:
            value = None
        return str(value or "visible")

    def preferredNavigationLayerForMode(self, mode):
        """指定Navモードに対応する既定レイヤを返す。"""
        mode = str(mode or "")
        if mode in ("frame", "layer", "kp"):
            return self.activeFrameLayer()
        if mode == "picked":
            layer = self.viewerTargetLayer()
            if layer is not None:
                return layer
            layers = self.viewerTargetReadLayers()
            return layers[0] if layers else None
        if mode == "detect":
            for layer in self.projectCandidateLayers(visible_only=False):
                if self.layerSelectedFeatureIds(layer):
                    return layer
            for layer in self.projectCandidateLayers(visible_only=False):
                try:
                    if str(layer.subsetString() or "").strip():
                        return layer
                except Exception:
                    continue
            active = self.activeCandidateLayer()
            if active is not None:
                return active
            layers = self.projectCandidateLayers(visible_only=False)
            for layer in layers:
                if self.isAllClassesCandidateLayer(layer):
                    return layer
            return layers[0] if layers else None
        return None

    def activateNavigationLayer(self, layer):
        """レイヤツリーとアクティブレイヤを揃える。"""
        if layer is None:
            return False
        changed = False
        try:
            if hasattr(self.iface, "setActiveLayer"):
                self.iface.setActiveLayer(layer)
                changed = True
        except Exception:
            pass
        try:
            tree_view = self.iface.layerTreeView() if hasattr(self.iface, "layerTreeView") else None
            if tree_view is not None and hasattr(tree_view, "setCurrentLayer"):
                tree_view.setCurrentLayer(layer)
                changed = True
        except Exception:
            pass
        try:
            canvas = self.iface.mapCanvas()
            if canvas is not None and hasattr(canvas, "setCurrentLayer"):
                canvas.setCurrentLayer(layer)
                changed = True
        except Exception:
            pass
        return changed

    def syncNavigationLayerForMode(self, mode=None):
        """Navモードに合わせて既定レイヤを前面へ出す。"""
        if mode is None:
            try:
                mode = self.nav_mode.currentData()
            except Exception:
                mode = None
        layer = self.preferredNavigationLayerForMode(mode)
        if layer is None:
            return False
        return self.activateNavigationLayer(layer)

    def onNavigationModeChanged(self, *_args):
        """Navモード変更時にレイヤ選択を同期する。"""
        self.syncNavigationLayerForMode()

    def activeCandidateLayer(self):
        """QGISで現在アクティブなYOLO候補レイヤを返す。"""
        try:
            layer = self.iface.activeLayer()
        except Exception:
            return None
        if self.isCandidateLayer(layer):
            self.applyCandidateHiddenColumns(layer)
            return layer
        return None

    def ensureLayerTreeGroup(self, group_name):
        """指定名のレイヤグループを取得または作成する。"""
        root = QgsProject.instance().layerTreeRoot()
        group = None
        finder = getattr(root, "findGroup", None)
        if callable(finder):
            try:
                group = finder(group_name)
            except Exception:
                group = None
        if group is None:
            try:
                group = root.insertGroup(0, group_name)
            except Exception:
                group = root.addGroup(group_name)
        elif group.parent() == root:
            try:
                children = list(root.children() or [])
                if children.index(group) > 0:
                    clone = group.clone()
                    root.insertChildNode(0, clone)
                    root.removeChildNode(group)
                    group = clone
            except Exception:
                pass
        if group is not None:
            try:
                group.setExpanded(False)
            except Exception:
                pass
        return group

    def addLayerToGroup(self, layer, group_name, checked=False):
        """レイヤを指定グループへ入れて、初期表示状態を設定する。"""
        if layer is None:
            return None
        project = QgsProject.instance()
        group = self.ensureLayerTreeGroup(group_name)
        try:
            project.addMapLayer(layer, False)
        except Exception:
            project.addMapLayer(layer)
        try:
            node = group.addLayer(layer) if group is not None else None
        except Exception:
            node = None
        if node is None:
            try:
                node = project.layerTreeRoot().findLayer(layer.id())
            except Exception:
                node = None
        if node is not None:
            try:
                node.setItemVisibilityChecked(bool(checked))
            except Exception:
                pass
        return node

    def removeLayerTreeGroupIfEmpty(self, group_name):
        """指定グループが空ならレイヤツリーから削除する。"""
        try:
            root = QgsProject.instance().layerTreeRoot()
        except Exception:
            return False
        group = None
        finder = getattr(root, "findGroup", None)
        if callable(finder):
            try:
                group = finder(group_name)
            except Exception:
                group = None
        if group is None:
            return False
        try:
            children = list(group.children() or [])
        except Exception:
            children = []
        if children:
            return False
        try:
            parent = group.parent()
        except Exception:
            parent = None
        if parent is None:
            return False
        try:
            parent.removeChildNode(group)
            return True
        except Exception:
            return False

    def cleanupLayerTreeGroups(self):
        """このプラグインの空グループを片付ける。"""
        removed = False
        for group_name in ("Session", "All_POIs"):
            removed = self.removeLayerTreeGroupIfEmpty(group_name) or removed
        return removed

    def pluginRootDir(self):
        """プラグインのインストール先ディレクトリを返す。"""
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return ""

    def defaultCandidateStylePath(self):
        """class styleの正本になるQMLの既定パスを返す。"""
        path = os.path.join(self.pluginRootDir(), "styles", "default_style.qml")
        return path if os.path.isfile(path) else ""

    def candidateModelNames(self, layers):
        """候補レイヤ群からmodel_nameを収集する。"""
        names = set()
        for layer in layers or []:
            for value in self.layerFieldDistinctValues(layer, "model_name", limit=2):
                text = str(value or "").strip()
                if text:
                    names.add(text)
                if len(names) >= 2:
                    return names
        return names

    def candidateModelStylePaths(self, model_name):
        """model_nameから探索するQML候補パスを返す。"""
        text = str(model_name or "").strip()
        if not text:
            return []
        styles_dir = os.path.join(self.pluginRootDir(), "styles")
        base = os.path.splitext(os.path.basename(text))[0]
        stems = []
        for stem in (base, base.lower(), self.semanticClassKey(base), _safe_gpkg_layer_name(base)):
            stem_text = str(stem or "").strip()
            if stem_text and stem_text not in stems:
                stems.append(stem_text)
        return [os.path.join(styles_dir, f"{stem}.qml") for stem in stems]

    def candidateStylePathForLayers(self, layers):
        """候補レイヤ群に対応するQMLスタイルを返す。"""
        model_names = self.candidateModelNames(layers)
        if len(model_names) == 1:
            model_name = next(iter(model_names))
            for path in self.candidateModelStylePaths(model_name):
                if os.path.isfile(path):
                    return path
        return self.defaultCandidateStylePath()

    def classAliasMapFromCategorizedRenderer(self, layer):
        """categorical rendererからsemantic_class->表示ラベルを作る。"""
        aliases = {}
        if layer is None:
            return aliases
        try:
            renderer = layer.renderer()
        except Exception:
            renderer = None
        if not isinstance(renderer, QgsCategorizedSymbolRenderer):
            return aliases
        try:
            categories = list(renderer.categories() or [])
        except Exception:
            categories = []
        for category in categories:
            try:
                value = category.value()
            except Exception:
                value = None
            class_name = str(value or "").strip()
            if not class_name or class_name.lower() == "null":
                continue
            try:
                label = str(category.label() or "").strip()
            except Exception:
                label = ""
            if not label or label == class_name:
                continue
            for key in {
                class_name,
                class_name.lower(),
                self.semanticClassKey(class_name),
                self.semanticClassKey(class_name.split(":", 1)[-1] if ":" in class_name else class_name),
            }:
                key_text = str(key or "").strip()
                if key_text:
                    aliases[key_text] = label
        return aliases

    def classLabelToValueMapFromCategorizedRenderer(self, layer):
        """categorical rendererから表示ラベル->semantic_classを作る。"""
        label_to_value = {}
        if layer is None:
            return label_to_value
        try:
            renderer = layer.renderer()
        except Exception:
            renderer = None
        if not isinstance(renderer, QgsCategorizedSymbolRenderer):
            return label_to_value
        try:
            categories = list(renderer.categories() or [])
        except Exception:
            categories = []
        for category in categories:
            try:
                value = str(category.value() or "").strip()
            except Exception:
                value = ""
            try:
                label = str(category.label() or "").strip()
            except Exception:
                label = ""
            if value and label:
                label_to_value[label] = value
        return label_to_value

    def semanticClassDisplayName(self, semantic_class):
        """semantic_classのQGIS表示名を返す。"""
        text = str(semantic_class or "").strip()
        if not text:
            return ""
        aliases = dict(getattr(self, "_candidate_style_aliases", {}) or {})
        alias = aliases.get(text)
        if alias is None:
            alias = aliases.get(text.lower())
        if alias is None:
            alias = aliases.get(self.semanticClassKey(text))
        if alias is None and ":" in text:
            tail = text.split(":", 1)[-1].strip()
            alias = aliases.get(tail) or aliases.get(tail.lower()) or aliases.get(self.semanticClassKey(tail))
        return str(alias or text).strip()

    def semanticClassFromDisplayName(self, label):
        """凡例表示名からsemantic_classへ戻す。"""
        text = str(label or "").strip()
        if not text:
            return ""
        label_to_value = dict(getattr(self, "_candidate_style_label_to_value", {}) or {})
        semantic_class = label_to_value.get(text)
        if semantic_class:
            return semantic_class
        aliases = dict(getattr(self, "_candidate_style_aliases", {}) or {})
        if text in aliases:
            return text
        return text

    def candidateLayerDisplayNameWithAlias(self, display_name, semantic_class):
        """単一クラスレイヤの表示名にエイリアスを反映する。"""
        base = str(display_name or "").strip()
        class_name = str(semantic_class or "").strip()
        alias = self.semanticClassDisplayName(class_name)
        if not base or not class_name or not alias or alias == class_name:
            return self.normalizeCandidateLayerDisplayPrefix(base)
        normalized_base = self.normalizeCandidateLayerDisplayPrefix(base)
        if normalized_base.startswith("POI:"):
            return f"POI: {alias}"
        if normalized_base.startswith("360 Detection Candidates:"):
            return f"360 Detection Candidates: {alias}"
        return alias

    def loadNamedStyleIntoLayer(self, layer, style_path):
        """QMLスタイルをレイヤへ読み込む。"""
        if layer is None:
            return False
        path = str(style_path or "").strip()
        if not path or not os.path.isfile(path):
            return False
        try:
            result = layer.loadNamedStyle(path)
        except Exception:
            return False

        ok = False
        if isinstance(result, tuple):
            ok = bool(result[0])
        elif result is not None:
            ok = bool(result)
        if ok:
            try:
                layer.triggerRepaint()
            except Exception:
                pass
        return ok

    def layerFieldDistinctValues(self, layer, field_name, limit=3):
        """レイヤ内の指定フィールドの異なる値を少数だけ返す。"""
        values = []
        if layer is None or not field_name:
            return values
        seen = set()
        try:
            for feature in layer.getFeatures():
                value = self.targetFeatureValue(feature, field_name)
                text = str(value or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                values.append(text)
                if limit and len(values) >= int(limit):
                    break
        except Exception:
            return values
        return values

    def semanticClassKey(self, value):
        """semantic_class照合用の正規化キーを返す。"""
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if ":" in text:
            text = text.split(":", 1)[-1].strip()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text

    def layerSemanticClassValues(self, layer, limit=3):
        """レイヤ内のsemantic_class候補を返す。"""
        return self.layerFieldDistinctValues(layer, "semantic_class", limit=limit)

    def sortedLayerSemanticClasses(self, layer):
        """レイヤ内のsemantic_classを文字列昇順で返す。"""
        values = self.layerSemanticClassValues(layer, limit=0)
        return sorted({str(value or "").strip() for value in values if str(value or "").strip()})

    def layerSingleSemanticClass(self, layer):
        """単一クラスレイヤならsemantic_classを返す。"""
        if layer is not None:
            try:
                hint = str(layer.customProperty("tenkaku.semantic_class", "") or "").strip()
            except Exception:
                hint = ""
            if hint:
                return hint
        values = self.sortedLayerSemanticClasses(layer)
        return values[0] if len(values) == 1 else ""

    def inferLayerSemanticClass(self, layer):
        """単一クラスのレイヤならsemantic_classを推定して返す。"""
        if layer is not None:
            try:
                hint = str(layer.customProperty("tenkaku.semantic_class", "") or "").strip()
            except Exception:
                hint = ""
            if hint:
                return hint
        values = self.layerSemanticClassValues(layer, limit=2)
        if len(values) == 1:
            return values[0]
        if layer is None:
            return ""
        for text in (getattr(layer, "name", lambda: "")(), getattr(layer, "source", lambda: "")()):
            text = str(text or "").strip()
            if not text:
                continue
            if "poi_clusters_" in text:
                return text.split("poi_clusters_", 1)[1].strip()
            if "poi_candidates_" in text:
                return text.split("poi_candidates_", 1)[1].strip()
            if ":" in text:
                tail = text.rsplit(":", 1)[-1].strip()
                if tail:
                    return tail
        return ""

    def allClassesCandidateLayer(self, layers=None):
        """All_Classes候補レイヤを返す。"""
        for layer in layers or []:
            if self.isAllClassesCandidateLayer(layer):
                return layer
        project = QgsProject.instance()
        for layer in reversed(list(project.mapLayers().values())):
            if self.isAllClassesCandidateLayer(layer):
                return layer
        return None

    def symbolMapFromCategorizedRenderer(self, layer):
        """categorical rendererからsemantic_class->symbolを作る。"""
        symbol_map = {}
        if layer is None:
            return symbol_map
        try:
            renderer = layer.renderer()
        except Exception:
            renderer = None
        if not isinstance(renderer, QgsCategorizedSymbolRenderer):
            return symbol_map
        try:
            categories = list(renderer.categories() or [])
        except Exception:
            categories = []
        for category in categories:
            try:
                value = category.value()
            except Exception:
                value = None
            text = str(value or "").strip()
            if not text or text.lower() == "null":
                continue
            try:
                symbol = category.symbol()
            except Exception:
                symbol = None
            if symbol is None:
                continue
            try:
                cloned = symbol.clone()
            except Exception:
                cloned = symbol
            for key in {
                text,
                text.lower(),
                self.semanticClassKey(text),
                self.semanticClassKey(text.split(":", 1)[-1] if ":" in text else text),
            }:
                key_text = str(key or "").strip()
                if key_text:
                    symbol_map[key_text] = cloned.clone() if hasattr(cloned, "clone") else cloned
        return symbol_map

    def classSymbolMapFromAllClassesLayer(self, all_classes_layer):
        """All_Classesのcategorical rendererからsemantic_class->symbolを作る。"""
        return self.symbolMapFromCategorizedRenderer(all_classes_layer)

    def candidateStyleSourceLayer(self, layers):
        """default_style.qmlを読み込む代表候補レイヤを返す。"""
        for layer in layers or []:
            if layer is None:
                continue
            if self.sortedLayerSemanticClasses(layer):
                return layer
        return self.firstLayer(layers)

    def candidateSymbolMapFromDefaultStyle(self, layers):
        """対応QMLスタイルからsemantic_class->symbolを取り出す。"""
        source_layer = self.candidateStyleSourceLayer(layers)
        if source_layer is None:
            return {}
        style_path = self.candidateStylePathForLayers(layers)
        if style_path:
            self.loadNamedStyleIntoLayer(source_layer, style_path)
        self._candidate_style_path = style_path
        self._candidate_style_aliases = self.classAliasMapFromCategorizedRenderer(source_layer)
        self._candidate_style_label_to_value = self.classLabelToValueMapFromCategorizedRenderer(source_layer)
        return self.symbolMapFromCategorizedRenderer(source_layer)

    def symbolForSemanticClass(self, symbol_map, semantic_class):
        """semantic_classに対応するシンボルを返す。"""
        text = str(semantic_class or "").strip()
        if not text:
            return None
        symbol = symbol_map.get(text)
        if symbol is None:
            symbol = symbol_map.get(text.lower())
        if symbol is None:
            symbol = symbol_map.get(self.semanticClassKey(text))
        if symbol is None and ":" in text:
            tail = text.split(":", 1)[-1].strip()
            symbol = symbol_map.get(tail) or symbol_map.get(tail.lower()) or symbol_map.get(self.semanticClassKey(tail))
        return symbol

    def fallbackSymbolForSemanticClass(self, layer, semantic_class, index=0):
        """default_styleにないsemantic_class用のフォールバックシンボルを返す。"""
        try:
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        except Exception:
            symbol = None
        if symbol is None:
            try:
                renderer = layer.renderer()
                base_symbol = renderer.symbol() if hasattr(renderer, "symbol") else None
                symbol = base_symbol.clone() if hasattr(base_symbol, "clone") else base_symbol
            except Exception:
                symbol = None
        if symbol is not None:
            try:
                key = str(semantic_class or "")
                hue = (sum((pos + 1) * ord(char) for pos, char in enumerate(key)) + int(index) * 47) % 360
                symbol.setColor(QtGui.QColor.fromHsv(hue, 180, 220))
            except Exception:
                pass
        return symbol

    def applySingleSymbolFromMap(self, layer, symbol_map, semantic_class=""):
        """単一クラスレイヤへsemantic_class対応シンボルを当てる。"""
        if layer is None:
            return False
        semantic_class = str(semantic_class or "").strip() or self.layerSingleSemanticClass(layer)
        if not semantic_class:
            return False
        symbol = self.symbolForSemanticClass(symbol_map, semantic_class)
        if symbol is None:
            symbol = self.fallbackSymbolForSemanticClass(layer, semantic_class)
        if symbol is None:
            return False
        try:
            layer.setRenderer(QgsSingleSymbolRenderer(symbol.clone() if hasattr(symbol, "clone") else symbol))
            layer.triggerRepaint()
            return True
        except Exception:
            return False

    def applyCategorizedSemanticClassStyle(self, layer, symbol_map):
        """複数クラスレイヤをsemantic_classで分類表示する。"""
        if layer is None:
            return False
        class_values = self.sortedLayerSemanticClasses(layer)
        if not class_values:
            return False
        if len(class_values) == 1:
            try:
                layer.setName(self.candidateLayerDisplayNameWithAlias(layer.name(), class_values[0]))
            except Exception:
                pass
            return self.applySingleSymbolFromMap(layer, symbol_map, class_values[0])

        categories = []
        for index, semantic_class in enumerate(class_values):
            symbol = self.symbolForSemanticClass(symbol_map, semantic_class)
            if symbol is None:
                symbol = self.fallbackSymbolForSemanticClass(layer, semantic_class, index)
            if symbol is None:
                continue
            try:
                categories.append(QgsRendererCategory(
                    semantic_class,
                    symbol.clone() if hasattr(symbol, "clone") else symbol,
                    self.semanticClassDisplayName(semantic_class),
                ))
            except Exception:
                continue
        if not categories:
            return False
        try:
            layer.setRenderer(QgsCategorizedSymbolRenderer("semantic_class", categories))
            layer.triggerRepaint()
            return True
        except Exception:
            return False

    def syncCandidateLayerStyles(self, candidate_layers=None):
        """semantic_classを正本にして候補レイヤへスタイルを同期する。"""
        layers = list(candidate_layers or [])
        if not layers:
            project = QgsProject.instance()
            layers = [
                layer for layer in reversed(list(project.mapLayers().values()))
                if self.isCandidateLayer(layer)
            ]
        if not layers:
            return False

        symbol_map = self.candidateSymbolMapFromDefaultStyle(layers)
        synced = False
        for layer in layers:
            if layer is None:
                continue
            synced = self.applyCategorizedSemanticClassStyle(layer, symbol_map) or synced
        return synced

    def layerTreeViewObject(self):
        """QGISのレイヤツリービューを安全に返す。"""
        try:
            return self.iface.layerTreeView() if hasattr(self.iface, "layerTreeView") else None
        except Exception:
            return None

    def legendNodeText(self, node):
        """legend nodeから表示テキストを安全に取り出す。"""
        if node is None:
            return ""
        for attr_name in ("label", "name", "text", "title", "description"):
            attr = getattr(node, attr_name, None)
            if callable(attr):
                try:
                    value = attr()
                    if value not in (None, ""):
                        return str(value)
                except Exception:
                    pass
        data = getattr(node, "data", None)
        if callable(data):
            for role in (QT_DISPLAY_ROLE, QT_EDIT_ROLE, QT_USER_ROLE):
                try:
                    value = data(role)
                    if value not in (None, ""):
                        return str(value)
                except Exception:
                    continue
        return ""

    def legendNodeLayer(self, node):
        """legend nodeに関連付くレイヤを安全に返す。"""
        if node is None:
            return None
        for attr_name in ("layer", "layerNode", "parentLayerNode"):
            attr = getattr(node, attr_name, None)
            if callable(attr):
                try:
                    candidate = attr()
                except Exception:
                    continue
                if candidate is None:
                    continue
                layer_attr = getattr(candidate, "layer", None)
                if callable(layer_attr):
                    try:
                        layer = layer_attr()
                        if layer is not None:
                            return layer
                    except Exception:
                        pass
                if self.isCandidateLayer(candidate):
                    return candidate
        return None

    def legendSelectedCandidateClasses(self, layer=None):
        """アクティブ候補レイヤで選択中のsemantic_class集合を返す。"""
        layer = layer or self.activeCandidateLayer()
        if layer is None:
            return set()

        selected = set()
        tree_view = self.layerTreeViewObject()
        if tree_view is not None:
            nodes = []
            for method_name in ("selectedLegendNodes", "selectedNodes"):
                method = getattr(tree_view, method_name, None)
                if callable(method):
                    try:
                        nodes = list(method() or [])
                    except Exception:
                        nodes = []
                    if nodes:
                        break
            for node in nodes:
                node_layer = self.legendNodeLayer(node)
                if node_layer is None or node_layer.id() != layer.id():
                    continue
                text = self.legendNodeText(node).strip()
                if text and not self.isCandidateLayerName(text):
                    selected.add(self.semanticClassFromDisplayName(text))

        if selected:
            return selected

        try:
            subset = str(layer.subsetString() or "").strip()
        except Exception:
            subset = ""
        if not subset:
            return selected

        patterns = (
            r"""semantic_class\s*=\s*['"]([^'"]+)['"]""",
            r"""semantic_class\s+LIKE\s*['"]([^'"]+)['"]""",
            r"""semantic_class\s+IN\s*\(([^)]+)\)""",
        )
        for pattern in patterns:
            match = re.search(pattern, subset, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1)
            if "IN" in pattern.upper():
                for item in re.findall(r"""['"]([^'"]+)['"]""", value):
                    text = str(item or "").strip()
                    if text:
                        selected.add(text)
            else:
                text = str(value or "").strip()
                if text:
                    selected.add(text)
            if selected:
                break
        return selected

    def activeCandidateSemanticClasses(self, layer=None):
        """アクティブ候補レイヤで現在有効なsemantic_class集合を返す。"""
        layer = layer or self.activeCandidateLayer()
        if layer is None:
            return set()

        active_classes = set()

        try:
            subset = str(layer.subsetString() or "").strip()
        except Exception:
            subset = ""
        if subset:
            active_classes.update(self.semanticClassesFromSubsetExpression(subset))

        try:
            renderer = layer.renderer()
        except Exception:
            renderer = None
        if renderer is not None and hasattr(renderer, "categories"):
            try:
                categories = list(renderer.categories() or [])
            except Exception:
                categories = []
            enabled = []
            total = 0
            for category in categories:
                total += 1
                try:
                    render_state = bool(category.renderState())
                except Exception:
                    render_state = True
                if not render_state:
                    continue
                try:
                    value = category.value()
                except Exception:
                    value = None
                text = str(value or "").strip()
                if text and text.lower() != "all_classes":
                    enabled.append(text)
            if enabled and len(enabled) < total:
                active_classes.update(enabled)

        return active_classes

    def semanticClassesFromSubsetExpression(self, subset):
        """subset expressionからsemantic_class候補を抽出する。"""
        text = str(subset or "").strip()
        if not text:
            return set()
        classes = set()
        patterns = (
            r"""semantic_class\s*=\s*['"]([^'"]+)['"]""",
            r"""semantic_class\s+LIKE\s*['"]([^'"]+)['"]""",
            r"""semantic_class\s+IN\s*\(([^)]+)\)""",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1)
            if "IN" in pattern.upper():
                for item in re.findall(r"""['"]([^'"]+)['"]""", value):
                    token = str(item or "").strip()
                    if token:
                        classes.add(token)
            else:
                token = str(value or "").strip()
                if token:
                    classes.add(token)
            if classes:
                break
        return classes

    def layerTreeVisible(self, layer):
        """QGISレイヤツリー上で表示対象になっているかを返す。"""
        if layer is None:
            return False
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        except Exception:
            node = None
        if node is None:
            return True
        for method_name in ("isVisible", "itemVisibilityChecked"):
            method = getattr(node, method_name, None)
            if callable(method):
                try:
                    return bool(method())
                except Exception:
                    pass
        return True

    def layerSelectedFeatureIds(self, layer):
        """レイヤ上で選択中のfeature id集合を返す。"""
        if layer is None:
            return set()
        try:
            if int(layer.selectedFeatureCount()) <= 0:
                return set()
            return set(layer.selectedFeatureIds())
        except Exception:
            return set()

    def candidateFeatureRequest(self, layer):
        """候補レイヤのQGIS subset/filter式を明示的に反映したFeatureRequestを返す。"""
        request = QgsFeatureRequest()
        if layer is None:
            return request
        try:
            subset = str(layer.subsetString() or "").strip()
        except Exception:
            subset = ""
        if not subset:
            return request
        try:
            expression = QgsExpression(subset)
            if not expression.hasParserError():
                request.setFilterExpression(subset)
        except Exception:
            pass
        return request

    def candidateFeatures(self, layer, selected_only=False):
        """候補レイヤの地物を返す。QGIS subset/filter式と選択状態をNav対象へ反映する。"""
        if layer is None:
            return

        selected_ids = self.layerSelectedFeatureIds(layer) if selected_only else set()
        if selected_only and not selected_ids:
            return

        request = self.candidateFeatureRequest(layer)
        for feature in layer.getFeatures(request):
            if selected_only and feature.id() not in selected_ids:
                continue
            yield feature

    def projectCandidateLayers(self, visible_only=False):
        """現在プロジェクト内のYOLO候補レイヤを重複なしで返す。"""
        project = QgsProject.instance()
        layers = []
        seen = set()

        def add_layer(layer):
            if not self.isCandidateLayer(layer):
                return
            if visible_only and not self.layerTreeVisible(layer):
                return
            layer_id = layer.id()
            if layer_id in seen:
                return
            self.applyCandidateHiddenColumns(layer)
            layers.append(layer)
            seen.add(layer_id)

        add_layer(self.candidateLayer())

        for layer in reversed(list(project.mapLayers().values())):
            add_layer(layer)

        for layer in reversed(list(project.mapLayers().values())):
            if self.isNamedCandidateLayer(layer):
                add_layer(layer)

        return layers

    def isCurrentGpkgCandidateLayer(self, layer):
        """現在ジョブのtmp.gpkg内poi_candidates_360レイヤかを判定する。"""
        if not self.isCandidateLayer(layer):
            return False
        try:
            source = str(layer.source())
        except Exception:
            source = ""
        if not self.isCandidateLayerName(f"{layer.name()}\n{source}"):
            return False
        return self.normalizedPath(self.layerSourcePath(layer)) == self.normalizedPath(self.generatedLayerBackupPath())

    def isCandidateLayerName(self, value):
        """レイヤ名/source文字列がYOLO候補レイヤ名らしいか判定する。"""
        text = str(value or "").lower()
        return (
            "360 detection candidates" in text
            or "360 poi clusters" in text
            or "all_classes" in text
            or GPKG_CANDIDATE_LAYER_NAME.lower() in text
            or "poi_candidates" in text
            or "poi_clusters" in text
        )

    def isNamedCandidateLayer(self, layer):
        """表示名/source上もpoi_candidates_360相当と判断できるか確認する。"""
        if not self.isCandidateLayer(layer):
            return False
        try:
            name = str(layer.name())
        except Exception:
            name = ""
        try:
            source = str(layer.source())
        except Exception:
            source = ""
        return self.isCandidateLayerName(f"{name}\n{source}")

    def layerHasVideoFrameCandidate(self, layer, video_name, frame_num=None, selected_only=False):
        """指定動画/任意フレームのYOLO候補点を持つレイヤか確認する。"""
        if not self.isCandidateLayer(layer):
            return False

        for feature in self.candidateFeatures(layer, selected_only=selected_only):
            feature_video = self.targetFeatureValue(feature, "video")
            if video_name and feature_video and str(feature_video) != str(video_name):
                continue
            if frame_num is None:
                return True
            frame_value = self.targetFeatureFloat(feature, "frame")
            if frame_value is not None and int(frame_value) == int(frame_num):
                return True
        return False

    def candidateReadLayers(self, frame_num=None, scope=None):
        """復元参照に使うYOLO候補レイヤを現在ジョブに絞って返す。"""
        current_video = os.path.basename(self.video_file or "")
        scope = str(scope or self.currentDetectionScope() or "active")

        def layer_matches(layer, selected_only=False):
            if not self.layerHasVideoFrameCandidate(
                layer,
                current_video,
                frame_num,
                selected_only=selected_only,
            ):
                return False
            for feature in self.candidateFeatures(layer, selected_only=selected_only):
                feature_video = self.targetFeatureValue(feature, "video")
                if current_video and feature_video and str(feature_video) != current_video:
                    continue
                if frame_num is not None:
                    frame_value = self.targetFeatureFloat(feature, "frame")
                    if frame_value is None or int(frame_value) != int(frame_num):
                        continue
                if self.candidateFeatureMatchesViewerProjection(feature):
                    return True
            return False

        if scope == "active":
            layer = self.activeCandidateLayer()
            return [layer] if layer is not None and layer_matches(layer) else []

        layers = self.projectCandidateLayers(visible_only=(scope == "visible"))

        if scope == "selected":
            return [
                layer for layer in layers
                if self.layerSelectedFeatureIds(layer) and layer_matches(layer, selected_only=True)
            ]

        layers = [
            layer for layer in layers
            if layer_matches(layer)
        ]

        return layers

    def restoredCandidateTargetPayload(self, feature):
        """YOLO候補点レコードをviewer_session.jsonのtarget形式へ戻す。"""
        target_yaw = self.targetFeatureFloat(feature, "target_yaw")
        target_pitch = self.targetFeatureFloat(feature, "target_pitch")
        if target_yaw is None or target_pitch is None:
            return None

        confidence = self.targetFeatureFloat(feature, "confidence")
        projection = self.targetFeatureValue(feature, "projection") or "direction_only"
        ground_distance_m = self.targetFeatureFloat(feature, "ground_distance_m")
        if ground_distance_m is None:
            ground_distance_m = self.targetFeatureFloat(feature, "distance_m")
        map_target_yaw = self.targetFeatureFloat(feature, "map_target_yaw")
        if map_target_yaw is None:
            map_target_yaw = self.targetFeatureFloat(feature, "cubemap_target_yaw")
        map_bearing = self.targetFeatureFloat(feature, "bearing_deg")

        candidate_id = (
            self.targetFeatureValue(feature, "candidate_id")
            or self.targetFeatureValue(feature, "target_id")
            or self.targetFeatureValue(feature, "detection_id")
        )
        semantic_class = self.targetFeatureValue(feature, "semantic_class")
        review_status = self.targetFeatureValue(feature, "review_status")
        quality = self.targetFeatureValue(feature, "quality")

        target_source = self.targetFeatureValue(feature, "target_source") or "yolo_candidate"
        x_ratio = None
        y_ratio = None
        bbox_x_ratio = None
        bbox_y_ratio = None
        flat_auto = False
        if self.video_file:
            try:
                flat_auto = self.inferViewerProjectionFromVideo(self.video_file)[0] == VIEWER_PROJECTION_FLAT
            except Exception:
                flat_auto = False
        flat_context = self.viewerProjectionValue() == VIEWER_PROJECTION_FLAT or flat_auto

        anchor_x = self.targetFeatureFloat(feature, "anchor_x_px")
        anchor_y = self.targetFeatureFloat(feature, "anchor_y_px")
        bbox_json = self.targetFeatureValue(feature, "evidence_bbox_json")
        image_width = None
        image_height = None
        if bbox_json not in (None, ""):
            try:
                bbox = json.loads(str(bbox_json))
            except Exception:
                bbox = None
            if isinstance(bbox, dict):
                x1 = _parse_float(bbox.get("x1"))
                y1 = _parse_float(bbox.get("y1"))
                x2 = _parse_float(bbox.get("x2"))
                y2 = _parse_float(bbox.get("y2"))
                if (anchor_x is None or anchor_y is None):
                    if x1 is not None and x2 is not None:
                        anchor_x = (float(x1) + float(x2)) / 2.0
                    if y1 is not None and y2 is not None:
                        anchor_y = (float(y1) + float(y2)) / 2.0
                image_width = _parse_float(bbox.get("image_width")) or _parse_float(bbox.get("width"))
                image_height = _parse_float(bbox.get("image_height")) or _parse_float(bbox.get("height"))
            elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4 and (anchor_x is None or anchor_y is None):
                x1 = _parse_float(bbox[0])
                y1 = _parse_float(bbox[1])
                x2 = _parse_float(bbox[2])
                y2 = _parse_float(bbox[3])
                if x1 is not None and x2 is not None:
                    anchor_x = (float(x1) + float(x2)) / 2.0
                if y1 is not None and y2 is not None:
                    anchor_y = (float(y1) + float(y2)) / 2.0
        if image_width is None:
            image_width = self.targetFeatureFloat(feature, "image_width") or self.targetFeatureFloat(feature, "width_px")
        if image_height is None:
            image_height = self.targetFeatureFloat(feature, "image_height") or self.targetFeatureFloat(feature, "height_px")
        if (image_width is None or image_height is None) and flat_context and self.video_file:
            dimensions = self.videoDimensions(self.video_file)
            if dimensions:
                image_width, image_height = dimensions
        if anchor_x is not None and anchor_y is not None and image_width and image_height:
            bbox_x_ratio = max(0.0, min(1.0, float(anchor_x) / float(image_width)))
            bbox_y_ratio = max(0.0, min(1.0, float(anchor_y) / float(image_height)))

        normalized_x = self.targetFeatureFloat(feature, "cubemap_u")
        normalized_y = self.targetFeatureFloat(feature, "cubemap_v")
        if flat_context and bbox_x_ratio is not None and bbox_y_ratio is not None:
            x_ratio = bbox_x_ratio
            y_ratio = bbox_y_ratio
        elif normalized_x is not None and normalized_y is not None:
            x_ratio = max(0.0, min(1.0, (float(normalized_x) + 1.0) / 2.0))
            y_ratio = max(0.0, min(1.0, (float(normalized_y) + 1.0) / 2.0))
        elif bbox_x_ratio is not None and bbox_y_ratio is not None:
            x_ratio = bbox_x_ratio
            y_ratio = bbox_y_ratio
        target = {
            "yaw_delta_deg": 0.0,
            "pitch_delta_deg": 0.0,
            "target_yaw_to_camera_heading": float(target_yaw) % 360.0,
            "target_pitch_deg": max(-90.0, min(90.0, float(target_pitch))),
            "view_yaw_to_camera_heading": float(target_yaw) % 360.0,
            "view_pitch": max(-90.0, min(90.0, float(target_pitch))),
            "view_zoom": 1.35,
            "projection": str(projection),
            "target_source": str(target_source),
            "viewer_marker": self.targetFeatureValue(feature, "viewer_marker") or "target_point",
        }
        if x_ratio is not None and y_ratio is not None:
            target["x_ratio"] = x_ratio
            target["y_ratio"] = y_ratio
        if map_target_yaw is not None:
            target["map_target_yaw_to_camera_heading"] = float(map_target_yaw) % 360.0
        if map_bearing is not None:
            target["map_bearing_deg"] = float(map_bearing) % 360.0
        if ground_distance_m is not None and ground_distance_m > 0:
            target["ground_distance_m"] = float(ground_distance_m)
        if quality:
            target["quality"] = str(quality)
        if candidate_id not in (None, ""):
            target["candidate_id"] = str(candidate_id)
        if semantic_class not in (None, ""):
            target["semantic_class"] = str(semantic_class)
        if confidence is not None:
            target["confidence"] = float(confidence)
        if review_status not in (None, ""):
            target["review_status"] = str(review_status)
        return target

    def candidateFeatureMatchesViewerProjection(self, feature):
        """現在のviewer投影と候補点の画像根拠が一致するかを返す。"""
        flat_auto = False
        if self.video_file:
            try:
                flat_auto = self.inferViewerProjectionFromVideo(self.video_file)[0] == VIEWER_PROJECTION_FLAT
            except Exception:
                flat_auto = False
        if self.viewerProjectionValue() != VIEWER_PROJECTION_FLAT and not flat_auto:
            return True

        target_source = str(self.targetFeatureValue(feature, "target_source") or "").strip().lower()
        if target_source == "yolo_pinhole":
            return True

        evidence_path = str(self.targetFeatureValue(feature, "evidence_image_path") or "").replace("\\", "/").lower()
        evidence_face = str(self.targetFeatureValue(feature, "evidence_face") or "").strip().lower()
        cubemap_faces = {"front", "back", "left", "right", "up", "down"}
        if "/cubemap/" in evidence_path or evidence_path.startswith("cubemap/") or evidence_face in cubemap_faces:
            return False
        return True

    def viewerDetectionTargetsForFrame(self, frame_num):
        """指定フレームのYOLO候補点をビューア確認用payloadとして返す。"""
        target_frame = int(frame_num)
        scope = self.currentDetectionScope()
        selected_only = scope == "selected"
        layers = self.candidateReadLayers(target_frame, scope=scope)
        if not layers:
            return []

        current_video = os.path.basename(self.video_file or "")
        candidate_targets = []
        seen_candidates = set()

        for layer in layers:
            for feature in self.candidateFeatures(layer, selected_only=selected_only):
                frame_value = self.targetFeatureFloat(feature, "frame")
                if frame_value is None or int(frame_value) != target_frame:
                    continue

                feature_video = self.targetFeatureValue(feature, "video")
                if current_video and feature_video and str(feature_video) != current_video:
                    continue

                if not self.candidateFeatureMatchesViewerProjection(feature):
                    continue

                target = self.restoredCandidateTargetPayload(feature)
                if not target:
                    continue
                candidate_key = (
                    target.get("candidate_id"),
                    round(float(target.get("target_yaw_to_camera_heading") or 0.0), 3),
                    round(float(target.get("target_pitch_deg") or 0.0), 3),
                )
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                candidate_targets.append(target)

        def sort_key(item):
            confidence = _parse_float(item.get("confidence"))
            return (
                0 if confidence is not None else 1,
                -(confidence or 0.0),
                str(item.get("semantic_class") or ""),
                str(item.get("candidate_id") or ""),
            )

        candidate_targets.sort(key=sort_key)
        for index, target in enumerate(candidate_targets[:100], start=1):
            target["id"] = index
            target["order"] = index
        return candidate_targets[:100]

    def viewerViewForDetectionFrame(self, frame_num):
        """Detection check移動時に、最も高信頼のYOLO候補をビューア中心へ向ける。"""
        targets = self.viewerDetectionTargetsForFrame(frame_num)
        if not targets:
            return None
        target = targets[0]
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

    def viewerSessionHasMeaningfulTarget(self, state):
        """session内に表示対象として意味を持つtargetがあるかを返す。"""
        if not isinstance(state, dict):
            return False

        def has_meaningful_payload(target):
            """中央デフォルトだけの一時targetを、保存済み点/候補点と区別する。"""
            if not isinstance(target, dict):
                return False
            for key in ("semantic_class", "candidate_id", "target_source", "viewer_marker", "review_status"):
                if target.get(key) not in (None, ""):
                    return True
            for key in ("id", "order"):
                try:
                    if int(target.get(key)) > 0:
                        return True
                except (TypeError, ValueError):
                    pass
            return False

        targets = state.get("targets")
        if isinstance(targets, list) and any(has_meaningful_payload(target) for target in targets):
            return True
        return has_meaningful_payload(state.get("target"))

    def viewerSessionHasUserClickTarget(self, state):
        """session内にユーザが明示保存したクリック点があるかを返す。"""
        if not isinstance(state, dict):
            return False

        def is_user_click(target):
            if not isinstance(target, dict):
                return False
            target_source = str(target.get("target_source") or "").strip().lower()
            if target_source in ("viewer_click", "manual_click", "user_click"):
                return True
            return (
                target.get("candidate_id") in (None, "")
                and target.get("semantic_class") in (None, "")
                and target.get("viewer_marker") in (None, "")
                and (target.get("id") is not None or target.get("order") is not None)
            )

        targets = state.get("targets")
        if isinstance(targets, list) and any(is_user_click(target) for target in targets):
            return True
        return is_user_click(state.get("target"))

    def restoreViewerTargetsForState(self, state):
        """現在sessionに点が無ければ、Navモードに応じたtargetを補完して返す。"""
        if not isinstance(state, dict):
            return state
        current_video = os.path.basename(self.video_file or "")
        if not current_video or state.get("video") != current_video:
            return state

        frame_index = self.sessionFrameIndex(state)
        if frame_index is None:
            return state

        try:
            nav_mode = str(self.nav_mode.currentData() or "")
        except Exception:
            nav_mode = ""

        if nav_mode == "detect":
            if self.viewerSessionHasUserClickTarget(state):
                return state
            targets = self.viewerDetectionTargetsForFrame(frame_index)
            if not targets:
                if isinstance(state.get("target"), dict) or isinstance(state.get("targets"), list):
                    restored_state = dict(state)
                    restored_state.pop("target", None)
                    restored_state.pop("targets", None)
                    written_state = self.writeViewerCommandState(restored_state)
                    return written_state if isinstance(written_state, dict) else restored_state
                return state
            restored_state = dict(state)
            restored_state["targets"] = targets
            restored_state["target"] = targets[0]
            written_state = self.writeViewerCommandState(restored_state)
            return written_state if isinstance(written_state, dict) else restored_state

        if self.viewerSessionHasMeaningfulTarget(state):
            return state

        targets = self.viewerTargetsForFrame(frame_index)
        if not targets:
            return state

        restored_state = dict(state)
        restored_state["targets"] = targets
        restored_state["target"] = targets[-1]
        written_state = self.writeViewerCommandState(restored_state)
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
        keys = set()

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
        def is_user_click_projection(projection):
            """候補表示由来ではなく、ユーザが明示保存したクリック点だけを保存対象にする。"""
            target_source = str(projection.get("target_source") or "").strip().lower()
            if target_source and target_source not in ("viewer_click", "manual_click", "user_click"):
                return False
            if projection.get("candidate_id") not in (None, ""):
                return False
            if projection.get("semantic_class") not in (None, ""):
                return False
            if projection.get("viewer_marker") not in (None, ""):
                return False
            return projection.get("id") is not None or projection.get("order") is not None

        storable_projections = [
            projection for projection in target_projections
            if is_user_click_projection(projection)
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
                "x_ratio": float(projection.get("x_ratio")) if projection.get("x_ratio") is not None else None,
                "y_ratio": float(projection.get("y_ratio")) if projection.get("y_ratio") is not None else None,
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
            features.append((key, feat))

        if not features:
            return
        ok, added_features = layer.dataProvider().addFeatures([feature for _key, feature in features])
        if not ok:
            notifier = getattr(self, "reportViewerTargetStoreStatus", None)
            if callable(notifier):
                notifier("failed: addFeatures returned false", warning=True)
            return
        layer.updateExtents()
        layer.triggerRepaint()
        self.markLayerSaveOnExit(layer)
        for key, _feature in features[:len(added_features)]:
            existing_keys.add(key)
        self.saved_viewer_target_keys = existing_keys
        notifier = getattr(self, "reportViewerTargetStoreStatus", None)
        if callable(notifier):
            notifier(f"saved {len(added_features)} point(s) to 360 Click Targets")

    def matchedFrameCsvPaths(self):
        """参照点マッチ済みフレームCSVの探索候補パスを返す。"""
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
        """参照点マッチ済みCSVからナビゲーション用frame_index一覧を読み込む。"""
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

    def detectionFrames(self):
        """YOLO候補点が存在するframe一覧を返す。"""
        frames = []
        scope = self.currentDetectionScope()
        selected_only = scope == "selected"
        for layer in self.candidateReadLayers(scope=scope):
            for feature in self.candidateFeatures(layer, selected_only=selected_only):
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
                if self.nav_mode.currentIndex() != index:
                    self.nav_mode.setCurrentIndex(index)
                else:
                    self.syncNavigationLayerForMode(mode)
                return True
        return False

    def frameStepNavigationTarget(self, current_frame, direction, step_count):
        """Frame stepモードとして次フレームを決める。"""
        target = max(0, int(current_frame) + int(direction) * int(step_count))
        return target, self.findFeatureByFrame(target)

    def frameStepEdgeTarget(self, direction):
        """Frame stepモードで撮影点レコードの先頭/最後尾を返す。"""
        layer = self.activeFrameLayer()
        if layer is None:
            self.notifyWarning("video_gpx_layer_missing")
            return None, None

        frames = self.layerFrames(layer)
        if not frames:
            self.notifyWarning("no_layer_frame", direction="first" if direction < 0 else "last")
            return None, None

        target = frames[0] if direction < 0 else frames[-1]
        return target, self.findFeatureByFrame(target)

    def navigationEdgeTargetFrame(self, direction):
        """UIのナビモードに応じて、先頭/最後尾レコードのフレームと地物を返す。"""
        config = self.collectNavigationConfig()
        if config is None:
            return None, None

        self.syncNavigationLayerForMode(config.mode)

        edge_name = "first" if direction < 0 else "last"
        mode = config.mode

        if mode == "frame":
            return self.frameStepEdgeTarget(direction)

        if mode == "kp":
            frames, path = self.matchedFrames()
            if not frames:
                self.setNavigationModeByData("frame")
                self.notifyWarning("kp_navigation_fallback_frame")
                return self.frameStepEdgeTarget(direction)
            target = frames[0] if direction < 0 else frames[-1]
            return target, self.findFeatureByFrame(target)

        if mode == "picked":
            frames = self.pickedFrames()
            if not frames:
                self.notifyWarning("no_picked_frame", direction=edge_name)
                return None, None
            target = frames[0] if direction < 0 else frames[-1]
            return target, self.findFeatureByFrame(target)

        if mode == "detect":
            frames = self.detectionFrames()
            if not frames:
                self.notifyWarning("no_detection_frame", direction=edge_name)
                return None, None
            target = frames[0] if direction < 0 else frames[-1]
            return target, self.findFeatureByFrame(target)

        layer = self.activeFrameLayer()
        if layer is None:
            self.notifyWarning("video_gpx_layer_missing")
            return None, None

        frames = self.layerFrames(layer)
        if not frames:
            self.notifyWarning("no_layer_frame", direction=edge_name)
            return None, None
        target = frames[0] if direction < 0 else frames[-1]
        return target, self.findFeatureByFrame(target)

    def navigationTargetFrame(self, direction, fast=False):
        """UIのナビモードに応じて、次に表示すべきフレームと地物を決める。"""
        config = self.collectNavigationConfig()
        if config is None:
            return None, None

        self.syncNavigationLayerForMode(config.mode)

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
            if fast:
                frames = self.pickedFrames()
                if not frames:
                    self.notifyWarning("no_picked_frame", direction="next" if direction > 0 else "previous")
                    return None, None
                target = self.steppedFrame(frames, current_frame, direction, 1)
                if target is None:
                    self.notifyWarning("no_picked_frame", direction="next" if direction > 0 else "previous")
                    return None, None
                return target, self.findFeatureByFrame(target)
            return self.frameStepNavigationTarget(current_frame, direction, step_count)

        if mode == "detect":
            if fast:
                frames = self.detectionFrames()
                if not frames:
                    self.notifyWarning("no_detection_frame", direction="next" if direction > 0 else "previous")
                    return None, None
                target = self.steppedFrame(frames, current_frame, direction, 1)
                if target is None:
                    self.notifyWarning("no_detection_frame", direction="next" if direction > 0 else "previous")
                    return None, None
                return target, self.findFeatureByFrame(target)
            return self.frameStepNavigationTarget(current_frame, direction, step_count)

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

    def navigateEdge(self, direction):
        """現在ナビゲーション対象レコードの先頭または最後尾へ移動する。"""
        target, feature = self.navigationEdgeTargetFrame(direction)
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
            if layer_id == self.candidate_layer_id:
                self.candidate_layer_id = None

        self.created_layer_ids = remaining_layer_ids
        self.save_on_exit_layer_ids = set()
        self.loaded_layer_feature_counts = {}
        self.saved_viewer_target_keys = set()
        self.cleanupLayerTreeGroups()
        return removed_count

    def markLayerSaveOnExit(self, layer):
        """終了時にtmp.gpkgへ退避すべき揮発レイヤとして記録する。"""
        if layer is None:
            return False
        try:
            layer_id = layer.id()
        except Exception:
            return False
        if not layer_id:
            return False
        self.save_on_exit_layer_ids.add(layer_id)
        return True

    def registerLoadedLayerForChangeTracking(self, layer):
        """GPKGから読み込んだ作業用メモリレイヤの変更を検知する。"""
        if layer is None:
            return False
        try:
            layer_id = layer.id()
        except Exception:
            return False
        if not layer_id:
            return False

        self.loaded_layer_feature_counts[layer_id] = self.layerFeatureCount(layer)

        for signal_name in (
            "featureAdded",
            "featureDeleted",
            "attributeValueChanged",
            "geometryChanged",
        ):
            try:
                signal = getattr(layer, signal_name)
                signal.connect(lambda *args, layer=layer: self.markLayerSaveOnExit(layer))
            except Exception:
                pass
        return True

    def shouldSaveLayerOnExit(self, layer_id, layer):
        """終了時にレイヤをGPKGへ保存すべきか判定する。"""
        if layer_id in self.save_on_exit_layer_ids:
            return True
        if layer_id not in self.loaded_layer_feature_counts:
            return False
        try:
            return self.layerFeatureCount(layer) != int(self.loaded_layer_feature_counts[layer_id])
        except Exception:
            return False

    def generatedLayerBackupPath(self):
        """Exit時に生成レイヤを退避保存するGeoPackageパスを返す。"""
        if self.loaded_gpkg_path:
            return self.loaded_gpkg_path
        return os.path.join(self.resolvedOutputDir(), "tmp.gpkg")

    def generatedLayers(self):
        """現在QGISに残っている、終了時バックアップ対象レイヤだけを取得する。"""
        project = QgsProject.instance()
        layers = []
        for layer_id in self.created_layer_ids:
            layer = project.mapLayer(layer_id)
            if layer is not None and self.shouldSaveLayerOnExit(layer_id, layer):
                layers.append(layer)
        return layers

    def generatedLayerBackupName(self, layer, base_layer_name, index):
        """tmp.gpkg内の保存レイヤ名を役割に応じて決める。"""
        fields = self.layerFields(layer)
        if fields is None:
            return _safe_gpkg_layer_name(f"{base_layer_name}_{index:02d}")
        if self.isCandidateLayer(layer):
            semantic_class = self.layerSingleSemanticClass(layer)
            if semantic_class:
                return _safe_gpkg_layer_name(f"poi_clusters_{semantic_class}")
            display_name = str(getattr(layer, "name", lambda: "")() or "")
            for prefix in ("360 Detection Candidates: ", "360 POI Clusters: ", "POI: "):
                if display_name.startswith(prefix):
                    return _safe_gpkg_layer_name(display_name[len(prefix):])
            if display_name.startswith(("poi_candidates", "poi_clusters")):
                return _safe_gpkg_layer_name(display_name)
            return GPKG_CANDIDATE_LAYER_NAME
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
        self.clearJobInputs()
        self.last_rows = []
        self.frame_position_by_frame = {}
        self.frame_layer_id = None
        self.target_layer_id = None
        self.candidate_layer_id = None
        self.save_on_exit_layer_ids = set()
        self.loaded_layer_feature_counts = {}
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

    def newJobSession(self):
        """プラグインをリロードせず、前回ジョブ状態を保存・除去して新規入力へ戻す。"""
        self.cleanupSession(close_panel=False, remove_layers=True, show_message=True)

    def existingProcessOutputPaths(self, config):
        """Processで上書きされ得る既存成果物パスを返す。"""
        output_dir = config.output_dir
        base_name = _base_output_name(config.video_file, config.gpx_file)
        candidates = [
            os.path.join(output_dir, "tmp.gpkg"),
            os.path.join(output_dir, base_name + FRAMES_CSV_SUFFIX),
            os.path.join(output_dir, base_name + NAVIGATION_JSON_SUFFIX),
            os.path.join(output_dir, base_name + MATCHED_FRAMES_CSV_SUFFIX),
        ]
        return [path for path in candidates if path and os.path.exists(path)]

    def confirmProcessOutputOverwrite(self, config):
        """既存成果物がある場合、Process開始前に上書き確認する。"""
        existing = self.existingProcessOutputPaths(config)
        if not existing:
            return True
        shown = "\n".join(os.path.basename(path) for path in existing[:8])
        if len(existing) > 8:
            shown += f"\n... and {len(existing) - 8} more"
        message = (
            "The selected output folder already contains files that may be overwritten:\n\n"
            f"{shown}\n\n"
            "Continue processing with this output folder?"
        )
        answer = QtWidgets.QMessageBox.question(
            self,
            "Confirm Output Overwrite",
            message,
            QT_MESSAGE_BOX_YES | QT_MESSAGE_BOX_NO,
            QT_MESSAGE_BOX_NO,
        )
        return answer == QT_MESSAGE_BOX_YES

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
        if not self.confirmProcessOutputOverwrite(config):
            return

        self.session_closing = False
        self.last_process_config = config
        print(f"Processing GPX: {config.gpx_file}")
        print(f"Processing Video: {config.video_file}")

        self.progress_bar.setValue(0)
        self.process_button.setEnabled(False)

        self.worker = Geo360View(
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
                QgsField("reference_id", QVariant.String),
                QgsField("reference_name", QVariant.String),
                QgsField("reference_label", QVariant.String),
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
                    match.get("reference_id", "") if match else "",
                    match.get("reference_name", "") if match else "",
                    match.get("reference_label", match["kp"]) if match else "",
                    round(match["distance_m"], 3) if match else None,
                    match["lat"] if match else None,
                    match["lon"] if match else None,
                    1 if match else 0,
                ])
                features.append(feat)

            pr.addFeatures(features)
            layer.updateExtents()
            self.createLayerSpatialIndex(layer)
            QgsProject.instance().addMapLayer(layer)
            self.created_layer_ids.append(layer.id())
            self.markLayerSaveOnExit(layer)
            self.frame_layer_id = layer.id()
            print("Layer added successfully.")
            self.notifyInfo("layer_added", count=len(features))
            self.exportFrameData(rows, matches=matches, match_count=match_count)
        else:
            print("No rows. Could not add layer.")
            self.notifyWarning("no_rows_layer")

    def buildKpMatches(self, rows):
        """現在UIの参照点CSV/許容距離を使って最近接マッチングを実行する。"""
        return build_kp_matches(rows, self.processKpFileValue(), self.processKpToleranceValue())

    def resolveKpMatches(self, rows):
        """参照点マッチングを安全に実行し、レイヤ属性とCSV出力で共有する。"""
        try:
            matches, match_count = self.buildKpMatches(rows)
            return matches, match_count, None
        except Exception as e:
            return [None] * len(rows), 0, str(e)

    def exportFrameData(self, rows, matches=None, match_count=None):
        """全フレーム同期CSV、参照点ナビゲーションJSON/CSVを出力する。"""
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
            "reference_id",
            "reference_name",
            "reference_label",
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
                        "reference_id": match.get("reference_id", "") if match else "",
                        "reference_name": match.get("reference_name", "") if match else "",
                        "reference_label": match.get("reference_label", match["kp"]) if match else "",
                        "kp_distance_m": _format_distance(match["distance_m"] if match else None),
                        "kp_latitude": f"{match['lat']:.9f}" if match else "",
                        "kp_longitude": f"{match['lon']:.9f}" if match else "",
                        "kp_match": "1" if match else "0",
                    })

                    if match:
                        # 参照点マッチ済み点だけをWEBビューアPrev/Next用ノードにする。
                        navigation_nodes.append({
                            "index": len(navigation_nodes),
                            "frame": frame_num,
                            "source_frame": source_frame,
                            "frame_shift": frame_shift,
                            "image_path": image_path,
                            "timestamp": _format_timestamp(time),
                            "kp": match["kp"],
                            "reference_id": match.get("reference_id", ""),
                            "reference_name": match.get("reference_name", ""),
                            "reference_label": match.get("reference_label", match["kp"]),
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
                    "reference_id",
                    "reference_name",
                    "reference_label",
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
                                "reference_id": node.get("reference_id", ""),
                                "reference_name": node.get("reference_name", ""),
                                "reference_label": node.get("reference_label", node["kp"]),
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
        if self.new_job_action is not None:
            self.iface.removePluginMenu(PLUGIN_TITLE, self.new_job_action)
        if self.exit_action is not None:
            self.iface.removePluginMenu(PLUGIN_TITLE, self.exit_action)

        # ツールバーを削除
        if self.toolbar and self.toolbar.parent() is not None:
            self.toolbar.parent().removeToolBar(self.toolbar)
        self.action = None
        self.viewer_action = None
        self.new_job_action = None
        self.exit_action = None
        self.toolbar = None

    def closeEvent(self, event):
        """パネル右上の閉じる操作ではセッション終了までは行わず、UIだけ閉じる。"""
        event.accept()

def classFactory(iface):
    """QGISがプラグインインスタンスを生成するためのエントリポイント。"""
    return GPXVideoPlugin(iface)
