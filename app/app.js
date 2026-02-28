// ─── State ─────────────────────────────────────────────────────────────────────
const state = {
  // Navigation
  view: "browse",               // "browse" | "review"
  currentBoard: null,           // board filter (null = all)
  currentSource: null,          // source filter (null = all)
  currentCollection: null,      // collection ID filter
  currentCollectionIds: [],     // recursive collection scope
  currentCollectionLabel: "",   // display label for collection scope
  currentCatalogFile: null,     // catalog dimension file (e.g. "room/bathroom.md")
  currentCatalogFiles: [],      // recursive catalog scope
  currentCatalogLabel: "",      // display label for catalog scope
  currentTreeNodeId: null,      // active sidebar tree node ID
  triageFilter: "",             // "" | "pending" | "keeper" | "hidden" | "needs-comment"

  // Assets
  assets: [],
  hasMore: false,
  loadingAssets: false,
  offset: 0,
  q: "",
  semanticMode: false,
  assetsRequestSeq: 0,
  chatPrompt: "",                // last Ask-Dave prompt that produced results
  chatItemIds: null,             // array of IDs from a chat show_items action

  // Review mode
  reviewItems: [],
  reviewIndex: 0,
  reviewHistory: [],
  reviewSkipped: 0,
  reviewKept: 0,
  reviewHidden: 0,

  // Collections + facets + catalog
  collections: [],
  facets: { sources: [], boards: [] },
  catalogTree: [],

  // Modal + annotations
  modalAsset: null,
  annotations: [],
  activeAnnotationId: null,
  dragging: null,
  noteTimers: {},
  modalScanPages: null,
  modalScanPageIndex: 0,

  // Imports
  scanImportBusy: false,
  photoImportBusy: false,
  scanImportFile: null,
  photoImportFile: null,

  // Canvas review mode
  canvasReview: false,          // true when canvas review overlay is active
  canvasSelected: new Set(),    // set of selected asset IDs

  // Actor / collaboration
  actor: null,                  // { id, name, role, token } or null
  hiddenTree: null,             // hidden items tree for sidebar (owners only)
  expandedTreeNodes: new Set(), // track which tree nodes are expanded by user
  openQuestions: [],             // open question annotations (owners only)
  questionPollTimer: null,
};

const ASSETS_PAGE_SIZE = 240;
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const escapeHtml = Shared.escapeHtml;
const api = Shared.api;
const formatApiError = Shared.formatApiError;

const IMAGE_SUFFIX_RE = /\.(jpg|jpeg|png|webp|gif|bmp|svg)(\?.*)?$/i;
const PDF_FILE_EXT_RE = /\.pdf$/i;
const IMAGE_FILE_EXT_RE = /\.(jpg|jpeg|png|webp|gif|bmp|heic|heif|tif|tiff)$/i;

async function apiUpload(path, formData) {
  const res = await fetch(path, { method: "POST", body: formData });
  if (!res.ok) { const t = await res.text(); throw new Error(t || res.statusText); }
  return res.json();
}

// ─── Utilities ─────────────────────────────────────────────────────────────────

function semanticQueryFromInput(value) {
  const text = `${value || ""}`.trim();
  if (!text) return "";
  for (const p of ["sem:", "similar:"]) {
    if (text.toLowerCase().startsWith(p)) return text.slice(p.length).trim();
  }
  return "";
}

function previewForAsset(a) {
  if (a.thumb_path) return `/media/${a.id}?kind=thumb`;
  if (a.stored_path) return `/media/${a.id}?kind=original`;
  if (a.image_url && IMAGE_SUFFIX_RE.test(a.image_url)) return a.image_url;
  return "";
}

function displayTitle(a) {
  const title = (a.title || "").trim();
  const ai = (a.ai_summary || "").trim();
  const alt = (a.seo_alt_text || "").trim().replace(/^This may contain:\s*/i, "");
  // Junk titles: bare domains, parking pages, etc.
  const isJunk = title && /^(https?:\/\/|www\.)|\.(com|org|net|co)\b/i.test(title)
    && title.length < 40;
  const bestTitle = (!title || isJunk) ? (ai || alt || title) : title;
  return bestTitle
    || (a.board || "").trim()
    || (a.creator_name ? `via ${a.creator_name}` : "")
    || "(untitled)";
}

function sourceHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function isPdfFile(file) {
  if (!file) return false;
  return PDF_FILE_EXT_RE.test(file.name || "") || (file.type || "").toLowerCase() === "application/pdf";
}

function isImageFile(file) {
  if (!file) return false;
  return (file.type || "").startsWith("image/") || IMAGE_FILE_EXT_RE.test(file.name || "");
}

function setSingleFileSelection(input, file, stateKey) {
  state[stateKey] = file || null;
  if (!input) return;
  if (!file) { input.value = ""; return; }
  try { const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files; } catch {}
}

function wireSingleFileDropZone(options) {
  const { zone, input } = options;
  if (!zone || !input) return;
  const prevent = (e) => { e.preventDefault(); e.stopPropagation(); };
  const busy = () => typeof options.isBusy === "function" ? !!options.isBusy() : false;
  ["dragenter", "dragover"].forEach((evt) => zone.addEventListener(evt, (e) => { prevent(e); if (!busy()) zone.classList.add("dragActive"); }));
  ["dragleave", "dragend"].forEach((evt) => zone.addEventListener(evt, (e) => { prevent(e); zone.classList.remove("dragActive"); }));
  zone.addEventListener("drop", (e) => {
    prevent(e); zone.classList.remove("dragActive");
    if (busy()) return;
    const file = e.dataTransfer?.files?.[0] || null;
    if (!file) return;
    if (!options.accept(file)) { if (options.invalidMessage) Shared.showToast(options.invalidMessage, { type: "error" }); return; }
    setSingleFileSelection(input, file, options.stateKey);
    if (typeof options.onSelected === "function") options.onSelected(file);
  });
}

