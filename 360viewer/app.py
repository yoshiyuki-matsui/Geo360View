from __future__ import annotations

"""QGISプラグインから起動される標準ライブラリ製ローカル360Viewerサーバ。"""

import csv
import base64
import binascii
import json
import math
import mimetypes
import os
import re
import struct
import sys
import threading
import time
import uuid
from datetime import datetime
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))
from video_frames import FRAME_READER_VERSION, open_video_capture, read_video_frame
from environment_diagnostics import collect_environment
from viewer_runtime import server_build

# Capture the loaded generation once. An older process must not advertise
# newly installed code by recomputing this after files have been replaced.
SERVER_BUILD = server_build(__file__)
OWNER_TOKEN = os.environ.get("VIEWER_OWNER_TOKEN", "")

CONFIG_PATH = Path(os.environ.get("VIEWER_CONFIG", BASE_DIR / "viewer_config.json"))
STATIC_DIR = BASE_DIR / "static"
KRPANO_JS_PATH = STATIC_DIR / "vendor" / "krpano" / "krpano.js"
PSV_VENDOR_DIR = STATIC_DIR / "vendor" / "photo-sphere-viewer"
PSV_CORE_JS_PATH = PSV_VENDOR_DIR / "core" / "index.module.js"
PSV_CORE_CSS_PATH = PSV_VENDOR_DIR / "core" / "index.css"
PSV_MARKERS_JS_PATH = PSV_VENDOR_DIR / "markers-plugin" / "index.module.js"
PSV_MARKERS_CSS_PATH = PSV_VENDOR_DIR / "markers-plugin" / "index.css"
PSV_THREE_JS_PATH = PSV_VENDOR_DIR / "three" / "three.module.js"
PSV_THREE_CORE_JS_PATH = PSV_VENDOR_DIR / "three" / "three.core.js"
DEFAULT_VIEW = {
    "yaw_to_camera_heading": 0.0,
    "pitch": 0.0,
    "zoom": 1.0,
}
DEFAULT_CAMERA_HEIGHT_M = 1.5
MIN_CAMERA_HEIGHT_M = 0.1
MAX_CAMERA_HEIGHT_M = 20.0
DEFAULT_HUD_HEIGHT_SCALE = 1.0
MIN_HUD_HEIGHT_SCALE = 0.1
MAX_HUD_HEIGHT_SCALE = 5.0
MAX_VIEWER_TARGETS = 100
VIEWER_PROJECTION_SPHERE = "sphere"
VIEWER_PROJECTION_FLAT = "flat"
VIEWER_PROJECTIONS = {VIEWER_PROJECTION_SPHERE, VIEWER_PROJECTION_FLAT}
VIEWER_ENGINE_KRPANO = "krpano"
VIEWER_ENGINE_PSV = "psv"
VIEWER_ENGINES = {VIEWER_ENGINE_KRPANO, VIEWER_ENGINE_PSV}
PSV_VENDOR_VERSION = "5.15.1-reference1"
DEFAULT_FLAT_HFOV_DEG = 70.0
DEFAULT_FLAT_VFOV_DEG = 43.0
DEFAULT_PSV_MIN_FOV_DEG = 20.0
DEFAULT_PSV_MAX_FOV_DEG = 120.0



class ConfigError(RuntimeError):
    """ビューア設定ファイルが読めない場合の起動時エラー。"""
    pass


class ApiError(RuntimeError):
    """HTTP APIとして返すstatus/message付きの例外。"""

    def __init__(self, status: int, message: str):
        """HTTPステータスとエラーメッセージを保持する。"""
        super().__init__(message)
        self.status = status
        self.message = message


def normalize_camera_height(value: Any, default: float = DEFAULT_CAMERA_HEIGHT_M) -> float:
    """ジョブ条件のカメラ高さを安全な範囲のm値へ正規化する。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    if not math.isfinite(numeric):
        numeric = float(default)
    return max(MIN_CAMERA_HEIGHT_M, min(MAX_CAMERA_HEIGHT_M, numeric))


def normalize_hud_height_scale(value: Any, default: float = DEFAULT_HUD_HEIGHT_SCALE) -> float:
    """地面範囲円だけに使うカメラ高倍率を安全な範囲へ正規化する。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    if not math.isfinite(numeric):
        numeric = float(default)
    return max(MIN_HUD_HEIGHT_SCALE, min(MAX_HUD_HEIGHT_SCALE, numeric))


def normalize_viewer_projection(value: Any, default: str = VIEWER_PROJECTION_SPHERE) -> str:
    """ビューア画像投影を sphere/flat の安全な値へ正規化する。"""
    text = str(value or default).strip().lower()
    aliases = {
        "360": VIEWER_PROJECTION_SPHERE,
        "equirectangular": VIEWER_PROJECTION_SPHERE,
        "pano": VIEWER_PROJECTION_SPHERE,
        "pinhole": VIEWER_PROJECTION_FLAT,
        "front": VIEWER_PROJECTION_FLAT,
    }
    text = aliases.get(text, text)
    return text if text in VIEWER_PROJECTIONS else default


def normalize_viewer_engine(value: Any, default: str = VIEWER_ENGINE_KRPANO) -> str:
    """viewer実装をkrpano/Photo Sphere Viewerの安全な値へ正規化する。"""
    text = str(value or default).strip().lower()
    aliases = {
        "photo-sphere-viewer": VIEWER_ENGINE_PSV,
        "photosphere": VIEWER_ENGINE_PSV,
        "photo_sphere_viewer": VIEWER_ENGINE_PSV,
    }
    text = aliases.get(text, text)
    return text if text in VIEWER_ENGINES else default


def photo_sphere_viewer_available() -> bool:
    """Photo Sphere Viewerのローカルvendor一式が配置済みかを返す。"""
    return all(
        path.is_file()
        for path in (
            PSV_CORE_JS_PATH,
            PSV_CORE_CSS_PATH,
            PSV_MARKERS_JS_PATH,
            PSV_MARKERS_CSS_PATH,
            PSV_THREE_JS_PATH,
            PSV_THREE_CORE_JS_PATH,
        )
    )


def normalize_fov_deg(value: Any, default: float) -> float:
    """flat表示用FOVをkrpanoが扱える範囲へ正規化する。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    if not math.isfinite(numeric):
        numeric = float(default)
    return max(1.0, min(179.0, numeric))


def config_value(raw: dict[str, Any], names: tuple[str, ...], default: Any) -> Any:
    """複数の設定名候補から最初に見つかった値を返す。"""
    for name in names:
        if name in raw:
            return raw.get(name)
    return default


def load_config() -> dict[str, Any]:
    """viewer_config JSONを読み、パスと画質設定を正規化して返す。"""
    if not CONFIG_PATH.is_file():
        raise ConfigError(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    video_dir = resolve_config_path(raw.get("video_dir", "."))
    session_json_path = resolve_config_path(raw.get("session_json_path", "session.json"))
    command_json_path = resolve_config_path(
        raw.get("command_json_path", session_json_path.with_name("viewer_command.json"))
    )
    viewer_cache_dir = resolve_config_path(raw.get("viewer_cache_dir", "viewer_cache"))

    return {
        "host": raw.get("host", "127.0.0.1"),
        "port": int(raw.get("port", 8181)),
        "video_dir": video_dir,
        "session_json_path": session_json_path,
        "command_json_path": command_json_path,
        "viewer_jpeg_quality": max(1, min(100, int(raw.get("viewer_jpeg_quality", 90)))),
        "viewer_progressive_jpeg": parse_bool(raw.get("viewer_progressive_jpeg", True)),
        "viewer_max_width": max(0, int(raw.get("viewer_max_width", 3072))),
        "viewer_snapshot_jpeg_quality": max(1, min(100, int(raw.get("viewer_snapshot_jpeg_quality", 96)))),
        "viewer_snapshot_max_width": max(0, int(raw.get("viewer_snapshot_max_width", 0))),
        "viewer_snapshot_output_scale": max(1.0, min(3.0, float(raw.get("viewer_snapshot_output_scale", 2.0)))),
        "viewer_cache_dir": viewer_cache_dir,
        "viewer_camera_height_m": normalize_camera_height(raw.get("viewer_camera_height_m")),
        "viewer_hud_height_scale": normalize_hud_height_scale(raw.get("viewer_hud_height_scale")),
        "viewer_debug_log_enabled": parse_bool(raw.get("viewer_debug_log_enabled", False)),
        "viewer_projection": normalize_viewer_projection(raw.get("viewer_projection")),
        "viewer_flat_hfov_deg": normalize_fov_deg(raw.get("viewer_flat_hfov_deg"), DEFAULT_FLAT_HFOV_DEG),
        "viewer_flat_vfov_deg": normalize_fov_deg(raw.get("viewer_flat_vfov_deg"), DEFAULT_FLAT_VFOV_DEG),
        "viewer_psv_min_fov_deg": normalize_fov_deg(
            config_value(raw, ("viewer_psv_min_fov_deg", "psv_min_fov_deg", "min_fov", "minFov"), DEFAULT_PSV_MIN_FOV_DEG),
            DEFAULT_PSV_MIN_FOV_DEG,
        ),
        "viewer_psv_max_fov_deg": normalize_fov_deg(
            config_value(raw, ("viewer_psv_max_fov_deg", "psv_max_fov_deg", "max_fov", "maxFov"), DEFAULT_PSV_MAX_FOV_DEG),
            DEFAULT_PSV_MAX_FOV_DEG,
        ),
    }


def resolve_config_path(value: str) -> Path:
    """設定内の相対パスを360viewerディレクトリ基準の絶対パスへ解決する。"""
    raw_value = str(value or "")
    windows_match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw_value)
    if windows_match and os.name != "nt":
        drive = windows_match.group(1).lower()
        rest = windows_match.group(2).replace("\\", "/")
        path = Path("/mnt") / drive / rest
        return path.resolve()

    path = Path(raw_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def parse_bool(value: Any) -> bool:
    """JSON/環境値の真偽表現をboolへ変換する。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def now_iso() -> str:
    """セッションJSONへ書くローカルタイムゾーン付き現在時刻を返す。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def query_value(query: dict[str, list[str]], name: str, default: Any = None) -> Any:
    """parse_qs形式のqueryから先頭値を取り出す。"""
    values = query.get(name)
    if not values:
        return default
    return values[0]


def safe_video_name(video: str) -> str:
    """動画名をファイル名だけに制限し、パストラバーサルを防ぐ。"""
    video = (video or "").strip()
    if not video:
        raise ApiError(400, "video is required")
    if "/" in video or "\\" in video or ":" in video:
        raise ApiError(400, "video must be a file name, not a path")
    if Path(video).name != video:
        raise ApiError(400, "video must be a file name")
    if Path(video).suffix.lower() != ".mp4":
        raise ApiError(400, "video must be an .mp4 file")
    return video


def parse_frame_index(value: Any) -> int:
    """HTTP入力から0以上の整数フレーム番号を取り出す。"""
    try:
        frame_index = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, "frame_index must be an integer")
    if frame_index < 0:
        raise ApiError(400, "frame_index must be greater than or equal to 0")
    return frame_index


def parse_float(value: Any, name: str, default: float | None = None) -> float:
    """HTTP入力からfloat値を取り出す。必須値不足はApiErrorにする。"""
    if value is None or value == "":
        if default is None:
            raise ApiError(400, f"{name} is required")
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number")


def parse_optional_float(value: Any) -> float | None:
    """空値をNoneとして扱う任意float変換。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_yaw(value: float) -> float:
    """yaw角を0以上360未満へ正規化する。"""
    return value % 360.0


