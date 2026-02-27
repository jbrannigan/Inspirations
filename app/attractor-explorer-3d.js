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
 * Default mode: pre-computed physics. Run N ticks synchronously → render once.
 * "Live" checkbox enables continuous render loop with per-frame force ticks.
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
      init() {}, loadData() {}, setFilter() {}, setSearch() {},
      setFocusedMode() {}, highlight() {}, onSelect() {}, onClickNode() {},
      pause() {}, resume() {}, destroy() {},
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

  let _meshes = [];              // [{id, mesh, node}]
  let _poleMarkers = [];         // [{mesh, labelEl, att}]
  let _clickCallback = null;
  let _selectCallback = null;
  let _highlightedIds = null;
  let _filterIds = null;
  let _searchTerm = "";
  let _focusedMode = true;

  // Settings
  let _attractStrength = 0.35;
  let _repulsion = 6;
  let _nodeSize = 8;             // world units (scene spans ±350)
  let _liveMode = false;

  // Tween
  let _tweenStart = 0;
  const _tweenDuration = 600;
  let _tweening = false;

  // Physics
  const SETTLE_TICKS = 200;
  const RETICK = 150;

  // Texture loading
  const _texCache = {};
  let _texLoader = null;
  let _texLoading = 0;
  const _texQueue = [];
  const MAX_CONCURRENT_TEX = 12;

  // Source colors
  const SOURCE_COLORS = {
    pinterest: 0xc8553d,
    facebook: 0x4267b2,
    houzz: 0x4dbc63,
    scan: 0x8b6914,
  };

  // ─── Helpers ──────────────────────────────────────────────────────────────

  function _bgColor() {
    const style = getComputedStyle(document.documentElement);
    return style.getPropertyValue("--bg").trim() || "#faf8f5";
  }

  // ─── Init ─────────────────────────────────────────────────────────────────

  function init(containerId) {
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
    _container.appendChild(_controlsEl);

    // Texture loader
    _texLoader = new THREE.TextureLoader();

    // Click detection
    _renderer.domElement.addEventListener("click", _onClick);

    // Resize
    const ro = new ResizeObserver(() => {
      const nw = _container.clientWidth;
      const nh = _container.clientHeight;
      _camera.aspect = nw / nh;
      _camera.updateProjectionMatrix();
      _renderer.setSize(nw, nh);
    });
    ro.observe(_container);
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

  function loadData(data) {
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
      const x = (a.x || 0) + jit();
      const y = (a.y || 0) + jit();
      const z = (a.z || 0) + jit();
      return {
        id: a.id,
        vector: vec,
        x, y, z,
        _restX: a.x || 0,
        _restY: a.y || 0,
        _restZ: a.z || 0,
        vx: 0, vy: 0, vz: 0,
        thumb_url: a.t,
        title: a.title || "",
        source: a.src || "",
        _tex: null,
        _texQueued: false,
      };
    });

    _allNodes = _nodes.slice();

    // Create meshes
    _nodes.forEach((node) => {
      const mesh = _createNodeMesh(node);
      _meshes.push({ id: node.id, mesh, node });
    });

    // Build controls
    _buildControls();

    // Collision resolve to separate coincident/overlapping nodes
    _settleSimulation(SETTLE_TICKS);
    _syncMeshPositions();

    console.log(`[3D] Loaded ${_nodes.length} nodes, camera Z=${_camera.position.z.toFixed(0)}, nodeSize=${_nodeSize}`);

    // Start render loop (Three.js always needs one for OrbitControls)
    _startRenderLoop();

    // Queue textures for visible nodes
    _queueVisibleTextures();
  }

  function _createNodeMesh(node) {
    const geo = new THREE.PlaneGeometry(1, 1);
    const color = SOURCE_COLORS[node.source] || 0x999999;
    const mat = new THREE.MeshBasicMaterial({
      color: color,             // always source color as placeholder (visible on light bg)
      side: THREE.DoubleSide,
      transparent: true,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(node.x, node.y, node.z);
    mesh.scale.setScalar(_nodeSize);
    mesh.userData = { nodeId: node.id, node };
    _scene.add(mesh);
    return mesh;
  }

  function _syncMeshPositions() {
    for (const { mesh, node } of _meshes) {
      mesh.position.set(node.x, node.y, node.z);
    }
  }

  function _clearScene() {
    for (const { mesh } of _meshes) {
      mesh.geometry.dispose();
      mesh.material.dispose();
      if (mesh.material.map) mesh.material.map.dispose();
      _scene && _scene.remove(mesh);
    }
    _meshes = [];

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
    Object.values(_texCache).forEach((t) => t.dispose());
    for (const key in _texCache) delete _texCache[key];
    _texQueue.length = 0;
    _texLoading = 0;
  }

  // ─── 3D Force simulation ──────────────────────────────────────────────────

  function _forceTick() {
    const n = _nodes.length;
    if (n === 0) return;

    for (const node of _nodes) {
      let fx = 0, fy = 0, fz = 0;

      // Attractor pull
      for (const att of _activeAttractors) {
        const w = node.vector[att.dim] * _attractStrength;
        if (w > 0) {
          fx += (att.px - node.x) * w * 0.02;
          fy += (att.py - node.y) * w * 0.02;
          fz += (att.pz - node.z) * w * 0.02;
        }
      }

      // Return-to-rest force
      const restStr = _activeAttractors.length > 0 ? 0.003 : 0.05;
      fx += (node._restX - node.x) * restStr;
      fy += (node._restY - node.y) * restStr;
      fz += (node._restZ - node.z) * restStr;

      // Apply velocity with damping
      node.vx = node.vx * 0.65 + fx;
      node.vy = node.vy * 0.65 + fy;
      node.vz = node.vz * 0.65 + fz;

      node.x += node.vx;
      node.y += node.vy;
      node.z += node.vz;
    }

    // Simple collision avoidance via grid hash
    _collisionPass();
  }

  function _collisionPass() {
    const scale = _repulsion / 6;  // 6 is baseline
    const cellSize = _nodeSize * 2.5 * scale;
    const grid = new Map();

    for (const node of _nodes) {
      const cx = Math.floor(node.x / cellSize);
      const cy = Math.floor(node.y / cellSize);
      const cz = Math.floor(node.z / cellSize);
      const key = `${cx},${cy},${cz}`;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(node);
    }

    const minDist = _nodeSize * 1.1 * scale;
    const minDist2 = minDist * minDist;

    for (const [key, cell] of grid) {
      const [cx, cy, cz] = key.split(",").map(Number);
      // Check this cell and neighbors
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          for (let dz = -1; dz <= 1; dz++) {
            const nKey = `${cx + dx},${cy + dy},${cz + dz}`;
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
                  const overlap = (minDist - d) * 0.25;
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
    for (let i = 0; i < ticks; i++) {
      _forceTick();
    }
  }

  function _settleAndTween(ticks) {
    // Stash current positions
    for (const node of _nodes) {
      node._tweenFromX = node.x;
      node._tweenFromY = node.y;
      node._tweenFromZ = node.z;
    }

    // Settle
    _settleSimulation(ticks);

    // Stash settled as targets, restore old
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

    if (_liveMode) {
      // Live mode: render loop handles ticking
    } else {
      _settleAndTween(RETICK);
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

      // Live mode: tick forces each frame
      if (_liveMode) {
        _forceTick();
        _syncMeshPositions();
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
        _syncMeshPositions();

        if (t >= 1) {
          _tweening = false;
          _queueVisibleTextures();
        }
      }

      // Billboard: face camera
      for (const { mesh } of _meshes) {
        if (mesh.visible) {
          mesh.quaternion.copy(_camera.quaternion);
        }
      }

      // Update node visibility / opacity
      _updateNodeVisuals();

      // Update pole label positions
      _updatePoleLabelsScreen();

      _controls.update();
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

  function _updateNodeVisuals() {
    for (const { id, mesh, node } of _meshes) {
      let opacity = 1.0;
      if (_filterIds && !_filterIds.has(id)) opacity = 0.05;
      if (_highlightedIds && !_highlightedIds.has(id)) opacity = 0.06;
      if (_searchTerm && !node.title.toLowerCase().includes(_searchTerm))
        opacity = 0.08;

      mesh.material.opacity = opacity;
      mesh.visible = opacity > 0.02;
    }
  }

  // ─── Texture loading ──────────────────────────────────────────────────────

  function _queueVisibleTextures() {
    // Queue all nodes that have thumb_url and no texture yet
    for (const node of _nodes) {
      if (node.thumb_url && !node._tex && !node._texQueued) {
        node._texQueued = true;
        _texQueue.push(node);
      }
    }
    _processTexQueue();
  }

  function _processTexQueue() {
    while (_texLoading < MAX_CONCURRENT_TEX && _texQueue.length > 0) {
      const node = _texQueue.shift();
      _texLoading++;

      if (_texCache[node.thumb_url]) {
        node._tex = _texCache[node.thumb_url];
        _applyTexToMesh(node);
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
          _applyTexToMesh(node);
          _texLoading--;
          _processTexQueue();
        },
        undefined,
        () => {
          _texLoading--;
          _processTexQueue();
        }
      );
    }
  }

  function _applyTexToMesh(node) {
    const entry = _meshes.find((m) => m.id === node.id);
    if (entry) {
      entry.mesh.material.color.set(0xffffff); // reset to white so texture is not tinted
      entry.mesh.material.map = node._tex;
      entry.mesh.material.needsUpdate = true;
    }
  }

  // ─── Click detection ──────────────────────────────────────────────────────

  function _onClick(e) {
    if (!_scene || !_camera) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, _camera);
    const visibleMeshes = _meshes.filter((m) => m.mesh.visible).map((m) => m.mesh);
    const hits = raycaster.intersectObjects(visibleMeshes);
    if (hits[0]) {
      const { nodeId, node } = hits[0].object.userData;
      if (_clickCallback) _clickCallback(nodeId, node);
    }
  }

  // ─── Control panel ────────────────────────────────────────────────────────

  let _on3DToggleCb = null;

  function _buildControls() {
    if (!_controlsEl) return;
    _controlsEl.innerHTML = "";

    // Sliders row FIRST (always visible)
    const slidersRow = document.createElement("div");
    slidersRow.className = "attractor-sliders";

    slidersRow.innerHTML = `
      <label>Strength <input type="range" id="_attr3dStr" min="0.05" max="0.8" step="0.05" value="${_attractStrength}"></label>
      <label>Spread <input type="range" id="_attr3dSpread" min="1" max="20" step="1" value="${_repulsion}"></label>
      <label>Size <input type="range" id="_attr3dSize" min="2" max="30" step="1" value="${_nodeSize}"></label>
      <label class="physics-toggle">3D <input type="checkbox" id="_attr3dToggle" checked></label>
      <label class="physics-toggle">Focus <input type="checkbox" id="_attr3dFocus" ${_focusedMode ? "checked" : ""}></label>
      <label class="physics-toggle">Live <input type="checkbox" id="_attr3dLive" ${_liveMode ? "checked" : ""}></label>
    `;
    _controlsEl.appendChild(slidersRow);

    // Chip groups in hover-reveal section
    const chipsSection = document.createElement("div");
    chipsSection.className = "attractor-chips-section";

    const chipOrder = ["rooms", "styles", "materials", "colors"];
    for (const catKey of chipOrder) {
      const options = _attractorOptions[catKey];
      if (!options || options.length === 0) continue;

      const group = document.createElement("div");
      group.className = "attractor-group";

      const label = document.createElement("span");
      label.className = "attractor-group-label";
      label.textContent = (_categories[catKey] || {}).label || catKey;
      group.appendChild(label);

      const chips = document.createElement("div");
      chips.className = "attractor-chips";

      const maxChips = catKey === "colors" ? 8 : 10;
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

    // Wire sliders
    const strSlider = _controlsEl.querySelector("#_attr3dStr");
    if (strSlider)
      strSlider.addEventListener("input", (e) => {
        _attractStrength = parseFloat(e.target.value);
        if (_activeAttractors.length > 0) {
          if (_liveMode) { /* forces update each frame */ }
          else _settleAndTween(RETICK);
        }
      });

    const spreadSlider = _controlsEl.querySelector("#_attr3dSpread");
    if (spreadSlider)
      spreadSlider.addEventListener("input", (e) => {
        _repulsion = parseFloat(e.target.value);
        if (_activeAttractors.length > 0) {
          if (_liveMode) { /* forces update each frame */ }
          else _settleAndTween(RETICK);
        } else {
          _settleSimulation(RETICK);
          _syncMeshPositions();
        }
      });

    const sizeSlider = _controlsEl.querySelector("#_attr3dSize");
    if (sizeSlider)
      sizeSlider.addEventListener("input", (e) => {
        _nodeSize = parseFloat(e.target.value);
        for (const { mesh } of _meshes) {
          mesh.scale.setScalar(_nodeSize);
        }
      });

    const focusToggle = _controlsEl.querySelector("#_attr3dFocus");
    if (focusToggle)
      focusToggle.addEventListener("change", (e) => {
        _focusedMode = e.target.checked;
        _rebuildForFocusedMode();
      });

    const liveToggle = _controlsEl.querySelector("#_attr3dLive");
    if (liveToggle)
      liveToggle.addEventListener("change", (e) => {
        _liveMode = e.target.checked;
        if (!_liveMode) {
          _settleSimulation(RETICK);
          _syncMeshPositions();
          _queueVisibleTextures();
        }
      });

    // 3D toggle — fires callback to switch back to 2D
    const toggle3D = _controlsEl.querySelector("#_attr3dToggle");
    if (toggle3D)
      toggle3D.addEventListener("change", (e) => {
        if (_on3DToggleCb) _on3DToggleCb(e.target.checked);
      });
  }

  function _toggleAttractor(opt) {
    const idx = _activeAttractors.findIndex((a) => a.dim === opt.dim);
    if (idx >= 0) {
      _activeAttractors.splice(idx, 1);
    } else {
      _activeAttractors.push({ dim: opt.dim, name: opt.name, count: opt.count, px: 0, py: 0, pz: 0 });
    }

    // Update chip active states
    const chips = _controlsEl.querySelectorAll(".attractor-chip");
    chips.forEach((chip) => {
      const dimStr = chip.dataset.dim;
      const isActive = _activeAttractors.some((a) => a.dim === parseInt(dimStr));
      chip.classList.toggle("active", isActive);
    });

    if (_focusedMode) {
      _rebuildForFocusedMode();
    } else {
      _updateAttractorForces();
    }
    _updateChipLabels();
  }

  // ─── Overlap indicators (same logic as 2D) ───────────────────────────────

  function _computeOverlapStats() {
    if (_activeAttractors.length === 0) return null;
    const source = _allNodes.length > 0 ? _allNodes : _nodes;

    const coveredIds = new Set();
    for (const node of source) {
      for (const att of _activeAttractors) {
        if (node.vector[att.dim] > 0) {
          coveredIds.add(node.id);
          break;
        }
      }
    }

    const stats = new Map();
    for (const catKey of Object.keys(_attractorOptions)) {
      for (const opt of _attractorOptions[catKey]) {
        stats.set(opt.dim, { total: 0, unique: 0 });
      }
    }

    for (const node of source) {
      for (const [dim, s] of stats) {
        if (node.vector[dim] > 0) {
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
    const chips = _controlsEl.querySelectorAll(".attractor-chip");

    chips.forEach((chip) => {
      const dim = parseInt(chip.dataset.dim);
      const baseCount = parseInt(chip.dataset.count);
      const countEl = chip.querySelector(".chip-count");
      if (!countEl) return;

      if (!stats) {
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

  // ─── Focused mode ─────────────────────────────────────────────────────────

  function _rebuildForFocusedMode() {
    // Remove old meshes from scene.
    // Do NOT dispose texture maps — they are shared via _texCache and
    // referenced by node._tex for instant re-application.
    for (const { mesh } of _meshes) {
      mesh.material.map = null;          // detach without disposing
      mesh.geometry.dispose();
      mesh.material.dispose();
      _scene.remove(mesh);
    }
    _meshes = [];
    _texQueue = [];                      // clear pending queue
    _texLoading = 0;

    // Determine visible node set
    if (_focusedMode) {
      if (_filterIds && _filterIds.size > 0) {
        _nodes = _allNodes.filter((n) => _filterIds.has(n.id));
      } else if (_activeAttractors.length > 0) {
        _nodes = _allNodes.filter((n) =>
          _activeAttractors.some((att) => n.vector[att.dim] > 0)
        );
      } else {
        _nodes = _allNodes.slice();
      }
    } else {
      _nodes = _allNodes.slice();
    }

    // Recreate meshes — re-apply cached textures immediately
    _nodes.forEach((node) => {
      const mesh = _createNodeMesh(node);
      _meshes.push({ id: node.id, mesh, node });
      if (node._tex) {
        mesh.material.color.set(0xffffff);
        mesh.material.map = node._tex;
        mesh.material.needsUpdate = true;
      }
    });

    // Reset velocities
    for (const node of _nodes) {
      node.vx = 0; node.vy = 0; node.vz = 0;
    }

    if (_activeAttractors.length > 0) {
      _updateAttractorForces();
    } else {
      _settleSimulation(SETTLE_TICKS);
      _syncMeshPositions();
    }
    // Queue texture loads for any nodes that still need them
    _queueVisibleTextures();
  }

  // ─── Public API ───────────────────────────────────────────────────────────

  function setFilter(nodeIds) {
    _filterIds = nodeIds ? new Set(nodeIds) : null;
    if (_focusedMode) {
      _rebuildForFocusedMode();
    }
  }

  function setSearch(term) {
    _searchTerm = (term || "").toLowerCase().trim();
  }

  function setFocusedMode(on) {
    _focusedMode = !!on;
    const toggle = _controlsEl?.querySelector("#_attr3dFocus");
    if (toggle) toggle.checked = _focusedMode;
    _rebuildForFocusedMode();
  }

  function highlight(nodeIds) {
    _highlightedIds = nodeIds ? new Set(nodeIds) : null;
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
    _stopRenderLoop();
    _clearScene();
    if (_renderer) {
      _renderer.dispose();
      _renderer.domElement.remove();
      _renderer = null;
    }
    if (_controlsEl) _controlsEl.remove();
    if (_labelsEl) _labelsEl.remove();
    _controlsEl = null;
    _labelsEl = null;
  }

  // ─── Export ───────────────────────────────────────────────────────────────

  window.AttractorExplorer3D = {
    init,
    loadData,
    setFilter,
    setSearch,
    setFocusedMode,
    highlight,
    onSelect,
    onClickNode,
    on3DToggle(cb) { _on3DToggleCb = cb; },
    pause,
    resume,
    destroy,
  };
})();