function _uniqNonEmpty(values) {
  const out = [];
  const seen = new Set();
  for (const raw of (values || [])) {
    const v = `${raw || ""}`.trim();
    if (!v || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

function getCatalogFilterFiles() {
  return _uniqNonEmpty([...(state.currentCatalogFiles || []), state.currentCatalogFile || ""]);
}

function hasCatalogFilter() {
  return getCatalogFilterFiles().length > 0;
}

function clearCatalogFilter() {
  state.currentCatalogFile = null;
  state.currentCatalogFiles = [];
  state.currentCatalogLabel = "";
}

function setCatalogFilter(files, { label = "", nodeId = null } = {}) {
  const uniq = _uniqNonEmpty(files);
  if (!uniq.length) {
    clearCatalogFilter();
    state.currentTreeNodeId = null;
  } else {
    state.currentCatalogFile = uniq[0];
    state.currentCatalogFiles = uniq;
    state.currentCatalogLabel = label || "";
    state.currentTreeNodeId = nodeId;
  }
}

function getCollectionFilterIds() {
  return _uniqNonEmpty([...(state.currentCollectionIds || []), state.currentCollection || ""]);
}

function hasCollectionFilter() {
  return getCollectionFilterIds().length > 0;
}

function clearCollectionFilter() {
  state.currentCollection = null;
  state.currentCollectionIds = [];
  state.currentCollectionLabel = "";
}

function setCollectionFilterIds(ids, { label = "", nodeId = null } = {}) {
  const uniq = _uniqNonEmpty(ids);
  if (!uniq.length) {
    clearCollectionFilter();
    state.currentTreeNodeId = null;
  } else {
    state.currentCollection = uniq.length === 1 ? uniq[0] : null;
    state.currentCollectionIds = uniq;
    state.currentCollectionLabel = label || "";
    state.currentTreeNodeId = nodeId;
  }
}

function collectDescendantCatalogFiles(node) {
  const files = [];
  const stack = [node];
  while (stack.length) {
    const cur = stack.pop();
    if (!cur || typeof cur !== "object") continue;
    if (cur.file) files.push(cur.file);
    const children = Array.isArray(cur.children) ? cur.children : [];
    for (const child of children) stack.push(child);
  }
  return _uniqNonEmpty(files);
}

function collectDescendantCollectionIds(node) {
  const ids = [];
  const stack = [node];
  while (stack.length) {
    const cur = stack.pop();
    if (!cur || typeof cur !== "object") continue;
    if (cur.collection_id) ids.push(cur.collection_id);
    const children = Array.isArray(cur.children) ? cur.children : [];
    for (const child of children) stack.push(child);
  }
  return _uniqNonEmpty(ids);
}

function _setTreeNodeExpanded(nodeKey, toggleEl, childrenEl, open) {
  if (open) {
    childrenEl.classList.add("open");
    toggleEl.classList.add("expanded");
    state.expandedTreeNodes.add(nodeKey);
  } else {
    childrenEl.classList.remove("open");
    toggleEl.classList.remove("expanded");
    state.expandedTreeNodes.delete(nodeKey);
  }
}

function _toggleTreeNodeExpanded(nodeKey, toggleEl, childrenEl) {
  _setTreeNodeExpanded(nodeKey, toggleEl, childrenEl, !childrenEl.classList.contains("open"));
}

function _wireTreeArrowToggle(toggleEl, nodeKey, childrenEl) {
  const arrow = toggleEl.querySelector(".tree-arrow");
  if (!arrow) return;
  arrow.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    _toggleTreeNodeExpanded(nodeKey, toggleEl, childrenEl);
  });
}

// ─── Asset loading ─────────────────────────────────────────────────────────────

async function loadAssets(opts = {}) {
  if (state.loadingAssets) return;
  const append = opts.append || false;
  if (!append) { state.offset = 0; }

  state.loadingAssets = true;
  const seq = ++state.assetsRequestSeq;

  if (!append) renderSkeletons();

  const params = new URLSearchParams();
  params.set("limit", ASSETS_PAGE_SIZE);
  params.set("offset", state.offset);

  const semQ = semanticQueryFromInput(state.q);
  if (semQ) {
    params.set("q", `sem:${semQ}`);
    state.semanticMode = true;
  } else {
    state.semanticMode = false;
    if (state.q) params.set("q", state.q);
  }

  if (state.currentSource) params.set("source", state.currentSource);
  if (state.currentBoard) params.set("board", state.currentBoard);
  if (state.currentCollection) params.set("collection_id", state.currentCollection);

  if (state.triageFilter === "needs-comment") {
    params.set("needs_annotation", "1");
    params.set("include_hidden", "1");
  } else if (state.triageFilter === "hidden") {
    params.set("triage_status", "hidden");
    params.set("include_hidden", "1");
  } else if (state.triageFilter === "flagged") {
    params.set("flagged", "1");
    params.set("include_hidden", "1");
  } else if (state.triageFilter) {
    params.set("triage_status", state.triageFilter);
  }

  // Always include hidden items when "all" is selected to show full picture
  // but don't show triage=hidden by default unless explicitly requested
  // (server default: exclude hidden)

  try {
    let data;
    const catalogFiles = getCatalogFilterFiles();
    if (catalogFiles.length) {
      // Catalog browsing: load items from one or more catalog files
      const catParams = new URLSearchParams();
      for (const file of catalogFiles) catParams.append("file", file);
      catParams.set("limit", ASSETS_PAGE_SIZE);
      catParams.set("offset", state.offset);
      data = await api(`/api/catalog/items?${catParams}`);
    } else if (semQ) {
      const res = await fetch(`/api/search/similar?${params}`);
      if (!res.ok) throw new Error(await res.text());
      data = await res.json();
    } else {
      const collectionIds = getCollectionFilterIds();
      if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
      data = await api(`/api/assets?${params}`);
    }

    if (seq !== state.assetsRequestSeq) return; // stale

    const newAssets = data.assets || [];
    if (append) {
      state.assets = [...state.assets, ...newAssets];
    } else {
      state.assets = newAssets;
    }
    state.hasMore = !!(data.has_more);
    state.totalCount = data.total || null;
    state.offset += newAssets.length;

    renderGrid();
    updateStats();
    updateLoadMoreBtn();
    updateFilterIndicator();
    syncExplorerFilter();
  } catch (e) {
    if (seq !== state.assetsRequestSeq) return;
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load items: ${escapeHtml(formatApiError(e))}</div>`;
  } finally {
    if (seq === state.assetsRequestSeq) state.loadingAssets = false;
  }
}

function updateLoadMoreBtn() {
  const btn = $("#loadMore");
  if (!btn) return;
  btn.hidden = !state.hasMore || state.semanticMode;
  btn.disabled = state.loadingAssets;
  btn.textContent = state.loadingAssets ? "Loading…" : "Load More";
}

function updateStats() {
  const statsEl = $("#stats");
  if (!statsEl) return;
  const shown = state.assets.length;
  const total = state.totalCount;
  if (state.hasMore && total) {
    statsEl.textContent = `${shown} of ${total} items`;
  } else if (state.hasMore) {
    statsEl.textContent = `${shown} items shown — more available`;
  } else {
    statsEl.textContent = `${shown} items`;
  }
}

// ─── Grid rendering ─────────────────────────────────────────────────────────────

function renderSkeletons() {
  const grid = $("#grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (let i = 0; i < 12; i++) {
    const el = document.createElement("div");
    el.className = "skeleton-card";
    el.innerHTML = '<div class="skeleton-thumb"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>';
    grid.appendChild(el);
  }
}

function renderGrid() {
  const grid = $("#grid");
  if (!grid) return;
  grid.innerHTML = "";
  // Maintain canvas review class across re-renders
  const browseView = $("#browseView");
  if (browseView) browseView.classList.toggle("canvas-review-active", state.canvasReview);

  if (!state.assets.length) {
    grid.innerHTML = '<div class="empty-state">No items match your current filters.</div>';
    return;
  }

  for (const a of state.assets) {
    grid.appendChild(buildCard(a));
  }
}

function buildCard(a) {
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.id = a.id;

  const imgUrl = previewForAsset(a);
  const ts = a.triage_status || "";
  const needsComment = a.needs_annotation == 1;
  const flagged = a.flagged == 1;
  const tagged = a.tagged == 1;

  // Triage/flag/tag badges — owner-only
  let tagBadgeHtml = "";
  let badgeHtml = "";
  if (isOwner()) {
    // Tagged badge (Jim's anomaly markers for Claude Code diagnosis)
    if (tagged) {
      tagBadgeHtml = '<span class="triage-badge tagged" title="Tagged for diagnosis"></span>';
    }
    if (flagged) {
      badgeHtml = '<span class="triage-badge flagged" title="Flagged for review"></span>';
    } else if (ts === "keeper" && needsComment) {
      badgeHtml = '<span class="triage-badge needs-comment" title="Keeper — needs comment"></span>';
    } else if (ts === "keeper") {
      badgeHtml = '<span class="triage-badge keeper" title="Keeper"></span>';
    } else if (ts === "hidden") {
      badgeHtml = '<span class="triage-badge hidden-status" title="Hidden"></span>';
    }
  }

  const isScan = a.source === "scan";
  const memberIds = (a.scan_group_member_ids || []);
  const isMultiScan = isScan && memberIds.length > 1;

  let scanNavHtml = "";
  if (isMultiScan) {
    scanNavHtml = `<div class="card-scan-nav">
      <button class="scan-nav-btn scan-prev" aria-label="Previous page" disabled>‹</button>
      <span class="scan-nav-indicator">1 / ${memberIds.length}</span>
      <button class="scan-nav-btn scan-next" aria-label="Next page">›</button>
    </div>`;
  }

  const sourceLabel = { pinterest: "Pin", facebook: "FB", scan: "Scan", photo: "Photo" }[a.source] || a.source || "";
  const quickTagHtml = state.actor
    ? `<button class="card-quick-tag${tagged ? " tagged" : ""}" title="${tagged ? "Remove tag" : "Tag for diagnosis"}" type="button">🏷️</button>`
    : "";
  const isKeeper = ts === "keeper";
  const quickStarHtml = isOwner()
    ? `<button class="card-quick-star${isKeeper ? " starred" : ""}" title="${isKeeper ? "Remove keeper" : "Mark as keeper"}" type="button">★</button>`
    : "";

  const selectedClass = state.canvasReview && state.canvasSelected.has(a.id) ? " canvas-selected" : "";
  el.className = "card" + selectedClass;

  el.innerHTML = `
    <div class="card-image">
      <div class="card-checkbox"></div>
      ${imgUrl
        ? `<img src="${escapeHtml(imgUrl)}" loading="lazy" alt="" />`
        : `<div class="card-placeholder">${escapeHtml(displayTitle(a))}</div>`}
      ${tagBadgeHtml}${badgeHtml}
      <span class="source-badge source-${escapeHtml(a.source || "")}">${escapeHtml(sourceLabel)}</span>
      ${quickStarHtml}
      ${quickTagHtml}
      ${scanNavHtml}
    </div>
    <div class="card-footer">
      <span class="card-title">${escapeHtml(displayTitle(a))}</span>
      <span class="card-source">${escapeHtml([a.board, a.creator_name].filter(Boolean).join(" · "))}</span>
    </div>
  `;

  el.onclick = (e) => {
    if (e.target.closest(".scan-nav-btn")) return;
    if (state.canvasReview) {
      toggleCanvasSelection(a.id, el);
      return;
    }
    openModal(a);
  };

  // Scan page nav wiring
  if (isMultiScan) {
    let pageIdx = 0;
    const prev = el.querySelector(".scan-prev");
    const next = el.querySelector(".scan-next");
    const indicator = el.querySelector(".scan-nav-indicator");
    const img = el.querySelector(".card-image img");

    const updateNav = () => {
      if (prev) prev.disabled = pageIdx === 0;
      if (next) next.disabled = pageIdx >= memberIds.length - 1;
      if (indicator) indicator.textContent = `${pageIdx + 1} / ${memberIds.length}`;
      if (img) img.src = `/media/${memberIds[pageIdx]}?kind=thumb`;
    };

    if (prev) prev.addEventListener("click", (e) => { e.stopPropagation(); pageIdx = Math.max(0, pageIdx - 1); updateNav(); });
    if (next) next.addEventListener("click", (e) => { e.stopPropagation(); pageIdx = Math.min(memberIds.length - 1, pageIdx + 1); updateNav(); });
  }

  // Quick-tag button wiring (Jim's anomaly tagging)
  const quickTagBtn = el.querySelector(".card-quick-tag");
  if (quickTagBtn) {
    quickTagBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const newTagged = a.tagged ? 0 : 1;
      try {
        await api(`/api/assets/${encodeURIComponent(a.id)}/tag`, {
          method: "POST",
          body: JSON.stringify({ tagged: newTagged }),
        });
        a.tagged = newTagged;
        // Toggle tag badge on card
        const cardImg = el.querySelector(".card-image");
        const oldBadge = el.querySelector(".triage-badge.tagged");
        if (oldBadge) oldBadge.remove();
        if (newTagged && cardImg) {
          const badge = document.createElement("span");
          badge.className = "triage-badge tagged";
          badge.title = "Tagged for diagnosis";
          cardImg.prepend(badge);
        }
        // Update quick-tag button state
        quickTagBtn.classList.toggle("tagged", !!newTagged);
        quickTagBtn.title = newTagged ? "Remove tag" : "Tag for diagnosis";
        Shared.showToast(newTagged ? "Tagged for diagnosis" : "Tag removed", { type: "success", duration: 2000 });
      } catch (err) {
        Shared.showToast(`Tag failed: ${formatApiError(err)}`, { type: "error" });
      }
    });
  }

  // Quick-star button wiring (owner keep/unkeep)
  const quickStarBtn = el.querySelector(".card-quick-star");
  if (quickStarBtn) {
    quickStarBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const newStatus = a.triage_status === "keeper" ? null : "keeper";
      try {
        await api(`/api/assets/${encodeURIComponent(a.id)}/triage`, {
          method: "POST",
          body: JSON.stringify({ status: newStatus }),
        });
        a.triage_status = newStatus;
        // Toggle keeper badge on card
        const cardImg = el.querySelector(".card-image");
        const oldBadge = el.querySelector(".triage-badge.keeper");
        if (oldBadge) oldBadge.remove();
        if (newStatus === "keeper" && cardImg) {
          const badge = document.createElement("span");
          badge.className = "triage-badge keeper";
          badge.title = "Keeper";
          cardImg.prepend(badge);
        }
        // Update star button state
        quickStarBtn.classList.toggle("starred", newStatus === "keeper");
        quickStarBtn.title = newStatus === "keeper" ? "Remove keeper" : "Mark as keeper";
        Shared.showToast(newStatus === "keeper" ? "Marked as keeper ★" : "Keeper removed", { type: "success", duration: 2000 });
        // Refresh tree counts
        loadCatalogTree();
        if (isOwner()) loadHiddenTree();
      } catch (err) {
        Shared.showToast(`Keep failed: ${formatApiError(err)}`, { type: "error" });
      }
    });
  }

  return el;
}

// ─── Catalog tree + sidebar ──────────────────────────────────────────────────

async function loadFacets() {
  try {
    const params = new URLSearchParams();
    if (state.currentSource) params.set("source", state.currentSource);
    const qs = params.toString();
    const data = await api(`/api/facets${qs ? "?" + qs : ""}`);
    const facets = data.facets || data;
    state.facets = facets;
  } catch (e) {
    console.error("Failed to load facets:", e);
  }
}

async function loadCatalogTree() {
  try {
    const data = await api("/api/catalog/tree");
    state.catalogTree = data.tree || [];
    renderCatalogTree();
  } catch (e) {
    console.error("Failed to load catalog tree:", e);
    const wrap = $("#catalogTree");
    if (wrap) wrap.innerHTML = '<div class="muted sidebar-loading">Tree unavailable.</div>';
  }
}

function resetTriageFilter() {
  if (state.triageFilter) {
    state.triageFilter = "";
    // Update status chip UI to reflect "All"
    $$("[data-triage]").forEach((c) => {
      c.classList.toggle("active", c.dataset.triage === "");
    });
  }
}

function renderCatalogTree() {
  const wrap = $("#catalogTree");
  if (!wrap) return;
  wrap.innerHTML = "";

  const tree = state.catalogTree || [];
  if (!tree.length) {
    wrap.innerHTML = '<div class="muted sidebar-loading">No catalog yet.</div>';
    return;
  }

  // "All items" node at top
  const allBtn = document.createElement("button");
  allBtn.className = `tree-leaf${!state.currentSource && !state.currentBoard && !hasCollectionFilter() && !hasCatalogFilter() ? " active" : ""}`;
  allBtn.innerHTML = `<span>All Items</span>`;
  allBtn.onclick = () => {
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    clearCollectionFilter();
    clearCatalogFilter();
    state.currentTreeNodeId = null;
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };
  wrap.appendChild(allBtn);

  for (const node of tree) {
    if (node.type === "source") {
      wrap.appendChild(buildSourceNode(node));
    } else if (node.type === "dimension") {
      wrap.appendChild(buildDimensionNode(node));
    } else if (node.type === "collections_group") {
      wrap.appendChild(buildCollectionsGroupNode(node));
    }
  }

  // Re-append hidden tree (owner-only) — it lives inside catalogTree
  // and gets wiped by innerHTML="" above
  if (isOwner() && state.hiddenTree) renderHiddenTree();
}

function buildSourceNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = node.id;
  const sourceKey = node.label.toLowerCase();
  const selectedCatalogFiles = getCatalogFilterFiles();
  const selectedCatalogSet = new Set(selectedCatalogFiles);
  const isActiveSource = state.currentTreeNodeId === node.id
    || (state.currentSource === sourceKey && !state.currentBoard && !hasCatalogFilter() && !hasCollectionFilter());
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveSource ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span>${escapeHtml(node.label)}</span><span class="tree-count">${node.count}</span>`;

  const children = document.createElement("div");
  children.className = "tree-children";

  // Check if any child is active — auto-expand
  const hasActiveChild = (node.children || []).some(
    (c) => {
      const boardName = c.board_name || "";
      const isCatchAll = boardName.startsWith("(");
      if (isCatchAll) return !!c.file && selectedCatalogSet.has(c.file);
      return state.currentSource === sourceKey && state.currentBoard && state.currentBoard.toLowerCase() === boardName.toLowerCase();
    }
  );
  if (hasActiveChild || isActiveSource) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Header click filters to the full source scope (all descendant folders).
  toggle.onclick = () => {
    resetTriageFilter();
    state.currentSource = sourceKey;
    state.currentBoard = null;
    clearCollectionFilter();
    clearCatalogFilter();
    state.currentTreeNodeId = node.id;
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    const leaf = document.createElement("button");
    const boardName = child.label;
    const boardDbName = child.board_name || "";  // original board name from DB
    const isCatchAll = boardDbName.startsWith("(");  // (small boards), (unsorted reels), etc.

    // For catch-all entries, use catalog file mode; for regular boards, filter by source+board
    const isActive = isCatchAll
      ? selectedCatalogFiles.length === 1 && selectedCatalogFiles[0] === child.file
      : (state.currentSource === sourceKey
        && state.currentBoard
        && state.currentBoard.toLowerCase() === boardDbName.toLowerCase());

    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.innerHTML = `<span>${escapeHtml(boardName)}</span><span class="tree-count">${child.count}</span>`;
    leaf.onclick = () => {
      resetTriageFilter();
      if (isCatchAll) {
        // Use catalog file mode for catch-all entries
        state.currentSource = null;
        state.currentBoard = null;
        clearCollectionFilter();
        setCatalogFilter([child.file], { label: child.label, nodeId: child.id });
      } else {
        // Direct source+board filter for named boards
        state.currentSource = sourceKey;
        state.currentBoard = boardDbName;
        clearCollectionFilter();
        clearCatalogFilter();
        state.currentTreeNodeId = child.id;
      }
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    // Context menu for bulk triage (owner-only)
    if (!isCatchAll) {
      const _src = node.label.toLowerCase();
      const _brd = boardDbName;
      addTreeHideToggle(leaf, () => ({ source: _src, board: _brd }));
    }
    children.appendChild(leaf);
  }

  // Context menu for the entire source (owner-only)
  addTreeHideToggle(toggle, () => ({ source: node.label.toLowerCase() }));

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildDimensionNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = node.id;
  const selectedCatalogFiles = getCatalogFilterFiles();
  const selectedCatalogSet = new Set(selectedCatalogFiles);
  const isActiveHeader = state.currentTreeNodeId === node.id;
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span>${escapeHtml(node.label)}</span><span class="tree-count">${node.count}</span>`;

  const children = document.createElement("div");
  children.className = "tree-children";

  // Check if any child is active — auto-expand
  const hasActiveChild = (node.children || []).some(
    (c) => selectedCatalogSet.has(c.file)
  );
  if (hasActiveChild || isActiveHeader) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Header click filters to all descendant catalog files.
  toggle.onclick = () => {
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    clearCollectionFilter();
    setCatalogFilter(collectDescendantCatalogFiles(node), { label: node.label, nodeId: node.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    const leaf = document.createElement("button");
    const isActive = selectedCatalogFiles.length === 1 && selectedCatalogFiles[0] === child.file;
    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.innerHTML = `<span>${escapeHtml(child.label)}</span><span class="tree-count">${child.count}</span>`;
    leaf.onclick = () => {
      resetTriageFilter();
      state.currentSource = null;
      state.currentBoard = null;
      clearCollectionFilter();
      setCatalogFilter([child.file], { label: child.label, nodeId: child.id });
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    children.appendChild(leaf);
  }

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

function buildCollectionsGroupNode(node) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const nodeKey = "collections";
  const selectedCollectionIds = getCollectionFilterIds();
  const selectedCollectionSet = new Set(selectedCollectionIds);
  const isActiveHeader = state.currentTreeNodeId === node.id;
  const toggle = document.createElement("button");
  toggle.className = `tree-toggle${isActiveHeader ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span>Collections</span><span class="tree-count">${node.count}</span>`;

  const children = document.createElement("div");
  children.className = "tree-children";

  const hasActiveChild = (node.children || []).some((c) => selectedCollectionSet.has(c.collection_id));
  if (hasActiveChild || isActiveHeader) state.expandedTreeNodes.add(nodeKey);
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Header click filters to all descendant collections.
  toggle.onclick = () => {
    resetTriageFilter();
    state.currentSource = null;
    state.currentBoard = null;
    clearCatalogFilter();
    setCollectionFilterIds(collectDescendantCollectionIds(node), { label: "All Collections", nodeId: node.id });
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
  };

  for (const child of (node.children || [])) {
    const leaf = document.createElement("button");
    const isActive = selectedCollectionIds.length === 1 && selectedCollectionIds[0] === child.collection_id;
    leaf.className = `tree-leaf${isActive ? " active" : ""}`;
    leaf.innerHTML = `<span>${escapeHtml(child.label)}</span><span class="tree-count">${child.count}</span>`;
    leaf.onclick = () => {
      resetTriageFilter();
      state.currentSource = null;
      state.currentBoard = null;
      clearCatalogFilter();
      setCollectionFilterIds([child.collection_id], { label: child.label, nodeId: child.id });
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    };
    // Context menu for bulk triage on collections (owner-only)
    const _colId = child.collection_id;
    addTreeHideToggle(leaf, () => ({ collection_id: _colId }));
    children.appendChild(leaf);
  }

  el.appendChild(toggle);
  el.appendChild(children);
  return el;
}

// ─── Bulk triage from sidebar (owner-only) ───────────────────────────────────

// Track which tree node keys have been bulk-hidden (for undo)
// Key: serialized filter params string; Value: array of asset IDs that were hidden
const _bulkHiddenByNode = {};

function _nodeKey(filterParams) {
  return JSON.stringify(filterParams, Object.keys(filterParams).sort());
}

function addTreeHideToggle(el, getFilterParams) {
  if (!isOwner()) return;
  const btn = document.createElement("button");
  btn.className = "tree-hide-toggle";
  btn.title = "Hide all items in this folder";
  const key = _nodeKey(getFilterParams());
  const isHidden = !!_bulkHiddenByNode[key];
  btn.innerHTML = "✗";
  btn.classList.toggle("tree-hide-active", isHidden);

  btn.onclick = async (e) => {
    e.stopPropagation();
    e.preventDefault();
    const currentKey = _nodeKey(getFilterParams());
    if (_bulkHiddenByNode[currentKey]) {
      // UNDO: reset items back to pending
      await bulkTriageFromTree(null, getFilterParams(), currentKey);
    } else {
      // HIDE: hide all items
      await bulkTriageFromTree("hidden", getFilterParams(), currentKey);
    }
  };
  el.style.position = "relative";
  el.appendChild(btn);
}

async function bulkTriageFromTree(status, filterParams, nodeKey) {
  const isHiding = status === "hidden";
  const isUndoing = status === null && _bulkHiddenByNode[nodeKey];
  try {
    let ids;
    if (isUndoing) {
      // Use the saved IDs to undo
      ids = _bulkHiddenByNode[nodeKey];
    } else {
      // Fetch all matching IDs from the server
      const params = new URLSearchParams(filterParams);
      params.set("limit", "5000");
      params.set("offset", "0");
      params.set("include_hidden", "1");
      const data = await api(`/api/assets?${params}`);
      ids = (data.assets || []).map((a) => a.id);
    }
    if (!ids || !ids.length) {
      Shared.showToast("No items in this folder.", { type: "info" });
      return;
    }
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status }),
    });

    if (isHiding) {
      _bulkHiddenByNode[nodeKey] = ids;
      Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} hidden.`, { type: "success" });
    } else if (isUndoing) {
      delete _bulkHiddenByNode[nodeKey];
      Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} restored.`, { type: "success" });
    }

    // Refresh grid + tree (re-fetch tree for updated counts)
    await loadAssets();
    await loadCatalogTree();
    if (isOwner()) loadHiddenTree();
  } catch (e) {
    Shared.showToast(`Bulk triage failed: ${formatApiError(e)}`, { type: "error" });
  }
}

function setSourceFilter(source) {
  resetTriageFilter();
  state.currentSource = source || null;
  state.currentBoard = null;
  clearCollectionFilter();
  clearCatalogFilter();
  state.currentTreeNodeId = null;
  state.offset = 0;
  renderCatalogTree();
  loadAssets();
}

function setBoardFilter(board) {
  resetTriageFilter();
  state.currentBoard = board || null;
  clearCollectionFilter();
  clearCatalogFilter();
  state.currentTreeNodeId = null;
  state.offset = 0;
  renderCatalogTree();
  loadAssets();
}

function showDynamicSidebar(heading, items) {
  const section = $("#dynamicSidebarSection");
  const headingEl = $("#dynamicSidebarHeading");
  const content = $("#dynamicSidebarContent");
  if (!section || !headingEl || !content) return;
  headingEl.textContent = heading;
  content.innerHTML = "";
  for (const item of items) {
    const btn = document.createElement("button");
    btn.className = "tree-leaf";
    btn.innerHTML = `<span>${escapeHtml(item.label)}</span>${item.count != null ? `<span class="tree-count">${item.count}</span>` : ""}`;
    if (item.onclick) btn.onclick = item.onclick;
    content.appendChild(btn);
  }
  section.hidden = false;
}

function hideDynamicSidebar() {
  const section = $("#dynamicSidebarSection");
  if (section) section.hidden = true;
}

// ─── Hidden tree (owner-only) ──────────────────────────────────────────────────

async function loadHiddenTree() {
  try {
    const data = await api("/api/hidden/tree");
    state.hiddenTree = data;
    renderHiddenTree();
  } catch {
    state.hiddenTree = null;
  }
}

function renderHiddenTree() {
  const wrap = $("#catalogTree");
  if (!wrap || !state.hiddenTree) return;
  const tree = state.hiddenTree;
  if (!tree.total) return;

  // Keep a single hidden section even when multiple render paths run.
  wrap.querySelectorAll(".tree-hidden-section").forEach((n) => n.remove());

  const el = document.createElement("div");
  el.className = "tree-node tree-hidden-section";

  const toggle = document.createElement("button");
  const allHidden = state.triageFilter === "hidden"
    && !state.currentSource
    && !state.currentBoard
    && !hasCollectionFilter()
    && !hasCatalogFilter();
  toggle.className = `tree-toggle${allHidden ? " active" : ""}`;
  toggle.innerHTML = `<span class="tree-arrow">&#9654;</span><span class="tree-hidden-label">&#128065;&#xFE0E; Hidden</span><span class="tree-count">${tree.total}</span>`;

  const children = document.createElement("div");
  children.className = "tree-children";

  // "All Hidden" leaf
  const allLeaf = document.createElement("button");
  allLeaf.className = `tree-leaf tree-hidden-folder${allHidden ? " active" : ""}`;
  allLeaf.innerHTML = `<span>All Hidden</span><span class="tree-count">${tree.total}</span>`;
  allLeaf.onclick = () => {
    state.currentSource = null;
    state.currentBoard = null;
    clearCollectionFilter();
    clearCatalogFilter();
    state.currentTreeNodeId = null;
    state.triageFilter = "hidden";
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
    syncExplorerFilter();
  };
  children.appendChild(allLeaf);

  for (const src of (tree.sources || [])) {
    for (const b of (src.boards || [])) {
      const leaf = document.createElement("button");
      const isActive = state.triageFilter === "hidden" && state.currentSource === src.source && state.currentBoard === b.board;
      leaf.className = `tree-leaf tree-hidden-folder${isActive ? " active" : ""}`;
      leaf.innerHTML = `<span>${escapeHtml(src.source)} / ${escapeHtml(b.board)}</span><span class="tree-count">${b.count}</span>`;
      leaf.onclick = () => {
        state.currentSource = src.source;
        state.currentBoard = b.board;
        clearCollectionFilter();
        clearCatalogFilter();
        state.currentTreeNodeId = null;
        state.triageFilter = "hidden";
        state.offset = 0;
        renderCatalogTree();
        loadAssets();
        syncExplorerFilter();
      };
      children.appendChild(leaf);
    }
  }

  const nodeKey = "hidden-tree";
  if (allHidden || state.triageFilter === "hidden") {
    state.expandedTreeNodes.add(nodeKey);
  }
  _setTreeNodeExpanded(nodeKey, toggle, children, state.expandedTreeNodes.has(nodeKey));
  _wireTreeArrowToggle(toggle, nodeKey, children);

  // Hidden root header click applies "all hidden" filter.
  toggle.onclick = () => {
    state.currentSource = null;
    state.currentBoard = null;
    clearCollectionFilter();
    clearCatalogFilter();
    state.currentTreeNodeId = null;
    state.triageFilter = "hidden";
    state.offset = 0;
    renderCatalogTree();
    loadAssets();
    syncExplorerFilter();
  };

  el.appendChild(toggle);
  el.appendChild(children);
  wrap.appendChild(el);
}

// ─── Question badge + polling (owner-only) ──────────────────────────────────────

async function pollQuestions() {
  try {
    const data = await api("/api/questions/dashboard");
    state.openQuestions = data.questions || [];
    renderQuestionBadge();
  } catch {
    // silent
  }
}

function renderQuestionBadge() {
  let badge = $("#questionBadge");
  if (!badge) {
    // Create badge element in header if it doesn't exist
    const header = $(".top-bar") || $("header");
    if (!header) return;
    badge = document.createElement("button");
    badge.id = "questionBadge";
    badge.className = "question-badge";
    badge.title = "Open questions from collaborators";
    badge.onclick = toggleQuestionPanel;
    header.appendChild(badge);
  }
  const count = state.openQuestions.length;
  badge.hidden = count === 0;
  badge.innerHTML = `<span class="question-badge-icon">?</span><span class="question-badge-count">${count}</span>`;
}

function toggleQuestionPanel() {
  let panel = $("#questionPanel");
  if (panel) {
    panel.remove();
    return;
  }
  panel = document.createElement("div");
  panel.id = "questionPanel";
  panel.className = "question-panel";

  const header = document.createElement("div");
  header.className = "question-panel-header";
  header.innerHTML = `<strong>Open Questions (${state.openQuestions.length})</strong>`;
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "\u00d7";
  closeBtn.className = "question-panel-close";
  closeBtn.onclick = () => panel.remove();
  header.appendChild(closeBtn);
  panel.appendChild(header);

  if (!state.openQuestions.length) {
    panel.innerHTML += '<div class="question-panel-empty">No open questions!</div>';
  } else {
    for (const q of state.openQuestions) {
      const item = document.createElement("div");
      item.className = "question-panel-item";
      item.innerHTML = `
        <div class="question-panel-item-meta">${escapeHtml(q.actor_name || "Anonymous")} &middot; ${escapeHtml(q.asset_title || "Untitled")}</div>
        <div class="question-panel-item-text">${escapeHtml(q.text || "(no text)")}</div>
      `;
      item.onclick = () => {
        panel.remove();
        // Navigate to the asset
        const asset = state.assets.find((a) => a.id === q.asset_id);
        if (asset) { openModal(asset); }
        else { Shared.showToast("Loading item...", { type: "info", duration: 2000 }); }
      };
      panel.appendChild(item);
    }
  }

  const badge = $("#questionBadge");
  if (badge) badge.parentElement.appendChild(panel);
  else document.body.appendChild(panel);
}

// ─── Triage status filter ───────────────────────────────────────────────────────

function wireStatusChips() {
  const chips = $$("[data-triage]");
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.triageFilter = chip.dataset.triage;
      state.offset = 0;
      renderCatalogTree();
      loadAssets();
    });
  });
}