def view_state_from_query(query: dict[str, list[str]], session: dict[str, Any] | None = None) -> dict[str, float]:
    """URL queryと既存セッションからビュー視点状態を作る。"""
    session = session if session is not None else read_session()

    def value_for(name: str) -> Any:
        """query値がなければ前回セッション、さらに既定値を使う。"""
        value = query_value(query, name)
        if value is None or value == "":
            value = session.get(name, DEFAULT_VIEW[name])
        return value

    cfg = load_config()
    return {
        "yaw_to_camera_heading": normalize_yaw(
            parse_float(value_for("yaw_to_camera_heading"), "yaw_to_camera_heading", DEFAULT_VIEW["yaw_to_camera_heading"])
        ),
        "pitch": parse_float(value_for("pitch"), "pitch", DEFAULT_VIEW["pitch"]),
        "zoom": parse_float(value_for("zoom"), "zoom", DEFAULT_VIEW["zoom"]),
        "viewer_projection": normalize_viewer_projection(
            query_value(query, "viewer_projection", session.get("viewer_projection", cfg["viewer_projection"]))
        ),
        "viewer_flat_hfov_deg": normalize_fov_deg(
            query_value(query, "viewer_flat_hfov_deg", session.get("viewer_flat_hfov_deg", cfg["viewer_flat_hfov_deg"])),
            cfg["viewer_flat_hfov_deg"],
        ),
        "viewer_flat_vfov_deg": normalize_fov_deg(
            query_value(query, "viewer_flat_vfov_deg", session.get("viewer_flat_vfov_deg", cfg["viewer_flat_vfov_deg"])),
            cfg["viewer_flat_vfov_deg"],
        ),
        "viewer_psv_min_fov_deg": normalize_fov_deg(
            query_value(query, "viewer_psv_min_fov_deg", session.get("viewer_psv_min_fov_deg", cfg["viewer_psv_min_fov_deg"])),
            cfg["viewer_psv_min_fov_deg"],
        ),
        "viewer_psv_max_fov_deg": normalize_fov_deg(
            query_value(query, "viewer_psv_max_fov_deg", session.get("viewer_psv_max_fov_deg", cfg["viewer_psv_max_fov_deg"])),
            cfg["viewer_psv_max_fov_deg"],
        ),
    }


def safe_cache_stem(video: str) -> str:
    """ビューアJPEGキャッシュ名に使える安全な動画stemを返す。"""
    stem = Path(video).stem
    stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", stem).strip("_")
    return stem or "video"


def video_path(video: str) -> Path:
    """動画ファイル名を設定済みvideo_dir配下の絶対パスへ解決する。"""
    cfg = load_config()
    video = safe_video_name(video)
    root = cfg["video_dir"]
    path = (root / video).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ApiError(400, "video is outside video_dir")
    return path


def matched_frames_path(video: str) -> Path:
    """動画名に対応する参照点マッチ済みナビゲーションCSVのパスを返す。"""
    cfg = load_config()
    stem = Path(video).stem
    return (cfg["video_dir"] / f"{stem}_matched_frames.csv").resolve()


def frame_csv_candidates(video: str) -> list[Path]:
    """動画名に対応する全フレームCSVの候補パスを返す。"""
    cfg = load_config()
    stem = Path(video).stem
    session_dir = cfg["session_json_path"].resolve().parent
    paths = [
        session_dir / f"{stem}_frames.csv",
        cfg["video_dir"] / f"{stem}_frames.csv",
    ]
    navigation_paths = [
        session_dir / f"{stem}_navigation.json",
        cfg["video_dir"] / f"{stem}_navigation.json",
    ]
    for root in [session_dir, cfg["video_dir"]]:
        try:
            navigation_paths.extend(root.glob("*_navigation.json"))
        except OSError:  # nosec B112 - skip invalid item and continue scanning remaining records
            continue

    for path in navigation_paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # nosec B112 - skip invalid item and continue scanning remaining records
            continue
        payload_video = payload.get("video") if isinstance(payload, dict) else None
        if payload_video and Path(str(payload_video)).name != video:
            continue
        frames_csv = payload.get("frames_csv") if isinstance(payload, dict) else None
        if isinstance(frames_csv, str) and frames_csv:
            paths.append(path.parent / frames_csv)
    seen: set[Path] = set()
    candidates: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)
    return candidates


def first_present_path(paths: list[Path]) -> Path | None:
    """候補パスのうち最初に存在するファイルを返す。"""
    for path in paths:
        if path.is_file():
            return path
    return None


def load_matched_frames(video: str) -> list[int]:
    """matched_frames CSVからPrev/Next用frame_index一覧を読み込む。"""
    path = matched_frames_path(video)
    if not path.is_file():
        return []

    frames: set[int] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "frame_index" not in reader.fieldnames:
            return []
        for row in reader:
            raw = (row.get("frame_index") or "").strip()
            if not raw:
                continue
            try:
                frame = int(raw)
            except ValueError:  # nosec B112 - skip invalid item and continue scanning remaining records
                continue
            if frame >= 0:
                frames.add(frame)
    return sorted(frames)


def load_matched_frame_record(video: str, frame_index: int) -> dict[str, Any] | None:
    """matched_frames CSVから現在フレームの参照点情報を返す。"""
    path = matched_frames_path(video)
    if not path.is_file():
        return None

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "frame_index" not in reader.fieldnames:
            return None
        for row in reader:
            try:
                row_frame = int((row.get("frame_index") or "").strip())
            except ValueError:  # nosec B112 - skip invalid item and continue scanning remaining records
                continue
            if row_frame != int(frame_index):
                continue
            reference_label = (
                row.get("reference_label")
                or row.get("reference_name")
                or row.get("kp")
                or row.get("reference_id")
                or ""
            )
            return {
                "label": str(reference_label).strip(),
                "reference_id": (row.get("reference_id") or "").strip(),
                "reference_name": (row.get("reference_name") or "").strip(),
                "kp": (row.get("kp") or "").strip(),
                "distance_m": parse_optional_float(row.get("kp_distance_m")),
                "latitude": parse_optional_float(row.get("latitude")),
                "longitude": parse_optional_float(row.get("longitude")),
                "source": "matched_frames_csv",
            }
    return None


