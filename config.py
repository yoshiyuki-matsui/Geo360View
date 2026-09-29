"""UI入力を機能単位のConfigへ束ね、処理前に検証する純Python層。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


NAVIGATION_MODES = {"frame", "layer", "kp", "marking", "picked", "detect"}
RADAR_OFFSETS = {0, 90, 180, 270}


@dataclass(frozen=True)
class ProcessConfig:
    """GPX/MP4からフレーム位置を生成するための入力設定。"""

    gpx_file: str
    video_file: str
    output_dir: str
    frame_shift: int
    kp_file: str | None
    kp_tolerance_m: float


@dataclass(frozen=True)
class FrameExtractConfig:
    """単一フレーム抽出に必要な入力設定。"""

    video_file: str
    frame_number: int
    output_dir: str


@dataclass(frozen=True)
class NavigationConfig:
    """フレーム送り操作に必要な入力設定。"""

    mode: str
    step: int
    fast_step: int
    follow: bool


@dataclass(frozen=True)
class RadarConfig:
    """地図レーダ表示と距離校正に必要な入力設定。"""

    range_m: float
    scale: float
    cal_fov_deg: float
    cal_dist_m: float
    offset_deg: int


@dataclass(frozen=True)
class ViewerConfig:
    """360Viewer起動とHTTP連携に必要な入力設定。"""

    host: str
    port: int
    video_dir: str
    session_json_path: str
    cache_dir: str
    jpeg_quality: int
    progressive_jpeg: bool
    max_width: int
    camera_height_m: float
    hud_height_scale: float


def _text(value: Any) -> str:
    """Noneを空文字へ寄せ、前後空白を除去する。"""
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    """空文字をNoneへ寄せた文字列を返す。"""
    text = _text(value)
    return text or None


def _int_value(value: Any, name: str, errors: list[str], default: int = 0) -> int:
    """整数へ変換し、失敗時はerrorsへ説明を追加する。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{name} must be an integer.")
        return default