// ─── Collections ────────────────────────────────────────────────────────────────

async function loadCollections() {
  try {
    const data = await api("/api/collections");
    state.collections = data.collections || [];
  } catch (e) {
    console.error("Failed to load collections:", e);
  }
}

function setCollectionFilter(collectionId) {
  if (collectionId) {
    state.currentSource = null;
    state.currentBoard = null;
    clearCatalogFilter();
    const col = state.collections.find((c) => c.id === collectionId);
    setCollectionFilterIds([collectionId], { label: col ? col.name : "", nodeId: null });
  } else {
    clearCollectionFilter();
    state.currentTreeNodeId = null;
  }
  state.offset = 0;
  renderCatalogTree();
  loadAssets();
}

$("#newCollection").addEventListener("click", async () => {
  const name = prompt("Collection name:");
  if (!name || !name.trim()) return;
  try {
    await api("/api/collections", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
    await loadCollections();
    await loadCatalogTree();
    Shared.showToast(`Created collection "${name.trim()}"`, { type: "success" });
  } catch (e) {
    Shared.showToast(`Failed: ${formatApiError(e)}`, { type: "error" });
  }
});

// ─── Detail modal ────────────────────────────────────────────────────────────────

async function openModal(asset) {
  state.modalAsset = asset;

  const title = displayTitle(asset);
  const metaParts = [];
  if (asset.board) metaParts.push(asset.board);
  metaParts.push(asset.source || "");
  if (asset.created_at) metaParts.push(asset.created_at.slice(0, 10));

  $("#modalTitle").textContent = title;
  $("#modalMeta").textContent = metaParts.filter(Boolean).join(" · ");

  const img = $("#modalImage");
  if (img) {
    const url = asset.thumb_path ? `/media/${asset.id}?kind=original`
                : asset.stored_path ? `/media/${asset.id}?kind=original`
                : asset.image_url || "";
    img.src = url;
    img.style.display = url ? "block" : "none";
  }

  // Content kind badge
  const badgeWrap = $("#modalBadge");
  if (badgeWrap) {
    const kind = (asset.content_kind || "").trim();
    const kindLabels = { pin: "Pin", reel: "Reel", video: "Video", photo: "Photo", scan: "Scan", link: "Link", post: "Post" };
    if (kind) {
      badgeWrap.textContent = kindLabels[kind.toLowerCase()] || kind;
      badgeWrap.hidden = false;
    } else {
      badgeWrap.hidden = true;
    }
  }

  // Creator
  const creatorEl = $("#modalCreator");
  if (creatorEl) {
    const creator = (asset.creator_name || "").trim();
    creatorEl.textContent = creator ? `by ${creator}` : "";
    creatorEl.hidden = !creator;
  }

  // Description (post_text / closeup_desc / seo_alt_text)
  const descEl = $("#modalDescription");
  if (descEl) {
    const desc = (asset.post_text || "").trim()
      || (asset.closeup_desc || "").trim()
      || (asset.seo_alt_text || "").trim();
    descEl.textContent = desc;
    descEl.hidden = !desc;
  }

  // Hashtags
  const hashtagsEl = $("#modalHashtags");
  if (hashtagsEl) {
    const raw = (asset.hashtags || "").trim();
    if (raw) {
      const tags = raw.split(",").map(t => t.trim()).filter(Boolean);
      hashtagsEl.innerHTML = tags.map(t => `<span class="hashtag-chip">${escapeHtml(t)}</span>`).join(" ");
      hashtagsEl.hidden = false;
    } else {
      hashtagsEl.innerHTML = "";
      hashtagsEl.hidden = true;
    }
  }

  // Labels / tags
  const labelsEl = $("#modalLabels");
  if (labelsEl) {
    labelsEl.innerHTML = "";
    labelsEl.hidden = true;
    labelsEl.classList.remove("expanded");
    try {
      const resp = await fetch(`/api/assets/${asset.id}/labels`);
      if (resp.ok) {
        const data = await resp.json();
        const labels = data.labels || [];
        if (labels.length > 0) {
          const INITIAL_SHOW = 30;
          const chips = labels.map(l =>
            `<span class="label-chip" data-source="${escapeHtml(l.source || "")}" title="${escapeHtml(l.source || "")}">${escapeHtml(l.label)}</span>`
          );
          labelsEl.innerHTML = chips.slice(0, INITIAL_SHOW).join(" ");
          if (labels.length > INITIAL_SHOW) {
            const toggleBtn = document.createElement("button");
            toggleBtn.className = "labels-toggle";
            toggleBtn.textContent = `+${labels.length - INITIAL_SHOW} more`;
            toggleBtn.onclick = () => {
              labelsEl.innerHTML = chips.join(" ");
              labelsEl.classList.add("expanded");
            };
            labelsEl.appendChild(toggleBtn);
          }
          labelsEl.hidden = false;
        }
      }
    } catch {}
  }

  // Engagement stats
  const engagementEl = $("#modalEngagement");
  if (engagementEl) {
    let engHtml = "";
    try {
      const eng = asset.engagement_json ? JSON.parse(asset.engagement_json) : null;
      if (eng) {
        const parts = [];
        if (eng.repins != null) parts.push(`${eng.repins} repins`);
        if (eng.comments != null) parts.push(`${eng.comments} comments`);
        if (eng.likes != null) parts.push(`${eng.likes} likes`);
        if (eng.reactions != null) parts.push(`${eng.reactions} reactions`);
        if (eng.shares != null) parts.push(`${eng.shares} shares`);
        engHtml = parts.join(" · ");
      }
    } catch {}
    engagementEl.textContent = engHtml;
    engagementEl.hidden = !engHtml;
  }

  // Image dimensions
  const dimsEl = $("#modalDimensions");
  if (dimsEl) {
    const w = asset.image_width;
    const h = asset.image_height;
    if (w && h) {
      dimsEl.textContent = `${w} × ${h}`;
      dimsEl.hidden = false;
    } else {
      dimsEl.hidden = true;
    }
  }

  // Source link — use source_ref only if it's a valid HTTP URL;
  // otherwise fall back to source_url (fixes Houzz houzz:// URIs etc.)
  const ref = asset.source_ref || "";
  const isHttpRef = ref.startsWith("http://") || ref.startsWith("https://");
  const siteUrl = asset.source_url || "";
  const isHttpSite = siteUrl.startsWith("http://") || siteUrl.startsWith("https://");

  const sourceLink = $("#sourceLink");
  if (sourceLink) {
    if (asset.source === "scan" && ref) {
      sourceLink.href = `/media/${asset.id}?kind=pdf`;
      sourceLink.textContent = "Open PDF";
      sourceLink.hidden = false;
    } else if (isHttpRef) {
      sourceLink.href = ref;
      sourceLink.textContent = `Open ${asset.source || "original"}`;
      sourceLink.hidden = false;
    } else if (isHttpSite) {
      sourceLink.href = siteUrl;
      sourceLink.textContent = `Open ${asset.source || "original"}`;
      sourceLink.hidden = false;
    } else {
      sourceLink.hidden = true;
    }
  }

  // Source site link — only show when primary link used source_ref (not source_url)
  const sourceSiteRow = $("#sourceSiteRow");
  const sourceSiteLink = $("#sourceSiteLink");
  const showSiteLink = sourceSiteRow && sourceSiteLink && isHttpSite && isHttpRef;
  if (showSiteLink) {
    sourceSiteLink.href = siteUrl;
    sourceSiteLink.textContent = `Original site (${sourceHost(siteUrl) || siteUrl}) ↗`;
    sourceSiteRow.hidden = false;
  } else if (sourceSiteRow) {
    sourceSiteRow.hidden = true;
  }

  // View source button — scans: show page image (not the full combined PDF)
  const viewSourceBtn = $("#viewSourceBtn");
  if (viewSourceBtn) {
    if (asset.source === "scan" && asset.source_ref) {
      viewSourceBtn.textContent = "View Page";
      viewSourceBtn.onclick = () => { window.open(`/media/${asset.id}?kind=original`, "_blank", "noopener"); };
      viewSourceBtn.disabled = false;
      viewSourceBtn.hidden = false;
    } else {
      viewSourceBtn.hidden = true;
    }
  }

  // Print button
  const printBtn = $("#printAssetBtn");
  if (printBtn) printBtn.onclick = () => printModalAsset(asset);

  // Notes
  const notesArea = $("#assetNotes");
  if (notesArea) {
    notesArea.value = asset.notes || "";
    notesArea.oninput = () => scheduleNotesUpdate(asset.id, notesArea.value);
  }

  // Keeper star in modal title
  const keeperStar = $("#modalKeeperStar");
  if (keeperStar) keeperStar.hidden = asset.triage_status !== "keeper";

  // Triage buttons
  updateModalTriageButtons(asset.triage_status);
  const keepBtn = $("#modalKeepBtn");
  const hideBtn = $("#modalHideBtn");
  if (keepBtn) keepBtn.onclick = async () => { await setTriageFromModal(asset, "keeper"); };
  if (hideBtn) hideBtn.onclick = async () => { await setTriageFromModal(asset, "hidden"); };

  // Flag button
  const flagBtn = $("#modalFlagBtn");
  if (flagBtn) {
    flagBtn.classList.toggle("active", !!asset.flagged);
    flagBtn.textContent = asset.flagged ? "🚩 Flagged" : "🚩 Flag";
    flagBtn.onclick = async () => {
      const newFlagged = asset.flagged ? 0 : 1;
      try {
        await api(`/api/assets/${encodeURIComponent(asset.id)}/flag`, {
          method: "POST",
          body: JSON.stringify({ flagged: newFlagged }),
        });
        asset.flagged = newFlagged;
        flagBtn.classList.toggle("active", !!newFlagged);
        flagBtn.textContent = newFlagged ? "🚩 Flagged" : "🚩 Flag";
        // Update card badge
        const card = $(`[data-id="${asset.id}"]`);
        if (card) {
          const oldBadge = card.querySelector(".triage-badge.flagged");
          if (oldBadge) oldBadge.remove();
          if (newFlagged) {
            const badge = document.createElement("span");
            badge.className = "triage-badge flagged";
            badge.title = "Flagged for review";
            card.querySelector(".card-image").prepend(badge);
          }
        }
        Shared.showToast(newFlagged ? "Flagged for review" : "Flag removed", { type: "success" });
      } catch (e) {
        Shared.showToast(`Failed: ${formatApiError(e)}`, { type: "error" });
      }
    };
  }

  // Scan page nav
  const imageStage = $("#imageStage");
  const existingNav = imageStage && imageStage.querySelector(".modalScanNav");
  if (existingNav) existingNav.remove();

  if (asset.source === "scan" && (asset.scan_group_member_ids || []).length > 1) {
    const pages = asset.scan_group_member_ids;
    state.modalScanPages = pages;
    const refMatch = (asset.source_ref || "").match(/#p(\d+)$/);
    state.modalScanPageIndex = refMatch ? parseInt(refMatch[1], 10) - 1 : 0;
    const navEl = document.createElement("div");
    navEl.className = "modalScanNav";
    navEl.innerHTML = `
      <button class="modalScanPrev" ${state.modalScanPageIndex === 0 ? "disabled" : ""}>‹</button>
      <span class="modalScanIndicator">Page ${state.modalScanPageIndex + 1} of ${pages.length}</span>
      <button class="modalScanNext" ${state.modalScanPageIndex === pages.length - 1 ? "disabled" : ""}>›</button>
    `;
    navEl.querySelector(".modalScanPrev").onclick = () => _navModalScan(-1);
    navEl.querySelector(".modalScanNext").onclick = () => _navModalScan(1);
    if (imageStage) imageStage.appendChild(navEl);
  } else {
    state.modalScanPages = null;
    state.modalScanPageIndex = 0;
  }

  $("#modal").classList.remove("hidden");
  await loadAnnotations(asset.id);
  renderAnnotations();
  renderMarkers();
}

function updateModalTriageButtons(triageStatus) {
  const keepBtn = $("#modalKeepBtn");
  const hideBtn = $("#modalHideBtn");
  if (keepBtn) keepBtn.classList.toggle("active", triageStatus === "keeper");
  if (hideBtn) hideBtn.classList.toggle("active", triageStatus === "hidden");
}

async function setTriageFromModal(asset, status) {
  const newStatus = asset.triage_status === status ? null : status;
  try {
    await api(`/api/assets/${encodeURIComponent(asset.id)}/triage`, {
      method: "POST",
      body: JSON.stringify({ status: newStatus }),
    });
    asset.triage_status = newStatus;
    updateModalTriageButtons(newStatus);
    // Update keeper star in modal title
    const keeperStar = $("#modalKeeperStar");
    if (keeperStar) keeperStar.hidden = newStatus !== "keeper";
    // Update badge on card
    const card = $(`[data-id="${asset.id}"]`);
    if (card) {
      const oldBadge = card.querySelector(".triage-badge");
      if (oldBadge) oldBadge.remove();
      if (newStatus === "keeper") {
        const badge = document.createElement("span");
        badge.className = "triage-badge keeper";
        badge.title = "Keeper";
        card.querySelector(".card-image").prepend(badge);
      } else if (newStatus === "hidden") {
        const badge = document.createElement("span");
        badge.className = "triage-badge hidden-status";
        badge.title = "Hidden";
        card.querySelector(".card-image").prepend(badge);
      }
    }
    const msg = newStatus === "keeper" ? "Marked as keeper" : newStatus === "hidden" ? "Hidden" : "Reset to pending";
    Shared.showToast(msg, { type: "success" });
    // Refresh tree counts (they depend on hidden status)
    loadCatalogTree();
    if (isOwner()) loadHiddenTree();
  } catch (e) {
    Shared.showToast(`Failed: ${formatApiError(e)}`, { type: "error" });
  }
}

function closeModal() {
  $("#modal").classList.add("hidden");
  state.modalAsset = null;
  state.annotations = [];
  const img = $("#modalImage");
  if (img) img.style.display = "block";
}

async function _navModalScan(delta) {
  if (!state.modalScanPages) return;
  const newIdx = Math.max(0, Math.min(state.modalScanPages.length - 1, state.modalScanPageIndex + delta));
  if (newIdx === state.modalScanPageIndex) return;
  state.modalScanPageIndex = newIdx;
  const siblingId = state.modalScanPages[newIdx];
  const curAsset = state.modalAsset;
  const siblingSourceRef = (curAsset.source_ref || "").replace(/#p\d+$/, "") + `#p${newIdx + 1}`;
  state.modalAsset = { ...curAsset, id: siblingId, source_ref: siblingSourceRef };
  const modalImage = $("#modalImage");
  if (modalImage) modalImage.src = `/media/${siblingId}?kind=thumb`;
  const indicator = document.querySelector(".modalScanIndicator");
  if (indicator) indicator.textContent = `Page ${newIdx + 1} of ${state.modalScanPages.length}`;
  const prevBtn = document.querySelector(".modalScanPrev");
  const nextBtn = document.querySelector(".modalScanNext");
  if (prevBtn) prevBtn.disabled = newIdx === 0;
  if (nextBtn) nextBtn.disabled = newIdx === state.modalScanPages.length - 1;
  const sourceLink = $("#sourceLink");
  const pdfUrl = `/media/${siblingId}?kind=pdf#page=${newIdx + 1}`;
  if (sourceLink) { sourceLink.href = pdfUrl; sourceLink.textContent = "Open PDF"; }
  await loadAnnotations(siblingId);
  renderAnnotations();
  renderMarkers();
}

// ─── Notes / annotations ────────────────────────────────────────────────────────

function scheduleNotesUpdate(assetId, value) {
  clearTimeout(state.noteTimers[assetId]);
  state.noteTimers[assetId] = setTimeout(async () => {
    try {
      await api(`/api/assets/${encodeURIComponent(assetId)}`, {
        method: "PUT",
        body: JSON.stringify({ notes: value }),
      });
    } catch {}
  }, 800);
}

async function loadAnnotations(assetId) {
  try {
    const data = await api(`/api/annotations?asset_id=${encodeURIComponent(assetId)}`);
    state.annotations = data.annotations || [];
  } catch { state.annotations = []; }
}

function renderAnnotations() {
  const wrap = $("#annList");
  if (!wrap) return;
  wrap.innerHTML = "";
  state.annotations.forEach((ann, idx) => {
    const isQuestion = ann.annotation_type === "question";
    const isResolved = isQuestion && ann.resolved;
    const el = document.createElement("div");
    el.className = `listItem annItem${state.activeAnnotationId === ann.id ? " active" : ""}${isQuestion ? " ann-question" : ""}${isResolved ? " ann-resolved" : ""}`;

    const marker = isQuestion ? "?" : `#${idx + 1}`;
    const actorLabel = ann.actor_name ? `<span class="ann-actor">${escapeHtml(ann.actor_name)}</span>` : "";
    const resolveBtn = isQuestion && state.actor && state.actor.role === "owner"
      ? `<button class="iconBtn ann-resolve" data-resolve="${ann.id}" title="${isResolved ? "Unresolve" : "Resolve"}" type="button">${isResolved ? "&#9745;" : "&#9744;"}</button>`
      : "";

    el.innerHTML = `
      <div class="annHeader">
        <strong>${marker}</strong>${actorLabel}${resolveBtn}
        <button class="iconBtn danger" data-del="${ann.id}" type="button">\u00d7</button>
      </div>
      <textarea data-ann="${ann.id}">${escapeHtml(ann.text || "")}</textarea>
    `;
    el.onclick = () => setActiveAnnotation(ann.id);
    const ta = el.querySelector("textarea");
    ta.addEventListener("input", async () => {
      ann.text = ta.value;
      syncFloatingText(ann.id, ta.value);
      scheduleAnnotationUpdate(ann.id, { text: ta.value });
    });
    el.querySelector("[data-del]").onclick = async (e) => {
      e.stopPropagation();
      await deleteAnnotationWithUndo(ann);
    };
    const resolveEl = el.querySelector("[data-resolve]");
    if (resolveEl) {
      resolveEl.onclick = async (e) => {
        e.stopPropagation();
        const newVal = ann.resolved ? 0 : 1;
        try {
          await api(`/api/annotations/${ann.id}`, { method: "PUT", body: JSON.stringify({ resolved: newVal }) });
          ann.resolved = newVal;
          renderAnnotations();
          renderMarkers();
        } catch (err) {
          Shared.showToast(`Failed to update: ${formatApiError(err)}`, { type: "error" });
        }
      };
    }
    wrap.appendChild(el);
  });
}

function scheduleAnnotationUpdate(annId, patch) {
  clearTimeout(state.noteTimers[`ann_${annId}`]);
  state.noteTimers[`ann_${annId}`] = setTimeout(async () => {
    try {
      await api(`/api/annotations/${annId}`, { method: "PUT", body: JSON.stringify(patch) });
    } catch (e) {
      console.error("Annotation save failed:", e);
      Shared.showToast("Annotation save failed — will retry on next edit", { type: "error" });
    }
  }, 600);
}

function setActiveAnnotation(annId) {
  state.activeAnnotationId = annId;
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
}

function syncFloatingText(annId, value) {
  if (state.activeAnnotationId !== annId) return;
  const ft = $("#floatingText");
  if (ft && ft.value !== value) ft.value = value;
}

function renderFloatingNote() {
  const note = $("#floatingNote");
  const ft = $("#floatingText");
  if (!note || !ft) return;
  const ann = state.annotations.find((a) => a.id === state.activeAnnotationId);
  if (!ann) { note.classList.add("hidden"); return; }
  const pt = normalizedToStagePoint(ann.x, ann.y);
  note.style.left = `${pt.left + 16}px`;
  note.style.top = `${pt.top}px`;
  note.classList.remove("hidden");
  ft.value = ann.text || "";
}

async function deleteAnnotationWithUndo(ann) {
  const { id, x, y, text } = ann;
  const assetId = state.modalAsset?.id;
  await api(`/api/annotations/${id}`, { method: "DELETE" });
  state.annotations = state.annotations.filter((a) => a.id !== id);
  if (state.activeAnnotationId === id) state.activeAnnotationId = null;
  renderAnnotations(); renderMarkers(); renderFloatingNote();
  Shared.showToast("Annotation deleted", {
    type: "info", actionLabel: "Undo",
    onAction: async () => {
      if (!assetId) return;
      const res = await api("/api/annotations", { method: "POST", body: JSON.stringify({ asset_id: assetId, x, y, text: text || "" }) });
      state.annotations.push(res.annotation);
      renderAnnotations(); renderMarkers(); renderFloatingNote();
    },
  });
}

function modalImageGeometry() {
  const stage = $("#imageStage");
  const img = $("#modalImage");
  const stageRect = stage.getBoundingClientRect();
  const { width: sw, height: sh } = stageRect;
  if (!img || img.style.display === "none" || !img.naturalWidth || !img.naturalHeight || sw <= 0 || sh <= 0) {
    return { stageRect, left: 0, top: 0, width: sw, height: sh };
  }
  const scale = Math.min(sw / img.naturalWidth, sh / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  return { stageRect, left: (sw - width) / 2, top: (sh - height) / 2, width, height };
}

function stagePointToNormalized(clientX, clientY, clamp = false) {
  const geo = modalImageGeometry();
  if (geo.width <= 0 || geo.height <= 0) return null;
  let x = (clientX - geo.stageRect.left - geo.left) / geo.width;
  let y = (clientY - geo.stageRect.top - geo.top) / geo.height;
  if (clamp) { x = Math.max(0, Math.min(1, x)); y = Math.max(0, Math.min(1, y)); return { x, y, geo }; }
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x, y, geo };
}

function normalizedToStagePoint(x, y) {
  const geo = modalImageGeometry();
  return { left: geo.left + x * geo.width, top: geo.top + y * geo.height, geo };
}

const _markerColors = ["#6F5AA8","#c4787a","#7a9b8a","#b8860b","#5a8fc4"];
function markerColor(idx) { return _markerColors[idx % _markerColors.length]; }

function renderMarkers() {
  $$(".marker").forEach((m) => m.remove());
  const stage = $("#imageStage");
  if (!stage) return;
  state.annotations.forEach((ann, idx) => {
    const isQuestion = ann.annotation_type === "question";
    const isResolved = isQuestion && ann.resolved;
    const m = document.createElement("div");
    m.className = `marker${isQuestion ? " marker-question" : ""}${isResolved ? " marker-resolved" : ""}`;
    const pt = normalizedToStagePoint(ann.x, ann.y);
    m.style.left = `${pt.left}px`;
    m.style.top = `${pt.top}px`;
    m.dataset.id = ann.id;
    m.style.background = isQuestion ? "#e67e22" : markerColor(idx);
    const markerLabel = isQuestion ? "?" : `${idx + 1}`;
    m.innerHTML = `
      <span style="color:#F2F2F6">${markerLabel}</span>
      <div class="badgeIcons">
        <button class="ok" data-ok="${ann.id}" aria-label="Done" type="button">
          <svg viewBox="0 0 16 16" width="12" height="12"><path d="M3.2 8.4l2.3 2.3L12.8 3.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <button class="del" data-del="${ann.id}" aria-label="Delete" type="button">
          <svg viewBox="0 0 16 16" width="12" height="12"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        </button>
      </div>
    `;
    m.onpointerdown = (e) => {
      if (e.target.closest(".badgeIcons")) return;
      e.stopPropagation();
      m.setPointerCapture(e.pointerId);
      state.dragging = { id: ann.id, pointerId: e.pointerId, moved: false };
    };
    m.onclick = (e) => { e.stopPropagation(); setActiveAnnotation(ann.id); };
    if (state.activeAnnotationId === ann.id) m.classList.add("active");
    m.querySelector("[data-ok]").onclick = (e) => { e.stopPropagation(); state.activeAnnotationId = null; renderAnnotations(); renderMarkers(); renderFloatingNote(); };
    m.querySelector("[data-del]").onclick = async (e) => { e.stopPropagation(); await deleteAnnotationWithUndo(ann); };
    stage.appendChild(m);
  });
}

// Image stage event listeners for annotation creation/drag
const imageStageEl = document.getElementById("imageStage");
if (imageStageEl) {
  imageStageEl.addEventListener("click", async (e) => {
    if (!state.modalAsset) return;
    if (e.target.closest(".marker") || e.target.closest(".floatingNote")) return;
    const point = stagePointToNormalized(e.clientX, e.clientY);
    if (!point) return;
    // Check if "question mode" toggle is active
    const qToggle = $("#annQuestionToggle");
    const annotation_type = qToggle && qToggle.checked ? "question" : "note";
    const res = await api("/api/annotations", {
      method: "POST",
      body: JSON.stringify({ asset_id: state.modalAsset.id, x: point.x, y: point.y, text: "", annotation_type }),
    });
    state.annotations.push(res.annotation);
    state.activeAnnotationId = res.annotation.id;
    renderAnnotations(); renderMarkers(); renderFloatingNote();
  });

  imageStageEl.addEventListener("pointermove", async (e) => {
    if (!state.dragging) return;
    const point = stagePointToNormalized(e.clientX, e.clientY, true);
    if (!point) return;
    const ann = state.annotations.find((a) => a.id === state.dragging.id);
    if (!ann) return;
    ann.x = point.x; ann.y = point.y;
    state.dragging.moved = true;
    renderMarkers(); renderFloatingNote();
  });

  imageStageEl.addEventListener("pointerup", async () => {
    if (!state.dragging) return;
    const ann = state.annotations.find((a) => a.id === state.dragging.id);
    if (ann) {
      await api(`/api/annotations/${ann.id}`, { method: "PUT", body: JSON.stringify({ x: ann.x, y: ann.y }) });
    }
    state.dragging = null;
  });
}

// Modal close wiring
const closeModalBtn = $("#closeModal");
if (closeModalBtn) closeModalBtn.onclick = closeModal;
const modalEl = $("#modal");
if (modalEl) modalEl.onclick = (e) => { if (e.target.id === "modal") closeModal(); };

// ─── Print ──────────────────────────────────────────────────────────────────────

function printModalAsset(asset) {
  const url = asset.stored_path ? `/media/${asset.id}?kind=original` : asset.image_url || "";
  if (!url) return;
  const win = window.open("", "_blank");
  win.document.write(`<!doctype html><html><body style="margin:0"><img src="${escapeHtml(url)}" style="max-width:100%" /></body></html>`);
  win.document.close();
  win.onload = () => { win.print(); };
}

// ─── Review mode ────────────────────────────────────────────────────────────────

function enterReview() {
  if (!state.assets.length) {
    Shared.showToast("No items to review.", { type: "info" });
    return;
  }
  state.view = "review";
  state.reviewItems = [...state.assets];
  state.reviewIndex = 0;
  state.reviewHistory = [];
  state.reviewSkipped = 0;
  state.reviewKept = 0;
  state.reviewHidden = 0;

  const browseView = $("#browseView");
  const reviewView = $("#reviewView");
  const reviewComplete = $("#reviewComplete");
  const reviewCard = $("#reviewCard");
  if (browseView) browseView.hidden = true;
  if (reviewView) reviewView.hidden = false;
  if (reviewComplete) reviewComplete.hidden = true;
  if (reviewCard) reviewCard.hidden = false;

  // Update back button label based on whether we came from canvas review
  const backBtn = $("#reviewBack");
  if (backBtn) backBtn.textContent = state.canvasReview ? "← Back to grid" : "← Back to browsing";

  // Hide canvas action bar while in one-by-one (it'll come back when we return to grid)
  const actionBar = $("#canvasActionBar");
  if (actionBar) actionBar.hidden = true;

  renderReviewCard();
}

function exitReview() {
  state.view = "browse";
  const browseView = $("#browseView");
  const reviewView = $("#reviewView");
  if (browseView) browseView.hidden = false;
  if (reviewView) reviewView.hidden = true;

  if (state.canvasReview) {
    // Return to canvas review grid — re-show action bar, keep review state
    const actionBar = $("#canvasActionBar");
    if (actionBar) actionBar.hidden = false;
    loadAssets();
  } else {
    loadAssets();
  }
}

function renderReviewCard() {
  const item = state.reviewItems[state.reviewIndex];
  if (!item) return;

  const total = state.reviewItems.length;
  const counter = $("#reviewCounter");
  const progressBar = $("#reviewProgressBar");
  if (counter) counter.textContent = `${state.reviewIndex + 1} of ${total}`;
  if (progressBar) progressBar.style.width = `${((state.reviewIndex) / total) * 100}%`;

  const img = $("#reviewImg");
  if (img) {
    const url = item.thumb_path ? `/media/${item.id}?kind=original`
                : item.stored_path ? `/media/${item.id}?kind=original`
                : item.image_url || "";
    img.src = url;
    img.alt = displayTitle(item);
  }

  const titleEl = $("#reviewTitle");
  if (titleEl) {
    const keeperPrefix = item.triage_status === "keeper" ? "★ " : "";
    titleEl.textContent = keeperPrefix + displayTitle(item);
    titleEl.style.color = item.triage_status === "keeper" ? "#b8860b" : "";
  }

  const metaEl = $("#reviewMeta");
  if (metaEl) {
    const parts = [];
    if (item.board) parts.push(item.board);
    parts.push(item.source || "");
    metaEl.textContent = parts.filter(Boolean).join(" · ");
  }

  const descEl = $("#reviewDesc");
  if (descEl) descEl.textContent = item.seo_alt_text || item.ai_summary || item.description || "";

  const link = $("#reviewSourceLink");
  if (link) {
    const ref = item.source_ref || "";
    link.href = ref || "#";
    link.hidden = !ref;
    link.textContent = ref ? `View on ${item.source || "source"} ↗` : "";
  }

  // Reset checkbox
  const cb = $("#commentLater");
  if (cb) cb.checked = false;

  // Update undo button
  const undoBtn = $("#reviewUndo");
  if (undoBtn) undoBtn.disabled = state.reviewHistory.length === 0;
}

async function reviewAction(action) {
  const item = state.reviewItems[state.reviewIndex];
  if (!item) return;

  // Save undo entry
  state.reviewHistory.push({
    id: item.id,
    index: state.reviewIndex,
    previousStatus: item.triage_status || null,
    previousAnnotation: item.needs_annotation || 0,
    action,
  });

  if (action === "keep") {
    const commentLater = document.getElementById("commentLater")?.checked || false;
    try {
      await api(`/api/assets/${encodeURIComponent(item.id)}/triage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "keeper", needs_annotation: commentLater ? 1 : 0 }),
      });
      item.triage_status = "keeper";
      item.needs_annotation = commentLater ? 1 : 0;
    } catch (e) {
      Shared.showToast(`Failed to save: ${formatApiError(e)}`, { type: "error" });
    }
    state.reviewKept++;
  } else if (action === "hide") {
    try {
      await api(`/api/assets/${encodeURIComponent(item.id)}/triage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "hidden" }),
      });
      item.triage_status = "hidden";
    } catch (e) {
      Shared.showToast(`Failed to save: ${formatApiError(e)}`, { type: "error" });
    }
    state.reviewHidden++;
  } else {
    // skip — no API call
    state.reviewSkipped++;
  }

  state.reviewIndex++;
  if (state.reviewIndex >= state.reviewItems.length) {
    showReviewComplete();
    return;
  }
  renderReviewCard();
}

