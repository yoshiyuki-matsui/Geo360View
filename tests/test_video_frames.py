"""Regression tests for incorrect OpenCV seeks and optional FFmpeg fallback."""

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("video_frames_under_test", Path(__file__).resolve().parents[1] / "video_frames.py")
frames = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frames)


class VideoCaptureThreadTests(unittest.TestCase):
    def setUp(self):
        self.cap = Mock()
        self.cap.isOpened.return_value = True
        self.cap.get.return_value = 8
        self.cv2 = SimpleNamespace(VideoCapture=Mock(return_value=self.cap),
                                   CAP_FFMPEG=1900, CAP_PROP_N_THREADS=70)

    def test_open_limits_ffmpeg_threads_before_decoder_initialization(self):
        actual = frames.open_video_capture(Path("video.mp4"), self.cv2)
        self.assertIs(actual, self.cap)
        self.cv2.VideoCapture.assert_called_once_with("video.mp4", 1900, [70, 8])
        self.cap.set.assert_not_called()
        self.cap.release.assert_not_called()

    def test_codec_using_fewer_threads_is_accepted(self):
        self.cap.get.return_value = 1
        self.assertIs(frames.open_video_capture("video.mp4", self.cv2), self.cap)

    def test_unopened_capture_is_released_without_unrestricted_retry(self):
        self.cap.isOpened.return_value = False
        with self.assertRaisesRegex(RuntimeError, "8 decoder threads"):
            frames.open_video_capture("video.mp4", self.cv2)
        self.cap.release.assert_called_once()
        self.cv2.VideoCapture.assert_called_once()

    def test_unapplied_limit_is_rejected_and_released(self):
        for value in (0, -1, 16, 20, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.cap.reset_mock()
                self.cap.get.return_value = value
                with self.assertRaisesRegex(RuntimeError, "limit was not applied"):
                    frames.open_video_capture("video.mp4", self.cv2)
                self.cap.release.assert_called_once()

    def test_property_error_releases_capture(self):
        self.cap.get.side_effect = RuntimeError("backend failure")
        with self.assertRaisesRegex(RuntimeError, "backend failure"):
            frames.open_video_capture("video.mp4", self.cv2)
        self.cap.release.assert_called_once()

    def test_legacy_api_warns_and_preserves_existing_open(self):
        legacy = SimpleNamespace(VideoCapture=Mock(return_value=self.cap), __version__="4.6.0")
        with self.assertWarnsRegex(RuntimeWarning, "4.6.0.*cannot set"):
            self.assertIs(frames.open_video_capture("video.mp4", legacy), self.cap)
        legacy.VideoCapture.assert_called_once_with("video.mp4")


class VideoFrameTests(unittest.TestCase):
    def setUp(self):
        self.cv2 = SimpleNamespace(CAP_PROP_FRAME_COUNT=7, CAP_PROP_POS_FRAMES=1,
                                   CAP_PROP_FPS=5, IMREAD_COLOR=1, imdecode=Mock())
        self.cap = Mock()
        self.position = 0
        self.cap.get.side_effect = lambda prop: {7: 53497, 1: self.position, 5: 29.97}[prop]
        self.cap.set.side_effect = self.seek
        self.cap.read.side_effect = self.read
        self.image = object()

    def seek(self, prop, number):
        self.position = number
        return True

    def read(self):
        self.position += 1
        return True, self.image

    def test_healthy_seek_does_not_call_ffmpeg(self):
        with patch.object(frames, "_ffmpeg_frame") as fallback:
            image, source = frames.read_video_frame(self.cap, "video.mp4", 9571, self.cv2)
        self.assertIs(image, self.image)
        self.assertEqual(source, "decode")
        fallback.assert_not_called()

    def test_first_frame_is_read_without_seeking_to_zero(self):
        image, source = frames.read_video_frame(self.cap, "video.mp4", 0, self.cv2)
        self.assertIs(image, self.image)
        self.cap.set.assert_not_called()

    def test_interactive_bad_seek_fails_without_starting_ffmpeg(self):
        self.cap.set.side_effect = lambda *args: setattr(self, "position", -3071382977204209) or True
        with patch.object(frames, "_ffmpeg_frame") as fallback:
            with self.assertRaisesRegex(RuntimeError, "OpenCV seek position"):
                frames.read_video_frame(self.cap, "video.mp4", 9571, self.cv2)
        self.cap.read.assert_not_called()
        fallback.assert_not_called()

    def test_huge_negative_seek_position_never_returns_the_wrong_frame(self):
        self.cap.set.side_effect = lambda *args: setattr(self, "position", -3071382977204209) or True
        correct = object()
        with patch.object(frames, "_ffmpeg_frame", return_value=correct) as fallback:
            image, source = frames.read_video_frame(self.cap, "video.mp4", 9571, self.cv2,
                                                   max_width=1536, allow_ffmpeg=True)
        self.assertIs(image, correct)
        self.assertEqual(source, "ffmpeg")
        self.cap.read.assert_not_called()
        self.cap.release.assert_called_once()
        fallback.assert_called_once_with("video.mp4", 9571, 29.97, self.cv2, 1536)

    def test_read_position_mismatch_or_nonfinite_value_uses_fallback(self):
        for value in (0, 1, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.position = 0
                self.cap.read.side_effect = lambda: (setattr(self, "position", value) or True, self.image)
                with patch.object(frames, "_ffmpeg_frame", return_value="correct"):
                    self.assertEqual(frames.read_video_frame(self.cap, "video.mp4", 9571, self.cv2, allow_ffmpeg=True),
                                     ("correct", "ffmpeg"))

    def test_failed_read_uses_fallback(self):
        self.cap.read.side_effect = lambda: (False, None)
        with patch.object(frames, "_ffmpeg_frame", return_value="correct"):
            self.assertEqual(frames.read_video_frame(self.cap, "video.mp4", 9571, self.cv2, allow_ffmpeg=True),
                             ("correct", "ffmpeg"))

    def test_out_of_range_request_does_not_decode_or_fallback(self):
        with patch.object(frames, "_ffmpeg_frame") as fallback:
            with self.assertRaisesRegex(ValueError, "0-53496"):
                frames.read_video_frame(self.cap, "video.mp4", 53671, self.cv2)
        self.cap.read.assert_not_called()
        fallback.assert_not_called()

    def test_missing_ffmpeg_reports_error_instead_of_caching_wrong_image(self):
        self.cap.set.side_effect = lambda *args: setattr(self, "position", -3071382977204209) or True
        with patch.object(frames.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "position.*FFmpeg executable is unavailable"):
                frames.read_video_frame(self.cap, "video.mp4", 9571, self.cv2, allow_ffmpeg=True)

    def test_ffmpeg_command_uses_argv_timeout_and_requested_width(self):
        result = SimpleNamespace(returncode=0, stdout=b"jpeg", stderr=b"")
        self.cv2.imdecode.return_value = self.image
        fake_numpy = SimpleNamespace(frombuffer=lambda data, dtype: data, uint8=object())
        with patch.object(frames.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                patch.object(frames.subprocess, "run", return_value=result) as run, \
                patch.dict(sys.modules, {"numpy": fake_numpy}):
            actual = frames._ffmpeg_frame("video with spaces.mp4", 9571, 30000 / 1001, self.cv2, 1536)
        self.assertIs(actual, self.image)
        args, kwargs = run.call_args
        command = args[0]
        self.assertEqual(command[0], "/usr/bin/ffmpeg")
        self.assertIn("scale=min(1536\\,iw):-2", command)
        self.assertLess(float(command[command.index("-ss") + 1]), 9571 / (30000 / 1001))
        self.assertEqual(kwargs["timeout"], 60)
        self.assertNotIn("shell", kwargs)

    def test_failed_ffmpeg_output_is_reported(self):
        result = SimpleNamespace(returncode=1, stdout=b"", stderr=b"decoder error")
        with patch.object(frames.shutil, "which", return_value="ffmpeg"), \
                patch.object(frames.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "decoder error"):
                frames._ffmpeg_frame("video.mp4", 9571, 29.97, self.cv2, 1536)


if __name__ == "__main__":
    unittest.main()
