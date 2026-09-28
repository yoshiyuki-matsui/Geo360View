# Geo360 View

[Japanese README](README_ja.md)

Geo360 View is a QGIS plugin for reviewing GPX-synchronized 360-degree and normal field videos on a map.

## Japanese-first support

Geo360 View is currently released as a trial version. The primary support language is Japanese.

For installation, usage, operation reports, bug reports, and discussions, please start with the Japanese README:

- [README_ja.md](README_ja.md)
- [Operation report form](https://github.com/yoshiyuki-matsui/Geo360View/issues/new?template=operation-report.yml)
- [Bug report form](https://github.com/yoshiyuki-matsui/Geo360View/issues/new?template=bug-report.yml)
- [GitHub Discussions](https://github.com/yoshiyuki-matsui/Geo360View/discussions)

Reports in English are welcome, but responses may be written in Japanese and/or machine-translated.

It aligns an MP4 video with a GPX track, creates frame-by-frame camera points, and opens selected frames in a browser-based viewer. Optional reference point CSV data can be matched to camera points, so known KP markers, utility poles, bridges, facilities, or inspection points can be reviewed directly against the recorded scene.

Geo360 View is more than a playback viewer. It produces reusable intermediate outputs such as camera-point GeoPackages, matched reference CSV files, cached frame images, and GPS-tagged snapshots.


![Geo360 View Geo360View](docs/images/Geo360Viewe.png)
### OverView
![Geo360 View OverView](docs/images/overview.gif)
### Panel
![Geo360 View panel](docs/images/panel_0.png)
### Shooting Points
![Geo360 View 撮影点](docs/images/point.png)
### 360 HUD Viewer
![Geo360 View 360 HUD Viewer](docs/images/viewer.png)
### Save Snap Shot
![Geo360 View スナップショット保存](docs/images/capture.png)
### EXIF Tag
![Geo360 View EXIF GPS](docs/images/exif.png)

## Features

- Read GPX tracks and interpolate camera positions to MP4 frame numbers.
- Apply a frame shift to align video frames and GNSS positions.
- Create a `Video GPX Points` layer in QGIS.
- Optionally match generated camera points to a reference point CSV, such as KP markers, utility poles, bridges, or facility master points.
- Open a local browser viewer from QGIS.
- Display 360/equirectangular frames and normal-FOV frames.
- Switch frames without exporting the whole video to images.
- Preserve viewer yaw, pitch, and zoom while navigating.
- Show map-side and viewer-side HUD guides for orientation and distance cues.
- Show matched reference attributes as an overlay in the viewer.
- Save GPS-tagged snapshots with optional HUD/reference overlays.
- Save and restore a GeoPackage work session.
- Use Photo Sphere Viewer as the open viewer engine, with a krpano-compatible integration path kept for local evaluation.

## Viewer Engines

Geo360 View currently supports two viewer paths:

- `psv`: Photo Sphere Viewer + MarkersPlugin.
- `krpano`: legacy/local evaluation path.

The Photo Sphere Viewer path reuses the same local HTTP API, image cache, and `viewer_session.json` state as the krpano path. This keeps the QGIS side independent from the browser viewer implementation.

## Scope

This public-oriented plugin is limited to video/GPX synchronization and visual review. Automatic object detection, POI generation, semantic clustering, and model-review workflows are intentionally outside this repository.

## Requirements

- QGIS 3.40 or later.
- QGIS Python with OpenCV (`cv2`) available.
- A browser that can open the local viewer, preferably Edge or Chrome.

## Install

Install the plugin directory into your QGIS Python plugin folder and restart QGIS.

On Windows, the default user plugin folder is typically:

```text
C:\Users\<user>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\Geo360View
```

## OpenCV Setup For Windows/QGIS

If QGIS reports that `cv2` is not available, install OpenCV into the Python environment used by QGIS. Installing OpenCV into a normal Windows Python, Conda, or another virtual environment may not make it available from QGIS.

For OSGeo4W/QGIS on Windows, open **OSGeo4W Shell** from the Start menu and run:

```bash
python -m pip install "opencv-python>=4.8"
python -c "import cv2; print(cv2.__version__)"
```

If the second command prints an OpenCV version, the QGIS Python environment can import `cv2`.

## Input Data

- MP4 video recorded along a route.
- GPX track recorded during the same run.
- Optional reference point CSV with latitude/longitude columns.

For practical performance, copy MP4 files to a local SSD or other local disk
before processing. Reading large MP4 files from NAS, SMB/NFS shares, cloud-sync
folders, or VPN-mounted storage can make frame extraction and viewer navigation
very slow because Geo360 View reads video frames on demand.

Reference CSV files should be saved as UTF-8. When editing with Microsoft Excel, choose `CSV UTF-8 (Comma delimited) (*.csv)`. If Japanese text is garbled, reopen the CSV in a text editor such as Sakura Editor or VS Code and save it again as UTF-8.

Minimal reference CSV example:

```csv
id,name,latitude,longitude
1991,Route A KP:1991,35.97173562,136.2038756
2034,Route A KP:2034,35.97156058,136.2037934
```

`name` is used as the viewer label when present. The matched output also preserves `reference_id`, `reference_name`, and `reference_label` fields.

## Outputs

Geo360 View keeps the original video as the source of truth and writes practical intermediate outputs:

- `Video GPX Points` QGIS layer.
- Frame-position CSV files.
- Reference-matched CSV files.
- Navigation JSON for the local viewer.
- On-demand viewer cache images.
- GPS EXIF snapshots with optional HUD and reference overlays.

For 360-degree videos, cached frame images are equirectangular intermediate images. Snapshots are the human-readable view images generated from the current viewer direction.

## Known Limitations

- Sample video data is not bundled because 360-degree video files are usually large and may contain privacy-sensitive content.
- Network or VPN storage can be much slower than local disks for MP4 access. Local execution with local video files is recommended.
- QGIS 4/Qt 6 compatibility is experimental.
- Snapshot image quality depends on source video quality, cache image resolution, viewer rendering, and JPEG compression.
- The krpano path is kept for local compatibility checks only. Photo Sphere Viewer is the preferred open distribution path.

## Contact

For operation reports and bug reports, please use GitHub Issues:

https://github.com/yoshiyuki-matsui/Geo360View/issues

For questions, usage ideas, and use-case discussions, please use GitHub Discussions:

https://github.com/yoshiyuki-matsui/Geo360View/discussions

Support is primarily provided in Japanese. Reports in English are welcome, but responses may be written in Japanese and/or machine-translated.

For business inquiries, custom workflows, automatic POI generation, object detection, or reporting, contact:

rdcenter.nakashacreative@gmail.com

## License

Geo360 View is licensed under GPL-2.0-or-later to align with QGIS plugin distribution requirements.

Bundled browser-side open source components are distributed under their own licenses:

- Photo Sphere Viewer core: MIT
- Photo Sphere Viewer MarkersPlugin: MIT
- three.js: MIT

krpano is not bundled. If you use the legacy krpano path locally, place your own licensed krpano runtime according to the krpano license.

## Documentation

- [DESIGN.ja.md](DESIGN.ja.md): Japanese design notes.
- [DESIGN.md](DESIGN.md): English design notes.
- [CHANGELOG.md](CHANGELOG.md): release notes.
- [samples/README.md](samples/README.md): sample data policy and input notes.