async function undoReview() {
  const last = state.reviewHistory.pop();
  if (!last) return;

  // Revert counts
  if (last.action === "keep") state.reviewKept = Math.max(0, state.reviewKept - 1);
  else if (last.action === "hide") state.reviewHidden = Math.max(0, state.reviewHidden - 1);
  else state.reviewSkipped = Math.max(0, state.reviewSkipped - 1);

  // Restore API
  try {
    await api(`/api/assets/${encodeURIComponent(last.id)}/triage`, {
      method: "POST",
      body: JSON.stringify({ status: last.previousStatus, needs_annotation: last.previousAnnotation }),
    });
    const item = state.reviewItems.find((i) => i.id === last.id);
    if (item) { item.triage_status = last.previousStatus; item.needs_annotation = last.previousAnnotation; }
  } catch (e) {
    Shared.showToast(`Undo failed: ${formatApiError(e)}`, { type: "error" });
  }

  state.reviewIndex = last.index;

  // If review was completed, show card again
  const reviewComplete = $("#reviewComplete");
  const reviewCard = $("#reviewCard");
  if (reviewComplete) reviewComplete.hidden = true;
  if (reviewCard) reviewCard.hidden = false;

  renderReviewCard();
}

function showReviewComplete() {
  const reviewCard = $("#reviewCard");
  const reviewActions = document.querySelector(".review-actions");
  const reviewUndoBtn = $("#reviewUndo");
  const reviewComplete = $("#reviewComplete");

  if (reviewCard) reviewCard.hidden = true;
  if (reviewActions) reviewActions.style.display = "none";
  if (reviewUndoBtn) reviewUndoBtn.hidden = true;
  if (reviewComplete) {
    reviewComplete.hidden = false;
    const desc = $("#reviewCompleteDesc");
    const total = state.reviewItems.length;
    if (desc) desc.textContent = `You reviewed ${total} item${total === 1 ? "" : "s"}.`;
    const statsEl = $("#reviewCompleteStats");
    if (statsEl) {
      statsEl.innerHTML = `
        <span class="review-stat keeper">${state.reviewKept} keepers</span>
        <span class="review-stat hidden-s">${state.reviewHidden} hidden</span>
        <span class="review-stat skipped">${state.reviewSkipped} skipped</span>
      `;
    }
    const progressBar = $("#reviewProgressBar");
    if (progressBar) progressBar.style.width = "100%";
    const counter = $("#reviewCounter");
    if (counter) counter.textContent = `${total} of ${total}`;
  }
}

