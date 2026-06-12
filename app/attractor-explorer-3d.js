/**
 * Attractor Explorer 3D — Three.js semantic visualization with attractor forces
 *
 * Same attractor-chip UI and public API as AttractorExplorer (2D canvas),
 * but renders in 3D with WebGL using Three.js. Nodes are camera-facing
 * billboards with lazy-loaded thumbnails.
 *
 * Force simulation is a lightweight custom 3D loop (no d3-force-3d dependency):
 *   - Attractor pull (weighted by feature vector)
 *   - Return-to-rest force (PCA positions)
 *   - Velocity damping
 *   - Grid-hash collision avoidance
 *
 * Default mode: live physics. Continuous render loop with per-frame force ticks.
 * Users can still switch back to settled/pre-computed behavior via the Live checkbox.
 *
 * Sets window.AttractorExplorer3D with the same public API shape as AttractorExplorer.
 */
(async function () {
  "use strict";

  let THREE, OrbitControls;
  try {
    const threeModule = await import("three");
    THREE = threeModule;
    const ocModule = await import("three/addons/controls/OrbitControls.js");
    OrbitControls = ocModule.OrbitControls;
  } catch (e) {
    console.error("[AttractorExplorer3D] Three.js not available:", e);
    window.AttractorExplorer3D = {
      __unavailable: true,
      init() {}, loadData() {}, setFilter() {}, setSearch() {},
      setFocusedMode() {}, getVisibleNodeIds() { return []; }, highlight() {}, onSelect() {}, onClickNode() {},
      pause() {}, resume() {}, resize() {}, destroy() {},
    };
    return;
  }

  // ─── State ───────────────────────────────────────────────────────────────
  let _container = null;
  let _renderer = null;
  let _scene = null;
  let _camera = null;
  let _controls = null;
  let _controlsEl = null;
  let _labelsEl = null;
  let _animFrameId = null;
  let _paused = false;

  let _nodes = [];
  let _allNodes = [];
  let _dimensions = [];
  let _categories = {};
  let _attractorOptions = {};
  let _activeAttractors = [];   // [{dim, name, count, px, py, pz}]

  let _instanceMesh = null;      // THREE.InstancedMesh for all colored base tiles
  let _instanceNodes = [];       // instanceId -> node
  let _overlayMeshes = new Map();// id -> {mesh, node} textured near-camera overlays
  let _poleMarkers = [];         // [{mesh, labelEl, att}]
  let _clickCallback = null;
  let _selectCallback = null;
  let _highlightedIds = null;
  let _filterIds = null;
  let _searchTerm = "";
  let _focusedMode = true;
  let _groupByKey = "";

  // Settings
  let _attractStrength = 0.35;
  let _repulsion = 6;
  let _nodeSize = 8;             // world units (scene spans ±350)
  let _restPull = 0.02;          // return-to-rest strength when no attractors are active
  let _liveMode = true;
  let _liveDefaultEnabled = true;
  let _liveUntil = 0;

  // Tween
  let _tweenStart = 0;
  const _tweenDuration = 600;
  let _tweening = false;
  let _cameraCenterTween = null;
  let _deferredSettleRaf = null;
  let _deferredSettleRunId = 0;
  let _deferSettleUntil = 0;

  // Physics
  const SETTLE_TICKS = 200;
  const RETICK = 150;
  const LOAD_SETTLE_DEFER_MS = 2500;
  const LIVE_BURST_MS = 6500;

  // Texture loading
  const _texCache = {};
  let _texLoader = null;
  let _texLoading = 0;
  let _texQueue = [];
  let _texQueueDirty = false;
  let _maxConcurrentTex = 12;
  // 0 means "no cap" (allow overlays for all currently visible nodes).
  let _maxTextureOverlays = 0;
  let _texPrefetchCount = 180;
  let _textureRampTimers = [];
  const OVERLAY_SYNC_MIN_MS = 90;
  const SETTINGS_KEY = "inspirations.attractor3d.settings.v3";
  const MAX_PRESET_NAME_LEN = 32;
  const MAX_PRESET_COUNT = 12;
  const MIN_REST_PULL = 0.002;
  const MAX_REST_PULL = 0.08;
  const SIZE_BUCKET = Object.freeze({
    SMALL: "small",
    MEDIUM: "medium",
    LARGE: "large",
  });
  // Tuned per dataset size bucket:
  // small <= 300, medium 301-1500, large > 1500 visible nodes.
  const PHYSICS_PROFILE = Object.freeze({
    small: Object.freeze({
      dampingHot: 0.69,
      dampingCalm: 0.47,
      velEpsBase: 0.0055,
      velEpsCalmAdd: 0.007,
      forceEpsBase: 0.0038,
      forceEpsCalmAdd: 0.0062,
      speedHotNorm: 0.013,
      forceHotNorm: 0.1,
      calmLerp: 0.14,
      collisionMinDistMul: 0.98,
      collisionSlopBase: 0.008,
      collisionSlopCalmAdd: 0.014,
      collisionPushHot: 0.22,
      collisionPushCalmDrop: 0.06,
      overlayScale: 1.14,
      overlayOffset: 0.18,
      baseTileWhenOverlay: 0.025,
    }),
    medium: Object.freeze({
      dampingHot: 0.66,
      dampingCalm: 0.44,
      velEpsBase: 0.006,
      velEpsCalmAdd: 0.009,
      forceEpsBase: 0.004,
      forceEpsCalmAdd: 0.0075,
      speedHotNorm: 0.012,
      forceHotNorm: 0.09,
      calmLerp: 0.12,
      collisionMinDistMul: 1.06,
      collisionSlopBase: 0.01,
      collisionSlopCalmAdd: 0.02,
      collisionPushHot: 0.24,
      collisionPushCalmDrop: 0.09,
      overlayScale: 1.09,
      overlayOffset: 0.22,
      baseTileWhenOverlay: 0.02,
    }),
    large: Object.freeze({
      dampingHot: 0.68,
      dampingCalm: 0.5,
      velEpsBase: 0.005,
      velEpsCalmAdd: 0.0075,
      forceEpsBase: 0.0035,
      forceEpsCalmAdd: 0.0065,
      speedHotNorm: 0.0085,
      forceHotNorm: 0.065,
      calmLerp: 0.09,
      collisionMinDistMul: 1.12,
      collisionSlopBase: 0.008,
      collisionSlopCalmAdd: 0.015,
      collisionPushHot: 0.26,
      collisionPushCalmDrop: 0.08,
      overlayScale: 1.04,
      overlayOffset: 0.26,
      baseTileWhenOverlay: 0.016,
    }),
  });

  // Shared geometry + billboard tracking
  let _sharedGeo = null;
  let _lastCameraQuat = null;
  let _lastCameraPos = null;
  let _resizeObserver = null;
  let _needsVisualUpdate = false;
  let _needsInstanceUpdate = false;
  let _needsOverlaySync = false;
  let _lastOverlaySyncAt = 0;

  // Hot-path temp objects
  let _tmpMatrix = null;
  let _tmpPosition = null;
  let _tmpScale = null;
  let _tmpColor = null;
  let _tmpBgColor = null;
  let _tmpCameraOffset = null;

  // UI state
  let _showThumbs = true;
  let _sizeManuallySet = false;
  let _settingsLoaded = false;
  let _hasSavedNodeSize = false;
  let _presets = [];
  let _startupPresetName = "";
  let _liveCalm = 0;            // 0 = active movement, 1 = settled/calmed

  // Click suppression to prevent drag-release opening detail modal
  const CLICK_DRAG_PX = 6;
  const CLICK_SUPPRESS_MS = 220;
  let _pointerDown = null;
  let _dragMoved = false;
  let _controlsDragging = false;
  let _suppressClickUntil = 0;
  let _pointerDownHandler = null;
  let _pointerMoveHandler = null;
  let _pointerUpHandler = null;
  let _pointerCancelHandler = null;
  let _pointerLeaveHandler = null;
  let _controlsStartHandler = null;
  let _controlsEndHandler = null;
  let _hoverPreviewEl = null;
  let _hoverPreviewImgEl = null;
  let _hoverPreviewTitleEl = null;
  let _hoverPreviewNodeId = "";
  let _hoverPreviewRaf = 0;
  let _hoverPreviewClientX = 0;
  let _hoverPreviewClientY = 0;
  const _hoverPreviewEnabled = !!(window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches);

  // Source colors
  const SOURCE_COLORS = {
    pinterest: 0xc8553d,
    facebook: 0x4267b2,
    houzz: 0x4dbc63,
    scan: 0x8b6914,
    photo: 0x5b6f8c,
  };
  const GROUP_BY_LIMIT = 7;
  const GROUP_BY_SPECS = [
    { key: "", label: "None" },
    { key: "source", label: "Source" },
    { key: "room", label: "Room" },
    { key: "style_family", label: "Style" },
    { key: "materials", label: "Material" },
    { key: "colors", label: "Color" },
    { key: "product_focus", label: "Product" },
  ];
  const GROUP_BY_SOURCE_LABELS = {
    pinterest: "Pinterest",
    facebook: "Facebook",
    houzz: "Houzz",
    scan: "Scans",
    photo: "Photos",
  };
  const DEFAULT_OPEN_CATEGORY_KEYS = new Set(["room", "style_family", "materials", "colors"]);

  function _normalizeSourceKey(source) {
    const key = String(source || "").trim().toLowerCase();
    if (key === "clip" || key === "clips" || key === "magazine clip" || key === "magazine clips") {
      return "scan";
    }
    return key;
  }

  // ─── Helpers ──────────────────────────────────────────────────────────────

  function _bgColor() {
    const style = getComputedStyle(document.documentElement);
    return style.getPropertyValue("--bg").trim() || "#faf8f5";
  }

  function _isOwnerRole() {
    return String(document.documentElement?.dataset?.actorRole || "").trim().toLowerCase() === "owner";
  }

  function _armClickSuppression() {
    _suppressClickUntil = performance.now() + CLICK_SUPPRESS_MS;
  }

  function _hideHoverPreview() {
    if (_hoverPreviewEl) _hoverPreviewEl.hidden = true;
    _hoverPreviewNodeId = "";
    if (_renderer?.domElement) _renderer.domElement.style.cursor = "";
  }

  function _showHoverPreview(node, clientX, clientY) {
    if (!_hoverPreviewEl || !_container || !_renderer) return;
    if (!node) {
      _hideHoverPreview();
      return;
    }
    if (_hoverPreviewNodeId !== node.id) {
      if (_hoverPreviewTitleEl) {
        _hoverPreviewTitleEl.textContent = String(node.title || "(untitled)");
      }
      if (_hoverPreviewImgEl) {
        const url = String(node.thumb_url || "");
        _hoverPreviewImgEl.hidden = !url;
        if (url && _hoverPreviewImgEl.src !== url) _hoverPreviewImgEl.src = url;
      }
      _hoverPreviewNodeId = node.id;
    }
    _hoverPreviewEl.hidden = false;
    const bounds = _container.getBoundingClientRect();
    const x = clientX - bounds.left;
    const y = clientY - bounds.top;
    const pad = 10;
    const offset = 16;
    const previewW = _hoverPreviewEl.offsetWidth || 220;
    const previewH = _hoverPreviewEl.offsetHeight || 170;
    let left = x + offset;
    let top = y + offset;
    if (left + previewW > bounds.width - pad) left = x - previewW - offset;
    if (left < pad) left = pad;
    if (top + previewH > bounds.height - pad) top = bounds.height - previewH - pad;
    if (top < pad) top = pad;
    _hoverPreviewEl.style.left = `${Math.round(left)}px`;
    _hoverPreviewEl.style.top = `${Math.round(top)}px`;
    if (_renderer?.domElement) _renderer.domElement.style.cursor = "pointer";
  }

  function _scheduleHoverPreview(clientX, clientY) {
    if (!_hoverPreviewEnabled) return;
    _hoverPreviewClientX = clientX;
    _hoverPreviewClientY = clientY;
    if (_hoverPreviewRaf) return;
    _hoverPreviewRaf = requestAnimationFrame(() => {
      _hoverPreviewRaf = 0;
      if (!_hoverPreviewEnabled || _controlsDragging || !!_pointerDown) {
        _hideHoverPreview();
        return;
      }
      const node = _pickNodeAtClient(_hoverPreviewClientX, _hoverPreviewClientY);
      _showHoverPreview(node, _hoverPreviewClientX, _hoverPreviewClientY);
    });
  }

  function _settleTicksForNodeCount(nodeCount) {
    // Large datasets can spend too long in synchronous settle loops.
    // Scale ticks down with size to keep mode switches responsive.
    if (nodeCount >= 5000) return 18;
    if (nodeCount >= 3000) return 28;
    if (nodeCount >= 1500) return 50;
    return SETTLE_TICKS;
  }

  function _retickTicksForNodeCount(nodeCount) {
    if (nodeCount >= 5000) return 16;
    if (nodeCount >= 3000) return 30;
    if (nodeCount >= 1500) return 55;
    return RETICK;
  }

  function _settleChunkSizeForNodeCount(nodeCount) {
    if (nodeCount >= 5000) return 2;
    if (nodeCount >= 3000) return 3;
    if (nodeCount >= 1500) return 4;
    return 8;
  }

  function _textureBudgetForNodeCount(nodeCount) {
    if (nodeCount >= 5000) {
      return { prefetch: 90, overlays: 90, concurrent: 10 };
    }
    if (nodeCount >= 3000) {
      return { prefetch: 120, overlays: 120, concurrent: 12 };
    }
    if (nodeCount >= 1500) {
      return { prefetch: 160, overlays: 160, concurrent: 14 };
    }
    return { prefetch: 220, overlays: 220, concurrent: 16 };
  }

  function _cancelTextureRamp() {
    for (const timer of _textureRampTimers) window.clearTimeout(timer);
    _textureRampTimers = [];
  }

  function _expandTextureOverlays(limit) {
    _maxTextureOverlays = Math.max(0, Math.round(Number(limit) || 0));
    _needsOverlaySync = true;
    _syncTextureOverlays(true);
  }

  function _scheduleTextureRamp(initialOverlayLimit, nodeCount) {
    _cancelTextureRamp();
    if (!initialOverlayLimit || initialOverlayLimit <= 0 || nodeCount <= initialOverlayLimit) return;

    const stages = [
      { delay: 1800, limit: Math.min(nodeCount, initialOverlayLimit * 2) },
      { delay: 3600, limit: Math.min(nodeCount, initialOverlayLimit * 4) },
      // Final stage restores the pre-cap behavior: every visible node may
      // receive a thumbnail, but only after the first usable 3D paint.
      { delay: 6500, limit: 0 },
    ];
    for (const stage of stages) {
      _textureRampTimers.push(window.setTimeout(() => {
        _expandTextureOverlays(stage.limit);
      }, stage.delay));
    }
  }

  function _cancelDeferredSettle() {
    _deferredSettleRunId += 1;
    if (_deferredSettleRaf) {
      cancelAnimationFrame(_deferredSettleRaf);
      _deferredSettleRaf = null;
    }
  }

  function _shouldDeferSettleNow() {
    return performance.now() < _deferSettleUntil;
  }

  function _sameIdSet(a, b) {
    if (a === b) return true;
    if (!a || !b) return false;
    if (a.size !== b.size) return false;
    for (const id of a) {
      if (!b.has(id)) return false;
    }
    return true;
  }

  function _sourceColorValue(source) {
    return SOURCE_COLORS[_normalizeSourceKey(source)] || 0x999999;
  }

  function _nodeOpacity(node) {
    let opacity = 1.0;
    if (_filterIds && !_filterIds.has(node.id)) opacity = 0.05;
    if (_highlightedIds && !_highlightedIds.has(node.id)) opacity = 0.06;
    if (_searchTerm && !node.title.toLowerCase().includes(_searchTerm)) opacity = 0.08;
    return opacity;
  }

  function _markSceneDirty() {
    _needsInstanceUpdate = true;
    _needsOverlaySync = true;
  }

  function _markVisualsDirty() {
    _needsVisualUpdate = true;
  }

  function _fmtNum(value, digits) {
    return Number(value).toFixed(digits);
  }

  function _clamp(value, min, max, fallback) {
    const n = Number(value);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(min, Math.min(max, n));
  }

  function _sizeBucketForCount(nodeCount) {
    if (nodeCount <= 300) return SIZE_BUCKET.SMALL;
    if (nodeCount <= 1500) return SIZE_BUCKET.MEDIUM;
    return SIZE_BUCKET.LARGE;
  }

  function _physicsProfileForCount(nodeCount) {
    return PHYSICS_PROFILE[_sizeBucketForCount(nodeCount)] || PHYSICS_PROFILE.medium;
  }

  function _activePhysicsProfile() {
    const n = _nodes.length || _allNodes.length || 0;
    return _physicsProfileForCount(n);
  }

  function _normalizePreset(rawPreset) {
    if (!rawPreset || typeof rawPreset !== "object") return null;
    const name = String(rawPreset.name || "").trim().slice(0, MAX_PRESET_NAME_LEN);
    if (!name) return null;
    return {
      name,
      strength: _clamp(rawPreset.strength, 0.05, 0.8, 0.35),
      spread: _clamp(rawPreset.spread, 1, 20, 6),
      size: _clamp(rawPreset.size, 0.05, 30, 8),
      restPull: _clamp(rawPreset.restPull, MIN_REST_PULL, MAX_REST_PULL, 0.02),
      focusedMode: true,
      liveMode: !!rawPreset.liveMode,
      showThumbs: typeof rawPreset.showThumbs === "boolean" ? rawPreset.showThumbs : true,
    };
  }

  function _applyLookToState(look, opts = {}) {
    const markManualSize = opts.markManualSize !== false;
    _attractStrength = _clamp(look?.strength, 0.05, 0.8, _attractStrength);
    _repulsion = _clamp(look?.spread, 1, 20, _repulsion);
    const nextSize = _clamp(look?.size, 0.05, 30, _nodeSize);
    if (Number.isFinite(nextSize)) {
      _nodeSize = nextSize;
      _hasSavedNodeSize = true;
      if (markManualSize) _sizeManuallySet = true;
    }
    if (Number.isFinite(look?.restPull)) {
      _restPull = _clamp(look.restPull, MIN_REST_PULL, MAX_REST_PULL, _restPull);
    }
    _focusedMode = true;
    if (typeof look?.liveMode === "boolean") {
      _liveDefaultEnabled = look.liveMode;
      _liveMode = look.liveMode;
    }
    if (typeof look?.showThumbs === "boolean") _showThumbs = look.showThumbs;
  }

  function _defaultNodeSizeForCount(nodeCount) {
    if (nodeCount > 5500) return 3.6;
    if (nodeCount > 4000) return 4.2;
    if (nodeCount > 2500) return 5.1;
    if (nodeCount > 1500) return 6.0;
    if (nodeCount > 900) return 6.9;
    if (nodeCount > 300) return 8.0;
    return 9.2;
  }

  function _loadSettingsOnce() {
    if (_settingsLoaded) return;
    _settingsLoaded = true;
    try {
      const raw = window.localStorage.getItem(SETTINGS_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (Number.isFinite(s.strength)) _attractStrength = _clamp(s.strength, 0.05, 0.8, _attractStrength);
      if (Number.isFinite(s.spread)) _repulsion = _clamp(s.spread, 1, 20, _repulsion);
      if (Number.isFinite(s.size)) {
        _nodeSize = _clamp(s.size, 0.05, 30, _nodeSize);
        _hasSavedNodeSize = true;
      }
      if (Number.isFinite(s.restPull)) {
        _restPull = _clamp(s.restPull, MIN_REST_PULL, MAX_REST_PULL, _restPull);
      }
      _focusedMode = true;
      if (typeof s.showThumbs === "boolean") _showThumbs = s.showThumbs;
      if (typeof s.liveMode === "boolean") {
        _liveDefaultEnabled = s.liveMode;
        _liveMode = s.liveMode;
      }
      if (Array.isArray(s.presets)) {
        _presets = s.presets
          .map((p) => _normalizePreset(p))
          .filter(Boolean)
          .slice(0, MAX_PRESET_COUNT);
      }
      if (typeof s.startupPresetName === "string") {
        _startupPresetName = s.startupPresetName.trim().slice(0, MAX_PRESET_NAME_LEN);
      }
      if (_startupPresetName) {
        const startupPreset = _presets.find((p) => p.name === _startupPresetName);
        if (startupPreset) _applyLookToState(startupPreset, { markManualSize: true });
      }
      _focusedMode = true;
    } catch (_) {
      // Ignore malformed local settings
    }
  }

  function _saveSettings() {
    try {
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify({
        strength: _attractStrength,
        spread: _repulsion,
        size: _nodeSize,
        restPull: _restPull,
        focusedMode: true,
        showThumbs: _showThumbs,
        liveMode: _liveDefaultEnabled,
        presets: _presets.map((p) => ({
          name: p.name,
          strength: p.strength,
          spread: p.spread,
          size: p.size,
          restPull: p.restPull,
          focusedMode: true,
          liveMode: p.liveMode,
          showThumbs: p.showThumbs,
        })),
        startupPresetName: _startupPresetName || "",
      }));
    } catch (_) {
      // Ignore localStorage failures
    }
  }

  function _syncLiveToggleUi() {
    const liveToggle = _controlsEl?.querySelector("#_attr3dLive");
    if (liveToggle) liveToggle.checked = !!_liveMode;
  }

  function _armLiveBurst(durationMs = LIVE_BURST_MS) {
    if (!_liveDefaultEnabled) {
      _liveMode = false;
      _liveUntil = 0;
      _syncLiveToggleUi();
      return;
    }
    _liveMode = true;
    _liveUntil = performance.now() + Math.max(1000, Number(durationMs) || LIVE_BURST_MS);
    _liveCalm = 0;
    _syncLiveToggleUi();
  }

  function _endLiveBurst({ settle = true } = {}) {
    if (!_liveMode && _liveUntil === 0) return;
    _liveMode = false;
    _liveUntil = 0;
    _syncLiveToggleUi();
    if (!settle) return;
    if (_activeAttractors.length > 0) {
      _settleSimulation(_retickTicksForNodeCount(_nodes.length));
    } else {
      for (const node of _nodes) {
        node.vx = 0;
        node.vy = 0;
        node.vz = 0;
      }
      _markSceneDirty();
    }
    _syncInstanceMesh();
    _queueNearTextures();
    _syncTextureOverlays(true);
  }

  function _resetNodesToRest() {
    for (const node of _nodes) {
      node.vx = 0;
      node.vy = 0;
      node.vz = 0;
      node.x = node._restX;
      node.y = node._restY;
      node.z = node._restZ;
    }
    _markSceneDirty();
  }

  function _normalizeRestLayoutToScene() {
    if (_nodes.length === 0) return;

    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    for (const node of _nodes) {
      if (node._restX < minX) minX = node._restX;
      if (node._restY < minY) minY = node._restY;
      if (node._restZ < minZ) minZ = node._restZ;
      if (node._restX > maxX) maxX = node._restX;
      if (node._restY > maxY) maxY = node._restY;
      if (node._restZ > maxZ) maxZ = node._restZ;
    }

    const spanX = maxX - minX;
    const spanY = maxY - minY;
    const spanZ = maxZ - minZ;
    const maxSpan = Math.max(spanX, spanY, spanZ);
    if (!Number.isFinite(maxSpan) || maxSpan <= 1e-6) return;

    const centerX = (minX + maxX) * 0.5;
    const centerY = (minY + maxY) * 0.5;
    const centerZ = (minZ + maxZ) * 0.5;
    const targetSpan = 320;
    const scale = Math.min(120, Math.max(0.5, targetSpan / maxSpan));

    for (const node of _nodes) {
      node._restX = (node._restX - centerX) * scale;
      node._restY = (node._restY - centerY) * scale;
      node._restZ = (node._restZ - centerZ) * scale;
      node.x = (node.x - centerX) * scale;
      node.y = (node.y - centerY) * scale;
      node.z = (node.z - centerZ) * scale;
    }
  }

  // ─── Init ─────────────────────────────────────────────────────────────────

  function init(containerId) {
    _loadSettingsOnce();

    _container = document.getElementById(containerId);
    if (!_container) return;
    _container.style.position = "relative";

    const w = _container.clientWidth || 800;
    const h = _container.clientHeight || 600;

    _renderer = new THREE.WebGLRenderer({ antialias: true });
    _renderer.setPixelRatio(window.devicePixelRatio);
    _renderer.setSize(w, h);
    _renderer.setClearColor(new THREE.Color(_bgColor()), 1);
    _container.appendChild(_renderer.domElement);

    _scene = new THREE.Scene();

    _camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 5000);
    _camera.position.set(0, 0, _initialCameraZ(w, h));

    _controls = new OrbitControls(_camera, _renderer.domElement);
    _controls.enableDamping = true;
    _controls.dampingFactor = 0.08;
    _controls.screenSpacePanning = true;
    _controlsStartHandler = () => {
      _controlsDragging = true;
      _hideHoverPreview();
    };
    _controlsEndHandler = () => {
      _controlsDragging = false;
    };
    _controls.addEventListener("start", _controlsStartHandler);
    _controls.addEventListener("end", _controlsEndHandler);

    // Lights
    const ambient = new THREE.AmbientLight(0xffffff, 0.85);
    _scene.add(ambient);
    const dir = new THREE.DirectionalLight(0xfff8f0, 0.4);
    dir.position.set(5, 10, 7);
    _scene.add(dir);

    // Label overlay
    _labelsEl = document.createElement("div");
    _labelsEl.className = "attractor-labels-overlay";
    _labelsEl.style.cssText =
      "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;";
    _container.appendChild(_labelsEl);

    // Control panel
    _controlsEl = document.createElement("div");
    _controlsEl.className = "attractor-controls";
    const toolbarMount = document.getElementById("explorerToolbarMount");
    if (toolbarMount) {
      toolbarMount.hidden = false;
      _controlsEl.classList.add("toolbar-mounted");
      toolbarMount.appendChild(_controlsEl);
    } else {
      _container.appendChild(_controlsEl);
    }

    // Hover preview (desktop/laptop pointers only)
    _hoverPreviewEl = document.createElement("div");
    _hoverPreviewEl.className = "attractor-hover-preview";
    _hoverPreviewEl.hidden = true;
    _hoverPreviewEl.innerHTML = `
      <img class="attractor-hover-preview-img" alt="">
      <div class="attractor-hover-preview-title"></div>
    `;
    _container.appendChild(_hoverPreviewEl);
    _hoverPreviewImgEl = _hoverPreviewEl.querySelector(".attractor-hover-preview-img");
    _hoverPreviewTitleEl = _hoverPreviewEl.querySelector(".attractor-hover-preview-title");

    // Texture loader
    _texLoader = new THREE.TextureLoader();

    // Shared geometry for base instances and texture overlays
    _sharedGeo = new THREE.PlaneGeometry(1, 1);

    _tmpMatrix = new THREE.Matrix4();
    _tmpPosition = new THREE.Vector3();
    _tmpScale = new THREE.Vector3(1, 1, 1);
    _tmpColor = new THREE.Color(1, 1, 1);
    _tmpBgColor = new THREE.Color(_bgColor());
    _tmpCameraOffset = new THREE.Vector3();
    _lastCameraPos = _camera.position.clone();

    // Sentinel: (0,0,0,0) is not a valid unit quaternion — forces first billboard update
    _lastCameraQuat = new THREE.Quaternion(0, 0, 0, 0);

    // Click detection
    _renderer.domElement.addEventListener("click", _onClick);
    _pointerDownHandler = (e) => {
      _pointerDown = { x: e.clientX, y: e.clientY };
      _dragMoved = false;
      _hideHoverPreview();
    };
    _pointerMoveHandler = (e) => {
      if (_pointerDown) {
        const dx = e.clientX - _pointerDown.x;
        const dy = e.clientY - _pointerDown.y;
        if ((dx * dx + dy * dy) > (CLICK_DRAG_PX * CLICK_DRAG_PX)) {
          _dragMoved = true;
        }
      }
      _scheduleHoverPreview(e.clientX, e.clientY);
    };
    _pointerUpHandler = () => {
      if (_dragMoved) _armClickSuppression();
      _pointerDown = null;
      _dragMoved = false;
      _controlsDragging = false; // failsafe if OrbitControls end event is missed
    };
    _pointerCancelHandler = () => {
      _armClickSuppression();
      _pointerDown = null;
      _dragMoved = false;
      _controlsDragging = false;
      _hideHoverPreview();
    };
    _pointerLeaveHandler = () => {
      _hideHoverPreview();
    };
    _renderer.domElement.addEventListener("pointerdown", _pointerDownHandler);
    _renderer.domElement.addEventListener("pointermove", _pointerMoveHandler);
    _renderer.domElement.addEventListener("pointerup", _pointerUpHandler);
    _renderer.domElement.addEventListener("pointercancel", _pointerCancelHandler);
    _renderer.domElement.addEventListener("pointerleave", _pointerLeaveHandler);
    window.addEventListener("pointerup", _pointerUpHandler);
    window.addEventListener("pointercancel", _pointerCancelHandler);

    // Resize
    _resizeObserver = new ResizeObserver(() => {
      resize();
    });
    _resizeObserver.observe(_container);
  }

  function resize() {
    if (!_renderer || !_camera || !_container) return;
    const nw = Math.max(1, _container.clientWidth || 800);
    const nh = Math.max(1, _container.clientHeight || 600);
    _camera.aspect = nw / nh;
    _camera.updateProjectionMatrix();
    _renderer.setSize(nw, nh);
    _needsVisualUpdate = true;
    _needsInstanceUpdate = true;
    _needsOverlaySync = true;
    _updatePoleLabelsScreen();
    _renderer.render(_scene, _camera);
  }

  function _initialCameraZ(w, h) {
    // Position camera so the PCA cloud fills most of the viewport.
    // PCA spread is data-dependent: X may span ±175, Y/Z often narrower.
    // Using 400 as effective diameter (conservative estimate).
    const fovRad = (60 * Math.PI) / 180;
    const halfFrustum = Math.tan(fovRad / 2);
    const sceneDiameter = 400;
    const aspect = w / h;
    const fill = 1.2;
    return aspect >= 1
      ? sceneDiameter / (fill * 2 * halfFrustum)
      : sceneDiameter / (fill * 2 * halfFrustum * aspect);
  }

  // ─── Data loading ─────────────────────────────────────────────────────────

  function _normalizeDataPayload(rawData) {
    if (rawData && Array.isArray(rawData.assets)) return rawData;
    if (!rawData || !Array.isArray(rawData.nodes)) {
      return { dimensions: [], categories: {}, attractors: {}, assets: [] };
    }
    // Accept /api/explorer/layout shape for backward compatibility.
    return {
      dimensions: rawData.dimensions || [],
      categories: rawData.categories || {},
      attractors: rawData.attractors || {},
      assets: rawData.nodes.map((node) => ({
        id: node.id,
        x: node.x,
        y: node.y,
        z: node.z,
        t: node.thumb_url || "",
        title: node.title || "",
        src: node.src || "",
        v: node.v || {},
      })),
    };
  }

  function loadData(rawData, options = {}) {
    const data = _normalizeDataPayload(rawData);
    _cancelDeferredSettle();
    _deferSettleUntil = options.deferSettle
      ? (performance.now() + LOAD_SETTLE_DEFER_MS)
      : 0;
    _clearScene();

    _dimensions = data.dimensions || [];
    _categories = data.categories || {};
    _attractorOptions = data.attractors || {};

    const assets = data.assets || [];

    _nodes = assets.map((a) => {
      // Reconstruct sparse → full vector
      const vec = new Float32Array(_dimensions.length);
      if (a.v) {
        for (const [idx, w] of Object.entries(a.v)) {
          vec[parseInt(idx)] = w;
        }
      }
      // Add small random jitter to prevent exact coincidence (fallback PCA
      // may produce very few unique positions — collision needs seed offsets)
      const jit = () => (Math.random() - 0.5) * 2;  // ±1 world unit jitter
      const jx = jit();
      const jy = jit();
      const jz = jit();
      const x = (a.x || 0) + jx;
      const y = (a.y || 0) + jy;
      const z = (a.z || 0) + jz;
      return {
        id: a.id,
        vector: vec,
        x, y, z,
        _restX: (a.x || 0) + jx,
        _restY: (a.y || 0) + jy,
        _restZ: (a.z || 0) + jz,
        vx: 0, vy: 0, vz: 0,
        thumb_url: (window.Shared && Shared.prefixPath) ? Shared.prefixPath(a.t) : a.t,
        title: a.title || "",
        source: _normalizeSourceKey(a.src || ""),
        _tex: null,
        _texQueued: false,
        _texFailed: false,
        _texPriority: Number.POSITIVE_INFINITY,
        _visAlpha: 1,
        _visible: true,
        _instanceIndex: -1,
      };
    });

    const texBudget = _textureBudgetForNodeCount(_nodes.length);
    _texPrefetchCount = texBudget.prefetch;
    _maxTextureOverlays = texBudget.overlays;
    _maxConcurrentTex = texBudget.concurrent;
    _scheduleTextureRamp(_maxTextureOverlays, _nodes.length);

    _normalizeRestLayoutToScene();
    _allNodes = _nodes.slice();
    _liveCalm = 0;
    _liveUntil = 0;

    if (!_hasSavedNodeSize && !_sizeManuallySet) {
      _nodeSize = _defaultNodeSizeForCount(_nodes.length);
    }

    // Build controls. Start new loads in category-filter mode; the user can
    // switch to grouping explicitly from the toolbar.
    _focusedMode = true;
    _groupByKey = "";
    _activeAttractors = [];
    _buildControls();

    // Start from precomputed layout coordinates (avoids "everything is a sphere")
    _resetNodesToRest();
    _buildInstanceMesh();
    _markVisualsDirty();
    _updateNodeVisuals(true);
    _syncInstanceMesh();
    _lastCameraQuat.set(0, 0, 0, 0);
    if (_lastCameraPos) _lastCameraPos.copy(_camera.position);

    console.log(`[3D] Loaded ${_nodes.length} nodes, camera Z=${_camera.position.z.toFixed(0)}, nodeSize=${_nodeSize}`);

    // Start render loop (Three.js always needs one for OrbitControls)
    if (!_animFrameId) _startRenderLoop();

    // Queue nearby textures and build initial overlay set
    _queueNearTextures();
    _syncTextureOverlays(true);
    _armLiveBurst();
  }

  function _disposeInstanceMesh() {
    if (!_instanceMesh) return;
    _scene.remove(_instanceMesh);
    _instanceMesh.material.dispose();
    _instanceMesh = null;
    _instanceNodes = [];
  }

  function _clearOverlayMeshes() {
    for (const { mesh } of _overlayMeshes.values()) {
      mesh.material.map = null;
      mesh.material.dispose();
      _scene && _scene.remove(mesh);
    }
    _overlayMeshes.clear();
  }

  function _buildInstanceMesh() {
    _disposeInstanceMesh();
    _instanceNodes = _nodes.slice();
    if (_instanceNodes.length === 0) return;

    const mat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      side: THREE.DoubleSide,
      transparent: true,
    });
    _instanceMesh = new THREE.InstancedMesh(_sharedGeo, mat, _instanceNodes.length);
    _instanceMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    _instanceMesh.frustumCulled = false;

    for (let i = 0; i < _instanceNodes.length; i++) {
      _instanceNodes[i]._instanceIndex = i;
    }
    _scene.add(_instanceMesh);
    _markSceneDirty();
  }

  function _syncInstanceMesh() {
    if (!_instanceMesh || !_camera) return;

    const profile = _activePhysicsProfile();
    const q = _camera.quaternion;
    for (const node of _instanceNodes) {
      const idx = node._instanceIndex;
      const alpha = node._visAlpha ?? 1;
      const visible = alpha > 0.02;
      const scaleMul = visible ? (0.3 + alpha * 0.7) : 0.001;
      const hasTextureOverlay = _showThumbs && !!node._tex && node._visible;
      const baseScaleAdjust = hasTextureOverlay ? profile.baseTileWhenOverlay : 1.0;
      const scale = _nodeSize * scaleMul * baseScaleAdjust;

      _tmpPosition.set(node.x, node.y, node.z);
      _tmpScale.setScalar(scale);
      _tmpMatrix.compose(_tmpPosition, q, _tmpScale);
      _instanceMesh.setMatrixAt(idx, _tmpMatrix);

      _tmpColor.setHex(_sourceColorValue(node.source));
      if (alpha < 1) {
        _tmpColor.lerp(_tmpBgColor, Math.min(0.95, 1 - alpha));
      }
      _instanceMesh.setColorAt(idx, _tmpColor);
    }

    _instanceMesh.instanceMatrix.needsUpdate = true;
    if (_instanceMesh.instanceColor) {
      _instanceMesh.instanceColor.needsUpdate = true;
    }
    _instanceMesh.computeBoundingSphere();
    _needsInstanceUpdate = false;
  }

  function _clearScene() {
    _cancelTextureRamp();
    _clearOverlayMeshes();
    _disposeInstanceMesh();

    for (const { mesh, labelEl } of _poleMarkers) {
      mesh.geometry.dispose();
      mesh.material.dispose();
      _scene && _scene.remove(mesh);
      if (labelEl) labelEl.remove();
    }
    _poleMarkers = [];

    _nodes = [];
    _allNodes = [];
    _activeAttractors = [];
    _needsVisualUpdate = false;
    _needsInstanceUpdate = false;
    _needsOverlaySync = false;
    _lastOverlaySyncAt = 0;
    Object.values(_texCache).forEach((t) => t.dispose());
    for (const key in _texCache) delete _texCache[key];
    _texQueue.length = 0;
    _texQueueDirty = false;
    _texLoading = 0;
  }

  // ─── 3D Force simulation ──────────────────────────────────────────────────

  function _forceTick() {
    const n = _nodes.length;
    if (n === 0) return;
    const profile = _physicsProfileForCount(n);
    let totalSpeed2 = 0;
    let totalForceAbs = 0;
    const damping = profile.dampingHot - (_liveCalm * (profile.dampingHot - profile.dampingCalm));
    const velEps = profile.velEpsBase + (_liveCalm * profile.velEpsCalmAdd);
    const forceEps = profile.forceEpsBase + (_liveCalm * profile.forceEpsCalmAdd);

    for (const node of _nodes) {
      let fx = 0, fy = 0, fz = 0;

      // Attractor pull
      for (const att of _activeAttractors) {
        const w = att.source !== undefined
          ? (node.source === att.source ? _attractStrength : 0)
          : node.vector[att.dim] * _attractStrength;
        if (w > 0) {
          fx += (att.px - node.x) * w * 0.02;
          fy += (att.py - node.y) * w * 0.02;
          fz += (att.pz - node.z) * w * 0.02;
        }
      }

      // Return-to-rest force
      const restStr = _activeAttractors.length > 0 ? 0.003 : _restPull;
      fx += (node._restX - node.x) * restStr;
      fy += (node._restY - node.y) * restStr;
      fz += (node._restZ - node.z) * restStr;

      // Apply velocity with damping
      node.vx = node.vx * damping + fx;
      node.vy = node.vy * damping + fy;
      node.vz = node.vz * damping + fz;

      // Deadzone: remove tiny residual vibration once the system is near equilibrium
      if (Math.abs(node.vx) < velEps && Math.abs(fx) < forceEps) node.vx = 0;
      if (Math.abs(node.vy) < velEps && Math.abs(fy) < forceEps) node.vy = 0;
      if (Math.abs(node.vz) < velEps && Math.abs(fz) < forceEps) node.vz = 0;

      node.x += node.vx;
      node.y += node.vy;
      node.z += node.vz;

      totalSpeed2 += (node.vx * node.vx) + (node.vy * node.vy) + (node.vz * node.vz);
      totalForceAbs += Math.abs(fx) + Math.abs(fy) + Math.abs(fz);
    }

    // Track whether simulation is "hot" or "calm" to adapt damping each frame.
    const avgSpeed2 = totalSpeed2 / n;
    const avgForceAbs = totalForceAbs / n;
    const speedHot = Math.min(1, avgSpeed2 / profile.speedHotNorm);
    const forceHot = Math.min(1, avgForceAbs / profile.forceHotNorm);
    const targetCalm = 1 - Math.max(speedHot, forceHot);
    _liveCalm += (targetCalm - _liveCalm) * profile.calmLerp;
    if (_liveCalm < 0) _liveCalm = 0;
    if (_liveCalm > 1) _liveCalm = 1;

    // Simple collision avoidance via grid hash
    _collisionPass();
  }

  // Collision grid packing: offset 512, stride 1025 — covers cell coords ±512
  // (scene ±350, min cellSize ~0.83 → max cell coord ±422, well within ±512)
  const _CELL_S = 1025;
  const _CELL_S2 = _CELL_S * _CELL_S;
  const _CELL_OFF = 512;

  function _collisionPass() {
    const profile = _activePhysicsProfile();
    const scale = _repulsion / 6;  // 6 is baseline
    const cellSize = _nodeSize * 2.5 * scale;
    const grid = new Map();

    for (const node of _nodes) {
      const cx = Math.floor(node.x / cellSize);
      const cy = Math.floor(node.y / cellSize);
      const cz = Math.floor(node.z / cellSize);
      const key = (cx + _CELL_OFF) * _CELL_S2 + (cy + _CELL_OFF) * _CELL_S + (cz + _CELL_OFF);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(node);
    }

    const minDist = _nodeSize * profile.collisionMinDistMul * scale;
    const minDist2 = minDist * minDist;
    const slop = minDist * (profile.collisionSlopBase + (profile.collisionSlopCalmAdd * _liveCalm));
    const pushK = profile.collisionPushHot - (profile.collisionPushCalmDrop * _liveCalm);

    for (const [key, cell] of grid) {
      const cx = Math.floor(key / _CELL_S2) - _CELL_OFF;
      const cy = Math.floor((key % _CELL_S2) / _CELL_S) - _CELL_OFF;
      const cz = (key % _CELL_S) - _CELL_OFF;
      // Check this cell and neighbors
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          for (let dz = -1; dz <= 1; dz++) {
            const nKey = (cx + dx + _CELL_OFF) * _CELL_S2 + (cy + dy + _CELL_OFF) * _CELL_S + (cz + dz + _CELL_OFF);
            const neighbor = grid.get(nKey);
            if (!neighbor) continue;
            for (const a of cell) {
              for (const b of neighbor) {
                if (a === b) continue;
                const ddx = a.x - b.x;
                const ddy = a.y - b.y;
                const ddz = a.z - b.z;
                const d2 = ddx * ddx + ddy * ddy + ddz * ddz;
                if (d2 < minDist2) {
                  let d = Math.sqrt(d2);
                  let nx, ny, nz;
                  if (d < 0.01) {
                    // Coincident nodes — push apart in random direction
                    const theta = Math.random() * Math.PI * 2;
                    const phi = Math.acos(2 * Math.random() - 1);
                    nx = Math.sin(phi) * Math.cos(theta);
                    ny = Math.sin(phi) * Math.sin(theta);
                    nz = Math.cos(phi);
                    d = 0.01;
                  } else {
                    nx = ddx / d;
                    ny = ddy / d;
                    nz = ddz / d;
                  }
                  const rawOverlap = minDist - d;
                  if (rawOverlap <= slop) continue;
                  const overlap = rawOverlap * pushK;
                  a.x += nx * overlap;
                  a.y += ny * overlap;
                  a.z += nz * overlap;
                  b.x -= nx * overlap;
                  b.y -= ny * overlap;
                  b.z -= nz * overlap;
                }
              }
            }
          }
        }
      }
    }
  }

  function _settleSimulation(ticks) {
    _cancelDeferredSettle();
    for (let i = 0; i < ticks; i++) {
      _forceTick();
    }
    _markSceneDirty();
  }

  function _settleAndTween(ticks, options = {}) {
    const defer = !!options.defer;
    _cancelDeferredSettle();

    // Stash current positions
    for (const node of _nodes) {
      node._tweenFromX = node.x;
      node._tweenFromY = node.y;
      node._tweenFromZ = node.z;
    }

    // Default behavior: settle synchronously then tween to settled targets.
    if (!defer) {
      _settleSimulation(ticks);
      for (const node of _nodes) {
        node._targetX = node.x;
        node._targetY = node.y;
        node._targetZ = node.z;
        node.x = node._tweenFromX;
        node.y = node._tweenFromY;
        node.z = node._tweenFromZ;
      }
      _tweenStart = performance.now();
      _tweening = true;
      return;
    }

    // Defer settle work across frames to keep view switch responsive.
    let remaining = Math.max(0, ticks | 0);
    const chunkTicks = _settleChunkSizeForNodeCount(_nodes.length);
    const runId = _deferredSettleRunId;

    const finalize = () => {
      if (runId !== _deferredSettleRunId) return;
      for (const node of _nodes) {
        node._targetX = node.x;
        node._targetY = node.y;
        node._targetZ = node.z;
        node.x = node._tweenFromX;
        node.y = node._tweenFromY;
        node.z = node._tweenFromZ;
      }
      _tweenStart = performance.now();
      _tweening = true;
      _markSceneDirty();
      _deferredSettleRaf = null;
    };

    const step = () => {
      if (runId !== _deferredSettleRunId) return;
      const stepTicks = Math.min(chunkTicks, remaining);
      for (let i = 0; i < stepTicks; i++) _forceTick();
      remaining -= stepTicks;
      if (remaining > 0) {
        _deferredSettleRaf = requestAnimationFrame(step);
        return;
      }
      finalize();
    };

    if (remaining <= 0) {
      finalize();
      return;
    }
    _deferredSettleRaf = requestAnimationFrame(step);
  }

  // ─── Attractor forces ─────────────────────────────────────────────────────

  function _updateAttractorForces() {
    if (_activeAttractors.length > 0) {
      // Position poles on Fibonacci sphere
      const n = _activeAttractors.length;
      const radius = 250; // spread is ~350 so poles are just inside the cloud
      const goldenAngle = Math.PI * (1 + Math.sqrt(5));

      _activeAttractors.forEach((att, i) => {
        const phi = Math.acos(1 - 2 * (i + 0.5) / n);
        const theta = goldenAngle * i;
        att.px = radius * Math.sin(phi) * Math.cos(theta);
        att.py = radius * Math.sin(phi) * Math.sin(theta);
        att.pz = radius * Math.cos(phi);
      });
    }

    // Reset velocities for cleaner settle
    for (const node of _nodes) {
      node.vx = 0; node.vy = 0; node.vz = 0;
    }
    _liveCalm = 0;

    if (_liveDefaultEnabled) {
      _armLiveBurst();
    } else {
      const useDeferredSettle = _shouldDeferSettleNow();
      _settleAndTween(_retickTicksForNodeCount(_nodes.length), { defer: useDeferredSettle });
      if (useDeferredSettle) _deferSettleUntil = 0;
    }

    _updatePoleMarkers();
  }

  // ─── Pole markers ─────────────────────────────────────────────────────────

  function _updatePoleMarkers() {
    // Remove old markers
    for (const { mesh, labelEl } of _poleMarkers) {
      mesh.geometry.dispose();
      mesh.material.dispose();
      _scene.remove(mesh);
      if (labelEl) labelEl.remove();
    }
    _poleMarkers = [];

    for (const att of _activeAttractors) {
      // Sphere at pole position
      const geo = new THREE.SphereGeometry(4, 12, 8);
      const mat = new THREE.MeshBasicMaterial({
        color: 0xfde047,
        transparent: true,
        opacity: 0.4,
      });
      const sphere = new THREE.Mesh(geo, mat);
      sphere.position.set(att.px, att.py, att.pz);
      _scene.add(sphere);

      // HTML label
      const labelEl = document.createElement("div");
      labelEl.className = "attractor-pole-label";
      labelEl.textContent = att.name;
      labelEl.style.cssText = `
        position:absolute;
        transform:translate(-50%,-50%);
        font-size:13px;font-weight:700;
        color:#fde047;
        text-shadow:0 1px 6px rgba(0,0,0,0.8), 0 0 20px rgba(184,134,11,0.4);
        white-space:nowrap;pointer-events:none;
        letter-spacing:0.5px;
      `;
      _labelsEl.appendChild(labelEl);

      _poleMarkers.push({ mesh: sphere, labelEl, att });
    }
  }

  function _updatePoleLabelsScreen() {
    if (!_camera || !_container) return;
    const w = _container.clientWidth;
    const h = _container.clientHeight;

    for (const { att, labelEl } of _poleMarkers) {
      const v = new THREE.Vector3(att.px, att.py, att.pz);
      v.project(_camera);
      if (v.z > 1) {
        labelEl.style.display = "none";
        continue;
      }
      labelEl.style.display = "";
      const sx = (v.x * 0.5 + 0.5) * w;
      const sy = (-v.y * 0.5 + 0.5) * h;
      labelEl.style.left = sx + "px";
      labelEl.style.top = sy + "px";
    }
  }

  // ─── Render loop ──────────────────────────────────────────────────────────

  function _startRenderLoop() {
    function loop() {
      _animFrameId = requestAnimationFrame(loop);
      if (_paused) return;

      _stepCameraCenterTween();
      if (_controls) _controls.update();


      if (_liveMode && _liveUntil > 0 && performance.now() >= _liveUntil) {
        _endLiveBurst({ settle: true });
      }

      // Billboard orientation changes
      if (!_camera.quaternion.equals(_lastCameraQuat)) {
        _lastCameraQuat.copy(_camera.quaternion);
        _needsInstanceUpdate = true;
        _needsOverlaySync = true;
      }

      // Track camera movement for overlay selection/placement
      const camDx = _camera.position.x - _lastCameraPos.x;
      const camDy = _camera.position.y - _lastCameraPos.y;
      const camDz = _camera.position.z - _lastCameraPos.z;
      const cameraMoved = (camDx * camDx + camDy * camDy + camDz * camDz) > 0.01;
      if (cameraMoved) {
        _lastCameraPos.copy(_camera.position);
        _needsOverlaySync = true;
      }

      // Live mode: tick forces each frame
      if (_liveMode) {
        _forceTick();
        _markSceneDirty();
      }

      // Tween interpolation
      if (_tweening) {
        const elapsed = performance.now() - _tweenStart;
        const t = Math.min(1, elapsed / _tweenDuration);
        const ease = 1 - Math.pow(1 - t, 3); // ease-out cubic

        for (const node of _nodes) {
          node.x = node._tweenFromX + (node._targetX - node._tweenFromX) * ease;
          node.y = node._tweenFromY + (node._targetY - node._tweenFromY) * ease;
          node.z = node._tweenFromZ + (node._targetZ - node._tweenFromZ) * ease;
        }
        _markSceneDirty();

        if (t >= 1) {
          _tweening = false;
          _queueNearTextures();
        }
      }

      // Update node visibility and instance color/scale dimming only when needed
      if (_needsVisualUpdate) _updateNodeVisuals(false);
      if (_needsInstanceUpdate) {
        _syncInstanceMesh();
      }

      const now = performance.now();
      if (_needsOverlaySync && (now - _lastOverlaySyncAt) >= OVERLAY_SYNC_MIN_MS) {
        _syncTextureOverlays();
      }

      // Update pole label positions
      _updatePoleLabelsScreen();

      _renderer.render(_scene, _camera);
    }
    _animFrameId = requestAnimationFrame(loop);
  }

  function _stopRenderLoop() {
    if (_animFrameId) {
      cancelAnimationFrame(_animFrameId);
      _animFrameId = null;
    }
  }

  function _visibleClusterCenter() {
    if (!_nodes.length) return null;
    let sumX = 0;
    let sumY = 0;
    let sumZ = 0;
    let count = 0;
    for (const node of _nodes) {
      const x = Number.isFinite(node._targetX) ? node._targetX : node.x;
      const y = Number.isFinite(node._targetY) ? node._targetY : node.y;
      const z = Number.isFinite(node._targetZ) ? node._targetZ : node.z;
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
      sumX += x;
      sumY += y;
      sumZ += z;
      count++;
    }
    if (!count) return null;
    return new THREE.Vector3(sumX / count, sumY / count, sumZ / count);
  }

  function _smoothCenterVisibleCluster() {
    if (!_camera || !_controls || !THREE || _controlsDragging) return;
    const center = _visibleClusterCenter();
    if (!center) return;

    const fromTarget = _controls.target.clone();
    const fromCamera = _camera.position.clone();
    const cameraOffset = fromCamera.clone().sub(fromTarget);
    const toCamera = center.clone().add(cameraOffset);

    if (fromTarget.distanceToSquared(center) < 0.01) return;
    _cameraCenterTween = {
      start: performance.now(),
      duration: 620,
      fromTarget,
      toTarget: center,
      fromCamera,
      toCamera,
    };
    _needsOverlaySync = true;
  }

  function _stepCameraCenterTween() {
    if (!_cameraCenterTween || !_camera || !_controls) return;
    const tween = _cameraCenterTween;
    const t = Math.min(1, (performance.now() - tween.start) / tween.duration);
    const ease = 1 - Math.pow(1 - t, 3);
    _controls.target.lerpVectors(tween.fromTarget, tween.toTarget, ease);
    _camera.position.lerpVectors(tween.fromCamera, tween.toCamera, ease);
    _needsOverlaySync = true;
    if (t >= 1) {
      _cameraCenterTween = null;
      _queueNearTextures();
    }
  }

  function _updateNodeVisuals(force) {
    if (!force && !_needsVisualUpdate) return;
    _needsVisualUpdate = false;

    let changed = false;
    for (const node of _nodes) {
      const opacity = _nodeOpacity(node);
      const visible = opacity > 0.02;
      if (Math.abs((node._visAlpha ?? 1) - opacity) > 0.001 || node._visible !== visible) {
        node._visAlpha = opacity;
        node._visible = visible;
        changed = true;
      }
    }
    if (changed) {
      _needsInstanceUpdate = true;
      _needsOverlaySync = true;
    }
  }

  // ─── Texture loading ──────────────────────────────────────────────────────

  function _rankNearestNodes(maxCount, requireUnloaded) {
    if (!_camera) return [];
    const cam = _camera.position;
    const camDir = _tmpCameraOffset.copy(_camera.getWorldDirection(new THREE.Vector3())).normalize();
    const ranked = [];

    for (const node of _nodes) {
      if (!node._visible || !node.thumb_url) continue;
      if (requireUnloaded && (node._tex || node._texQueued || node._texFailed)) continue;
      const dx = node.x - cam.x;
      const dy = node.y - cam.y;
      const dz = node.z - cam.z;
      // Prefer nodes near the camera plane depth so thumbs cover the silhouette
      // instead of only the visual center.
      const depth = dx * camDir.x + dy * camDir.y + dz * camDir.z;
      const lateral2 = dx * dx + dy * dy + dz * dz - depth * depth;
      const score = depth * depth + Math.max(0, lateral2) * 0.06;
      ranked.push({ node, d2: score });
    }

    // For prefetch queues we want nearest-first ordering.
    // For uncapped overlay sync (maxCount=0), sorting is unnecessary work.
    if (requireUnloaded || maxCount > 0) {
      ranked.sort((a, b) => a.d2 - b.d2);
    }
    if (maxCount > 0 && ranked.length > maxCount) ranked.length = maxCount;
    return ranked;
  }

  function _queueNearTextures() {
    if (!_showThumbs) return;
    if (_texPrefetchCount <= 0) return;
    const toLoad = _rankNearestNodes(_texPrefetchCount, true);
    for (let i = 0; i < toLoad.length; i++) {
      _enqueueTextureNode(toLoad[i].node, i);
    }
    _processTexQueue();
  }

  function _enqueueTextureNode(node, priority) {
    if (!node || node._tex || node._texFailed || !node.thumb_url) return;
    if (node._texQueued) return;
    node._texQueued = true;
    node._texPriority = Number.isFinite(priority) ? priority : Number.POSITIVE_INFINITY;
    _texQueue.push(node);
    _texQueueDirty = true;
  }

  function _processTexQueue() {
    if (_texQueueDirty && _texQueue.length > 1) {
      _texQueue.sort((a, b) => (a._texPriority ?? Number.POSITIVE_INFINITY) - (b._texPriority ?? Number.POSITIVE_INFINITY));
      _texQueueDirty = false;
    }
    while (_texLoading < _maxConcurrentTex && _texQueue.length > 0) {
      const node = _texQueue.shift();
      if (!node || node._tex || node._texFailed || !node.thumb_url) {
        if (node) {
          node._texQueued = false;
          node._texPriority = Number.POSITIVE_INFINITY;
        }
        continue;
      }
      _texLoading++;

      if (_texCache[node.thumb_url]) {
        node._tex = _texCache[node.thumb_url];
        node._texQueued = false;
        node._texPriority = Number.POSITIVE_INFINITY;
        _needsInstanceUpdate = true;
        _needsOverlaySync = true;
        _texLoading--;
        _processTexQueue();
        continue;
      }

      _texLoader.load(
        node.thumb_url,
        (tex) => {
          tex.colorSpace = THREE.SRGBColorSpace;
          _texCache[node.thumb_url] = tex;
          node._tex = tex;
          node._texQueued = false;
          node._texPriority = Number.POSITIVE_INFINITY;
          _needsInstanceUpdate = true;
          _needsOverlaySync = true;
          _texLoading--;
          _processTexQueue();
        },
        undefined,
        (err) => {
          console.warn('[3D] tex error', node.thumb_url.slice(0, 40), err);
          node._texQueued = false;
          node._texFailed = true;
          node._texPriority = Number.POSITIVE_INFINITY;
          _texLoading--;
          _processTexQueue();
        }
      );
    }
  }

  function _removeOverlay(nodeId) {
    const entry = _overlayMeshes.get(nodeId);
    if (!entry) return;
    entry.mesh.material.map = null;
    entry.mesh.material.dispose();
    _scene.remove(entry.mesh);
    _overlayMeshes.delete(nodeId);
  }

  function _ensureOverlay(node) {
    let entry = _overlayMeshes.get(node.id);
    if (entry) return entry;
    if (!node._tex || !_showThumbs) return null;

    const mat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      side: THREE.DoubleSide,
      transparent: true,
      map: node._tex,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    });
    const mesh = new THREE.Mesh(_sharedGeo, mat);
    mesh.renderOrder = 1;
    mesh.userData = { nodeId: node.id, node, isOverlay: true };
    _scene.add(mesh);
    entry = { mesh, node };
    _overlayMeshes.set(node.id, entry);
    return entry;
  }

  function _syncOverlayTransform(entry) {
    const { mesh, node } = entry;
    const profile = _activePhysicsProfile();
    const alpha = node._visAlpha ?? 1;
    if (!_showThumbs || !node._visible || alpha <= 0.02) {
      mesh.visible = false;
      return;
    }

    mesh.visible = true;
    mesh.quaternion.copy(_camera.quaternion);
    _tmpCameraOffset.copy(_camera.position).sub(_tmpPosition.set(node.x, node.y, node.z));
    const lenSq = _tmpCameraOffset.lengthSq();
    if (lenSq > 1e-6) {
      _tmpCameraOffset.multiplyScalar(profile.overlayOffset / Math.sqrt(lenSq));
    } else {
      _tmpCameraOffset.set(0, 0, 0);
    }
    mesh.position.set(
      node.x + _tmpCameraOffset.x,
      node.y + _tmpCameraOffset.y,
      node.z + _tmpCameraOffset.z
    );
    mesh.scale.setScalar(_nodeSize * (0.3 + alpha * 0.7) * profile.overlayScale);
    mesh.material.opacity = Math.max(0.2, Math.min(1, alpha + 0.1));
    if (mesh.material.map !== node._tex) {
      mesh.material.map = node._tex;
      mesh.material.needsUpdate = true;
    }
  }

  function _syncTextureOverlays(force) {
    if (!_camera) return;

    if (!_showThumbs) {
      if (_overlayMeshes.size > 0) _clearOverlayMeshes();
      _needsOverlaySync = false;
      _lastOverlaySyncAt = performance.now();
      return;
    }

    const ranked = _rankNearestNodes(_maxTextureOverlays, false);
    const wantedIds = new Set();
    for (let i = 0; i < ranked.length; i++) {
      const { node } = ranked[i];
      wantedIds.add(node.id);
      if (!node._tex) {
        _enqueueTextureNode(node, i);
        continue;
      }
      const entry = _ensureOverlay(node);
      if (entry) _syncOverlayTransform(entry);
    }

    for (const [nodeId] of _overlayMeshes) {
      if (!wantedIds.has(nodeId)) _removeOverlay(nodeId);
    }

    if (force || _texQueue.length > 0) _processTexQueue();
    _needsOverlaySync = false;
    _lastOverlaySyncAt = performance.now();
  }

  // ─── Click detection ──────────────────────────────────────────────────────

  function _pickNodeAtClient(clientX, clientY) {
    if (!_scene || !_camera || !_renderer) return null;
    const rect = _renderer.domElement.getBoundingClientRect();
    if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
      return null;
    }
    const mouse = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, _camera);
    const pickTargets = [];
    if (_instanceMesh) pickTargets.push(_instanceMesh);
    for (const { mesh } of _overlayMeshes.values()) {
      if (mesh.visible) pickTargets.push(mesh);
    }
    const hits = raycaster.intersectObjects(pickTargets, false);
    if (!hits[0]) return null;
    const hit = hits[0];
    if (hit.object === _instanceMesh && hit.instanceId !== undefined) {
      return _instanceNodes[hit.instanceId] || null;
    }
    return hit.object?.userData?.node || null;
  }

  function _onClick(e) {
    if (!_scene || !_camera) return;
    // OrbitControls can miss end events on some browsers/devices.
    // If no pointer is currently down, treat a lingering drag flag as stale.
    if (_controlsDragging && !_pointerDown) _controlsDragging = false;
    if (_controlsDragging) return;
    if (performance.now() < _suppressClickUntil) return;
    const node = _pickNodeAtClient(e.clientX, e.clientY);
    if (node && node.id && _clickCallback) _clickCallback(node.id, node);
  }

  // ─── Control panel ────────────────────────────────────────────────────────

  function _sanitizePresetName(rawName) {
    return String(rawName || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, MAX_PRESET_NAME_LEN);
  }

  function _findPresetByName(name) {
    if (!name) return null;
    return _presets.find((p) => p.name === name) || null;
  }

  function _currentLookSnapshot(name) {
    return _normalizePreset({
      name: name || "Current look",
      strength: _attractStrength,
      spread: _repulsion,
      size: _nodeSize,
      restPull: _restPull,
      focusedMode: true,
      liveMode: _liveMode,
      showThumbs: _showThumbs,
    });
  }

  function _setNumericControlValue(input, value, digits) {
    if (!input) return;
    const text = _fmtNum(value, digits);
    if ("value" in input) {
      if (document.activeElement !== input) input.value = text;
    } else {
      input.textContent = text;
    }
  }

  function _wireRangeNumberControl({ rangeId, numberId, min, max, fallback, digits, apply }) {
    const range = _controlsEl?.querySelector(`#${rangeId}`);
    const number = _controlsEl?.querySelector(`#${numberId}`);
    if (!range) return;

    const commit = (rawValue, { formatNumber = true } = {}) => {
      const value = _clamp(rawValue, min, max, fallback);
      range.value = String(value);
      if (number && formatNumber) number.value = _fmtNum(value, digits);
      apply(value);
    };

    range.addEventListener("input", (e) => {
      commit(e.target.value);
    });

    if (number) {
      number.addEventListener("input", (e) => {
        const raw = String(e.target.value || "").trim();
        if (!raw || raw === "-" || raw === "." || raw === "-.") return;
        commit(raw, { formatNumber: false });
      });
      number.addEventListener("change", (e) => {
        commit(e.target.value);
      });
      number.addEventListener("keydown", (e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      });
    }
  }

  function _syncControlInputsFromState() {
    if (!_controlsEl) return;
    const strSlider = _controlsEl.querySelector("#_attr3dStr");
    const spreadSlider = _controlsEl.querySelector("#_attr3dSpread");
    const sizeSlider = _controlsEl.querySelector("#_attr3dSize");
    const restPullSlider = _controlsEl.querySelector("#_attr3dRestPull");
    const strVal = _controlsEl.querySelector("#_attr3dStrVal");
    const spreadVal = _controlsEl.querySelector("#_attr3dSpreadVal");
    const sizeVal = _controlsEl.querySelector("#_attr3dSizeVal");
    const restPullVal = _controlsEl.querySelector("#_attr3dRestPullVal");
    const liveToggle = _controlsEl.querySelector("#_attr3dLive");
    const thumbsToggle = _controlsEl.querySelector("#_attr3dThumbs");
    if (strSlider) strSlider.value = String(_attractStrength);
    if (spreadSlider) spreadSlider.value = String(_repulsion);
    if (sizeSlider) sizeSlider.value = String(_nodeSize);
    if (restPullSlider) restPullSlider.value = String(_restPull);
    _setNumericControlValue(strVal, _attractStrength, 2);
    _setNumericControlValue(spreadVal, _repulsion, 0);
    _setNumericControlValue(sizeVal, _nodeSize, 2);
    _setNumericControlValue(restPullVal, _restPull, 3);
    _syncGroupByUi();
    if (liveToggle) liveToggle.checked = _liveMode;
    if (thumbsToggle) thumbsToggle.checked = _showThumbs;
  }

  function _refreshPresetControls(selectedName) {
    if (!_controlsEl) return;
    const presetSelect = _controlsEl.querySelector("#_attr3dPresetSelect");
    const presetDelete = _controlsEl.querySelector("#_attr3dPresetDelete");
    const startupToggle = _controlsEl.querySelector("#_attr3dPresetStartup");
    if (!presetSelect) return;

    const currentSelection = selectedName || presetSelect.value || "";
    presetSelect.innerHTML = `<option value="">Looks…</option>`;
    for (const preset of _presets) {
      const option = document.createElement("option");
      option.value = preset.name;
      option.textContent = preset.name;
      presetSelect.appendChild(option);
    }

    const nextSelection = _findPresetByName(currentSelection)
      ? currentSelection
      : (_findPresetByName(_startupPresetName) ? _startupPresetName : "");
    presetSelect.value = nextSelection;
    if (presetDelete) presetDelete.disabled = !nextSelection;
    if (startupToggle) {
      startupToggle.disabled = !nextSelection;
      startupToggle.checked = !!nextSelection && nextSelection === _startupPresetName;
    }
  }

  function _saveCurrentLookAsPreset(name) {
    const cleanName = _sanitizePresetName(name);
    if (!cleanName) return false;
    const look = _currentLookSnapshot(cleanName);
    if (!look) return false;
    const idx = _presets.findIndex((p) => p.name === cleanName);
    if (idx >= 0) {
      _presets[idx] = look;
      _saveSettings();
      return true;
    }
    if (_presets.length >= MAX_PRESET_COUNT) {
      window.alert(`Preset limit reached (${MAX_PRESET_COUNT}). Delete one before adding another.`);
      return false;
    }
    _presets.push(look);
    _saveSettings();
    return true;
  }

  function _deletePreset(name) {
    const idx = _presets.findIndex((p) => p.name === name);
    if (idx < 0) return false;
    _presets.splice(idx, 1);
    if (_startupPresetName === name) _startupPresetName = "";
    _saveSettings();
    return true;
  }

  function _groupByOptionsHtml() {
    return GROUP_BY_SPECS
      .filter((spec) => !spec.key || spec.key === "source" || Array.isArray(_attractorOptions[spec.key]))
      .map((spec) => `<option value="${spec.key}" ${_groupByKey === spec.key ? "selected" : ""}>${spec.label}</option>`)
      .join("");
  }

  function _groupByLabel(key) {
    const spec = GROUP_BY_SPECS.find((item) => item.key === key);
    return spec ? spec.label : "";
  }

  function _scopeNodesWithoutGrouping() {
    return _allNodes.filter((node) => {
      if (_filterIds && _filterIds.size > 0 && !_filterIds.has(node.id)) return false;
      if (!_nodeMatchesText(node)) return false;
      return true;
    });
  }

  function _groupOptionsForKey(key) {
    const scopeNodes = _scopeNodesWithoutGrouping();
    if (!key || !scopeNodes.length) return [];
    if (key === "source") {
      const counts = new Map();
      for (const node of scopeNodes) {
        const src = _normalizeSourceKey(node.source || "");
        if (!src) continue;
        counts.set(src, (counts.get(src) || 0) + 1);
      }
      return Array.from(counts.entries())
        .map(([source, count]) => ({
          source,
          name: GROUP_BY_SOURCE_LABELS[source] || source,
          count,
          px: 0, py: 0, pz: 0,
        }))
        .sort((a, b) => b.count - a.count)
        .slice(0, GROUP_BY_LIMIT);
    }

    const options = Array.isArray(_attractorOptions[key]) ? _attractorOptions[key] : [];
    return options
      .map((opt) => {
        let count = 0;
        for (const node of scopeNodes) {
          if (node.vector?.[opt.dim] > 0) count++;
        }
        return { dim: opt.dim, name: opt.name, count, px: 0, py: 0, pz: 0 };
      })
      .filter((opt) => opt.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, GROUP_BY_LIMIT);
  }

  function _refreshGroupByAttractors() {
    _activeAttractors = _groupOptionsForKey(_groupByKey);
    _syncGroupByUi();
  }

  function _syncGroupByUi() {
    const select = _controlsEl?.querySelector("#_attr3dGroupBy");
    if (select && select.value !== _groupByKey) select.value = _groupByKey;
    const clearBtn = _controlsEl?.querySelector("#_attr3dClearGrouping");
    if (clearBtn) clearBtn.disabled = !_groupByKey;

    const strip = _controlsEl?.querySelector("#_attr3dActiveGroups");
    const label = _controlsEl?.querySelector("#_attr3dActiveGroupsLabel");
    const chips = _controlsEl?.querySelector("#_attr3dGroupChips");
    if (!strip || !chips) return;
    chips.innerHTML = "";
    if (_focusedMode || _activeAttractors.length === 0) {
      strip.hidden = true;
      return;
    }

    strip.hidden = false;
    if (label) label.textContent = _groupByKey
      ? `Grouped by ${_groupByLabel(_groupByKey) || _groupByKey}`
      : "Grouped categories";
    for (const att of _activeAttractors) {
      const chip = document.createElement("span");
      chip.className = "attractor-chip attractor-group-chip active";
      chip.setAttribute("aria-label", `${att.name || "Group"} group, ${att.count || 0} items`);
      const name = document.createElement("span");
      name.textContent = att.name || "Group";
      const count = document.createElement("span");
      count.className = "chip-count";
      count.textContent = String(att.count || 0);
      chip.append(name, count);
      chips.appendChild(chip);
    }
  }

  function _setGroupBy(key) {
    const nextKey = String(key || "");
    const hadGroupBy = !!_groupByKey;
    _groupByKey = nextKey;
    if (_groupByKey) _focusedMode = false;
    if (!_groupByKey && hadGroupBy) _activeAttractors = [];
    _rebuildForFocusedMode();
  }

  function _nodeMatchesAttractor(node, att) {
    if (!node || !att) return false;
    return att.source !== undefined
      ? node.source === att.source
      : node.vector?.[att.dim] > 0;
  }

  function _nodeMatchesAnyAttractor(node) {
    if (_activeAttractors.length === 0) return true;
    return _activeAttractors.some((att) => _nodeMatchesAttractor(node, att));
  }

  function _syncAttractorChipStates() {
    if (!_controlsEl) return;
    _controlsEl.querySelectorAll(".attractor-chips-section .attractor-chip").forEach((chip) => {
      const srcStr = chip.dataset.src;
      const dim = Number.parseInt(chip.dataset.dim || "", 10);
      const isActive = srcStr
        ? _activeAttractors.some((a) => a.source === srcStr)
        : Number.isFinite(dim) && _activeAttractors.some((a) => a.dim === dim);
      chip.classList.toggle("active", isActive);
    });
  }

  function _syncCategoriesButtonUi() {
    const btn = _controlsEl?.querySelector(".attractor-panel-toggle");
    const count = _activeAttractors.length;
    if (btn) {
      btn.textContent = count > 0 ? `Categories (${count})` : "Categories";
      btn.classList.toggle("active", count > 0);
    }
    const clearBtn = _controlsEl?.querySelector(".attractor-clear-categories");
    if (clearBtn) clearBtn.disabled = count === 0;
  }

  function _syncModeSwitchUi() {
    const filterBtn = _controlsEl?.querySelector("#_attr3dModeFilter");
    const groupBtn = _controlsEl?.querySelector("#_attr3dModeGroup");
    if (filterBtn) {
      filterBtn.classList.toggle("active", _focusedMode);
      filterBtn.setAttribute("aria-pressed", _focusedMode ? "true" : "false");
    }
    if (groupBtn) {
      groupBtn.classList.toggle("active", !_focusedMode);
      groupBtn.setAttribute("aria-pressed", !_focusedMode ? "true" : "false");
    }
    const modeText = _controlsEl?.querySelector(".attractor-categories-toolbar span");
    if (modeText) {
      modeText.textContent = `Categories ${_focusedMode ? "filter matching items" : "group matching items"}`;
    }
  }

  function _computeOverlapStats() {
    if (_activeAttractors.length === 0) return null;

    const source = _scopeNodesWithoutGrouping();
    const coveredIds = new Set();
    for (const node of source) {
      if (_nodeMatchesAnyAttractor(node)) coveredIds.add(node.id);
    }

    const stats = new Map();
    for (const catKey of Object.keys(_attractorOptions)) {
      for (const opt of _attractorOptions[catKey] || []) {
        stats.set(opt.dim, { total: 0, unique: 0 });
      }
    }

    for (const node of source) {
      for (const [dim, s] of stats) {
        if (node.vector?.[dim] > 0) {
          s.total++;
          if (!coveredIds.has(node.id)) s.unique++;
        }
      }
    }
    return stats;
  }

  function _updateChipLabels() {
    if (!_controlsEl) return;
    const stats = _computeOverlapStats();
    const chips = _controlsEl.querySelectorAll(".attractor-chips-section .attractor-chip");
    chips.forEach((chip) => {
      const countEl = chip.querySelector(".chip-count");
      if (!countEl) return;
      const baseCount = Number.parseInt(chip.dataset.count || "", 10);
      const dim = Number.parseInt(chip.dataset.dim || "", 10);
      if (!stats || !Number.isFinite(dim)) {
        if (Number.isFinite(baseCount)) countEl.textContent = String(baseCount);
        countEl.title = "";
        return;
      }

      const s = stats.get(dim);
      if (!s) {
        if (Number.isFinite(baseCount)) countEl.textContent = String(baseCount);
        return;
      }

      const isActive = _activeAttractors.some((a) => a.dim === dim);
      if (isActive) {
        countEl.textContent = String(s.total);
        countEl.title = `${s.total} items match this category`;
      } else {
        countEl.textContent = `${s.unique}/${s.total}`;
        countEl.title = `${s.unique} new items not covered by active categories (${s.total} total)`;
      }
    });
  }

  function _toggleAttractor(opt) {
    _groupByKey = "";
    const idx = opt.source !== undefined
      ? _activeAttractors.findIndex((a) => a.source === opt.source)
      : _activeAttractors.findIndex((a) => a.dim === opt.dim);
    if (idx >= 0) {
      _activeAttractors.splice(idx, 1);
    } else {
      _activeAttractors.push(
        opt.source !== undefined
          ? { source: opt.source, name: opt.name, count: opt.count, px: 0, py: 0, pz: 0 }
          : { dim: opt.dim, name: opt.name, count: opt.count, px: 0, py: 0, pz: 0 }
      );
    }
    _rebuildForFocusedMode();
    _emitSelectionChange();
  }

  function _clearAttractors() {
    if (_activeAttractors.length === 0 && !_groupByKey) return;
    _groupByKey = "";
    _activeAttractors = [];
    _rebuildForFocusedMode();
    _emitSelectionChange();
  }

  function _applyLookAndRefresh(look) {
    if (!look) return false;
    _applyLookToState(look, { markManualSize: true });
    _liveCalm = 0;
    _syncControlInputsFromState();
    _saveSettings();
    _rebuildForFocusedMode();
    return true;
  }

  function _buildControls() {
    if (!_controlsEl) return;
    _controlsEl.innerHTML = "";

    const searchRow = document.createElement("div");
    searchRow.className = "attractor-search-row";
    searchRow.innerHTML = `
      <input class="attractor-search" type="search" placeholder="Type text to filter" aria-label="Filter map text">
      <button class="attractor-panel-toggle" type="button" aria-expanded="false">Categories</button>
      <span class="attractor-help-text">Sidebar filters choose the items. Group by arranges the current scope.</span>
    `;
    const searchInput = searchRow.querySelector(".attractor-search");
    const panelToggle = searchRow.querySelector(".attractor-panel-toggle");
    if (searchInput) searchInput.value = _searchTerm || "";
    if (panelToggle) {
      panelToggle.addEventListener("click", () => {
        const expanded = !_controlsEl.classList.contains("categories-open");
        _controlsEl.classList.toggle("categories-open", expanded);
        panelToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      });
    }
    _controlsEl.appendChild(searchRow);

    const slidersRow = document.createElement("div");
    slidersRow.className = "attractor-sliders";

    slidersRow.innerHTML = `
      <label class="slider-with-value">
        <span class="slider-label">Strength</span>
        <span class="slider-head"><input type="range" id="_attr3dStr" min="0.05" max="0.8" step="0.05" value="${_attractStrength}"><input class="slider-value slider-number" id="_attr3dStrVal" type="number" inputmode="decimal" min="0.05" max="0.8" step="0.05" value="${_fmtNum(_attractStrength, 2)}" aria-label="Strength value"></span>
      </label>
      <label class="slider-with-value">
        <span class="slider-label">Spread</span>
        <span class="slider-head"><input type="range" id="_attr3dSpread" min="1" max="20" step="1" value="${_repulsion}"><input class="slider-value slider-number" id="_attr3dSpreadVal" type="number" inputmode="numeric" min="1" max="20" step="1" value="${_fmtNum(_repulsion, 0)}" aria-label="Spread value"></span>
      </label>
      <label class="slider-with-value">
        <span class="slider-label">Size</span>
        <span class="slider-head"><input type="range" id="_attr3dSize" min="0.05" max="30" step="0.05" value="${_nodeSize}"><input class="slider-value slider-number" id="_attr3dSizeVal" type="number" inputmode="decimal" min="0.05" max="30" step="0.05" value="${_fmtNum(_nodeSize, 2)}" aria-label="Size value"></span>
      </label>
      <label class="slider-with-value">
        <span class="slider-label">Anchor</span>
        <span class="slider-head"><input type="range" id="_attr3dRestPull" min="${MIN_REST_PULL}" max="${MAX_REST_PULL}" step="0.002" value="${_restPull}"><input class="slider-value slider-number" id="_attr3dRestPullVal" type="number" inputmode="decimal" min="${MIN_REST_PULL}" max="${MAX_REST_PULL}" step="0.002" value="${_fmtNum(_restPull, 3)}" aria-label="Anchor value"></span>
      </label>
      <span class="filter-group-switch" role="group" aria-label="Category mode">
        <button type="button" id="_attr3dModeFilter" class="mode-option ${_focusedMode ? "active" : ""}" aria-pressed="${_focusedMode ? "true" : "false"}">Filter</button>
        <button type="button" id="_attr3dModeGroup" class="mode-option ${!_focusedMode ? "active" : ""}" aria-pressed="${!_focusedMode ? "true" : "false"}">Group</button>
      </span>
      <label class="group-by-control">Group by <select id="_attr3dGroupBy" aria-label="Group visible items">
        ${_groupByOptionsHtml()}
      </select></label>
      <button type="button" class="attractor-clear-grouping" id="_attr3dClearGrouping" ${_groupByKey ? "" : "disabled"}>Clear grouping</button>
      <label class="physics-toggle">Live <input type="checkbox" id="_attr3dLive" ${_liveMode ? "checked" : ""}></label>
      ${_isOwnerRole() ? `<label class="physics-toggle">Thumbs <input type="checkbox" id="_attr3dThumbs" ${_showThumbs ? "checked" : ""}></label>` : ""}
    `;
    _controlsEl.appendChild(slidersRow);

    const activeGroups = document.createElement("div");
    activeGroups.className = "attractor-active-groups";
    activeGroups.id = "_attr3dActiveGroups";
    activeGroups.hidden = true;
    activeGroups.innerHTML = `
      <span class="attractor-active-groups-label" id="_attr3dActiveGroupsLabel">Grouped</span>
      <span class="attractor-chips attractor-group-chips" id="_attr3dGroupChips"></span>
    `;
    _controlsEl.appendChild(activeGroups);

    const chipsSection = document.createElement("div");
    chipsSection.className = "attractor-chips-section";
    const toolbar = document.createElement("div");
    toolbar.className = "attractor-categories-toolbar";
    toolbar.innerHTML = `
      <span>Categories ${_focusedMode ? "filter matching items" : "group matching items"}</span>
      <button type="button" class="attractor-clear-categories">Clear categories</button>
    `;
    chipsSection.appendChild(toolbar);

    {
      const srcOrder = ["pinterest", "facebook", "houzz", "scan", "photo"];
      const srcLabels = { pinterest: "Pinterest", facebook: "Facebook", houzz: "Houzz", scan: "Scans", photo: "Photos" };
      const srcCounts = {};
      for (const n of _allNodes) srcCounts[n.source] = (srcCounts[n.source] || 0) + 1;
      const presentSrcs = srcOrder.filter((s) => srcCounts[s] > 0);
      if (presentSrcs.length > 0) {
        const group = document.createElement("details");
        group.className = "attractor-group";
        group.open = _activeAttractors.length === 0 || _activeAttractors.some((att) => att.source !== undefined);
        const lbl = document.createElement("summary");
        lbl.className = "attractor-group-label";
        lbl.innerHTML = `Source <span class="attractor-group-count">${presentSrcs.length}</span>`;
        group.appendChild(lbl);
        const chips = document.createElement("div");
        chips.className = "attractor-chips";
        for (const src of presentSrcs) {
          const cssColor = "#" + (SOURCE_COLORS[src] || 0x999999).toString(16).padStart(6, "0");
          const count = srcCounts[src];
          const btn = document.createElement("button");
          btn.className = "attractor-chip";
          btn.type = "button";
          btn.dataset.src = src;
          btn.dataset.count = count;
          btn.innerHTML = `<span class="src-dot" style="background:${cssColor}"></span>${srcLabels[src] || src} <span class="chip-count">${count}</span>`;
          btn.addEventListener("click", () => _toggleAttractor({ source: src, name: srcLabels[src] || src, count }));
          chips.appendChild(btn);
        }
        group.appendChild(chips);
        chipsSection.appendChild(group);
      }
    }

    const chipOrder = [
      "track",
      "space_context",
      "subject_type",
      "room",
      "product_focus",
      "concern_domain",
      "product_system_focus",
      "style_family",
      "materials",
      "colors",
    ];
    for (const catKey of chipOrder) {
      const options = _attractorOptions[catKey];
      if (!options || options.length === 0) continue;

      const group = document.createElement("details");
      group.className = "attractor-group";
      group.open = _activeAttractors.some((att) => options.some((opt) => opt.dim === att.dim))
        || (_activeAttractors.length === 0 && DEFAULT_OPEN_CATEGORY_KEYS.has(catKey));

      const label = document.createElement("summary");
      label.className = "attractor-group-label";
      label.innerHTML = `${(_categories[catKey] || {}).label || catKey} <span class="attractor-group-count">${options.length}</span>`;
      group.appendChild(label);

      const chips = document.createElement("div");
      chips.className = "attractor-chips";
      for (const opt of options) {
        const btn = document.createElement("button");
        btn.className = "attractor-chip";
        btn.type = "button";
        btn.dataset.dim = opt.dim;
        btn.dataset.name = opt.name;
        btn.dataset.count = opt.count;
        btn.innerHTML = `${opt.name} <span class="chip-count">${opt.count}</span>`;
        btn.addEventListener("click", () => _toggleAttractor(opt));
        chips.appendChild(btn);
      }
      group.appendChild(chips);
      chipsSection.appendChild(group);
    }
    _controlsEl.appendChild(chipsSection);
    const clearCategories = chipsSection.querySelector(".attractor-clear-categories");
    if (clearCategories) clearCategories.addEventListener("click", _clearAttractors);

    if (_isOwnerRole()) {
      const presetsRow = document.createElement("div");
      presetsRow.className = "attractor-presets-row";
      presetsRow.innerHTML = `
        <span class="preset-label">Looks</span>
        <select id="_attr3dPresetSelect" class="attractor-preset-select" aria-label="3D presets">
          <option value="">Looks…</option>
        </select>
        <button type="button" class="attractor-preset-btn" id="_attr3dPresetSave">Save</button>
        <button type="button" class="attractor-preset-btn" id="_attr3dPresetDelete" disabled>Delete</button>
        <label class="attractor-preset-startup">
          <input type="checkbox" id="_attr3dPresetStartup" disabled>
          Startup
        </label>
      `;
      _controlsEl.appendChild(presetsRow);
    }

    // Wire sliders and editable values. The number inputs are deliberately
    // redundant: precision dragging on iPad is unreliable.
    _wireRangeNumberControl({
      rangeId: "_attr3dStr",
      numberId: "_attr3dStrVal",
      min: 0.05,
      max: 0.8,
      fallback: _attractStrength,
      digits: 2,
      apply(value) {
        _attractStrength = value;
        _saveSettings();
        if (_activeAttractors.length > 0 && !_liveMode) _settleAndTween(_retickTicksForNodeCount(_nodes.length));
      },
    });

    _wireRangeNumberControl({
      rangeId: "_attr3dSpread",
      numberId: "_attr3dSpreadVal",
      min: 1,
      max: 20,
      fallback: _repulsion,
      digits: 0,
      apply(value) {
        _repulsion = value;
        _saveSettings();
        if (_activeAttractors.length > 0) {
          if (!_liveMode) _settleAndTween(_retickTicksForNodeCount(_nodes.length));
        } else {
          _resetNodesToRest();
          _syncInstanceMesh();
        }
      },
    });

    _wireRangeNumberControl({
      rangeId: "_attr3dSize",
      numberId: "_attr3dSizeVal",
      min: 0.05,
      max: 30,
      fallback: _nodeSize,
      digits: 2,
      apply(value) {
        _nodeSize = value;
        _sizeManuallySet = true;
        _saveSettings();
        _markSceneDirty();
      },
    });

    _wireRangeNumberControl({
      rangeId: "_attr3dRestPull",
      numberId: "_attr3dRestPullVal",
      min: MIN_REST_PULL,
      max: MAX_REST_PULL,
      fallback: _restPull,
      digits: 3,
      apply(value) {
        _restPull = value;
        _saveSettings();
      },
    });

    const groupBySelect = _controlsEl.querySelector("#_attr3dGroupBy");
    if (groupBySelect) groupBySelect.addEventListener("change", (e) => _setGroupBy(e.target.value || ""));
    const clearGroupingBtn = _controlsEl.querySelector("#_attr3dClearGrouping");
    if (clearGroupingBtn) clearGroupingBtn.addEventListener("click", () => _setGroupBy(""));

    const filterModeBtn = _controlsEl.querySelector("#_attr3dModeFilter");
    const groupModeBtn = _controlsEl.querySelector("#_attr3dModeGroup");
    if (filterModeBtn) filterModeBtn.addEventListener("click", () => setFocusedMode(true));
    if (groupModeBtn) groupModeBtn.addEventListener("click", () => setFocusedMode(false));

    const liveToggle = _controlsEl.querySelector("#_attr3dLive");
    if (liveToggle)
      liveToggle.addEventListener("change", (e) => {
        _liveDefaultEnabled = e.target.checked;
        _liveMode = e.target.checked;
        _liveCalm = 0;
        _saveSettings();
        if (_liveDefaultEnabled) {
          _armLiveBurst();
        } else {
          _endLiveBurst({ settle: true });
        }
      });

    const thumbsToggle = _controlsEl.querySelector("#_attr3dThumbs");
    if (thumbsToggle)
      thumbsToggle.addEventListener("change", (e) => {
        _showThumbs = e.target.checked;
        _saveSettings();
        _needsInstanceUpdate = true;
        if (!_showThumbs) {
          _clearOverlayMeshes();
        } else {
          _queueNearTextures();
          _syncTextureOverlays(true);
        }
      });

    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        _searchTerm = (e.target.value || "").toLowerCase().trim();
        _emitTextFilterChange(e.target.value || "");
        _rebuildForFocusedMode();
      });
    }

    const presetSelect = _controlsEl.querySelector("#_attr3dPresetSelect");
    const presetSave = _controlsEl.querySelector("#_attr3dPresetSave");
    const presetDelete = _controlsEl.querySelector("#_attr3dPresetDelete");
    const startupToggle = _controlsEl.querySelector("#_attr3dPresetStartup");

    if (presetSelect) {
      presetSelect.addEventListener("change", () => {
        const name = _sanitizePresetName(presetSelect.value);
        if (!name) {
          _refreshPresetControls("");
          return;
        }
        const preset = _findPresetByName(name);
        if (!preset) {
          _refreshPresetControls("");
          return;
        }
        _applyLookAndRefresh(preset);
        _refreshPresetControls(name);
      });
    }

    if (presetSave) {
      presetSave.addEventListener("click", () => {
        const seed = _sanitizePresetName(presetSelect?.value) || "";
        const rawName = window.prompt("Save current 3D look as:", seed || "My look");
        const name = _sanitizePresetName(rawName);
        if (!name) return;
        if (_saveCurrentLookAsPreset(name)) {
          _refreshPresetControls(name);
        }
      });
    }

    if (presetDelete) {
      presetDelete.addEventListener("click", () => {
        const name = _sanitizePresetName(presetSelect?.value);
        if (!name) return;
        if (!window.confirm(`Delete preset "${name}"?`)) return;
        if (_deletePreset(name)) {
          _refreshPresetControls("");
        }
      });
    }

    if (startupToggle) {
      startupToggle.addEventListener("change", () => {
        const selectedName = _sanitizePresetName(presetSelect?.value);
        if (!selectedName) {
          startupToggle.checked = false;
          startupToggle.disabled = true;
          _startupPresetName = "";
          _saveSettings();
          return;
        }
        _startupPresetName = startupToggle.checked ? selectedName : "";
        _saveSettings();
        _refreshPresetControls(selectedName);
      });
    }

    _refreshPresetControls("");
    _syncAttractorChipStates();
    _syncCategoriesButtonUi();
    _syncModeSwitchUi();
    _syncGroupByUi();
    _updateChipLabels();
  }

  function _emitSelectionChange() {
    if (typeof _selectCallback !== "function") return;
    const scopeAttractors = _focusedMode ? _activeAttractors : [];
    _selectCallback(getVisibleNodeIds(), {
      activeAttractors: scopeAttractors.map((att) => ({
        name: att.name || "",
        count: att.count || 0,
        source: att.source,
        dim: att.dim,
      })),
      categoryMode: _focusedMode ? "filter" : "group",
    });
  }

  function _emitTextFilterChange(term) {
    window.dispatchEvent(new CustomEvent("inspirations:explorer-text-filter", {
      detail: { term: String(term || "") },
    }));
  }

  function _nodeMatchesText(node) {
    if (!_searchTerm) return true;
    const haystack = `${node.title || ""} ${node.source || ""}`.toLowerCase();
    return haystack.includes(_searchTerm);
  }

  // ─── Scope rebuild ────────────────────────────────────────────────────────

  function _rebuildForFocusedMode() {
    _cancelDeferredSettle();
    _clearOverlayMeshes();
    _disposeInstanceMesh();
    _texQueue.length = 0;               // clear pending queue
    _texQueueDirty = false;
    _texLoading = 0;
    for (const node of _allNodes) {    // reset so nodes can be re-queued after rebuild
      if (!node._tex && !node._texFailed) node._texQueued = false;
      node._texPriority = Number.POSITIVE_INFINITY;
    }

    // Sidebar/text filters define the base scope. Category chips can either
    // filter that scope or group it, depending on the toolbar switch.
    const scopeNodes = _scopeNodesWithoutGrouping();
    if (_groupByKey) {
      _focusedMode = false;
      _refreshGroupByAttractors();
    } else {
      _syncGroupByUi();
    }
    _nodes = (_focusedMode && _activeAttractors.length > 0)
      ? scopeNodes.filter((node) => _nodeMatchesAnyAttractor(node))
      : scopeNodes;

    _buildInstanceMesh();

    // Reset velocities
    for (const node of _nodes) {
      node.vx = 0; node.vy = 0; node.vz = 0;
    }

    if (_activeAttractors.length > 0) {
      _updateAttractorForces();
    } else {
      _resetNodesToRest();
      _updatePoleMarkers();
      _syncInstanceMesh();
      if (_liveDefaultEnabled) _armLiveBurst();
    }

    _markVisualsDirty();
    _updateNodeVisuals(true);
    _syncInstanceMesh();
    _smoothCenterVisibleCluster();
    _syncAttractorChipStates();
    _syncCategoriesButtonUi();
    _syncModeSwitchUi();
    _syncGroupByUi();
    _updateChipLabels();
    // Queue texture loads for any nodes that still need them
    _queueNearTextures();
    _syncTextureOverlays(true);
  }

  // ─── Public API ───────────────────────────────────────────────────────────

  function setFilter(nodeIds) {
    const nextFilter = nodeIds ? new Set(nodeIds) : null;
    if (_sameIdSet(_filterIds, nextFilter)) return;
    _filterIds = nextFilter;
    _rebuildForFocusedMode();
  }

  function setSearch(term) {
    const rawTerm = term || "";
    const nextTerm = rawTerm.toLowerCase().trim();
    const input = _controlsEl?.querySelector(".attractor-search");
    if (input && input.value !== rawTerm) input.value = rawTerm;
    if (_searchTerm === nextTerm) return;
    _searchTerm = nextTerm;
    _rebuildForFocusedMode();
  }

  function setFocusedMode(on) {
    _focusedMode = !!on;
    if (_focusedMode && _groupByKey) {
      _groupByKey = "";
      _activeAttractors = [];
    }
    _saveSettings();
    _rebuildForFocusedMode();
    _emitSelectionChange();
  }

  function getVisibleNodeIds() {
    return (_nodes || []).map((node) => node.id).filter(Boolean);
  }

  function highlight(nodeIds) {
    _highlightedIds = nodeIds ? new Set(nodeIds) : null;
    _markVisualsDirty();
  }

  function onSelect(callback) {
    _selectCallback = callback;
  }

  function onClickNode(callback) {
    _clickCallback = callback;
  }

  function pause() {
    _paused = true;
  }

  function resume() {
    _paused = false;
    if (!_animFrameId) _startRenderLoop();
  }

  function destroy() {
    _cancelDeferredSettle();
    _deferSettleUntil = 0;
    _stopRenderLoop();
    _clearScene();
    if (_controls) {
      if (_controlsStartHandler) _controls.removeEventListener("start", _controlsStartHandler);
      if (_controlsEndHandler) _controls.removeEventListener("end", _controlsEndHandler);
      _controlsStartHandler = null;
      _controlsEndHandler = null;
      _controls.dispose();
      _controls = null;
    }
    if (_renderer?.domElement) {
      _renderer.domElement.removeEventListener("click", _onClick);
      if (_pointerDownHandler) _renderer.domElement.removeEventListener("pointerdown", _pointerDownHandler);
      if (_pointerMoveHandler) _renderer.domElement.removeEventListener("pointermove", _pointerMoveHandler);
      if (_pointerUpHandler) _renderer.domElement.removeEventListener("pointerup", _pointerUpHandler);
      if (_pointerCancelHandler) _renderer.domElement.removeEventListener("pointercancel", _pointerCancelHandler);
      if (_pointerLeaveHandler) _renderer.domElement.removeEventListener("pointerleave", _pointerLeaveHandler);
    }
    if (_pointerUpHandler) window.removeEventListener("pointerup", _pointerUpHandler);
    if (_pointerCancelHandler) window.removeEventListener("pointercancel", _pointerCancelHandler);
    if (_hoverPreviewRaf) {
      cancelAnimationFrame(_hoverPreviewRaf);
      _hoverPreviewRaf = 0;
    }
    _hideHoverPreview();
    _pointerDownHandler = null;
    _pointerMoveHandler = null;
    _pointerUpHandler = null;
    _pointerCancelHandler = null;
    _pointerLeaveHandler = null;
    _pointerDown = null;
    _dragMoved = false;
    _controlsDragging = false;
    _suppressClickUntil = 0;
    _hoverPreviewClientX = 0;
    _hoverPreviewClientY = 0;
    _hoverPreviewNodeId = "";
    _lastCameraPos = null;
    _needsVisualUpdate = false;
    _needsInstanceUpdate = false;
    _needsOverlaySync = false;
    _lastOverlaySyncAt = 0;
    _tmpMatrix = null;
    _tmpPosition = null;
    _tmpScale = null;
    _tmpColor = null;
    _tmpBgColor = null;
    _tmpCameraOffset = null;
    if (_sharedGeo) {
      _sharedGeo.dispose();
      _sharedGeo = null;
    }
    if (_renderer) {
      _renderer.dispose();
      _renderer.domElement.remove();
      _renderer = null;
    }
    if (_resizeObserver) {
      _resizeObserver.disconnect();
      _resizeObserver = null;
    }
    if (_hoverPreviewEl) {
      _hoverPreviewEl.remove();
      _hoverPreviewEl = null;
    }
    _hoverPreviewImgEl = null;
    _hoverPreviewTitleEl = null;
    if (_controlsEl) _controlsEl.remove();
    const toolbarMount = document.getElementById("explorerToolbarMount");
    if (toolbarMount && toolbarMount.children.length === 0) toolbarMount.hidden = true;
    if (_labelsEl) _labelsEl.remove();
    _controlsEl = null;
    _labelsEl = null;
  }

  // ─── Export ───────────────────────────────────────────────────────────────

  window.AttractorExplorer3D = {
    __unavailable: false,
    init,
    loadData,
    setFilter,
    setSearch,
    setFocusedMode,
    getVisibleNodeIds,
    highlight,
    onSelect,
    onClickNode,
    pause,
    resume,
    resize,
    destroy,
  };
})();