def _float_value(value: Any, name: str, errors: list[str], default: float = 0.0) -> float:
    """floatへ変換し、失敗時はerrorsへ説明を追加する。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{name} must be a number.")
        return default


def _file_exists(path: str, label: str, errors: list[str]) -> None:
    """ファイル存在を検証する。"""
    if not os.path.isfile(path):
        errors.append(f"{label} was not found: {path}")


def _extension(path: str) -> str:
    """小文字拡張子を返す。"""
    return Path(path).suffix.lower()


def _validate_output_dir(path: str, errors: list[str]) -> None:
    """出力先が既存ファイルではないことと、親が存在することを確認する。"""
    if not path:
        errors.append("Output folder is required.")
        return
    if os.path.isfile(path):
        errors.append(f"Output folder points to a file: {path}")
        return

    parent = Path(path).expanduser().resolve().parent
    if not parent.exists():
        errors.append(f"Output folder parent does not exist: {parent}")


def _validate_creatable_parent(path: str, label: str, errors: list[str]) -> None:
    """対象パスの親ディレクトリが作成可能な構造かを確認する。"""
    parent = Path(path).expanduser().resolve().parent
    if parent.exists():
        if not parent.is_dir():
            errors.append(f"{label} parent points to a file: {parent}")
        return

    nearest_existing = parent
    while not nearest_existing.exists() and nearest_existing != nearest_existing.parent:
        nearest_existing = nearest_existing.parent
    if not nearest_existing.is_dir():
        errors.append(f"{label} parent cannot be created under: {nearest_existing}")


def validate_process_config(raw: dict[str, Any]) -> tuple[ProcessConfig | None, list[str]]:
    """Process実行前の入力を検証し、正規化済みConfigを返す。"""
    errors: list[str] = []
    gpx_file = _text(raw.get("gpx_file"))
    video_file = _text(raw.get("video_file"))
    output_dir = _text(raw.get("output_dir"))
    kp_file = _optional_text(raw.get("kp_file"))
    frame_shift = _int_value(raw.get("frame_shift", 0), "Frame shift", errors)
    kp_tolerance_m = _float_value(raw.get("kp_tolerance_m", 5.0), "Reference tolerance", errors, 5.0)

    if not gpx_file:
        errors.append("GPX file is required.")
    else:
        if _extension(gpx_file) != ".gpx":
            errors.append("GPX file must be a .gpx file.")
        _file_exists(gpx_file, "GPX file", errors)

    if not video_file:
        errors.append("Video file is required.")
    else:
        if _extension(video_file) != ".mp4":
            errors.append("Video file must be a .mp4 file.")
        _file_exists(video_file, "Video file", errors)

    if kp_file:
        if _extension(kp_file) != ".csv":
            errors.append("Reference file must be a .csv file.")
        _file_exists(kp_file, "Reference file", errors)

    _validate_output_dir(output_dir, errors)

    if not -1000000 <= frame_shift <= 1000000:
        errors.append("Frame shift must be between -1000000 and 1000000.")
    if kp_tolerance_m < 0:
        errors.append("Reference tolerance must be greater than or equal to 0.")

    if errors:
        return None, errors
    return ProcessConfig(
        gpx_file=gpx_file,
        video_file=video_file,
        output_dir=output_dir,
        frame_shift=frame_shift,
        kp_file=kp_file,
        kp_tolerance_m=kp_tolerance_m,
    ), []


def validate_frame_extract_config(raw: dict[str, Any]) -> tuple[FrameExtractConfig | None, list[str]]:
    """単一フレーム抽出前の入力を検証する。"""
    errors: list[str] = []
    video_file = _text(raw.get("video_file"))
    output_dir = _text(raw.get("output_dir"))
    frame_number = _int_value(raw.get("frame_number", 0), "Frame number", errors)

    if not video_file:
        errors.append("Video file is required.")
    else:
        if _extension(video_file) != ".mp4":
            errors.append("Video file must be a .mp4 file.")
        _file_exists(video_file, "Video file", errors)

    _validate_output_dir(output_dir, errors)

    if frame_number < 0:
        errors.append("Frame number must be greater than or equal to 0.")

    if errors:
        return None, errors
    return FrameExtractConfig(video_file=video_file, frame_number=frame_number, output_dir=output_dir), []


def validate_navigation_config(raw: dict[str, Any]) -> tuple[NavigationConfig | None, list[str]]:
    """ナビゲーション操作前の入力を検証する。"""
    errors: list[str] = []
    mode = _text(raw.get("mode"))
    step = _int_value(raw.get("step", 1), "Navigation step", errors, 1)
    fast_step = _int_value(raw.get("fast_step", 30), "Fast navigation step", errors, 30)
    follow = bool(raw.get("follow", False))

    if mode not in NAVIGATION_MODES:
        errors.append(f"Navigation mode is invalid: {mode}")
    if step < 1:
        errors.append("Navigation step must be greater than or equal to 1.")
    if fast_step < 1:
        errors.append("Fast navigation step must be greater than or equal to 1.")

    if errors:
        return None, errors
    return NavigationConfig(mode=mode, step=step, fast_step=fast_step, follow=follow), []


def validate_radar_config(raw: dict[str, Any]) -> tuple[RadarConfig | None, list[str]]:
    """レーダ表示前の入力を検証する。"""
    errors: list[str] = []
    range_m = _float_value(raw.get("range_m", 5.0), "Radar range", errors, 5.0)
    scale = _float_value(raw.get("scale", 1.0), "Radar scale", errors, 1.0)
    cal_fov_deg = _float_value(raw.get("cal_fov_deg", 90.0), "Calibration FOV", errors, 90.0)
    cal_dist_m = _float_value(raw.get("cal_dist_m", 5.0), "Calibration distance", errors, 5.0)
    offset_deg = _int_value(raw.get("offset_deg", 0), "Radar offset", errors, 0)

    if not 1.0 <= range_m <= 500.0:
        errors.append("Radar range must be between 1.0 and 500.0 m.")
    if not 0.1 <= scale <= 20.0:
        errors.append("Radar scale must be between 0.1 and 20.0.")
    if not 1.0 <= cal_fov_deg <= 179.0:
        errors.append("Calibration FOV must be between 1.0 and 179.0 degrees.")
    if not 0.1 <= cal_dist_m <= 500.0:
        errors.append("Calibration distance must be between 0.1 and 500.0 m.")
    if offset_deg not in RADAR_OFFSETS:
        errors.append("Radar offset must be one of 0, 90, 180, or 270 degrees.")

    if errors:
        return None, errors
    return RadarConfig(
        range_m=range_m,
        scale=scale,
        cal_fov_deg=cal_fov_deg,
        cal_dist_m=cal_dist_m,
        offset_deg=offset_deg,
    ), []


def validate_viewer_config(raw: dict[str, Any]) -> tuple[ViewerConfig | None, list[str]]:
    """360Viewer起動前の入力を検証する。"""
    errors: list[str] = []
    host = _text(raw.get("host", "127.0.0.1"))
    port = _int_value(raw.get("port", 8181), "Viewer port", errors, 8181)
    video_dir = _text(raw.get("video_dir"))
    session_json_path = _text(raw.get("session_json_path"))
    cache_dir = _text(raw.get("cache_dir"))
    jpeg_quality = _int_value(raw.get("jpeg_quality", 90), "Viewer JPEG quality", errors, 90)
    progressive_jpeg = bool(raw.get("progressive_jpeg", True))
    max_width = _int_value(raw.get("max_width", 3072), "Viewer maximum width", errors, 3072)
    camera_height_m = _float_value(raw.get("camera_height_m", 1.5), "Viewer camera height", errors, 1.5)
    hud_height_scale = _float_value(raw.get("hud_height_scale", 1.0), "Viewer HUD height scale", errors, 1.0)

    if not host:
        errors.append("Viewer host is required.")
    if not 1 <= port <= 65535:
        errors.append("Viewer port must be between 1 and 65535.")
    if not video_dir:
        errors.append("Viewer video folder is required.")
    elif not os.path.isdir(video_dir):
        errors.append(f"Viewer video folder was not found: {video_dir}")
    if not session_json_path:
        errors.append("Viewer session JSON path is required.")
    else:
        _validate_creatable_parent(session_json_path, "Viewer session JSON", errors)
    if not cache_dir:
        errors.append("Viewer cache folder is required.")
    elif os.path.isfile(cache_dir):
        errors.append(f"Viewer cache folder points to a file: {cache_dir}")
    else:
        _validate_creatable_parent(os.path.join(cache_dir, ".keep"), "Viewer cache folder", errors)
    if not 1 <= jpeg_quality <= 100:
        errors.append("Viewer JPEG quality must be between 1 and 100.")
    if max_width < 0:
        errors.append("Viewer maximum width must be greater than or equal to 0.")
    if not 0.1 <= camera_height_m <= 20.0:
        errors.append("Viewer camera height must be between 0.1 and 20.0 m.")
    if not 0.1 <= hud_height_scale <= 5.0:
        errors.append("Viewer HUD height scale must be between 0.1 and 5.0.")

    if errors:
        return None, errors
    return ViewerConfig(
        host=host,
        port=port,
        video_dir=video_dir,
        session_json_path=session_json_path,
        cache_dir=cache_dir,
        jpeg_quality=jpeg_quality,
        progressive_jpeg=progressive_jpeg,
        max_width=max_width,
        camera_height_m=camera_height_m,
        hud_height_scale=hud_height_scale,
    ), []
