# 360 Viewer

OpenCV + Python standard-library HTTP server for frame-linked 360/flat video review.

Geo360 View uses Photo Sphere Viewer as the public viewer path. A
krpano-compatible code path is kept for local compatibility testing, but krpano
runtime files are not bundled.

## Layout

```text
.
├── app.py
├── viewer_config.json
├── session.json
├── static/
│   ├── viewer.css
│   ├── viewer.js
│   ├── psv_viewer.js
│   └── vendor/
│       └── photo-sphere-viewer/
│           ├── core/
│           ├── markers-plugin/
│           └── three/
└── templates/
    └── viewer.html   # kept for reference; app.py renders HTML directly
```

### session.json / viewer_session.json
The configured session file stores the last viewer state so the page and QGIS plugin can restore or monitor it. In standalone mode this defaults to `session.json`; when started from QGIS it is written as `viewer_session.json` under the plugin output directory.

It records the current `video`, `frame_index`, `yaw_to_camera_heading`, `pitch`, `zoom`, job-specific `viewer_camera_height_m`, optional `target`, optional ordered `targets`, and `updated_at` timestamp.

The QGIS plugin polls this file to draw the map radar overlay.

When the viewer is driven from QGIS, the session state may include a `radar`
object. It contains range values used by the browser HUD. The HUD is a visual
distance guide, not exact monocular depth reconstruction: it mirrors the
QGIS-side range marker so operators can compare the current view with the
main range guides and the 1 m dashed auxiliary grid by eye. Use the `HUD`
toolbar button to show or hide the range HUD and ground grid together.
The grid is a ground-surface guide. Compare it with feet, signpost bases, road
markings, curb stones, manholes, or other points on the ground, not with elevated
objects such as sign faces, walls, or overhead wires.

Clicking the panorama stores a `target` object in the session state. Double-clicking
also appends the point to the ordered `targets` list. The target values contain
the clicked 360 yaw/pitch, relative yaw from the view center, and clicked-time
zoom. Browser markers are reprojected from the stored yaw/pitch into the current
view, while QGIS can use the same values with the calibrated radar distance to
draw temporary map-plane projection points and append them to the `360 Click
Targets` memo layer.

## Setup

Install dependencies in the Python environment that will run the viewer. The HTTP server uses the Python standard library; OpenCV is the only runtime dependency for frame extraction.

OpenCV 4.8 or newer with FFmpeg support is recommended. The development version opens videos with `CAP_PROP_N_THREADS=8` and checks the reported decoder thread count. It does not retry a rejected open without the limit. OpenCV 4.6 uses the legacy read path with a warning and cannot enforce this setting. Restart any existing viewer server after changing the Python environment or plugin code.

