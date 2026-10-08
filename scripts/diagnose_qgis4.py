"""Opt-in QGIS console diagnostics for an unresponsive Geo360View panel.

Run with runpy.run_path, then call start_diagnostics(). Stop with
stop_diagnostics() after reproducing the issue. No OpenCV import is performed.
"""

import faulthandler
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import tempfile


_log = None


def start_diagnostics(timeout=15):
    """Record environment details and all thread stacks every timeout seconds."""
    global _log
    if _log is not None:
        return _log.name
    from qgis.core import Qgis, QgsApplication
    from qgis.PyQt.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    _log = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="geo360view-qgis4-", suffix=".log", delete=False,
    )
    packages = {}
    for name in ("numpy", "opencv-python", "opencv-python-headless", "opencv-contrib-python", "PyQt5", "PyQt6"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    details = {
        "qgis": Qgis.QGIS_VERSION,
        "qt": QT_VERSION_STR,
        "pyqt": PYQT_VERSION_STR,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "profile": QgsApplication.qgisSettingsDirPath(),
        "sys_path": sys.path,
        "packages": packages,
        "environment": {name: os.environ.get(name) for name in (
            "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
        )},
    }
    _log.write(json.dumps(details, ensure_ascii=False, indent=2) + "\n\nThread stacks:\n")
    _log.flush()
    faulthandler.dump_traceback_later(timeout, repeat=True, file=_log)
    print("Geo360View diagnostics:", _log.name)
    print("Reproduce the hang; then call stop_diagnostics().")
    return _log.name


def stop_diagnostics():
    """Cancel the diagnostic timer and close its log without deleting it."""
    global _log
    if _log is None:
        return
    faulthandler.cancel_dump_traceback_later()
    path = Path(_log.name)
    _log.close()
    _log = None
    print("Geo360View diagnostics saved:", path)
