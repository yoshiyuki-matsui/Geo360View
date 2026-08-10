from __future__ import annotations

"""QGISプラグインから起動される標準ライブラリ製ローカル360Viewerサーバ。"""

import csv
import json
import math
import mimetypes
import os
import re
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from xml.sax.saxutils import escape as xml_escape


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("VIEWER_CONFIG", BASE_DIR / "viewer_config.json"))
STATIC_DIR = BASE_DIR / "static"
KRPANO_JS_PATH = STATIC_DIR / "vendor" / "krpano" / "krpano.js"
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
DEFAULT_FLAT_HFOV_DEG = 70.0
DEFAULT_FLAT_VFOV_DEG = 43.0



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


def normalize_fov_deg(value: Any, default: float) -> float:
    """flat表示用FOVをkrpanoが扱える範囲へ正規化する。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    if not math.isfinite(numeric):
        numeric = float(default)
    return max(1.0, min(179.0, numeric))


def load_config() -> dict[str, Any]:
    """viewer_config JSONを読み、パスと画質設定を正規化して返す。"""
    if not CONFIG_PATH.is_file():
        raise ConfigError(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    video_dir = resolve_config_path(raw.get("video_dir", "sample_videos"))
    session_json_path = resolve_config_path(raw.get("session_json_path", "session.json"))
    viewer_cache_dir = resolve_config_path(raw.get("viewer_cache_dir", "viewer_cache"))

    return {
        "host": raw.get("host", "127.0.0.1"),
        "port": int(raw.get("port", 8181)),
        "video_dir": video_dir,
        "session_json_path": session_json_path,
        "viewer_jpeg_quality": max(1, min(100, int(raw.get("viewer_jpeg_quality", 70)))),
        "viewer_progressive_jpeg": parse_bool(raw.get("viewer_progressive_jpeg", True)),
        "viewer_max_width": max(0, int(raw.get("viewer_max_width", 3072))),
        "viewer_cache_dir": viewer_cache_dir,
        "viewer_camera_height_m": normalize_camera_height(raw.get("viewer_camera_height_m")),
        "viewer_hud_height_scale": normalize_hud_height_scale(raw.get("viewer_hud_height_scale")),
        "viewer_debug_log_enabled": parse_bool(raw.get("viewer_debug_log_enabled", False)),
        "viewer_projection": normalize_viewer_projection(raw.get("viewer_projection")),
        "viewer_flat_hfov_deg": normalize_fov_deg(raw.get("viewer_flat_hfov_deg"), DEFAULT_FLAT_HFOV_DEG),
        "viewer_flat_vfov_deg": normalize_fov_deg(raw.get("viewer_flat_vfov_deg"), DEFAULT_FLAT_VFOV_DEG),
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
    """動画名に対応するKPマッチ済みナビゲーションCSVのパスを返す。"""
    cfg = load_config()
    stem = Path(video).stem
    return (cfg["video_dir"] / f"{stem}_matched_frames.csv").resolve()


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
            except ValueError:
                continue
            if frame >= 0:
                frames.add(frame)
    return sorted(frames)


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


def write_session(state: dict[str, Any]) -> dict[str, Any]:
    """ビューア状態をviewer_session.jsonへ原子的に書き込む。"""
    cfg = load_config()
    path = cfg["session_json_path"]
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
    state["updated_at"] = now_iso()

    # QGIS側ポーリングが途中書き込みを読まないよう、一時ファイルから置換する。
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)
    return state


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
    }
    if payload.get("viewer_front_offset_deg") is not None:
        try:
            state["viewer_front_offset_deg"] = normalize_signed_yaw(
                parse_float(payload.get("viewer_front_offset_deg"), "viewer_front_offset_deg")
            )
        except ApiError:
            pass
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
        x_ratio = max(0.0, min(1.0, parse_float(payload.get("x_ratio"), "target.x_ratio", 0.5)))
        y_ratio = max(0.0, min(1.0, parse_float(payload.get("y_ratio"), "target.y_ratio", 0.5)))
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
        "x_ratio": x_ratio,
        "y_ratio": y_ratio,
        "yaw_delta_deg": yaw_delta_deg,
        "pitch_delta_deg": pitch_delta_deg,
        "target_yaw_to_camera_heading": target_yaw,
        "target_pitch_deg": target_pitch,
        "view_yaw_to_camera_heading": view_yaw,
        "view_pitch": view_pitch,
        "view_zoom": view_zoom,
        "projection": projection,
    }
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
        except ApiError:
            pass
    for key in ("target_source", "semantic_class", "review_status", "candidate_id", "viewer_marker"):
        value = payload.get(key)
        if value not in (None, ""):
            target[key] = str(value)
    if payload.get("confidence") is not None:
        try:
            confidence = parse_float(payload.get("confidence"), "target.confidence")
            if math.isfinite(confidence):
                target["confidence"] = max(0.0, min(1.0, confidence))
        except ApiError:
            pass
    try:
        target_id = int(payload.get("id"))
        if target_id > 0:
            target["id"] = target_id
    except (TypeError, ValueError):
        pass
    try:
        order = int(payload.get("order"))
        if order > 0:
            target["order"] = order
    except (TypeError, ValueError):
        pass
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
    }
    viewer_front_offset = payload.get("viewer_front_offset_deg")
    if viewer_front_offset is None and session.get("video") == video:
        viewer_front_offset = session.get("viewer_front_offset_deg")
    if viewer_front_offset is not None:
        try:
            state["viewer_front_offset_deg"] = normalize_signed_yaw(
                parse_float(viewer_front_offset, "viewer_front_offset_deg")
            )
        except ApiError:
            pass
    radar = validate_radar_payload(payload.get("radar"))
    if radar:
        state["radar"] = radar
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


def build_viewer_html(bootstrap: dict[str, Any], krpano_available: bool, frame_url: str) -> bytes:
    """ビューアHTMLを生成し、初期状態をJavaScriptへ埋め込む。"""
    bootstrap_json = json.dumps(bootstrap, ensure_ascii=False).replace("</", "<\\/")
    krpano_script = (
        '  <script src="/static/vendor/krpano/krpano.js"></script>\n'
        if krpano_available
        else ""
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>360 Viewer PoC</title>
  <link rel="stylesheet" href="/static/viewer.css">
{krpano_script}</head>
<body>
  <main class="viewer-shell">
    <section class="toolbar" aria-label="Viewer controls">
      <button id="prevButton" type="button">Prev</button>
      <button id="nextButton" type="button">Next</button>
      <button id="viewHoldButton" class="view-hold-toggle" type="button" aria-pressed="false">Lock</button>
      <button id="radarHudToggleButton" class="hud-toggle" type="button" aria-expanded="true">HUD</button>
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
  <script src="/static/viewer.js"></script>
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
    image_url = xml_escape(absolute_url(handler, frame_image_url(video, frame_index)))

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


def viewer_cache_path(video: str, frame_index: int, cfg: dict[str, Any]) -> Path:
    """画質設定を含めたビューアJPEGキャッシュパスを作る。"""
    cache_name = (
        f"{safe_cache_stem(video)}_"
        f"frame_{frame_index:06d}_"
        f"w{cfg['viewer_max_width']}_"
        f"q{cfg['viewer_jpeg_quality']}_"
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


def extract_frame_jpeg(video: str, frame_index: int) -> tuple[bytes, str]:
    """動画から指定フレームをJPEG抽出し、ビューアキャッシュも利用する。"""
    import cv2

    cfg = load_config()
    cache_path = viewer_cache_path(video, frame_index, cfg)
    if cache_path.is_file():
        return cache_path.read_bytes(), "cache"

    path = video_path(video)
    if not path.is_file():
        raise ApiError(404, f"Video not found: {video}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ApiError(422, f"Failed to open video: {video}")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
    finally:
        cap.release()

    if not ok or frame is None:
        raise ApiError(422, f"Failed to read frame_index={frame_index} from {video}")

    frame = resize_for_viewer(frame, cfg["viewer_max_width"], cv2)
    encode_params = [
        int(cv2.IMWRITE_JPEG_QUALITY),
        int(cfg["viewer_jpeg_quality"]),
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

    return jpeg_bytes, "decode"


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

            if parsed.path == "/api/health":
                self.send_json({
                    "app": "360viewer",
                    "status": "ok",
                    "config": str(CONFIG_PATH),
                })
                return

            if parsed.path == "/":
                self.send_bytes(
                    b"Open /viewer?video=abc.mp4&frame_index=1234",
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
                self.handle_frame_image(parsed.path)
                return

            if parsed.path == "/api/session/viewer-state":
                self.send_json(read_session())
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
                    except ApiError:
                        pass
                state = write_session(state)
                self.send_json(state)
                return

            if parsed.path == "/api/session/navigate":
                payload = self.read_json_body()
                state = write_session(state_from_navigation_payload(payload))
                self.send_json(state)
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
        video_exists = video_path(video).is_file()
        matched_csv_exists = matched_frames_path(video).is_file()
        krpano_available = KRPANO_JS_PATH.is_file()
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

        # bootstrapはviewer.jsがページ初期化時に参照する唯一の初期状態。
        bootstrap = {
            "state": state,
            "prev_frame": prev_frame,
            "next_frame": next_frame,
            "frame_url": frame_url,
            "scene_url": scene_url,
            "krpano_available": krpano_available,
            "matched_csv_exists": matched_csv_exists,
            "video_exists": video_exists,
            "krpano_js_url": "/static/vendor/krpano/krpano.js",
            "viewer_camera_height_m": state["viewer_camera_height_m"],
            "viewer_hud_height_scale": state["viewer_hud_height_scale"],
            "viewer_projection": state["viewer_projection"],
            "viewer_flat_hfov_deg": state["viewer_flat_hfov_deg"],
            "viewer_flat_vfov_deg": state["viewer_flat_vfov_deg"],
        }

        self.send_bytes(
            build_viewer_html(bootstrap, krpano_available, frame_url),
            "text/html; charset=utf-8",
            {"Cache-Control": "no-store"},
        )

    def handle_krpano_scene(self, query: dict[str, list[str]]) -> None:
        """krpanoが読み込むXMLシーンを返す。"""
        video = safe_video_name(query_value(query, "video", ""))
        frame_index = parse_frame_index(query_value(query, "frame_index"))
        xml = build_krpano_xml(self, video, frame_index, view_state_from_query(query))
        self.send_bytes(xml.encode("utf-8"), "application/xml; charset=utf-8")

    def handle_frame_image(self, path: str) -> None:
        """`/frames/<video>/<frame>.jpg` を処理し、抽出JPEGを返す。"""
        match = re.match(r"^/frames/([^/]+)/([0-9]+)\.jpg$", path)
        if not match:
            raise ApiError(404, "frame image endpoint not found")

        video = safe_video_name(unquote(match.group(1)))
        frame_index = parse_frame_index(match.group(2))
        cfg = load_config()
        jpeg, frame_source = extract_frame_jpeg(video, frame_index)
        self.send_bytes(
            jpeg,
            "image/jpeg",
            {
                "Cache-Control": "no-store",
                "X-Frame-Index": str(frame_index),
                "X-Video": quote(video),
                "X-JPEG-Quality": str(cfg["viewer_jpeg_quality"]),
                "X-JPEG-Progressive": "1" if cfg["viewer_progressive_jpeg"] else "0",
                "X-Viewer-Max-Width": str(cfg["viewer_max_width"]),
                "X-Frame-Source": frame_source,
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


def main() -> None:
    """設定を読み、ThreadingHTTPServerで360Viewerを起動する。"""
    config = load_config()
    ViewerHandler.debug_log_enabled = bool(config.get("viewer_debug_log_enabled"))
    server = ThreadingHTTPServer((config["host"], config["port"]), ViewerHandler)
    print(f"360Viewer serving on http://{config['host']}:{config['port']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
