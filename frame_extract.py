"""QGIS側のオンザフライ静止画抽出とプレビュー表示。"""

import os
import time
from datetime import datetime

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import Qt

from .common import _parse_float
from .constants import PLUGIN_TITLE
from .exif_utils import _insert_exif, _minimal_exif_payload


class FrameExtractMixin:
    """選択フレームをOpenCVで抽出し、QGISパネルへ表示するMixin。"""

    def compactPreviewInfo(self, info):
        """長い抽出ログをパネル幅に収まる短縮表示へ変換する。"""
        if len(info) <= 160:
            return info
        return f"{info[:112]} ... {info[-44:]}"

    def loadPreview(self, image_path, info):
        """保存済みJPEGをプレビュー領域へ読み込み、抽出ログを更新する。"""
        pixmap = QtGui.QPixmap(image_path)
        if pixmap.isNull():
            self.preview_label.setText("Preview unavailable")
        else:
            self.preview_label.setPixmap(
                pixmap.scaled(480, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.preview_info.setText(self.compactPreviewInfo(info))
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
            except Exception:
                pass
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
            # クリックのたびに再エンコードしない。フレーム番号は不変キーなのでキャッシュ可能。
            elapsed = time.perf_counter() - start
            info = f"Frame {frame_num} cached: {image_path} ({elapsed:.3f}s)"
            self.loadPreview(image_path, info)
            self.notifyInfo("frame_cached", frame=frame_num, elapsed=elapsed)
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
        info = (
            f"Frame {frame_num} saved: {image_path} "
            f"(open {open_elapsed:.3f}s, seek/read {decode_elapsed:.3f}s, "
            f"save {save_elapsed:.3f}s, total {total_elapsed:.3f}s)"
        )
        self.loadPreview(image_path, info)
        self.notifyInfo("frame_saved", frame=frame_num, total=total_elapsed, path=image_path)