Ubuntu 24.04 supplied OpenCV 4.6 in our tested environment. For QGIS integration, follow the [dedicated-directory Ubuntu setup](../README.md#opencv-setup-for-ubuntu-2404) and verify both the QGIS and viewer processes load OpenCV 4.8 or newer. A standard desktop launch may continue to load Ubuntu's system package.

```bash
python -m pip install -r requirements.txt
```

Run the viewer:

```bash
python app.py
```

Place your licensed krpano runtime at:

```text
static/vendor/krpano/krpano.js
```

Older krpano runtimes can be used. The viewer sets `basepath` to `static/vendor/krpano/` and uses a same-origin XML scene with absolute frame image URLs.

### Photo Sphere Viewer alternative

Photo Sphere Viewer can be selected with the `engine=psv` query parameter:

```text
http://127.0.0.1:8181/viewer?video=your-video.mp4&frame_index=0&engine=psv
```

The PSV path is designed as a krpano replacement candidate, not as a separate
data model. It reuses the same HTTP endpoints and session JSON:

- `/frames/<video>/<frame_index>.jpg`
- `/api/session/viewer-state`
- `/api/session/viewer-command`
- `/api/navigation`

The browser state remains krpano-compatible. Stored values such as
`yaw_to_camera_heading`, `pitch`, `zoom`, `target`, and `targets` are not changed
for PSV. `psv_viewer.js` converts only at the viewer boundary, for example by
flipping pitch sign when sending view/marker positions into PSV.

Place local npm package files under:

```text
static/vendor/photo-sphere-viewer/
  core/index.module.js
  core/index.css
  markers-plugin/index.module.js
  markers-plugin/index.css
  three/three.module.js
  three/three.core.js
```

`three.core.js` is required because the `three.module.js` build imports it with
a relative `./three.core.js` import.

PSV FOV can be tuned in `viewer_config.json`:

```json
{
  "viewer_psv_min_fov_deg": 20,
  "viewer_psv_max_fov_deg": 179
}
```

Aliases `psv_min_fov_deg`, `psv_max_fov_deg`, `min_fov`, `max_fov`, `minFov`,
and `maxFov` are accepted for local experiments. Values are clamped to
`1..179` because PSV itself clamps FOV values in that range.

Current compatibility notes:

- Equirectangular 360 frames are displayed by Photo Sphere Viewer.
- Target markers are rendered through MarkersPlugin and use existing target
  yaw/pitch values.
- Marker labels show semantic class, confidence, and id when present.
- The `HUD` button toggles range HUD, projected ground rings, markers, labels,
  and the lock guide together.
- `Lock` draws a screen-space direction ray using the current target.
- `Save snapshot` saves the current viewer stage to `snapshots/` beside the
  configured session JSON. The saved JPEG includes visible HUD/target cues
  where possible and writes GPS EXIF from the current frame position when one
  is available. Reference matches remain visible as overlay/footer context.
- Ordinary flat frames are not passed to PSV. They are displayed by the fallback
  image element as a 2D viewer to avoid PSV's panorama loader error.
- Flat-frame markers use stored `x_ratio` / `y_ratio` and support wheel zoom and
  drag pan.
- Ground rings are disabled in flat mode because this fallback has no full 3D
  camera model.

Known differences from the optimized krpano path:

- Frame switching can feel slower because PSV recreates or updates WebGL
  textures through `setPanorama()`.
- Ground-ring scale still needs empirical calibration against road width,
  lane width, and camera height.
- The PSV path is currently an evaluation path for distribution feasibility.
  Keep the krpano path available while performance and calibration are being
  reviewed.

Sample videos are not bundled because 360-degree videos are usually large and
may contain privacy-sensitive information. In normal QGIS use, the plugin
writes a runtime config that points `video_dir` to the selected MP4 folder.

For standalone viewer testing, either set `video_dir` in `viewer_config.json`
to a folder containing your MP4, or start the viewer with a QGIS-generated
runtime config.

```text
your_video_folder/
  route.mp4
  route_matched_frames.csv   # optional Reference-matched navigation file
```

The default `viewer_config.json` uses `"video_dir": "."` only as a safe
standalone fallback. It does not imply that sample videos are bundled.

`<video-stem>_matched_frames.csv` contains only the frames that the viewer can move to. `image_path` is optional and is used by downstream exported-image workflows; Prev/Next navigation only requires `frame_index`.

```csv
frame_index,image_path
1200,images/0001/frame_0001200.jpg
1234,images/0001/frame_0001234.jpg
1290,images/0001/frame_0001290.jpg
1400,images/0001/frame_0001400.jpg
```

## Configuration

`viewer_config.json`:

```json
{
  "host": "127.0.0.1",
  "port": 8181,
  "video_dir": ".",
  "session_json_path": "session.json",
  "viewer_jpeg_quality": 90,
  "viewer_progressive_jpeg": true,
  "viewer_max_width": 3072,
  "viewer_psv_min_fov_deg": 20,
  "viewer_psv_max_fov_deg": 179,
  "viewer_cache_dir": "viewer_cache",
  "viewer_camera_height_m": 1.5,
  "viewer_browser_app_window": true,
  "viewer_browser_path": ""
}
```

Relative paths are resolved from this prototype directory.
`viewer_jpeg_quality` controls the on-the-fly JPEG returned by `/frames/...jpg`; the default is 90 to keep road-surface details readable while remaining practical for local review. `viewer_progressive_jpeg` enables progressive JPEG encoding when the OpenCV build supports it. `viewer_max_width` downsizes extracted frames for interactive viewing; use `0` to keep the original width. `viewer_cache_dir` stores encoded viewer JPEGs so revisited frames do not require MP4 decoding again. `viewer_camera_height_m` is the default camera-center height used for standalone sessions; QGIS jobs store their value in `viewer_session.json`.
When QGIS opens the viewer, `viewer_browser_app_window` tries to launch Edge/Chrome as a standalone app window. `viewer_browser_path` can be set to a specific `msedge.exe` or `chrome.exe` path when automatic detection does not find the browser. If app-window launch fails, QGIS falls back to the system default browser.

## Run

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8181/viewer?video=your-video.mp4&frame_index=0&yaw_to_camera_heading=90&pitch=0&zoom=1
```

When view parameters are specified, the viewer uses them for the initial krpano view. When they are omitted, the viewer restores `yaw_to_camera_heading`, `pitch`, and `zoom` from the session file.

When another frame is loaded through browser navigation, the viewer carries the latest `yaw_to_camera_heading`, `pitch`, and `zoom` into the new frame. When QGIS navigation provides explicit view values, such as `Marking` restore, those values are applied instead.

## Endpoints

```text
GET /viewer?video=your-video.mp4&frame_index=0&yaw_to_camera_heading=90&pitch=0&zoom=1
```

Displays the viewer and writes the initial state to the configured session file.

```text
GET /frames/<video>/<frame_index>.jpg
```

Extracts `frame_index` from the configured video with OpenCV and returns a viewer-optimized JPEG. The image is resized according to `viewer_max_width`, encoded with `viewer_jpeg_quality`, and stored in `viewer_cache_dir` for reuse.

```text
POST /api/session/viewer-state
```

Updates the configured session file.

Example:

```json
{
  "video": "your-video.mp4",
  "frame_index": 0,
  "yaw_to_camera_heading": 90.0,
  "pitch": -10.0,
  "zoom": 1.0
}
```

## Notes

- `frame_index` is zero-based.
- `video` must be a file name under `video_dir`. Paths, `../`, and non-MP4 files are rejected.
- The configured session file is written atomically via a temporary file and rename.
- Prev/Next moves only to frames listed in `<video_stem>_matched_frames.csv`.
- Left/Right arrow keys perform the same Prev/Next navigation while the browser viewer has focus.
- The debug log is collapsed by default. Use the `Log` toolbar button to show or hide it.
- The range HUD is shown by default when QGIS provides radar values. Use `HUD` to show or hide the range HUD and 1 m dashed auxiliary grid together.
- Clicking the panorama marks the clicked screen position and updates `target`; double-clicking appends ordered `targets` as Markings for QGIS-side projection, persistence, and later view restoration.
- If krpano is missing, the page reports the missing file and shows a non-interactive extracted image fallback if the video exists.
