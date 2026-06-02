# GPXVideoProcessor Design Notes

Last updated: 2026-06-02

## Purpose

GPXVideoProcessor is a QGIS plugin for synchronizing 360-degree MP4 video frames with position information derived from GPX.

The main use case is field-feature registration support:

- Generate a frame-by-frame position table from GPX and MP4 metadata.
- Apply a frame shift to align video frames and positions.
- Optionally match positions to KP master points.
- Inspect selected camera frames against the map background.
- Let the operator visually confirm intersections, roadside objects, and other features before placing feature points in another QGIS plugin.

This plugin is not intended to export all final evidence images. Full export is expected to be handled by a separate batch Exporter.

## Current Architecture

```text
GPXVideoProcessor/
├── main.py                      QGIS plugin UI, processing, layer creation, viewer process control
├── TenkakuNinja/
│   └── geo_util.py              GPX parsing and frame interpolation helpers
├── 360viewer/
│   ├── app.py                   Local HTTP 360 viewer, standard library server
│   ├── static/viewer.js         Browser-side viewer/session synchronization
│   ├── static/viewer.css        Viewer layout
│   ├── static/vendor/krpano/    krpano runtime location
│   ├── viewer_config.json       Standalone viewer defaults
│   └── requirements.txt         OpenCV only
├── metadata.txt                 QGIS plugin metadata
├── README.md
└── DESIGN.md
```

The QGIS plugin and the browser viewer are loosely coupled. The QGIS plugin starts the viewer process and sends frame navigation requests through HTTP. The viewer writes its current view state to JSON so QGIS can later draw direction/radar overlays without taking over editing tools.

## Runtime Environment

### QGIS

- QGIS minimum version: `3.40` as declared in `metadata.txt`.
- The plugin runs in QGIS Python.
- The plugin should use the QGIS Python environment directly. A separate venv is intentionally avoided.

### Python Dependencies

Required:

- `cv2` / OpenCV

Not required:

- Flask
- pandas
- scipy

The 360 viewer was changed from Flask to Python standard-library `http.server.ThreadingHTTPServer`, so Flask wheels are no longer needed.

### krpano

For interactive 360 viewing, place the licensed krpano runtime here:

```text
GPXVideoProcessor/360viewer/static/vendor/krpano/krpano.js
```

If `krpano.js` is missing, the viewer falls back to a normal extracted equirectangular image.

## QGIS Plugin Menu

The plugin menu and toolbar currently expose:

- `360ViewerOpen`
- `Start`
- `Exit`

### 360ViewerOpen

Starts the local HTTP viewer process and opens the browser.

Important implementation detail:

- QGIS may expose `sys.executable` as `qgis.exe` or `qgis-bin.exe`.
- The plugin avoids launching QGIS recursively by searching for a Python launcher such as `python.exe`, `python3.exe`, or `python-qgis.bat`.

### Start

Opens the synchronization/processing panel and reports whether the viewer server is running.

### Exit

Ends the current plugin session:

- Stops click mode.
- Stops the viewer process started by this plugin.
- Saves generated QGIS memory layers to `tmp.gpkg`.
- Removes generated layers from QGIS.
- Closes the panel and resets plugin state.

Only layers whose IDs were created by this plugin are removed. Other layers with the same name are not targeted.

## Processing Flow

1. Select a GPX file.
2. Select an MP4 video.
3. Optionally select a KP CSV.
4. Set KP tolerance and frame shift.
5. Run `Process`.
6. The plugin reads GPX points and interpolates positions to video frames.
7. A `Video GPX Points` memory layer is added to QGIS.
8. CSV/JSON outputs are written.
9. Enable `Click Current Layer`.
10. Click a point on the `Video GPX Points` layer.
11. The browser viewer displays the corresponding frame.
12. QGIS also creates/loads a local preview JPEG.

## Frame Number Semantics

The video frame number is treated as the immutable key.

- `frame`: video-side frame index, zero-based.
- `source_frame`: GPX interpolation source frame after shift.
- `frame_shift`: configured shift amount.

When a frame shift is applied:

```text
source_frame = frame - frame_shift
```

The `frame` value itself is not changed. This is important because OpenCV/ffmpeg extraction and downstream evidence export should refer to the original video frame number.

## GPX Handling

`TenkakuNinja/geo_util.py` accepts GPX files with non-standard or extended structures.

Supported timestamp patterns include:

- Standard ISO8601 such as `2025-03-24T13:08:49.000Z`
- Timezone offsets such as `+09:00`
- `UTC`, `GMT`, and `JST` suffixes
- Compact date/time forms where supported by the parser
- Namespaced and non-namespaced GPX elements

The processor requires at least two timestamped GPX points.

## KP Matching

KP matching is optional.

Input CSV latitude/longitude column names are auto-detected from common names such as:

- `lat`, `latitude`, `gps_lat`, `y`, `緯度`
- `lon`, `lng`, `longitude`, `gps_lon`, `gps_lng`, `x`, `経度`

KP identifier columns are also auto-detected from names such as:

- `kp`, `kilopost`, `kilo_post`, `name`, `id`, `point`, `測点`, `キロポスト`

Matching uses:

- `QgsSpatialIndex` for nearest neighbor lookup.
- `QgsDistanceArea` with WGS84 for distance measurement.
- A user-defined tolerance in meters.

