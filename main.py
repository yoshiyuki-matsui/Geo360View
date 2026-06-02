# GPXVideoProcessor/main.py
import csv
from datetime import datetime, timezone
import importlib
import json
import os
import re
import struct
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qgis.PyQt import QtGui, QtWidgets
from qgis.PyQt.QtWidgets import (
    QWidget, QPushButton, QFileDialog, QVBoxLayout, QLabel, QProgressBar,
    QDoubleSpinBox, QSpinBox
)
from qgis.PyQt.QtCore import (
    QDate, QDateTime, QProcess, QProcessEnvironment, QThread, QTime, QTimer,
    QVariant, Qt, QUrl, pyqtSignal
)
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsField, QgsSpatialIndex, QgsDistanceArea,
    QgsCoordinateReferenceSystem, QgsWkbTypes, QgsVectorFileWriter
)
from qgis.gui import QgsMapToolIdentifyFeature, QgsRubberBand

QAction = getattr(QtWidgets, "QAction", None) or QtGui.QAction

PLUGIN_TITLE = "GPXVideoProcessor"
LATITUDE_FIELDS = ("lat", "latitude", "gps_lat", "y", "緯度")
LONGITUDE_FIELDS = ("lon", "lng", "longitude", "gps_lon", "gps_lng", "x", "経度")
KP_FIELDS = ("kp", "kilopost", "kilo_post", "name", "id", "point", "測点", "キロポスト")
FRAMES_CSV_SUFFIX = "_frames.csv"
MATCHED_FRAMES_CSV_SUFFIX = "_matched_frames.csv"
NAVIGATION_JSON_SUFFIX = "_navigation.json"

# 🔁 geo_utils.py からインポート
from .TenkakuNinja.geo_util import (
    read_gpx,
    haversine,
    time_to_frame,
    is_drop_frame_fps,
    interpolate_gpx_to_frames
)

def _utc_time_spec():
    if hasattr(Qt, "TimeSpec"):
        return Qt.TimeSpec.UTC
    return Qt.UTC


def _to_qdatetime(value):
    return QDateTime(
        QDate(value.year, value.month, value.day),
        QTime(value.hour, value.minute, value.second, value.microsecond // 1000),
        _utc_time_spec()
    )


def _format_timestamp(value):
    return value.isoformat(timespec="milliseconds") + "Z"


def _format_distance(value):
    if value is None:
        return ""
    return f"{value:.3f}"


def _base_output_name(video_path, gpx_path):
    source_path = video_path or gpx_path or "video_gpx"
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", base_name).strip("_") or "video_gpx"


def _frame_image_name(frame_num):
    return f"frames_{frame_num:06d}.jpg"


def _exif_ascii(value):
    return str(value or "").encode("ascii", "replace") + b"\x00"


def _decimal_to_dms_rationals(value):
    value = abs(float(value))
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return [
        (degrees, 1),
        (minutes, 1),
        (round(seconds * 1000000), 1000000),
    ]


def _minimal_exif_payload(tags, gps=None):
    entries = []
    data = bytearray()

    def add_ascii(tag, value):
        value_bytes = _exif_ascii(value)
        entries.append((tag, 2, len(value_bytes), value_bytes))

    def add_long(tag, value):
        entries.append((tag, 4, 1, struct.pack("<I", value)))

    add_ascii(0x010E, tags.get("description", ""))  # ImageDescription
    add_ascii(0x0131, tags.get("software", f"{PLUGIN_TITLE} QGIS plugin"))  # Software
    add_ascii(0x0132, tags.get("datetime", ""))  # DateTime
    if gps:
        add_long(0x8825, 0)  # GPSInfoIFDPointer; offset is filled after IFD0 sizing.
    entries.sort(key=lambda item: item[0])

    ifd_offset = 8
    data_offset = ifd_offset + 2 + len(entries) * 12 + 4
    gps_entries = _gps_ifd_entries(gps) if gps else []
    if gps_entries:
        data_offset += 2 + len(gps_entries) * 12 + 4
    ifd = bytearray()
    ifd.extend(struct.pack("<H", len(entries)))

    for tag, field_type, count, value_bytes in entries:
        if tag == 0x8825:
            gps_ifd_offset = ifd_offset + 2 + len(entries) * 12 + 4
            packed_value = struct.pack("<I", gps_ifd_offset)
            ifd.extend(struct.pack("<HHI", tag, field_type, count))
            ifd.extend(packed_value)
            continue

        if len(value_bytes) <= 4:
            packed_value = value_bytes.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value_bytes)
        ifd.extend(struct.pack("<HHI", tag, field_type, count))
        ifd.extend(packed_value)

    ifd.extend(struct.pack("<I", 0))
    gps_ifd = _pack_gps_ifd(gps_entries, data_offset, data) if gps_entries else b""
    tiff = b"II*\x00" + struct.pack("<I", ifd_offset) + bytes(ifd) + gps_ifd + bytes(data)
    return b"Exif\x00\x00" + tiff


