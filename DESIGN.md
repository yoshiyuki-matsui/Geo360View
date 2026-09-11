# Geo360 View Design Notes

Last updated: 2026-09-11

## Purpose

Geo360 View is a lightweight QGIS plugin for aligning MP4 videos with GPX tracks and viewing the corresponding frames from camera points on a map.

The public scope is limited to video/position synchronization, camera-point layer creation, optional reference point matching, and visual review in a browser viewer. Automatic object detection, POI generation, semantic clustering, and model-review workflows are intentionally outside this repository.

## Architecture

```text
Geo360View/
├── main.py                      QGIS plugin UI and top-level controller
├── constants.py                 Shared plugin constants
├── config.py                    UI input Config dataclasses and validation
├── common.py                    CSV, string, timestamp, and naming helpers
├── processor.py                 QThread that generates frame positions from GPX and MP4
├── viewer_controller.py         360Viewer process control and HTTP integration
├── frame_extract.py             Frame extraction, EXIF writing, and QGIS preview display
├── map_tools.py                 QGIS map-click tool
├── messages.py                  User-facing message templates and locale switching
├── radar.py                     viewer_session.json polling and radar overlay drawing
├── kp.py                        Reference CSV reader and nearest-neighbor matching
├── exif_utils.py                JPEG EXIF helpers
├── TenkakuNinja/
│   └── geo_util.py              GPX parsing and frame interpolation helpers
├── 360viewer/
│   ├── app.py                   Local HTTP viewer
│   ├── static/viewer.js         krpano-compatible viewer control
│   ├── static/psv_viewer.js     Photo Sphere Viewer control
│   ├── static/viewer.css        Viewer layout
│   ├── static/vendor/           Local vendor files
│   ├── viewer_config.json       Viewer defaults
│   └── requirements.txt         Viewer dependencies
├── docs/                        Manual checks and operation notes
├── tests/                       QGIS-independent unit tests
├── metadata.txt                 QGIS plugin metadata
├── CHANGELOG.md                 Release notes
└── README.md
```

The QGIS plugin and browser viewer are loosely coupled. QGIS starts a local HTTP server and sends frame navigation requests through HTTP. The viewer writes the current frame, view direction, and HUD state to `viewer_session.json`; QGIS polls that file to update temporary map radar overlays.

## Main Flow

1. The user selects an MP4, GPX, optional reference CSV, and output folder.
2. OpenCV reads video FPS and frame count.
3. GPX timestamps are interpolated to video frame numbers.
4. An optional frame shift is applied.
5. QGIS creates the `Video GPX Points` layer.
6. Optional reference point matching writes navigation CSV output.
7. A camera-point click or navigation command opens the corresponding frame in the browser viewer.

## Viewer Engines

The viewer is selected by the `engine` parameter.

- `psv`: Photo Sphere Viewer + MarkersPlugin. This is the preferred public viewer path.
- `krpano`: legacy/local compatibility path. krpano runtime distribution must follow the krpano license.

The Photo Sphere Viewer path reuses the same image cache, HTTP API, and `viewer_session.json` state as the krpano path. QGIS payload semantics stay stable, and viewer-specific coordinate differences are handled only at the browser boundary.

## Projection

Videos are handled as one of the following:

- `sphere`: 360-degree/equirectangular images.
- `flat`: normal-FOV images.

The plugin suggests an initial projection from MP4 aspect ratio and allows manual override. Flat images are not passed to Photo Sphere Viewer as panoramas; they are rendered through a 2D fallback viewer in the same browser page.

## Public Boundary

Geo360View is the open viewer layer.
It lets users validate whether their own MP4, GPX, and reference-point data can be reviewed smoothly in QGIS.

Geo360 View does not include:

- Automatic object detection.
- YOLO/RF-DETR model execution.
- POI candidate generation, aggregation, or management.
- Semantic-class candidate layer review.
- Model comparison and detection review workflows.

Advanced workflows such as automatic object detection, POI generation, multi-frame ray intersection, clustering, and report generation are handled by GPXVideoProcessor and related commercial services.
