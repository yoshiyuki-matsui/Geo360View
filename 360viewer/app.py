from __future__ import annotations

"""QGISプラグインから起動される標準ライブラリ製ローカル360Viewerサーバ。"""

import csv
import json
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
    }


def resolve_config_path(value: str) -> Path:
    """設定内の相対パスを360viewerディレクトリ基準の絶対パスへ解決する。"""
    path = Path(value)
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

    return {
        "yaw_to_camera_heading": normalize_yaw(
            parse_float(value_for("yaw_to_camera_heading"), "yaw_to_camera_heading", DEFAULT_VIEW["yaw_to_camera_heading"])
        ),
        "pitch": parse_float(value_for("pitch"), "pitch", DEFAULT_VIEW["pitch"]),
        "zoom": parse_float(value_for("zoom"), "zoom", DEFAULT_VIEW["zoom"]),
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
    session = read_session()
    view = view_state_from_query(query, session)

    return {
        "video": video,
        "frame_index": frame_index,
        "yaw_to_camera_heading": view["yaw_to_camera_heading"],
        "pitch": view["pitch"],
        "zoom": view["zoom"],
    }


def validate_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """ブラウザからPOSTされた視点状態payloadを検証・正規化する。"""
    video = safe_video_name(str(payload.get("video", "")))
    frame_index = parse_frame_index(payload.get("frame_index"))
    return {
        "video": video,
        "frame_index": frame_index,
        "yaw_to_camera_heading": normalize_yaw(parse_float(payload.get("yaw_to_camera_heading"), "yaw_to_camera_heading")),
        "pitch": parse_float(payload.get("pitch"), "pitch", DEFAULT_VIEW["pitch"]),
        "zoom": parse_float(payload.get("zoom"), "zoom", DEFAULT_VIEW["zoom"]),
    }


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

    return {
        "video": video,
        "frame_index": frame_index,
        "yaw_to_camera_heading": normalize_yaw(parse_float(view_value("yaw_to_camera_heading"), "yaw_to_camera_heading")),
        "pitch": parse_float(view_value("pitch"), "pitch", DEFAULT_VIEW["pitch"]),
        "zoom": parse_float(view_value("zoom"), "zoom", DEFAULT_VIEW["zoom"]),
    }


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
    image_url = xml_escape(absolute_url(handler, frame_image_url(video, frame_index)))

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

    def log_message(self, format: str, *args: Any) -> None:
        """標準のHTTPログをQGIS側で見やすい形式にする。"""
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
                state = write_session(validate_state_payload(payload))
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

        state = write_session(state_from_request_args(query, video, frame_index))
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
        self.send_bytes(json_bytes(value), "application/json; charset=utf-8", status=status)

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