def _gps_ifd_entries(gps):
    lat = float(gps["lat"])
    lon = float(gps["lon"])
    return [
        (0x0001, 2, 2, _exif_ascii("N" if lat >= 0 else "S")),
        (0x0002, 5, 3, _decimal_to_dms_rationals(lat)),
        (0x0003, 2, 2, _exif_ascii("E" if lon >= 0 else "W")),
        (0x0004, 5, 3, _decimal_to_dms_rationals(lon)),
        (0x0012, 2, 7, _exif_ascii("WGS-84")),
    ]


def _pack_gps_ifd(entries, data_offset, data):
    gps_ifd = bytearray()
    gps_ifd.extend(struct.pack("<H", len(entries)))

    for tag, field_type, count, value in entries:
        if field_type == 5:
            packed_value = struct.pack("<I", data_offset + len(data))
            for numerator, denominator in value:
                data.extend(struct.pack("<II", numerator, denominator))
        elif len(value) <= 4:
            packed_value = value.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value)

        gps_ifd.extend(struct.pack("<HHI", tag, field_type, count))
        gps_ifd.extend(packed_value)

    gps_ifd.extend(struct.pack("<I", 0))
    return bytes(gps_ifd)


def _insert_exif(jpeg_bytes, exif_payload):
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        return jpeg_bytes
    segment_length = len(exif_payload) + 2
    if segment_length > 65535:
        return jpeg_bytes
    return (
        jpeg_bytes[:2]
        + b"\xff\xe1"
        + struct.pack(">H", segment_length)
        + exif_payload
        + jpeg_bytes[2:]
    )


def _normalize_field_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"[\s:./()（）\[\]-]+", "_", value).strip("_")


def _find_field(fieldnames, candidates):
    normalized = [(field, _normalize_field_name(field)) for field in fieldnames or []]
    candidate_names = {_normalize_field_name(candidate) for candidate in candidates}

    for field, normalized_field in normalized:
        if normalized_field in candidate_names:
            return field

    for field, normalized_field in normalized:
        if any(candidate and candidate in normalized_field for candidate in candidate_names):
            return field

    return None


def _safe_gpkg_layer_name(value):
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_").lower()
    if not value:
        value = "video_gpx_points"
    if value[0].isdigit():
        value = f"layer_{value}"
    return value[:63]


def _looks_like_python_launcher(path):
    name = os.path.basename(str(path or "")).lower()
    return name.startswith("python")


