/**
 * Explorer — 3D Semantic Image Explorer
 * Self-contained module. Sets window.Explorer.
 * Depends on Three.js being available via importmap (see index.html).
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
    console.error("[Explorer] Failed to import Three.js:", e);
    window.Explorer = { init() {}, loadData() {}, setFilter() {}, highlight() {}, onSelect() {}, resetCamera() {}, destroy() {} };
    return;
  }

  // ─── State ──────────────────────────────────────────────────────────────────
  let _renderer = null;
  let _scene = null;
  let _camera = null;
  let _controls = null;
  let _animFrameId = null;
  let _container = null;
  let _nodes = [];           // raw data from loadData
  let _clusters = [];
  let _meshes = [];          // { id, sprite, data }
  let _clusterDots = [];     // { mesh, labelEl }
  let _clusterHalos = [];
  let _spread = 1.5;
  let _showLabels = true;
  let _selectCallback = null;
  let _clickCallback = null;
  let _selectedIds = new Set();
  let _highlightedIds = null; // null = no highlight active
  let _filterIds = null;      // null = show all
  let _paused = false;

  // Lasso state
  let _lassoActive = false;
  let _lassoStart = null;
  let _lassoEl = null;

  // LOD thresholds (distance from camera to node).
  // Data is normalized to ±15 units × spread. Camera z is computed
  // dynamically to fill ~75% of the viewport.
  const LOD_FAR = 120;
  const LOD_MED = 65;
  const LOD_CLOSE = 35;

  // Texture cache
  const _texCache = {};
  const _texLoader = new THREE.TextureLoader();

  // ─── Helpers ─────────────────────────────────────────────────────────────────

  function _bgColor() {
    const style = getComputedStyle(document.documentElement);
    return style.getPropertyValue("--bg").trim() || "#faf8f5";
  }

  function _loadTexture(url) {
    if (_texCache[url]) return _texCache[url];
    const tex = _texLoader.load(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    _texCache[url] = tex;
    return tex;
  }

  function _disposeTexture(url) {
    if (_texCache[url]) {
      _texCache[url].dispose();
      delete _texCache[url];
    }
  }

  function _nodeScreenPos(node, camera, width, height) {
    const v = new THREE.Vector3(node.x * _spread, node.y * _spread, node.z * _spread);
    v.project(camera);
    return {
      sx: (v.x * 0.5 + 0.5) * width,
      sy: (-v.y * 0.5 + 0.5) * height,
    };
  }

  function _clampedOpacity(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  // ─── Init ─────────────────────────────────────────────────────────────────

  function init(containerId, config = {}) {
    _container = document.getElementById(containerId);
    if (!_container) return;

    const w = _container.clientWidth || window.innerWidth;
    const h = _container.clientHeight || window.innerHeight;

    _renderer = new THREE.WebGLRenderer({ antialias: true });
    _renderer.setPixelRatio(window.devicePixelRatio);
    _renderer.setSize(w, h);
    _renderer.setClearColor(new THREE.Color(_bgColor()), 1);
    _container.appendChild(_renderer.domElement);

    _scene = new THREE.Scene();

    _camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 2000);
    _camera.position.set(0, 0, _computeInitialZ(w, h));

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

    // Lasso overlay
    _lassoEl = document.createElement("div");
    _lassoEl.style.cssText = "position:absolute;border:2px dashed #b8860b;background:rgba(184,134,11,0.08);pointer-events:none;display:none;box-sizing:border-box;";
    _container.style.position = "relative";
    _container.appendChild(_lassoEl);

    // Controls panel
    _buildControlsPanel();

    // Event listeners
    window.addEventListener("resize", _onResize);
    _renderer.domElement.addEventListener("click", _onClick);
    _renderer.domElement.addEventListener("mousemove", _onMouseMove);
    _renderer.domElement.addEventListener("mousedown", _onMouseDown);
    window.addEventListener("mousemove", _onLassoMove);
    window.addEventListener("mouseup", _onLassoEnd);

    _animFrameId = requestAnimationFrame(_renderLoop);
  }

  // ─── Controls panel ──────────────────────────────────────────────────────

  function _buildControlsPanel() {
    const panel = document.createElement("div");
    panel.id = "explorerControlsPanel";
    panel.className = "explorerControlsPanel";
    panel.innerHTML = `
      <button class="explorerPanelToggle" id="explorerPanelToggle" title="Toggle controls">⚙</button>
      <div class="explorerPanelBody" id="explorerPanelBody">
        <label class="explorerControl explorerCheckbox">
          <input type="checkbox" id="explorerLabels" checked>
          <span>Cluster labels</span>
        </label>
        <button id="explorerResetCamera" class="explorerBtn">Reset camera</button>
      </div>
    `;
    _container.appendChild(panel);

    let open = true;
    panel.querySelector("#explorerPanelToggle").addEventListener("click", () => {
      open = !open;
      panel.querySelector("#explorerPanelBody").style.display = open ? "" : "none";
    });
    panel.querySelector("#explorerLabels").addEventListener("change", (e) => {
      _showLabels = e.target.checked;
      _updateLabelVisibility();
    });
    panel.querySelector("#explorerResetCamera").addEventListener("click", resetCamera);
  }

  function _updateLabelVisibility() {
    _clusterDots.forEach(({ labelEl }) => {
      if (labelEl) labelEl.style.display = _showLabels ? "" : "none";
    });
  }

  // ─── Load data ───────────────────────────────────────────────────────────

  function loadData(data) {
    _clearScene();
    _nodes = data.nodes || [];
    _clusters = data.clusters || [];

    // Build cluster lookup
    const clusterMap = {};
    _clusters.forEach((c) => { clusterMap[c.id] = c; });

    // Create image billboards
    _nodes.forEach((node) => {
      const geo = new THREE.PlaneGeometry(1, 1);
      const mat = new THREE.MeshBasicMaterial({
        color: node.thumb_url ? 0xffffff : new THREE.Color(clusterMap[node.cluster_id]?.color || "#888"),
        side: THREE.DoubleSide,
        transparent: true,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(node.x * _spread, node.y * _spread, node.z * _spread);
      mesh.userData = { nodeId: node.id, node };
      _scene.add(mesh);

      // Load texture lazily
      if (node.thumb_url) {
        const tex = _loadTexture(node.thumb_url);
        mat.map = tex;
        mat.needsUpdate = true;
      }

      _meshes.push({ id: node.id, mesh, node });
    });

    // Cluster halos (flat circles on xz plane)
    _clusters.forEach((cluster) => {
      const [cx, cy, cz] = cluster.centroid;
      const radius = Math.sqrt(cluster.count) * 0.6;
      const geo = new THREE.CircleGeometry(radius * _spread, 32);
      const mat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(cluster.color),
        transparent: true,
        opacity: 0.06,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      const halo = new THREE.Mesh(geo, mat);
      halo.rotation.x = -Math.PI / 2;
      halo.position.set(cx * _spread, (cy - radius * 0.3) * _spread, cz * _spread);
      halo.userData = { baseRadius: radius };
      _scene.add(halo);
      _clusterHalos.push(halo);

      // Cluster dot sphere
      const sphereGeo = new THREE.SphereGeometry(0.3, 12, 8);
      const sphereMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(cluster.color) });
      const sphere = new THREE.Mesh(sphereGeo, sphereMat);
      sphere.position.set(cx * _spread, cy * _spread, cz * _spread);
      _scene.add(sphere);

      // Label element (HTML overlay)
      const labelEl = document.createElement("div");
      labelEl.className = "explorerClusterLabel";
      labelEl.textContent = cluster.label;
      labelEl.style.cssText = `
        position:absolute;
        pointer-events:none;
        font-size:11px;
        font-family:DM Sans,sans-serif;
        color:#2c2825;
        background:rgba(250,248,245,0.88);
        border:1px solid rgba(44,40,37,0.12);
        border-radius:4px;
        padding:2px 6px;
        white-space:nowrap;
        transform:translate(-50%,-100%);
        display:${_showLabels ? "" : "none"};
      `;
      _container.appendChild(labelEl);

      _clusterDots.push({ sphere, labelEl, cluster });
    });

    _updateLOD();
  }

  // ─── LOD update ──────────────────────────────────────────────────────────

  function _updateLOD() {
    if (!_camera || !_meshes.length) return;

    const w = _container.clientWidth;
    const h = _container.clientHeight;

    _meshes.forEach(({ mesh, node }) => {
      const dist = _camera.position.distanceTo(mesh.position);

      // Base visibility
      let visible = true;
      if (_filterIds && !_filterIds.has(node.id)) visible = false;

      // Scale based on distance
      let scale;
      if (dist > LOD_FAR) {
        scale = 0.0; // hidden — cluster dots shown instead
      } else if (dist > LOD_MED) {
        const t = (dist - LOD_MED) / (LOD_FAR - LOD_MED);
        scale = (1 - t) * 0.8 + 0.2;
      } else if (dist > LOD_CLOSE) {
        scale = 1.0;
      } else {
        scale = 1.5;
      }

      mesh.visible = visible && scale > 0.05;
      if (mesh.visible) {
        mesh.scale.setScalar(scale);
        // Always face camera
        mesh.quaternion.copy(_camera.quaternion);
      }

      // Highlight / filter opacity
      let opacity = 1.0;
      if (_highlightedIds && !_highlightedIds.has(node.id)) {
        opacity = 0.08;
      }
      if (_filterIds && !_filterIds.has(node.id)) {
        opacity = 0.0;
      }
      mesh.material.opacity = opacity;
    });

    // Cluster dots: show when far, hide when close
    _clusterDots.forEach(({ sphere, labelEl, cluster }) => {
      const [cx, cy, cz] = cluster.centroid;
      const pos = new THREE.Vector3(cx * _spread, cy * _spread, cz * _spread);
      const dist = _camera.position.distanceTo(pos);
      const showDot = dist > LOD_MED;
      sphere.visible = showDot;

      if (labelEl) {
        if (!showDot || !_showLabels) {
          labelEl.style.display = "none";
        } else {
          labelEl.style.display = "";
          const sp = _worldToScreen(pos, w, h);
          if (sp) {
            labelEl.style.left = sp.x + "px";
            labelEl.style.top = sp.y + "px";
          } else {
            labelEl.style.display = "none";
          }
        }
      }
    });
  }

  function _worldToScreen(worldPos, w, h) {
    const v = worldPos.clone().project(_camera);
    if (v.z > 1) return null; // behind camera
    return {
      x: (v.x * 0.5 + 0.5) * w,
      y: (-v.y * 0.5 + 0.5) * h,
    };
  }

  function _repositionNodes() {
    _meshes.forEach(({ mesh, node }) => {
      mesh.position.set(node.x * _spread, node.y * _spread, node.z * _spread);
    });
    _clusterDots.forEach(({ sphere, cluster }) => {
      const [cx, cy, cz] = cluster.centroid;
      sphere.position.set(cx * _spread, cy * _spread, cz * _spread);
    });
    _clusterHalos.forEach((halo, i) => {
      const cluster = _clusters[i];
      if (!cluster) return;
      const [cx, cy, cz] = cluster.centroid;
      const r = halo.userData.baseRadius;
      halo.position.set(cx * _spread, (cy - r * 0.3) * _spread, cz * _spread);
    });
  }

  // ─── Render loop ─────────────────────────────────────────────────────────

  function _renderLoop() {
    _animFrameId = requestAnimationFrame(_renderLoop);
    if (_paused) return;
    _controls.update();
    _updateLOD();
    _renderer.render(_scene, _camera);
  }

  // ─── Events ──────────────────────────────────────────────────────────────

  function _onResize() {
    if (!_container || !_renderer) return;
    const w = _container.clientWidth;
    const h = _container.clientHeight;
    _camera.aspect = w / h;
    _camera.updateProjectionMatrix();
    _renderer.setSize(w, h);
  }

  // Hover state for raycasting (throttled via rAF — handled in render loop)
  let _hoverMesh = null;

  function _onMouseMove(e) {
    if (!_scene || !_camera) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, _camera);
    const hits = raycaster.intersectObjects(_meshes.map((m) => m.mesh).filter((m) => m.visible));

    if (_hoverMesh && _hoverMesh !== (hits[0]?.object)) {
      _hoverMesh.scale.divideScalar(1.2);
      _hoverMesh = null;
    }
    if (hits[0]) {
      const mesh = hits[0].object;
      if (mesh !== _hoverMesh) {
        mesh.scale.multiplyScalar(1.2);
        _hoverMesh = mesh;
        _renderer.domElement.style.cursor = "pointer";
      }
    } else {
      _renderer.domElement.style.cursor = "";
    }
  }

  function _onClick(e) {
    if (!_scene || !_camera) return;
    // Don't fire click if lasso was active
    if (_lassoActive) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, _camera);
    const hits = raycaster.intersectObjects(_meshes.map((m) => m.mesh).filter((m) => m.visible));
    if (hits[0]) {
      const { nodeId, node } = hits[0].object.userData;
      if (_clickCallback) _clickCallback(nodeId, node);
    }
  }

  function _onMouseDown(e) {
    if (e.shiftKey) {
      // Start lasso
      const rect = _renderer.domElement.getBoundingClientRect();
      _lassoStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      _lassoActive = false; // won't be active until drag starts
      _controls.enabled = false;
    }
  }

  function _onLassoMove(e) {
    if (!_lassoStart) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const dx = cx - _lassoStart.x;
    const dy = cy - _lassoStart.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
      _lassoActive = true;
    }
    if (_lassoActive) {
      const x = Math.min(_lassoStart.x, cx);
      const y = Math.min(_lassoStart.y, cy);
      const w = Math.abs(dx);
      const h = Math.abs(dy);
      _lassoEl.style.display = "block";
      _lassoEl.style.left = x + "px";
      _lassoEl.style.top = y + "px";
      _lassoEl.style.width = w + "px";
      _lassoEl.style.height = h + "px";
    }
  }

  function _onLassoEnd(e) {
    if (!_lassoStart) return;
    _lassoEl.style.display = "none";
    if (_lassoActive) {
      _finishLasso(e);
    }
    _lassoStart = null;
    _lassoActive = false;
    _controls.enabled = true;
  }

  function _finishLasso(e) {
    const rect = _renderer.domElement.getBoundingClientRect();
    const ex = e.clientX - rect.left;
    const ey = e.clientY - rect.top;
    const x1 = Math.min(_lassoStart.x, ex);
    const x2 = Math.max(_lassoStart.x, ex);
    const y1 = Math.min(_lassoStart.y, ey);
    const y2 = Math.max(_lassoStart.y, ey);
    const w = _container.clientWidth;
    const h = _container.clientHeight;

    const selected = [];
    _meshes.forEach(({ id, node }) => {
      const sp = _nodeScreenPos(node, _camera, w, h);
      if (sp.sx >= x1 && sp.sx <= x2 && sp.sy >= y1 && sp.sy <= y2) {
        selected.push(id);
      }
    });

    // Visual: show selected
    _selectedIds = new Set(selected);
    _meshes.forEach(({ id, mesh }) => {
      if (_selectedIds.has(id)) {
        mesh.material.color.set(0xffd700);
      }
    });

    if (_selectCallback) _selectCallback(selected);
  }

  // ─── Public API ──────────────────────────────────────────────────────────

  function setFilter(nodeIds) {
    _filterIds = nodeIds ? new Set(nodeIds) : null;
  }

  function highlight(nodeIds) {
    _highlightedIds = nodeIds ? new Set(nodeIds) : null;
    _meshes.forEach(({ id, mesh }) => {
      if (!_highlightedIds || _highlightedIds.has(id)) {
        mesh.material.opacity = 1.0;
        mesh.material.emissive && mesh.material.emissive.set(0x000000);
      } else {
        mesh.material.opacity = 0.08;
      }
    });
  }

  function onSelect(callback) {
    _selectCallback = callback;
  }

  function onClickNode(callback) {
    _clickCallback = callback;
  }

  function _computeInitialZ(w, h) {
    // Position camera so the scene (±15 units × spread) fills ~75% of the shorter viewport dimension.
    const fovRad = (60 * Math.PI) / 180;
    const fullFrustumFactor = 2 * Math.tan(fovRad / 2); // ≈ 1.155
    const sceneDiameter = 2 * 15 * _spread;
    const aspect = w / h;
    const fill = 1.5;
    if (aspect >= 1) {
      // Landscape: height is limiting dimension
      return sceneDiameter / (fill * fullFrustumFactor);
    } else {
      // Portrait: width is limiting dimension
      return sceneDiameter / (fill * fullFrustumFactor * aspect);
    }
  }

  function resetCamera() {
    if (!_camera || !_controls) return;
    const w = _container.clientWidth || window.innerWidth;
    const h = _container.clientHeight || window.innerHeight;
    _camera.position.set(0, 0, _computeInitialZ(w, h));
    _controls.target.set(0, 0, 0);
    _controls.update();
  }

  function pause() {
    _paused = true;
  }

  function resume() {
    _paused = false;
  }

  function destroy() {
    if (_animFrameId) cancelAnimationFrame(_animFrameId);
    window.removeEventListener("resize", _onResize);
    window.removeEventListener("mousemove", _onLassoMove);
    window.removeEventListener("mouseup", _onLassoEnd);
    _clearScene();
    if (_renderer) {
      _renderer.dispose();
      _renderer.domElement.remove();
      _renderer = null;
    }
    Object.values(_texCache).forEach((t) => t.dispose());
    const panel = document.getElementById("explorerControlsPanel");
    if (panel) panel.remove();
    if (_lassoEl) _lassoEl.remove();
  }

  function _clearScene() {
    _meshes.forEach(({ mesh }) => {
      mesh.geometry.dispose();
      mesh.material.dispose();
      _scene && _scene.remove(mesh);
    });
    _meshes = [];

    _clusterDots.forEach(({ sphere, labelEl }) => {
      sphere.geometry.dispose();
      sphere.material.dispose();
      _scene && _scene.remove(sphere);
      if (labelEl) labelEl.remove();
    });
    _clusterDots = [];

    _clusterHalos.forEach((halo) => {
      halo.geometry.dispose();
      halo.material.dispose();
      _scene && _scene.remove(halo);
    });
    _clusterHalos = [];
  }

  // ─── Expose ───────────────────────────────────────────────────────────────
  function setSpread(val) {
    _spread = parseFloat(val);
    _repositionNodes();
  }

  window.Explorer = { init, loadData, setFilter, highlight, onSelect, onClickNode, resetCamera, setSpread, pause, resume, destroy };
})();
