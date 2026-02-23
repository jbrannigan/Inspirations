// ─── State ─────────────────────────────────────────────────────────────────────
const state = {
  // Navigation
  view: "browse",               // "browse" | "review"
  currentBoard: null,           // board filter (null = all)
  currentSource: null,          // source filter (null = all)
  currentCollection: null,      // collection ID filter
  triageFilter: "",             // "" | "pending" | "keeper" | "hidden" | "needs-comment"

  // Assets
  assets: [],
  hasMore: false,
  loadingAssets: false,
  offset: 0,
  q: "",
  semanticMode: false,
  assetsRequestSeq: 0,

  // Review mode
  reviewItems: [],
  reviewIndex: 0,
  reviewHistory: [],
  reviewSkipped: 0,
  reviewKept: 0,
  reviewHidden: 0,

  // Collections + facets
  collections: [],
  facets: { sources: [], boards: [] },

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
  return (a.title || "").trim()
    || (a.seo_alt_text || "").trim()
    || (a.board || "").trim()
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
  } else if (state.triageFilter) {
    params.set("triage_status", state.triageFilter);
  }

  // Always include hidden items when "all" is selected to show full picture
  // but don't show triage=hidden by default unless explicitly requested
  // (server default: exclude hidden)

  try {
    let data;
    if (semQ) {
      const res = await fetch(`/api/search/similar?${params}`);
      if (!res.ok) throw new Error(await res.text());
      data = await res.json();
    } else {
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
    state.offset += newAssets.length;

    renderGrid();
    updateStats();
    updateLoadMoreBtn();
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
  if (statsEl) statsEl.textContent = `${state.assets.length} items shown`;
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
  let badgeHtml = "";
  if (ts === "keeper" && needsComment) {
    badgeHtml = '<span class="triage-badge needs-comment" title="Keeper — comment later"></span>';
  } else if (ts === "keeper") {
    badgeHtml = '<span class="triage-badge keeper" title="Keeper"></span>';
  } else if (ts === "hidden") {
    badgeHtml = '<span class="triage-badge hidden-status" title="Hidden"></span>';
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

  el.innerHTML = `
    <div class="card-image">
      ${imgUrl
        ? `<img src="${escapeHtml(imgUrl)}" loading="lazy" alt="" />`
        : `<div class="card-placeholder">${escapeHtml(displayTitle(a))}</div>`}
      ${badgeHtml}
      ${scanNavHtml}
    </div>
    <div class="card-footer">
      <span class="card-title">${escapeHtml(displayTitle(a))}</span>
      <span class="card-source">${escapeHtml(a.board || a.source || "")}${a.content_kind && a.content_kind !== "pin" ? ` · ${escapeHtml(a.content_kind)}` : ""}</span>
    </div>
  `;

  el.onclick = (e) => {
    if (e.target.closest(".scan-nav-btn")) return;
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

  return el;
}

// ─── Facets + sidebar ───────────────────────────────────────────────────────────

async function loadFacets() {
  try {
    const data = await api("/api/facets");
    state.facets = data;
    renderSourceChips(data.sources || []);
    renderBoardList(data.boards || []);
  } catch (e) {
    console.error("Failed to load facets:", e);
  }
}

function renderSourceChips(sources) {
  const wrap = $("#sourceChips");
  if (!wrap) return;
  wrap.innerHTML = "";

  const allBtn = document.createElement("button");
  allBtn.className = `filter-chip${!state.currentSource ? " active" : ""}`;
  allBtn.dataset.source = "";
  allBtn.textContent = "All";
  allBtn.onclick = () => setSourceFilter(null);
  wrap.appendChild(allBtn);

  for (const s of sources) {
    const src = s.source || s.value || "";
    if (!src) continue;
    const btn = document.createElement("button");
    btn.className = `filter-chip${state.currentSource === src ? " active" : ""}`;
    btn.dataset.source = src;
    const label = { pinterest: "Pinterest", facebook: "Facebook", scan: "Scans", photo: "Photos" }[src] || src;
    btn.textContent = `${label} (${s.count || 0})`;
    btn.onclick = () => setSourceFilter(src);
    wrap.appendChild(btn);
  }
}

function renderBoardList(boards) {
  const wrap = $("#boardList");
  if (!wrap) return;
  wrap.innerHTML = "";

  if (!boards.length) {
    wrap.innerHTML = '<div class="muted sidebar-loading">No boards yet.</div>';
    return;
  }

  const allBtn = document.createElement("button");
  allBtn.className = `board-chip${!state.currentBoard ? " active" : ""}`;
  allBtn.innerHTML = `<span>All boards</span>`;
  allBtn.onclick = () => setBoardFilter(null);
  wrap.appendChild(allBtn);

  for (const b of boards) {
    const board = b.board || b.value || "";
    if (!board) continue;
    const btn = document.createElement("button");
    btn.className = `board-chip${state.currentBoard === board ? " active" : ""}`;
    btn.innerHTML = `<span>${escapeHtml(board)}</span><span class="count">${b.count || 0}</span>`;
    btn.onclick = () => setBoardFilter(board);
    wrap.appendChild(btn);
  }
}

function setSourceFilter(source) {
  state.currentSource = source || null;
  state.offset = 0;
  renderSourceChips(state.facets.sources || []);
  loadAssets();
}

function setBoardFilter(board) {
  state.currentBoard = board || null;
  state.offset = 0;
  renderBoardList(state.facets.boards || []);
  loadAssets();
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
      loadAssets();
    });
  });
}