def _parse_float(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    value = value.replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _open_csv_dict_reader(path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            handle = open(path, "r", encoding=encoding, newline="")
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            return handle, csv.DictReader(handle, dialect=dialect)
        except UnicodeDecodeError as e:
            last_error = e
        except OSError:
            raise
    raise ValueError(f"Could not read CSV encoding: {last_error}")


def _read_kp_csv(path):
    handle, reader = _open_csv_dict_reader(path)
    with handle:
        fieldnames = reader.fieldnames or []
        lat_field = _find_field(fieldnames, LATITUDE_FIELDS)
        lon_field = _find_field(fieldnames, LONGITUDE_FIELDS)
        kp_field = _find_field(fieldnames, KP_FIELDS)

        if not lat_field or not lon_field:
            raise ValueError(
                "KP CSV must contain latitude/longitude columns "
                f"(fields: {', '.join(fieldnames)})"
            )

        rows = []
        for index, row in enumerate(reader, start=1):
            lat = _parse_float(row.get(lat_field))
            lon = _parse_float(row.get(lon_field))
            if lat is None or lon is None:
                continue

            kp_value = row.get(kp_field) if kp_field else None
            kp_value = str(kp_value).strip() if kp_value not in (None, "") else str(index)
            rows.append({
                "kp": kp_value,
                "lat": lat,
                "lon": lon,
                "point": QgsPointXY(lon, lat),
            })

    if not rows:
        raise ValueError("KP CSV did not contain valid latitude/longitude rows.")

    return rows


class GPXVideoProcessor(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, gpx_path, video_path, frame_shift=0):
        super().__init__()
        self.gpx_path = gpx_path
        self.video_path = video_path
        self.frame_shift = frame_shift

    def run(self):
        print("GPXVideoProcessor: run() called")  # ← ログを追加
        try:
            try:
                import cv2
            except ImportError as e:
                self.error.emit(f"OpenCV (cv2) is not available in QGIS Python: {e}")
                return

            # GPXファイルを読み込み
            gpx_points, gpx_info = read_gpx(self.gpx_path, diagnostics=True)
            if len(gpx_points) < 2:
                message = (
                    f"GPX track needs at least two timestamped points. "
                    f"Found {gpx_info['point_count']} point element(s), "
                    f"parsed {len(gpx_points)} timestamped point(s). "
                    f"Missing time: {gpx_info['missing_time_count']}, "
                    f"unparseable time: {gpx_info['bad_time_count']}."
                )
                if gpx_info["time_samples"]:
                    message += f" Time sample(s): {', '.join(gpx_info['time_samples'])}"
                self.error.emit(message)
                return

            # ビデオファイルを読み込み
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.error.emit("Failed to open video file")
                return

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps <= 0:
                self.error.emit("Could not read video FPS.")
                return
            if total_frames <= 0:
                self.error.emit("Could not read video frame count.")
                return

            # GPXトラックデータを補間し、フレーム単位に細分化（shred）
            interpolated_gpx = interpolate_gpx_to_frames(gpx_points, fps)
            if not interpolated_gpx:
                self.error.emit("No interpolated GPX points were generated.")
                return

            source_by_frame = {}
            start_time = interpolated_gpx[0][0]
            for time_value, lat, lon in interpolated_gpx:
                source_frame = time_to_frame((time_value - start_time).total_seconds(), fps)
                source_by_frame[source_frame] = (time_value, float(lat), float(lon))

            rows = []
            total = total_frames
            for frame_num in range(total_frames):
                if self.isInterruptionRequested():
                    self.error.emit("Processing cancelled.")
                    return

                source_frame = frame_num - self.frame_shift
                source_row = source_by_frame.get(source_frame)
                if source_row is not None:
                    time_value, lat, lon = source_row
                    rows.append((frame_num, source_frame, time_value, lat, lon))

                if frame_num % 1000 == 0 or frame_num == total_frames - 1:
                    self.progress.emit(int(((frame_num + 1) / total) * 100))

            self.finished.emit(rows)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            if 'cap' in locals():
                cap.release()


class FrameIdentifyTool(QgsMapToolIdentifyFeature):
    def __init__(self, canvas, layer, plugin):
        super().__init__(canvas)
        self.canvas = canvas
        self.layer = layer
        self.plugin = plugin
        self.setLayer(layer)
        self.rubber_band = None

    def canvasReleaseEvent(self, event):
        try:
            results = self.identify(
                event.x(),
                event.y(),
                [self.layer],
                QgsMapToolIdentifyFeature.TopDownStopAtFirst
            )
            if not results:
                self.plugin.iface.messageBar().pushWarning(PLUGIN_TITLE, "No frame point found.")
                return

            feature = results[0].mFeature
            frame = feature["frame"]
            if frame is None:
                self.plugin.iface.messageBar().pushWarning(PLUGIN_TITLE, "Clicked feature has no frame value.")
                return

            self.highlightFeature(feature)
            frame_num = int(frame)
            self.plugin.showFrameInViewer(frame_num)
            QTimer.singleShot(150, lambda: self.plugin.extractFrame(frame_num, feature=feature))
        except Exception as e:
            self.plugin.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Frame click failed: {e}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.plugin.deactivateClickMode()

    def highlightFeature(self, feature):
        self.clearHighlight()
        geom_type = QgsWkbTypes.geometryType(self.layer.wkbType())
        self.rubber_band = QgsRubberBand(self.canvas, geom_type)
        self.rubber_band.setColor(QtGui.QColor(255, 80, 0, 180))
        self.rubber_band.setWidth(3)
        self.rubber_band.setToGeometry(feature.geometry(), self.layer)
        self.rubber_band.show()

    def clearHighlight(self):
        if self.rubber_band:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None

    def deactivate(self):
        self.clearHighlight()
        super().deactivate()


class GPXVideoPlugin(QWidget):
    def __init__(self, iface, parent=None):
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
        self.session_closing = False
        self.toolbar = None
        self._gui_initialized = False

    def initGui(self):
        if self._gui_initialized:
            return

        self.setWindowTitle("GPX Video Processor")

        layout = QVBoxLayout()

        self.gpx_label = QLabel("Select GPX File:")
        self.gpx_path = QLabel("No file selected")
        self.gpx_button = QPushButton("Browse GPX")
        self.gpx_button.clicked.connect(self.selectGPX)

        self.video_label = QLabel("Select Video File:")
        self.video_path = QLabel("No file selected")
        self.video_button = QPushButton("Browse Video")
        self.video_button.clicked.connect(self.selectVideo)

        self.kp_label = QLabel("Select KP CSV (optional):")
        self.kp_path = QLabel("No file selected")
        self.kp_button = QPushButton("Browse KP CSV")
        self.kp_button.clicked.connect(self.selectKP)

        self.kp_tolerance_label = QLabel("KP match tolerance:")
        self.kp_tolerance = QDoubleSpinBox()
        self.kp_tolerance.setRange(0.0, 10000.0)
        self.kp_tolerance.setDecimals(1)
        self.kp_tolerance.setSingleStep(0.5)
        self.kp_tolerance.setValue(5.0)
        self.kp_tolerance.setSuffix(" m")

        self.frame_shift_label = QLabel("Frame shift:")
        self.frame_shift = QSpinBox()
        self.frame_shift.setRange(-1000000, 1000000)
        self.frame_shift.setSingleStep(1)
        self.frame_shift.setValue(0)
        self.frame_shift.setSuffix(" frame(s)")
        self.frame_shift.setToolTip(
            "Keeps video frame numbers fixed. Position source frame = video frame - shift."
        )

        self.output_label = QLabel("Output directory:")
        self.output_path = QLabel("Default after video selection")
        self.output_button = QPushButton("Browse Output")
        self.output_button.clicked.connect(self.selectOutputDir)

        self.extract_frame_label = QLabel("Extract test frame:")
        self.extract_frame = QSpinBox()
        self.extract_frame.setRange(0, 1000000000)
        self.extract_frame.setSingleStep(1)
        self.extract_frame.setValue(0)
        self.extract_button = QPushButton("Extract Frame")
        self.extract_button.clicked.connect(self.extractTestFrame)

        self.click_mode_button = QPushButton("Click Current Layer")
        self.click_mode_button.clicked.connect(self.activateClickMode)
        self.stop_click_mode_button = QPushButton("Stop Click Mode")
        self.stop_click_mode_button.clicked.connect(self.deactivateClickMode)

        self.preview_info = QLabel("No frame extracted")
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setText("Preview")

        self.process_button = QPushButton("Process")
        self.process_button.clicked.connect(self.processData)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        layout.addWidget(self.gpx_label)
        layout.addWidget(self.gpx_path)
        layout.addWidget(self.gpx_button)
        layout.addWidget(self.video_label)
        layout.addWidget(self.video_path)
        layout.addWidget(self.video_button)
        layout.addWidget(self.kp_label)
        layout.addWidget(self.kp_path)
        layout.addWidget(self.kp_button)
        layout.addWidget(self.kp_tolerance_label)
        layout.addWidget(self.kp_tolerance)
        layout.addWidget(self.frame_shift_label)
        layout.addWidget(self.frame_shift)
        layout.addWidget(self.output_label)
        layout.addWidget(self.output_path)
        layout.addWidget(self.output_button)
        layout.addWidget(self.extract_frame_label)
        layout.addWidget(self.extract_frame)
        layout.addWidget(self.extract_button)
        layout.addWidget(self.click_mode_button)
        layout.addWidget(self.stop_click_mode_button)
        layout.addWidget(self.preview_info)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.process_button)
        layout.addWidget(self.progress_bar)

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
        self._gui_initialized = True

    def showWindow(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def run(self):
        self.showWindow()
        self.reportViewerStatus()

    def selectGPX(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select GPX File", "", "GPX Files (*.gpx)")
        if file_path:
            self.gpx_file = file_path  # ここを確認
            self.gpx_path.setText(file_path)  # ユーザーに表示用のラベルを更新

    def selectVideo(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", "MP4 Files (*.mp4)")
        if file_path:
            self.video_file = file_path  # ここを確認
            self.video_path.setText(file_path)  # ユーザーに表示用のラベルを更新
            self.viewer_browser_opened = False
            if not self.output_dir_user_selected:
                self.output_path.setText(self.defaultOutputDir())
            self.writeViewerRuntimeConfig(show_error=False)

    def selectKP(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select KP CSV", "", "CSV Files (*.csv)")
        if file_path:
            self.kp_file = file_path
            self.kp_path.setText(file_path)

    def selectOutputDir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.defaultOutputDir())
        if directory:
            self.output_dir = directory
            self.output_dir_user_selected = True
            self.output_path.setText(directory)
            self.writeViewerRuntimeConfig(show_error=False)

    def defaultOutputDir(self):
        base_path = self.video_file or self.gpx_file or __file__
        return os.path.join(os.path.dirname(base_path), "360view_output")

    def resolvedOutputDir(self):
        return self.output_dir or self.defaultOutputDir()

    def imagesDir(self):
        return os.path.join(self.resolvedOutputDir(), "images")

    def frameImagePath(self, frame_num):
        return os.path.join(self.imagesDir(), _frame_image_name(frame_num))

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

    def stopWorker(self, wait_ms=1000, show_message=True):
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
        project = QgsProject.instance()
        removed_count = 0
        remaining_layer_ids = []

        for layer_id in self.created_layer_ids:
            if project.mapLayer(layer_id) is None:
                continue
            project.removeMapLayer(layer_id)
            removed_count += 1

        self.created_layer_ids = remaining_layer_ids
        return removed_count

    def generatedLayerBackupPath(self):
        return os.path.join(self.resolvedOutputDir(), "tmp.gpkg")

    def generatedLayers(self):
        project = QgsProject.instance()
        layers = []
        for layer_id in self.created_layer_ids:
            layer = project.mapLayer(layer_id)
            if layer is not None:
                layers.append(layer)
        return layers

    def gpkgOverwriteAction(self, overwrite_file):
        action_name = "CreateOrOverwriteFile" if overwrite_file else "CreateOrOverwriteLayer"
        action_enum = getattr(QgsVectorFileWriter, "ActionOnExistingFile", None)
        if action_enum is not None:
            return getattr(action_enum, action_name)
        return getattr(QgsVectorFileWriter, action_name)

    def writeLayerToGpkg(self, layer, gpkg_path, layer_name, overwrite_file):
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
        self.last_rows = []
        self.progress_bar.setValue(0)
        self.process_button.setEnabled(True)
        self.preview_info.setText("No frame extracted")
        self.preview_label.clear()
        self.preview_label.setText("Preview")

    def cleanupSession(self, close_panel=True, remove_layers=True, show_message=True):
        self.session_closing = True
        self.deactivateClickMode(show_message=False)
        worker_stopped = self.stopWorker(show_message=show_message)
        self.stopViewerProcess()

        saved_path = None
        saved_count = 0
        save_error = None
        if remove_layers:
            saved_path, saved_count, save_error = self.saveGeneratedLayers()

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
        self.cleanupSession(close_panel=True, remove_layers=True, show_message=True)

    def loadPreview(self, image_path, info):
        pixmap = QtGui.QPixmap(image_path)
        if pixmap.isNull():
            self.preview_label.setText("Preview unavailable")
        else:
            self.preview_label.setPixmap(
                pixmap.scaled(640, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.preview_info.setText(info)

    def featureGps(self, feature):
        lat = None
        lon = None

        for lat_name, lon_name in (("aligned_latitude", "aligned_longitude"), ("latitude", "longitude")):
            if feature.fields().indexFromName(lat_name) >= 0 and feature.fields().indexFromName(lon_name) >= 0:
                lat = _parse_float(feature[lat_name])
                lon = _parse_float(feature[lon_name])
                if lat is not None and lon is not None:
                    return {"lat": lat, "lon": lon}

        geom = feature.geometry()
        if geom and not geom.isEmpty():
            try:
                point = geom.asPoint()
                return {"lat": point.y(), "lon": point.x()}
            except Exception:
                pass
        return None

    def saveFrameImage(self, frame, frame_num, image_path, elapsed, gps=None):
        try:
            import cv2
        except ImportError as e:
            raise RuntimeError(f"OpenCV (cv2) is not available in QGIS Python: {e}")

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 92]
        )
        if not ok:
            raise RuntimeError("Failed to encode frame as JPEG.")

        now = datetime.now()
        description = (
            f"{PLUGIN_TITLE} frame={frame_num}; "
            f"frame_index_base=0; "
            f"video={self.video_file}; "
            f"extract_total_sec={elapsed:.3f}"
        )
        if gps:
            description += f"; lat={gps['lat']:.9f}; lon={gps['lon']:.9f}"

        exif_payload = _minimal_exif_payload(
            {
                "description": description,
                "software": f"{PLUGIN_TITLE} QGIS plugin",
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            },
            gps=gps
        )
        jpeg_bytes = _insert_exif(encoded.tobytes(), exif_payload)

        with open(image_path, "wb") as handle:
            handle.write(jpeg_bytes)

    def extractTestFrame(self):
        self.extractFrame(self.extract_frame.value())

    def extractFrame(self, frame_num, feature=None):
        if not self.video_file:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Select a video file first.")
            return

        self.extract_frame.setValue(frame_num)
        image_dir = self.imagesDir()
        image_path = self.frameImagePath(frame_num)

        try:
            os.makedirs(image_dir, exist_ok=True)
        except OSError as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to create images directory: {e}")
            return

        start = time.perf_counter()
        if os.path.exists(image_path):
            elapsed = time.perf_counter() - start
            info = f"Frame {frame_num} cached: {image_path} ({elapsed:.3f}s)"
            self.loadPreview(image_path, info)
            self.iface.messageBar().pushMessage(PLUGIN_TITLE, info)
            return

        try:
            import cv2
        except ImportError as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"OpenCV (cv2) is not available: {e}")
            return

        cap = None
        try:
            open_start = time.perf_counter()
            cap = cv2.VideoCapture(self.video_file)
            if not cap.isOpened():
                self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Failed to open video file.")
                return
            open_elapsed = time.perf_counter() - open_start

            seek_start = time.perf_counter()
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ok, frame = cap.read()
            decode_elapsed = time.perf_counter() - seek_start
            if not ok or frame is None:
                self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to read frame {frame_num}.")
                return

            save_start = time.perf_counter()
            self.saveFrameImage(
                frame,
                frame_num,
                image_path,
                time.perf_counter() - start,
                gps=self.featureGps(feature) if feature else None
            )
            save_elapsed = time.perf_counter() - save_start
        except Exception as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to extract frame: {e}")
            return
        finally:
            if cap is not None:
                cap.release()

        total_elapsed = time.perf_counter() - start
        info = (
            f"Frame {frame_num} saved: {image_path} "
            f"(open {open_elapsed:.3f}s, seek/read {decode_elapsed:.3f}s, "
            f"save {save_elapsed:.3f}s, total {total_elapsed:.3f}s)"
        )
        self.loadPreview(image_path, info)
        self.iface.messageBar().pushMessage(PLUGIN_TITLE, info)

    def activateClickMode(self):
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "Select a Video GPX Points layer first.")
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
        self.process_button.setEnabled(True)
        self.progress_bar.setValue(100)
        if self.session_closing:
            return

        self.last_rows = rows

        if rows:
            layer = QgsVectorLayer("Point?crs=EPSG:4326", "Video GPX Points", "memory")
            pr = layer.dataProvider()

            pr.addAttributes([
                QgsField("frame", QVariant.Int),
                QgsField("source_frame", QVariant.Int),
                QgsField("frame_shift", QVariant.Int),
                QgsField("timestamp", QVariant.DateTime),
                QgsField("latitude", QVariant.Double),
                QgsField("longitude", QVariant.Double)
            ])
            layer.updateFields()

            features = []
            for frame_num, source_frame, time, lat, lon in rows:
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
                feat.setAttributes([
                    frame_num,
                    source_frame,
                    self.frame_shift.value(),
                    _to_qdatetime(time),
                    lat,
                    lon
                ])
                features.append(feat)

            pr.addFeatures(features)
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)
            self.created_layer_ids.append(layer.id())
            print("Layer added successfully.")
            self.iface.messageBar().pushMessage(PLUGIN_TITLE, "Layer added successfully.")
            self.exportFrameData(rows)
        else:
            print("No rows. Could not add layer.")
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, "No rows. Could not add layer.")

    def buildKpMatches(self, rows):
        matches = [None] * len(rows)
        if not self.kp_file:
            return matches, 0

        kp_rows = _read_kp_csv(self.kp_file)
        index = QgsSpatialIndex()
        kp_by_id = {}
        for kp_id, kp in enumerate(kp_rows):
            feat = QgsFeature()
            feat.setId(kp_id)
            feat.setGeometry(QgsGeometry.fromPointXY(kp["point"]))
            index.addFeature(feat)
            kp_by_id[kp_id] = kp

        distance = QgsDistanceArea()
        distance.setSourceCrs(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext()
        )
        distance.setEllipsoid("WGS84")

        tolerance_m = self.kp_tolerance.value()
        match_count = 0
        for row_index, (frame_num, source_frame, time, lat, lon) in enumerate(rows):
            original_point = QgsPointXY(lon, lat)
            nearest_ids = index.nearestNeighbor(original_point, 1)
            if not nearest_ids:
                continue

            kp = kp_by_id.get(nearest_ids[0])
            if kp is None:
                continue

            distance_m = distance.measureLine(original_point, kp["point"])
            if distance_m > tolerance_m:
                continue

            matches[row_index] = {
                "kp": kp["kp"],
                "distance_m": distance_m,
                "lat": kp["lat"],
                "lon": kp["lon"],
            }
            match_count += 1

        return matches, match_count

    def exportFrameData(self, rows):
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
            video_dir_matched_csv = os.path.join(
                os.path.dirname(self.video_file),
                base_name + MATCHED_FRAMES_CSV_SUFFIX
            )
            if video_dir_matched_csv not in matched_csv_paths:
                matched_csv_paths.append(video_dir_matched_csv)

        try:
            matches, match_count = self.buildKpMatches(rows)
        except Exception as e:
            self.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Failed to match KP CSV: {e}")
            matches = [None] * len(rows)
            match_count = 0

        fieldnames = [
            "frame",
            "source_frame",
            "frame_shift",
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

                    writer.writerow({
                        "frame": frame_num,
                        "source_frame": source_frame,
                        "frame_shift": frame_shift,
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
                        navigation_nodes.append({
                            "index": len(navigation_nodes),
                            "frame": frame_num,
                            "source_frame": source_frame,
                            "frame_shift": frame_shift,
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
        self.process_button.setEnabled(True)
        self.progress_bar.setValue(0)
        if self.session_closing and error == "Processing cancelled.":
            print(f"Error: {error}")
            return

        print(f"Error: {error}")
        self.iface.messageBar().pushWarning(PLUGIN_TITLE, error)

    def unload(self):
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
        # UIが閉じられたときに呼ばれる
        event.accept()

def classFactory(iface):
    return GPXVideoPlugin(iface)
