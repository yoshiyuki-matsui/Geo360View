(function () {
  const bootstrap = window.VIEWER_BOOTSTRAP || {};
  const state = Object.assign({
    video: "",
    frame_index: 0,
    yaw_to_camera_heading: 0,
    pitch: 0,
    zoom: 1,
    viewer_camera_height_m: bootstrap.viewer_camera_height_m,
    viewer_projection: bootstrap.viewer_projection || "sphere",
    viewer_flat_hfov_deg: bootstrap.viewer_flat_hfov_deg || 70,
    viewer_flat_vfov_deg: bootstrap.viewer_flat_vfov_deg || 43,
    target: null,
    targets: []
  }, bootstrap.state || {});
  const GROUND_GRID_STEP_M = 1;
  const GROUND_RING_SAMPLE_COUNT = 96;
  const GROUND_GRID_SAMPLE_COUNT = 64;
  const MAX_CLICK_TARGETS = 100;
  const SINGLE_CLICK_DELAY_MS = 320;
  const VIEW_STATE_POST_INTERVAL_MS = 1000;
  const EXTERNAL_SESSION_POLL_INTERVAL_MS = 300;
  const TARGET_CLEAR_GRACE_MS = 900;

  let krpano = null;
  let lastPosted = null;
  let postTimer = null;
  let suppressPostUntil = 0;
  let lastExternalSignature = null;
  let lastMarkerSignature = null;
  let pendingEmptyTargetKey = null;
  let pendingEmptyTargetSince = 0;
  let singleClickTimer = null;
  let krpanoReady = false;
  let krpanoImageLoaded = false;
  let debugLogVisible = false;
  let radarHudVisible = true;
  let viewHoldEnabled = false;
  let lastViewDebug = null;
  let navigationState = {
    prev_frame: bootstrap.prev_frame,
    next_frame: bootstrap.next_frame,
    matched_csv_exists: Boolean(bootstrap.matched_csv_exists)
  };

  const prevButton = document.getElementById("prevButton");
  const nextButton = document.getElementById("nextButton");
  const viewHoldButton = document.getElementById("viewHoldButton");
  const radarHudToggleButton = document.getElementById("radarHudToggleButton");
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
  let lockGuideOverlay = document.getElementById("lockGuideOverlay");
  let lockGuideBand = document.getElementById("lockGuideBand");
  let lockGuideLine = document.getElementById("lockGuideLine");
  let lockGuideEndpoint = document.getElementById("lockGuideEndpoint");
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
  let viewerHudHeightScale = normalizeHudHeightScale(state.viewer_hud_height_scale);
  if (!Array.isArray(state.targets)) {
    state.targets = [];
  }
  if (!state.target && state.targets.length) {
    state.target = state.targets[state.targets.length - 1];
  }

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

  function signedAngleDelta(fromDegrees, toDegrees) {
    return normalizeSignedYaw(Number(toDegrees) - Number(fromDegrees));
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

  function normalizeHudHeightScale(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 1.0;
    }
    return clamp(numeric, 0.1, 5.0);
  }

  function normalizeViewerProjection(value) {
    const text = String(value || "sphere").toLowerCase();
    if (["flat", "pinhole", "front"].includes(text)) {
      return "flat";
    }
    return "sphere";
  }

  function normalizeFovDeg(value, fallback) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return fallback;
    }
    return clamp(numeric, 1, 179);
  }

  function isFlatProjection() {
    return normalizeViewerProjection(state.viewer_projection) === "flat";
  }

  function updateProjectionLayout(viewState) {
    if (!panoStage) {
      return;
    }
    const projection = normalizeViewerProjection((viewState && viewState.viewer_projection) || state.viewer_projection);
    panoStage.classList.toggle("pano-stage-flat", projection === "flat");
  }

  function updateCameraHeight(value) {
    viewerCameraHeightM = normalizeCameraHeight(value);
    state.viewer_camera_height_m = viewerCameraHeightM;
  }

  function updateHudHeightScale(value) {
    viewerHudHeightScale = normalizeHudHeightScale(value);
    state.viewer_hud_height_scale = viewerHudHeightScale;
  }

  function effectiveHudCameraHeightM() {
    return viewerCameraHeightM * viewerHudHeightScale;
  }

  function normalizedView(source) {
    const projection = normalizeViewerProjection(source && source.viewer_projection);
    const view = {
      yaw_to_camera_heading: projection === "flat" ? 0 : normalizeYaw(source && source.yaw_to_camera_heading),
      pitch: projection === "flat" ? 0 : normalizePitch(source && source.pitch),
      zoom: normalizeZoom(source && source.zoom),
      viewer_projection: projection,
      viewer_flat_hfov_deg: normalizeFovDeg(source && source.viewer_flat_hfov_deg, 70),
      viewer_flat_vfov_deg: normalizeFovDeg(source && source.viewer_flat_vfov_deg, 43)
    };
    return view;
  }

  function readKrpanoView() {
    if (!krpano || typeof krpano.get !== "function") {
      return null;
    }

    const projection = normalizeViewerProjection(state.viewer_projection);
    const yaw = projection === "flat" ? 0 : normalizeYaw(krpano.get("view.hlookat"));
    const pitch = projection === "flat" ? 0 : Number(krpano.get("view.vlookat")) || 0;
    const fov = Number(krpano.get("view.fov")) || (projection === "flat" ? normalizeFovDeg(state.viewer_flat_hfov_deg, 70) : 90);
    const zoom = projection === "flat" ? 90 / normalizeFovDeg(state.viewer_flat_hfov_deg, 70) : 90 / Math.max(fov, 1);
    const viewerFrontOffset = Number(state.viewer_front_offset_deg);

    const view = {
      video: state.video,
      frame_index: Number(state.frame_index),
      yaw_to_camera_heading: yaw,
      pitch: normalizePitch(pitch),
      zoom: normalizeZoom(zoom),
      viewer_camera_height_m: viewerCameraHeightM,
      viewer_hud_height_scale: viewerHudHeightScale,
      viewer_projection: projection,
      viewer_flat_hfov_deg: normalizeFovDeg(state.viewer_flat_hfov_deg, 70),
      viewer_flat_vfov_deg: normalizeFovDeg(state.viewer_flat_vfov_deg, 43)
    };
    if (Number.isFinite(viewerFrontOffset)) {
      view.viewer_front_offset_deg = normalizeSignedYaw(viewerFrontOffset);
    }
    return view;
  }

  function updateReadout(viewState) {
    const active = viewState || state;
    const fov = 90 / normalizeZoom(active.zoom);
    const targets = displayClickTargets();
    const latestTarget = targets.length ? targets[targets.length - 1] : null;
    const target = latestTarget && Number.isFinite(Number(latestTarget.yaw_delta_deg))
      ? `, clicks: ${targets.length} (${Number(latestTarget.yaw_delta_deg).toFixed(1)}deg)`
      : "";
    videoLabel.textContent = `video: ${active.video}`;
    frameLabel.textContent = `frame_index: ${active.frame_index}`;
    const projection = normalizeViewerProjection(active.viewer_projection || state.viewer_projection);
    viewLabel.textContent = `projection: ${projection}, yaw: ${Number(active.yaw_to_camera_heading).toFixed(2)}, pitch: ${Number(active.pitch).toFixed(2)}, fov: ${fov.toFixed(1)}, zoom: ${Number(active.zoom).toFixed(2)}${target}`;
    updateProjectionLayout(active);
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
    if (!debugLog || !debugLogVisible) {
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
    const hudCameraHeightM = effectiveHudCameraHeightM();
    const samples = [
      ["front5", { x: 0, y: -hudCameraHeightM, z: 5 }],
      ["right5", { x: 5, y: -hudCameraHeightM, z: 0 }],
      ["back5", { x: 0, y: -hudCameraHeightM, z: -5 }],
      ["left5", { x: -5, y: -hudCameraHeightM, z: 0 }]
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
      updateClickTargetMarker();
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

  function groundPointForDistance(distanceM, targetYaw) {
    const yawRadians = normalizeYaw(targetYaw) * Math.PI / 180;
    return {
      x: Math.sin(yawRadians) * distanceM,
      y: -effectiveHudCameraHeightM(),
      z: Math.cos(yawRadians) * distanceM
    };
  }

  function maxGroundEstimateDistanceM() {
    const radar = state.radar || {};
    const candidates = [
      Number(radar.outer_range_m),
      Number(radar.range_m) * 2,
      Number(radar.calibration_distance_m) * 2,
      20
    ].filter((value) => Number.isFinite(value) && value > 0);
    return clamp(Math.max.apply(null, candidates), 5, 200);
  }

  function estimateGroundDistanceFromScreen(targetYaw, screenX, screenY, viewState, stageRect) {
    if (!stageRect || !stageRect.width || !stageRect.height) {
      return null;
    }
    const maxDistanceM = maxGroundEstimateDistanceM();
    const minDistanceM = 0.05;
    const coarseSamples = 360;
    const coarseStepM = (maxDistanceM - minDistanceM) / coarseSamples;
    let bestDistanceM = null;
    let bestErrorSq = Number.POSITIVE_INFINITY;

    function measure(distanceM) {
      const point = groundPointForDistance(distanceM, targetYaw);
      const projected = projectGroundPoint(point, viewState, stageRect);
      if (!projected) {
        return;
      }
      const dx = projected.x - screenX;
      const dy = projected.y - screenY;
      const errorSq = dx * dx + dy * dy;
      if (errorSq < bestErrorSq) {
        bestErrorSq = errorSq;
        bestDistanceM = distanceM;
      }
    }

    for (let index = 0; index <= coarseSamples; index += 1) {
      measure(minDistanceM + coarseStepM * index);
    }
    if (bestDistanceM === null) {
      return null;
    }

    const refineStartM = Math.max(minDistanceM, bestDistanceM - coarseStepM);
    const refineEndM = Math.min(maxDistanceM, bestDistanceM + coarseStepM);
    const refineSamples = 40;
    const refineStepM = (refineEndM - refineStartM) / refineSamples;
    for (let index = 0; index <= refineSamples; index += 1) {
      measure(refineStartM + refineStepM * index);
    }

    const maxErrorPx = Math.max(80, Math.min(stageRect.width, stageRect.height) * 0.12);
    if (bestErrorSq > maxErrorPx * maxErrorPx) {
      return null;
    }
    return bestDistanceM;
  }

  function attachGroundDistance(target, targetYaw, screenX, screenY, viewState, stageRect) {
    const groundDistanceM = estimateGroundDistanceFromScreen(targetYaw, screenX, screenY, viewState, stageRect);
    if (Number.isFinite(groundDistanceM) && groundDistanceM > 0) {
      target.ground_distance_m = Number(groundDistanceM.toFixed(3));
    }
    return target;
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

  function normalizedClickTargets() {
    if (!Array.isArray(state.targets)) {
      return [];
    }
    return state.targets
      .filter((target) => target && typeof target === "object")
      .sort((left, right) => Number(left.order || left.id || 0) - Number(right.order || right.id || 0));
  }

  function displayClickTargets() {
    const targets = normalizedClickTargets();
    if (targets.length) {
      return targets;
    }
    return state.target && typeof state.target === "object" ? [state.target] : [];
  }

  function sessionTargets(session) {
    const targets = Array.isArray(session && session.targets) ? session.targets : [];
    const target = session && session.target && typeof session.target === "object" ? session.target : null;
    if (targets.length) {
      return targets;
    }
    return target ? [target] : [];
  }

  function clickTargetLabelText(target) {
    const id = Number(target.id || target.order);
    const idText = Number.isFinite(id) && id > 0 ? `[${id}]` : "";
    const semanticClass = target.semantic_class ? String(target.semantic_class) : "";
    const confidence = Number(target.confidence);
    const confidenceText = Number.isFinite(confidence) ? `(${confidence.toFixed(2)})` : "";

    if (semanticClass) {
      return `${idText || "[]"}:${semanticClass}${confidenceText}`;
    }
    if (idText) {
      return idText;
    }
    return "";
  }

  function ensureClickTargetLabel(marker) {
    let label = marker.querySelector(".click-target-marker-label");
    if (!label) {
      label = document.createElement("span");
      label.className = "click-target-marker-label";
      marker.appendChild(label);
    }
    return label;
  }

  function setClickTargetMarker(marker, target) {
    const projected = projectClickTargetMarker(target);
    if (!projected) {
      marker.hidden = true;
      return;
    }
    marker.style.left = `${projected.x.toFixed(1)}px`;
    marker.style.top = `${projected.y.toFixed(1)}px`;
    marker.classList.toggle(
      "click-target-marker-auto",
      target.target_source === "yolo_candidate" || target.viewer_marker === "target_point"
    );
    const titleParts = [];
    if (target.semantic_class) {
      titleParts.push(String(target.semantic_class));
    }
    const confidence = Number(target.confidence);
    if (Number.isFinite(confidence)) {
      titleParts.push(`${Math.round(confidence * 100)}%`);
    }
    if (target.id) {
      titleParts.push(`#${target.id}`);
    }
    marker.title = titleParts.join(" ");
    const label = ensureClickTargetLabel(marker);
    const labelText = clickTargetLabelText(target);
    label.textContent = labelText;
    label.hidden = !labelText;
    marker.hidden = false;
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
    const yaw = Number(target.target_yaw_to_camera_heading);
    const pitch = targetPitch(target);
    if (!Number.isFinite(yaw) || pitch === null) {
      return null;
    }
    return {
      h: normalizeYaw(yaw),
      v: normalizePitch(pitch)
    };
  }

  function projectClickTargetMarkerWithKrpano(target, stageRect) {
    if (!krpano || !krpano.actions || typeof krpano.actions.spheretoscreen !== "function") {
      return null;
    }
    const sphere = targetSphere(target);
    if (!sphere) {
      return null;
    }
    const projected = krpano.actions.spheretoscreen(sphere.h, sphere.v);
    if (!projected) {
      return null;
    }
    const x = Number(projected.x);
    const y = Number(projected.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return null;
    }
    const markerMarginPx = 24;
    if (
      x < -markerMarginPx
      || x > stageRect.width + markerMarginPx
      || y < -markerMarginPx
      || y > stageRect.height + markerMarginPx
    ) {
      return null;
    }
    return { x, y };
  }

  function projectClickTargetMarkerFallback(target, viewState, stageRect) {
    const sphere = targetSphere(target);
    if (!sphere || !viewState || !stageRect.width || !stageRect.height) {
      return null;
    }
    const yawDeltaDeg = signedAngleDelta(viewState.yaw_to_camera_heading, sphere.h);
    if (Math.abs(yawDeltaDeg) >= 89.0) {
      return null;
    }
    const zoom = normalizeZoom(viewState.zoom);
    const horizontalFovDeg = clamp(90 / zoom, 1, 179);
    const horizontalHalfRadians = (horizontalFovDeg / 2) * Math.PI / 180;
    const verticalHalfRadians = Math.atan(
      Math.tan(horizontalHalfRadians) * (stageRect.height / stageRect.width)
    );
    const pitchDeltaDeg = normalizePitch(sphere.v) - normalizePitch(viewState.pitch);
    const xNdc = Math.tan(yawDeltaDeg * Math.PI / 180) / Math.tan(horizontalHalfRadians);
    const yNdc = -Math.tan(pitchDeltaDeg * Math.PI / 180) / Math.tan(verticalHalfRadians);
    if (!Number.isFinite(xNdc) || !Number.isFinite(yNdc) || Math.abs(xNdc) > 1.2 || Math.abs(yNdc) > 1.2) {
      return null;
    }
    return {
      x: ((xNdc + 1) / 2) * stageRect.width,
      y: ((yNdc + 1) / 2) * stageRect.height
    };
  }

  function projectClickTargetMarkerImageXY(target, stageRect) {
    if (!isFlatProjection()) {
      return null;
    }
    const xRatio = Number(target && target.x_ratio);
    const yRatio = Number(target && target.y_ratio);
    if (!Number.isFinite(xRatio) || !Number.isFinite(yRatio)) {
      return null;
    }
    return {
      x: clamp(xRatio, 0, 1) * stageRect.width,
      y: clamp(yRatio, 0, 1) * stageRect.height
    };
  }

  function projectClickTargetMarker(target) {
    if (!panoStage) {
      return null;
    }
    const stageRect = panoStage.getBoundingClientRect();
    if (!stageRect.width || !stageRect.height) {
      return null;
    }
    return projectClickTargetMarkerImageXY(target, stageRect)
      || projectClickTargetMarkerWithKrpano(target, stageRect)
      || projectClickTargetMarkerFallback(target, readKrpanoView() || state, stageRect);
  }

  function ensureLockGuideOverlay() {
    if (lockGuideOverlay && lockGuideBand && lockGuideLine && lockGuideEndpoint) {
      return true;
    }
    if (!panoStage || !document.createElementNS) {
      return false;
    }
    // The server now emits this SVG, but older pages may still be open.
    // Create it client-side as a fallback so Ctrl+F5 is enough during review work.
    const svgNs = "http://www.w3.org/2000/svg";
    lockGuideOverlay = document.createElementNS(svgNs, "svg");
    lockGuideOverlay.id = "lockGuideOverlay";
    lockGuideOverlay.classList.add("lock-guide-overlay");
    lockGuideOverlay.setAttribute("viewBox", "0 0 100 100");
    lockGuideOverlay.setAttribute("preserveAspectRatio", "none");
    lockGuideOverlay.setAttribute("aria-hidden", "true");
    lockGuideOverlay.hidden = true;

    lockGuideBand = document.createElementNS(svgNs, "path");
    lockGuideBand.id = "lockGuideBand";
    lockGuideBand.classList.add("lock-guide-band");
    lockGuideOverlay.appendChild(lockGuideBand);

    lockGuideLine = document.createElementNS(svgNs, "path");
    lockGuideLine.id = "lockGuideLine";
    lockGuideLine.classList.add("lock-guide-line");
    lockGuideOverlay.appendChild(lockGuideLine);

    lockGuideEndpoint = document.createElementNS(svgNs, "circle");
    lockGuideEndpoint.id = "lockGuideEndpoint";
    lockGuideEndpoint.classList.add("lock-guide-endpoint");
    lockGuideEndpoint.setAttribute("r", "5");
    lockGuideOverlay.appendChild(lockGuideEndpoint);

    panoStage.appendChild(lockGuideOverlay);
    return true;
  }

  function clearLockGuide() {
    ensureLockGuideOverlay();
    if (lockGuideOverlay) {
      lockGuideOverlay.hidden = true;
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

  function guideEndpointFromDirection(target, viewState, stageRect) {
    // Accurate path when the target can be projected from spherical coordinates.
    // This still returns an interior point; updateLockGuide extends it to the viewport edge.
    const sphere = targetSphere(target);
    if (!sphere || !viewState || !stageRect.width || !stageRect.height) {
      return null;
    }
    const zoom = normalizeZoom(viewState.zoom);
    const horizontalFovDeg = clamp(90 / zoom, 1, 179);
    const horizontalHalfRadians = (horizontalFovDeg / 2) * Math.PI / 180;
    const verticalHalfRadians = Math.atan(
      Math.tan(horizontalHalfRadians) * (stageRect.height / stageRect.width)
    );
    const yawDeltaDeg = signedAngleDelta(viewState.yaw_to_camera_heading, sphere.h);
    const pitchDeltaDeg = normalizePitch(sphere.v) - normalizePitch(viewState.pitch);
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
    // Last-resort direction cue. Even when exact screen projection is unavailable,
    // yaw/pitch deltas still tell the user which way to look while Lock is enabled.
    const sphere = targetSphere(target);
    if (!sphere || !viewState || !stageRect.width || !stageRect.height) {
      return null;
    }
    const yawDeltaDeg = signedAngleDelta(viewState.yaw_to_camera_heading, sphere.h);
    const pitchDeltaDeg = normalizePitch(sphere.v) - normalizePitch(viewState.pitch);
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
    // Draw the guide all the way to the viewport edge. A short line to a near-center
    // target was too easy to miss, especially when the marker and label were visible.
    let dx = Number(towardX) - Number(fromX);
    let dy = Number(towardY) - Number(fromY);
    if (!Number.isFinite(dx) || !Number.isFinite(dy) || Math.hypot(dx, dy) < 1) {
      dy = -1;
      dx = 0;
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
    // Lock guide is additive: point markers and labels stay unchanged.
    // It only appears while the user has explicitly enabled Lock.
    if (!viewHoldEnabled || !ensureLockGuideOverlay() || !panoStage) {
      clearLockGuide();
      return;
    }
    const stageRect = panoStage.getBoundingClientRect();
    if (!stageRect.width || !stageRect.height || !target) {
      clearLockGuide();
      return;
    }
    lockGuideOverlay.setAttribute("viewBox", `0 0 ${stageRect.width} ${stageRect.height}`);
    const viewState = readKrpanoView() || state;
    const projected = projectClickTargetMarker(target)
      || guideEndpointFromDirection(target, viewState, stageRect)
      || guidePointFromYawPitch(target, viewState, stageRect);
    if (!projected) {
      clearLockGuide();
      return;
    }
    const centerX = stageRect.width / 2;
    // The line starts at the bottom center, representing the viewer/camera position.
    const centerY = stageRect.height;
    const endpoint = rayToStageEdge(centerX, centerY, projected.x, projected.y, stageRect);
    const endX = endpoint.x;
    const endY = endpoint.y;
    const path = `M ${centerX.toFixed(1)} ${centerY.toFixed(1)} L ${endX.toFixed(1)} ${endY.toFixed(1)}`;
    lockGuideBand.setAttribute("d", path);
    lockGuideLine.setAttribute("d", path);
    lockGuideEndpoint.setAttribute("cx", String(endX.toFixed(1)));
    lockGuideEndpoint.setAttribute("cy", String(endY.toFixed(1)));
    lockGuideOverlay.hidden = false;
  }

  function updateClickTargetMarker() {
    if (!clickTargetMarker || !panoStage) {
      return;
    }
    if (!radarHudVisible) {
      lastMarkerSignature = null;
      panoStage.querySelectorAll(".click-target-marker-extra").forEach((marker) => marker.remove());
      clickTargetMarker.hidden = true;
      clearLockGuide();
      return;
    }
    const targets = displayClickTargets();
    if (!targets.length) {
      lastMarkerSignature = null;
      panoStage.querySelectorAll(".click-target-marker-extra").forEach((marker) => marker.remove());
      clickTargetMarker.hidden = true;
      clearLockGuide();
      return;
    }
    const markerSignature = [
      state.video || "",
      String(Number(state.frame_index)),
      targets.slice(0, MAX_CLICK_TARGETS).map(targetSignature).join("~")
    ].join("::");
    if (markerSignature === lastMarkerSignature) {
      updateLockGuide(targets[0]);
      return;
    }
    lastMarkerSignature = markerSignature;
    panoStage.querySelectorAll(".click-target-marker-extra").forEach((marker) => marker.remove());
    updateLockGuide(targets[0]);
    targets.slice(0, MAX_CLICK_TARGETS).forEach((target, index) => {
      const marker = index === 0 ? clickTargetMarker : document.createElement("div");
      if (index > 0) {
        marker.className = "click-target-marker click-target-marker-extra";
        panoStage.appendChild(marker);
      }
      setClickTargetMarker(marker, target);
    });
  }

  function repositionClickTargetMarkers() {
    // krpanoの画像ロード完了後に、既存DOMを作り直さず座標だけを再投影します。
    // 8K 360静止画のロードが遅れた場合でも、pano本体を再描画せずにmarker/labelの消失を抑えます。
    if (!clickTargetMarker || !panoStage || !radarHudVisible) {
      return;
    }
    const targets = displayClickTargets();
    if (!targets.length) {
      return;
    }
    const extraMarkers = Array.from(panoStage.querySelectorAll(".click-target-marker-extra"));
    targets.slice(0, MAX_CLICK_TARGETS).forEach((target, index) => {
      const marker = index === 0 ? clickTargetMarker : extraMarkers[index - 1];
      if (marker) {
        setClickTargetMarker(marker, target);
      }
    });
    updateLockGuide(targets[0]);
  }

  function currentSessionState(sourceState) {
    const current = Object.assign({}, sourceState || readKrpanoView() || state);
    current.viewer_camera_height_m = viewerCameraHeightM;
    current.viewer_hud_height_scale = viewerHudHeightScale;
    const viewerFrontOffset = Number(state.viewer_front_offset_deg);
    current.viewer_projection = normalizeViewerProjection(state.viewer_projection);
    current.viewer_flat_hfov_deg = normalizeFovDeg(state.viewer_flat_hfov_deg, 70);
    current.viewer_flat_vfov_deg = normalizeFovDeg(state.viewer_flat_vfov_deg, 43);
    if (Number.isFinite(viewerFrontOffset)) {
      current.viewer_front_offset_deg = normalizeSignedYaw(viewerFrontOffset);
    }
    if (!current.target && state.target) {
      current.target = state.target;
    }
    const targets = normalizedClickTargets();
    if ((!Array.isArray(current.targets) || !current.targets.length) && targets.length) {
      current.targets = targets.slice(0, MAX_CLICK_TARGETS);
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
    const screenX = event.clientX - rect.left;
    const screenY = event.clientY - rect.top;
    const current = readKrpanoView() || state;
    const zoom = normalizeZoom(current.zoom);
    const krpanoSphere = screenClickSphere(event, rect, current);
    if (krpanoSphere) {
      return attachGroundDistance({
        x_ratio: xRatio,
        y_ratio: yRatio,
        yaw_delta_deg: krpanoSphere.yawDeltaDeg,
        pitch_delta_deg: krpanoSphere.pitchDeltaDeg,
        target_yaw_to_camera_heading: krpanoSphere.targetYaw,
        target_pitch_deg: krpanoSphere.targetPitch,
        view_yaw_to_camera_heading: normalizeYaw(current.yaw_to_camera_heading),
        view_pitch: normalizePitch(current.pitch),
        view_zoom: zoom,
        projection: "ground_plane"
      }, krpanoSphere.targetYaw, screenX, screenY, current, rect);
    }

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
    const targetPitch = normalizePitch(Number(current.pitch) + pitchDeltaDeg);

    return attachGroundDistance({
      x_ratio: xRatio,
      y_ratio: yRatio,
      yaw_delta_deg: normalizeSignedYaw(yawDeltaDeg),
      pitch_delta_deg: pitchDeltaDeg,
      target_yaw_to_camera_heading: targetYaw,
      target_pitch_deg: targetPitch,
      view_yaw_to_camera_heading: normalizeYaw(current.yaw_to_camera_heading),
      view_pitch: normalizePitch(current.pitch),
      view_zoom: zoom,
      projection: "ground_plane"
    }, targetYaw, screenX, screenY, current, rect);
  }

  function screenClickSphere(event, stageRect, viewState) {
    if (!krpano || !krpano.actions || typeof krpano.actions.screentosphere !== "function") {
      return null;
    }
    try {
      const sphere = krpano.actions.screentosphere(event.clientX - stageRect.left, event.clientY - stageRect.top);
      if (!sphere) {
        return null;
      }
      const targetYaw = normalizeYaw(sphere.h);
      const targetPitch = normalizePitch(sphere.v);
      return {
        targetYaw,
        targetPitch,
        yawDeltaDeg: signedAngleDelta(viewState.yaw_to_camera_heading, targetYaw),
        pitchDeltaDeg: targetPitch - normalizePitch(viewState.pitch)
      };
    } catch (error) {
      return null;
    }
  }

  function setupClickTargetProjection() {
    if (!panoStage) {
      return;
    }
    function clearSingleClickTimer() {
      if (singleClickTimer) {
        window.clearTimeout(singleClickTimer);
        singleClickTimer = null;
      }
    }

    function commitSingleClickTarget(target) {
      state.target = target;
      updateReadout(readKrpanoView() || state);
      postViewerState(true);
      logDebug(`target click yaw=${target.target_yaw_to_camera_heading.toFixed(2)} delta=${target.yaw_delta_deg.toFixed(2)}`);
    }

    function nextTargetId() {
      return normalizedClickTargets().reduce((maxId, target) => {
        return Math.max(maxId, Number(target.id) || Number(target.order) || 0);
      }, 0) + 1;
    }

    function appendClickTarget(target) {
      const id = nextTargetId();
      const savedTarget = Object.assign({}, target, {
        id,
        order: id
      });
      const targets = normalizedClickTargets();
      targets.push(savedTarget);
      state.targets = targets.slice(-MAX_CLICK_TARGETS);
      state.target = savedTarget;
      updateReadout(readKrpanoView() || state);
      postViewerState(true);
      logDebug(`target dblclick #${id} yaw=${savedTarget.target_yaw_to_camera_heading.toFixed(2)} delta=${savedTarget.yaw_delta_deg.toFixed(2)}`);
    }

    panoStage.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      if (event.detail > 1) {
        return;
      }
      const target = screenClickTarget(event);
      if (!target) {
        return;
      }
      clearSingleClickTimer();
      singleClickTimer = window.setTimeout(() => {
        singleClickTimer = null;
        commitSingleClickTarget(target);
      }, SINGLE_CLICK_DELAY_MS);
    }, true);

    panoStage.addEventListener("dblclick", (event) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      event.preventDefault();
      clearSingleClickTimer();
      const target = screenClickTarget(event);
      if (!target) {
        return;
      }
      appendClickTarget(target);
    }, true);
  }

  window.viewerOnViewChanged = function () {
    const activeView = readKrpanoView() || state;
    schedulePost();
    updateReadout(activeView);
    updateGroundRings(activeView);
    updateLockGuide(displayClickTargets()[0]);
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
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        repositionClickTargetMarkers();
      });
    });
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
      && normalizeViewerProjection(a.viewer_projection) === normalizeViewerProjection(b.viewer_projection)
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

  function targetSignature(target) {
    if (!target || typeof target !== "object") {
      return "";
    }
    const numberKey = (value, digits) => {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? numeric.toFixed(digits) : "";
    };
    return [
      target.id || "",
      target.order || "",
      target.semantic_class || "",
      numberKey(target.confidence, 4),
      numberKey(target.target_yaw_to_camera_heading, 3),
      numberKey(target.target_pitch_deg, 3),
      numberKey(target.yaw_delta_deg, 3),
      numberKey(target.pitch_delta_deg, 3),
      numberKey(target.x_ratio, 5),
      numberKey(target.y_ratio, 5)
    ].join("|");
  }

  function sessionSignature(value) {
    if (!value || typeof value !== "object") {
      return "";
    }
    const targets = Array.isArray(value.targets) ? value.targets : [];
    return [
      value.video || "",
      String(Number(value.frame_index)),
      targetSignature(value.target),
      targets.map(targetSignature).join("~")
    ].join("::");
  }

  function noteExternalSession(session) {
    const signature = sessionSignature(session);
    if (signature && signature !== sessionSignature(state) && signature !== lastExternalSignature) {
      // QGIS writes viewer_session.json independently. Without this guard, the
      // browser's periodic view-state POST can race and restore the previous POI.
      suppressPostUntil = Date.now() + 1200;
    }
    lastExternalSignature = signature;
  }

  function viewerUrl(video, frameIndex, viewState) {
    const params = new URLSearchParams();
    params.set("video", video);
    params.set("frame_index", String(frameIndex));
    const view = normalizedView(viewState || state);
    params.set("yaw_to_camera_heading", String(view.yaw_to_camera_heading));
    params.set("pitch", String(view.pitch));
    params.set("zoom", String(view.zoom));
    params.set("viewer_projection", view.viewer_projection);
    params.set("viewer_flat_hfov_deg", String(view.viewer_flat_hfov_deg));
    params.set("viewer_flat_vfov_deg", String(view.viewer_flat_vfov_deg));
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
      params.set("viewer_projection", view.viewer_projection);
      params.set("viewer_flat_hfov_deg", String(view.viewer_flat_hfov_deg));
      params.set("viewer_flat_vfov_deg", String(view.viewer_flat_vfov_deg));
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

    const requestedView = normalizedView(nextState);
    const nextRadar = nextState.radar && typeof nextState.radar === "object" ? nextState.radar : null;
    const nextTargets = Array.isArray(nextState.targets) ? nextState.targets : [];
    const nextTarget = nextState.target && typeof nextState.target === "object" ? nextState.target : null;
    updateCameraHeight(nextState.viewer_camera_height_m === undefined ? viewerCameraHeightM : nextState.viewer_camera_height_m);
    updateHudHeightScale(nextState.viewer_hud_height_scale === undefined ? viewerHudHeightScale : nextState.viewer_hud_height_scale);
    state.viewer_projection = normalizeViewerProjection(nextState.viewer_projection || state.viewer_projection);
    state.viewer_flat_hfov_deg = normalizeFovDeg(nextState.viewer_flat_hfov_deg || state.viewer_flat_hfov_deg, 70);
    state.viewer_flat_vfov_deg = normalizeFovDeg(nextState.viewer_flat_vfov_deg || state.viewer_flat_vfov_deg, 43);

    Object.assign(state, nextState, requestedView, {
      video: nextVideo,
      frame_index: nextFrame
    });
    state.radar = nextRadar;
    state.targets = nextTargets;
    state.target = nextTarget || (nextTargets.length ? nextTargets[nextTargets.length - 1] : null);
    updateReadout(state);
    updateBrowserUrl(nextVideo, nextFrame);
    postViewerState(true, state);
    refreshNavigation(nextVideo, nextFrame);

    const nextFrameUrl = frameImageUrl(nextVideo, nextFrame);
    fallbackFrame.hidden = true;
    fallbackFrame.removeAttribute("src");
    fallbackFrame.dataset.src = nextFrameUrl;

    if (!krpano || !krpanoReady || typeof krpano.call !== "function") {
      return false;
    }

    krpanoImageLoaded = false;
    const sceneUrl = krpanoSceneUrl(nextVideo, nextFrame, requestedView);
    logDebug(`krpano loadpano ${sceneUrl}`);
    krpano.call(`loadpano("${sceneUrl}", null, MERGE, BLEND(0.2));`);
    return true;
  }

  async function postViewerState(immediate, sourceState, options) {
    if (!immediate && Date.now() < suppressPostUntil) {
      return;
    }

    const current = currentSessionState(sourceState);
    if (options && options.viewOnly) {
      // Periodic browser updates are only for preserving the user's view.
      // QGIS owns the active POI selection, so do not let view posts overwrite it.
      current._viewer_view_update_only = true;
      delete current.target;
      delete current.targets;
    }
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
      postViewerState(false, undefined, { viewOnly: true });
    }, 300);
  }

  function currentViewHeldState(nextState) {
    // Lock preserves the user's current view while QGIS changes frames/POIs.
    // Do not alter target payloads or POI Lock math here; only carry yaw/pitch/zoom.
    if (!viewHoldEnabled) {
      return nextState;
    }
    const currentView = readKrpanoView();
    if (!currentView) {
      return nextState;
    }
    return Object.assign({}, nextState, {
      yaw_to_camera_heading: currentView.yaw_to_camera_heading,
      pitch: currentView.pitch,
      zoom: currentView.zoom
    });
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
    const response = await fetch(`/api/session/viewer-state?_=${Date.now()}`, {
      cache: "no-store"
    }).catch(() => null);
    if (!response || !response.ok) {
      return;
    }

    const session = await response.json().catch(() => null);
    if (!session || !session.video || session.frame_index === undefined || session.frame_index === null) {
      return;
    }

    noteExternalSession(session);
    if (!sameFrame(session, state)) {
      pendingEmptyTargetKey = null;
      pendingEmptyTargetSince = 0;
      const nextSession = currentViewHeldState(session);
      if (!loadFrameInPlace(nextSession)) {
        window.location.href = viewerUrl(session.video, session.frame_index, nextSession);
      }
      lastPosted = currentSessionState(state);
      return;
    }

    updateRadarState(session.radar);
    updateCameraHeight(session.viewer_camera_height_m);
    state.viewer_projection = normalizeViewerProjection(session.viewer_projection || state.viewer_projection);
    state.viewer_flat_hfov_deg = normalizeFovDeg(session.viewer_flat_hfov_deg || state.viewer_flat_hfov_deg, 70);
    state.viewer_flat_vfov_deg = normalizeFovDeg(session.viewer_flat_vfov_deg || state.viewer_flat_vfov_deg, 43);
    if (Number.isFinite(Number(session.viewer_front_offset_deg))) {
      state.viewer_front_offset_deg = normalizeSignedYaw(Number(session.viewer_front_offset_deg));
    }
    const incomingTargets = sessionTargets(session);
    if (!incomingTargets.length && displayClickTargets().length) {
      const emptyTargetKey = `${session.video || ""}:${Number(session.frame_index)}`;
      const now = Date.now();
      if (pendingEmptyTargetKey !== emptyTargetKey) {
        pendingEmptyTargetKey = emptyTargetKey;
        pendingEmptyTargetSince = now;
      }
      if (now - pendingEmptyTargetSince < TARGET_CLEAR_GRACE_MS) {
        updateReadout(readKrpanoView() || state);
        updateGroundRings(readKrpanoView() || state);
        lastPosted = currentSessionState(state);
        return;
      }
    } else {
      pendingEmptyTargetKey = null;
      pendingEmptyTargetSince = 0;
    }
    state.targets = Array.isArray(session.targets) ? session.targets : [];
    state.target = session.target && typeof session.target === "object"
      ? session.target
      : (state.targets.length ? state.targets[state.targets.length - 1] : null);
    updateReadout(readKrpanoView() || state);
    updateGroundRings(readKrpanoView() || state);
    lastPosted = currentSessionState(state);
  }

  function setupNavigation() {
    prevButton.addEventListener("click", () => navigateToFrame(navigationState.prev_frame));
    nextButton.addEventListener("click", () => navigateToFrame(navigationState.next_frame));
    updateNavigationButtons();
  }

  function updateViewHoldButton() {
    if (!viewHoldButton) {
      return;
    }
    viewHoldButton.classList.toggle("is-active", viewHoldEnabled);
    viewHoldButton.setAttribute("aria-pressed", viewHoldEnabled ? "true" : "false");
  }

  function setupViewHoldButton() {
    if (!viewHoldButton) {
      return;
    }
    viewHoldButton.addEventListener("click", () => {
      viewHoldEnabled = !viewHoldEnabled;
      updateViewHoldButton();
      updateClickTargetMarker();
      postViewerState(true);
    });
    updateViewHoldButton();
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
        window.setInterval(schedulePost, VIEW_STATE_POST_INTERVAL_MS);
      }
    });
  }

  setupFallbackFrameDiagnostics();
  setupNavigation();
  setupViewHoldButton();
  setupKeyboardNavigation();
  setupDebugLogToggle();
  setupRadarHudToggle();
  setupClickTargetProjection();
  updateReadout(state);
  setupKrpano();
  window.setInterval(pollExternalNavigation, EXTERNAL_SESSION_POLL_INTERVAL_MS);
}());
