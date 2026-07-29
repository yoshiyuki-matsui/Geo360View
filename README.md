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
- Suggesting `360 / Equirectangular` or `Flat / Normal FOV` from MP4 aspect ratio, while allowing manual projection override per job.
- Preserving browser viewer yaw/pitch/zoom when switching frames.
- Drawing temporary QGIS and 360-viewer distance guides, including 1 m ground-grid helpers.
- Saving and restoring a GPKG work session with camera points, 360 click targets, job metadata, calibration parameters, and picked-point view state.
- Opening the 360 viewer in a dedicated Edge/Chrome app window when available.
- Clearing previous GPX/MP4/KP/Output selections with `New Job` and warning before Process overwrites existing output artifacts.

See [DESIGN.ja.md](DESIGN.ja.md) for the current design, environment assumptions, operating flow, outputs, and known tuning points. [DESIGN.md](DESIGN.md) is the English version. See [CHANGELOG.md](CHANGELOG.md) for version history.

## Navigation mode and scope

The plugin has two navigation controls that work together:

- `Navigation mode`: what the plugin should move through.
- `Scope`: which layer set should be used when the mode is `Detection check`.

Recommended use:

- `Frame step`: move by frame number.
- `Layer point`: follow the `Video GPX Points` layer.
- `Picked point`: follow frames that have 360 click targets.
- `Detection check`: follow POI candidate / cluster layers.
- `KP matched CSV`: follow KP-matched frames if the CSV exists.

For `Detection check`, the `Scope` changes the target set:

- `Active layer`: only the currently active candidate layer.
- `Visible layers`: candidate / cluster layers that are visible in the QGIS layer tree.
- `All candidates`: all loaded candidate / cluster layers.
- `Selected features`: only features selected in QGIS.

In practice, `Active layer` is useful when you want to inspect one class at a time, `Visible layers` is good for the current on-screen set, and `Selected features` is the escape hatch for temporarily narrowed queries or manual selections.
