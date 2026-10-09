"""Read-only environment reports for QGIS and the standalone viewer."""

import configparser
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
from urllib.request import ProxyHandler, build_opener, urlopen


ENVIRONMENT_KEYS = (
    "LD_LIBRARY_PATH", "LD_PRELOAD", "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "OPENCV_FFMPEG_THREADS", "OPENCV_VIDEOIO_PRIORITY_LIST",
    "GEO360_PROBE_THREADS", "DISPLAY", "XDG_SESSION_TYPE",
)
LIBRARY_NAMES = ("libopencv_videoio", "libavcodec", "libavformat", "libavutil", "libswscale")


def collect_environment():
    """Collect this process only; do not open videos or run external programs."""
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "online_cpus": os.cpu_count(),
        "environment": {key: os.environ.get(key) for key in ENVIRONMENT_KEYS},
        "ffmpeg_cli_path": shutil.which("ffmpeg"),
    }
    try:
        parser = configparser.ConfigParser()
        parser.read(Path(__file__).with_name("metadata.txt"), encoding="utf-8")
        report["plugin_version"] = parser.get("general", "version")
    except Exception as error:
        report["plugin_version"] = f"unavailable: {error}"
    try:
        if "qgis.core" not in sys.modules:
            raise ImportError("QGIS is not loaded")
        from qgis.core import Qgis
        from qgis.PyQt.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        report["qgis"] = {"version": Qgis.QGIS_VERSION,
                          "qt": QT_VERSION_STR, "pyqt": PYQT_VERSION_STR}
    except ImportError:
        report["qgis"] = "not loaded in this process"
    try:
        import cv2
        info = {"version": cv2.__version__, "module": cv2.__file__,
                "decoder_thread_api": hasattr(cv2, "CAP_PROP_N_THREADS"),
                "configured_decoder_thread_limit": 8 if hasattr(cv2, "CAP_PROP_N_THREADS") else None,
                "thread_limit_note": "Configured limit, not a measurement of an active decoder."}
        report["opencv"] = info
        try:
            build = cv2.getBuildInformation()
            section = re.search(r"^  Video I/O:.*?(?=^  \S|\Z)", build, re.M | re.S)
            info["video_io_build"] = section.group().strip() if section else "not reported"
            parallel = re.search(r"^\s*Parallel framework:.*$", build, re.M)
            info["parallel_framework"] = parallel.group().strip() if parallel else "not reported"
            info["opencv_processing_threads"] = cv2.getNumThreads()
            info["processing_threads_note"] = "Separate from FFmpeg decoder threads."
            registry = getattr(cv2, "videoio_registry", None)
            if registry is not None:
                info["registered_video_backends"] = [
                    registry.getBackendName(backend) for backend in registry.getBackends()
                ]
        except Exception as error:
            info["details_error"] = str(error)
    except Exception as error:
        report["opencv"] = {"error": str(error)}
    try:
        with open("/proc/self/maps", encoding="utf-8") as mappings:
            report["loaded_video_libraries"] = sorted({
                line.split()[-1] for line in mappings
                if any(name in line for name in LIBRARY_NAMES)
            })
    except OSError:
        report["loaded_video_libraries"] = "unavailable on this platform"
    return report


def collect_viewer_environment(base_url):
    """Inspect the local server without starting or adopting it."""
    report = {"url": base_url}
    for endpoint, key in (("health", "identity"), ("diagnostics", "environment")):
        try:
            with urlopen(f"{base_url}/api/{endpoint}", timeout=1) as response:
                data = response.read(512 * 1024 + 1)
            if len(data) > 512 * 1024:
                raise ValueError("Diagnostic response exceeds size limit")
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            if key == "identity":
                # Do not include the process ownership token in public reports.
                payload = {name: payload.get(name) for name in
                           ("app", "status", "pid", "app_path", "server_build", "frame_reader")}
            report[key] = payload
        except Exception as error:
            report[key] = {"unavailable": str(error)}
    return report


def collect_viewer_startup(plugin):
    """Compare process state and direct HTTP without starting another server."""
    report = {}
    try:
        process = getattr(plugin, "viewer_process", None)
        report["managed_process_running"] = plugin.viewerProcessRunning()
        report["managed_pid"] = int(process.processId()) if process is not None else None
        report["launcher"] = plugin.viewerPythonCommand()
        if process is not None:
            report["process_error"] = process.errorString()
        report["plugin_health_check"] = plugin.viewerHealth()
    except Exception as error:
        report["process_check_error"] = str(error)
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"{plugin.viewerBaseUrl()}/api/health", timeout=1) as response:
            data = response.read(512 * 1024 + 1)
        if len(data) > 512 * 1024:
            raise ValueError("Health response exceeds size limit")
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        report["direct_health"] = {name: payload.get(name) for name in
                                   ("app", "status", "pid", "app_path", "server_build", "frame_reader")}
        report["direct_owner_matches"] = bool(getattr(plugin, "_viewer_owner_token", None)) and (
            payload.get("owner_token") == plugin._viewer_owner_token
        )
    except Exception as error:
        report["direct_health"] = {"unavailable": str(error)}
    return report


def format_environment_report(report):
    """Return a pasteable Markdown report with readable build information."""
    # Work on a copy so formatting never alters the collected evidence.
    data = json.loads(json.dumps(report, ensure_ascii=False))
    builds = []
    for label, environment in (("QGIS / current process", data.get("current_process", {})),
                               ("Web viewer process", data.get("viewer", {}).get("environment", {}))):
        opencv = environment.get("opencv", {})
        if isinstance(opencv, dict) and "video_io_build" in opencv:
            builds.append(f"### {label}: Video I/O\n\n```text\n{opencv.pop('video_io_build')}\n```")
    text = "## Geo360View environment diagnostic\n\n"
    text += "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
    if builds:
        text += "\n\n" + "\n\n".join(builds)
    return text


def print_environment_report():
    """Entry point for the QGIS Python console; also works as a CLI script."""
    report = {"current_process": collect_environment()}
    try:
        from qgis.utils import plugins
        plugin = plugins.get("Geo360View")
        if plugin is None:
            report["viewer"] = {"unavailable": "Geo360View is not enabled"}
        else:
            report["viewer"] = collect_viewer_environment(plugin.viewerBaseUrl())
            report["viewer"]["startup"] = collect_viewer_startup(plugin)
    except ImportError:
        report["viewer"] = {"unavailable": "Run in the QGIS Python console to inspect the viewer"}
    except Exception as error:
        report["viewer"] = {"unavailable": str(error)}
    print(format_environment_report(report))


if __name__ == "__main__":
    print_environment_report()
