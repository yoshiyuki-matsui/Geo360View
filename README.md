# GPXVideoProcessor

GPXVideoProcessor is a QGIS plugin for synchronizing GPX-derived camera positions with MP4 frame numbers and checking 360-degree video frames on a map.

The current implementation focuses on:

- Reading GPX tracks, including non-standard timestamp formats handled by `TenkakuNinja/geo_util.py`.
- Interpolating GPX positions to video frame numbers.
- Applying a frame shift while keeping the video frame number immutable.
- Creating a `Video GPX Points` memory layer in QGIS.
- Exporting frame-position CSV files and optional KP-matched navigation files.
- Launching a local 360 viewer from QGIS without Flask.
- Showing the selected frame in a browser-based krpano viewer when a map point is clicked.

See [DESIGN.ja.md](DESIGN.ja.md) for the current design, environment assumptions, operating flow, outputs, and known tuning points. [DESIGN.md](DESIGN.md) is the English version.
