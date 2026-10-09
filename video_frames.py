"""Validated OpenCV reads; FFmpeg is available only for explicit diagnostics."""

import math
import os
import shutil
import subprocess
import warnings


FRAME_READER_VERSION = "seek-v2"
VIDEO_DECODE_THREADS = 8


def open_video_capture(video_path, cv2):
    """Open with at most eight FFmpeg decoder threads when the API is available.

    Older OpenCV builds retain their existing capture path, with a warning:
    they cannot enforce this limit without an external workaround.
    Never retry a rejected thread-limited open with unrestricted defaults.
    """
    threads_property = getattr(cv2, "CAP_PROP_N_THREADS", None)
    if threads_property is None:
        warnings.warn(
            f"OpenCV {getattr(cv2, '__version__', 'unknown')} cannot set the video "
            "decoder thread limit. OpenCV 4.8 or newer with the FFmpeg backend "
            "is recommended; legacy random seeks may return incorrect frames.",
            RuntimeWarning,
        )
        return cv2.VideoCapture(str(video_path))
    cap = cv2.VideoCapture(str(video_path), cv2.CAP_FFMPEG,
                           [threads_property, VIDEO_DECODE_THREADS])
    try:
        if not cap.isOpened():
            raise RuntimeError("Failed to open video with the FFmpeg backend and "
                               "8 decoder threads; check the video and OpenCV FFmpeg support")
        actual = _number(cap.get(threads_property))
        if actual is None or not 1 <= actual <= VIDEO_DECODE_THREADS:
            raise RuntimeError(f"OpenCV decoder thread limit was not applied: {actual}; "
                               f"expected 1-{VIDEO_DECODE_THREADS}")
        return cap
    except Exception:
        cap.release()
        raise


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _check_position(value, expected, stage):
    position = _number(value)
    if position is None or position < 0 or abs(position - expected) > 0.5:
        raise RuntimeError(f"OpenCV {stage} position is {position}; expected {expected}")


def _ffmpeg_frame(video_path, frame_index, fps, cv2, max_width):
    program = shutil.which("ffmpeg")
    if not program:
        raise RuntimeError("FFmpeg executable is unavailable; install FFmpeg to use the fallback")
    fps = _number(fps)
    if fps is None or fps <= 0:
        raise RuntimeError("A valid video FPS is required for FFmpeg time seeking")
    # Seek just before the target timestamp to avoid rounding into the next
    # frame of a constant-rate video. FFmpeg discards earlier decoded frames.
    seconds = max(0.0, (frame_index - 0.25) / fps)
    command = [program, "-nostdin", "-hide_banner", "-loglevel", "error",
               "-ss", f"{seconds:.9f}", "-i", os.path.abspath(video_path),
               "-map", "0:v:0", "-frames:v", "1"]
    if max_width > 0:
        command += ["-vf", f"scale=min({int(max_width)}\\,iw):-2"]
    command += ["-threads", "1", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "2", "pipe:1"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=60, check=False)
    if result.returncode or not result.stdout:
        detail = result.stderr.decode("utf-8", "replace").strip()[-2000:]
        raise RuntimeError(f"FFmpeg frame extraction failed: {detail or 'no image returned'}")
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("FFmpeg output could not be decoded as an image")
    return frame


def read_video_frame(cap, video_path, frame_index, cv2, max_width=0, *, allow_ffmpeg=False):
    """Return (image, source); reject visibly incorrect OpenCV positions.

    Interactive callers never opt into the slow FFmpeg CLI fallback. Explicit
    diagnostic callers may enable frame/FPS time seeking. Reported positions alone
    cannot prove image content is correct, but invalid positions must never
    produce an image cached under a requested frame number.
    """
    if frame_index < 0:
        raise ValueError("Frame index must be nonnegative")
    count = _number(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if count is not None and count >= 1 and frame_index >= int(count):
        raise ValueError(f"Frame {frame_index} is outside the video range (0-{int(count) - 1})")
    try:
        # A fresh VideoCapture starts at zero; seeking to zero can itself fail
        # on affected OpenCV/FFmpeg builds.
        if frame_index:
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
                raise RuntimeError("OpenCV frame seek failed")
            _check_position(cap.get(cv2.CAP_PROP_POS_FRAMES), frame_index, "seek")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Failed to read frame_index={frame_index}")
        _check_position(cap.get(cv2.CAP_PROP_POS_FRAMES), frame_index + 1, "read")
        return frame, "decode"
    except Exception as error:
        if not allow_ffmpeg:
            raise
        fps = cap.get(cv2.CAP_PROP_FPS)
        # Release the native decoder before starting a second one for 8K video.
        cap.release()
        try:
            frame = _ffmpeg_frame(video_path, frame_index, fps, cv2, max_width)
        except Exception as fallback_error:
            raise RuntimeError(f"{error}; {fallback_error}") from fallback_error
        return frame, "ffmpeg"
