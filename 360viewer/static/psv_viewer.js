(async function () {
  /*
   * Photo Sphere Viewer based alternative viewer.
   *
   * This script deliberately runs beside `viewer.js` instead of replacing it.
   * The experiment is to prove that the existing QGIS/session/image-cache
   * contract can drive a non-krpano viewer:
   *
   * - reuse `/frames/...jpg` for on-demand frame images;
   * - reuse `/api/session/...` JSON for QGIS/browser synchronization;
   * - keep stored yaw/pitch/zoom values in the existing krpano-compatible form;
   * - convert only at the PSV API boundary;
   * - use a 2D image fallback for ordinary flat camera frames.
   */
  const bootstrap = window.VIEWER_BOOTSTRAP || {};
  const state = Object.assign({
    video: "",
    frame_index: 0,
    yaw_to_camera_heading: 0,
    pitch: 0,
    zoom: 1,
    viewer_camera_height_m: bootstrap.viewer_camera_height_m,
    viewer_hud_height_scale: bootstrap.viewer_hud_height_scale,
    target: null,
    targets: []
  }, bootstrap.state || {});

  const EXTERNAL_SESSION_POLL_INTERVAL_MS = 300;
  const VIEW_STATE_POST_INTERVAL_MS = 1000;
  const MAX_CLICK_TARGETS = 100;
  const GROUND_GRID_STEP_M = 1;
  const GROUND_RING_SAMPLE_COUNT = 96;
  const GROUND_GRID_SAMPLE_COUNT = 64;
  const DEFAULT_PSV_MIN_FOV_DEG = 20;
  const DEFAULT_PSV_MAX_FOV_DEG = 120;
  const PSV_CORE_JS_URL = bootstrap.psv_core_js_url || "/static/vendor/photo-sphere-viewer/core/index.module.js";
  const PSV_MARKERS_JS_URL = bootstrap.psv_markers_js_url || "/static/vendor/photo-sphere-viewer/markers-plugin/index.module.js";

  let viewer = null;
  let markersPlugin = null;
  let lastAppliedCommandId = String(state.applied_command_id || "");
  let postTimer = null;
  let externalPollTimer = null;
  let statePostIntervalTimer = null;
  let radarHudVisible = true;
  let viewHoldEnabled = false;
  let flatZoom = 1;
  let flatPanX = 0;
  let flatPanY = 0;
  let flatDragging = false;
  let flatDragPointerId = null;
  let flatDragStartX = 0;
  let flatDragStartY = 0;
  let flatDragOriginX = 0;
  let flatDragOriginY = 0;

  const prevButton = document.getElementById("prevButton");
  const nextButton = document.getElementById("nextButton");
  const viewHoldButton = document.getElementById("viewHoldButton");
  const radarHudToggleButton = document.getElementById("radarHudToggleButton");
  const snapshotButton = document.getElementById("snapshotButton");
  const notice = document.getElementById("notice");
  const fallbackFrame = document.getElementById("fallbackFrame");
  const videoLabel = document.getElementById("videoLabel");
  const frameLabel = document.getElementById("frameLabel");
  const viewLabel = document.getElementById("viewLabel");
  const pano = document.getElementById("pano");
  const panoStage = document.querySelector(".pano-stage");
  const groundRingsOverlay = document.getElementById("groundRingsOverlay");
  const groundRingGrid = document.getElementById("groundRingGrid");
  const groundRingOuter = document.getElementById("groundRingOuter");
  const groundRingInner = document.getElementById("groundRingInner");
  const radarHud = document.getElementById("radarHud");
  const hudRangeLabel = document.getElementById("hudRangeLabel");
  const hudOuterRangeLabel = document.getElementById("hudOuterRangeLabel");
  const hudDistanceMarker = document.getElementById("hudDistanceMarker");
  const hudDistanceLabel = document.getElementById("hudDistanceLabel");
  const hudInnerRing = radarHud ? radarHud.querySelector(".hud-ring-inner") : null;
  const hudOuterRing = radarHud ? radarHud.querySelector(".hud-ring-outer") : null;
  const hudPoints = radarHud ? Array.from(radarHud.querySelectorAll(".hud-point")) : [];
  const lockGuideOverlay = document.getElementById("lockGuideOverlay");
  const lockGuideBand = document.getElementById("lockGuideBand");
  const lockGuideLine = document.getElementById("lockGuideLine");
  const lockGuideEndpoint = document.getElementById("lockGuideEndpoint");
  const referenceOverlay = document.getElementById("referenceOverlay");
  const referenceOverlayLabel = document.getElementById("referenceOverlayLabel");
  const referenceOverlayMeta = document.getElementById("referenceOverlayMeta");
  const referenceOverlayCoords = document.getElementById("referenceOverlayCoords");
  const debugLog = document.getElementById("debugLog");
  const debugToggleButton = document.getElementById("debugToggleButton");
  let viewerCameraHeightM = normalizeCameraHeight(state.viewer_camera_height_m);
  let viewerHudHeightScale = normalizeHudHeightScale(state.viewer_hud_height_scale);

  let debugLogVisible = false;
  let navigationState = {
    prev_frame: bootstrap.prev_frame,
    next_frame: bootstrap.next_frame,
    matched_csv_exists: Boolean(bootstrap.matched_csv_exists),
    reference: bootstrap.reference || null,
    frame_position: bootstrap.frame_position || null
  };

  function clamp(value, minValue, maxValue) {
    return Math.max(minValue, Math.min(maxValue, value));
  }

  function normalizeYaw(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return ((numeric % 360) + 360) % 360;
  }

  function normalizeSignedYaw(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return ((numeric + 180) % 360 + 360) % 360 - 180;
  }

  function normalizePitch(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return Math.max(-90, Math.min(90, numeric));
  }

  function normalizeZoom(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return 1;
    }
    return numeric;
  }

  function normalizePsvFov(value, defaultValue) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return defaultValue;
    }
    return clamp(numeric, 1, 179);
  }

  const PSV_MIN_FOV_DEG = normalizePsvFov(bootstrap.viewer_psv_min_fov_deg, DEFAULT_PSV_MIN_FOV_DEG);
  const PSV_MAX_FOV_DEG = Math.max(
    PSV_MIN_FOV_DEG,
    normalizePsvFov(bootstrap.viewer_psv_max_fov_deg, DEFAULT_PSV_MAX_FOV_DEG)
  );

  function normalizeCameraHeight(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return 1.5;
    }
    return clamp(numeric, 0.1, 10);
  }

  function normalizeHudHeightScale(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return 1.0;
    }
    return clamp(numeric, 0.1, 5.0);
  }

  function effectiveHudCameraHeightM() {
    return viewerCameraHeightM * viewerHudHeightScale;
  }

  function degreesToRadians(degrees) {
    return Number(degrees) * Math.PI / 180;
  }

  function radiansToDegrees(radians) {
    return Number(radians) * 180 / Math.PI;
  }

  function krpanoPitchToPsvPitch(pitch) {
    // Session data is shared with the krpano viewer and QGIS, so it keeps the
    // krpano pitch sign. PSV's vertical sign is opposite for view/marker
    // positions. Flip only at this boundary to avoid changing persisted JSON.
    return -normalizePitch(pitch);
  }

  function psvPitchToKrpanoPitch(pitch) {
    // Convert PSV's current view back before posting viewer_session.json.
    return -normalizePitch(pitch);
  }

  function zoomToPsvLevel(zoom) {
    // Existing state stores a krpano-like zoom where fov ~= 90 / zoom.
    // PSV uses a 0..100 zoom level between maxFov and minFov. This mapping is
    // intentionally approximate but stable enough for QGIS navigation, HUD
    // projection, and side-by-side viewer comparison.
    const fov = clamp(90 / normalizeZoom(zoom), PSV_MIN_FOV_DEG, PSV_MAX_FOV_DEG);
    return clamp(((PSV_MAX_FOV_DEG - fov) / (PSV_MAX_FOV_DEG - PSV_MIN_FOV_DEG)) * 100, 0, 100);
  }

  function psvLevelToZoom(level) {
    const normalized = clamp(Number(level), 0, 100);
    const fov = psvLevelToFov(normalized);
    return normalizeZoom(90 / clamp(fov, 1, PSV_MAX_FOV_DEG));
  }

  function psvLevelToFov(level) {
    const normalized = clamp(Number(level), 0, 100);
    return PSV_MAX_FOV_DEG + (normalized / 100) * (PSV_MIN_FOV_DEG - PSV_MAX_FOV_DEG);
  }

  function viewHorizontalFovDeg(viewState) {
    if (isFlatProjection()) {
      // Flat mode is not a PSV camera. Use the configured ordinary-camera HFOV
      // for readout and simple overlay math.
      return clamp(Number(state.viewer_flat_hfov_deg || bootstrap.viewer_flat_hfov_deg || 70) / normalizeZoom(state.zoom), 1, 179);
    }
    if (viewer && typeof viewer.getZoomLevel === "function") {
      return psvLevelToFov(viewer.getZoomLevel());
    }
    return clamp(90 / normalizeZoom(viewState && viewState.zoom), PSV_MIN_FOV_DEG, PSV_MAX_FOV_DEG);
  }

  function formatMeters(value) {
    if (!Number.isFinite(value)) {
      return "-";
    }
    if (value >= 10) {
      return `${value.toFixed(0)}m`;
    }
    return `${value.toFixed(1)}m`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));
  }

  function targetLabel(target, id) {
    const className = target.semantic_class ? String(target.semantic_class) : "";
    const confidence = Number(target.confidence);
    return [
      className,
      Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : "",
      `#${id}`
    ].filter(Boolean).join(" ");
  }

  function clearFlatTargetMarkers() {
    if (!panoStage) {
      return;
    }
    panoStage.querySelectorAll(".psv-flat-target-marker").forEach((marker) => marker.remove());
  }

  function updateFlatTargetMarkers() {
    clearFlatTargetMarkers();
    if (!panoStage || !isFlatProjection() || !radarHudVisible) {
      return;
    }
    const stageRect = panoStage.getBoundingClientRect();
    if (!stageRect.width || !stageRect.height) {
      return;
    }
    displayTargets().slice(0, MAX_CLICK_TARGETS).forEach((target, index) => {
      const point = flatPointFromRatio(target, stageRect);
      if (!point) {
        return;
      }
      const id = String(target.id || target.order || index + 1);
      const markerTypeClass = target.target_source || target.source === "auto"
        ? "click-target-marker-auto"
        : "click-target-marker-saved";
      const marker = document.createElement("div");
      marker.className = `click-target-marker click-target-marker-extra psv-flat-target-marker ${markerTypeClass}`;
      marker.style.left = `${point.x.toFixed(1)}px`;
      marker.style.top = `${point.y.toFixed(1)}px`;
      marker.title = targetLabel(target, id) || `target #${id}`;
      const label = document.createElement("span");
      label.className = "click-target-marker-label";
      label.textContent = marker.title;
      marker.appendChild(label);
      panoStage.appendChild(marker);
    });
  }

  function arcPath(radiusPx) {
    const cx = 130;
    const cy = 104;
    const r = clamp(radiusPx, 1, 100);
    return `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  }

  function isFlatProjection(value) {
    return String(value || state.viewer_projection || "").toLowerCase() === "flat";
  }

  function flatBaseRect(stageRect) {
    // Reconstruct the image rectangle created by `object-fit: contain`.
    // Flat targets are stored as source-image ratios, not screen pixels.
    const naturalWidth = fallbackFrame.naturalWidth || 16;
    const naturalHeight = fallbackFrame.naturalHeight || 9;
    const scale = Math.min(stageRect.width / naturalWidth, stageRect.height / naturalHeight);
    const width = naturalWidth * scale;
    const height = naturalHeight * scale;
    return {
      left: (stageRect.width - width) / 2,
      top: (stageRect.height - height) / 2,
      width,
      height
    };
  }

  function flatImageRect(stageRect) {
    const base = flatBaseRect(stageRect);
    const centerX = stageRect.width / 2 + flatPanX;
    const centerY = stageRect.height / 2 + flatPanY;
    const width = base.width * flatZoom;
    const height = base.height * flatZoom;
    return {
      left: centerX - width / 2,
      top: centerY - height / 2,
      width,
      height
    };
  }

  function flatPointFromRatio(target, stageRect) {
    const xRatio = Number(target && target.x_ratio);
    const yRatio = Number(target && target.y_ratio);
    if (!Number.isFinite(xRatio) || !Number.isFinite(yRatio)) {
      return null;
    }
    const rect = flatImageRect(stageRect);
    return {
      x: rect.left + clamp(xRatio, 0, 1) * rect.width,
      y: rect.top + clamp(yRatio, 0, 1) * rect.height
    };
  }

  function applyFlatTransform() {
    // CSS-transform the image and then place markers from the same transformed
    // rectangle. This keeps target labels attached during wheel zoom and drag.
    if (!fallbackFrame) {
      return;
    }
    fallbackFrame.style.transform = `translate(${flatPanX.toFixed(1)}px, ${flatPanY.toFixed(1)}px) scale(${flatZoom.toFixed(4)})`;
    fallbackFrame.style.transformOrigin = "center center";
    updateFlatTargetMarkers();
    updateLockGuide(state.target);
  }

  function rotateYaw(vector, degrees) {
    const radians = degrees * Math.PI / 180;
    const sin = Math.sin(radians);
    const cos = Math.cos(radians);
    return {
      x: cos * vector.x + sin * vector.z,
      y: vector.y,
      z: -sin * vector.x + cos * vector.z
    };
  }

  function rotatePitch(vector, degrees) {
    const radians = degrees * Math.PI / 180;
    const sin = Math.sin(radians);
    const cos = Math.cos(radians);
    return {
      x: vector.x,
      y: cos * vector.y + sin * vector.z,
      z: -sin * vector.y + cos * vector.z
    };
  }

  function projectGroundPoint(point, viewState, stageRect) {
    const yaw = normalizeYaw(viewState && viewState.yaw_to_camera_heading);
    const pitch = normalizePitch(viewState && viewState.pitch);
    const horizontalFovDeg = viewHorizontalFovDeg(viewState);
    const horizontalHalfRadians = (horizontalFovDeg / 2) * Math.PI / 180;
    const verticalHalfRadians = Math.atan(
      Math.tan(horizontalHalfRadians) * (stageRect.height / stageRect.width)
    );
    const verticalFovDeg = clamp(verticalHalfRadians * 2 * 180 / Math.PI, 1, 179);
    const yawAligned = rotateYaw(point, -yaw);
    const viewAligned = rotatePitch(yawAligned, pitch);
    if (viewAligned.z <= 0.01) {
      return null;
    }
    const tanHalfHorizontal = Math.tan((horizontalFovDeg / 2) * Math.PI / 180);
    const tanHalfVertical = Math.tan((verticalFovDeg / 2) * Math.PI / 180);
    if (Math.abs(tanHalfHorizontal) < 1e-9 || Math.abs(tanHalfVertical) < 1e-9) {
      return null;
    }
    const xNdc = (viewAligned.x / viewAligned.z) / tanHalfHorizontal;
    const yNdc = -(viewAligned.y / viewAligned.z) / tanHalfVertical;
    if (!Number.isFinite(xNdc) || !Number.isFinite(yNdc)) {
      return null;
    }
    if (Math.abs(xNdc) > 2.2 || Math.abs(yNdc) > 2.2) {
      return null;
    }
    return {
      x: ((xNdc + 1) / 2) * stageRect.width,
      y: ((yNdc + 1) / 2) * stageRect.height
    };
  }

  function buildGroundRingPath(radiusM, viewState, stageRect, sampleCount) {
    if (!groundRingsOverlay || !stageRect || radiusM <= 0 || !stageRect.width || !stageRect.height) {
      return "";
    }
    const segments = [];
    let currentSegment = [];
    const hudCameraHeightM = effectiveHudCameraHeightM();
    for (let index = 0; index <= sampleCount; index += 1) {
      const fraction = index / sampleCount;
      const azimuth = fraction * Math.PI * 2;
      const point = {
        x: Math.sin(azimuth) * radiusM,
        y: -hudCameraHeightM,
        z: Math.cos(azimuth) * radiusM
      };
      const projected = projectGroundPoint(point, viewState, stageRect);
      if (!projected) {
        if (currentSegment.length >= 2) {
          segments.push(currentSegment);
        }
        currentSegment = [];
        continue;
      }
      currentSegment.push(projected);
    }
    if (currentSegment.length >= 2) {
      segments.push(currentSegment);
    }
    if (!segments.length) {
      return "";
    }
    return segments.map((segment) => segment.map((point, pointIndex) => {
      const command = pointIndex === 0 ? "M" : "L";
      return `${command} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    }).join(" ")).join(" ");
  }

  function sameGridRadius(left, right) {
    return Math.abs(Number(left) - Number(right)) < 0.001;
  }

  function buildGroundGridPath(outerRadiusM, innerRadiusM, viewState, stageRect) {
    if (!Number.isFinite(outerRadiusM) || outerRadiusM < GROUND_GRID_STEP_M) {
      return "";
    }
    const maxGridRadiusM = Math.floor(outerRadiusM);
    const paths = [];
    for (let radiusM = GROUND_GRID_STEP_M; radiusM <= maxGridRadiusM; radiusM += GROUND_GRID_STEP_M) {
      if (sameGridRadius(radiusM, innerRadiusM) || sameGridRadius(radiusM, outerRadiusM)) {
        continue;
      }
      const path = buildGroundRingPath(radiusM, viewState, stageRect, GROUND_GRID_SAMPLE_COUNT);
      if (path) {
        paths.push(path);
      }
    }
    return paths.join(" ");
  }

  function clearGroundRings() {
    if (groundRingGrid) {
      groundRingGrid.removeAttribute("d");
    }
    if (groundRingOuter) {
      groundRingOuter.removeAttribute("d");
    }
    if (groundRingInner) {
      groundRingInner.removeAttribute("d");
    }
  }

  function updateGroundRings(viewState) {
    if (!groundRingsOverlay || !groundRingOuter || !groundRingInner || !groundRingGrid) {
      return;
    }
    const stageRect = panoStage ? panoStage.getBoundingClientRect() : null;
    if (!stageRect || !stageRect.width || !stageRect.height || !state.radar || !radarHudVisible || isFlatProjection()) {
      // Ground rings assume a spherical camera model. In flat mode the page is
      // only a 2D image viewer, so keep the compact HUD but hide projected rings.
      groundRingsOverlay.hidden = true;
      clearGroundRings();
      return;
    }
    const outerRadiusM = Number(state.radar.outer_range_m);
    const innerRadiusM = Number(state.radar.range_m);
    if (!Number.isFinite(outerRadiusM) || !Number.isFinite(innerRadiusM) || outerRadiusM <= 0 || innerRadiusM <= 0) {
      groundRingsOverlay.hidden = true;
      clearGroundRings();
      return;
    }
    groundRingsOverlay.setAttribute("viewBox", `0 0 ${stageRect.width} ${stageRect.height}`);
    const activeView = viewState || readPsvView() || state;
    const gridPath = buildGroundGridPath(outerRadiusM, innerRadiusM, activeView, stageRect);
    const outerPath = buildGroundRingPath(outerRadiusM, activeView, stageRect, GROUND_RING_SAMPLE_COUNT);
    const innerPath = buildGroundRingPath(innerRadiusM, activeView, stageRect, GROUND_RING_SAMPLE_COUNT);
    if (gridPath) {
      groundRingGrid.setAttribute("d", gridPath);
    } else {
      groundRingGrid.removeAttribute("d");
    }
    groundRingOuter.setAttribute("d", outerPath);
    groundRingInner.setAttribute("d", innerPath);
    groundRingsOverlay.hidden = !(gridPath || outerPath || innerPath);
  }

  function updateRadarHudVisibility() {
    const visible = radarHudVisible && Boolean(state.radar);
    if (radarHud) {
      radarHud.hidden = !visible;
    }
    if (groundRingsOverlay) {
      groundRingsOverlay.hidden = !visible;
    }
    updateReferenceOverlay();
    updateMarkers();
    if (!radarHudVisible) {
      // Treat HUD as the visual-aid group: range HUD, rings, target markers,
      // labels, and lock guide are toggled together.
      clearLockGuide();
    }
    if (radarHudToggleButton) {
      radarHudToggleButton.textContent = radarHudVisible ? "Hide HUD" : "HUD";
      radarHudToggleButton.setAttribute("aria-expanded", radarHudVisible ? "true" : "false");
    }
  }

  function setupRadarHudToggle() {
    updateRadarHudVisibility();
    if (!radarHudToggleButton) {
      return;
    }
    radarHudToggleButton.addEventListener("click", () => {
      radarHudVisible = !radarHudVisible;
      updateRadarHudVisibility();
      updateGroundRings(readPsvView() || state);
      updateLockGuide(state.target);
    });
  }

  function updateRadarHud(viewState) {
    if (!radarHud || !state.radar) {
      updateRadarHudVisibility();
      updateGroundRings(viewState);
      return;
    }
    const radar = state.radar;
    const rangeM = Number(radar.range_m);
    const outerRangeM = Number(radar.outer_range_m);
    const baseSectorRadiusM = Number(radar.base_sector_radius_m);
    const calibrationFovDeg = Number(radar.calibration_fov_deg);
    const calibrationDistanceM = Number(radar.calibration_distance_m);
    const manualScale = Number(radar.manual_scale || 1);
    const minSectorRadiusM = Number(radar.min_sector_radius_m || 1);
    const minZoomMultiplier = Number(radar.min_zoom_multiplier || 0.25);
    const maxZoomMultiplier = Number(radar.max_zoom_multiplier || 8);
    if (
      !Number.isFinite(rangeM)
      || !Number.isFinite(outerRangeM)
      || !Number.isFinite(baseSectorRadiusM)
      || outerRangeM <= 0
    ) {
      state.radar = null;
      updateRadarHudVisibility();
      return;
    }
    const zoom = normalizeZoom((viewState || state).zoom);
    const currentFovDeg = 90 / zoom;
    const zoomMultiplier = Number.isFinite(calibrationFovDeg) && calibrationFovDeg > 0
      ? clamp(calibrationFovDeg / currentFovDeg, minZoomMultiplier, maxZoomMultiplier)
      : clamp(zoom, minZoomMultiplier, maxZoomMultiplier);
    const denominator = Number.isFinite(calibrationDistanceM) && calibrationDistanceM > 0
      ? calibrationDistanceM
      : rangeM;
    const outerRadiusPx = clamp((outerRangeM / denominator) * baseSectorRadiusM * manualScale * zoomMultiplier, 4, 100);
    const innerRadiusPx = clamp((rangeM / denominator) * baseSectorRadiusM * manualScale * zoomMultiplier, 2, 100);
    const distanceM = Number(state.target && state.target.ground_distance_m);
    const displayDistanceM = Number.isFinite(distanceM) && distanceM > 0 ? distanceM : rangeM;
    const distanceMultiplier = displayDistanceM / denominator;
    const markerRadiusPx = clamp(distanceMultiplier * baseSectorRadiusM * manualScale * zoomMultiplier, 2, 100);
    const innerY = clamp(104 - innerRadiusPx, 4, 104);
    const markerY = clamp(104 - markerRadiusPx, 4, 104);

    if (hudOuterRing) {
      hudOuterRing.setAttribute("d", arcPath(outerRadiusPx));
    }
    if (hudInnerRing) {
      hudInnerRing.setAttribute("d", arcPath(innerRadiusPx));
    }
    if (hudPoints[0]) {
      hudPoints[0].setAttribute("cy", String(innerY));
    }
    if (hudPoints[1]) {
      hudPoints[1].setAttribute("cy", "4");
    }
    if (hudRangeLabel) {
      hudRangeLabel.textContent = formatMeters(rangeM);
      hudRangeLabel.setAttribute("y", String(innerY + 4));
    }
    if (hudOuterRangeLabel) {
      hudOuterRangeLabel.textContent = formatMeters(outerRangeM);
    }
    if (hudDistanceMarker) {
      const halfWidth = clamp(32 + distanceMultiplier * 12, 34, 76);
      hudDistanceMarker.setAttribute("x1", String(130 - halfWidth));
      hudDistanceMarker.setAttribute("x2", String(130 + halfWidth));
      hudDistanceMarker.setAttribute("y1", String(markerY));
      hudDistanceMarker.setAttribute("y2", String(markerY));
    }
    if (hudDistanceLabel) {
      hudDistanceLabel.textContent = formatMeters(distanceM);
      hudDistanceLabel.setAttribute("y", String(clamp(markerY - 8, 12, 96)));
    }
    updateRadarHudVisibility();
    updateGroundRings(viewState);
  }

  function frameImageUrl(video, frameIndex) {
    return `/frames/${encodeURIComponent(video)}/${frameIndex}.jpg`;
  }

  function navigationUrl(video, frameIndex) {
    const params = new URLSearchParams();
    params.set("video", video);
    params.set("frame_index", String(frameIndex));
    return `/api/navigation?${params.toString()}`;
  }

  function setNotice(messages) {
    const list = messages.filter(Boolean);
    if (!list.length) {
      notice.hidden = true;
      notice.textContent = "";
      return;
    }
    notice.hidden = false;
    notice.innerHTML = list.map((message) => `<div>${message}</div>`).join("");
  }

  function referenceSummary(reference) {
    if (!reference || typeof reference !== "object") {
      return "";
    }
    const parts = [];
    if (reference.label) {
      parts.push(`Reference: ${reference.label}`);
    }
    const distance = Number(reference.distance_m);
    if (Number.isFinite(distance)) {
      parts.push(`distance: ${distance.toFixed(1)} m`);
    }
    return parts.join("  ");
  }

  function updateReferenceOverlay() {
    if (!referenceOverlay || !referenceOverlayLabel || !referenceOverlayMeta || !referenceOverlayCoords) {
      return;
    }
    const reference = navigationState.reference;
    if (!radarHudVisible || !reference || typeof reference !== "object") {
      referenceOverlay.hidden = true;
      referenceOverlayLabel.textContent = "";
      referenceOverlayMeta.textContent = "";
      referenceOverlayCoords.textContent = "";
      return;
    }
    const label = String(reference.label || reference.reference_name || reference.kp || reference.reference_id || "").trim();
    const referenceId = String(reference.reference_id || "").trim();
    const distance = Number(reference.distance_m);
    const latitude = Number(reference.latitude);
    const longitude = Number(reference.longitude);
    const meta = [];
    if (referenceId && referenceId !== label) {
      meta.push(`ID: ${referenceId}`);
    }
    if (Number.isFinite(distance)) {
      meta.push(`distance: ${distance.toFixed(1)} m`);
    }
    referenceOverlayLabel.textContent = label || "Reference";
    referenceOverlayMeta.textContent = meta.join("  ");
    referenceOverlayCoords.textContent = Number.isFinite(latitude) && Number.isFinite(longitude)
      ? `lat/lon: ${latitude.toFixed(7)}, ${longitude.toFixed(7)}`
      : "";
    referenceOverlay.hidden = false;
  }

  function drawTextWithBackground(ctx, text, x, y, options = {}) {
    if (!text) {
      return;
    }
    const font = options.font || "14px Arial, sans-serif";
    const paddingX = options.paddingX ?? 8;
    const paddingY = options.paddingY ?? 5;
    ctx.save();
    ctx.font = font;
    ctx.textBaseline = "top";
    const metrics = ctx.measureText(text);
    const height = options.height || 18;
    ctx.fillStyle = options.background || "rgba(0, 0, 0, 0.64)";
    ctx.fillRect(x - paddingX, y - paddingY, metrics.width + paddingX * 2, height + paddingY * 2);
    ctx.fillStyle = options.color || "#f7f7f7";
    ctx.fillText(text, x, y);
    ctx.restore();
  }

  function drawTargetMarkers(ctx, stageRect) {
    const markers = panoStage.querySelectorAll(".click-target-marker");
    ctx.save();
    markers.forEach((marker) => {
      const rect = marker.getBoundingClientRect();
      const x = rect.left + rect.width / 2 - stageRect.left;
      const y = rect.top + rect.height / 2 - stageRect.top;
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        return;
      }
      ctx.strokeStyle = "rgba(112, 255, 142, 0.96)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.moveTo(x - 13, y);
      ctx.lineTo(x + 13, y);
      ctx.moveTo(x, y - 13);
      ctx.lineTo(x, y + 13);
      ctx.stroke();
      const label = marker.textContent ? marker.textContent.trim() : "";
      if (label) {
        drawTextWithBackground(ctx, label, x + 14, y - 10, {
          font: "13px Arial, sans-serif",
          color: "#ffffff",
          background: "rgba(0, 0, 0, 0.58)"
        });
      }
    });
    ctx.restore();
  }

  function elementIsDrawable(element) {
    return Boolean(element) && !element.hidden && element.style.display !== "none";
  }

  function drawSvgPathOnCanvas(ctx, element, options) {
    if (!elementIsDrawable(element) || typeof Path2D === "undefined") {
      return;
    }
    const pathData = element.getAttribute("d");
    if (!pathData) {
      return;
    }
    let path;
    try {
      path = new Path2D(pathData);
    } catch (error) {
      logDebug(`snapshot path skipped: ${error}`);
      return;
    }
    ctx.save();
    ctx.globalAlpha = options.alpha ?? 1;
    ctx.strokeStyle = options.stroke;
    ctx.lineWidth = options.lineWidth ?? 1;
    ctx.lineCap = options.lineCap || "round";
    ctx.lineJoin = options.lineJoin || "round";
    ctx.setLineDash(options.dash || []);
    ctx.stroke(path);
    ctx.restore();
  }

  function drawSvgCircleOnCanvas(ctx, element, options) {
    if (!elementIsDrawable(element)) {
      return;
    }
    const cx = Number(element.getAttribute("cx"));
    const cy = Number(element.getAttribute("cy"));
    const r = Number(element.getAttribute("r") || 5);
    if (!Number.isFinite(cx) || !Number.isFinite(cy) || !Number.isFinite(r) || r <= 0) {
      return;
    }
    ctx.save();
    ctx.globalAlpha = options.alpha ?? 1;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    if (options.fill) {
      ctx.fillStyle = options.fill;
      ctx.fill();
    }
    if (options.stroke && options.lineWidth > 0) {
      ctx.strokeStyle = options.stroke;
      ctx.lineWidth = options.lineWidth;
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawGroundRingsOnCanvas(ctx) {
    if (!elementIsDrawable(groundRingsOverlay)) {
      return;
    }
    drawSvgPathOnCanvas(ctx, groundRingGrid, {
      stroke: "rgba(71, 71, 68, 0.973)",
      lineWidth: 1,
      dash: [2, 8]
    });
    drawSvgPathOnCanvas(ctx, groundRingOuter, {
      stroke: "rgba(0, 190, 255, 0.78)",
      lineWidth: 2
    });
    drawSvgPathOnCanvas(ctx, groundRingInner, {
      stroke: "rgba(247, 242, 1, 0.92)",
      lineWidth: 2
    });
  }

  function drawLockGuideOnCanvas(ctx) {
    if (!elementIsDrawable(lockGuideOverlay)) {
      return;
    }
    drawSvgPathOnCanvas(ctx, lockGuideBand, {
      stroke: "rgba(255, 214, 74, 0.24)",
      lineWidth: 4
    });
    drawSvgPathOnCanvas(ctx, lockGuideLine, {
      stroke: "rgba(255, 238, 128, 0.88)",
      lineWidth: 1,
      dash: [7, 10]
    });
    drawSvgCircleOnCanvas(ctx, lockGuideEndpoint, {
      fill: "rgba(255, 238, 128, 0.82)",
      stroke: "rgba(0, 0, 0, 0.52)",
      lineWidth: 2
    });
  }

  function drawSnapshotFooter(ctx, width, height, current) {
    const lines = [
      `video: ${current.video || ""}`,
      `frame_index: ${current.frame_index}`,
      referenceSummary(navigationState.reference)
    ].filter(Boolean);
    if (!lines.length) {
      return;
    }
    ctx.save();
    ctx.font = "14px Arial, sans-serif";
    ctx.textBaseline = "top";
    const lineHeight = 20;
    const boxHeight = lines.length * lineHeight + 14;
    ctx.fillStyle = "rgba(0, 0, 0, 0.64)";
    ctx.fillRect(12, height - boxHeight - 12, Math.min(width - 24, 620), boxHeight);
    ctx.fillStyle = "#f7f7f7";
    lines.forEach((line, index) => {
      ctx.fillText(line, 22, height - boxHeight - 2 + index * lineHeight);
    });
    ctx.restore();
  }

  async function buildSnapshotDataUrl() {
    const stageRect = panoStage.getBoundingClientRect();
    const width = Math.max(1, Math.round(stageRect.width));
    const height = Math.max(1, Math.round(stageRect.height));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, width, height);

    if (isFlatProjection()) {
      const rect = flatImageRect(stageRect);
      if (fallbackFrame.complete && fallbackFrame.naturalWidth > 0) {
        ctx.drawImage(fallbackFrame, rect.left, rect.top, rect.width, rect.height);
      }
    } else {
      const sourceCanvas = pano.querySelector("canvas");
      if (!sourceCanvas) {
        throw new Error("viewer canvas is not ready");
      }
      ctx.drawImage(sourceCanvas, 0, 0, width, height);
    }

    if (radarHudVisible) {
      drawGroundRingsOnCanvas(ctx);
      drawLockGuideOnCanvas(ctx);
      drawTargetMarkers(ctx, stageRect);
    }
    drawSnapshotFooter(ctx, width, height, readPsvView());
    return canvas.toDataURL("image/jpeg", 0.92);
  }

  async function saveSnapshot() {
    if (!snapshotButton) {
      return;
    }
    snapshotButton.disabled = true;
    const previousText = snapshotButton.textContent;
    snapshotButton.textContent = "Saving...";
    try {
      const current = currentSessionState();
      const imageData = await buildSnapshotDataUrl();
      const payload = Object.assign({}, current, {
        image_data: imageData,
        reference: navigationState.reference || null,
        frame_position: navigationState.frame_position || current.frame_position || state.frame_position || null
      });
      const response = await fetch("/api/snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result && result.error ? result.error : `HTTP ${response.status}`);
      }
      const gpsStatus = result.gps_written
        ? `GPS: ${result.gps_source || "written"}`
        : "GPS: unavailable";
      setNotice([`Snapshot saved: ${result.filename}`, gpsStatus]);
      logDebug(`snapshot saved: ${result.path}`);
    } catch (error) {
      setNotice([`Snapshot failed: ${error}`]);
      logDebug(`snapshot failed: ${error}`);
    } finally {
      snapshotButton.disabled = false;
      snapshotButton.textContent = previousText;
    }
  }

  function logDebug(message) {
    if (!debugLog) {
      return;
    }
    const row = document.createElement("div");
    row.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    debugLog.appendChild(row);
    debugLog.scrollTop = debugLog.scrollHeight;
  }

  function updateDebugLogVisibility() {
    if (debugLog) {
      debugLog.hidden = !debugLogVisible;
    }
    if (debugToggleButton) {
      debugToggleButton.setAttribute("aria-expanded", debugLogVisible ? "true" : "false");
    }
  }

  function setupDebugLogToggle() {
    updateDebugLogVisibility();
    if (!debugToggleButton) {
      return;
    }
    debugToggleButton.addEventListener("click", () => {
      debugLogVisible = !debugLogVisible;
      updateDebugLogVisibility();
    });
  }

  function showFallbackFrame(message) {
    if (!fallbackFrame.getAttribute("src")) {
      const source = fallbackFrame.dataset.src || bootstrap.frame_url;
      if (source) {
        fallbackFrame.setAttribute("src", source);
      }
    }
    fallbackFrame.hidden = false;
    if (message) {
      setNotice([message]);
      logDebug(message);
    }
  }

  function hideFallbackFrame() {
    fallbackFrame.hidden = true;
  }

  async function describeModuleFetch(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      const contentType = response.headers.get("content-type") || "(no content-type)";
      if (!response.ok) {
        const text = await response.text().catch(() => "");
        return `${url} -> HTTP ${response.status}, ${contentType}, ${text.slice(0, 120)}`;
      }
      return `${url} -> HTTP ${response.status}, ${contentType}`;
    } catch (error) {
      return `${url} -> fetch failed: ${error}`;
    }
  }

  function displayTargets() {
    if (Array.isArray(state.targets) && state.targets.length) {
      return state.targets
        .filter((target) => target && typeof target === "object")
        .sort((left, right) => Number(left.order || left.id || 0) - Number(right.order || right.id || 0));
    }
    return state.target && typeof state.target === "object" ? [state.target] : [];
  }

  function targetPitch(target) {
    const storedPitch = Number(target.target_pitch_deg);
    if (Number.isFinite(storedPitch)) {
      return normalizePitch(storedPitch);
    }
    const viewPitch = Number(target.view_pitch);
    const pitchDelta = Number(target.pitch_delta_deg);
    if (Number.isFinite(viewPitch) && Number.isFinite(pitchDelta)) {
      return normalizePitch(viewPitch + pitchDelta);
    }
    return null;
  }

  function targetSphere(target) {
    const yaw = Number(target && target.target_yaw_to_camera_heading);
    const pitch = targetPitch(target || {});
    if (!Number.isFinite(yaw) || pitch === null) {
      return null;
    }
    return {
      h: normalizeYaw(yaw),
      v: normalizePitch(pitch)
    };
  }

  function clearLockGuide() {
    if (lockGuideOverlay) {
      lockGuideOverlay.hidden = true;
      lockGuideOverlay.setAttribute("hidden", "");
      lockGuideOverlay.style.display = "none";
    }
    if (lockGuideBand) {
      lockGuideBand.removeAttribute("d");
    }
    if (lockGuideLine) {
      lockGuideLine.removeAttribute("d");
    }
    if (lockGuideEndpoint) {
      lockGuideEndpoint.removeAttribute("cx");
      lockGuideEndpoint.removeAttribute("cy");
    }
  }

  function showLockGuideOverlay() {
    if (!lockGuideOverlay) {
      return;
    }
    lockGuideOverlay.hidden = false;
    lockGuideOverlay.removeAttribute("hidden");
    lockGuideOverlay.style.display = "";
  }

  function guideEndpointFromDirection(target, viewState, stageRect) {
    // Spherical lock guide is screen-space math derived from the stored target
    // yaw/pitch. PSV markers are still the authoritative marker placement.
    const sphere = targetSphere(target);
    if (!sphere || !viewState || !stageRect.width || !stageRect.height) {
      return null;
    }
    const horizontalFovDeg = viewHorizontalFovDeg(viewState);
    const horizontalHalfRadians = (horizontalFovDeg / 2) * Math.PI / 180;
    const verticalHalfRadians = Math.atan(
      Math.tan(horizontalHalfRadians) * (stageRect.height / stageRect.width)
    );
    const yawDeltaDeg = normalizeSignedYaw(sphere.h - normalizeYaw(viewState.yaw_to_camera_heading));
    const pitchDeltaDeg = normalizePitch(sphere.v) - normalizePitch(viewState.pitch);
    if (Math.abs(yawDeltaDeg) >= 89.0) {
      return null;
    }
    let xNdc = Math.tan(yawDeltaDeg * Math.PI / 180) / Math.tan(horizontalHalfRadians);
    let yNdc = -Math.tan(pitchDeltaDeg * Math.PI / 180) / Math.tan(verticalHalfRadians);
    if (!Number.isFinite(xNdc) || !Number.isFinite(yNdc)) {
      return null;
    }
    if (Math.abs(xNdc) < 0.001 && Math.abs(yNdc) < 0.001) {
      yNdc = -0.001;
    }
    const scale = Math.min(1, 0.92 / Math.max(Math.abs(xNdc), Math.abs(yNdc), 0.001));
    xNdc *= scale;
    yNdc *= scale;
    return {
      x: ((xNdc + 1) / 2) * stageRect.width,
      y: ((yNdc + 1) / 2) * stageRect.height
    };
  }

  function guidePointFromYawPitch(target, viewState, stageRect) {
    const sphere = targetSphere(target);
    if (!sphere || !viewState || !stageRect.width || !stageRect.height) {
      return null;
    }
    const yawDeltaDeg = normalizeSignedYaw(sphere.h - normalizeYaw(viewState.yaw_to_camera_heading));
    const pitchDeltaDeg = normalizePitch(sphere.v) - normalizePitch(viewState.pitch);
    if (Math.abs(yawDeltaDeg) > 90.0) {
      const side = yawDeltaDeg >= 0 ? 1 : -1;
      const rearRatio = clamp((Math.abs(yawDeltaDeg) - 90.0) / 90.0, 0, 1);
      return {
        x: stageRect.width / 2 + side * (stageRect.width * (0.18 + 0.28 * rearRatio)),
        y: stageRect.height * (0.78 + 0.12 * rearRatio)
      };
    }
    let dx = Math.sin(yawDeltaDeg * Math.PI / 180);
    let dy = -Math.sin(pitchDeltaDeg * Math.PI / 180);
    if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
      dy = -1;
    }
    const length = Math.hypot(dx, dy);
    return {
      x: stageRect.width / 2 + (dx / length) * 100,
      y: stageRect.height / 2 + (dy / length) * 100
    };
  }

  function rayToStageEdge(fromX, fromY, towardX, towardY, stageRect) {
    let dx = Number(towardX) - Number(fromX);
    let dy = Number(towardY) - Number(fromY);
    if (!Number.isFinite(dx) || !Number.isFinite(dy) || Math.hypot(dx, dy) < 1) {
      dx = 0;
      dy = -1;
    }
    const candidates = [];
    if (Math.abs(dx) > 0.001) {
      candidates.push((0 - fromX) / dx);
      candidates.push((stageRect.width - fromX) / dx);
    }
    if (Math.abs(dy) > 0.001) {
      candidates.push((0 - fromY) / dy);
      candidates.push((stageRect.height - fromY) / dy);
    }
    const positive = candidates.filter((value) => Number.isFinite(value) && value > 0);
    const scale = positive.length ? Math.min(...positive) : 1;
    return {
      x: clamp(fromX + dx * scale, 0, stageRect.width),
      y: clamp(fromY + dy * scale, 0, stageRect.height)
    };
  }

  function updateLockGuide(target) {
    if (!viewHoldEnabled || !radarHudVisible || !lockGuideOverlay || !panoStage) {
      clearLockGuide();
      return;
    }
    const stageRect = panoStage.getBoundingClientRect();
    if (!stageRect.width || !stageRect.height) {
      clearLockGuide();
      return;
    }
    lockGuideOverlay.setAttribute("viewBox", `0 0 ${stageRect.width} ${stageRect.height}`);
    const viewState = readPsvView() || state;
    const centerX = stageRect.width / 2;
    const centerY = stageRect.height;
    const projected = target
      ? (
        isFlatProjection()
          // Flat targets have exact x/y image ratios. Use those instead of
          // yaw/pitch, which may be unavailable for ordinary camera frames.
          ? flatPointFromRatio(target, stageRect)
          : (guideEndpointFromDirection(target, viewState, stageRect) || guidePointFromYawPitch(target, viewState, stageRect))
      )
      : { x: centerX, y: stageRect.height / 2 };
    if (!projected) {
      clearLockGuide();
      return;
    }
    const endpoint = rayToStageEdge(centerX, centerY, projected.x, projected.y, stageRect);
    const path = `M ${centerX.toFixed(1)} ${centerY.toFixed(1)} L ${endpoint.x.toFixed(1)} ${endpoint.y.toFixed(1)}`;
    lockGuideBand.setAttribute("d", path);
    lockGuideLine.setAttribute("d", path);
    lockGuideEndpoint.setAttribute("cx", String(endpoint.x.toFixed(1)));
    lockGuideEndpoint.setAttribute("cy", String(endpoint.y.toFixed(1)));
    showLockGuideOverlay();
  }

  function setupViewHoldToggle() {
    if (viewHoldButton) {
      viewHoldButton.textContent = viewHoldEnabled ? "Unlock" : "Lock";
      viewHoldButton.setAttribute("aria-pressed", viewHoldEnabled ? "true" : "false");
      viewHoldButton.addEventListener("click", () => {
        viewHoldEnabled = !viewHoldEnabled;
        viewHoldButton.textContent = viewHoldEnabled ? "Unlock" : "Lock";
        viewHoldButton.setAttribute("aria-pressed", viewHoldEnabled ? "true" : "false");
        updateLockGuide(state.target);
      });
    }
    updateLockGuide(state.target);
  }

  function psvMarkersFromTargets() {
    if (!radarHudVisible || isFlatProjection()) {
      // Flat markers are plain absolutely-positioned DOM elements because PSV
      // is not active for ordinary camera frames.
      return [];
    }
    return displayTargets().slice(0, MAX_CLICK_TARGETS).map((target, index) => {
      const yaw = Number(target.target_yaw_to_camera_heading);
      const pitch = targetPitch(target);
      if (!Number.isFinite(yaw) || pitch === null) {
        return null;
      }
      const id = String(target.id || target.order || index + 1);
      const label = targetLabel(target, id);
      const markerTypeClass = target.target_source || target.source === "auto"
        ? "click-target-marker-auto"
        : "click-target-marker-saved";
      return {
        id: `target-${id}`,
        position: {
          yaw: `${normalizeYaw(yaw)}deg`,
          pitch: `${krpanoPitchToPsvPitch(pitch)}deg`
        },
        html: `<span class="psv-target-pin click-target-marker ${markerTypeClass}"><span class="click-target-marker-label">${escapeHtml(label || `target #${id}`)}</span></span>`,
        size: { width: 18, height: 18 },
        anchor: "center center",
        tooltip: label || `target #${id}`,
        className: "psv-target-marker"
      };
    }).filter(Boolean);
  }

  function updateMarkers() {
    if (isFlatProjection()) {
      if (markersPlugin && typeof markersPlugin.setMarkers === "function") {
        markersPlugin.setMarkers([]);
      }
      updateFlatTargetMarkers();
      return;
    }
    clearFlatTargetMarkers();
    if (markersPlugin && typeof markersPlugin.setMarkers === "function") {
      markersPlugin.setMarkers(psvMarkersFromTargets());
    }
  }

  function readPsvView() {
    if (isFlatProjection() || !viewer || typeof viewer.getPosition !== "function") {
      return state;
    }
    const position = viewer.getPosition();
    const zoomLevel = typeof viewer.getZoomLevel === "function" ? viewer.getZoomLevel() : zoomToPsvLevel(state.zoom);
    return Object.assign({}, state, {
      yaw_to_camera_heading: normalizeYaw(radiansToDegrees(position.yaw)),
      pitch: psvPitchToKrpanoPitch(radiansToDegrees(position.pitch)),
      zoom: psvLevelToZoom(zoomLevel),
      viewer_projection: "sphere",
      viewer_psv_min_fov_deg: PSV_MIN_FOV_DEG,
      viewer_psv_max_fov_deg: PSV_MAX_FOV_DEG
    });
  }

  function currentSessionState() {
    const current = readPsvView();
    if (state.target) {
      current.target = state.target;
    }
    if (Array.isArray(state.targets) && state.targets.length) {
      current.targets = state.targets;
    }
    if (state.frame_position) {
      current.frame_position = state.frame_position;
    }
    if (state.applied_command_id) {
      current.applied_command_id = state.applied_command_id;
    }
    return current;
  }

  function updateReadout() {
    const active = readPsvView();
    videoLabel.textContent = `video: ${active.video}`;
    frameLabel.textContent = `frame_index: ${active.frame_index}`;
    viewLabel.textContent = `engine: psv, yaw: ${Number(active.yaw_to_camera_heading).toFixed(2)}, pitch: ${Number(active.pitch).toFixed(2)}, zoom: ${Number(active.zoom).toFixed(2)}, fov: ${viewHorizontalFovDeg(active).toFixed(1)}`;
    updateRadarHud(active);
    updateLockGuide(state.target);
  }

  async function postViewerState(immediate) {
    if (!immediate && postTimer) {
      window.clearTimeout(postTimer);
      postTimer = null;
    }
    const current = currentSessionState();
    try {
      await fetch("/api/session/viewer-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(current)
      });
      return true;
    } catch (error) {
      setNotice([`Failed to update viewer_session.json: ${error}`]);
      return false;
    }
  }

  function schedulePost() {
    if (postTimer) {
      window.clearTimeout(postTimer);
    }
    postTimer = window.setTimeout(() => postViewerState(false), 300);
  }

  async function refreshNavigation(video, frameIndex) {
    const response = await fetch(navigationUrl(video, frameIndex), { cache: "no-store" }).catch(() => null);
    if (!response || !response.ok) {
      return;
    }
    const payload = await response.json().catch(() => null);
    if (!payload) {
      return;
    }
    navigationState = {
      prev_frame: payload.prev_frame,
      next_frame: payload.next_frame,
      matched_csv_exists: Boolean(payload.matched_csv_exists),
      reference: payload.reference || null,
      frame_position: payload.frame_position || state.frame_position || navigationState.frame_position || null
    };
    updateReferenceOverlay();
    updateNavigationButtons();
  }

  function updateNavigationButtons() {
    if (prevButton) {
      prevButton.disabled = navigationState.prev_frame === null || navigationState.prev_frame === undefined;
    }
    if (nextButton) {
      nextButton.disabled = navigationState.next_frame === null || navigationState.next_frame === undefined;
    }
  }

  function showFlatFrame(imageUrl) {
    // Ordinary forward-camera frames are intentionally not passed to PSV.
    // PSV expects a panorama and reports "The panorama cannot be loaded" for
    // normal aspect-ratio images, so use the fallback image as a small 2D viewer.
    if (panoStage) {
      panoStage.classList.add("pano-stage-flat");
    }
    if (pano) {
      pano.hidden = true;
    }
    fallbackFrame.dataset.src = imageUrl;
    fallbackFrame.setAttribute("src", imageUrl);
    fallbackFrame.hidden = false;
    flatZoom = normalizeZoom(state.zoom);
    if (flatZoom < 1) {
      flatZoom = 1;
    }
    fallbackFrame.onload = () => applyFlatTransform();
    applyFlatTransform();
    clearGroundRings();
    updateRadarHudVisibility();
    updateLockGuide(state.target);
  }

  function showSphereFrame() {
    if (panoStage) {
      panoStage.classList.remove("pano-stage-flat");
    }
    if (pano) {
      pano.hidden = false;
    }
    fallbackFrame.style.transform = "";
    clearFlatTargetMarkers();
  }

  function setupFlatInteractions() {
    if (!panoStage) {
      return;
    }
    panoStage.addEventListener("wheel", (event) => {
      if (!isFlatProjection()) {
        return;
      }
      event.preventDefault();
      const stageRect = panoStage.getBoundingClientRect();
      const beforeZoom = flatZoom;
      const nextZoom = clamp(beforeZoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15), 1, 8);
      if (Math.abs(nextZoom - beforeZoom) < 0.001) {
        return;
      }
      const pointerX = event.clientX - stageRect.left - stageRect.width / 2;
      const pointerY = event.clientY - stageRect.top - stageRect.height / 2;
      const factor = nextZoom / beforeZoom;
      flatPanX = pointerX - (pointerX - flatPanX) * factor;
      flatPanY = pointerY - (pointerY - flatPanY) * factor;
      flatZoom = nextZoom;
      state.zoom = flatZoom;
      applyFlatTransform();
      updateReadout();
      schedulePost();
    }, { passive: false });

    function finishFlatDrag(event) {
      // Clear drag state for every pointer termination path. Releasing outside
      // the stage otherwise leaves the image attached to later pointer moves.
      if (!flatDragging) {
        return;
      }
      if (event && flatDragPointerId !== null && event.pointerId !== flatDragPointerId) {
        return;
      }
      flatDragging = false;
      if (event && panoStage.hasPointerCapture && panoStage.hasPointerCapture(event.pointerId)) {
        panoStage.releasePointerCapture(event.pointerId);
      }
      flatDragPointerId = null;
      schedulePost();
    }

    panoStage.addEventListener("pointerdown", (event) => {
      if (!isFlatProjection() || flatZoom <= 1 || !event.isPrimary) {
        return;
      }
      event.preventDefault();
      flatDragging = true;
      flatDragPointerId = event.pointerId;
      flatDragStartX = event.clientX;
      flatDragStartY = event.clientY;
      flatDragOriginX = flatPanX;
      flatDragOriginY = flatPanY;
      if (panoStage.setPointerCapture) {
        panoStage.setPointerCapture(event.pointerId);
      }
    });
    panoStage.addEventListener("pointermove", (event) => {
      if (!flatDragging || event.pointerId !== flatDragPointerId) {
        return;
      }
      event.preventDefault();
      flatPanX = flatDragOriginX + event.clientX - flatDragStartX;
      flatPanY = flatDragOriginY + event.clientY - flatDragStartY;
      applyFlatTransform();
    });
    panoStage.addEventListener("pointerup", finishFlatDrag);
    panoStage.addEventListener("pointercancel", finishFlatDrag);
    panoStage.addEventListener("lostpointercapture", finishFlatDrag);
    window.addEventListener("blur", () => finishFlatDrag(null));
  }

  async function loadFrame(session) {
    const nextVideo = session.video;
    const nextFrame = Number(session.frame_index);
    if (!nextVideo || !Number.isFinite(nextFrame)) {
      return false;
    }
    Object.assign(state, session, {
      video: nextVideo,
      frame_index: nextFrame,
      viewer_projection: isFlatProjection(session.viewer_projection) ? "flat" : "sphere"
    });
    if (session.viewer_camera_height_m !== undefined) {
      viewerCameraHeightM = normalizeCameraHeight(session.viewer_camera_height_m);
      state.viewer_camera_height_m = viewerCameraHeightM;
    }
    if (session.viewer_hud_height_scale !== undefined) {
      viewerHudHeightScale = normalizeHudHeightScale(session.viewer_hud_height_scale);
      state.viewer_hud_height_scale = viewerHudHeightScale;
    }
    if (session.radar && typeof session.radar === "object") {
      state.radar = session.radar;
    }
    state.targets = Array.isArray(session.targets) ? session.targets : [];
    state.target = session.target && typeof session.target === "object"
      ? session.target
      : (state.targets.length ? state.targets[state.targets.length - 1] : null);

    const commandId = String(session.command_id || "");
    if (commandId) {
      lastAppliedCommandId = commandId;
      state.applied_command_id = commandId;
    }

    const currentView = readPsvView();
    const panorama = frameImageUrl(nextVideo, nextFrame);
    try {
      if (isFlatProjection()) {
        // Navigation can switch between sphere and flat frames without a full
        // page reload; the active renderer is chosen per session payload.
        showFlatFrame(panorama);
        updateReadout();
        await refreshNavigation(nextVideo, nextFrame);
        await postViewerState(true);
        return true;
      }
      showSphereFrame();
      if (viewer && typeof viewer.setPanorama === "function") {
        await viewer.setPanorama(panorama, {
          transition: false,
          position: {
            yaw: degreesToRadians(normalizeYaw(session.yaw_to_camera_heading ?? currentView.yaw_to_camera_heading)),
            pitch: degreesToRadians(krpanoPitchToPsvPitch(session.pitch ?? currentView.pitch))
          }
        });
        if (typeof viewer.zoom === "function") {
          viewer.zoom(zoomToPsvLevel(session.zoom ?? currentView.zoom));
        }
      }
      fallbackFrame.dataset.src = panorama;
      hideFallbackFrame();
      updateMarkers();
      updateReadout();
      await refreshNavigation(nextVideo, nextFrame);
      await postViewerState(true);
      return true;
    } catch (error) {
      showFallbackFrame(`Photo Sphere Viewer could not load the frame: ${error}`);
      return false;
    }
  }

  async function pollExternalNavigation() {
    const response = await fetch(`/api/session/viewer-command?_=${Date.now()}`, { cache: "no-store" }).catch(() => null);
    if (!response || !response.ok) {
      return;
    }
    const session = await response.json().catch(() => null);
    if (!session || !session.video || session.frame_index === undefined || session.frame_index === null) {
      return;
    }
    const commandId = String(session.command_id || "");
    if (commandId && commandId === lastAppliedCommandId) {
      return;
    }
    await loadFrame(session);
  }

  function setupNavigation() {
    if (prevButton) {
      prevButton.addEventListener("click", () => {
        if (navigationState.prev_frame !== null && navigationState.prev_frame !== undefined) {
          loadFrame(Object.assign({}, readPsvView(), {
            video: state.video,
            frame_index: navigationState.prev_frame
          }));
        }
      });
    }
    if (nextButton) {
      nextButton.addEventListener("click", () => {
        if (navigationState.next_frame !== null && navigationState.next_frame !== undefined) {
          loadFrame(Object.assign({}, readPsvView(), {
            video: state.video,
            frame_index: navigationState.next_frame
          }));
        }
      });
    }
    updateNavigationButtons();
  }

  function setupSnapshot() {
    if (snapshotButton) {
      snapshotButton.addEventListener("click", saveSnapshot);
    }
  }

  async function setupPhotoSphereViewer() {
    if (isFlatProjection()) {
      showFlatFrame(bootstrap.frame_url);
      updateReadout();
      await postViewerState(true);
      if (!statePostIntervalTimer) {
        statePostIntervalTimer = window.setInterval(schedulePost, VIEW_STATE_POST_INTERVAL_MS);
      }
      if (!externalPollTimer) {
        externalPollTimer = window.setInterval(pollExternalNavigation, EXTERNAL_SESSION_POLL_INTERVAL_MS);
      }
      logDebug("Photo Sphere Viewer flat fallback ready");
      return;
    }

    if (!bootstrap.psv_available) {
      showFallbackFrame(
        "Photo Sphere Viewer files are not found. Place local vendor files under static/vendor/photo-sphere-viewer/."
      );
      return;
    }

    let Viewer;
    let MarkersPlugin;
    try {
      const coreStatus = await describeModuleFetch(PSV_CORE_JS_URL);
      if (!coreStatus.includes("HTTP 200")) {
        showFallbackFrame(`Photo Sphere Viewer core module is not reachable: ${coreStatus}`);
        return;
      }
      const core = await import(PSV_CORE_JS_URL);
      const markers = await import(PSV_MARKERS_JS_URL);
      Viewer = core.Viewer;
      MarkersPlugin = markers.MarkersPlugin;
    } catch (error) {
      showFallbackFrame(`Photo Sphere Viewer modules could not be loaded: ${error}`);
      return;
    }

    try {
      hideFallbackFrame();
      viewer = new Viewer({
        container: pano,
        panorama: bootstrap.frame_url,
        minFov: PSV_MIN_FOV_DEG,
        maxFov: PSV_MAX_FOV_DEG,
        defaultYaw: `${normalizeYaw(state.yaw_to_camera_heading)}deg`,
        defaultPitch: `${krpanoPitchToPsvPitch(state.pitch)}deg`,
        defaultZoomLvl: zoomToPsvLevel(state.zoom),
        rendererParameters: { alpha: true, antialias: true, preserveDrawingBuffer: true },
        navbar: ["zoom", "move", "caption", "fullscreen"],
        plugins: [
          [MarkersPlugin, { markers: psvMarkersFromTargets() }]
        ]
      });
      markersPlugin = viewer.getPlugin(MarkersPlugin);
      viewer.addEventListener("ready", () => {
        updateMarkers();
        updateReadout();
        postViewerState(true);
        if (!statePostIntervalTimer) {
          statePostIntervalTimer = window.setInterval(schedulePost, VIEW_STATE_POST_INTERVAL_MS);
        }
        if (!externalPollTimer) {
          externalPollTimer = window.setInterval(pollExternalNavigation, EXTERNAL_SESSION_POLL_INTERVAL_MS);
        }
        logDebug("Photo Sphere Viewer ready");
      }, { once: true });
      viewer.addEventListener("position-updated", () => {
        updateReadout();
        schedulePost();
      });
      viewer.addEventListener("zoom-updated", () => {
        updateReadout();
        schedulePost();
      });
    } catch (error) {
      showFallbackFrame(`Photo Sphere Viewer failed to start: ${error}`);
    }
  }

  setupDebugLogToggle();
  setupRadarHudToggle();
  setupViewHoldToggle();
  setupFlatInteractions();
  setupNavigation();
  setupSnapshot();
  await setupPhotoSphereViewer();
}());
