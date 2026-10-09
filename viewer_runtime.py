"""Identify the server code loaded by a viewer process at startup."""

import hashlib
import os
from pathlib import Path


def server_build(app_path):
    app_path = Path(app_path)
    digest = hashlib.sha256()
    for path in (app_path, app_path.parent.parent / "video_frames.py",
                 app_path.parent.parent / "viewer_runtime.py"):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def same_path(first, second):
    if not isinstance(first, str) or not isinstance(second, str) or not first or not second:
        return False
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def matching_server(payload, app_path, config_path, token):
    """Only reuse a server launched by this plugin instance with current code."""
    return (
        isinstance(payload, dict)
        and payload.get("app") == "360viewer"
        and payload.get("status") == "ok"
        and same_path(payload.get("app_path"), str(app_path))
        and same_path(payload.get("config"), str(config_path))
        and bool(token)
        and payload.get("owner_token") == token
        and payload.get("server_build") == server_build(app_path)
    )
