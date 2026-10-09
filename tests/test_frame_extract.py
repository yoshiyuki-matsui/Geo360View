"""Regressions for non-finite GPS values and extraction error reporting."""

import ast
import importlib
import io
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_modules():
    package = ModuleType("frame_extract_test_package")
    package.__path__ = [str(ROOT)]
    qt = ModuleType("qgis.PyQt")
    qt.QtGui = SimpleNamespace()
    qt_core = ModuleType("qgis.PyQt.QtCore")
    for name in ("QDate", "QDateTime", "QTime", "Qt"):
        setattr(qt_core, name, object())
    compat = ModuleType("frame_extract_test_package.qt_compat")
    for name in ("QT_UTC", "QT_KEEP_ASPECT_RATIO", "QT_SMOOTH_TRANSFORMATION"):
        setattr(compat, name, object())
    with patch.dict(sys.modules, {
        package.__name__: package,
        compat.__name__: compat,
        "qgis": ModuleType("qgis"), "qgis.PyQt": qt, "qgis.PyQt.QtCore": qt_core,
    }):
        return tuple(importlib.import_module(package.__name__ + "." + name)
                     for name in ("common", "exif_utils", "frame_extract"))


def feature(attributes, lat=float("nan"), lon=float("nan")):
    class Feature:
        def __getitem__(self, key):
            return attributes[key]

        def fields(self):
            return SimpleNamespace(indexFromName=lambda name: 0 if name in attributes else -1)

        def geometry(self):
            return SimpleNamespace(isEmpty=lambda: False, asPoint=lambda: SimpleNamespace(
                x=lambda: lon, y=lambda: lat,
            ))

    return Feature()


