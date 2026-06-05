(function () {
  const bootstrap = window.VIEWER_BOOTSTRAP || {};
  const state = Object.assign({
    video: "",
    frame_index: 0,
    yaw_to_camera_heading: 0,
    pitch: 0,
    zoom: 1
  }, bootstrap.state || {});

  let krpano = null;
  let lastPosted = null;
  let postTimer = null;
  let krpanoReady = false;
  let krpanoImageLoaded = false;
  let debugLogVisible = false;
  let navigationState = {
    prev_frame: bootstrap.prev_frame,
    next_frame: bootstrap.next_frame,
    matched_csv_exists: Boolean(bootstrap.matched_csv_exists)
  };

  const prevButton = document.getElementById("prevButton");
  const nextButton = document.getElementById("nextButton");
  const debugToggleButton = document.getElementById("debugToggleButton");
  const notice = document.getElementById("notice");
  const debugLog = document.getElementById("debugLog");
  const fallbackFrame = document.getElementById("fallbackFrame");
  const videoLabel = document.getElementById("videoLabel");
  const frameLabel = document.getElementById("frameLabel");
  const viewLabel = document.getElementById("viewLabel");

  function normalizeYaw(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return ((numeric % 360) + 360) % 360;
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
      zoom: normalizeZoom(zoom)
    };
  }

  function updateReadout(viewState) {
    const active = viewState || state;
    videoLabel.textContent = `video: ${active.video}`;
    frameLabel.textContent = `frame_index: ${active.frame_index}`;
    viewLabel.textContent = `yaw: ${Number(active.yaw_to_camera_heading).toFixed(2)}, pitch: ${Number(active.pitch).toFixed(2)}, zoom: ${Number(active.zoom).toFixed(2)}`;
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

    Object.assign(state, nextState, inheritedView, {
      video: nextVideo,
      frame_index: nextFrame
    });
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
    const current = readKrpanoView() || state;
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
        updateReadout(readKrpanoView());
        postViewerState(true);
        window.setInterval(schedulePost, 300);
      }
    });
  }

  setupFallbackFrameDiagnostics();
  setupNavigation();
  setupKeyboardNavigation();
  setupDebugLogToggle();
  updateReadout(state);
  setupKrpano();
  window.setInterval(pollExternalNavigation, 750);
}());
