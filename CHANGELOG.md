# Changelog

This file records user-visible changes for Geo360 View.

## 0.5.6 - Unreleased

### Added

- Add a read-only Python-console environment report covering QGIS and the running Web viewer separately, including OpenCV/FFmpeg build information, CPU count, and library paths, formatted for issue reports. No video decoding or automatic server startup is performed.

### Fixed

- Open all plugin/viewer video captures through a shared FFmpeg opener with at most eight decoder threads on builds supporting `CAP_PROP_N_THREADS` (OpenCV 4.8+). Check the reported thread count and never retry without the limit. Legacy builds retain the existing path with a warning; OpenCV 4.8+ is recommended.
- Identify running viewer servers by their loaded code and owning plugin instance; refuse stale or unrelated servers instead of silently reusing them.
- Stop owned viewer servers on normal QGIS shutdown, with terminate/kill fallback and diagnostics if stopping fails. Parent-input EOF monitoring remains enabled on Linux and is disabled in the Windows comparison candidate.
- Clamp frame-step navigation to the video's final frame and stop further forward navigation at the end.
- Reject out-of-range frame display and extraction requests before changing the current frame.
- Distinguish out-of-range viewer image requests from actual decoding failures.
- Validate OpenCV seek/read positions using the same reader for QGIS previews and the browser viewer. Invalid reads fail explicitly without creating mislabeled images.
- Disable automatic FFmpeg CLI fallback in interactive paths to preserve on-demand navigation latency. FFmpeg extraction remains available only through an explicit diagnostic reader call; it is not a runtime requirement.
- Regenerate preview images created before position validation, and use a new viewer cache generation to avoid reusing incorrectly extracted frames.
- Remove the application-wide keyboard event filter. Handle panel keys in the panel and canvas keys in the existing map tool, avoiding unrelated QGIS receiver conversions through SIP. The user reported that plugin operations and opening the plugin manager no longer crashed with the removal candidate; child-widget keyboard behavior still needs explicit verification.

### Validation

- User confirmed normal 0.5.6 operation on home Ubuntu / QGIS 3.44.7 with OpenCV 4.8.1 and NumPy 1.26.4, without the diagnostic LD_PRELOAD shim. Both QGIS and the viewer load the dedicated headless wheel, which also changes the bundled FFmpeg libraries; this is not an isolated thread-setting comparison.
- User confirmed 0.5.6 operation on Windows QGIS 3.40 and 4.2.2, plus viewer-server shutdown on plugin Exit and normal QGIS exit. The precise cause of the earlier Windows startup problem remains unconfirmed.
- Company Ubuntu / QGIS 3.44.7 with eight CPUs and system OpenCV 4.6.0 works without the diagnostic shim or an FFmpeg CLI installation. This legacy API path cannot enforce the decoder thread limit.
- On company Ubuntu, the user also confirmed that the viewer server stops on plugin Exit and normal QGIS exit.
- On home Ubuntu with OpenCV 4.8.1, the user confirmed viewer-server shutdown on both plugin Exit and normal QGIS exit.
- A subsequent normal launch on home Ubuntu loads system OpenCV 4.6.0 in both processes without the diagnostic shim. Existing cached images display, but a different frame (3933) fails with HTTP 422; cached display must not be treated as successful fresh decoding. The response body for this failure has not yet been captured.
- On Ubuntu / QGIS 3.44, the user confirmed that the failing frame 53671 exceeds the video's reported 53497 frames (valid range 0–53496). OpenCV 4.6.0 uses the FFmpeg backend.
- The user confirmed correct preview and browser frame extraction after restarting a stale viewer server. The published 0.5.5 ZIP is unchanged.
- On the affected Ubuntu machine, a standalone OpenCV seek to 9571 reported a huge negative position and returned the starting scene. FFmpeg CLI extraction at the corresponding time returned the expected scene.
- 115 Python regression tests pass, including startup diagnostics, platform-specific parent-pipe monitoring selection, thread-limited opens, invalid-frame rejection, server identity, and cleanup. Parent-pipe EOF is tested in a subprocess with a substitute network listener; forced-exit recovery remains unverified.
- See the [environment validation record](docs/runtime_validation.ja.md) for evidence and unverified items. Tested ZIP hashes have not yet been captured per environment; final artifact verification and feature-by-feature 0.5.6 checks remain outstanding.

## 0.5.5 - 2026-10-08

### Changed

- Declare QGIS 4 / Qt6 support up to the verified version 4.2.2 with qgisMaximumVersion=4.2.2 while retaining QGIS 3.40 compatibility.
- Use QMetaType field types and Qgis.GeometryType for layer creation and radar overlays.
- Set experimental=False for the regular 0.5.5 release after user validation on QGIS 3.40 and 4.2.2.

### Fixed