// ─── Canvas Review Mode ──────────────────────────────────────────────────────

function enterCanvasReview() {
  if (!state.assets.length) {
    Shared.showToast("No items to review.", { type: "info" });
    return;
  }
  state.canvasReview = true;
  state.canvasSelected.clear();

  const browseView = $("#browseView");
  if (browseView) browseView.classList.add("canvas-review-active");

  const actionBar = $("#canvasActionBar");
  if (actionBar) actionBar.hidden = false;

  // Highlight grid button to indicate active review
  const gridBtn = $("#viewGrid");
  if (gridBtn) gridBtn.classList.add("reviewing");

  updateCanvasSelectionCount();
  Shared.showToast("Review mode — click cards to select, then act on selection.", { type: "info" });
}

function exitCanvasReview() {
  state.canvasReview = false;
  state.canvasSelected.clear();

  const browseView = $("#browseView");
  if (browseView) browseView.classList.remove("canvas-review-active");

  const actionBar = $("#canvasActionBar");
  if (actionBar) actionBar.hidden = true;

  // Remove review highlight from grid button
  const gridBtn = $("#viewGrid");
  if (gridBtn) gridBtn.classList.remove("reviewing");

  $$(".card.canvas-selected").forEach((c) => c.classList.remove("canvas-selected"));
}