Example:

- KP interval: 10 m
- Tolerance: 5 m

Matched positions are snapped to KP master coordinates in the exported aligned columns.

## Generated QGIS Layer

Layer name:

```text
Video GPX Points
```

Geometry:

```text
Point, EPSG:4326
```

Fields:

- `frame`
- `source_frame`
- `frame_shift`
- `timestamp`
- `latitude`
- `longitude`

The layer is memory-backed during the session. On `Exit`, generated layers are saved to:

```text
<output_dir>/tmp.gpkg
```

If multiple generated layers exist, they are saved into the same GeoPackage with numbered layer names.

If GeoPackage saving fails, the plugin does not remove the QGIS layers.

## Output Files

Default output directory:

```text
<video_dir>/360view_output
```

Main outputs:

```text
<video_stem>_frames.csv
<video_stem>_navigation.json
<video_stem>_matched_frames.csv
tmp.gpkg
viewer_session.json
viewer_cache/
images/
```

### `<video_stem>_frames.csv`

Frame-by-frame synchronized output.

Columns include:

- `frame`
- `source_frame`
- `frame_shift`
- `timestamp`
- `latitude`
- `longitude`
- `aligned_latitude`
- `aligned_longitude`
- `kp`
- `kp_distance_m`
- `kp_latitude`
- `kp_longitude`
- `kp_match`

### `<video_stem>_matched_frames.csv`

WEB viewer navigation CSV. It is generated when KP matching is used.

The viewer expects at least:

```csv
frame_index
```

The plugin writes this CSV both to the output directory and to the video directory so the viewer can find it.

If this file is missing, the browser displays:

```text
Matched frames CSV is not found. Prev/Next navigation is disabled.
```

This does not prevent direct frame display from QGIS clicks.

### `viewer_session.json`

Stores the browser viewer state:

- `video`
- `frame_index`
- `yaw_to_camera_heading`
- `pitch`
- `zoom`
- `updated_at`

This is intended for future QGIS-side radar/direction display.

### `images/frames_******.jpg`

QGIS preview cache. These images are saved with minimal EXIF metadata.

When created from a clicked QGIS point, GPS EXIF fields are added where latitude/longitude can be resolved.

### `viewer_cache/`

WEB viewer JPEG cache. This is separate from the QGIS preview cache and is optimized for interactive viewing.

Current default:

```json
{
  "viewer_jpeg_quality": 70,
  "viewer_progressive_jpeg": true,
  "viewer_max_width": 3072
}
```

The source 8K frame is resized for the browser viewer before JPEG encoding. This does not affect QGIS preview images or future evidence export.

## 360 Viewer

The local viewer is served by:

```text
GPXVideoProcessor/360viewer/app.py
```

Server:

```text
http://127.0.0.1:8181
```

Important endpoints:

```text
GET  /api/health
GET  /viewer?video=<file.mp4>&frame_index=<frame>
GET  /krpano-scene.xml?video=<file.mp4>&frame_index=<frame>
GET  /frames/<file.mp4>/<frame>.jpg
GET  /api/session/viewer-state
POST /api/session/viewer-state
POST /api/session/navigate
```

The browser does not reload the whole page for each QGIS click once the viewer page is open. It polls session state and calls krpano `loadpano()` to swap scenes in place.

## Performance Notes

Measured during development:

- QGIS-side preview extraction typically completes in about 1 to 2 seconds.
- Browser display initially felt around 4 to 5 seconds with 8K frames.
- After optimizations, total perceived time was around 3 seconds.

Current optimizations:

- WEB viewer JPEG quality default: `70`.
- WEB viewer progressive JPEG enabled where supported.
- WEB viewer max width default: `3072`.
- WEB viewer encoded JPEG cache.
- QGIS click sends browser navigation first, then starts QGIS preview extraction after a short delay.
- Browser uses krpano `loadpano()` instead of full page reload for subsequent frame changes.
- Hidden fallback image is lazy-loaded only when needed to avoid duplicate frame requests.

Further tuning options:

- Lower `viewer_max_width` to `2048` for faster preview.
- Disable or make optional the QGIS-side preview image extraction during click navigation.
- Add prefetching for neighboring frames.
- Keep a persistent OpenCV `VideoCapture` for QGIS preview extraction.
- Batch-export final evidence images outside the plugin.

## Current Limitations

- The browser tab itself is not closed by QGIS `Exit`; only the local server process is stopped.
- `matched_frames.csv` is only available when KP matching output exists.
- krpano runtime is not bundled and must be placed manually because it is licensed software.
- The viewer cache is optimized for visual checking, not evidence preservation.
- OpenCV frame extraction consistency with ffmpeg should be verified before evidence export workflows depend on it.

## Future Work

Planned or likely next steps:

- QGIS-side monitoring of `viewer_session.json`.
- Draw a radar/direction overlay in QGIS from `yaw_to_camera_heading`, `pitch`, and current frame position.
- Keep this overlay independent from layer selection and map tools used by feature-registration plugins.
- Add a dedicated Exporter for full-resolution evidence image export.
- Add OpenCV/ffmpeg frame identity tests using raw pixel hashes.
- Add dependency packaging with fixed wheels for QGIS Python deployment.
