# Device Compatibility Notes

This document records real-device input compatibility confirmed during development.

## Insta360 X4

Confirmed input:

- Camera: Insta360 X4
- Control/GNSS source: smartphone remote / smartphone GNSS
- Video: MP4 encoded as H.265
- Track: GPX exported by Insta360

Result:

- GPXVideoProcessor loaded the Insta360 GPX directly.
- The H.265 MP4 was readable by the current QGIS Python/OpenCV environment.
- With frame shift set to zero, the initial frame/position synchronization was broadly reasonable.

Notes:

- This is different from the in-house GNSS-BeatBox GPX path and confirms that the plugin is not limited to the original custom GPX format.
- H.265 support depends on the OpenCV/codec capabilities in the target QGIS runtime environment.
- Before production use, long-duration synchronization drift and frame extraction consistency should still be verified with representative videos.