function toggleCanvasSelection(id, cardEl) {
  if (state.canvasSelected.has(id)) {
    state.canvasSelected.delete(id);
    if (cardEl) cardEl.classList.remove("canvas-selected");
  } else {
    state.canvasSelected.add(id);
    if (cardEl) cardEl.classList.add("canvas-selected");
  }
  updateCanvasSelectionCount();
}

function selectAllCanvas() {
  state.assets.forEach((a) => state.canvasSelected.add(a.id));
  $$(".card").forEach((c) => {
    const id = c.dataset.id;
    if (id && state.canvasSelected.has(id)) c.classList.add("canvas-selected");
  });
  updateCanvasSelectionCount();
}

function clearCanvasSelection() {
  state.canvasSelected.clear();
  $$(".card.canvas-selected").forEach((c) => c.classList.remove("canvas-selected"));
  updateCanvasSelectionCount();
}

function updateCanvasSelectionCount() {
  const count = state.canvasSelected.size;
  const el = $("#canvasSelectionCount");
  if (el) el.textContent = `${count} selected`;
  const hasSelection = count > 0;
  ["#canvasKeep", "#canvasHide", "#canvasFlag"].forEach((sel) => {
    const btn = $(sel);
    if (btn) btn.disabled = !hasSelection;
  });
}

async function canvasBulkKeep() {
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  try {
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status: "keeper" }),
    });
    ids.forEach((id) => {
      const a = state.assets.find((x) => x.id === id);
      if (a) a.triage_status = "keeper";
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} marked as keepers.`, { type: "success" });
    clearCanvasSelection();
    renderGrid();
  } catch (e) {
    Shared.showToast(`Bulk keep failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkHide() {
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  try {
    await api("/api/assets/triage/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, status: "hidden" }),
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} hidden.`, { type: "success" });
    clearCanvasSelection();
    await loadAssets();
  } catch (e) {
    Shared.showToast(`Bulk hide failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function canvasBulkFlag() {
  const ids = Array.from(state.canvasSelected);
  if (!ids.length) return;
  try {
    await api("/api/assets/flag/bulk", {
      method: "POST",
      body: JSON.stringify({ ids, flagged: 1 }),
    });
    ids.forEach((id) => {
      const a = state.assets.find((x) => x.id === id);
      if (a) a.flagged = 1;
    });
    Shared.showToast(`${ids.length} item${ids.length === 1 ? "" : "s"} flagged for review.`, { type: "success" });
    clearCanvasSelection();
    renderGrid();
  } catch (e) {
    Shared.showToast(`Bulk flag failed: ${formatApiError(e)}`, { type: "error" });
  }
}

// Canvas review action bar wiring
const canvasKeepBtn = $("#canvasKeep");
if (canvasKeepBtn) canvasKeepBtn.addEventListener("click", canvasBulkKeep);
const canvasHideBtn = $("#canvasHide");
if (canvasHideBtn) canvasHideBtn.addEventListener("click", canvasBulkHide);
const canvasFlagBtn = $("#canvasFlag");
if (canvasFlagBtn) canvasFlagBtn.addEventListener("click", canvasBulkFlag);
const canvasClearBtn = $("#canvasClear");
if (canvasClearBtn) canvasClearBtn.addEventListener("click", clearCanvasSelection);
const canvasToOneByOneBtn = $("#canvasToOneByOne");
if (canvasToOneByOneBtn) canvasToOneByOneBtn.addEventListener("click", () => {
  exitCanvasReview();
  enterReview();
});
const canvasExitReviewBtn = $("#canvasExitReview");
if (canvasExitReviewBtn) canvasExitReviewBtn.addEventListener("click", exitCanvasReview);

// Review button — canvas review is the default
const reviewBtn = $("#reviewBtn");
if (reviewBtn) reviewBtn.addEventListener("click", enterCanvasReview);

const reviewBackBtn = $("#reviewBack");
if (reviewBackBtn) reviewBackBtn.addEventListener("click", exitReview);

const reviewHideBtn = $("#reviewHideBtn");
if (reviewHideBtn) reviewHideBtn.addEventListener("click", () => reviewAction("hide"));

const reviewSkipBtn = $("#reviewSkipBtn");
if (reviewSkipBtn) reviewSkipBtn.addEventListener("click", () => reviewAction("skip"));

const reviewKeepBtn = $("#reviewKeepBtn");
if (reviewKeepBtn) reviewKeepBtn.addEventListener("click", () => reviewAction("keep"));

const reviewUndoBtn = $("#reviewUndo");
if (reviewUndoBtn) reviewUndoBtn.addEventListener("click", undoReview);

const reviewExitBtn = $("#reviewExitBtn");
if (reviewExitBtn) reviewExitBtn.addEventListener("click", exitReview);

const reviewSkippedBtn = $("#reviewSkippedBtn");
if (reviewSkippedBtn) reviewSkippedBtn.addEventListener("click", () => {
  // Restart with skipped items (those that were "skip" actioned)
  const skipped = state.reviewItems.filter((item) => {
    const histEntry = state.reviewHistory.find((h) => h.id === item.id);
    return !histEntry || histEntry.action === "skip";
  });
  if (!skipped.length) { Shared.showToast("No skipped items.", { type: "info" }); return; }
  state.reviewItems = skipped;
  state.reviewIndex = 0;
  state.reviewHistory = [];
  state.reviewKept = 0;
  state.reviewHidden = 0;
  state.reviewSkipped = 0;
  const reviewComplete = $("#reviewComplete");
  const reviewCard = $("#reviewCard");
  const reviewActions = document.querySelector(".review-actions");
  const reviewUndoBtnEl = $("#reviewUndo");
  if (reviewComplete) reviewComplete.hidden = true;
  if (reviewCard) reviewCard.hidden = false;
  if (reviewActions) reviewActions.style.display = "";
  if (reviewUndoBtnEl) reviewUndoBtnEl.hidden = false;
  renderReviewCard();
});

// ─── Keyboard shortcuts ──────────────────────────────────────────────────────────

window.addEventListener("keydown", (e) => {
  // Close modal with Escape
  if (e.key === "Escape") {
    if (!$("#modal").classList.contains("hidden")) { closeModal(); return; }
    if (!$("#scanImportModal").classList.contains("hidden") && !state.scanImportBusy) { closeScanImportModal(); return; }
    if (!$("#photoImportModal").classList.contains("hidden") && !state.photoImportBusy) { closePhotoImportModal(); return; }
    if (state.canvasReview) { exitCanvasReview(); return; }
    if (state.view === "review") { exitReview(); return; }
    return;
  }

  // Canvas review shortcuts
  if (state.canvasReview) {
    const tag = (e.target && e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (!$("#modal").classList.contains("hidden")) return;
    if ((e.ctrlKey || e.metaKey) && e.key === "a") {
      e.preventDefault();
      selectAllCanvas();
    }
    return;
  }

  // One-by-one review mode shortcuts (only when review is active and no modal/input focused)
  if (state.view !== "review") return;
  const tag = (e.target && e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  if (!$("#modal").classList.contains("hidden")) return;

  switch (e.key) {
    case "ArrowRight":
    case "k":
    case "K":
      e.preventDefault();
      reviewAction("keep");
      break;
    case "ArrowLeft":
    case "s":
    case "S":
      e.preventDefault();
      reviewAction("hide");
      break;
    case "ArrowDown":
    case " ":
      e.preventDefault();
      reviewAction("skip");
      break;
    case "z":
    case "Z":
      e.preventDefault();
      undoReview();
      break;
    case "c":
    case "C": {
      e.preventDefault();
      const cb = $("#commentLater");
      if (cb) cb.checked = !cb.checked;
      break;
    }
  }
});

// ─── Chat bar ────────────────────────────────────────────────────────────────────

function showChatSpinner(text) {
  const bar = $("#chatResponse");
  if (!bar) return;
  clearTimeout(addChatResponse._timer);
  bar.innerHTML = `<span class="chat-spinner"></span>${escapeHtml(text || "Thinking…")}`;
  bar.hidden = false;
}

function hideChatSpinner() {
  const bar = $("#chatResponse");
  if (!bar) return;
  clearTimeout(addChatResponse._timer);
  bar.hidden = true;
  bar.innerHTML = "";
}

function addChatResponse(text, duration) {
  const bar = $("#chatResponse");
  if (!bar) return;
  bar.innerHTML = "";
  bar.textContent = text;
  bar.hidden = false;
  clearTimeout(addChatResponse._timer);
  addChatResponse._timer = setTimeout(() => { if (bar) bar.hidden = true; }, duration || 6000);
}

// Extract meaningful keywords from a chat message for text-search fallback.
const _CHAT_STOP_WORDS = new Set([
  "show", "me", "find", "get", "display", "list", "search", "look", "give",
  "make", "create", "do", "see", "open", "go", "browse", "view", "let",
  "for", "some", "all", "the", "a", "an", "with", "in", "of", "and",
  "or", "that", "have", "has", "are", "is", "it", "to", "my", "its",
  "please", "can", "you", "could", "would", "want", "need", "like",
  "i", "items", "things", "images", "photos", "pictures", "inspirations",
  "inspiration", "ideas", "try", "just",
]);
function _chatKeywords(text) {
  return text.toLowerCase().split(/\s+/)
    .filter((w) => w.length > 1 && !_CHAT_STOP_WORDS.has(w))
    .join(" ");
}

async function processChat(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return;

  showChatSpinner("Thinking\u2026");

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: trimmed }),
    });

    const action = data.action || "message";
    const params = data.params || {};
    const message = data.message || "";
    const routingMessage = data.routing_message || "";

    // Show routing acknowledgment while grid loads
    if (routingMessage && action !== "message") {
      showChatSpinner(routingMessage);
    }

    // Persist the prompt for any action that changes the visible results
    if (action !== "message") {
      state.chatPrompt = trimmed;
    }

    await executeChatAction(action, params);

    hideChatSpinner();

    if (message) {
      addChatResponse(message, action === "message" ? 12000 : 6000);
    }
  } catch (e) {
    hideChatSpinner();
    const errMsg = formatApiError(e);
    if (errMsg.includes("ANTHROPIC_API_KEY") || errMsg.includes("Anthropic")) {
      // AI chat unavailable — fall back to text search using extracted keywords
      const keywords = _chatKeywords(trimmed) || trimmed;
      state.chatPrompt = trimmed;
      state.q = keywords;
      loadAssets();
      addChatResponse(`Filtering by "${keywords}" (AI chat unavailable without API key)`, 8000);
    } else {
      addChatResponse(`Chat error: ${errMsg}`, 8000);
    }
  }
}

async function executeChatAction(action, params) {
  switch (action) {
    case "show_items": {
      // Fetch specific items by ID prefix and display
      const ids = (params.ids || []).join(",");
      if (!ids) break;
      try {
        // Clear any stale filter state so the indicator reflects the chat result
        state.q = "";
        state.currentSource = null;
        state.currentBoard = null;
        clearCollectionFilter();
        clearCatalogFilter();
        state.currentTreeNodeId = null;
        state.triageFilter = "";
        const data = await api(`/api/assets?ids=${encodeURIComponent(ids)}&include_hidden=1&limit=200`);
        state.assets = data.assets || [];
        state.hasMore = false;
        state.offset = state.assets.length;
        // Store curated IDs so the explorer can highlight just these
        state.chatItemIds = state.assets.map((a) => a.id);
        renderGrid();
        updateStats();
        updateLoadMoreBtn();
        updateFilterIndicator();
        syncExplorerFilter();
      } catch (e) {
        addChatResponse(`Failed to load items: ${formatApiError(e)}`, 8000);
      }
      break;
    }
    case "show_sidebar": {
      const type = params.type || "";
      if (type === "collections") {
        await loadCollections();
        const visible = state.collections.filter((c) => (c.name || "").toLowerCase() !== "hidden");
        showDynamicSidebar("Collections", visible.map((c) => ({
          label: c.name,
          count: c.count || 0,
          onclick: () => { setCollectionFilter(c.id); hideDynamicSidebar(); },
        })));
      } else if (type === "boards") {
        const sourceFilter = (params.source || "").toLowerCase();
        // Build board list from catalog tree
        const boards = [];
        for (const node of (state.catalogTree || [])) {
          if (node.type !== "source") continue;
          if (sourceFilter && node.label.toLowerCase() !== sourceFilter) continue;
          for (const child of (node.children || [])) {
            boards.push({
              label: `${child.label} (${node.label})`,
              count: child.count,
              onclick: () => {
                const boardDbName = child.board_name || "";
                const isCatchAll = boardDbName.startsWith("(");
                if (isCatchAll && child.file) {
                  state.currentSource = null;
                  state.currentBoard = null;
                  clearCollectionFilter();
                  setCatalogFilter([child.file], { label: child.label, nodeId: null });
                } else {
                  state.currentSource = node.label.toLowerCase();
                  state.currentBoard = boardDbName || child.label;
                  clearCollectionFilter();
                  clearCatalogFilter();
                }
                state.currentTreeNodeId = null;
                state.offset = 0;
                renderCatalogTree();
                loadAssets();
                hideDynamicSidebar();
              },
            });
          }
        }
        showDynamicSidebar(sourceFilter ? `${sourceFilter} Boards` : "All Boards", boards);
      } else if (type === "sources") {
        const sources = (state.catalogTree || [])
          .filter((n) => n.type === "source")
          .map((n) => ({
            label: n.label,
            count: n.count,
            onclick: () => {
              state.currentSource = n.label.toLowerCase();
              state.currentBoard = null;
              clearCollectionFilter();
              clearCatalogFilter();
              state.currentTreeNodeId = null;
              state.offset = 0;
              renderCatalogTree();
              loadAssets();
              hideDynamicSidebar();
            },
          }));
        showDynamicSidebar("Sources", sources);
      }
      break;
    }
    case "filter": {
      state.chatItemIds = null;
      state.currentTreeNodeId = null;
      if (params.source !== undefined) {
        state.currentSource = params.source || null;
        if (params.source) {
          clearCatalogFilter();
          if (!params.board) clearCollectionFilter();
        }
      }
      if (params.board !== undefined) {
        state.currentBoard = params.board || null;
        if (params.board) {
          clearCollectionFilter();
          clearCatalogFilter();
        }
      }
      if (params.triage_status !== undefined) {
        state.triageFilter = params.triage_status || "";
        $$("[data-triage]").forEach((c) => {
          c.classList.toggle("active", c.dataset.triage === (params.triage_status || ""));
        });
      }
      if (params.q !== undefined) {
        state.q = params.q || "";
      }
      if (params.collection_id !== undefined) {
        if (params.collection_id) {
          state.currentSource = null;
          state.currentBoard = null;
          clearCatalogFilter();
          const col = state.collections.find((c) => c.id === params.collection_id);
          setCollectionFilterIds([params.collection_id], { label: col ? col.name : "", nodeId: null });
        } else {
          clearCollectionFilter();
        }
      }
      renderCatalogTree();
      await loadAssets();
      break;
    }
    case "search": {
      state.chatItemIds = null;
      state.q = params.q || "";
      await loadAssets();
      break;
    }
    case "semantic_search": {
      state.chatItemIds = null;
      state.q = `sem:${params.q || ""}`;
      await loadAssets();
      break;
    }
    case "create_collection": {
      if (params.name) {
        try {
          await api("/api/collections", {
            method: "POST",
            body: JSON.stringify({ name: params.name }),
          });
          await loadCollections();
          await loadCatalogTree();
        } catch (e) {
          addChatResponse(`Couldn't create collection: ${formatApiError(e)}`, 8000);
        }
      }
      break;
    }
    case "show_collection": {
      const name = (params.name || "").toLowerCase();
      const col = state.collections.find(
        (c) => c.name.toLowerCase() === name || c.name.toLowerCase().includes(name)
      );
      if (col) {
        setCollectionFilter(col.id);
      } else if (params.collection_id) {
        setCollectionFilter(params.collection_id);
      }
      break;
    }
    case "enter_review": {
      enterCanvasReview();
      break;
    }
    case "clear_filters": {
      state.currentSource = null;
      state.currentBoard = null;
      clearCollectionFilter();
      clearCatalogFilter();
      state.currentTreeNodeId = null;
      state.triageFilter = "";
      state.q = "";
      $$("[data-triage]").forEach((c) => {
        c.classList.toggle("active", c.dataset.triage === "");
      });
      renderCatalogTree();
      await loadAssets();
      break;
    }
    case "bulk_triage": {
      const status = params.status || null;
      // In canvas review with selection, act on selected items; otherwise all visible
      const ids = (state.canvasReview && state.canvasSelected.size > 0)
        ? Array.from(state.canvasSelected)
        : state.assets.map((a) => a.id);
      if (!ids.length) {
        addChatResponse("No items visible to triage.", 6000);
        break;
      }
      try {
        await api("/api/assets/triage/bulk", {
          method: "POST",
          body: JSON.stringify({ ids, status }),
        });
        if (state.canvasReview) clearCanvasSelection();
        await loadAssets();
      } catch (e) {
        addChatResponse(`Bulk triage failed: ${formatApiError(e)}`, 8000);
      }
      break;
    }
    case "bulk_flag": {
      const ids = (state.canvasReview && state.canvasSelected.size > 0)
        ? Array.from(state.canvasSelected)
        : state.assets.map((a) => a.id);
      if (!ids.length) {
        addChatResponse("No items to flag.", 6000);
        break;
      }
      try {
        await api("/api/assets/flag/bulk", {
          method: "POST",
          body: JSON.stringify({ ids, flagged: 1 }),
        });
        if (state.canvasReview) clearCanvasSelection();
        await loadAssets();
      } catch (e) {
        addChatResponse(`Bulk flag failed: ${formatApiError(e)}`, 8000);
      }
      break;
    }
    case "triage_by_query": {
      // Server already applied the triage — just refresh the grid
      await loadAssets();
      break;
    }
    case "message":
    default:
      break;
  }
}