- Fix map-click frame selection on Qt6 by reading QgsMapMouseEvent.originalPixelPoint() instead of the removed x()/y() shortcuts.
- Reject non-finite numeric attributes and omit invalid GPS EXIF coordinates so missing Marking geometry does not prevent JPEG saving.
- Report the failing extraction stage and print the full traceback instead of suggesting a video codec problem for every frame-display error.

### Validation

- Added regressions for Qt6 enum handling, field schemas, keyboard events, map clicks, non-finite GPS values, and Marking navigation boundaries; 56 Python unit tests pass.
- The user confirmed that ZIP-installed 0.5.5 runs on Windows with QGIS 4.2.2.
- The user also confirmed Marking creation and saving, view restoration, and snapshot saving on QGIS 4.2.2.
- The user confirmed that tmp.gpkg is created and saved when closing the plugin after video/track alignment.
- After the numeric/GPS fixes, the user confirmed that neither the NaN warning nor the misleading codec message appears during the tested operations.
- The user confirmed operation on QGIS 3.40 with no apparent regressions.
- The user also confirmed 0.5.5 operation on another Ubuntu bare-metal machine; the exact QGIS version and tested operations were not recorded.

## 0.5.4 - 2026-10-06

### Changed

- Removed the remaining Python 2 compatibility aliases from bundled `defusedxml.ElementTree` to clear repository informational lint warnings.

## 0.5.3 - 2026-10-06

### Changed

- Cleaned up informational QGIS repository checks by removing shadowed variable names in frame export code.
- Adjusted bundled `defusedxml` file permissions and local variable names to avoid packaging and lint warnings.

## 0.5.2 - 2026-10-04

### Security

- Replaced standard-library GPX XML parsing with `defusedxml.ElementTree` to satisfy QGIS plugin security checks and reduce XML entity attack risk.
- Removed `xml.sax.saxutils.escape` from the local viewer XML generation path and use safe HTML/XML escaping without importing `xml.sax`.
- Reworked pass-only exception handlers so ignored non-critical cleanup/UI failures are explicit instead of silent `except: pass` patterns.
- Marked intentional skip-on-invalid-record handlers and local-only viewer `urlopen` calls with Bandit `nosec` annotations.
- Replaced fixed-table GeoPackage metadata SQL f-strings with literal SQL constants.

### Changed

- Bundled `defusedxml` with the plugin and documented that users do not need to install it separately.
- Updated Qt/QGIS enum references through compatibility constants to satisfy Qt6 compatibility checks while keeping QGIS 3 / Qt5 support.

## 0.5.0 - 2026-09-29

### Added

- Added viewer-side Marking as a 360-space bookmark workflow.
- Added `Marking` navigation mode for revisiting saved Marking frames.
- Saved Markings to the `geo360_markings` GeoPackage layer with frame, view direction, zoom, and provisional map projection attributes.
- Added Marking creation in both the krpano-compatible viewer path and the Photo Sphere Viewer path.
- Restored saved Marking view direction and zoom when navigating back to a Marking frame.
- Included Marking markers in viewer snapshots, allowing evidence images and GPKG Marking records to be related by `frame`.

### Changed

- Renamed the user-facing clicked-point workflow to Marking, while keeping `click_targets_360` readable as a legacy layer.
- Updated README and manual test documentation around Marking, snapshots, and the public viewer/business-workflow boundary.

## 0.3.0 - 2026-09-04

### Added

- Initial Geo360 View split from the internal GPXVideoProcessor codebase.
- Added Photo Sphere Viewer + MarkersPlugin as the open viewer engine.
- Reused the existing local HTTP API, image cache, and `viewer_session.json` route for the Photo Sphere Viewer path.
- Added target marker display, labels, HUD visibility control, ground range rings, and Lock guide-ray display in the browser viewer.
- Added normal-FOV image support through a 2D fallback viewer with mouse-wheel zoom and drag pan.
- Added Photo Sphere Viewer FOV settings: `viewer_psv_min_fov_deg` and `viewer_psv_max_fov_deg`.
- Added GPS EXIF snapshot saving from the viewer.
- Added reference CSV attributes (`reference_id`, `reference_name`, `reference_label`) to matched outputs.
- Added viewer-side reference overlays for matched reference points.
- Added public README screenshots and Japanese README.
- Added `.gitignore` and removed generated bytecode/runtime files from the repository.

### Changed

- Repositioned the repository as a lightweight QGIS plugin for MP4/GPX synchronization and map-linked visual review.
- Kept POI generation, automatic object detection, semantic clustering, and model-review workflows outside the public Geo360 View scope.
- Set Photo Sphere Viewer as the preferred openly distributable viewer path.

### Notes

- The krpano path remains in the copied code for local compatibility checks, but distribution of krpano runtime files must be handled separately according to its license.
- Photo Sphere Viewer is the preferred path for an openly distributable viewer engine.
