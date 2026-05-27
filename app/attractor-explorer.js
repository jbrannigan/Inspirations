/**
 * Attractor Explorer — 2D force-directed semantic visualization
 *
 * Canvas-based D3 force layout where users toggle semantic "attractors"
 * (Bathroom, Modern, Wood…) that pull matching items toward labeled poles.
 *
 * Default mode: pre-computed physics. The simulation runs synchronously for
 * N ticks to get settled positions, then renders a single frame. No ongoing
 * CPU cost. "Live" checkbox enables real-time simulation for visual feedback.
 *
 * Sets window.AttractorExplorer with the same public API shape as Explorer.
 */
(function () {
  "use strict";

  // ─── State ───────────────────────────────────────────────────────────────
  let _container = null;
  let _canvas = null;
  let _ctx = null;
  let _controlsEl = null;
  let _labelsEl = null; // overlay for attractor pole labels
  let _simulation = null;
  let _nodes = [];
  let _allNodes = [];    // full node list (always preserved, even in focused mode)
  let _dimensions = [];
  let _categories = {};
  let _attractorOptions = {};
  let _activeAttractors = []; // [{dim, name, count, px, py}]
  let _transform = { x: 0, y: 0, k: 1 };
  let _zoomBehavior = null;
  let _width = 800;
  let _height = 600;
  let _paused = false;
  let _clickCallback = null;
  let _selectCallback = null;
  let _highlightedIds = null;
  let _filterIds = null;
  let _searchTerm = "";
  let _rafId = null;
  let _focusedMode = true; // when ON, only filtered items participate in simulation

  // Settings (controllable via sliders)
  let _attractStrength = 0.35;
  let _repulsion = -6;
  let _nodeSize = 18;
  let _colorMode = "source"; // source | cluster | room | style
  let _liveMode = false;     // false = pre-computed (default); true = live render loop

  // CSS pre-zoom tracking (for instant visual feedback during zoom)
  let _lastRenderedTransform = { x: 0, y: 0, k: 1 };

  // Tween state (for smooth transitions between pre-computed layouts)
  let _tweenStart = 0;
  let _tweenDuration = 600;  // ms
  let _tweening = false;
  let _centerTweenId = 0;

  // Pre-computed physics settings
  const SETTLE_TICKS = 200;   // ticks for initial layout
  const RETICK = 150;         // ticks when attractors change

  // Thumbnail loading
  let _showThumbs = true;
  const _imgCache = {};
  let _thumbsLoading = 0;
  const _thumbQueue = [];
  const MAX_CONCURRENT_THUMBS = 12;
  const MOBILE_MAX_CONCURRENT_THUMBS = 4;

  // Quadtree for hit testing
  let _quadtree = null;

  // Color palettes
  const SOURCE_COLORS = {
    pinterest: "#c8553d",
    facebook: "#4267b2",
    houzz: "#4dbc63",
    scan: "#8b6914",
    photo: "#5b6f8c",
  };
  const DEFAULT_OPEN_CATEGORY_KEYS = new Set(["room", "style_family", "materials", "colors"]);

  function _normalizeSourceKey(source) {
    const key = String(source || "").trim().toLowerCase();
    if (key === "clip" || key === "clips" || key === "magazine clip" || key === "magazine clips") {
      return "scan";
    }
    return key;
  }

  const CLUSTER_PALETTE = [
    "#b8860b", "#8b6914", "#6b8e23", "#7b68ee", "#cd853f",
    "#2e8b57", "#b05050", "#4682b4", "#d2691e", "#708090",
    "#9b59b6", "#1abc9c", "#e67e22", "#c0392b", "#7f8c8d",
  ];

  function _isMobileConstrained() {
    return !!(
      window.matchMedia &&
      (
        window.matchMedia("(max-width: 900px)").matches ||
        window.matchMedia("(hover: none) and (pointer: coarse)").matches
      )
    );
  }

  // ─── Init ────────────────────────────────────────────────────────────────

  function init(containerId) {
    _container = document.getElementById(containerId);
    if (!_container) return;
    _container.style.position = "relative";

    _width = _container.clientWidth || 800;
    _height = _container.clientHeight || 600;

    // Canvas
    _canvas = document.createElement("canvas");
    _canvas.width = _width;
    _canvas.height = _height;
    _canvas.style.width = "100%";
    _canvas.style.height = "100%";
    _canvas.style.cursor = "grab";
    _container.appendChild(_canvas);
    _ctx = _canvas.getContext("2d");

    // Attractor pole label overlay
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

    // Zoom & pan via D3 with CSS pre-zoom for instant feedback
    if (typeof d3 !== "undefined") {
      _zoomBehavior = d3
        .zoom()
        .scaleExtent([0.15, 6])
        .on("zoom", (event) => {
          _transform = event.transform;
          // Instant CSS pre-zoom: show approximate zoom while canvas repaints
          const lt = _lastRenderedTransform;
          const relScale = _transform.k / lt.k;
          const dx = _transform.x - lt.x * relScale;
          const dy = _transform.y - lt.y * relScale;
          _canvas.style.transformOrigin = "0 0";
          _canvas.style.transform = `translate(${dx}px, ${dy}px) scale(${relScale})`;
          _scheduleRender();
          _updateVisibleThumbs();
        });

      d3.select(_canvas).call(_zoomBehavior);

      // Click detection
      _canvas.addEventListener("click", _onClick);
    }

    // Resize observer
    const ro = new ResizeObserver(() => {
      resize();
    });
    ro.observe(_container);
  }

  function resize() {
    if (!_container || !_canvas) return;
    _width = Math.max(1, _container.clientWidth || 800);
    _height = Math.max(1, _container.clientHeight || 600);
    _canvas.width = _width;
    _canvas.height = _height;
    _scheduleRender();
  }

  // ─── Data loading ────────────────────────────────────────────────────────

  function loadData(data) {
    _dimensions = data.dimensions || [];
    _categories = data.categories || {};
    _attractorOptions = data.attractors || {};

    // Build nodes with full vectors.
    // Scale PCA coords to fill usable canvas area (leave margin for controls + edges).
    const assets = data.assets || [];
    const controlsH = 220; // approximate height of control panel
    const margin = 40;
    const usableW = _width - margin * 2;
    const usableH = _height - controlsH - margin;
    const ucx = _width / 2;
    const ucy = controlsH + usableH / 2;

    // Find PCA data range
    let pcaMinX = Infinity, pcaMaxX = -Infinity;
    let pcaMinY = Infinity, pcaMaxY = -Infinity;
    for (const a of assets) {
      if (a.x < pcaMinX) pcaMinX = a.x;
      if (a.x > pcaMaxX) pcaMaxX = a.x;
      if (a.y < pcaMinY) pcaMinY = a.y;
      if (a.y > pcaMaxY) pcaMaxY = a.y;
    }
    const pcaRangeX = pcaMaxX - pcaMinX || 1;
    const pcaRangeY = pcaMaxY - pcaMinY || 1;
    const pcaMidX = (pcaMinX + pcaMaxX) / 2;
    const pcaMidY = (pcaMinY + pcaMaxY) / 2;
    // Uniform scale to fit both axes (preserve aspect ratio)
    const pcaScale = Math.min(usableW / pcaRangeX, usableH / pcaRangeY) * 0.9;

    _nodes = assets.map((a) => {
      // Reconstruct full vector from sparse
      const vec = new Float32Array(_dimensions.length);
      if (a.v) {
        for (const [idx, w] of Object.entries(a.v)) {
          vec[parseInt(idx)] = w;
        }
      }
      // Scale PCA coordinates to fill usable canvas
      const sx = ucx + (a.x - pcaMidX) * pcaScale;
      const sy = ucy + (a.y - pcaMidY) * pcaScale;
      return {
        id: a.id,
        vector: vec,
        x: sx,
        y: sy,
        _restX: sx,
        _restY: sy,
        thumb_url: (window.Shared && Shared.prefixPath) ? Shared.prefixPath(a.t) : a.t,
        title: a.title || "",
        source: _normalizeSourceKey(a.src || ""),
        _img: null,
        _imgQueued: false,
        _color: SOURCE_COLORS[_normalizeSourceKey(a.src)] || "#999",
      };
    });

    // Preserve full node list for overlap stats & focused mode restore
    _allNodes = _nodes.slice();

    // Build controls
    _buildControls();

    // Create the simulation (always needed for pre-computed physics)
    _initSimulation();

    // Settle the initial PCA layout with collision avoidance
    _settleSimulation(_isMobileConstrained() ? 60 : SETTLE_TICKS);

    // Render the settled state
    _updateQuadtree();
    _scheduleRender();

    // If live mode, also start the render loop
    if (_liveMode) _startRenderLoop();

    // Queue visible thumbnails
    _updateVisibleThumbs();
  }

  // ─── Force simulation ────────────────────────────────────────────────────

  function _initSimulation() {
    if (typeof d3 === "undefined") return;

    // Stop any existing simulation
    if (_simulation) _simulation.stop();

    _simulation = d3
      .forceSimulation(_nodes)
      .force("charge", d3.forceManyBody().strength(_repulsion).distanceMax(250))
      .force("collide", d3.forceCollide().radius(_nodeSize / 2 + 1).iterations(1))
      .force(
        "restX",
        d3.forceX((d) => d._restX).strength(0.08)
      )
      .force(
        "restY",
        d3.forceY((d) => d._restY).strength(0.08)
      )
      .alphaDecay(0.02)
      .velocityDecay(0.35)
      .stop(); // Don't auto-run — we'll tick manually or start explicitly
  }

  /**
   * Run the simulation synchronously for N ticks, then stop.
   * This produces settled positions without an ongoing render loop.
   */
  function _settleSimulation(ticks) {
    if (!_simulation) return;
    _simulation.alpha(0.5);
    for (let i = 0; i < ticks; i++) {
      _simulation.tick();
    }
    _simulation.stop();
  }

  /**
   * Snapshot current node positions, settle simulation, then tween from
   * old positions to new settled positions for smooth visual transition.
   */
  function _settleAndTween(ticks) {
    // Stash current positions for tween
    for (const node of _nodes) {
      node._tweenFromX = node.x;
      node._tweenFromY = node.y;
    }

    // Settle to new positions
    _settleSimulation(ticks);

    // Stash settled positions as targets
    for (const node of _nodes) {
      node._targetX = node.x;
      node._targetY = node.y;
      // Restore to old position so tween starts from there
      node.x = node._tweenFromX;
      node.y = node._tweenFromY;
    }

    // Animate
    _startTween();
  }

  function _updateAttractorForces() {
    if (!_simulation) return;

    // Remove all existing attractor forces
    for (let i = 0; i < 20; i++) {
      _simulation.force(`ax${i}`, null);
      _simulation.force(`ay${i}`, null);
    }

    if (_activeAttractors.length === 0) {
      // Restore rest position forces (PCA layout)
      _simulation.force(
        "restX",
        d3.forceX((d) => d._restX).strength(0.08)
      );
      _simulation.force(
        "restY",
        d3.forceY((d) => d._restY).strength(0.08)
      );
    } else {
      // Weaken rest forces when attractors are active
      _simulation.force(
        "restX",
        d3.forceX(_width / 2).strength(0.005)
      );
      _simulation.force(
        "restY",
        d3.forceY(_height / 2).strength(0.005)
      );

      // Position attractors in a ring — offset down to avoid controls overlay
      const controlsH = _controlsEl ? _controlsEl.offsetHeight + 16 : 0;
      const cx = _width / 2;
      const cy = (controlsH + _height) / 2;               // center of usable area
      const usableH = _height - controlsH;
      const radius = Math.min(_width, usableH) * 0.42;

      _activeAttractors.forEach((att, i) => {
        const theta =
          (Math.PI * 2 * i) / _activeAttractors.length - Math.PI / 2;
        att.px = cx + radius * Math.cos(theta);
        att.py = Math.max(controlsH + 20, cy + radius * Math.sin(theta));

        const dimIdx = att.dim;
        _simulation.force(
          `ax${i}`,
          d3
            .forceX(att.px)
            .strength((d) => att.source !== undefined
              ? (d.source === att.source ? _attractStrength : 0)
              : d.vector[dimIdx] * _attractStrength)
        );
        _simulation.force(
          `ay${i}`,
          d3
            .forceY(att.py)
            .strength((d) => att.source !== undefined
              ? (d.source === att.source ? _attractStrength : 0)
              : d.vector[dimIdx] * _attractStrength)
        );
      });
    }

    if (_liveMode) {
      // Live: reheat and let the render loop show the animation
      _simulation.alpha(0.6).restart();
    } else {
      // Pre-computed: settle synchronously and tween
      _settleAndTween(RETICK);
    }

    _updateAttractorLabels();
  }

  // ─── Tween animation ──────────────────────────────────────────────────────

  function _startTween() {
    _tweenStart = performance.now();
    _tweening = true;
    _updateAttractorLabels();
    _runTweenLoop();
  }

  function _runTweenLoop() {
    if (!_tweening) return;
    const elapsed = performance.now() - _tweenStart;
    const t = Math.min(1, elapsed / _tweenDuration);
    // Ease-out cubic
    const ease = 1 - Math.pow(1 - t, 3);

    for (const node of _nodes) {
      node.x = node._tweenFromX + (node._targetX - node._tweenFromX) * ease;
      node.y = node._tweenFromY + (node._targetY - node._tweenFromY) * ease;
    }

    _updateQuadtree();
    _render();

    if (t < 1) {
      requestAnimationFrame(_runTweenLoop);
    } else {
      _tweening = false;
      _updateVisibleThumbs();
    }
  }

  function _smoothCenterVisibleCluster() {
    if (!_canvas || !_nodes.length) return;
    let sumX = 0;
    let sumY = 0;
    let count = 0;
    for (const node of _nodes) {
      const x = Number.isFinite(node._targetX) ? node._targetX : node.x;
      const y = Number.isFinite(node._targetY) ? node._targetY : node.y;
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      sumX += x;
      sumY += y;
      count++;
    }
    if (!count) return;

    const cx = sumX / count;
    const cy = sumY / count;
    const k = _transform.k || 1;
    const target = {
      x: (_width * 0.5) - (cx * k),
      y: (_height * 0.5) - (cy * k),
      k,
    };

    // Use D3's zoom pipeline when available so pan state and user interactions
    // stay in sync. Fall back to a lightweight tween if D3 is unavailable.
    if (typeof d3 !== "undefined" && _zoomBehavior && d3.zoomIdentity) {
      d3.select(_canvas)
        .transition()
        .duration(520)
        .ease(d3.easeCubicOut)
        .call(
          _zoomBehavior.transform,
          d3.zoomIdentity.translate(target.x, target.y).scale(target.k)
        );
      return;
    }

    const runId = ++_centerTweenId;
    const start = performance.now();
    const from = { x: _transform.x, y: _transform.y, k: _transform.k };
    const duration = 520;
    const step = () => {
      if (runId !== _centerTweenId) return;
      const t = Math.min(1, (performance.now() - start) / duration);
      const ease = 1 - Math.pow(1 - t, 3);
      _transform = {
        x: from.x + (target.x - from.x) * ease,
        y: from.y + (target.y - from.y) * ease,
        k: from.k + (target.k - from.k) * ease,
      };
      _scheduleRender();
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ─── Attractor pole labels ───────────────────────────────────────────────

  function _updateAttractorLabels() {
    if (!_labelsEl) return;
    _labelsEl.innerHTML = "";

    for (const att of _activeAttractors) {
      const el = document.createElement("div");
      el.className = "attractor-pole-label";
      el.textContent = att.name;
      // Position in canvas coords, adjusted by transform
      const sx = att.px * _transform.k + _transform.x;
      const sy = att.py * _transform.k + _transform.y;
      el.style.cssText = `
        position:absolute;left:${sx}px;top:${sy}px;
        transform:translate(-50%,-50%);
        font-size:13px;font-weight:700;
        color:#fde047;
        text-shadow:0 1px 6px rgba(0,0,0,0.8), 0 0 20px rgba(184,134,11,0.4);
        white-space:nowrap;pointer-events:none;
        letter-spacing:0.5px;
      `;
      _labelsEl.appendChild(el);
    }
  }

  // ─── Rendering ───────────────────────────────────────────────────────────

  let _renderScheduled = false;
  function _scheduleRender() {
    if (!_renderScheduled) {
      _renderScheduled = true;
      requestAnimationFrame(_render);
    }
  }

  function _startRenderLoop() {
    function loop() {
      if (_paused) return;
      _updateQuadtree();
      _render();
      _rafId = requestAnimationFrame(loop);
    }
    _rafId = requestAnimationFrame(loop);
  }

  function _stopRenderLoop() {
    if (_rafId) {
      cancelAnimationFrame(_rafId);
      _rafId = null;
    }
  }

  function _render() {
    _renderScheduled = false;
    if (!_ctx || !_canvas) return;

    // Clear CSS pre-zoom transform now that we're doing a real repaint
    if (_canvas.style.transform) {
      _canvas.style.transform = "";
    }
    _lastRenderedTransform = { x: _transform.x, y: _transform.y, k: _transform.k };

    const w = _canvas.width;
    const h = _canvas.height;
    const k = _transform.k;
    const tx = _transform.x;
    const ty = _transform.y;

    // Clear with background
    _ctx.fillStyle = getComputedStyle(document.documentElement)
      .getPropertyValue("--bg")
      .trim() || "#faf8f5";
    _ctx.fillRect(0, 0, w, h);

    _ctx.save();
    _ctx.translate(tx, ty);
    _ctx.scale(k, k);

    const size = _nodeSize;
    const half = size / 2;

    // Visible bounds in world coords
    const vx0 = -tx / k - size;
    const vy0 = -ty / k - size;
    const vx1 = (w - tx) / k + size;
    const vy1 = (h - ty) / k + size;

    // Draw attractor connection lines (subtle)
    if (_activeAttractors.length > 0) {
      _ctx.globalAlpha = 0.04;
      _ctx.strokeStyle = "#b8860b";
      _ctx.lineWidth = 0.5;
      for (const att of _activeAttractors) {
        for (const node of _nodes) {
          if (node.vector[att.dim] > 0.3) {
            _ctx.beginPath();
            _ctx.moveTo(node.x, node.y);
            _ctx.lineTo(att.px, att.py);
            _ctx.stroke();
          }
        }
      }
      _ctx.globalAlpha = 1;
    }

    // Draw attractor dots
    for (const att of _activeAttractors) {
      _ctx.beginPath();
      _ctx.arc(att.px, att.py, 8, 0, Math.PI * 2);
      _ctx.fillStyle = "rgba(253, 224, 71, 0.3)";
      _ctx.fill();
      _ctx.strokeStyle = "#fde047";
      _ctx.lineWidth = 2;
      _ctx.stroke();
    }

    // Draw nodes
    for (const node of _nodes) {
      // Culling
      if (node.x < vx0 || node.x > vx1 || node.y < vy0 || node.y > vy1)
        continue;

      // Opacity for filter / highlight / search
      let alpha = 1;
      if (_filterIds && !_filterIds.has(node.id)) alpha = 0.07;
      if (_highlightedIds && !_highlightedIds.has(node.id)) alpha = 0.08;
      if (
        _searchTerm &&
        !node.title.toLowerCase().includes(_searchTerm)
      )
        alpha = 0.1;

      _ctx.globalAlpha = alpha;

      const x = node.x - half;
      const y = node.y - half;

      // Draw thumbnail or colored square
      if (_showThumbs && node._img && node._img.complete && node._img.naturalWidth > 0) {
        _ctx.drawImage(node._img, x, y, size, size);
      } else {
        _ctx.fillStyle = _getNodeColor(node);
        _ctx.fillRect(x, y, size, size);
      }

      // Border
      _ctx.strokeStyle = alpha < 0.5 ? "rgba(0,0,0,0.05)" : "rgba(0,0,0,0.15)";
      _ctx.lineWidth = 0.5;
      _ctx.strokeRect(x, y, size, size);
    }

    _ctx.globalAlpha = 1;
    _ctx.restore();

    // Update attractor label positions (they're HTML overlays)
    _updateAttractorLabels();
  }

  function _getNodeColor(node) {
    if (_colorMode === "source") {
      return SOURCE_COLORS[node.source] || "#999";
    }
    // Could add more color modes later
    return node._color || "#999";
  }

  // ─── Thumbnail loading ───────────────────────────────────────────────────

  function _updateVisibleThumbs() {
    if (!_nodes.length) return;
    const k = _transform.k;
    const tx = _transform.x;
    const ty = _transform.y;
    const w = _width;
    const h = _height;
    const size = _nodeSize;

    // Only load thumbnails when zoomed in enough to see them
    if (k * size < 6) return;

    const vx0 = -tx / k - size;
    const vy0 = -ty / k - size;
    const vx1 = (w - tx) / k + size;
    const vy1 = (h - ty) / k + size;

    for (const node of _nodes) {
      if (
        node.x >= vx0 && node.x <= vx1 &&
        node.y >= vy0 && node.y <= vy1 &&
        node.thumb_url && !node._img && !node._imgQueued
      ) {
        node._imgQueued = true;
        _thumbQueue.push(node);
      }
    }
    _processThumbQueue();
  }

  function _processThumbQueue() {
    const maxConcurrent = _isMobileConstrained() ? MOBILE_MAX_CONCURRENT_THUMBS : MAX_CONCURRENT_THUMBS;
    while (_thumbsLoading < maxConcurrent && _thumbQueue.length > 0) {
      const node = _thumbQueue.shift();
      _thumbsLoading++;
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        node._img = img;
        _thumbsLoading--;
        _processThumbQueue();
        _scheduleRender();
      };
      img.onerror = () => {
        _thumbsLoading--;
        _processThumbQueue();
      };
      img.src = node.thumb_url;
    }
  }

  // ─── Interaction ─────────────────────────────────────────────────────────

  function _updateQuadtree() {
    if (typeof d3 === "undefined") return;
    _quadtree = d3
      .quadtree()
      .x((d) => d.x)
      .y((d) => d.y)
      .addAll(_nodes);
  }

  function _onClick(e) {
    if (!_quadtree) return;
    const rect = _canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - _transform.x) / _transform.k;
    const my = (e.clientY - rect.top - _transform.y) / _transform.k;
    const hit = _quadtree.find(mx, my, _nodeSize * 1.5);
    if (hit && _clickCallback) {
      _clickCallback(hit.id, hit);
    }
  }

  // ─── Control panel ───────────────────────────────────────────────────────

  function _fmtNum(value, digits) {
    return Number(value).toFixed(digits).replace(/\.?0+$/, "");
  }

  function _clamp(value, min, max, fallback) {
    const n = Number(value);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, n));
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

  function _buildControls() {
    if (!_controlsEl) return;
    _controlsEl.innerHTML = "";

    const searchRow = document.createElement("div");
    searchRow.className = "attractor-search-row";
    searchRow.innerHTML = `
      <input class="attractor-search" type="search" placeholder="Type text to filter" aria-label="Filter map text">
      <button class="attractor-panel-toggle" type="button" aria-expanded="false">Categories</button>
      <span class="attractor-help-text">Text filters the map. Categories can filter the map or group matching items.</span>
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

    // Sliders and pills live in the collapsible drawer.
    const slidersRow = document.createElement("div");
    slidersRow.className = "attractor-sliders";

    slidersRow.innerHTML = `
      <label class="slider-with-value">
        <span class="slider-label">Strength</span>
        <span class="slider-head"><input type="range" id="_attrStr" min="0.05" max="0.8" step="0.05" value="${_attractStrength}"><input class="slider-value slider-number" id="_attrStrVal" type="number" inputmode="decimal" min="0.05" max="0.8" step="0.05" value="${_fmtNum(_attractStrength, 2)}" aria-label="Strength value"></span>
      </label>
      <label class="slider-with-value">
        <span class="slider-label">Spread</span>
        <span class="slider-head"><input type="range" id="_attrRep" min="1" max="20" step="1" value="${Math.abs(_repulsion)}"><input class="slider-value slider-number" id="_attrRepVal" type="number" inputmode="numeric" min="1" max="20" step="1" value="${_fmtNum(Math.abs(_repulsion), 0)}" aria-label="Spread value"></span>
      </label>
      <label class="slider-with-value">
        <span class="slider-label">Size</span>
        <span class="slider-head"><input type="range" id="_attrSize" min="6" max="40" step="1" value="${_nodeSize}"><input class="slider-value slider-number" id="_attrSizeVal" type="number" inputmode="numeric" min="6" max="40" step="1" value="${_fmtNum(_nodeSize, 0)}" aria-label="Size value"></span>
      </label>
      <span class="filter-group-switch" role="group" aria-label="Category mode">
        <button type="button" id="_attrModeFilter" class="mode-option ${_focusedMode ? "active" : ""}" aria-pressed="${_focusedMode ? "true" : "false"}">Filter</button>
        <button type="button" id="_attrModeGroup" class="mode-option ${!_focusedMode ? "active" : ""}" aria-pressed="${!_focusedMode ? "true" : "false"}">Group</button>
      </span>
      <label class="physics-toggle">Live <input type="checkbox" id="_attrLive" ${_liveMode ? "checked" : ""}></label>
      <label class="physics-toggle">Thumbs <input type="checkbox" id="_attrThumbs" ${_showThumbs ? "checked" : ""}></label>
    `;
    _controlsEl.appendChild(slidersRow);

    // Chip groups in hover-reveal section
    const chipsSection = document.createElement("div");
    chipsSection.className = "attractor-chips-section";
    const toolbar = document.createElement("div");
    toolbar.className = "attractor-categories-toolbar";
    toolbar.innerHTML = `
      <span>Categories ${_focusedMode ? "filter matching items" : "group matching items"}</span>
      <button type="button" class="attractor-clear-categories">Clear categories</button>
    `;
    chipsSection.appendChild(toolbar);

    // Source chips
    {
      const srcOrder = ["pinterest", "facebook", "houzz", "scan"];
      const srcLabels = { pinterest: "Pinterest", facebook: "Facebook", houzz: "Houzz", scan: "Scans" };
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
          const cssColor = SOURCE_COLORS[src] || "#999999";
          const count = srcCounts[src];
          const btn = document.createElement("button");
          btn.className = "attractor-chip";
          btn.type = "button";
          btn.dataset.src = src;
          btn.dataset.count = count;
          btn.innerHTML = `<span class="src-dot" style="background:${cssColor}"></span>${srcLabels[src]} <span class="chip-count">${count}</span>`;
          btn.addEventListener("click", () => _toggleAttractor({ source: src, name: srcLabels[src], count }));
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

      // Show top items (most popular)
      const maxChips = catKey === "colors"
        ? 8
        : (catKey === "product_focus" || catKey === "room" ? 12 : 10);
      for (const opt of options.slice(0, maxChips)) {
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
    _syncCategoriesButtonUi();

    // Wire sliders and editable values. Number inputs keep tuning usable on iPad.
    _wireRangeNumberControl({
      rangeId: "_attrStr",
      numberId: "_attrStrVal",
      min: 0.05,
      max: 0.8,
      fallback: _attractStrength,
      digits: 2,
      apply(value) {
        _attractStrength = value;
        if (_activeAttractors.length > 0) _updateAttractorForces();
      },
    });

    _wireRangeNumberControl({
      rangeId: "_attrRep",
      numberId: "_attrRepVal",
      min: 1,
      max: 20,
      fallback: Math.abs(_repulsion),
      digits: 0,
      apply(value) {
        _repulsion = -value;
        if (_simulation) {
          _simulation.force("charge", d3.forceManyBody().strength(_repulsion).distanceMax(250));
          if (_liveMode) {
            _simulation.alpha(0.3).restart();
          } else if (_activeAttractors.length > 0) {
            _settleAndTween(RETICK);
          } else {
            _settleSimulation(RETICK);
            _updateQuadtree();
            _scheduleRender();
          }
        }
      },
    });

    _wireRangeNumberControl({
      rangeId: "_attrSize",
      numberId: "_attrSizeVal",
      min: 6,
      max: 40,
      fallback: _nodeSize,
      digits: 0,
      apply(value) {
        _nodeSize = Math.round(value);
        if (_simulation)
          _simulation.force("collide", d3.forceCollide().radius(_nodeSize / 2 + 1).iterations(1));
        _updateVisibleThumbs();
        if (_liveMode) {
          _simulation.alpha(0.2).restart();
        } else {
          _settleSimulation(80);
          _updateQuadtree();
          _scheduleRender();
        }
      },
    });

    const filterModeBtn = _controlsEl.querySelector("#_attrModeFilter");
    const groupModeBtn = _controlsEl.querySelector("#_attrModeGroup");
    if (filterModeBtn) filterModeBtn.addEventListener("click", () => setFocusedMode(true));
    if (groupModeBtn) groupModeBtn.addEventListener("click", () => setFocusedMode(false));

    // Live toggle
    const liveToggle = _controlsEl.querySelector("#_attrLive");
    if (liveToggle)
      liveToggle.addEventListener("change", (e) => {
        _liveMode = e.target.checked;
        if (_liveMode) {
          // Start live render loop
          _simulation.alpha(0.3).restart();
          _startRenderLoop();
        } else {
          // Stop live loop, settle to final positions
          _simulation.stop();
          _stopRenderLoop();
          _settleSimulation(RETICK);
          _updateQuadtree();
          _scheduleRender();
          _updateVisibleThumbs();
        }
      });

    const thumbsToggle = _controlsEl.querySelector("#_attrThumbs");
    if (thumbsToggle)
      thumbsToggle.addEventListener("change", (e) => {
        _showThumbs = e.target.checked;
        _scheduleRender();
      });

    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        _searchTerm = (e.target.value || "").toLowerCase().trim();
        _emitTextFilterChange(e.target.value || "");
        if (_focusedMode) {
          _rebuildForFocusedMode();
        } else {
          _scheduleRender();
        }
      });
    }
  }

  function _toggleAttractor(opt) {
    const idx = opt.source !== undefined
      ? _activeAttractors.findIndex((a) => a.source === opt.source)
      : _activeAttractors.findIndex((a) => a.dim === opt.dim);
    if (idx >= 0) {
      _activeAttractors.splice(idx, 1);
    } else {
      if (opt.source !== undefined) {
        _activeAttractors.push({ source: opt.source, name: opt.name, count: opt.count, px: 0, py: 0 });
      } else {
        _activeAttractors.push({ dim: opt.dim, name: opt.name, count: opt.count, px: 0, py: 0 });
      }
    }

    // Update chip active states
    const chips = _controlsEl.querySelectorAll(".attractor-chip");
    chips.forEach((chip) => {
      const srcStr = chip.dataset.src;
      const isActive = srcStr
        ? _activeAttractors.some((a) => a.source === srcStr)
        : _activeAttractors.some((a) => a.dim === parseInt(chip.dataset.dim));
      chip.classList.toggle("active", isActive);
    });

    if (_focusedMode) {
      // Rebuild node list to include/exclude based on new attractor set
      _rebuildForFocusedMode();
    } else {
      _updateAttractorForces();
    }
    _updateChipLabels();
    _syncCategoriesButtonUi();
    _emitSelectionChange();
  }

  function _clearAttractors() {
    if (_activeAttractors.length === 0) return;
    _activeAttractors = [];
    _controlsEl?.querySelectorAll(".attractor-chip.active").forEach((chip) => {
      chip.classList.remove("active");
    });
    if (_focusedMode) {
      _rebuildForFocusedMode();
    } else {
      _updateAttractorForces();
    }
    _updateChipLabels();
    _syncCategoriesButtonUi();
    _emitSelectionChange();
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
    const filterBtn = _controlsEl?.querySelector("#_attrModeFilter");
    const groupBtn = _controlsEl?.querySelector("#_attrModeGroup");
    if (filterBtn) {
      filterBtn.classList.toggle("active", _focusedMode);
      filterBtn.setAttribute("aria-pressed", _focusedMode ? "true" : "false");
    }
    if (groupBtn) {
      groupBtn.classList.toggle("active", !_focusedMode);
      groupBtn.setAttribute("aria-pressed", !_focusedMode ? "true" : "false");
    }
    const modeText = _controlsEl?.querySelector(".attractor-categories-toolbar span");
    if (modeText) modeText.textContent = `Categories ${_focusedMode ? "filter matching items" : "group matching items"}`;
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

  // ─── Overlap indicators ──────────────────────────────────────────────────

  /**
   * Compute, for every attractor dimension, how many items are "unique"
   * (not already covered by any currently active attractor).
   * Returns null when no attractors are active.
   */
  function _computeOverlapStats() {
    if (_activeAttractors.length === 0) return null;

    const source = _allNodes.length > 0 ? _allNodes : _nodes;

    // IDs covered by at least one active attractor
    const coveredIds = new Set();
    for (const node of source) {
      for (const att of _activeAttractors) {
        const matches = att.source !== undefined ? node.source === att.source : node.vector[att.dim] > 0;
        if (matches) {
          coveredIds.add(node.id);
          break;
        }
      }
    }

    // Collect every dim index across all attractor option groups
    const stats = new Map(); // dim → {total, unique}
    for (const catKey of Object.keys(_attractorOptions)) {
      for (const opt of _attractorOptions[catKey]) {
        stats.set(opt.dim, { total: 0, unique: 0 });
      }
    }

    // Single pass: accumulate total and unique per dim
    for (const node of source) {
      for (const [dim, s] of stats) {
        if (node.vector[dim] > 0) {
          s.total++;
          if (!coveredIds.has(node.id)) {
            s.unique++;
          }
        }
      }
    }
    return stats;
  }

  /** Update every chip's count label with overlap info. */
  function _updateChipLabels() {
    if (!_controlsEl) return;
    const stats = _computeOverlapStats();
    const chips = _controlsEl.querySelectorAll(".attractor-chip");

    chips.forEach((chip) => {
      const dim = parseInt(chip.dataset.dim);
      const baseCount = parseInt(chip.dataset.count);
      const countEl = chip.querySelector(".chip-count");
      if (!countEl) return;

      if (!stats) {
        // No active attractors — plain count
        countEl.textContent = baseCount;
        countEl.title = "";
        return;
      }

      const s = stats.get(dim);
      if (!s) { countEl.textContent = baseCount; return; }

      const isActive = _activeAttractors.some((a) => a.dim === dim);
      if (isActive) {
        countEl.textContent = s.total;
        countEl.title = `${s.total} items match this attractor`;
      } else {
        countEl.textContent = `${s.unique}/${s.total}`;
        countEl.title = `${s.unique} new items not covered by active attractors (${s.total} total)`;
      }
    });
  }

  // ─── Focused mode ──────────────────────────────────────────────────────

  function _rebuildForFocusedMode() {
    if (_focusedMode) {
      _nodes = _allNodes.filter((n) => {
        if (_filterIds && _filterIds.size > 0 && !_filterIds.has(n.id)) return false;
        if (!_nodeMatchesText(n)) return false;
        if (_activeAttractors.length === 0) return true;
        return _activeAttractors.some((att) =>
          att.source !== undefined ? n.source === att.source : n.vector[att.dim] > 0
        );
      });
    } else {
      _nodes = _allNodes.slice();
    }
    _initSimulation();
    if (_activeAttractors.length > 0) {
      _updateAttractorForces();
    } else {
      _settleSimulation(SETTLE_TICKS);
    }
    _updateQuadtree();
    _scheduleRender();
    _updateVisibleThumbs();
    _smoothCenterVisibleCluster();
  }

  // ─── Public API (mirrors Explorer.js) ────────────────────────────────────

  function setFilter(nodeIds) {
    _filterIds = nodeIds ? new Set(nodeIds) : null;
    if (_focusedMode) {
      _rebuildForFocusedMode();
    } else {
      _scheduleRender();
    }
  }

  function highlight(nodeIds) {
    _highlightedIds = nodeIds ? new Set(nodeIds) : null;
    _scheduleRender();
  }

  function onSelect(callback) {
    _selectCallback = callback;
  }

  function onClickNode(callback) {
    _clickCallback = callback;
  }

  function pause() {
    _paused = true;
    if (_simulation) _simulation.stop();
    _stopRenderLoop();
    _tweening = false;
  }

  function resume() {
    _paused = false;
    if (_liveMode && _simulation) {
      _simulation.alpha(0.1).restart();
      _startRenderLoop();
    } else {
      // Pre-computed mode: just re-render current state
      _scheduleRender();
      _updateVisibleThumbs();
    }
  }

  function destroy() {
    pause();
    if (_controlsEl) _controlsEl.remove();
    const toolbarMount = document.getElementById("explorerToolbarMount");
    if (toolbarMount && toolbarMount.children.length === 0) toolbarMount.hidden = true;
    if (_container) {
      _container.innerHTML = "";
    }
    _controlsEl = null;
    _nodes = [];
    _allNodes = [];
    _simulation = null;
    _quadtree = null;
    _activeAttractors = [];
  }

  // ─── Export ──────────────────────────────────────────────────────────────

  function setSearch(term) {
    _searchTerm = (term || "").toLowerCase().trim();
    const input = _controlsEl?.querySelector(".attractor-search");
    if (input && input.value !== (term || "")) input.value = term || "";
    if (_focusedMode) {
      _rebuildForFocusedMode();
    } else {
      _scheduleRender();
    }
  }

  function setFocusedMode(on) {
    _focusedMode = !!on;
    _syncModeSwitchUi();
    _rebuildForFocusedMode();
  }

  function getVisibleNodeIds() {
    return (_nodes || []).map((node) => node.id).filter(Boolean);
  }

  window.AttractorExplorer = {
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
