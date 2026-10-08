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
        cv2 = ModuleType("cv2")
        cv2.VideoCapture = Mock(return_value=cap)
        cv2.CAP_PROP_POS_FRAMES = 1
        cv2.IMWRITE_JPEG_QUALITY = 2
        cv2.imencode = Mock(return_value=(True, SimpleNamespace(tobytes=lambda: b"\xff\xd8\xff\xd9")))
        return target, cv2, cap

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


class MarkingNavigationTests(unittest.TestCase):
    def setUp(self):
        common, _, _ = load_modules()
        tree = ast.parse((ROOT / "main.py").read_text())
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "GPXVideoPlugin")
        names = {"steppedFrame", "frameStepNavigationTarget", "navigationTargetFrame",
                 "navigateRelative", "pickedFrames"}
        methods = [node for node in plugin.body if isinstance(node, ast.FunctionDef)
                   and node.name in names]
        extracted = ast.Module(body=[ast.ClassDef(name="NavigationUnderTest", bases=[],
                                                keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        namespace = {"os": os}
        exec(compile(ast.fix_missing_locations(extracted), "main.py", "exec"), namespace)
        self.target = namespace["NavigationUnderTest"]()
        self.target.collectNavigationConfig = lambda: SimpleNamespace(mode="picked", step=1, fast_step=30)
        self.target.syncNavigationLayerForMode = Mock()
        self.target.currentFrameValue = lambda: 20
        self.target.isMarkingNavigationMode = lambda mode: mode == "picked"
        self.target.findFeatureByFrame = Mock(return_value="camera feature")
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
