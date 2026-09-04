# Geo360 View

Geo360 View is a QGIS plugin for viewing georeferenced 360-degree and normal field videos on a map.

It aligns an MP4 video with a GPX track, creates frame-by-frame camera points, and opens the selected frame in a browser-based viewer. The plugin is intended as a lightweight review tool: keep the original video as the source of truth, generate only the frame images needed for viewing, and move through the route from QGIS.

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

## Documentation

- [DESIGN.ja.md](DESIGN.ja.md): Japanese design notes.
- [DESIGN.md](DESIGN.md): English design notes.
- [CHANGELOG.md](CHANGELOG.md): release notes.