class FrameExtractionTests(unittest.TestCase):
    def setUp(self):
        self.common, self.exif, self.frames = load_modules()
        self.target = self.frames.FrameExtractMixin()

    def test_parse_float_rejects_nan_and_infinity_but_preserves_zero(self):
        for value in (float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "1e999"):
            with self.subTest(value=value):
                self.assertIsNone(self.common._parse_float(value))
        self.assertEqual(self.common._parse_float(0), 0.0)
        self.assertEqual(self.common._parse_float("１,２３４.５"), 1234.5)

    def test_invalid_aligned_gps_falls_back_to_original_position(self):
        result = self.target.featureGps(feature({
            "aligned_latitude": float("nan"), "aligned_longitude": 135.0,
            "latitude": 35.0, "longitude": 135.0,
        }))
        self.assertEqual(result, {"lat": 35.0, "lon": 135.0})

    def test_non_geometry_marking_position_does_not_supply_nan_gps(self):
        self.assertIsNone(self.target.featureGps(feature({})))

    def test_valid_geometry_and_zero_coordinates_are_kept(self):
        self.assertEqual(self.target.featureGps(feature({}, lat=0.0, lon=0.0)),
                         {"lat": 0.0, "lon": 0.0})

    def test_invalid_gps_is_omitted_from_exif_without_losing_other_tags(self):
        tags = {"description": "frame=42", "software": "Geo360View", "datetime": "2026:10:08 12:00:00"}
        expected = self.exif._minimal_exif_payload(tags)
        for gps in ({"lat": float("nan"), "lon": 135.0},
                    {"lat": 35.0, "lon": float("inf")},
                    {"lat": 91.0, "lon": 135.0},
                    {"lat": 35.0, "lon": 181.0}, {"lat": None}, {}):
            with self.subTest(gps=gps):
                self.assertEqual(self.exif._minimal_exif_payload(tags, gps), expected)
        self.assertNotEqual(self.exif._minimal_exif_payload(tags, {"lat": 0.0, "lon": 0.0}), expected)

    def prepare_extraction(self, directory):
        target = self.target
        target.video_file = "sample.mp4"
        target.collectFrameExtractConfig = lambda number: SimpleNamespace(frame_number=number, video_file=target.video_file)
        target.setCurrentFrame = Mock()
        target.imagesDir = lambda: directory
        target.frameImagePath = lambda number: str(Path(directory) / f"frame_{number}.jpg")
        target.uiText = lambda key, **kwargs: key
        target.framePreviewInfo = lambda *args: "preview"
        target.loadPreview = Mock()
        target.notifyWarning = Mock()
        target.notifyDebug = Mock()
        cap = Mock()
        cap.isOpened.return_value = True
        cap.read.return_value = (True, object())
        position = [0]
        def seek(prop, number):
            position[0] = number
            return True
        def read():
            position[0] += 1
            return True, object()
        cap.set.side_effect = seek
        cap.read.side_effect = read
        cap.get.side_effect = lambda prop: {1: position[0], 7: 53497, 5: 29.97}.get(prop, 0)
        cv2 = ModuleType("cv2")
        cv2.VideoCapture = Mock(return_value=cap)
        cv2.CAP_PROP_POS_FRAMES = 1
        cv2.CAP_PROP_FRAME_COUNT = 7
        cv2.CAP_PROP_FPS = 5
        cv2.IMWRITE_JPEG_QUALITY = 2
        cv2.imencode = Mock(return_value=(True, SimpleNamespace(tobytes=lambda: b"\xff\xd8\xff\xd9")))
        return target, cv2, cap

    def test_panel_frame_count_uses_thread_limited_ffmpeg_open(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            video = Path(directory) / "sample.mp4"
            video.write_bytes(b"video")
            target.video_file = str(video)
            cv2.CAP_FFMPEG = 1900
            cv2.CAP_PROP_N_THREADS = 70
            cap.get.side_effect = lambda prop: {7: 53497, 70: 8}[prop]
            with patch.dict(sys.modules, {"cv2": cv2}):
                self.assertEqual(target.videoFrameCount(), 53497)
            cv2.VideoCapture.assert_called_once_with(str(video), 1900, [70, 8])
            cap.release.assert_called_once()

    def test_frame_count_is_cached_and_refreshed_when_video_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            video = Path(directory) / "sample.mp4"
            video.write_bytes(b"video")
            target.video_file = str(video)
            cap.get.side_effect = None
            cap.get.return_value = 53497.0
            with patch.dict(sys.modules, {"cv2": cv2}):
                self.assertEqual(target.videoFrameCount(), 53497)
                self.assertEqual(target.videoFrameCount(), 53497)
                cv2.VideoCapture.assert_called_once()
                video.write_bytes(b"new video")
                cap.get.return_value = 60000.0
                self.assertEqual(target.videoFrameCount(), 60000)
            self.assertEqual(cv2.VideoCapture.call_count, 2)
            self.assertEqual(cap.release.call_count, 2)

    def test_extraction_beyond_end_preserves_current_frame_and_skips_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            target.videoFrameCount = lambda: 53497
            with patch.dict(sys.modules, {"cv2": cv2}):
                target.extractFrame(53671)
            target.notifyWarning.assert_called_once_with("frame_out_of_range", frame=53671, last=53496)
            target.setCurrentFrame.assert_not_called()
            cap.read.assert_not_called()
            target.loadPreview.assert_not_called()

    def test_unknown_or_nonfinite_frame_count_does_not_invent_a_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            video = Path(directory) / "sample.mp4"
            video.write_bytes(b"video")
            target.video_file = str(video)
            cap.get.side_effect = None
            for count in (0, -1, float("nan"), float("inf")):
                with self.subTest(count=count), patch.dict(sys.modules, {"cv2": cv2}):
                    cap.get.return_value = count
                    self.assertIsNone(target.videoFrameCount())
                    self.assertTrue(target.validateVideoFrame(53671))

    def test_extraction_saves_jpeg_when_feature_has_nan_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            with patch.dict(sys.modules, {"cv2": cv2}):
                target.extractFrame(42, feature=feature({}))
            data = (Path(directory) / "frame_42.jpg").read_bytes()
            self.assertTrue(data.startswith(b"\xff\xd8\xff\xe1"))
            self.assertIn(b"Exif\x00\x00", data)
            target.notifyWarning.assert_not_called()
            target.loadPreview.assert_called_once()
            cap.release.assert_called_once()

    def test_save_failure_reports_stage_and_keeps_full_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            error = ValueError("cannot convert float NaN to integer")
            target.saveFrameImage = Mock(side_effect=error)
            log = io.StringIO()
            with patch.dict(sys.modules, {"cv2": cv2}), patch("sys.stderr", log):
                target.extractFrame(42)
            target.notifyWarning.assert_called_once_with(
                "frame_extract_failed_at_stage", frame=42, stage="ui.preview.stage.save", error=error,
            )
            self.assertIn("Traceback", log.getvalue())
            self.assertIn("cannot convert float NaN", log.getvalue())
            cap.release.assert_called_once()

    def test_old_unvalidated_preview_is_regenerated_once(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            image_path = Path(target.frameImagePath(42))
            image_path.write_bytes(b"old wrong image")
            with patch.dict(sys.modules, {"cv2": cv2}):
                target.extractFrame(42)
                target.extractFrame(42)
            self.assertIn(b"frame_reader=seek-v2;", image_path.read_bytes())
            cap.read.assert_called_once()
            self.assertEqual(target.loadPreview.call_count, 2)

    def test_qgis_preview_rejects_bad_seek_without_ffmpeg_or_image_save(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cv2, cap = self.prepare_extraction(directory)
            cap.get.side_effect = lambda prop: {1: -3071382977204209, 7: 53497, 5: 29.97}[prop]
            fallback = Mock()
            with patch.dict(sys.modules, {"cv2": cv2}), \
                    patch.dict(self.frames.read_video_frame.__globals__, {"_ffmpeg_frame": fallback}):
                with patch("sys.stderr", new_callable=io.StringIO):
                    target.extractFrame(9571)
            cap.read.assert_not_called()
            fallback.assert_not_called()
            cv2.imencode.assert_not_called()
            self.assertFalse(Path(target.frameImagePath(9571)).exists())
            target.notifyWarning.assert_called_once()


class MarkingNavigationTests(unittest.TestCase):
    def setUp(self):
        common, _, _ = load_modules()
        tree = ast.parse((ROOT / "main.py").read_text())
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "GPXVideoPlugin")
        names = {"steppedFrame", "frameStepNavigationTarget", "navigationTargetFrame",
                 "navigateRelative", "pickedFrames", "displayFrame"}
        methods = [node for node in plugin.body if isinstance(node, ast.FunctionDef)
                   and node.name in names]
        extracted = ast.Module(body=[ast.ClassDef(name="NavigationUnderTest", bases=[],
                                                keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        namespace = {"os": os, "QTimer": Mock()}
        exec(compile(ast.fix_missing_locations(extracted), "main.py", "exec"), namespace)
        self.target = namespace["NavigationUnderTest"]()
        self.display_method = self.target.displayFrame
        self.target.collectNavigationConfig = lambda: SimpleNamespace(mode="picked", step=1, fast_step=30)
        self.target.syncNavigationLayerForMode = Mock()
        self.target.currentFrameValue = lambda: 20
        self.target.isMarkingNavigationMode = lambda mode: mode == "picked"
        self.target.findFeatureByFrame = Mock(return_value="camera feature")
        self.target.videoFrameCount = lambda: None
        self.target.notifyWarning = Mock()
        self.target.displayFrame = Mock()
        self.target.targetFeatureFloat = lambda feature, field: common._parse_float(feature[field])

    def test_next_marking_at_end_stops_before_frame_display(self):
        self.target.pickedFrames = lambda: [10, 20]
        self.target.navigateRelative(1, fast=True)
        self.target.notifyWarning.assert_called_once_with("no_picked_frame", direction="next")
        self.target.displayFrame.assert_not_called()
        self.target.findFeatureByFrame.assert_not_called()

    def test_regular_step_in_marking_mode_advances_one_video_frame(self):
        self.target.navigateRelative(1, fast=False)
        self.target.displayFrame.assert_called_once_with(21, feature="camera feature")
        self.target.notifyWarning.assert_not_called()

    def test_step_crossing_end_displays_last_valid_frame(self):
        self.target.videoFrameCount = lambda: 53497
        self.target.currentFrameValue = lambda: 53071
        self.target.collectNavigationConfig = lambda: SimpleNamespace(mode="picked", step=600, fast_step=30)
        self.target.navigateRelative(1)
        self.target.displayFrame.assert_called_once_with(53496, feature="camera feature")

    def test_next_at_video_end_does_not_send_another_display_request(self):
        self.target.videoFrameCount = lambda: 53497
        self.target.currentFrameValue = lambda: 53496
        self.target.navigateRelative(1)
        self.target.notifyWarning.assert_called_once_with("video_end_reached", last=53496)
        self.target.displayFrame.assert_not_called()
        self.target.findFeatureByFrame.assert_not_called()

    def test_previous_from_end_still_moves_back(self):
        self.target.videoFrameCount = lambda: 53497
        self.target.currentFrameValue = lambda: 53496
        self.target.navigateRelative(-1)
        self.target.displayFrame.assert_called_once_with(53495, feature="camera feature")

    def test_direct_out_of_range_display_preserves_frame_and_skips_viewer(self):
        self.target.validateVideoFrame = lambda frame: frame < 53497
        self.target.setCurrentFrame = Mock()
        self.target.showFrameInViewer = Mock()
        self.display_method(53671)
        self.target.setCurrentFrame.assert_not_called()
        self.target.showFrameInViewer.assert_not_called()

    def test_marking_frames_skip_nonfinite_attributes(self):
        self.target.video_file = ""
        layer = SimpleNamespace(getFeatures=lambda: [
            {"frame": float("nan")}, {"frame": float("inf")}, {"frame": 0}, {"frame": 20},
        ])
        self.target.viewerTargetReadLayers = lambda: [layer]
        self.target.targetFeatureValue = lambda feature, name: feature.get(name)
        self.assertEqual(self.target.pickedFrames(), [0, 20])


if __name__ == "__main__":
    unittest.main()