const chatInput = $("#chatInput");
const chatSend = $("#chatSend");
if (chatSend) chatSend.addEventListener("click", () => {
  const val = chatInput?.value || "";
  if (val.trim()) { processChat(val.trim()); chatInput.value = ""; }
});
if (chatInput) chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const val = chatInput.value || "";
    if (val.trim()) { processChat(val.trim()); chatInput.value = ""; }
  }
});

// ─── View toggle (Grid / Explorer) ───────────────────────────────────────────────

let explorerLoaded = false;
let explorerData = null;

const viewGridBtn = $("#viewGrid");
const viewExplorerBtn = $("#viewExplorer");

// Explorer implementations: 2D (default) and 3D (opt-in via module)
const _Explorer2D = window.AttractorExplorer || null;
let _explorerMode = "2d";   // "2d" | "3d"
let _ExplorerImpl = _Explorer2D || window.Explorer || null;
function _getExplorer3D() { return window.AttractorExplorer3D || null; }
let _cachedExplorerAttractorData = null;
let _cachedExplorerAttractorDataIncludesHidden = false;
let _explorerPayloadIncludesHidden = false;
let _explorerScopeReloading = false;
let _busyCursorDepth = 0;

function _setGlobalBusyCursor(cursor) {
  if (document.body) document.body.style.cursor = cursor;
  if (document.documentElement) document.documentElement.style.cursor = cursor;
  const container = document.getElementById("explorerContainer");
  if (container) container.style.cursor = cursor;
}

function _pushBusyCursor() {
  _busyCursorDepth += 1;
  _setGlobalBusyCursor("wait");
}

function _popBusyCursor() {
  _busyCursorDepth = Math.max(0, _busyCursorDepth - 1);
  if (_busyCursorDepth === 0) _setGlobalBusyCursor("");
}

function _isAttractorPayload(data) {
  return !!(
    data &&
    Array.isArray(data.assets) &&
    Array.isArray(data.dimensions) &&
    data.categories &&
    data.attractors
  );
}

function _merge3DExplorerData(layoutData, attractorData) {
  const base = attractorData || {};
  const assets = Array.isArray(base.assets) ? base.assets : [];
  const layoutNodes = Array.isArray(layoutData?.nodes) ? layoutData.nodes : [];
  const layoutById = new Map(layoutNodes.map((node) => [node.id, node]));
  let matched = 0;

  const mergedAssets = assets.map((asset) => {
    const layoutNode = layoutById.get(asset.id);
    if (!layoutNode) return asset;
    matched += 1;
    return {
      ...asset,
      x: Number.isFinite(layoutNode.x) ? layoutNode.x : asset.x,
      y: Number.isFinite(layoutNode.y) ? layoutNode.y : asset.y,
      z: Number.isFinite(layoutNode.z) ? layoutNode.z : asset.z,
      title: asset.title || layoutNode.title || "",
      t: asset.t || layoutNode.thumb_url || "",
    };
  });

  if (layoutNodes.length === 0) {
    console.warn("[Explorer] 3D layout returned no nodes; using PCA fallback positions");
  } else if (matched === 0) {
    console.warn("[Explorer] 3D layout IDs did not overlap; using PCA fallback positions");
  } else {
    console.log(`[Explorer] 3D layout merged ${matched}/${assets.length} nodes`);
  }

  return {
    ...base,
    assets: mergedAssets,
    layout_clusters: Array.isArray(layoutData?.clusters) ? layoutData.clusters : [],
  };
}

function _shouldExplorerIncludeHiddenData() {
  return isOwner() && state.triageFilter === "hidden";
}

async function _loadExplorerPayload(mode, includeHidden) {
  const hiddenQs = includeHidden ? "include_hidden=1" : "";
  const attractorUrl = `/api/explorer/attractor-data?dims=2${hiddenQs ? `&${hiddenQs}` : ""}`;
  const layoutUrl = `/api/explorer/layout${hiddenQs ? `?${hiddenQs}` : ""}`;

  if (mode === "3d") {
    // Keep 3D switches fast: reuse attractor metadata (vectors/chips) already
    // loaded for 2D, and only fetch layout coords for the mode switch.
    const layoutPromise = api(layoutUrl);
    let baseData =
      (_isAttractorPayload(explorerData) && _explorerPayloadIncludesHidden === includeHidden)
        ? explorerData
        : null;
    if (!_isAttractorPayload(baseData)) {
      baseData =
        (_isAttractorPayload(_cachedExplorerAttractorData)
          && _cachedExplorerAttractorDataIncludesHidden === includeHidden)
          ? _cachedExplorerAttractorData
          : null;
    }
    if (!_isAttractorPayload(baseData)) {
      baseData = await api(attractorUrl);
    }
    _cachedExplorerAttractorData = baseData;
    _cachedExplorerAttractorDataIncludesHidden = includeHidden;
    try {
      const layoutData = await layoutPromise;
      return _merge3DExplorerData(layoutData, baseData);
    } catch (e) {
      console.warn("[Explorer] 3D layout request failed; using PCA fallback positions", e);
      return baseData;
    }
  }
  const data = await api(attractorUrl);
  _cachedExplorerAttractorData = data;
  _cachedExplorerAttractorDataIncludesHidden = includeHidden;
  return data;
}

function setViewMode(mode) {
  if (state.canvasReview) exitCanvasReview();
  const browseView = $("#browseView");
  const explorerView = $("#explorerView");
  const sidebarEl = $("aside.sidebar");
  const layoutEl = $(".layout");

  if (mode === "explorer") {
    if (browseView) browseView.hidden = true;
    if (explorerView) explorerView.hidden = false;
    if (layoutEl) layoutEl.classList.add("explorer-active");
    if (viewGridBtn) viewGridBtn.classList.remove("active");
    if (viewExplorerBtn) viewExplorerBtn.classList.add("active");
    loadExplorerView();
  } else {
    if (browseView) browseView.hidden = false;
    if (explorerView) explorerView.hidden = true;
    if (layoutEl) layoutEl.classList.remove("explorer-active");
    if (viewGridBtn) viewGridBtn.classList.add("active");
    if (viewExplorerBtn) viewExplorerBtn.classList.remove("active");
    if (_ExplorerImpl && explorerLoaded) {
      _ExplorerImpl.pause();
    }
  }
}

/** Switch between 2D and 3D explorer implementations. */
async function switchExplorerMode(newMode) {
  if (newMode === _explorerMode && explorerLoaded) return;
  // Tear down current
  if (_ExplorerImpl && explorerLoaded) {
    _ExplorerImpl.destroy();
  }
  const container = document.getElementById("explorerContainer");
  if (container) container.innerHTML = "";
  explorerLoaded = false;
  explorerData = null;
  _explorerPayloadIncludesHidden = false;

  _explorerMode = newMode;
  const e3d = _getExplorer3D();
  if (newMode === "3d" && e3d) {
    _ExplorerImpl = e3d;
  } else {
    _ExplorerImpl = _Explorer2D || window.Explorer || null;
    _explorerMode = "2d";
  }
  _pushBusyCursor();
  try {
    await loadExplorerView();
  } finally {
    _popBusyCursor();
  }
}

async function loadExplorerView() {
  if (!_ExplorerImpl || typeof _ExplorerImpl.init !== "function") {
    Shared.showToast("Explorer not available", { type: "error", duration: 3000 });
    return;
  }

  if (!explorerLoaded) {
    _ExplorerImpl.init("explorerContainer");
    _ExplorerImpl.onClickNode(async (nodeId) => {
      // Try local cache first, then fetch from server
      let asset = state.assets.find((a) => a.id === nodeId);
      if (!asset) {
        try {
          const data = await api(`/api/assets?ids=${nodeId.slice(0,8)}&limit=1`);
          asset = (data.assets || [])[0];
        } catch (_) { /* ignore */ }
      }
      if (asset) openModal(asset);
    });
    // Wire 3D toggle from control panel checkbox
    if (_ExplorerImpl.on3DToggle) {
      _ExplorerImpl.on3DToggle((wants3D) => {
        const newMode = wants3D ? "3d" : "2d";
        if (newMode === "3d" && !_getExplorer3D()) {
          Shared.showToast("3D explorer loading…", { type: "info", duration: 2000 });
          return;
        }
        switchExplorerMode(newMode);
      });
    }
    explorerLoaded = true;
  } else {
    _ExplorerImpl.resume();
  }

  // Load data from appropriate endpoint
  _pushBusyCursor();
  try {
    const includeHidden = _shouldExplorerIncludeHiddenData();
    Shared.showToast(`Loading ${_explorerMode.toUpperCase()} attractor map…`, { type: "info", duration: 2000 });
    const data = await _loadExplorerPayload(_explorerMode, includeHidden);
    explorerData = data;
    _explorerPayloadIncludesHidden = includeHidden;
    _ExplorerImpl.loadData(data);
    syncExplorerFilter();   // apply any active grid filters as dim
  } catch (e) {
    Shared.showToast(`Explorer: ${formatApiError(e)}`, { type: "error" });
  } finally {
    _popBusyCursor();
  }
}

if (viewGridBtn) viewGridBtn.addEventListener("click", () => setViewMode("grid"));
if (viewExplorerBtn) viewExplorerBtn.addEventListener("click", () => setViewMode("explorer"));

// 3D toggle is now inside the control panel — wired in loadExplorerView()

// ─── Explorer ↔ filter sync ──────────────────────────────────────────────────────

let _explorerFilterSeq = 0;

function _hasActiveFilters() {
  return !!(
    state.triageFilter ||
    state.currentSource ||
    state.currentBoard ||
    hasCollectionFilter() ||
    hasCatalogFilter() ||
    state.chatItemIds ||
    (state.q && state.q.trim())
  );
}

async function syncExplorerFilter() {
  if (!_ExplorerImpl || !explorerLoaded) return;

  // Sync header search text into explorer's local title search
  if (typeof _ExplorerImpl.setSearch === "function") {
    _ExplorerImpl.setSearch(state.q || "");
  }

  // Hidden data is loaded only for owner hidden view.
  const wantsHiddenPayload = _shouldExplorerIncludeHiddenData();
  if (_explorerPayloadIncludesHidden !== wantsHiddenPayload) {
    if (_explorerScopeReloading) return;
    _explorerScopeReloading = true;
    try {
      await loadExplorerView();
    } finally {
      _explorerScopeReloading = false;
    }
    return;
  }

  // No filters → show everything
  if (!_hasActiveFilters()) {
    _ExplorerImpl.setFilter(null);
    return;
  }

  // Chat-curated items: highlight only those IDs
  if (state.chatItemIds) {
    _ExplorerImpl.setFilter(state.chatItemIds);
    return;
  }

  const catalogFiles = getCatalogFilterFiles();
  if (catalogFiles.length) {
    const catalogParams = new URLSearchParams();
    for (const file of catalogFiles) catalogParams.append("file", file);
    const seq = ++_explorerFilterSeq;
    try {
      const data = await api(`/api/catalog/asset-ids?${catalogParams}`);
      if (seq !== _explorerFilterSeq) return; // stale
      _ExplorerImpl.setFilter(data.ids || []);
    } catch (e) {
      // Silently ignore — filter dim is a nice-to-have
    }
    return;
  }

  // Build the same filter params the grid uses
  const params = new URLSearchParams();
  if (state.q && state.q.trim()) params.set("q", state.q.trim());
  if (state.currentSource) params.set("source", state.currentSource);
  if (state.currentBoard) params.set("board", state.currentBoard);
  const collectionIds = getCollectionFilterIds();
  if (collectionIds.length) params.set("collection_id", collectionIds.join(","));
  if (state.triageFilter === "needs-comment") {
    params.set("needs_annotation", "1");
    if (isOwner()) params.set("include_hidden", "1");
  } else if (state.triageFilter === "hidden") {
    params.set("triage_status", "hidden");
    if (_shouldExplorerIncludeHiddenData()) params.set("include_hidden", "1");
  } else if (state.triageFilter === "flagged") {
    params.set("flagged", "1");
    if (isOwner()) params.set("include_hidden", "1");
  } else if (state.triageFilter) {
    params.set("triage_status", state.triageFilter);
  }

  const seq = ++_explorerFilterSeq;
  try {
    const data = await api(`/api/asset-ids?${params}`);
    if (seq !== _explorerFilterSeq) return; // stale
    _ExplorerImpl.setFilter(data.ids || []);
  } catch (e) {
    // Silently ignore — filter dim is a nice-to-have
  }
}

