"""QGIS側のオンザフライ静止画抽出とプレビュー表示。"""

import os
import re
import time
from datetime import datetime

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import Qt

from .common import _parse_float
from .constants import PLUGIN_TITLE
from .exif_utils import _insert_exif, _minimal_exif_payload
from .qt_compat import QT_KEEP_ASPECT_RATIO, QT_SMOOTH_TRANSFORMATION


class FrameExtractMixin:
    """選択フレームをOpenCVで抽出し、QGISパネルへ表示するMixin。"""

    def compactPreviewInfo(self, info):
        """長い抽出ログを2行程度のプレビュー表示へ変換する。"""
        if len(info) <= 160:
            return info
        return f"{info[:112]} ... {info[-44:]}"

    def framePreviewInfo(self, frame_num, status, image_path, timing_text):
        """フレーム抽出結果を、パス行と処理時間行に分けて表示する。"""
        return self.uiText(
            "ui.preview.frame_info",
            frame=frame_num,
            status=status,
            path=image_path,
            timing=timing_text,
        )

    def formatPreviewFileSize(self, byte_count):
        """画像ファイルサイズをプレビュー用の短い表記へ変換する。"""
        try:
            size = float(max(int(byte_count), 0))
        except (TypeError, ValueError):
            return "-"

        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0 or unit == "GB":
                if unit == "B":
                    return f"{int(size)} B"
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return "-"

    def viewerCachePathForFrame(self, frame_num):
        """360Viewerが生成する軽量JPEGキャッシュの想定パスを返す。"""
        if hasattr(self, "loadViewerDefaults"):
            self.loadViewerDefaults()

        stem = os.path.splitext(os.path.basename(self.video_file or ""))[0]
        stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", stem).strip("_") or "video"
        cache_name = (
            f"{stem}_"
            f"frame_{int(frame_num):06d}_"
            f"w{int(getattr(self, 'viewer_max_width', 3072))}_"
            f"q{int(getattr(self, 'viewer_jpeg_quality', 90))}_"
            f"p{1 if getattr(self, 'viewer_progressive_jpeg', True) else 0}.jpg"
        )
        return os.path.join(self.viewerCacheDir(), cache_name)

    def viewerCacheDisplayPath(self, cache_path):
        """viewer_cacheパスを、出力フォルダ基準の短い表示名へ変換する。"""
        try:
            relative_path = os.path.relpath(cache_path, self.resolvedOutputDir())
            if relative_path != os.pardir and not relative_path.startswith(os.pardir + os.sep):
                return relative_path.replace("\\", "/").replace(os.sep, "/")
        except (OSError, TypeError, ValueError) as e:
            _geo360_ignored_error = e
        return os.path.basename(cache_path)

    def viewerCacheTooltip(self, frame_num):
        """プレビュー画像tooltipへ表示するviewer_cache情報を作る。"""
        cache_path = self.viewerCachePathForFrame(frame_num)
        try:
            file_size = os.path.getsize(cache_path)
        except OSError:
            file_size = None

        display_path = self.viewerCacheDisplayPath(cache_path)
        if file_size is None:
            return f"viewer_cache: {display_path}\n{cache_path}"

        size_text = self.formatPreviewFileSize(file_size)
        return f"viewer_cache: {display_path} | {size_text}\n{cache_path}"

    def loadPreview(self, image_path, info, frame_num=None):
        """保存済みJPEGをプレビュー領域へ読み込み、抽出ログを更新する。"""
        tooltip = self.viewerCacheTooltip(frame_num) if frame_num is not None else image_path
        pixmap = QtGui.QPixmap(image_path)
        if pixmap.isNull():
            self.preview_label.setText(self.uiText("ui.preview.unavailable"))
            self.preview_label.setToolTip(tooltip)
        else:
            self.preview_label.setPixmap(
                pixmap.scaled(480, 180, QT_KEEP_ASPECT_RATIO, QT_SMOOTH_TRANSFORMATION)
            )
            self.preview_label.setToolTip(tooltip)
        self.preview_info.setText(info)
        self.preview_info.setToolTip(info)

    def featureGps(self, feature):
        """クリックされたQGIS地物からJPEG EXIF用の緯度経度を取り出す。"""
        lat = None
        lon = None

        # KPマッチ後の座標を優先し、なければ元の撮影点座標を使う。
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
            except (TypeError, ValueError, AttributeError) as e:
                debug = getattr(self, "notifyDebugText", None)
                if callable(debug):
                    debug(f"Frame EXIF GPS could not be read from feature geometry: {e}")
        return None

    def saveFrameImage(self, frame, frame_num, image_path, elapsed, gps=None):
        """OpenCVフレームをJPEG化し、最小EXIFを付けて保存する。"""
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
        """UIのFrame入力値を使って単体抽出を実行する。"""
        self.extractFrame(self.extract_frame.value())

    def extractFrame(self, frame_num, feature=None):
        """指定フレームを動画から抽出し、キャッシュ保存とプレビュー更新を行う。"""
        config = self.collectFrameExtractConfig(frame_num)
        if config is None:
            return

        frame_num = int(config.frame_number)
        video_file = config.video_file
        self.setCurrentFrame(frame_num)
        image_dir = self.imagesDir()
        image_path = self.frameImagePath(frame_num)
        image_parent_dir = os.path.dirname(image_path)

        try:
            os.makedirs(image_dir, exist_ok=True)
            os.makedirs(image_parent_dir, exist_ok=True)
        except OSError as e:
            self.notifyWarning("images_dir_failed", error=e)
            return

        start = time.perf_counter()
        if os.path.exists(image_path):
            # クリックのたびに再エンコードしない。フレーム番号は不変キーなので抽出済み画像を再利用できる。
            elapsed = time.perf_counter() - start
            info = self.framePreviewInfo(
                frame_num,
                self.uiText("ui.preview.status.existing"),
                image_path,
                self.uiText("ui.preview.timing.existing", elapsed=elapsed),
            )
            self.loadPreview(image_path, info, frame_num=frame_num)
            self.notifyDebug("frame_cached", frame=frame_num, elapsed=elapsed)
            return

        try:
            import cv2
        except ImportError as e:
            self.notifyWarning("opencv_unavailable", error=e)
            return

        cap = None
        try:
            open_start = time.perf_counter()
            cap = cv2.VideoCapture(video_file)
            if not cap.isOpened():
                self.notifyWarning("video_open_failed")
                return
            open_elapsed = time.perf_counter() - open_start

            seek_start = time.perf_counter()
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ok, frame = cap.read()
            decode_elapsed = time.perf_counter() - seek_start
            if not ok or frame is None:
                self.notifyWarning("frame_read_failed", frame=frame_num)
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
            self.notifyWarning("frame_extract_failed", error=e)
            return
        finally:
            if cap is not None:
                cap.release()

        total_elapsed = time.perf_counter() - start
        timing_text = (
            f"open {open_elapsed:.3f}s, seek/read {decode_elapsed:.3f}s, "
            f"save {save_elapsed:.3f}s, total {total_elapsed:.3f}s"
        )
        info = self.framePreviewInfo(
            frame_num,
            self.uiText("ui.preview.status.saved"),
            image_path,
            timing_text,
        )
        self.loadPreview(image_path, info, frame_num=frame_num)
        self.notifyDebug("frame_saved", frame=frame_num, total=total_elapsed, path=image_path)
