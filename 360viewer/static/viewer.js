(function () {
  const bootstrap = window.VIEWER_BOOTSTRAP || {};
  const state = Object.assign({
    video: "",
    frame_index: 0,
    yaw_to_camera_heading: 0,
    pitch: 0,
    zoom: 1,
    viewer_camera_height_m: bootstrap.viewer_camera_height_m,
    target: null
  }, bootstrap.state || {});
  const GROUND_GRID_STEP_M = 1;
  const GROUND_RING_SAMPLE_COUNT = 96;
  const GROUND_GRID_SAMPLE_COUNT = 64;

  let krpano = null;
  let lastPosted = null;
  let postTimer = null;
  let krpanoReady = false;
  let krpanoImageLoaded = false;
  let debugLogVisible = false;
  let radarHudVisible = true;
  let groundGridVisible = true;
  let lastViewDebug = null;
  let navigationState = {
    prev_frame: bootstrap.prev_frame,
    next_frame: bootstrap.next_frame,
    matched_csv_exists: Boolean(bootstrap.matched_csv_exists)
  };

  const prevButton = document.getElementById("prevButton");
  const nextButton = document.getElementById("nextButton");
  const radarHudToggleButton = document.getElementById("radarHudToggleButton");
  const groundGridToggleButton = document.getElementById("groundGridToggleButton");
  const debugToggleButton = document.getElementById("debugToggleButton");
  const notice = document.getElementById("notice");
  const debugLog = document.getElementById("debugLog");
  const fallbackFrame = document.getElementById("fallbackFrame");
  const panoStage = document.querySelector(".pano-stage");
  const clickTargetMarker = document.getElementById("clickTargetMarker");
  const groundRingsOverlay = document.getElementById("groundRingsOverlay");
  const groundRingGrid = document.getElementById("groundRingGrid");
  const groundRingOuter = document.getElementById("groundRingOuter");
  const groundRingInner = document.getElementById("groundRingInner");
  const videoLabel = document.getElementById("videoLabel");
  const frameLabel = document.getElementById("frameLabel");
  const viewLabel = document.getElementById("viewLabel");
  const radarHud = document.getElementById("radarHud");
  const hudRangeLabel = document.getElementById("hudRangeLabel");
  const hudOuterRangeLabel = document.getElementById("hudOuterRangeLabel");
  const hudDistanceMarker = document.getElementById("hudDistanceMarker");
  const hudDistanceLabel = document.getElementById("hudDistanceLabel");
  const hudInnerRing = radarHud ? radarHud.querySelector(".hud-ring-inner") : null;
  const hudOuterRing = radarHud ? radarHud.querySelector(".hud-ring-outer") : null;
  const hudPoints = radarHud ? Array.from(radarHud.querySelectorAll(".hud-point")) : [];
  let viewerCameraHeightM = normalizeCameraHeight(state.viewer_camera_height_m);

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

  function normalizeCameraHeight(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 1.5;
    }
    return clamp(numeric, 0.1, 20.0);
  }

  function updateCameraHeight(value) {
    viewerCameraHeightM = normalizeCameraHeight(value);
    state.viewer_camera_height_m = viewerCameraHeightM;
  }

  function normalizedView(source) {
    return {
      yaw_to_camera_heading: normalizeYaw(source && source.yaw_to_camera_heading),
      pitch: normalizePitch(source && source.pitch),
      zoom: normalizeZoom(source && source.zoom)
    };
  }

  function readKrpanoView() {
    if (!krpano || typeof krpano.get !== "function") {
      return null;
    }

    const yaw = normalizeYaw(krpano.get("view.hlookat"));
    const pitch = Number(krpano.get("view.vlookat")) || 0;
    const fov = Number(krpano.get("view.fov")) || 90;
    const zoom = 90 / Math.max(fov, 1);

    return {
      video: state.video,
      frame_index: Number(state.frame_index),
      yaw_to_camera_heading: yaw,
      pitch: normalizePitch(pitch),
      zoom: normalizeZoom(zoom),
      viewer_camera_height_m: viewerCameraHeightM
    };
  }

  function updateReadout(viewState) {
    const active = viewState || state;
    const fov = 90 / normalizeZoom(active.zoom);
    const target = state.target && Number.isFinite(Number(state.target.yaw_delta_deg))
      ? `, click: ${Number(state.target.yaw_delta_deg).toFixed(1)}deg`
      : "";
    videoLabel.textContent = `video: ${active.video}`;
    frameLabel.textContent = `frame_index: ${active.frame_index}`;
    viewLabel.textContent = `yaw: ${Number(active.yaw_to_camera_heading).toFixed(2)}, pitch: ${Number(active.pitch).toFixed(2)}, fov: ${fov.toFixed(1)}, zoom: ${Number(active.zoom).toFixed(2)}${target}`;
    updateRadarHud(active);
    updateClickTargetMarker();
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

  function logDebug(message) {
    if (!debugLog) {
      return;
    }
    const line = document.createElement("div");
    line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    debugLog.appendChild(line);
    updateDebugLogVisibility();
  }

  function shouldLogViewChange(nextView) {
    if (!nextView) {
      return false;
    }
    if (!lastViewDebug) {
      return true;
    }
    return Math.abs(Number(nextView.yaw_to_camera_heading) - Number(lastViewDebug.yaw_to_camera_heading)) >= 1.0
      || Math.abs(Number(nextView.pitch) - Number(lastViewDebug.pitch)) >= 1.0
      || Math.abs(Number(nextView.zoom) - Number(lastViewDebug.zoom)) >= 0.05;
  }

  function logViewDebug(viewState, reason) {
    const active = viewState || readKrpanoView() || state;
    if (!active || !shouldLogViewChange(active)) {
      return;
    }
    const fov = 90 / normalizeZoom(active.zoom);
    logDebug(`${reason || "view"} yaw=${Number(active.yaw_to_camera_heading).toFixed(2)} pitch=${Number(active.pitch).toFixed(2)} fov=${fov.toFixed(2)} zoom=${Number(active.zoom).toFixed(3)}`);
    lastViewDebug = {
      yaw_to_camera_heading: Number(active.yaw_to_camera_heading),
      pitch: Number(active.pitch),
      zoom: Number(active.zoom)
    };
  }

  function formatVector(vector) {
    if (!vector) {
      return "(n/a)";
    }
    return `(${Number(vector.x).toFixed(2)},${Number(vector.y).toFixed(2)},${Number(vector.z).toFixed(2)})`;
  }

  function logGroundRingSamples(viewState) {
    if (!panoStage || !viewState) {
      return;
    }
    const stageRect = panoStage.getBoundingClientRect();
    if (!stageRect.width || !stageRect.height) {
      return;
    }
    const samples = [
      ["front5", { x: 0, y: -viewerCameraHeightM, z: 5 }],
      ["right5", { x: 5, y: -viewerCameraHeightM, z: 0 }],
      ["back5", { x: 0, y: -viewerCameraHeightM, z: -5 }],
      ["left5", { x: -5, y: -viewerCameraHeightM, z: 0 }]
    ];
    const yaw = normalizeYaw(viewState.yaw_to_camera_heading);
    const pitch = normalizePitch(viewState.pitch);
    samples.forEach(([label, worldPoint]) => {
      const yawAligned = rotateYaw(worldPoint, -yaw);
      const viewAligned = rotatePitch(yawAligned, pitch);
      const projected = projectGroundPoint(worldPoint, viewState, stageRect);
      logDebug(`sample ${label} world=${formatVector(worldPoint)} yawAligned=${formatVector(yawAligned)} viewAligned=${formatVector(viewAligned)} visible=${Boolean(projected)}`);
    });
  }

  function updateDebugLogVisibility() {
    if (!debugLog) {
      return;
    }
    debugLog.hidden = !debugLogVisible;
    if (debugToggleButton) {
      debugToggleButton.textContent = debugLogVisible ? "Hide Log" : "Log";
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
      if (debugLogVisible && debugLog) {
        debugLog.scrollTop = debugLog.scrollHeight;
      }
    });
  }

  function updateRadarHudVisibility() {
    const visible = radarHudVisible && Boolean(state.radar);
    if (radarHud) {
      radarHud.hidden = !visible;
    }
    if (groundRingsOverlay) {
      groundRingsOverlay.hidden = !visible;
    }
    if (radarHudToggleButton) {
      radarHudToggleButton.textContent = radarHudVisible ? "Hide HUD" : "HUD";
      radarHudToggleButton.setAttribute("aria-expanded", radarHudVisible ? "true" : "false");
    }
    if (groundGridToggleButton) {
      groundGridToggleButton.textContent = groundGridVisible ? "Hide Grid" : "Grid";
      groundGridToggleButton.setAttribute("aria-pressed", groundGridVisible ? "true" : "false");
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
      updateGroundRings(readKrpanoView() || state);
    });
  }

  function setupGroundGridToggle() {
    updateRadarHudVisibility();
    if (!groundGridToggleButton) {
      return;
    }
    groundGridToggleButton.addEventListener("click", () => {
      groundGridVisible = !groundGridVisible;
      updateRadarHudVisibility();
      updateGroundRings(readKrpanoView() || state);
    });
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

  function arcPath(radiusPx) {
    const cx = 130;
    const cy = 104;
    const r = clamp(radiusPx, 1, 100);
    return `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
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

  function groundPointToSphere(point) {
    if (krpano && krpano.actions && typeof krpano.actions.spacetosphere === "function") {
      const sphere = krpano.actions.spacetosphere(point.x, -point.y, point.z);
      if (sphere && Number.isFinite(Number(sphere.h)) && Number.isFinite(Number(sphere.v))) {
        return {
          h: normalizeYaw(sphere.h),
          v: normalizePitch(sphere.v)
        };
      }
    }

    const horizontalDistance = Math.hypot(point.x, point.z);
    return {
      h: normalizeYaw(Math.atan2(point.x, point.z) * 180 / Math.PI),
      v: -Math.atan2(point.y, horizontalDistance) * 180 / Math.PI
    };
  }

  function projectGroundPointWithKrpano(point, stageRect) {
    if (!krpano || !krpano.actions || typeof krpano.actions.spheretoscreen !== "function") {
      return null;
    }
    const sphere = groundPointToSphere(point);
    const projected = krpano.actions.spheretoscreen(sphere.h, sphere.v);
    if (!projected) {
      return null;
    }
    const x = Number(projected.x);
    const y = Number(projected.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return null;
    }
    const marginX = stageRect.width * 1.2;
    const marginY = stageRect.height * 1.2;
    if (x < -marginX || x > stageRect.width + marginX || y < -marginY || y > stageRect.height + marginY) {
      return null;
    }
    return { x, y };
  }

  function projectGroundPoint(point, viewState, stageRect) {
    const krpanoProjected = projectGroundPointWithKrpano(point, stageRect);
    if (krpanoProjected) {
      return krpanoProjected;
    }

    const yaw = normalizeYaw(viewState && viewState.yaw_to_camera_heading);
    const pitch = normalizePitch(viewState && viewState.pitch);
    const zoom = normalizeZoom(viewState && viewState.zoom);
    const horizontalFovDeg = clamp(90 / zoom, 1, 179);
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
    if (!groundRingsOverlay || !stageRect || radiusM <= 0) {
      return "";
    }
    if (!stageRect.width || !stageRect.height) {
      return "";
    }
    const segments = [];
    let currentSegment = [];
    for (let index = 0; index <= sampleCount; index += 1) {
      const fraction = index / sampleCount;
      const azimuth = fraction * Math.PI * 2;
      const point = {
        x: Math.sin(azimuth) * radiusM,
        y: -viewerCameraHeightM,
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
    if (!groundGridVisible || !Number.isFinite(outerRadiusM) || outerRadiusM < GROUND_GRID_STEP_M) {
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
    if (!stageRect || !stageRect.width || !stageRect.height) {
      groundRingsOverlay.hidden = true;
      clearGroundRings();
      return;
    }
    groundRingsOverlay.setAttribute("viewBox", `0 0 ${stageRect.width} ${stageRect.height}`);
    if (!state.radar || !radarHudVisible) {
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
    const activeView = viewState || readKrpanoView() || state;
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
    let distanceMultiplier = clamp(1 / zoom, minZoomMultiplier, maxZoomMultiplier);
    let distanceM = Math.max(minSectorRadiusM, baseSectorRadiusM * distanceMultiplier);
    if (
      Number.isFinite(calibrationFovDeg)
      && Number.isFinite(calibrationDistanceM)
      && Number.isFinite(manualScale)
      && calibrationFovDeg > 0
      && calibrationFovDeg < 180
    ) {
      const currentHalfTan = Math.tan((currentFovDeg / 2) * Math.PI / 180);
      const calibrationHalfTan = Math.tan((calibrationFovDeg / 2) * Math.PI / 180);
      if (Math.abs(calibrationHalfTan) > 1e-9) {
        distanceMultiplier = currentHalfTan / calibrationHalfTan;
        distanceM = Math.max(minSectorRadiusM, calibrationDistanceM * manualScale * distanceMultiplier);
      }
    }
    const outerRadiusPx = 100;
    const innerRadiusPx = clamp((rangeM / outerRangeM) * outerRadiusPx, 1, outerRadiusPx);
    const markerRadiusPx = clamp((distanceM / outerRangeM) * outerRadiusPx, 0, outerRadiusPx);
    const markerY = 104 - markerRadiusPx;
    const innerY = 104 - innerRadiusPx;

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

  function updateRadarState(radar) {
    state.radar = radar && typeof radar === "object" ? radar : null;
    updateRadarHud(readKrpanoView() || state);
  }

  function updateClickTargetMarker() {
    if (!clickTargetMarker || !state.target) {
      if (clickTargetMarker) {
        clickTargetMarker.hidden = true;
      }
      return;
    }
    const xRatio = Number(state.target.x_ratio);
    const yRatio = Number(state.target.y_ratio);
    if (!Number.isFinite(xRatio) || !Number.isFinite(yRatio)) {
      clickTargetMarker.hidden = true;
      return;
    }
    clickTargetMarker.style.left = `${clamp(xRatio, 0, 1) * 100}%`;
    clickTargetMarker.style.top = `${clamp(yRatio, 0, 1) * 100}%`;
    clickTargetMarker.hidden = false;
  }

  function currentSessionState() {
    const current = Object.assign({}, readKrpanoView() || state);
    current.viewer_camera_height_m = viewerCameraHeightM;
    if (state.target) {
      current.target = state.target;
    }
    return current;
  }

  function screenClickTarget(event) {
    if (!panoStage) {
      return null;
    }
    const rect = panoStage.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return null;
    }

    const xRatio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const yRatio = clamp((event.clientY - rect.top) / rect.height, 0, 1);
    const current = readKrpanoView() || state;
    const zoom = normalizeZoom(current.zoom);
    const horizontalFovDeg = clamp(90 / zoom, 1, 179);
    const horizontalHalfRadians = (horizontalFovDeg / 2) * Math.PI / 180;
    const verticalHalfRadians = Math.atan(
      Math.tan(horizontalHalfRadians) * (rect.height / rect.width)
    );
    const verticalFovDeg = clamp(verticalHalfRadians * 2 * 180 / Math.PI, 1, 179);
    const xNdc = (xRatio - 0.5) * 2;
    const yNdc = (yRatio - 0.5) * 2;
    const yawDeltaDeg = Math.atan(xNdc * Math.tan((horizontalFovDeg / 2) * Math.PI / 180)) * 180 / Math.PI;
    const pitchDeltaDeg = -Math.atan(yNdc * Math.tan((verticalFovDeg / 2) * Math.PI / 180)) * 180 / Math.PI;
    const targetYaw = normalizeYaw(Number(current.yaw_to_camera_heading) + yawDeltaDeg);

    return {
      x_ratio: xRatio,
      y_ratio: yRatio,
      yaw_delta_deg: normalizeSignedYaw(yawDeltaDeg),
      pitch_delta_deg: pitchDeltaDeg,
      target_yaw_to_camera_heading: targetYaw,
      view_yaw_to_camera_heading: normalizeYaw(current.yaw_to_camera_heading),
      view_pitch: normalizePitch(current.pitch),
      view_zoom: zoom,
      projection: "center_plane"
    };
  }

  function setupClickTargetProjection() {
    if (!panoStage) {
      return;
    }
    panoStage.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      const target = screenClickTarget(event);
      if (!target) {
        return;
      }
      state.target = target;
      updateReadout(readKrpanoView() || state);
      postViewerState(true);
      logDebug(`target click yaw=${target.target_yaw_to_camera_heading.toFixed(2)} delta=${target.yaw_delta_deg.toFixed(2)}`);
    }, true);
  }

  window.viewerOnViewChanged = function () {
    const activeView = readKrpanoView() || state;
    schedulePost();
    updateReadout(activeView);
    updateGroundRings(activeView);
    logViewDebug(activeView, "view changed");
    if (activeView && Number(activeView.pitch) >= 70) {
      logGroundRingSamples(activeView);
    }
  };

  function showFallbackFrame(message) {
    if (!fallbackFrame.getAttribute("src")) {
      const source = fallbackFrame.dataset.src || bootstrap.frame_url;
      if (source) {
        fallbackFrame.setAttribute("src", source);
        logDebug(`fallback frame requested: ${source}`);
      }
    }
    fallbackFrame.hidden = false;
    if (message) {
      logDebug(message);
    }
  }

  function hideFallbackFrame() {
    fallbackFrame.hidden = true;
  }

  window.viewerKrpanoLoadComplete = function () {
    krpanoImageLoaded = true;
    logDebug("krpano image load complete");
    hideFallbackFrame();
  };

  window.viewerKrpanoLoadError = function () {
    krpanoImageLoaded = false;
    showFallbackFrame("krpano image load error. Showing extracted frame fallback.");
    setNotice(["krpano could not load the panorama image. Showing extracted frame fallback."]);
  };

  function sameState(a, b) {
    if (!a || !b) {
      return false;
    }
    return a.video === b.video
      && Number(a.frame_index) === Number(b.frame_index)
      && Math.abs(Number(a.yaw_to_camera_heading) - Number(b.yaw_to_camera_heading)) < 0.01
      && Math.abs(Number(a.pitch) - Number(b.pitch)) < 0.01
      && Math.abs(Number(a.zoom) - Number(b.zoom)) < 0.001;
  }

  function sameFrame(a, b) {
    if (!a || !b) {
      return false;
    }
    return a.video === b.video && Number(a.frame_index) === Number(b.frame_index);
  }

  function viewerUrl(video, frameIndex, viewState) {
    const params = new URLSearchParams();
    params.set("video", video);
    params.set("frame_index", String(frameIndex));
    if (viewState) {
      const view = normalizedView(viewState);
      params.set("yaw_to_camera_heading", String(view.yaw_to_camera_heading));
      params.set("pitch", String(view.pitch));
      params.set("zoom", String(view.zoom));
    }
    return `/viewer?${params.toString()}`;
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

  function krpanoSceneUrl(video, frameIndex, viewState) {
    const params = new URLSearchParams();
    params.set("video", video);
    params.set("frame_index", String(frameIndex));
    if (viewState) {
      const view = normalizedView(viewState);
      params.set("yaw_to_camera_heading", String(view.yaw_to_camera_heading));
      params.set("pitch", String(view.pitch));
      params.set("zoom", String(view.zoom));
    }
    return `${window.location.origin}/krpano-scene.xml?${params.toString()}`;
  }

  function updateBrowserUrl(video, frameIndex) {
    const nextUrl = viewerUrl(video, frameIndex);
    if (window.location.pathname + window.location.search !== nextUrl) {
      window.history.replaceState(null, "", nextUrl);
    }
  }

  function loadFrameInPlace(nextState) {
    const nextVideo = nextState.video;
    const nextFrame = Number(nextState.frame_index);
    if (!nextVideo || !Number.isFinite(nextFrame)) {
      return false;
    }

    const currentView = readKrpanoView() || state;
    const inheritedView = normalizedView(currentView);
    const nextRadar = nextState.radar && typeof nextState.radar === "object" ? nextState.radar : null;
    const nextTarget = nextState.target && typeof nextState.target === "object" ? nextState.target : null;
    updateCameraHeight(nextState.viewer_camera_height_m === undefined ? viewerCameraHeightM : nextState.viewer_camera_height_m);

    Object.assign(state, nextState, inheritedView, {
      video: nextVideo,
      frame_index: nextFrame
    });
    state.radar = nextRadar;
    state.target = nextTarget;
    updateReadout(state);
    updateBrowserUrl(nextVideo, nextFrame);
    postViewerState(true);
    refreshNavigation(nextVideo, nextFrame);

    const nextFrameUrl = frameImageUrl(nextVideo, nextFrame);
    fallbackFrame.hidden = true;
    fallbackFrame.removeAttribute("src");
    fallbackFrame.dataset.src = nextFrameUrl;

    if (!krpano || !krpanoReady || typeof krpano.call !== "function") {
      return false;
    }

    krpanoImageLoaded = false;
    const sceneUrl = krpanoSceneUrl(nextVideo, nextFrame, inheritedView);
    logDebug(`krpano loadpano ${sceneUrl}`);
    krpano.call(`loadpano("${sceneUrl}", null, MERGE|KEEPVIEW, BLEND(0.2));`);
    return true;
  }

  async function postViewerState(immediate) {
    const current = currentSessionState();
    updateReadout(current);

    if (!immediate && sameState(current, lastPosted)) {
      return;
    }

    lastPosted = Object.assign({}, current);
    await fetch("/api/session/viewer-state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(current)
    }).catch((error) => {
      setNotice([`Failed to update session.json: ${error}`]);
    });
  }

  function schedulePost() {
    if (postTimer) {
      window.clearTimeout(postTimer);
    }
    postTimer = window.setTimeout(() => {
      postViewerState(false);
    }, 300);
  }

  async function navigateToFrame(frameIndex) {
    if (frameIndex === null || frameIndex === undefined) {
      return;
    }
    const nextFrame = Number(frameIndex);
    if (!Number.isFinite(nextFrame)) {
      return;
    }
    const currentView = readKrpanoView() || state;
    const nextState = Object.assign({}, currentView, {
      video: state.video,
      frame_index: nextFrame
    });
    if (!loadFrameInPlace(nextState)) {
      await postViewerState(true);
      window.location.href = viewerUrl(state.video, nextFrame, currentView);
    }
  }

  function updateNavigationButtons() {
    prevButton.disabled = navigationState.prev_frame === null || navigationState.prev_frame === undefined;
    nextButton.disabled = navigationState.next_frame === null || navigationState.next_frame === undefined;
  }

  async function refreshNavigation(video, frameIndex) {
    const response = await fetch(navigationUrl(video, frameIndex), {
      cache: "no-store"
    }).catch(() => null);
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
      matched_csv_exists: Boolean(payload.matched_csv_exists)
    };
    updateNavigationButtons();
  }

  async function pollExternalNavigation() {
    const response = await fetch("/api/session/viewer-state", {
      cache: "no-store"
    }).catch(() => null);
    if (!response || !response.ok) {
      return;
    }

    const session = await response.json().catch(() => null);
    if (!session || !session.video || session.frame_index === undefined || session.frame_index === null) {
      return;
    }

    updateRadarState(session.radar);
    updateCameraHeight(session.viewer_camera_height_m);
    state.target = session.target && typeof session.target === "object" ? session.target : null;
    updateReadout(readKrpanoView() || state);
    updateGroundRings(readKrpanoView() || state);
    if (!sameFrame(session, state)) {
      if (!loadFrameInPlace(session)) {
        window.location.href = viewerUrl(session.video, session.frame_index, readKrpanoView() || state);
      }
    }
  }

  function setupNavigation() {
    prevButton.addEventListener("click", () => navigateToFrame(navigationState.prev_frame));
    nextButton.addEventListener("click", () => navigateToFrame(navigationState.next_frame));
    updateNavigationButtons();
  }

  function isEditableTarget(target) {
    if (!target) {
      return false;
    }
    const tagName = String(target.tagName || "").toLowerCase();
    return target.isContentEditable || ["input", "textarea", "select"].includes(tagName);
  }

  function setupKeyboardNavigation() {
    window.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }
      if (isEditableTarget(event.target)) {
        return;
      }

      if (event.key === "ArrowLeft") {
        if (navigationState.prev_frame !== null && navigationState.prev_frame !== undefined) {
          event.preventDefault();
          navigateToFrame(navigationState.prev_frame);
        }
        return;
      }

      if (event.key === "ArrowRight") {
        if (navigationState.next_frame !== null && navigationState.next_frame !== undefined) {
          event.preventDefault();
          navigateToFrame(navigationState.next_frame);
        }
      }
    });
  }

  function setupFallbackFrameDiagnostics() {
    function logLoaded() {
      if (fallbackFrame.naturalWidth && fallbackFrame.naturalHeight) {
        logDebug(`fallback frame loaded ${fallbackFrame.naturalWidth}x${fallbackFrame.naturalHeight}`);
      } else {
        logDebug("fallback frame loaded");
      }
    }

    fallbackFrame.addEventListener("load", () => {
      logLoaded();
    });
    fallbackFrame.addEventListener("error", () => {
      setNotice([`Failed to load extracted frame: ${bootstrap.frame_url}`]);
      logDebug(`fallback frame failed: ${bootstrap.frame_url}`);
    });

    if (fallbackFrame.complete && fallbackFrame.naturalWidth) {
      logLoaded();
    }
  }

  function setupKrpano() {
    const messages = [];
    if (!bootstrap.krpano_available) {
      messages.push("krpano.js is not found. Place your licensed file at static/vendor/krpano/krpano.js.");
    }
    if (!bootstrap.video_exists) {
      messages.push("Video file is not found under video_dir.");
    }
    if (!bootstrap.matched_csv_exists) {
      messages.push("Matched frames CSV is not found. Prev/Next navigation is disabled.");
    }
    setNotice(messages);

    if (!bootstrap.krpano_available || typeof window.embedpano !== "function") {
      showFallbackFrame();
      return;
    }

    hideFallbackFrame();
    logDebug(`krpano_available=${bootstrap.krpano_available}`);
    logDebug(`scene_url=${bootstrap.scene_url}`);
    logDebug(`frame_url=${bootstrap.frame_url}`);

    window.setTimeout(() => {
      if (!krpanoReady) {
        showFallbackFrame();
        setNotice(["krpano did not become ready. Showing extracted frame fallback."]);
      }
    }, 3000);

    window.setTimeout(() => {
      if (krpanoReady && !krpanoImageLoaded) {
        showFallbackFrame("krpano did not report image load complete. Showing extracted frame fallback.");
      }
    }, 15000);

    window.embedpano({
      swf: "/static/vendor/krpano/krpano.swf",
      xml: bootstrap.scene_url,
      target: "pano",
      basepath: "/static/vendor/krpano/",
      html5: "only",
      consolelog: true,
      passQueryParameters: false,
      onerror: function (message) {
        logDebug(`krpano onerror: ${message}`);
        showFallbackFrame();
        setNotice([`krpano error: ${message}`]);
      },
      onready: function (viewer) {
        krpanoReady = true;
        logDebug("krpano onready");
        krpano = viewer;
        if (typeof viewer.set === "function") {
          viewer.set("events.onloadcomplete", "js(viewerKrpanoLoadComplete())");
          viewer.set("events.onerror", "js(viewerKrpanoLoadError())");
          viewer.set("events.onviewchanged", "js(window.viewerOnViewChanged())");
        }
        updateReadout(readKrpanoView());
        updateGroundRings(readKrpanoView() || state);
        logViewDebug(readKrpanoView() || state, "initial view");
        if ((readKrpanoView() || state).pitch >= 70) {
          logGroundRingSamples(readKrpanoView() || state);
        }
        postViewerState(true);
        window.setInterval(schedulePost, 300);
      }
    });
  }

  setupFallbackFrameDiagnostics();
  setupNavigation();
  setupKeyboardNavigation();
  setupDebugLogToggle();
  setupRadarHudToggle();
  setupGroundGridToggle();
  setupClickTargetProjection();
  updateReadout(state);
  setupKrpano();
  window.setInterval(pollExternalNavigation, 750);
}());