// ─── Collections ────────────────────────────────────────────────────────────────

async function loadCollections() {
  try {
    const data = await api("/api/collections");
    state.collections = data.collections || [];
    renderCollectionList();
  } catch (e) {
    console.error("Failed to load collections:", e);
  }
}

function renderCollectionList() {
  const wrap = $("#collectionList");
  if (!wrap) return;
  wrap.innerHTML = "";

  const visible = state.collections.filter((c) => (c.name || "").toLowerCase() !== "hidden");

  if (!visible.length) {
    wrap.innerHTML = '<div class="muted sidebar-loading">No collections yet.</div>';
    return;
  }

  // "All" (deselect collection)
  if (state.currentCollection) {
    const allBtn = document.createElement("button");
    allBtn.className = "collection-chip";
    allBtn.textContent = "← All items";
    allBtn.onclick = () => setCollectionFilter(null);
    wrap.appendChild(allBtn);
  }

  for (const c of visible) {
    const btn = document.createElement("button");
    btn.className = `collection-chip${state.currentCollection === c.id ? " active" : ""}`;
    btn.innerHTML = `<span>${escapeHtml(c.name)}</span><span class="count">${c.count || 0}</span>`;
    btn.onclick = () => setCollectionFilter(c.id);
    wrap.appendChild(btn);
  }
}

function setCollectionFilter(collectionId) {
  state.currentCollection = collectionId || null;
  state.offset = 0;
  renderCollectionList();
  loadAssets();
}

