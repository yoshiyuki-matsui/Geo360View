# 360 Viewer PoC

OpenCV + Python standard-library HTTP server + krpano based proof of concept for 360 viewer.

## Layout

```text
.
├── app.py
├── make_sample_video.py
├── viewer_config.json
├── session.json
├── sample_videos/
│   ├── abc.mp4
│   └── abc_matched_frames.csv
├── static/
│   ├── viewer.css
│   ├── viewer.js
│   └── vendor/krpano/
│       └── krpano.js   # place your licensed krpano.js here
└── templates/
    └── viewer.html   # kept for reference; app.py renders HTML directly
```

### session.json / viewer_session.json
The configured session file stores the last viewer state so the page and QGIS plugin can restore or monitor it. In standalone mode this defaults to `session.json`; when started from QGIS it is written as `viewer_session.json` under the plugin output directory.

It records the current `video`, `frame_index`, `yaw_to_camera_heading`, `pitch`, `zoom`, and `updated_at` timestamp.

The QGIS plugin polls this file to draw the map radar overlay.

## Setup

Install dependencies in the Python environment that will run the viewer. The HTTP server uses the Python standard library; OpenCV is the only runtime dependency for frame extraction.

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

Put videos and matched-frame CSV files under `video_dir`.

```text
sample_videos/
  abc.mp4
  abc_matched_frames.csv
```

This prototype includes a small generated `abc.mp4` for endpoint testing. Regenerate it if needed:

```bash
python make_sample_video.py
```

`abc_matched_frames.csv` contains only the frames that the viewer can move to. `image_path` is optional and is used by downstream exported-image workflows; Prev/Next navigation only requires `frame_index`.

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
  "video_dir": "sample_videos",
  "session_json_path": "session.json",
  "viewer_jpeg_quality": 70,
  "viewer_progressive_jpeg": true,
  "viewer_max_width": 3072,
  "viewer_cache_dir": "viewer_cache"
}
```

Relative paths are resolved from this prototype directory.
`viewer_jpeg_quality` controls the on-the-fly JPEG returned by `/frames/...jpg`; lower values reduce browser decode and transfer cost. `viewer_progressive_jpeg` enables progressive JPEG encoding when the OpenCV build supports it. `viewer_max_width` downsizes extracted frames for interactive viewing; use `0` to keep the original width. `viewer_cache_dir` stores encoded viewer JPEGs so revisited frames do not require MP4 decoding again.

## Run

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8181/viewer?video=abc.mp4&frame_index=1234&yaw_to_camera_heading=90&pitch=0&zoom=1
```

When view parameters are specified, the viewer uses them for the initial krpano view. When they are omitted, the viewer restores `yaw_to_camera_heading`, `pitch`, and `zoom` from the session file.

When another frame is loaded through browser navigation or QGIS navigation, the viewer carries the latest `yaw_to_camera_heading`, `pitch`, and `zoom` into the new frame.

## Endpoints

```text
GET /viewer?video=abc.mp4&frame_index=1234&yaw_to_camera_heading=90&pitch=0&zoom=1
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
  "video": "abc.mp4",
  "frame_index": 1234,
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
- If krpano is missing, the page reports the missing file and shows a non-interactive extracted image fallback if the video exists.