// ─── Filter indicator ────────────────────────────────────────────────────────────

function updateFilterIndicator() {
  const bar = $("#filterIndicator");
  const text = $("#filterIndicatorText");
  if (!bar || !text) return;

  const parts = [];
  const catalogFiles = getCatalogFilterFiles();
  const collectionIds = getCollectionFilterIds();

  // When a chat prompt is active, show it as the primary context;
  // skip the raw search text since it's just the extracted keyword from the prompt.
  if (state.chatPrompt) {
    parts.push(`Dave: "${state.chatPrompt}"`);
  } else if (state.semanticMode) {
    const semQ = semanticQueryFromInput(state.q);
    parts.push(`Semantic search: "${semQ}"`);
  } else if (state.q && state.q.trim()) {
    parts.push(`"${state.q.trim()}"`);
  }
  if (state.currentSource && !catalogFiles.length && !collectionIds.length) {
    parts.push(`Source: ${state.currentSource}`);
  }
  if (state.currentBoard && !catalogFiles.length && !collectionIds.length) {
    parts.push(`Board: ${state.currentBoard}`);
  }
  if (catalogFiles.length) {
    let catalogLabel = state.currentCatalogLabel || "";
    if (!catalogLabel && catalogFiles.length === 1) {
      catalogLabel = catalogFiles[0].split("/").pop().replace(".md", "").replace(/_/g, " ");
    } else if (!catalogLabel) {
      catalogLabel = `${catalogFiles.length} folders`;
    }
    parts.push(`Catalog: ${catalogLabel}`);
  }
  if (collectionIds.length) {
    if (collectionIds.length === 1) {
      const cid = collectionIds[0];
      const col = state.collections.find((c) => c.id === cid);
      parts.push(`Collection: ${col ? col.name : cid.slice(0, 8)}`);
    } else {
      parts.push(`Collections: ${state.currentCollectionLabel || `${collectionIds.length} folders`}`);
    }
  }
  if (state.triageFilter) {
    const labels = { pending: "Pending", keeper: "Keepers", hidden: "Hidden", "needs-comment": "Needs comment", flagged: "🚩 Flagged" };
    parts.push(`Status: ${labels[state.triageFilter] || state.triageFilter}`);
  }

  if (parts.length === 0) {
    bar.hidden = true;
    return;
  }
  text.textContent = `Results filtered by ${parts.join(" + ")}`;
  bar.hidden = false;
}

const clearFilterBtn = $("#clearFilterIndicator");
if (clearFilterBtn) clearFilterBtn.addEventListener("click", () => {
  state.currentSource = null;
  state.currentBoard = null;
  clearCollectionFilter();
  clearCatalogFilter();
  state.currentTreeNodeId = null;
  state.triageFilter = "";
  state.q = "";
  state.chatPrompt = "";
  state.chatItemIds = null;
  $$("[data-triage]").forEach((c) => {
    c.classList.toggle("active", c.dataset.triage === "");
  });
  renderCatalogTree();
  updateFilterIndicator();
  loadAssets();
});

// ─── Search (driven entirely via Ask Dave now) ──────────────────────────────────

// ─── Load More ───────────────────────────────────────────────────────────────────

const loadMoreBtn = $("#loadMore");
if (loadMoreBtn) loadMoreBtn.addEventListener("click", () => loadAssets({ append: true }));

// ─── Scan import ──────────────────────────────────────────────────────────────────

function openScanImportModal() { $("#scanImportModal")?.classList.remove("hidden"); }
function closeScanImportModal() { $("#scanImportModal")?.classList.add("hidden"); }

function currentScanImportFile() {
  const input = $("#scanPdfInput");
  return state.scanImportFile || (input?.files?.[0]) || null;
}

function setScanImportButtonState() {
  const btn = $("#addScanPdf");
  if (btn) { btn.disabled = !!state.scanImportBusy; btn.textContent = state.scanImportBusy ? "Importing…" : "Add Scan"; }
  const runBtn = $("#runScanImport");
  if (runBtn) runBtn.disabled = !!state.scanImportBusy || !currentScanImportFile();
}

function resetScanImportModal() {
  const input = $("#scanPdfInput");
  setSingleFileSelection(input, null, "scanImportFile");
  const parser = $("#scanUseFormParser");
  if (parser) parser.checked = false;
  const delimiters = $("#scanDetectDelimiters");
  if (delimiters) delimiters.checked = true;
  const dropZone = $("#scanDropZone");
  if (dropZone) dropZone.classList.remove("dragActive");
  setScanImportButtonState();
}

async function importScanPdf(file, opts = {}) {
  if (!file) return;
  if (!isPdfFile(file)) { Shared.showToast("Please choose a PDF file.", { type: "error" }); return; }
  const name = file.name || "";
  const useFormParser = !!opts.useFormParser;
  const detectDelimiters = opts.detectDelimiters !== false;
  state.scanImportBusy = true;
  setScanImportButtonState();
  const narrative = $("#canvasNarrative");
  if (narrative) narrative.textContent = `Importing "${name}"…`;
  try {
    const formData = new FormData();
    formData.append("file", file, name);
    formData.append("use_form_parser", useFormParser ? "1" : "0");
    formData.append("split_on_delimiters", detectDelimiters ? "1" : "0");
    const payload = await apiUpload("/api/import/scans", formData);
    const report = payload.import || {};
    const created = Number(report.created_assets || 0);
    await loadFacets();
    await loadAssets();
    Shared.showToast(`Imported ${created} scan page${created === 1 ? "" : "s"} from "${name}".`, { type: "success" });
    closeScanImportModal();
  } catch (e) {
    Shared.showToast(`Scan import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.scanImportBusy = false;
    setScanImportButtonState();
    setSingleFileSelection($("#scanPdfInput"), null, "scanImportFile");
    if (narrative) narrative.textContent = "";
  }
}

const addScanPdfBtn = $("#addScanPdf");
const scanPdfInput = $("#scanPdfInput");
const scanDropZone = $("#scanDropZone");
const runScanImportBtn = $("#runScanImport");
const cancelScanImportBtn = $("#cancelScanImport");
const closeScanImportBtn = $("#closeScanImport");

if (addScanPdfBtn) addScanPdfBtn.onclick = () => { if (!state.scanImportBusy) { openScanImportModal(); resetScanImportModal(); } };
if (scanPdfInput) {
  scanPdfInput.addEventListener("change", () => {
    const file = scanPdfInput.files?.[0] || null;
    if (file && !isPdfFile(file)) {
      Shared.showToast("Please choose a PDF file.", { type: "error" });
      setSingleFileSelection(scanPdfInput, null, "scanImportFile");
      setScanImportButtonState(); return;
    }
    state.scanImportFile = file || null;
    setScanImportButtonState();
  });
}
if (scanDropZone) {
  wireSingleFileDropZone({
    zone: scanDropZone, input: scanPdfInput, stateKey: "scanImportFile",
    accept: isPdfFile, invalidMessage: "Please drop a PDF file.",
    isBusy: () => state.scanImportBusy || state.photoImportBusy,
    onSelected: () => setScanImportButtonState(),
  });
}
if (runScanImportBtn) {
  runScanImportBtn.addEventListener("click", async () => {
    if (state.scanImportBusy) return;
    const file = currentScanImportFile();
    const useFormParser = !!($("#scanUseFormParser")?.checked);
    const detectDelimiters = !!($("#scanDetectDelimiters")?.checked);
    await importScanPdf(file, { useFormParser, detectDelimiters });
  });
}
if (cancelScanImportBtn) cancelScanImportBtn.onclick = () => { if (!state.scanImportBusy) { closeScanImportModal(); resetScanImportModal(); } };
if (closeScanImportBtn) closeScanImportBtn.onclick = () => { if (!state.scanImportBusy) { closeScanImportModal(); resetScanImportModal(); } };
setScanImportButtonState();

// ─── Photo import ─────────────────────────────────────────────────────────────────

function openPhotoImportModal() { $("#photoImportModal")?.classList.remove("hidden"); }
function closePhotoImportModal() { $("#photoImportModal")?.classList.add("hidden"); }

function currentPhotoImportFile() {
  const input = $("#photoInput");
  return state.photoImportFile || (input?.files?.[0]) || null;
}

function setPhotoImportButtonState() {
  const btn = $("#addPhotos");
  if (btn) { btn.disabled = !!state.photoImportBusy || !!state.scanImportBusy; btn.textContent = state.photoImportBusy ? "Importing…" : "Add Photos"; }
  const runBtn = $("#runPhotoImport");
  if (runBtn) runBtn.disabled = !!state.photoImportBusy || !!state.scanImportBusy || !currentPhotoImportFile();
}

function resetPhotoImportModal() {
  const input = $("#photoInput");
  setSingleFileSelection(input, null, "photoImportFile");
  const dropZone = $("#photoDropZone");
  if (dropZone) dropZone.classList.remove("dragActive");
  setPhotoImportButtonState();
}

async function importPhoto(file) {
  if (!file) return;
  const name = file.name || "";
  if (!isImageFile(file)) { Shared.showToast("Please choose an image file.", { type: "error" }); return; }
  state.photoImportBusy = true;
  setPhotoImportButtonState();
  setScanImportButtonState();
  const narrative = $("#canvasNarrative");
  if (narrative) narrative.textContent = `Importing "${name}"…`;
  try {
    const formData = new FormData();
    formData.append("file", file, name);
    const payload = await apiUpload("/api/import/photos", formData);
    const report = payload.import || {};
    const created = Number(report.created_assets || 0);
    await loadFacets();
    await loadAssets();
    Shared.showToast(`Imported ${created} photo${created === 1 ? "" : "s"} from "${name}".`, { type: "success" });
    closePhotoImportModal();
  } catch (e) {
    Shared.showToast(`Photo import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.photoImportBusy = false;
    setPhotoImportButtonState();
    setScanImportButtonState();
    setSingleFileSelection($("#photoInput"), null, "photoImportFile");
    if (narrative) narrative.textContent = "";
  }
}

const addPhotosBtn = $("#addPhotos");
const photoInput = $("#photoInput");
const photoDropZone = $("#photoDropZone");
const runPhotoImportBtn = $("#runPhotoImport");
const cancelPhotoImportBtn = $("#cancelPhotoImport");
const closePhotoImportBtn = $("#closePhotoImport");

if (addPhotosBtn) addPhotosBtn.onclick = () => {
  if (!state.photoImportBusy && !state.scanImportBusy) { openPhotoImportModal(); resetPhotoImportModal(); }
};
if (photoInput) {
  photoInput.addEventListener("change", () => {
    const file = photoInput.files?.[0] || null;
    if (file && !isImageFile(file)) {
      Shared.showToast("Please choose an image file.", { type: "error" });
      setSingleFileSelection(photoInput, null, "photoImportFile");
      setPhotoImportButtonState(); return;
    }
    state.photoImportFile = file || null;
    setPhotoImportButtonState();
  });
}
if (photoDropZone) {
  wireSingleFileDropZone({
    zone: photoDropZone, input: photoInput, stateKey: "photoImportFile",
    accept: isImageFile, invalidMessage: "Please drop an image file.",
    isBusy: () => state.photoImportBusy || state.scanImportBusy,
    onSelected: () => setPhotoImportButtonState(),
  });
}
if (runPhotoImportBtn) {
  runPhotoImportBtn.addEventListener("click", async () => {
    if (state.photoImportBusy || state.scanImportBusy) return;
    await importPhoto(currentPhotoImportFile());
  });
}
if (cancelPhotoImportBtn) cancelPhotoImportBtn.onclick = () => { if (!state.photoImportBusy) { closePhotoImportModal(); resetPhotoImportModal(); } };
if (closePhotoImportBtn) closePhotoImportBtn.onclick = () => { if (!state.photoImportBusy) { closePhotoImportModal(); resetPhotoImportModal(); } };
setPhotoImportButtonState();

// ─── Init ─────────────────────────────────────────────────────────────────────────

wireStatusChips();

function isOwner() {
  return state.actor && state.actor.role === "owner";
}

function applyRoleVisibility() {
  const owner = isOwner();

  // Status chips: hide triage-specific chips for collaborators
  const statusSection = $("#statusChips")?.closest(".sidebar-section");
  if (statusSection) statusSection.hidden = !owner;

  // Review button, import buttons, admin link — owner-only
  const reviewBtnEl = $("#reviewBtn");
  if (reviewBtnEl) reviewBtnEl.hidden = !owner;
  const addScanEl = $("#addScanPdf");
  if (addScanEl) addScanEl.hidden = !owner;
  const addPhotosEl = $("#addPhotos");
  if (addPhotosEl) addPhotosEl.hidden = !owner;
  const adminEl = $(".adminLink");
  if (adminEl) adminEl.hidden = !owner;

  // Modal triage buttons — owner-only
  const keepBtnEl = $("#modalKeepBtn");
  const hideBtnEl = $("#modalHideBtn");
  if (keepBtnEl) keepBtnEl.hidden = !owner;
  if (hideBtnEl) hideBtnEl.hidden = !owner;

  // Modal flag button — visible to all logged-in actors
  const flagBtnEl = $("#modalFlagBtn");
  if (flagBtnEl) flagBtnEl.hidden = !state.actor;

  // Annotation question toggle — available to all (collaborators ask questions)
  // Notes textarea — available to all

  // New collection button — available to all logged-in actors
  const newCollBtn = $("#newCollection");
  if (newCollBtn) newCollBtn.hidden = !state.actor;
}

async function checkFlaggedCount() {
  if (!isOwner()) return;
  try {
    const data = await api("/api/assets?flagged=1&limit=1");
    const chip = $("#flaggedChip");
    if (chip) chip.hidden = !(data.assets && data.assets.length > 0);
  } catch { /* ignore */ }
}

(async () => {
  try {
    // Resolve current actor identity (magic link)
    try {
      const meData = await api("/api/me");
      state.actor = meData.actor || null;
    } catch { state.actor = null; }

    // Apply role-based visibility before rendering
    applyRoleVisibility();

    await Promise.all([loadCollections(), loadFacets(), loadCatalogTree()]);
    await loadAssets();

    // Owner-only features: hidden tree + question polling + flagged check
    if (isOwner()) {
      loadHiddenTree();
      pollQuestions();
      state.questionPollTimer = setInterval(pollQuestions, 60000);
      checkFlaggedCount();
    }
  } catch (e) {
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load: ${escapeHtml(formatApiError(e))}</div>`;
  }
})();