def load_frame_position_record(video: str, frame_index: int) -> dict[str, Any] | None:
    """frames CSVから現在フレームの撮影点座標を返す。"""
    path = first_present_path(frame_csv_candidates(video))
    if not path:
        return None

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return None
        frame_field = "frame_index" if "frame_index" in reader.fieldnames else "frame"
        if frame_field not in reader.fieldnames:
            return None
        for row in reader:
            try:
                row_frame = int((row.get(frame_field) or "").strip())
            except ValueError:  # nosec B112 - skip invalid item and continue scanning remaining records
                continue
            if row_frame != int(frame_index):
                continue
            lat = parse_optional_float(row.get("aligned_latitude"))
            lon = parse_optional_float(row.get("aligned_longitude"))
            if lat is None or lon is None:
                lat = parse_optional_float(row.get("latitude"))
                lon = parse_optional_float(row.get("longitude"))
            if lat is None or lon is None:
                return None
            return {
                "latitude": lat,
                "longitude": lon,
                "source": "frames_csv",
            }
    return None


def neighbor_frames(frames: list[int], current: int) -> tuple[int | None, int | None]:
    """現在フレームに対する前後のマッチ済みフレームを返す。"""
    prev_frame = None
    next_frame = None
    for frame in frames:
        if frame < current:
            prev_frame = frame
        elif frame > current:
            next_frame = frame
            break
    return prev_frame, next_frame


def navigation_payload(video: str, frame_index: int) -> dict[str, Any]:
    """現在フレームに対するWEBビューア用ナビゲーション状態を返す。"""
    frames = load_matched_frames(video)
    prev_frame, next_frame = neighbor_frames(frames, frame_index)
    return {
        "video": video,
        "frame_index": frame_index,
        "prev_frame": prev_frame,
        "next_frame": next_frame,
        "matched_csv_exists": matched_frames_path(video).is_file(),
        "matched_frame_count": len(frames),
        "reference": load_matched_frame_record(video, frame_index),
        "frame_position": load_frame_position_record(video, frame_index),
    }


def exif_ascii(value: Any) -> bytes:
    """EXIF ASCII型のNULL終端バイト列へ変換する。"""
    return str(value or "").encode("ascii", "replace") + b"\x00"


def decimal_to_dms_rationals(value: float) -> list[tuple[int, int]]:
    """十進緯度経度をGPS EXIFの度分秒RATIONAL配列へ変換する。"""
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


def gps_ifd_entries(gps: dict[str, float]) -> list[tuple[int, int, int, Any]]:
    """GPS EXIF IFDに入れる緯度経度・測地系タグを作る。"""
    lat = float(gps["lat"])
    lon = float(gps["lon"])
    return [
        (0x0000, 1, 4, b"\x02\x03\x00\x00"),
        (0x0001, 2, 2, exif_ascii("N" if lat >= 0 else "S")),
        (0x0002, 5, 3, decimal_to_dms_rationals(lat)),
        (0x0003, 2, 2, exif_ascii("E" if lon >= 0 else "W")),
        (0x0004, 5, 3, decimal_to_dms_rationals(lon)),
        (0x0012, 2, 7, exif_ascii("WGS-84")),
    ]


def pack_gps_ifd(entries: list[tuple[int, int, int, Any]], data_offset: int, data: bytearray) -> bytes:
    """GPS IFDをTIFF形式でpackし、可変長データを共有dataへ追加する。"""
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


def minimal_exif_payload(tags: dict[str, Any], gps: dict[str, float] | None = None) -> bytes:
    """ImageDescription/Software/DateTime/GPSだけを持つEXIF payloadを作る。"""
    entries = []
    data = bytearray()

    def add_ascii(tag: int, value: Any) -> None:
        value_bytes = exif_ascii(value)
        entries.append((tag, 2, len(value_bytes), value_bytes))

    def add_long(tag: int, value: int) -> None:
        entries.append((tag, 4, 1, struct.pack("<I", value)))

    add_ascii(0x010E, tags.get("description", "Geo360View snapshot"))
    add_ascii(0x0131, tags.get("software", "Geo360View 360 viewer"))
    add_ascii(0x0132, tags.get("datetime", ""))
    if gps:
        add_long(0x8825, 0)
    entries.sort(key=lambda item: item[0])

    ifd_offset = 8
    data_offset = ifd_offset + 2 + len(entries) * 12 + 4
    gps_entries = gps_ifd_entries(gps) if gps else []
    if gps_entries:
        data_offset += 2 + len(gps_entries) * 12 + 4

    ifd = bytearray()
    ifd.extend(struct.pack("<H", len(entries)))
    for tag, field_type, count, value_bytes in entries:
        if tag == 0x8825:
            gps_ifd_offset = ifd_offset + 2 + len(entries) * 12 + 4
            ifd.extend(struct.pack("<HHI", tag, field_type, count))
            ifd.extend(struct.pack("<I", gps_ifd_offset))
            continue
        if len(value_bytes) <= 4:
            packed_value = value_bytes.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value_bytes)
        ifd.extend(struct.pack("<HHI", tag, field_type, count))
        ifd.extend(packed_value)
    ifd.extend(struct.pack("<I", 0))
    gps_ifd = pack_gps_ifd(gps_entries, data_offset, data) if gps_entries else b""
    tiff = b"II*\x00" + struct.pack("<I", ifd_offset) + bytes(ifd) + gps_ifd + bytes(data)
    return b"Exif\x00\x00" + tiff


def insert_exif(jpeg_bytes: bytes, exif_payload: bytes) -> bytes:
    """JPEG先頭のSOI直後へAPP1 EXIFセグメントを挿入する。"""
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        return jpeg_bytes
    segment_length = len(exif_payload) + 2
    if segment_length > 65535:
        return jpeg_bytes
    return jpeg_bytes[:2] + b"\xff\xe1" + struct.pack(">H", segment_length) + exif_payload + jpeg_bytes[2:]


def safe_snapshot_name(value: Any, fallback: str = "snapshot") -> str:
    """ファイル名へ入れる識別子を安全なASCII寄り文字列へ正規化する。"""
    text = str(value or fallback).strip()
    text = re.sub(r"[^\w.-]+", "_", text, flags=re.ASCII).strip("._")
    return text[:80] or fallback


def snapshot_dir() -> Path:
    """QGIS出力先のsnapshotsディレクトリを返す。"""
    cfg = load_config()
    return cfg["session_json_path"].resolve().parent / "snapshots"


