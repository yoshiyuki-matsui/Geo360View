# GPXVideoProcessor Design Notes

Last updated: 2026-06-07

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
├── main.py                      QGIS plugin UI and top-level controller
├── constants.py                 Shared plugin constants
├── config.py                    UI input Config dataclasses and pure-Python validation
├── common.py                    CSV, string, timestamp, and naming helpers
├── processor.py                 QThread that generates frame positions from GPX and MP4
├── viewer_controller.py         360Viewer process control and HTTP integration
├── frame_extract.py             Frame extraction, EXIF writing, and QGIS preview display
├── map_tools.py                 QGIS map-click tool
├── messages.py                  User-facing message templates and locale switching
├── radar.py                     viewer_session.json polling and radar overlay drawing
├── exporter.py                  TenkakuNinja Exporter compatibility CLI wrapper
├── kp.py                        KP CSV reader and nearest-neighbor matching
├── exif_utils.py                JPEG EXIF helpers
├── TenkakuNinja/
│   ├── main.py                  Standalone Exporter CLI entry point
│   ├── exporter.py              GeoPackage-filtered evidence frame exporter
│   ├── requirements.txt         Standalone Exporter dependencies
│   ├── README.md                Standalone Exporter usage
│   └── geo_util.py              GPX parsing and frame interpolation helpers
├── 360viewer/
│   ├── app.py                   Local HTTP 360 viewer, standard library server
│   ├── static/viewer.js         Browser-side viewer/session synchronization
│   ├── static/viewer.css        Viewer layout
│   ├── static/vendor/krpano/    krpano runtime location
│   ├── viewer_config.json       Standalone viewer defaults
│   └── requirements.txt         OpenCV only
├── docs/
│   ├── exporter_spec.md         Frame image exporter specification
│   ├── quality_assurance.md     Quality policy, regression tests, and manual checks
│   ├── qgis_manual_test_checklist.md QGIS manual test checklist by feature
│   ├── rader_spec.md            Real-scale radar overlay specification
│   ├── tenkaku_ninja_operations.md TenkakuNinja-derived large JPEG operation notes
│   └── yolo_georeference_spec.md Future YOLO-to-georeference specification notes
├── metadata.txt                 QGIS plugin metadata
├── README.md
└── DESIGN.md
```

The QGIS plugin and the browser viewer are loosely coupled. The QGIS plugin starts the viewer process and sends frame navigation requests through HTTP. The viewer writes its current view state to JSON, and QGIS polls that file to draw a temporary direction/radar overlay without taking over editing tools.

## Python Module Split

`main.py` remains the QGIS plugin entry point and owns menu actions, panel UI wiring, and top-level state. Larger functional areas have been split into focused modules to keep the main file readable while preserving the visible processing flow.

Current responsibilities:

- `processor.py`: background GPX/video frame-position generation.
- `config.py`: pure-Python input validation layer that groups UI values into feature-level Config objects before processing.
- `kp.py`: KP CSV column detection, spatial indexing, and tolerance-based nearest-neighbor matching.
- `viewer_controller.py`: 360Viewer runtime config, QProcess lifecycle, HTTP health checks, and browser launch.
- `frame_extract.py`: single-frame OpenCV extraction, JPEG/EXIF writing, and QGIS panel preview.
- `radar.py`: `viewer_session.json` polling, bearing/FOV calculation, and temporary QGIS radar drawing.
- `map_tools.py`: `Video GPX Points` map-click handling, feature highlighting, and keyboard navigation.
- `common.py`: shared file naming, CSV, numeric, and timestamp helpers.
- `constants.py`: shared plugin constants.
- `exif_utils.py`: JPEG EXIF segment construction and insertion.

The split intentionally avoids excessive fragmentation. QGIS GUI layout and signal wiring stay in `main.py`; process control, image extraction, radar drawing, KP matching, and other clear functional units live in separate mixins/helpers.

## Current Status

As of 2026-06-04, the following behavior has been implemented and checked:

- Non-standard GPX timestamps can be parsed and interpolated to MP4 frame positions.
- The video frame number remains the immutable key while a user-defined frame shift is applied.
- When KP CSV is provided, nearest KP points within tolerance are matched and written to CSV.
- `360ViewerOpen` starts the local WEB viewer from QGIS.
- Clicking a camera point on the QGIS map displays the corresponding 360 frame in the browser.
- The browser swaps frames through krpano `loadpano()` instead of reloading the whole page after the initial load.
- Frame changes preserve the latest `yaw_to_camera_heading`, `pitch`, and `zoom`.
- The WEB viewer writes view state to `viewer_session.json`, and QGIS polls it every 500 ms.
- QGIS draws a temporary radar overlay with fixed-distance range circles, a field-of-view sector, direction line, and perpendicular line.
- The radar overlay uses `QgsRubberBand`, so it does not take over layer selection or map tools used by feature-registration plugins.
- Python responsibilities have been split out of `main.py` into processing, viewer control, frame extraction, radar, KP, and helper modules.
- The plugin panel now uses tabs to separate load/process settings from control/preview operations.
- Radar heading is estimated from the +/-10 frame movement trajectory instead of GPX direction attributes.
- Radar sector depth and the perpendicular distance marker are driven by `CalFOV`, `CalDist`, `Scale`, and the current viewer FOV.
- A clicked point in the WEB viewer can be temporarily projected onto the QGIS map using the calibrated center distance and the clicked yaw angle.
- Real-device data from Insta360 X4 + smartphone remote/GNSS has been tested: Insta360-exported GPX and H.265 MP4 can be loaded directly.
- `config.py` now validates Process, single-frame extraction, navigation, radar, and 360Viewer startup inputs outside QGIS.
- `docs/qgis_manual_test_checklist.md` lists QGIS manual checks by feature.

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

For H.265 MP4 input, the QGIS Python OpenCV build must be able to decode the codec. The development environment has been verified with H.265 MP4 from Insta360 X4.

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

## Plugin Panel UI

The panel uses two tabs to reduce vertical height and make the operation order easier to follow.

### `Load / Process`

This tab follows the full-processing setup order:

- GPX file selection
- MP4 video selection
- KP CSV selection
- Output directory selection
- `Shift` and `KP tol`
- `Process` and progress bar

Each file selector is laid out as one row: label, compact file name, and `Browse` button. The display shows only the basename; the full path is available as a tooltip. Long names are kept on one line and clipped so they do not force the panel wider.

### `Control / Preview`

This tab groups interactive checking and navigation:

- `Frame` number and `Extract`
- `Click Layer` / `Stop Click` / `Follow`
- Current frame, navigation mode, normal step, fast step, and radar `Range` / `Scale` / `CalFOV` / `CalDist` / `Offset`
- QGIS preview information
- QGIS preview image
- `<<`, `<`, `>`, `>>` navigation buttons

The earlier single vertical panel became too tall in QGIS. The current UI separates load settings from controls, keeps related operations on one row, and shortens button labels where the surrounding label already provides context.

## Frame Navigation

The plugin panel provides frame navigation controls based on the current frame:

- `<<`: move backward by the fast step
- `<`: move backward by the normal step
- `>`: move forward by the normal step
- `>>`: move forward by the fast step

Navigation settings:

- `Frame step`: move by frame number.
- `Layer point`: move through the `Video GPX Points` layer generated and retained by GPXVideoProcessor, sorted by `frame`.
- `KP matched CSV`: move through `<video_stem>_matched_frames.csv` sorted by `frame_index`.

`Video GPX Points` is treated as an internal reference layer for 360 image viewing. The plugin keeps the generated layer id and uses it for navigation and click-mode setup, so changing the user's feature-registration target layer does not change the viewer reference layer. The active layer is only used as a fallback before `Process`, when a pre-existing frame layer is being used manually.

The default normal step is `1`; the default fast step is `30`, which corresponds to roughly one second for 30 fps video.

The plugin panel uses an always-on-top window flag so it remains visible during QGIS map operations.

When click mode is active, or when the GPXVideoProcessor panel has focus, keyboard navigation is also available:

- `Left` / `Right`: normal step
- `Shift + Left` / `Shift + Right`: fast step
- `Space`: redisplay the current frame
- `Esc`: stop click mode

Keyboard input is handled by the active map tool and by a QGIS application event filter. Even when another map tool, such as a feature registration tool, is active, navigation keys are accepted while the GPXVideoProcessor panel has focus. Arrow keys inside spin boxes, combo boxes, and text inputs are not intercepted.

QGIS remains the primary navigation source. Browser-side Prev/Next is a supplemental navigation path. When the browser viewer has focus, `Left` / `Right` also moves through Prev/Next frames from `matched_frames.csv`.

When `Follow` is enabled, map clicks, button navigation, and keyboard navigation recenter the QGIS map on the displayed frame point without changing the current zoom level. It is disabled by default to avoid extra map redraw cost during fast viewing.

The browser viewer debug log is collapsed by default and can be shown or hidden with the `Log` toolbar button.

## Processing Flow

1. In the `Load / Process` tab, select a GPX file.
2. Select an MP4 video.
3. Optionally select a KP CSV.
4. Set the output directory, frame shift, and KP tolerance.
5. Run `Process`.
6. The plugin reads GPX points and interpolates positions to video frames.
7. A `Video GPX Points` memory layer is added to QGIS.
8. CSV/JSON outputs are written.
9. In the `Control / Preview` tab, enable `Click Layer`.
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
- `radar`
- `target`
- `updated_at`

QGIS polls this file every 500 ms and draws a temporary radar overlay on the map.

The overlay includes:

- Fixed-distance range circles centered on the camera point.
- A sector that represents the viewer field of view.
- A direction line.
- A perpendicular line at the end of the direction line.

The radar overlay is temporary `QgsRubberBand` drawing. On `Exit` or session cleanup, the plugin hides each rubber band, resets its geometry, removes it from the `QGraphicsScene`, and refreshes the QGIS canvas to avoid stale overlay remnants.

Radar display separates absolute distance from dynamic distance.

### Absolute Distance

The plugin panel's `Range` value is drawn as a fixed map-distance circle. The default is 5 m.

Drawn circles:

- `Range`
- `Range * 2`

With the default value, QGIS draws 5 m and 10 m range circles. These circles are only visual distance references.

### Calibrated Distance

The sector, direction line, and perpendicular end marker use `CalFOV`, `CalDist`, UI `Scale`, and the current browser viewer FOV. The perpendicular end marker acts as the calibrated center-distance marker for the current view.

```text
current_fov = 90 / zoom
fov_ratio = tan(current_fov / 2) / tan(CalFOV / 2)
sector_radius_m = max(1.0, CalDist * Scale * fov_ratio)
```

`CalFOV` is the FOV used at calibration time. `CalDist` is the map distance that the operator decides corresponds to the viewer center line at that FOV. `Use FOV` copies the current viewer FOV into `CalFOV`. The default `Scale` is `1.0`; it is a manual multiplier for human calibration against QGIS measurement. Increasing zoom narrows the field of view and pulls the sector depth and distance marker closer.

### Bearing Offset

If the visual front of a 360 video does not match the travel direction, the plugin panel's `Offset` can correct the radar bearing.

`Offset` means how many clockwise degrees the visual front of the video is rotated from the travel direction estimated from the movement trajectory.

Available values:

- `0deg`
- `90deg`
- `180deg`
- `270deg`

If future source videos guarantee that the visual front is the travel direction, `0deg` should be the standard setting.

### Heading Calculation

For target frame `i`, the plugin uses positions from `i - 10` and `i + 10` where possible. Latitude/longitude deltas are converted to local meter offsets:

```text
dx = east_m
dy = north_m
heading = (atan2(dx, dy) * 180 / pi + 360) % 360
```

`heading` is a GIS bearing where north is 0 degrees and angles increase clockwise.

Near the beginning/end of the frame range, the plugin falls back to the best available before/after or center-to-side vector.

### Fallbacks

To keep the radar stable when GNSS positions jump or the camera is nearly stationary:

- If heading changes by more than 45 degrees from the previous heading during nearby-frame updates, the previous heading is kept.
- If +/-10 frame travel distance is less than 0.5 m, the previous heading is kept.
- Sector depth is clamped to at least 1.0 m so the radar does not disappear when stationary.
- When the user jumps to a distant frame by map click/navigation, the previous-heading clamp is not applied.

### Viewer Bearing and FOV

The viewer's `yaw_to_camera_heading` is treated as a clockwise relative angle from the visual front of the video to the current view direction:

```text
viewer_bearing = (heading + Offset + yaw_to_camera_heading) % 360
```

The field of view is derived from viewer `zoom`:

```text
fov = 90 / zoom
```

FOV controls sector width and the ratio from `CalFOV` to the current calibrated distance. When current FOV equals `CalFOV` and `Scale=1.0`, sector depth equals `CalDist`. The final display depth is clamped to at least 1.0 m.

The WEB viewer also displays a small HUD with 5 m / 10 m-equivalent range guides and a calibrated distance marker that corresponds to the QGIS-side perpendicular marker. This HUD is not exact monocular depth recovery. It gives the image side the same visual distance cue as the map radar, so the operator can estimate distance by comparing it with the 5 m / 10 m guides. The toolbar `HUD` button shows or hides it.

When the operator clicks the image in the WEB viewer, the viewer stores the clicked point's absolute 360 yaw, relative yaw from the clicked-time view center, and clicked-time zoom in `viewer_session.json` as `target`. QGIS projects it as a temporary RubberBand point by taking the calibrated forward distance for the clicked-time FOV, dividing it by `cos(yaw_delta)`, and projecting from the camera point toward `heading + Offset + target_yaw`. This is an experimental map-plane projection aid and does not write to a user feature layer.

When switching to another frame image, the WEB viewer carries the latest `yaw_to_camera_heading`, `pitch`, and `zoom` values into the new frame.

### `images/0000/frame_0000000.jpg`

QGIS preview cache. These images are saved with minimal EXIF metadata.

The QGIS preview cache uses the same 1000-frame subfolder rule and `frame_{frame:07d}.jpg` naming as the Exporter. The `image_path` column in `*_frames.csv` and `*_matched_frames.csv` stores this hierarchical path relative to each CSV file. In the all-frame CSV, `image_path` also represents the planned Exporter location for frames that have not yet been extracted on demand.

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

- Tune `yaw_to_camera_heading` bearing conversion, `Range`, `Scale`, and `Offset` defaults against real operation data.
- Consider adding a maximum sector depth clamp for high-speed sections.
- Add radar overlay visibility, color, and opacity settings.
- Add a dedicated Exporter for full-resolution evidence image export.
- Add OpenCV/ffmpeg frame identity tests using raw pixel hashes.
- Add dependency packaging with fixed wheels for QGIS Python deployment.