$("#newCollection").addEventListener("click", async () => {
  const name = prompt("Collection name:");
  if (!name || !name.trim()) return;
  try {
    await api("/api/collections", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
    await loadCollections();
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

  // Source link
  const sourceLink = $("#sourceLink");
  if (sourceLink) {
    const ref = asset.source_ref || "";
    sourceLink.href = ref || "#";
    sourceLink.textContent = ref ? (asset.source === "scan" ? "Open PDF" : `Open ${asset.source || "original"}`) : "No source";
  }

  // Source site link (Pinterest/Facebook external URL)
  const sourceSiteRow = $("#sourceSiteRow");
  const sourceSiteLink = $("#sourceSiteLink");
  if (sourceSiteRow && sourceSiteLink && asset.source_url) {
    sourceSiteLink.href = asset.source_url;
    sourceSiteLink.textContent = `Original site (${sourceHost(asset.source_url) || asset.source_url}) ↗`;
    sourceSiteRow.hidden = false;
  } else if (sourceSiteRow) {
    sourceSiteRow.hidden = true;
  }

  // View source button — show only for scans (as "View Original"), hide for social
  const viewSourceBtn = $("#viewSourceBtn");
  if (viewSourceBtn) {
    const ref = asset.source_ref || "";
    if (asset.source === "scan") {
      viewSourceBtn.textContent = "View Original";
      viewSourceBtn.onclick = () => { if (ref) window.open(ref, "_blank", "noopener"); };
      viewSourceBtn.disabled = !ref;
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

  // Triage buttons
  updateModalTriageButtons(asset.triage_status);
  const keepBtn = $("#modalKeepBtn");
  const hideBtn = $("#modalHideBtn");
  if (keepBtn) keepBtn.onclick = async () => { await setTriageFromModal(asset, "keeper"); };
  if (hideBtn) hideBtn.onclick = async () => { await setTriageFromModal(asset, "hidden"); };

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
    // Update badge on card
    const card = $(`[data-id="${asset.id}"]`);
    if (card) {
      const oldBadge = card.querySelector(".triage-badge");
      if (oldBadge) oldBadge.remove();
      if (newStatus === "keeper") {
        const badge = document.createElement("span");
        badge.className = "triage-badge keeper";
        badge.title = "Keeper";
        card.querySelector(".card-image").appendChild(badge);
      } else if (newStatus === "hidden") {
        const badge = document.createElement("span");
        badge.className = "triage-badge hidden-status";
        badge.title = "Hidden";
        card.querySelector(".card-image").appendChild(badge);
      }
    }
    const msg = newStatus === "keeper" ? "Marked as keeper" : newStatus === "hidden" ? "Hidden" : "Reset to pending";
    Shared.showToast(msg, { type: "success" });
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
    const el = document.createElement("div");
    el.className = `listItem annItem${state.activeAnnotationId === ann.id ? " active" : ""}`;
    el.innerHTML = `
      <div class="annHeader">
        <strong>#${idx + 1}</strong>
        <button class="iconBtn danger" data-del="${ann.id}" type="button">×</button>
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
    const m = document.createElement("div");
    m.className = "marker";
    const pt = normalizedToStagePoint(ann.x, ann.y);
    m.style.left = `${pt.left}px`;
    m.style.top = `${pt.top}px`;
    m.dataset.id = ann.id;
    m.style.background = markerColor(idx);
    m.innerHTML = `
      <span style="color:#F2F2F6">${idx + 1}</span>
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
    const res = await api("/api/annotations", {
      method: "POST",
      body: JSON.stringify({ asset_id: state.modalAsset.id, x: point.x, y: point.y, text: "" }),
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

  renderReviewCard();
}

function exitReview() {
  state.view = "browse";
  const browseView = $("#browseView");
  const reviewView = $("#reviewView");
  if (browseView) browseView.hidden = false;
  if (reviewView) reviewView.hidden = true;
  loadAssets();
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
  if (titleEl) titleEl.textContent = displayTitle(item);

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

// Review button wiring
const reviewBtn = $("#reviewBtn");
if (reviewBtn) reviewBtn.addEventListener("click", enterReview);

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
    if (state.view === "review") { exitReview(); return; }
    return;
  }

  // Review mode shortcuts (only when review is active and no modal/input focused)
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

function addChatResponse(text, duration) {
  const bar = $("#chatResponse");
  if (!bar) return;
  bar.textContent = text;
  bar.hidden = false;
  clearTimeout(addChatResponse._timer);
  addChatResponse._timer = setTimeout(() => { if (bar) bar.hidden = true; }, duration || 6000);
}

async function processChat(text) {
  const lower = text.toLowerCase().trim();
  if (!lower) return;

  // Create collection
  const createMatch = lower.match(/(?:make|create)\s+(?:a\s+)?(?:new\s+)?collection\s+(?:called\s+|named\s+)?["']?(.+?)["']?$/);
  if (createMatch) {
    const name = createMatch[1].trim();
    try {
      await api("/api/collections", { method: "POST", body: JSON.stringify({ name }) });
      await loadCollections();
      addChatResponse(`Created collection "${name}".`);
    } catch (e) { addChatResponse(`Couldn't create collection: ${formatApiError(e)}`); }
    return;
  }

  // Show keepers/pending/hidden
  const statusMatch = lower.match(/(?:show|see|filter|find)\s+(?:me\s+)?(?:only\s+)?(?:the\s+)?(\bkeepers?\b|\bpending\b|\bhidden\b|\bneeds?\s+comment\b)/);
  if (statusMatch) {
    const s = statusMatch[1].replace(/\s+/g, "-");
    const triageVal = s.startsWith("keeper") ? "keeper" : s === "pending" ? "pending" : s === "hidden" ? "hidden" : "needs-comment";
    state.triageFilter = triageVal;
    // Update chip
    $$("[data-triage]").forEach((c) => {
      const match = (c.dataset.triage === triageVal) || (triageVal === "needs-comment" && c.dataset.triage === "needs-comment");
      c.classList.toggle("active", match);
    });
    await loadAssets();
    addChatResponse(`Showing ${triageVal} items.`);
    return;
  }

  // Show collection
  const showMatch = lower.match(/(?:show|open|view)\s+(?:me\s+)?(?:the\s+)?(?:collection\s+)?["']?(.+?)["']?(?:\s+collection)?$/);
  if (showMatch) {
    const name = showMatch[1].trim();
    const col = state.collections.find((c) => c.name.toLowerCase().includes(name));
    if (col) {
      setCollectionFilter(col.id);
      addChatResponse(`Showing collection "${col.name}".`);
    } else {
      addChatResponse(`No collection matching "${name}" found.`);
    }
    return;
  }

  // Search
  const searchMatch = lower.match(/(?:find|search(?:\s+for)?)\s+(.+)/);
  if (searchMatch) {
    const query = searchMatch[1].trim();
    state.q = query;
    const searchInput = $("#search");
    if (searchInput) searchInput.value = query;
    await loadAssets();
    addChatResponse(`Searching for "${query}".`);
    return;
  }

  // Review
  if (lower.match(/\breview\b/)) {
    enterReview();
    return;
  }

  addChatResponse("I didn't understand that. Try: 'make a collection called Kitchen', 'show keepers', 'find cabinets', or 'review'.", 12000);
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

// ─── Search ──────────────────────────────────────────────────────────────────────

const searchInput = $("#search");
if (searchInput) {
  searchInput.addEventListener("input", (e) => {
    state.q = e.target.value || "";
    if (semanticQueryFromInput(state.q)) return; // don't auto-search for sem:
    loadAssets();
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadAssets();
  });
}

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

(async () => {
  try {
    await Promise.all([loadCollections(), loadFacets()]);
    await loadAssets();
  } catch (e) {
    const grid = $("#grid");
    if (grid) grid.innerHTML = `<div class="empty-state">Unable to load: ${escapeHtml(formatApiError(e))}</div>`;
  }
})();
