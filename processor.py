from qgis.PyQt.QtCore import QThread, pyqtSignal

from .TenkakuNinja.geo_util import (
    interpolate_gpx_to_frames,
    read_gpx,
    time_to_frame,
)


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
        print("GPXVideoProcessor: run() called")
        try:
            try:
                import cv2
            except ImportError as e:
                self.error.emit(f"OpenCV (cv2) is not available in QGIS Python: {e}")
                return

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