def decode_snapshot_image(data_url: Any) -> bytes:
    """data:image/jpeg;base64,... 形式のキャプチャ画像をJPEG bytesへ変換する。"""
    text = str(data_url or "")
    prefix = "data:image/jpeg;base64,"
    if not text.startswith(prefix):
        raise ApiError(400, "snapshot image must be a JPEG data URL")
    try:
        jpeg_bytes = base64.b64decode(text[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(400, "snapshot image is not valid base64")
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        raise ApiError(400, "snapshot image is not a JPEG")
    return jpeg_bytes


def snapshot_gps(
    payload: dict[str, Any],
    frame_position: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """EXIF GPSへ入れる撮影点座標を決める。"""
    candidates = [
        frame_position or {},
        payload.get("frame_position") if isinstance(payload.get("frame_position"), dict) else {},
        payload,
    ]
    for item in candidates:
        try:
            lat_value = item.get("latitude")
            if lat_value in (None, ""):
                lat_value = item.get("lat")
            lon_value = item.get("longitude")
            if lon_value in (None, ""):
                lon_value = item.get("lon")
            lat = parse_optional_float(lat_value)
            lon = parse_optional_float(lon_value)
        except AttributeError:  # nosec B112 - skip invalid item and continue scanning remaining records
            continue
        if lat is not None and lon is not None:
            return {
                "lat": lat,
                "lon": lon,
                "source": item.get("source", "snapshot_payload"),
            }
    return None


def validate_frame_position_payload(payload: Any) -> dict[str, Any] | None:
    """QGIS/ブラウザから受け取った現在フレーム座標を検証する。"""
    if not isinstance(payload, dict):
        return None
    lat = parse_optional_float(payload.get("latitude"))
    lon = parse_optional_float(payload.get("longitude"))
    if lat is None or lon is None:
        lat = parse_optional_float(payload.get("lat"))
        lon = parse_optional_float(payload.get("lon"))
    if lat is None or lon is None:
        return None
    return {
        "latitude": lat,
        "longitude": lon,
        "source": str(payload.get("source") or "payload"),
    }


def save_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """ブラウザから送られた現在表示JPEGをsnapshotsへ保存する。"""
    video = safe_video_name(str(payload.get("video", "")))
    frame_index = parse_frame_index(payload.get("frame_index"))
    jpeg_bytes = decode_snapshot_image(payload.get("image_data"))
    reference = payload.get("reference") if isinstance(payload.get("reference"), dict) else None
    if reference is None:
        reference = load_matched_frame_record(video, frame_index)
    frame_position = validate_frame_position_payload(payload.get("frame_position"))
    if frame_position is None:
        frame_position = load_frame_position_record(video, frame_index)
    gps = snapshot_gps(payload, frame_position)
    now = datetime.now().astimezone()
    description = json.dumps({
        "app": "Geo360View",
        "video": video,
        "frame_index": frame_index,
        "reference": reference,
        "frame_position": frame_position,
        "gps_source": gps.get("source") if gps else None,
        "view": {
            "yaw_to_camera_heading": payload.get("yaw_to_camera_heading"),
            "pitch": payload.get("pitch"),
            "zoom": payload.get("zoom"),
            "viewer_projection": payload.get("viewer_projection"),
        },
    }, ensure_ascii=True, separators=(",", ":"))[:60000]
    jpeg_bytes = insert_exif(
        jpeg_bytes,
        minimal_exif_payload(
            {
                "description": description,
                "software": "Geo360View 360 viewer",
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            },
            gps=gps,
        ),
    )
    label = safe_snapshot_name((reference or {}).get("label"), "ref")
    filename = f"{safe_snapshot_name(Path(video).stem)}_frame{frame_index:06d}_{label}_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
    path = snapshot_dir() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_bytes(jpeg_bytes)
    os.replace(tmp_path, path)
    return {
        "path": str(path),
        "filename": filename,
        "gps_written": bool(gps),
        "gps_source": gps.get("source") if gps else None,
        "reference": reference,
        "frame_position": frame_position,
    }


def read_session() -> dict[str, Any]:
    """viewer_session.jsonを読み込む。壊れている場合は空状態として扱う。"""
    cfg = load_config()
    path = cfg["session_json_path"]
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_command() -> dict[str, Any]:
    """QGISからビューアへ送る表示指示JSONを読み込む。"""
    cfg = load_config()
    path = cfg["command_json_path"]
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_state_file(path: Path, state: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """ビューア状態JSONを指定パスへ原子的に書き込む。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["viewer_camera_height_m"] = normalize_camera_height(
        state.get("viewer_camera_height_m"),
        cfg["viewer_camera_height_m"],
    )
    state["viewer_hud_height_scale"] = normalize_hud_height_scale(
        state.get("viewer_hud_height_scale"),
        cfg["viewer_hud_height_scale"],
    )
    state["viewer_psv_min_fov_deg"] = normalize_fov_deg(
        state.get("viewer_psv_min_fov_deg"),
        cfg["viewer_psv_min_fov_deg"],
    )
    state["viewer_psv_max_fov_deg"] = normalize_fov_deg(
        state.get("viewer_psv_max_fov_deg"),
        cfg["viewer_psv_max_fov_deg"],
    )
    state["updated_at"] = now_iso()

    # QGIS側ポーリングが途中書き込みを読まないよう、一時ファイルから置換する。
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
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
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as e:
            _geo360_ignored_error = e
    return state


def write_session(state: dict[str, Any]) -> dict[str, Any]:
    """ブラウザの現在状態をviewer_session.jsonへ原子的に書き込む。"""
    cfg = load_config()
    return write_state_file(cfg["session_json_path"], state, cfg)


def write_command(state: dict[str, Any]) -> dict[str, Any]:
    """QGISからビューアへの表示指示をviewer_command.jsonへ原子的に書き込む。"""
    cfg = load_config()
    return write_state_file(cfg["command_json_path"], state, cfg)


def state_from_request_args(query: dict[str, list[str]], video: str, frame_index: int) -> dict[str, Any]:
    """viewer初回表示URLからセッションへ保存する状態を作る。"""
    cfg = load_config()
    session = read_session()
    view = view_state_from_query(query, session)
    camera_height = normalize_camera_height(
        query_value(query, "viewer_camera_height_m", session.get("viewer_camera_height_m")),
        cfg["viewer_camera_height_m"],
    )
    hud_height_scale = normalize_hud_height_scale(
        query_value(query, "viewer_hud_height_scale", session.get("viewer_hud_height_scale")),
        cfg["viewer_hud_height_scale"],
    )

    return {
        "video": video,
        "frame_index": frame_index,
        "yaw_to_camera_heading": view["yaw_to_camera_heading"],
        "pitch": view["pitch"],
        "zoom": view["zoom"],
        "viewer_camera_height_m": camera_height,
        "viewer_hud_height_scale": hud_height_scale,
        "viewer_projection": normalize_viewer_projection(
            query_value(query, "viewer_projection", session.get("viewer_projection", cfg["viewer_projection"]))
        ),
        "viewer_flat_hfov_deg": normalize_fov_deg(
            query_value(query, "viewer_flat_hfov_deg", session.get("viewer_flat_hfov_deg", cfg["viewer_flat_hfov_deg"])),
            cfg["viewer_flat_hfov_deg"],
        ),
        "viewer_flat_vfov_deg": normalize_fov_deg(
            query_value(query, "viewer_flat_vfov_deg", session.get("viewer_flat_vfov_deg", cfg["viewer_flat_vfov_deg"])),
            cfg["viewer_flat_vfov_deg"],
        ),
        "viewer_psv_min_fov_deg": view["viewer_psv_min_fov_deg"],
        "viewer_psv_max_fov_deg": view["viewer_psv_max_fov_deg"],
    }


def validate_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """ブラウザからPOSTされた視点状態payloadを検証・正規化する。"""
    video = safe_video_name(str(payload.get("video", "")))
    frame_index = parse_frame_index(payload.get("frame_index"))
    state = {
        "video": video,
        "frame_index": frame_index,
        "yaw_to_camera_heading": normalize_yaw(parse_float(payload.get("yaw_to_camera_heading"), "yaw_to_camera_heading")),
        "pitch": parse_float(payload.get("pitch"), "pitch", DEFAULT_VIEW["pitch"]),
        "zoom": parse_float(payload.get("zoom"), "zoom", DEFAULT_VIEW["zoom"]),
        "viewer_camera_height_m": normalize_camera_height(
            payload.get("viewer_camera_height_m"),
            load_config()["viewer_camera_height_m"],
        ),
        "viewer_hud_height_scale": normalize_hud_height_scale(
            payload.get("viewer_hud_height_scale"),
            load_config()["viewer_hud_height_scale"],
        ),
        "viewer_projection": normalize_viewer_projection(payload.get("viewer_projection", load_config()["viewer_projection"])),
        "viewer_flat_hfov_deg": normalize_fov_deg(payload.get("viewer_flat_hfov_deg"), load_config()["viewer_flat_hfov_deg"]),
        "viewer_flat_vfov_deg": normalize_fov_deg(payload.get("viewer_flat_vfov_deg"), load_config()["viewer_flat_vfov_deg"]),
        "viewer_psv_min_fov_deg": normalize_fov_deg(payload.get("viewer_psv_min_fov_deg"), load_config()["viewer_psv_min_fov_deg"]),
        "viewer_psv_max_fov_deg": normalize_fov_deg(payload.get("viewer_psv_max_fov_deg"), load_config()["viewer_psv_max_fov_deg"]),
    }
    if payload.get("viewer_front_offset_deg") is not None:
        try:
            state["viewer_front_offset_deg"] = normalize_signed_yaw(
                parse_float(payload.get("viewer_front_offset_deg"), "viewer_front_offset_deg")
            )
        except ApiError as e:
            _geo360_ignored_error = e
    applied_command_id = str(payload.get("applied_command_id") or "").strip()
    if applied_command_id:
        state["applied_command_id"] = applied_command_id
    if payload.get("viewer_image_loaded") is not None:
        state["viewer_image_loaded"] = bool(payload.get("viewer_image_loaded"))
    frame_position = validate_frame_position_payload(payload.get("frame_position"))
    if frame_position:
        state["frame_position"] = frame_position
    target = validate_target_payload(payload.get("target"))
    if target:
        state["target"] = target
    targets = validate_targets_payload(payload.get("targets"))
    if targets:
        state["targets"] = targets
        if not target:
            state["target"] = targets[-1]
    return state


def normalize_signed_yaw(value: float) -> float:
    """任意角度を-180..180度の符号付きyawへ正規化する。"""
    return (float(value) + 180.0) % 360.0 - 180.0


def validate_target_payload(payload: Any) -> dict[str, Any] | None:
    """ブラウザでクリックされた360空間上の投影ターゲットを検証する。"""
    if not isinstance(payload, dict):
        return None

    try:
        yaw_delta_deg = normalize_signed_yaw(parse_float(payload.get("yaw_delta_deg"), "target.yaw_delta_deg", 0.0))
        pitch_delta_deg = max(-90.0, min(90.0, parse_float(payload.get("pitch_delta_deg"), "target.pitch_delta_deg", 0.0)))
        target_yaw = normalize_yaw(parse_float(payload.get("target_yaw_to_camera_heading"), "target.target_yaw_to_camera_heading"))
        view_yaw = normalize_yaw(parse_float(payload.get("view_yaw_to_camera_heading"), "target.view_yaw_to_camera_heading", target_yaw - yaw_delta_deg))
        view_pitch = max(-90.0, min(90.0, parse_float(payload.get("view_pitch"), "target.view_pitch", 0.0)))
        target_pitch = max(-90.0, min(90.0, parse_float(payload.get("target_pitch_deg"), "target.target_pitch_deg", view_pitch + pitch_delta_deg)))
        view_zoom = max(0.01, parse_float(payload.get("view_zoom"), "target.view_zoom", DEFAULT_VIEW["zoom"]))
    except ApiError:
        return None

    projection = str(payload.get("projection") or "ground_plane")
    if projection not in {"ground_plane", "center_plane", "constant_distance", "direction_only"}:
        projection = "ground_plane"

    quality = str(payload.get("quality") or "")
    if quality not in {"trusted", "usable", "far", "direction_only", "unknown"}:
        quality = ""

    ground_distance_m = None
    if payload.get("ground_distance_m") is not None:
        try:
            parsed_ground_distance_m = parse_float(payload.get("ground_distance_m"), "target.ground_distance_m")
            if math.isfinite(parsed_ground_distance_m) and parsed_ground_distance_m > 0:
                ground_distance_m = max(0.01, min(1000.0, parsed_ground_distance_m))
        except ApiError:
            ground_distance_m = None

    target = {
        "yaw_delta_deg": yaw_delta_deg,
        "pitch_delta_deg": pitch_delta_deg,
        "target_yaw_to_camera_heading": target_yaw,
        "target_pitch_deg": target_pitch,
        "view_yaw_to_camera_heading": view_yaw,
        "view_pitch": view_pitch,
        "view_zoom": view_zoom,
        "projection": projection,
        "x_ratio": 0.5,
        "y_ratio": 0.5,
    }
    for key in ("x_ratio", "y_ratio"):
        if payload.get(key) is None:
            continue
        try:
            ratio = parse_float(payload.get(key), f"target.{key}")
            if math.isfinite(ratio):
                target[key] = max(0.0, min(1.0, ratio))
        except ApiError as e:
            _geo360_ignored_error = e
    if ground_distance_m is not None:
        target["ground_distance_m"] = ground_distance_m
    if quality:
        target["quality"] = quality
    for key in ("map_bearing_deg", "map_target_yaw_to_camera_heading"):
        if payload.get(key) is None:
            continue
        try:
            angle = parse_float(payload.get(key), f"target.{key}")
            if math.isfinite(angle):
                target[key] = normalize_yaw(angle)
        except ApiError as e:
            _geo360_ignored_error = e
    for key in ("target_source", "semantic_class", "review_status", "candidate_id", "viewer_marker"):
        value = payload.get(key)
        if value not in (None, ""):
            target[key] = str(value)
    if payload.get("confidence") is not None:
        try:
            confidence = parse_float(payload.get("confidence"), "target.confidence")
            if math.isfinite(confidence):
                target["confidence"] = max(0.0, min(1.0, confidence))
        except ApiError as e:
            _geo360_ignored_error = e
    try:
        target_id = int(payload.get("id"))
        if target_id > 0:
            target["id"] = target_id
    except (TypeError, ValueError) as e:
        _geo360_ignored_error = e
    try:
        order = int(payload.get("order"))
        if order > 0:
            target["order"] = order
    except (TypeError, ValueError) as e:
        _geo360_ignored_error = e
    return target


def validate_targets_payload(payload: Any) -> list[dict[str, Any]]:
    """複数クリックターゲット配列を検証し、順序IDを補完する。"""
    if not isinstance(payload, list):
        return []

    targets = []
    for item in payload[:MAX_VIEWER_TARGETS]:
        target = validate_target_payload(item)
        if not target:
            continue
        if "id" not in target:
            target["id"] = len(targets) + 1
        if "order" not in target:
            target["order"] = len(targets) + 1
        targets.append(target)
    return targets


def validate_radar_payload(payload: Any) -> dict[str, float] | None:
    """QGISから渡されたビューアHUD用レーダ補助値を検証する。"""
    if not isinstance(payload, dict):
        return None

    try:
        range_m = max(0.1, parse_float(payload.get("range_m"), "radar.range_m"))
        outer_range_m = max(range_m, parse_float(payload.get("outer_range_m"), "radar.outer_range_m", range_m * 2.0))
        base_sector_radius_m = max(0.0, parse_float(payload.get("base_sector_radius_m"), "radar.base_sector_radius_m"))
        calibration_fov_deg = max(1.0, min(179.0, parse_float(payload.get("calibration_fov_deg"), "radar.calibration_fov_deg", 90.0)))
        calibration_distance_m = max(0.1, parse_float(payload.get("calibration_distance_m"), "radar.calibration_distance_m", 5.0))
        manual_scale = max(0.1, parse_float(payload.get("manual_scale"), "radar.manual_scale", 1.0))
        min_sector_radius_m = max(0.0, parse_float(payload.get("min_sector_radius_m"), "radar.min_sector_radius_m", 1.0))
        min_zoom_multiplier = max(0.01, parse_float(payload.get("min_zoom_multiplier"), "radar.min_zoom_multiplier", 0.25))
        max_zoom_multiplier = max(
            min_zoom_multiplier,
            parse_float(payload.get("max_zoom_multiplier"), "radar.max_zoom_multiplier", 8.0)
        )
    except ApiError:
        return None

    return {
        "range_m": range_m,
        "outer_range_m": outer_range_m,
        "base_sector_radius_m": base_sector_radius_m,
        "calibration_fov_deg": calibration_fov_deg,
        "calibration_distance_m": calibration_distance_m,
        "manual_scale": manual_scale,
        "min_sector_radius_m": min_sector_radius_m,
        "min_zoom_multiplier": min_zoom_multiplier,
        "max_zoom_multiplier": max_zoom_multiplier,
    }


def same_video_frame(session: dict[str, Any], video: str, frame_index: int) -> bool:
    """セッション状態が指定video/frameと同一かを安全に判定する。"""
    try:
        return session.get("video") == video and int(session.get("frame_index", -1)) == int(frame_index)
    except (TypeError, ValueError):
        return False


def state_from_navigation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """QGISからのフレーム移動payloadを既存視点状態と合成する。"""
    session = read_session()
    video = safe_video_name(str(payload.get("video", "")))
    frame_index = parse_frame_index(payload.get("frame_index"))

    def view_value(name: str) -> Any:
        """QGISが視点値を送らない場合、直近のブラウザ視点を継承する。"""
        value = payload.get(name)
        if value is None or value == "":
            value = session.get(name, DEFAULT_VIEW[name])
        return value

    state = {
        "command_id": str(payload.get("command_id") or uuid.uuid4().hex),
        "video": video,
        "frame_index": frame_index,
        "yaw_to_camera_heading": normalize_yaw(parse_float(view_value("yaw_to_camera_heading"), "yaw_to_camera_heading")),
        "pitch": parse_float(view_value("pitch"), "pitch", DEFAULT_VIEW["pitch"]),
        "zoom": parse_float(view_value("zoom"), "zoom", DEFAULT_VIEW["zoom"]),
        "viewer_camera_height_m": normalize_camera_height(
            payload.get("viewer_camera_height_m", session.get("viewer_camera_height_m")),
            load_config()["viewer_camera_height_m"],
        ),
        "viewer_hud_height_scale": normalize_hud_height_scale(
            payload.get("viewer_hud_height_scale", session.get("viewer_hud_height_scale")),
            load_config()["viewer_hud_height_scale"],
        ),
        "viewer_projection": normalize_viewer_projection(payload.get("viewer_projection", session.get("viewer_projection", load_config()["viewer_projection"]))),
        "viewer_flat_hfov_deg": normalize_fov_deg(payload.get("viewer_flat_hfov_deg", session.get("viewer_flat_hfov_deg")), load_config()["viewer_flat_hfov_deg"]),
        "viewer_flat_vfov_deg": normalize_fov_deg(payload.get("viewer_flat_vfov_deg", session.get("viewer_flat_vfov_deg")), load_config()["viewer_flat_vfov_deg"]),
        "viewer_psv_min_fov_deg": normalize_fov_deg(payload.get("viewer_psv_min_fov_deg", session.get("viewer_psv_min_fov_deg")), load_config()["viewer_psv_min_fov_deg"]),
        "viewer_psv_max_fov_deg": normalize_fov_deg(payload.get("viewer_psv_max_fov_deg", session.get("viewer_psv_max_fov_deg")), load_config()["viewer_psv_max_fov_deg"]),
    }
    viewer_front_offset = payload.get("viewer_front_offset_deg")
    if viewer_front_offset is None and session.get("video") == video:
        viewer_front_offset = session.get("viewer_front_offset_deg")
    if viewer_front_offset is not None:
        try:
            state["viewer_front_offset_deg"] = normalize_signed_yaw(
                parse_float(viewer_front_offset, "viewer_front_offset_deg")
            )
        except ApiError as e:
            _geo360_ignored_error = e
    radar = validate_radar_payload(payload.get("radar"))
    if radar:
        state["radar"] = radar
    frame_position = validate_frame_position_payload(payload.get("frame_position"))
    if frame_position:
        state["frame_position"] = frame_position
    if "targets" in payload:
        targets = validate_targets_payload(payload.get("targets"))
        state["targets"] = targets
        if targets:
            state["target"] = targets[-1]
    else:
        target = validate_target_payload(payload.get("target"))
        if target:
            state["target"] = target
    return state


def json_bytes(value: Any) -> bytes:
    """JSONレスポンス用のUTF-8バイト列を作る。"""
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def relative_static_path(raw_path: str) -> Path:
    """`/static/...` URLをSTATIC_DIR配下の安全な実ファイルパスへ変換する。"""
    static_name = unquote(raw_path.removeprefix("/static/"))
    path = (STATIC_DIR / static_name).resolve()
    try:
        path.relative_to(STATIC_DIR)
    except ValueError:
        raise ApiError(400, "static file is outside static directory")
    if not path.is_file():
        raise ApiError(404, "static file not found")
    return path


def frame_image_url(video: str, frame_index: int) -> str:
    """指定フレームJPEGのHTTPパスを返す。"""
    return f"/frames/{quote(video)}/{frame_index}.jpg"


def absolute_url(handler: BaseHTTPRequestHandler, path: str) -> str:
    """リクエストHostヘッダを使って絶対URLを作る。"""
    host = handler.headers.get("Host")
    if not host:
        cfg = load_config()
        host = f"{cfg['host']}:{cfg['port']}"
    return f"http://{host}{path}"


def build_viewer_html(
    bootstrap: dict[str, Any],
    krpano_available: bool,
    frame_url: str,
    viewer_engine: str = VIEWER_ENGINE_KRPANO,
    psv_available: bool = False,
) -> bytes:
    """ビューアHTMLを生成し、初期状態をJavaScriptへ埋め込む。"""
    psv_core_js_url = f"/static/vendor/photo-sphere-viewer/core/index.module.js?v={PSV_VENDOR_VERSION}"
    psv_markers_js_url = f"/static/vendor/photo-sphere-viewer/markers-plugin/index.module.js?v={PSV_VENDOR_VERSION}"
    psv_three_js_url = f"/static/vendor/photo-sphere-viewer/three/three.module.js?v={PSV_VENDOR_VERSION}"
    bootstrap_json = json.dumps(bootstrap, ensure_ascii=False).replace("</", "<\\/")
    krpano_script = (
        '  <script src="/static/vendor/krpano/krpano.js"></script>\n'
        if viewer_engine == VIEWER_ENGINE_KRPANO and krpano_available
        else ""
    )
    psv_styles = (
        '  <link rel="stylesheet" href="/static/vendor/photo-sphere-viewer/core/index.css">\n'
        '  <link rel="stylesheet" href="/static/vendor/photo-sphere-viewer/markers-plugin/index.css">\n'
        if viewer_engine == VIEWER_ENGINE_PSV and psv_available
        else ""
    )
    psv_importmap = (
        """  <script type="importmap">
    {
      "imports": {
        "three": "%s",
        "@photo-sphere-viewer/core": "%s",
        "@photo-sphere-viewer/markers-plugin": "%s"
      }
    }
  </script>
""" % (psv_three_js_url, psv_core_js_url, psv_markers_js_url)
        if viewer_engine == VIEWER_ENGINE_PSV and psv_available
        else ""
    )
    viewer_script = (
        f'<script type="module" src="/static/psv_viewer.js?v={PSV_VENDOR_VERSION}"></script>'
        if viewer_engine == VIEWER_ENGINE_PSV
        else '<script src="/static/viewer.js"></script>'
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>360 Viewer PoC</title>
  <link rel="stylesheet" href="/static/viewer.css">
{psv_styles}{psv_importmap}{krpano_script}</head>
<body>
  <main class="viewer-shell">
    <section class="toolbar" aria-label="Viewer controls">
      <button id="prevButton" type="button">Prev</button>
      <button id="nextButton" type="button">Next</button>
      <button id="viewHoldButton" class="view-hold-toggle" type="button" aria-pressed="false">Lock</button>
      <button id="radarHudToggleButton" class="hud-toggle" type="button" aria-expanded="true">HUD</button>
      <button id="snapshotButton" class="snapshot-button" type="button">Save snapshot</button>
      <button id="debugToggleButton" class="debug-toggle" type="button" aria-expanded="false">Log</button>
      <div class="readout">
        <span id="videoLabel"></span>
        <span id="frameLabel"></span>
        <span id="viewLabel"></span>
      </div>
    </section>

    <section class="notice" id="notice" hidden></section>
    <section class="debug-log" id="debugLog" hidden></section>

    <section class="pano-stage">
      <div id="pano"></div>
      <img id="fallbackFrame" data-src="{frame_url}" alt="Extracted 360 frame">
      <svg id="groundRingsOverlay" class="ground-rings-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <path id="groundRingGrid" class="ground-ring-grid" />
        <path id="groundRingOuter" class="ground-ring ground-ring-outer" />
        <path id="groundRingInner" class="ground-ring ground-ring-inner" />
      </svg>
      <svg id="lockGuideOverlay" class="lock-guide-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" hidden>
        <path id="lockGuideBand" class="lock-guide-band" />
        <path id="lockGuideLine" class="lock-guide-line" />
        <circle id="lockGuideEndpoint" class="lock-guide-endpoint" r="5" />
      </svg>
      <div id="clickTargetMarker" class="click-target-marker" hidden></div>
      <div id="referenceOverlay" class="reference-overlay" hidden>
        <div id="referenceOverlayLabel" class="reference-overlay-label"></div>
        <div id="referenceOverlayMeta" class="reference-overlay-meta"></div>
        <div id="referenceOverlayCoords" class="reference-overlay-coords"></div>
      </div>
      <div id="radarHud" class="radar-hud" aria-hidden="true">
        <svg viewBox="0 0 260 118" role="img" aria-label="Viewer range guide">
          <path class="hud-ring hud-ring-outer" d="M 30 104 A 100 100 0 0 1 230 104" />
          <path class="hud-ring hud-ring-inner" d="M 80 104 A 50 50 0 0 1 180 104" />
          <line class="hud-axis" x1="130" y1="104" x2="130" y2="18" />
          <circle class="hud-point" cx="130" cy="64" r="3" />
          <circle class="hud-point" cx="130" cy="24" r="3" />
          <text id="hudRangeLabel" class="hud-label" x="136" y="68">5m</text>
          <text id="hudOuterRangeLabel" class="hud-label" x="136" y="28">10m</text>
          <line id="hudDistanceMarker" class="hud-distance-marker" x1="88" y1="64" x2="172" y2="64" />
          <text id="hudDistanceLabel" class="hud-distance-label" x="130" y="56">-</text>
        </svg>
      </div>
    </section>
  </main>

  <script>
    window.VIEWER_BOOTSTRAP = {bootstrap_json};
  </script>
  {viewer_script}
</body>
</html>
"""
    return html.encode("utf-8")


def build_krpano_xml(
    handler: BaseHTTPRequestHandler,
    video: str,
    frame_index: int,
    view: dict[str, Any] | None = None,
) -> str:
    """krpanoへ渡す単一シーンXMLを生成する。"""
    if view is None:
        view = view_state_from_query({})
    yaw = normalize_yaw(parse_float(view.get("yaw_to_camera_heading"), "yaw_to_camera_heading", DEFAULT_VIEW["yaw_to_camera_heading"]))
    pitch = parse_float(view.get("pitch"), "pitch", DEFAULT_VIEW["pitch"])
    zoom = parse_float(view.get("zoom"), "zoom", DEFAULT_VIEW["zoom"])
    fov = max(1.0, min(179.0, 90.0 / max(zoom, 0.01)))
    projection = normalize_viewer_projection(view.get("viewer_projection"))
    flat_hfov = normalize_fov_deg(view.get("viewer_flat_hfov_deg"), DEFAULT_FLAT_HFOV_DEG)
    flat_vfov = normalize_fov_deg(view.get("viewer_flat_vfov_deg"), DEFAULT_FLAT_VFOV_DEG)
    image_url = html_escape(absolute_url(handler, frame_image_url(video, frame_index)), quote=True)

    if projection == VIEWER_PROJECTION_FLAT:
        # 通常画角フレームはrectilinear画像として固定視点で表示する。
        return f"""<krpano>
  <events onloadcomplete="js(viewerKrpanoLoadComplete());" onloaderror="js(viewerKrpanoLoadError());" />
  <preview type="grid(cube,16,16,512,0x222222,0x444444,0x222222)" />
  <view hlookat="0.000000" vlookat="0.000000" fovtype="HFOV" fov="{flat_hfov:.6f}" limitview="fullrange" />
  <image hfov="{flat_hfov:.6f}" vfov="{flat_vfov:.6f}">
    <flat url="{image_url}" />
  </image>
</krpano>
"""

    # krpanoにはequirectangular JPEGをsphere画像として渡す。
    return f"""<krpano>
  <events onloadcomplete="js(viewerKrpanoLoadComplete());" onloaderror="js(viewerKrpanoLoadError());" />
  <preview type="grid(cube,16,16,512,0x222222,0x444444,0x222222)" />
  <view hlookat="{yaw:.6f}" vlookat="{pitch:.6f}" fov="{fov:.6f}" />
  <image>
    <sphere url="{image_url}" />
  </image>
</krpano>
"""


def viewer_cache_path(video: str, frame_index: int, cfg: dict[str, Any], *, snapshot: bool = False) -> Path:
    """画質設定を含めたビューアJPEGキャッシュパスを作る。"""
    quality = cfg["viewer_snapshot_jpeg_quality"] if snapshot else cfg["viewer_jpeg_quality"]
    max_width = cfg["viewer_snapshot_max_width"] if snapshot else cfg["viewer_max_width"]
    purpose = "snap" if snapshot else "view"
    cache_name = (
        f"{safe_cache_stem(video)}_"
        f"frame_{frame_index:06d}_"
        f"{FRAME_READER_VERSION}_"
        f"{purpose}_"
        f"w{max_width}_"
        f"q{quality}_"
        f"p{1 if cfg['viewer_progressive_jpeg'] else 0}.jpg"
    )
    return cfg["viewer_cache_dir"] / cache_name


def resize_for_viewer(frame: Any, max_width: int, cv2: Any) -> Any:
    """ブラウザ表示用に横幅上限へ縮小する。0以下なら縮小しない。"""
    if max_width <= 0:
        return frame

    height, width = frame.shape[:2]
    if width <= max_width:
        return frame

    scale = max_width / float(width)
    resized_size = (max_width, max(1, int(round(height * scale))))
    return cv2.resize(frame, resized_size, interpolation=cv2.INTER_AREA)


def extract_frame_jpeg(video: str, frame_index: int, *, snapshot: bool = False) -> tuple[bytes, str]:
    """動画から指定フレームをJPEG抽出し、ビューアキャッシュも利用する。"""
    import cv2

    cfg = load_config()
    cache_path = viewer_cache_path(video, frame_index, cfg, snapshot=snapshot)
    if cache_path.is_file():
        return cache_path.read_bytes(), "cache"

    path = video_path(video)
    if not path.is_file():
        raise ApiError(404, f"Video not found: {video}")

    try:
        cap = open_video_capture(path, cv2)
    except RuntimeError as error:
        raise ApiError(422, str(error)) from error
    if not cap.isOpened():
        cap.release()
        raise ApiError(422, f"Failed to open video: {video}")
    try:
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if math.isfinite(frame_count) and frame_count >= 1 and frame_index >= int(frame_count):
            raise ApiError(422, f"Frame {frame_index} is outside the video range (0-{int(frame_count) - 1}): {video}")
        try:
            frame, frame_source = read_video_frame(cap, str(path), frame_index, cv2,
                                                  max_width=cfg["viewer_snapshot_max_width"] if snapshot else cfg["viewer_max_width"])
        except (RuntimeError, ValueError) as error:
            raise ApiError(422, str(error)) from error
    finally:
        cap.release()

    max_width = cfg["viewer_snapshot_max_width"] if snapshot else cfg["viewer_max_width"]
    quality = cfg["viewer_snapshot_jpeg_quality"] if snapshot else cfg["viewer_jpeg_quality"]
    frame = resize_for_viewer(frame, max_width, cv2)
    encode_params = [
        int(cv2.IMWRITE_JPEG_QUALITY),
        int(quality),
    ]
    progressive_flag = getattr(cv2, "IMWRITE_JPEG_PROGRESSIVE", None)
    if progressive_flag is not None and cfg["viewer_progressive_jpeg"]:
        encode_params.extend([int(progressive_flag), 1])

    ok, encoded = cv2.imencode(".jpg", frame, encode_params)
    if not ok:
        raise ApiError(500, "Failed to encode frame as JPEG")

    jpeg_bytes = encoded.tobytes()
    try:
        # キャッシュも一時ファイルから置換し、同時リクエスト時の壊れたJPEGを避ける。
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f"{cache_path.name}.tmp")
        tmp_path.write_bytes(jpeg_bytes)
        os.replace(tmp_path, cache_path)
    except OSError as e:
        print(f"360Viewer cache write failed: {e}")

    return jpeg_bytes, frame_source


class ViewerHandler(BaseHTTPRequestHandler):
    """360ViewerのHTTPエンドポイントを処理するリクエストハンドラ。"""

    server_version = "360ViewerHTTP/1.0"
    debug_log_enabled = False

    def log_message(self, format: str, *args: Any) -> None:
        """標準のHTTPログをQGIS側で見やすい形式にする。"""
        if not self.debug_log_enabled:
            return
        print(f"360Viewer {self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        """ヘルスチェック、ビューアHTML、画像、静的ファイルを返す。"""
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True)

            if parsed.path == "/api/diagnostics":
                self.send_json(collect_environment())
                return

            if parsed.path == "/api/health":
                self.send_json({
                    "app": "360viewer",
                    "status": "ok",
                    "config": str(CONFIG_PATH),
                    "app_path": str(Path(__file__).resolve()),
                    "pid": os.getpid(),
                    "server_build": SERVER_BUILD,
                    "frame_reader": FRAME_READER_VERSION,
                    "owner_token": OWNER_TOKEN,
                })
                return

            if parsed.path == "/":
                self.send_bytes(
                    b"Open /viewer?video=your-video.mp4&frame_index=0",
                    "text/plain; charset=utf-8",
                )
                return

            if parsed.path == "/viewer":
                self.handle_viewer(query)
                return

            if parsed.path == "/krpano-scene.xml":
                self.handle_krpano_scene(query)
                return

            if parsed.path.startswith("/frames/"):
                self.handle_frame_image(parsed.path, query)
                return

            if parsed.path == "/api/session/viewer-state":
                self.send_json(read_session())
                return

            if parsed.path == "/api/session/viewer-command":
                self.send_json(read_command())
                return

            if parsed.path == "/api/navigation":
                video = safe_video_name(query_value(query, "video", ""))
                frame_index = parse_frame_index(query_value(query, "frame_index"))
                self.send_json(navigation_payload(video, frame_index))
                return

            if parsed.path.startswith("/static/"):
                self.handle_static(parsed.path)
                return

            raise ApiError(404, "not found")
        except ApiError as e:
            self.send_api_error(e)
        except Exception as e:
            self.send_api_error(ApiError(500, str(e)))

    def do_POST(self) -> None:
        """ブラウザ/QGISからのセッション状態更新を受け付ける。"""
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/session/viewer-state":
                payload = self.read_json_body()
                previous = read_session()
                state = validate_state_payload(payload)
                preserve_targets = bool(payload.get("_viewer_view_update_only"))
                if (
                    same_video_frame(previous, state["video"], state["frame_index"])
                    and isinstance(previous.get("radar"), dict)
                ):
                    state["radar"] = previous["radar"]
                if (
                    preserve_targets
                    and
                    same_video_frame(previous, state["video"], state["frame_index"])
                    and "target" not in payload
                    and isinstance(previous.get("target"), dict)
                ):
                    state["target"] = previous["target"]
                if (
                    preserve_targets
                    and
                    same_video_frame(previous, state["video"], state["frame_index"])
                    and "targets" not in payload
                    and isinstance(previous.get("targets"), list)
                ):
                    state["targets"] = previous["targets"]
                if (
                    same_video_frame(previous, state["video"], state["frame_index"])
                    and "viewer_camera_height_m" not in payload
                    and previous.get("viewer_camera_height_m") is not None
                ):
                    state["viewer_camera_height_m"] = normalize_camera_height(
                        previous.get("viewer_camera_height_m"),
                        load_config()["viewer_camera_height_m"],
                    )
                if (
                    same_video_frame(previous, state["video"], state["frame_index"])
                    and "viewer_hud_height_scale" not in payload
                    and previous.get("viewer_hud_height_scale") is not None
                ):
                    state["viewer_hud_height_scale"] = normalize_hud_height_scale(
                        previous.get("viewer_hud_height_scale"),
                        load_config()["viewer_hud_height_scale"],
                    )
                if (
                    same_video_frame(previous, state["video"], state["frame_index"])
                    and "viewer_front_offset_deg" not in payload
                    and previous.get("viewer_front_offset_deg") is not None
                ):
                    try:
                        state["viewer_front_offset_deg"] = normalize_signed_yaw(
                            parse_float(previous.get("viewer_front_offset_deg"), "viewer_front_offset_deg")
                        )
                    except ApiError as e:
                        _geo360_ignored_error = e
                state = write_session(state)
                self.send_json(state)
                return

            if parsed.path == "/api/session/navigate":
                payload = self.read_json_body()
                state = write_command(state_from_navigation_payload(payload))
                self.send_json(state)
                return

            if parsed.path == "/api/snapshot":
                payload = self.read_json_body()
                self.send_json(save_snapshot(payload))
                return

            raise ApiError(404, "not found")
        except ApiError as e:
            self.send_api_error(e)
        except Exception as e:
            self.send_api_error(ApiError(500, str(e)))

    def handle_viewer(self, query: dict[str, list[str]]) -> None:
        """`/viewer` を生成し、現在フレームとナビゲーション情報を埋め込む。"""
        session = read_session()
        raw_video = query_value(query, "video") or session.get("video")
        raw_frame = query_value(query, "frame_index", session.get("frame_index"))
        video = safe_video_name(str(raw_video or ""))
        frame_index = parse_frame_index(raw_frame)

        state = state_from_request_args(query, video, frame_index)
        if (
            same_video_frame(session, video, frame_index)
            and isinstance(session.get("radar"), dict)
        ):
            state["radar"] = session["radar"]
        if (
            same_video_frame(session, video, frame_index)
            and isinstance(session.get("target"), dict)
        ):
            state["target"] = session["target"]
        if (
            same_video_frame(session, video, frame_index)
            and isinstance(session.get("targets"), list)
        ):
            state["targets"] = session["targets"]
        state = write_session(state)
        frames = load_matched_frames(video)
        prev_frame, next_frame = neighbor_frames(frames, frame_index)
        reference = load_matched_frame_record(video, frame_index)
        frame_position = load_frame_position_record(video, frame_index)
        if frame_position is None and same_video_frame(session, video, frame_index):
            frame_position = validate_frame_position_payload(session.get("frame_position"))
        video_exists = video_path(video).is_file()
        matched_csv_exists = matched_frames_path(video).is_file()
        krpano_available = KRPANO_JS_PATH.is_file()
        psv_available = photo_sphere_viewer_available()
        requested_engine = normalize_viewer_engine(query_value(query, "engine", VIEWER_ENGINE_KRPANO))
        frame_url = frame_image_url(video, frame_index)
        scene_query_params = (
            f"video={quote(video)}&frame_index={frame_index}"
            f"&yaw_to_camera_heading={state['yaw_to_camera_heading']}"
            f"&pitch={state['pitch']}"
            f"&zoom={state['zoom']}"
            f"&viewer_projection={quote(state['viewer_projection'])}"
            f"&viewer_flat_hfov_deg={state['viewer_flat_hfov_deg']}"
            f"&viewer_flat_vfov_deg={state['viewer_flat_vfov_deg']}"
        )
        scene_query = f"/krpano-scene.xml?{scene_query_params}"
        scene_url = absolute_url(self, scene_query)
        cfg = load_config()

        # bootstrapはviewer.jsがページ初期化時に参照する唯一の初期状態。
        bootstrap = {
            "state": state,
            "prev_frame": prev_frame,
            "next_frame": next_frame,
            "reference": reference,
            "frame_position": frame_position,
            "frame_url": frame_url,
            "scene_url": scene_url,
            "krpano_available": krpano_available,
            "psv_available": psv_available,
            "viewer_engine": requested_engine,
            "matched_csv_exists": matched_csv_exists,
            "video_exists": video_exists,
            "krpano_js_url": "/static/vendor/krpano/krpano.js",
            "psv_core_js_url": f"/static/vendor/photo-sphere-viewer/core/index.module.js?v={PSV_VENDOR_VERSION}",
            "psv_markers_js_url": f"/static/vendor/photo-sphere-viewer/markers-plugin/index.module.js?v={PSV_VENDOR_VERSION}",
            "viewer_camera_height_m": state["viewer_camera_height_m"],
            "viewer_hud_height_scale": state["viewer_hud_height_scale"],
            "viewer_projection": state["viewer_projection"],
            "viewer_flat_hfov_deg": state["viewer_flat_hfov_deg"],
            "viewer_flat_vfov_deg": state["viewer_flat_vfov_deg"],
            "viewer_psv_min_fov_deg": state["viewer_psv_min_fov_deg"],
            "viewer_psv_max_fov_deg": state["viewer_psv_max_fov_deg"],
            "viewer_snapshot_jpeg_quality": cfg["viewer_snapshot_jpeg_quality"],
            "viewer_snapshot_output_scale": cfg["viewer_snapshot_output_scale"],
        }

        self.send_bytes(
            build_viewer_html(
                bootstrap,
                krpano_available,
                frame_url,
                viewer_engine=requested_engine,
                psv_available=psv_available,
            ),
            "text/html; charset=utf-8",
            {"Cache-Control": "no-store"},
        )

    def handle_krpano_scene(self, query: dict[str, list[str]]) -> None:
        """krpanoが読み込むXMLシーンを返す。"""
        video = safe_video_name(query_value(query, "video", ""))
        frame_index = parse_frame_index(query_value(query, "frame_index"))
        xml = build_krpano_xml(self, video, frame_index, view_state_from_query(query))
        self.send_bytes(xml.encode("utf-8"), "application/xml; charset=utf-8")

    def handle_frame_image(self, path: str, query: dict[str, list[str]] | None = None) -> None:
        """`/frames/<video>/<frame>.jpg` を処理し、抽出JPEGを返す。"""
        match = re.match(r"^/frames/([^/]+)/([0-9]+)\.jpg$", path)
        if not match:
            raise ApiError(404, "frame image endpoint not found")

        video = safe_video_name(unquote(match.group(1)))
        frame_index = parse_frame_index(match.group(2))
        cfg = load_config()
        snapshot = query is not None and "snapshot" in query
        jpeg, frame_source = extract_frame_jpeg(video, frame_index, snapshot=snapshot)
        self.send_bytes(
            jpeg,
            "image/jpeg",
            {
                "Cache-Control": "no-store",
                "X-Frame-Index": str(frame_index),
                "X-Video": quote(video),
                "X-JPEG-Quality": str(cfg["viewer_snapshot_jpeg_quality"] if snapshot else cfg["viewer_jpeg_quality"]),
                "X-JPEG-Progressive": "1" if cfg["viewer_progressive_jpeg"] else "0",
                "X-Viewer-Max-Width": str(cfg["viewer_snapshot_max_width"] if snapshot else cfg["viewer_max_width"]),
                "X-Frame-Source": frame_source,
                "X-Snapshot-Source": "1" if snapshot else "0",
            },
        )

    def handle_static(self, path: str) -> None:
        """viewer.css/jsやkrpano.jsなどの静的ファイルを返す。"""
        file_path = relative_static_path(path)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_bytes(file_path.read_bytes(), content_type, {"Cache-Control": "no-store"})

    def read_json_body(self) -> dict[str, Any]:
        """POSTリクエストのJSON object bodyを読み込んで検証する。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "invalid Content-Length")
        if length <= 0:
            raise ApiError(400, "JSON object body is required")

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "invalid JSON body")
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON object body is required")
        return payload

    def send_json(self, value: Any, status: int = 200) -> None:
        """JSONレスポンスを送信する。"""
        self.send_bytes(
            json_bytes(value),
            "application/json; charset=utf-8",
            {
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            status=status,
        )

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        """任意バイト列をHTTPレスポンスとして送信する。"""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_api_error(self, error: ApiError) -> None:
        """ApiErrorをAPI/通常ページそれぞれに合う形式で返す。"""
        status = error.status
        if status not in HTTPStatus._value2member_map_:
            status = 500

        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_json({"error": error.message}, status=status)
            return

        body = f"{status} {HTTPStatus(status).phrase}: {error.message}\n".encode("utf-8")
        self.send_bytes(body, "text/plain; charset=utf-8", status=status)


def stop_on_parent_pipe_close(server, stream):
    """QProcess keeps stdin open; EOF means the owner stopped or disappeared."""
    while stream.read(1):
        pass
    print("360Viewer stopping: owner input pipe closed", flush=True)
    server.shutdown()


def main() -> None:
    """設定を読み、ThreadingHTTPServerで360Viewerを起動する。"""
    config = load_config()
    ViewerHandler.debug_log_enabled = bool(config.get("viewer_debug_log_enabled"))
    server = ThreadingHTTPServer((config["host"], config["port"]), ViewerHandler)
    if os.environ.get("VIEWER_WATCH_STDIN") == "1":
        threading.Thread(target=stop_on_parent_pipe_close,
                         args=(server, sys.stdin.buffer), daemon=True).start()
    print(f"360Viewer serving on http://{config['host']}:{config['port']} "
          f"pid={os.getpid()} build={SERVER_BUILD}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt as e:
        _geo360_ignored_error = e
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
