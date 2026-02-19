const state = {
  assets: [],
  collections: [],
  activeCollectionId: "",
  viewCollectionId: "",
  selected: new Set(),
  expanded: new Set(),
  q: "",
  sources: new Set(),
  boards: new Set(),
  labels: new Set(),
  labelMatchMode: "any",
  mediaStatuses: new Set(),
  contentKinds: new Set(),
  creators: new Set(),
  modalAsset: null,
  annotations: [],
  selectMode: true,
  facets: { sources: [], boards: [], labels: [], media_statuses: [], content_kinds: [], creators: [] },
  tray: [],
  dragging: null,
  activeAnnotationId: null,
  noteTimers: {},
  assetsRequestSeq: 0,
  semanticMode: false,
  error: "",
  initComplete: false,
  hasMore: false,
  loadingAssets: false,
  scanImportBusy: false,
  photoImportBusy: false,
  scanImportFile: null,
  photoImportFile: null,
  mediaDefaultsSeeded: false,
  canvasMode: "main",
  view: "grid",
  filterOpen: { sources: true },
  filtersExpanded: false,
  gridZoom: localStorage.getItem("gridZoom") || "m",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const IMAGE_SUFFIX_RE = /\.(jpg|jpeg|png|webp|gif|bmp|svg)(\?.*)?$/i;
const PDF_FILE_EXT_RE = /\.pdf$/i;
const IMAGE_FILE_EXT_RE = /\.(jpg|jpeg|png|webp|gif|bmp|heic|heif|tif|tiff)$/i;
const EXTREME_ASPECT_RATIO_MAX = 1.8;
const EXTREME_ASPECT_RATIO_MIN = 0.8;
const ASSETS_PAGE_SIZE = 240;

const escapeHtml = Shared.escapeHtml;

function applyZoom() {
  const grid = $("#grid");
  if (!grid) return;
  grid.className = `grid zoom-${state.gridZoom}`;
  const zoomControl = $("#zoomControl");
  if (zoomControl) {
    zoomControl.querySelectorAll("button[data-zoom]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.zoom === state.gridZoom);
    });
  }
}

function setZoom(level) {
  state.gridZoom = level;
  localStorage.setItem("gridZoom", level);
  applyZoom();
}

function asList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter((x) => x !== null && x !== undefined && `${x}`.trim() !== "");
  return [value];
}

function parseAi(a) {
  if (!a.ai_json) return null;
  try {
    return JSON.parse(a.ai_json);
  } catch {
    return null;
  }
}

function aiLabelCount(ai) {
  if (!ai) return 0;
  const keys = [
    "rooms",
    "elements",
    "materials",
    "colors",
    "styles",
    "lighting",
    "fixtures",
    "appliances",
    "text_in_image",
    "brands_products",
    "tags",
  ];
  return keys.reduce((acc, k) => acc + asList(ai[k]).length, 0);
}

function topTags(ai, max = 5) {
  if (!ai) return [];
  const buckets = [
    "rooms",
    "elements",
    "materials",
    "colors",
    "styles",
    "lighting",
    "fixtures",
    "appliances",
    "tags",
  ];
  const out = [];
  const seen = new Set();
  for (const key of buckets) {
    for (const item of asList(ai[key])) {
      const v = `${item}`.trim();
      if (!v || seen.has(v)) continue;
      seen.add(v);
      out.push(v);
      if (out.length >= max) return out;
    }
  }
  return out;
}

function renderChips(items) {
  const list = asList(items);
  if (!list.length) {
    return '<span class="chip empty">none</span>';
  }
  return list.map((x) => `<span class="chip">${escapeHtml(x)}</span>`).join("");
}

function renderTagSections(ai) {
  if (!ai) return "";
  const sections = [
    ["Rooms", "rooms"],
    ["Elements", "elements"],
    ["Materials", "materials"],
    ["Colors", "colors"],
    ["Styles", "styles"],
    ["Lighting", "lighting"],
    ["Fixtures", "fixtures"],
    ["Appliances", "appliances"],
    ["Text in image", "text_in_image"],
    ["Brands / Products", "brands_products"],
    ["Tags", "tags"],
  ];
  return sections
    .map(
      ([label, key]) => `
      <div class="tagSection">
        <div class="tagTitle">${label}</div>
        <div class="chips">${renderChips(ai[key])}</div>
      </div>`
    )
    .join("");
}

const api = Shared.api;

async function apiUpload(path, formData) {
  const res = await fetch(path, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

const formatApiError = Shared.formatApiError;

function showFatalUiError(err) {
  const message = formatApiError(err);
  state.error = message;
  const narrative = $("#canvasNarrative");
  if (narrative) narrative.textContent = `The canvas could not be loaded. ${message}`;
  const stats = $("#stats");
  if (stats) stats.textContent = "Unable to load items";
  const filters = $("#filters");
  if (filters) filters.innerHTML = `<div class="muted">Unable to load filters: ${escapeHtml(message)}</div>`;
  const grid = $("#grid");
  if (grid && state.assets.length === 0) {
    grid.innerHTML = `<div class="muted">Unable to load items: ${escapeHtml(message)}</div>`;
  }
  updateLoadMoreButton();
}

function looksLikeImageRef(value) {
  const text = `${value || ""}`.trim().toLowerCase();
  if (!text) return false;
  if (IMAGE_SUFFIX_RE.test(text)) return true;
  if (text.includes(".jpg?") || text.includes(".jpeg?") || text.includes(".png?")) return true;
  return false;
}

function sourceHost(value) {
  const text = `${value || ""}`.trim();
  if (!text) return "";
  try {
    return new URL(text).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function previewForAsset(a) {
  if (a.thumb_path) return { url: `/media/${a.id}?kind=thumb`, kind: "thumb" };
  if (a.stored_path && looksLikeImageRef(a.stored_path)) return { url: `/media/${a.id}?kind=original`, kind: "stored" };
  if (a.image_url && looksLikeImageRef(a.image_url)) return { url: a.image_url, kind: "remote" };
  return { url: "", kind: "none" };
}

function shouldContainFit(img) {
  if (!img || !img.naturalWidth || !img.naturalHeight) return false;
  const ratio = img.naturalWidth / img.naturalHeight;
  return ratio > EXTREME_ASPECT_RATIO_MAX || ratio < EXTREME_ASPECT_RATIO_MIN;
}

function thumbFor(a) {
  return previewForAsset(a).url;
}

function isHttpUrl(value) {
  const text = `${value || ""}`.trim();
  if (!text) return false;
  try {
    const parsed = new URL(text);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function isPdfFile(file) {
  if (!file) return false;
  const name = `${file.name || ""}`.trim();
  const mime = `${file.type || ""}`.trim().toLowerCase();
  return PDF_FILE_EXT_RE.test(name) || mime === "application/pdf";
}

function isImageFile(file) {
  if (!file) return false;
  const name = `${file.name || ""}`.trim();
  const mime = `${file.type || ""}`.trim().toLowerCase();
  if (mime.startsWith("image/")) return true;
  return IMAGE_FILE_EXT_RE.test(name);
}

function setSingleFileSelection(input, file, stateKey) {
  state[stateKey] = file || null;
  if (!input) return;
  if (!file) {
    input.value = "";
    return;
  }
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
  } catch {
    // Some browsers block synthetic FileList assignment; state fallback still works.
  }
}

function wireSingleFileDropZone(options) {
  const zone = options.zone;
  const input = options.input;
  if (!zone || !input) return;
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  const busy = () => (typeof options.isBusy === "function" ? !!options.isBusy() : false);
  const activate = (event) => {
    prevent(event);
    if (busy()) return;
    zone.classList.add("dragActive");
  };
  const clear = (event) => {
    prevent(event);
    zone.classList.remove("dragActive");
  };
  ["dragenter", "dragover"].forEach((evt) => zone.addEventListener(evt, activate));
  ["dragleave", "dragend"].forEach((evt) => zone.addEventListener(evt, clear));
  zone.addEventListener("drop", (event) => {
    clear(event);
    if (busy()) return;
    const file = (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]) || null;
    if (!file) return;
    if (!options.accept(file)) {
      if (options.invalidMessage) Shared.showToast(options.invalidMessage, { type: "error" });
      return;
    }
    setSingleFileSelection(input, file, options.stateKey);
    if (typeof options.onSelected === "function") options.onSelected(file);
  });
}

function getCollectionById(collectionId) {
  if (!collectionId) return null;
  return state.collections.find((c) => c.id === collectionId) || null;
}

function getActiveCollection() {
  return getCollectionById(state.activeCollectionId);
}

function getViewCollection() {
  return getCollectionById(state.viewCollectionId);
}

function getHiddenCollection() {
  return state.collections.find((c) => `${c.name || ""}`.trim().toLowerCase() === "hidden") || null;
}

function updateLoadMoreButton() {
  const btn = $("#loadMore");
  if (!btn) return;
  const visible = !state.semanticMode && !state.error && state.hasMore;
  btn.hidden = !visible;
  btn.disabled = !visible || state.loadingAssets;
  btn.textContent = state.loadingAssets ? "Loading…" : "Load More";
}

function englishJoin(values) {
  const items = values.filter((x) => `${x || ""}`.trim() !== "");
  if (!items.length) return "";
  if (items.length === 1) return items[0];
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

function summarizeValues(values, max = 4) {
  const items = values.filter((x) => `${x || ""}`.trim() !== "");
  if (items.length <= max) return englishJoin(items);
  return `${englishJoin(items.slice(0, max))} and ${items.length - max} more`;
}

function sourceLabel(value) {
  const map = { pinterest: "Pinterest", facebook: "Facebook", scan: "Scan", photo: "Photo" };
  return map[value] || value;
}

function effectiveSelection(setValues, facetItems, facetKey) {
  const selected = Array.from(setValues).map((x) => `${x || ""}`.trim()).filter(Boolean);
  if (!selected.length) return [];
  const all = (facetItems || []).map((it) => `${it[facetKey] || ""}`.trim()).filter(Boolean);
  const allUnique = Array.from(new Set(all));
  if (allUnique.length > 0 && selected.length >= allUnique.length) return [];
  return selected;
}

function updateLabelModeButton() {
  const btn = $("#toggleLabelMode");
  if (!btn) return;
  btn.textContent = state.labelMatchMode === "all" ? "AI Tags: All" : "AI Tags: Any";
}

function filtersNarrativeParts() {
  const parts = [];
  const selectedSources = effectiveSelection(state.sources, state.facets.sources, "source").map(sourceLabel);
  const selectedBoards = effectiveSelection(state.boards, state.facets.boards, "board");
  const selectedLabels = effectiveSelection(state.labels, state.facets.labels, "label");
  const selectedMedia = effectiveSelection(state.mediaStatuses, state.facets.media_statuses, "media_status").map((v) =>
    prettyFacetValue("media_statuses", v)
  );
  const selectedKinds = effectiveSelection(state.contentKinds, state.facets.content_kinds, "content_kind").map((v) =>
    prettyFacetValue("content_kinds", v)
  );
  const selectedCreators = effectiveSelection(state.creators, state.facets.creators, "creator_name");

  if (selectedSources.length) parts.push(`Source: ${summarizeValues(selectedSources)}`);
  if (selectedBoards.length) parts.push(`Source tags: ${summarizeValues(selectedBoards)}`);
  if (selectedLabels.length) {
    const labelModeText = state.labelMatchMode === "all" ? "all selected tags" : "any selected tag";
    parts.push(`AI tags (${labelModeText}): ${summarizeValues(selectedLabels)}`);
  }
  if (selectedMedia.length) parts.push(`Media type: ${summarizeValues(selectedMedia)}`);
  if (selectedKinds.length) parts.push(`Record type: ${summarizeValues(selectedKinds)}`);
  if (selectedCreators.length) parts.push(`Creator/page: ${summarizeValues(selectedCreators)}`);
  return parts;
}

function mediaNarrativeClause(selectedMediaStatuses) {
  const unique = Array.from(new Set(selectedMediaStatuses));
  if (unique.length === 2 && unique.includes("image") && unique.includes("link_only")) {
    return "have an image or a link";
  }
  const parts = selectedMediaStatuses.map((value) => {
    if (value === "image") return "have an image";
    if (value === "link_only") return "have a link";
    if (value === "metadata_only") return "are metadata only";
    return `match "${value.replace(/_/g, " ")}"`;
  });
  if (!parts.length) return "";
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return `${parts[0]} or ${parts[1]}`;
  return `${parts.slice(0, -1).join(", ")}, or ${parts[parts.length - 1]}`;
}

function trayAssetIdsSet() {
  return new Set(state.tray.map((item) => item.id));
}

function memberAssetIds(item) {
  const explicit = asList(item && item.scan_group_member_ids)
    .map((id) => `${id || ""}`.trim())
    .filter(Boolean);
  if (explicit.length) return Array.from(new Set(explicit));
  const fallback = `${(item && item.id) || ""}`.trim();
  return fallback ? [fallback] : [];
}

function expandAssetIds(ids) {
  const byId = new Map();
  for (const item of state.assets) byId.set(item.id, item);
  for (const item of state.tray) if (!byId.has(item.id)) byId.set(item.id, item);
  const expanded = [];
  const seen = new Set();
  for (const rawId of ids || []) {
    const id = `${rawId || ""}`.trim();
    if (!id) continue;
    const item = byId.get(id);
    const members = item ? memberAssetIds(item) : [id];
    for (const memberId of members) {
      if (!memberId || seen.has(memberId)) continue;
      seen.add(memberId);
      expanded.push(memberId);
    }
  }
  return expanded;
}

function buildCanvasNarrative() {
  if (state.error) {
    return "The canvas could not be loaded right now. Please try again.";
  }

  if (state.canvasMode === "tray") {
    const textQuery = `${state.q || ""}`.trim();
    if (state.tray.length === 0) {
      return "The tray canvas is empty. Add items from the main canvas to start curating what you want to share.";
    }
    if (state.assets.length === 0 && textQuery) {
      return `The tray canvas has no items that match "${textQuery}".`;
    }
    if (textQuery) {
      return `The tray canvas is showing items from your share cart that match "${textQuery}".`;
    }
    return "The tray canvas is showing items from your share cart.";
  }

  const viewCollection = getViewCollection();
  const semanticQuery = semanticQueryFromInput(state.q);
  const textQuery = semanticQuery ? "" : `${state.q || ""}`.trim();
  const selectedSources = effectiveSelection(state.sources, state.facets.sources, "source");
  const selectedBoards = effectiveSelection(state.boards, state.facets.boards, "board");
  const selectedLabels = effectiveSelection(state.labels, state.facets.labels, "label");
  const selectedMedia = effectiveSelection(state.mediaStatuses, state.facets.media_statuses, "media_status");
  const selectedKinds = effectiveSelection(state.contentKinds, state.facets.content_kinds, "content_kind");
  const selectedCreators = effectiveSelection(state.creators, state.facets.creators, "creator_name");
  const hasFilters =
    selectedSources.length > 0 ||
    selectedBoards.length > 0 ||
    selectedLabels.length > 0 ||
    selectedMedia.length > 0 ||
    selectedKinds.length > 0 ||
    selectedCreators.length > 0;
  let base = viewCollection
    ? `The canvas is showing items from the "${viewCollection.name}" collection`
    : "The canvas is showing all items";

  if (semanticQuery) {
    base = viewCollection
      ? `The canvas is showing items from the "${viewCollection.name}" collection similar to "${semanticQuery}"`
      : `The canvas is showing items similar to "${semanticQuery}"`;
  } else if (textQuery) {
    base = viewCollection
      ? `The canvas is showing items from the "${viewCollection.name}" collection that match "${textQuery}"`
      : `The canvas is showing items that match "${textQuery}"`;
  }

  if (state.assets.length === 0) {
    base = base.replace("is showing", "currently has no");
    if (!base.endsWith(".")) base += ".";
    return `${base} Try changing the search term or clearing one or more filters.`;
  }

  const mediaOnlyFilter =
    hasFilters &&
    selectedMedia.length > 0 &&
    selectedSources.length === 0 &&
    selectedBoards.length === 0 &&
    selectedLabels.length === 0 &&
    selectedKinds.length === 0 &&
    selectedCreators.length === 0;
  if (!viewCollection && !semanticQuery && !textQuery && mediaOnlyFilter) {
    return `The canvas is showing all items filtered by those that ${mediaNarrativeClause(selectedMedia)}.`;
  }

  const filterParts = filtersNarrativeParts();
  if (!filterParts.length) return `${base}.`;
  return `${base}. Filters applied: ${filterParts.join("; ")}.`;
}

function semanticQueryFromInput(value) {
  const text = `${value || ""}`.trim();
  if (!text) return "";
  const prefixes = ["sem:", "similar:"];
  for (const p of prefixes) {
    if (text.toLowerCase().startsWith(p)) {
      return text.slice(p.length).trim();
    }
  }
  return "";
}

function semanticSourceFilter() {
  if (state.sources.size === 0) return "";
  return Array.from(state.sources).join(",");
}

function shortRef(value, max = 64) {
  const text = `${value || ""}`.trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function displayTitle(assetLike) {
  const source = `${(assetLike && assetLike.source) || ""}`.trim().toLowerCase();
  let title = `${(assetLike && assetLike.title) || ""}`.trim();
  if (!title) return "(untitled)";
  if (source === "facebook") {
    title = title
      .replace(/^.{1,40}\s+saved a (?:link|product|video)(?: from)?\s+/i, "")
      .replace(/^.{1,40}\s+saved a (?:link|product|video)\.?$/i, "")
      .trim();
    if (!title) {
      const host = sourceHost(
        `${(assetLike && assetLike.source_ref) || (assetLike && assetLike.image_url) || ""}`
      );
      return host ? `Saved from ${host}` : "(untitled)";
    }
  }
  return title || "(untitled)";
}

function isMobilePanelMode() {
  return window.matchMedia("(max-width: 1100px)").matches;
}

function closeMobilePanels() {
  document.body.classList.remove("mobile-left-open", "mobile-right-open");
}

function openMobilePanel(side) {
  if (!isMobilePanelMode()) return;
  closeMobilePanels();
  if (side === "right") {
    document.body.classList.add("mobile-right-open");
    return;
  }
  document.body.classList.add("mobile-left-open");
}

async function selectCollection(collectionId) {
  state.activeCollectionId = collectionId || "";
  state.viewCollectionId = collectionId || "";
  renderCollections();
  setStats();
  closeMobilePanels();
  await loadAssets();
}

function setStats() {
  const activeCollection = getActiveCollection();
  const viewCollection = getViewCollection();
  const trayIds = trayAssetIdsSet();
  const traySelectedCount = Array.from(state.selected).filter((id) => trayIds.has(id)).length;
  const trayMode = state.canvasMode === "tray";
  const reviewBtn = $("#reviewCollection");
  const destination = activeCollection ? ` • Add-to "${activeCollection.name}"` : "";
  const narrative = buildCanvasNarrative();
  $("#canvasNarrative").textContent = narrative;
  $("#stats").textContent = trayMode
    ? `${state.assets.length} tray item${state.assets.length === 1 ? "" : "s"} shown`
    : `${state.assets.length} items shown${destination}`;
  const selectionBar = $("#selectionBar");
  if (selectionBar) {
    selectionBar.hidden = state.selected.size === 0;
    const label = $("#selectionLabel");
    if (label) label.textContent = `${state.selected.size} selected`;
  }
  $("#addSelectedToCollection").textContent = activeCollection
    ? `Add to "${activeCollection.name}"`
    : "Select Collection to Add";
  $("#addSelectedToCollection").disabled = state.selected.size === 0 || !activeCollection || trayMode;
  $("#addSelected").textContent = activeCollection ? "Add to Tray (Optional)" : "Add to Tray";
  $("#addSelected").disabled = state.selected.size === 0 || trayMode;
  $("#removeSelectedFromCollection").textContent = viewCollection
    ? `Remove from "${viewCollection.name}"`
    : "Remove from Collection";
  $("#removeSelectedFromCollection").disabled = state.selected.size === 0 || !viewCollection || trayMode;
  $("#removeSelectedFromTray").disabled = traySelectedCount === 0;
  $("#addFiltered").textContent = activeCollection ? `Add Filtered to "${activeCollection.name}"` : "Add Filtered to Tray";
  $("#addFiltered").disabled = state.assets.length === 0 || trayMode;
  $("#clearSelection").disabled = state.selected.size === 0;
  if (reviewBtn) {
    reviewBtn.disabled = !viewCollection || trayMode;
    reviewBtn.textContent = viewCollection ? `Review "${viewCollection.name}"` : "Review Collection";
    reviewBtn.classList.toggle("primaryAction", !!viewCollection && !trayMode);
  }
  $("#showTrayCanvas").textContent = trayMode ? "Tray Canvas On" : "Show Tray Canvas";
  $("#showTrayCanvas").disabled = !trayMode && state.tray.length === 0;
  $("#showAll").textContent = trayMode ? "Back to Main Canvas" : "Show All";
  if (trayMode) {
    $("#collectionHint").textContent = `Tray canvas is active. Collections are separate; use "Add Tray to Collection" when your tray is ready.`;
  } else if (!activeCollection) {
    $("#collectionHint").textContent =
      state.selected.size > 0
        ? 'Pick a collection for primary add, or use tray as a temporary holding area.'
        : "No collection selected. Select one to enable direct add; tray remains optional.";
  } else if (!viewCollection) {
    $("#collectionHint").textContent = `Selected collection: "${activeCollection.name}". Canvas is showing all items.`;
  } else if (state.tray.length > 0) {
    $("#collectionHint").textContent = `Viewing "${viewCollection.name}". Use Review (opens a new tab) to inspect similarity groups. Direct add is primary; tray has ${state.tray.length} optional item${state.tray.length === 1 ? "" : "s"}.`;
  } else {
    $("#collectionHint").textContent = `Viewing "${viewCollection.name}". Use Review (opens a new tab) to inspect similarity groups, then keep adding selected items directly.`;
  }
  $("#trayCount").textContent = `${state.tray.length} items`;
  const addTrayLabel = activeCollection ? `Add Tray to "${activeCollection.name}"` : "Add Tray to Collection";
  const disableTrayActions = state.tray.length === 0;
  const disableAddTrayToCollection = disableTrayActions || !activeCollection;
  $("#createFromTray").disabled = disableTrayActions;
  $("#createFromTrayTop").disabled = disableTrayActions;
  $("#addTrayToCollection").textContent = addTrayLabel;
  $("#addTrayToCollectionTop").textContent = addTrayLabel;
  $("#addTrayToCollection").disabled = disableAddTrayToCollection;
  $("#addTrayToCollectionTop").disabled = disableAddTrayToCollection;
  $("#clearTray").disabled = disableTrayActions;
  $("#clearTrayTop").disabled = disableTrayActions;
  updateLoadMoreButton();
}

function renderCollections() {
  renderGroups();
}

function renderGroups() {
  const wrap = $("#groups");
  if (!wrap) return;
  wrap.innerHTML = "";
  const searchVal = ($("#groupSearch")?.value || "").toLowerCase().trim();

  // Boards section (from facets)
  const boards = (state.facets.boards || []).filter((it) => {
    if (!it.board) return false;
    if (searchVal && !it.board.toLowerCase().includes(searchVal)) return false;
    return true;
  });
  if (boards.length) {
    const header = document.createElement("div");
    header.className = "groupsHeader";
    header.textContent = "Boards";
    wrap.appendChild(header);
    for (const it of boards) {
      const isActive = state.boards.has(it.board);
      const el = document.createElement("div");
      el.className = `listItem groupItem${isActive ? " on" : ""}`;
      el.innerHTML = `<div class="groupItemRow"><span class="groupItemName">${escapeHtml(it.board)}</span><span class="groupItemCount">${it.n}</span></div>`;
      el.onclick = async () => {
        if (state.boards.has(it.board)) state.boards.delete(it.board);
        else state.boards.add(it.board);
        renderGroups();
        await loadAssets();
      };
      wrap.appendChild(el);
    }
  }

  // Collections section
  const collections = state.collections.filter((c) => {
    if (!searchVal) return true;
    return c.name.toLowerCase().includes(searchVal);
  });
  if (collections.length) {
    const header = document.createElement("div");
    header.className = "groupsHeader";
    header.textContent = "My Collections";
    wrap.appendChild(header);
    for (const c of collections) {
      const isViewing = c.id === state.viewCollectionId;
      const isDestination = c.id === state.activeCollectionId;
      const stateText = isViewing ? "Viewing" : isDestination ? "Destination" : "";
      const el = document.createElement("div");
      el.className = `listItem groupItem${isViewing ? " on" : ""}`;
      el.innerHTML = `<div class="groupItemRow"><span class="groupItemName">${escapeHtml(c.name)}</span><span class="groupItemCount">${c.count}</span></div>${stateText ? `<div class="muted" style="font-size:11px;margin-top:2px">${stateText}</div>` : ""}`;
      el.onclick = async () => {
        await selectCollection(c.id);
      };
      wrap.appendChild(el);
    }
  }

  if (!boards.length && !collections.length) {
    wrap.innerHTML = searchVal ? '<div class="muted">No matching groups.</div>' : '<div class="muted">No groups yet.</div>';
  }
  updateFiltersBadge();
}

function updateFiltersBadge() {
  const badge = $("#filtersBadge");
  if (!badge) return;
  const count = state.sources.size + state.labels.size + state.mediaStatuses.size + state.contentKinds.size + state.creators.size;
  badge.textContent = count > 0 ? `(${count})` : "";
}

function renderSkeletons(count) {
  if (count === undefined) count = 12;
  const wrap = $("#grid");
  wrap.innerHTML = "";
  applyZoom();
  for (let i = 0; i < count; i++) {
    const el = document.createElement("div");
    el.className = "skeleton-card";
    el.innerHTML = '<div class="skeleton-thumb"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>';
    wrap.appendChild(el);
  }
}

function renderGrid() {
  const wrap = $("#grid");
  wrap.innerHTML = "";
  applyZoom();
  if (!state.assets.length) {
    const isFiltered = state.q || state.sources.size || state.boards.size ||
      state.labels.size || state.contentKinds.size || state.creators.size;
    const message = state.error
      ? `Unable to load items: ${escapeHtml(state.error)}`
      : isFiltered ? "No items match your current filters." : "No items yet.";
    const action = state.error ? ""
      : isFiltered ? '<button class="miniBtn" id="emptyStateClear">Clear all filters</button>'
      : "<p>Use the import buttons above to add your first items.</p>";
    wrap.innerHTML = `<div class="empty-state"><div class="empty-state-message">${message}</div>${action}</div>`;
    const clearBtn = wrap.querySelector("#emptyStateClear");
    if (clearBtn) clearBtn.onclick = async () => { resetFiltersAndSearch(); await loadFacets({ seedDefaultMedia: false }); await loadAssets(); };
    setStats();
    return;
  }
  for (const a of state.assets) {
    const el = document.createElement("div");
    el.className = `card ${state.selected.has(a.id) ? "selected" : ""} ${state.expanded.has(a.id) ? "expanded" : ""}`;
    el.dataset.id = a.id;
    const preview = previewForAsset(a);
    const img = preview.url;
    const ai = a.ai;
    const summary = (ai && ai.summary) || a.ai_summary || a.description || "";
    const imageType = ai && ai.image_type ? `${ai.image_type}` : "";
    const labelCount = aiLabelCount(ai);
    const top = topTags(ai, 6);
    const host = sourceHost(a.source_ref || a.image_url || "");
    const placeholderLabel = host ? `No preview (${host})` : "No preview image";
    const metaParts = [];
    if (typeof a.score === "number") {
      metaParts.push(`Similarity: ${(a.score * 100).toFixed(1)}%`);
    }
    if (a.board) metaParts.push(`Board: ${a.board}`);
    metaParts.push(`Source: ${a.source}`);
    if (a.source === "scan" && Number(a.scan_doc_pages || 0) > 1) {
      metaParts.push(`Pages: ${Number(a.scan_doc_pages)}`);
    }
    if (a.creator_name) metaParts.push(`Creator: ${a.creator_name}`);
    if (a.content_kind) metaParts.push(`Type: ${a.content_kind}`);
    if (a.media_status) metaParts.push(`Media: ${a.media_status}`);
    if (imageType) metaParts.push(`Image: ${imageType}`);
    const meta = metaParts.join(" • ");
    const sourceRef = `${a.source_ref || ""}`.trim();
    const sourceRefDisplay = shortRef(sourceRef);
    const importedDate = `${a.imported_at || ""}`.slice(0, 10);
    const createdDate = `${a.created_at || ""}`.slice(0, 10);
    el.innerHTML = `
      <div class="thumb">
        ${
          img
            ? `<img src="${escapeHtml(img)}" loading="lazy" alt="" />`
            : `<div class="thumbPlaceholder"><div class="thumbPlaceholderText">${escapeHtml(placeholderLabel)}</div></div>`
        }
        <div class="badge">${a.source}</div>
        <label class="selectBox"><input type="checkbox" ${state.selected.has(a.id) ? "checked" : ""} /></label>
      </div>
      <div class="cardBody">
        <div class="cardTitle">${escapeHtml(displayTitle(a))}</div>
        ${summary ? `<div class="cardSummary">${escapeHtml(summary)}</div>` : `<div class="cardSummary">Not tagged yet.</div>`}
        <div class="cardMeta">${escapeHtml(meta)}</div>
        ${ai ? `<div class="compactTags">${renderChips(top)}</div>` : ""}
        ${ai ? `<div class="tagGrid">${renderTagSections(ai)}</div>` : ""}
        <div class="expandedInfo">
          <div class="expandedRow">
            ${
              sourceRef
                ? `<a class="sourceRefInline" href="${escapeHtml(sourceRef)}" target="_blank" rel="noopener">${escapeHtml(sourceRefDisplay)}</a>`
                : `<span class="muted">No source link</span>`
            }
          </div>
          ${
            importedDate
              ? `<div class="expandedRow">Imported: ${escapeHtml(importedDate)}</div>`
              : ""
          }
          ${
            createdDate && createdDate !== importedDate
              ? `<div class="expandedRow">Created: ${escapeHtml(createdDate)}</div>`
              : ""
          }
          ${!ai ? '<div class="expandedRow muted">No AI tags available for this item.</div>' : ""}
          ${ai ? `<div class="expandedRow muted">Model: ${escapeHtml(a.ai_model || a.ai_provider || "—")}</div>` : ""}
        </div>
        <div class="cardFooter">
          ${labelCount > 0
            ? `<div class="tag-status tagged">${labelCount} tags</div>`
            : `<div class="tag-status untagged">Not tagged</div>`}
          <button class="miniBtn annotateBtn" data-annotate>Annotate</button>
        </div>
      </div>
    `;
    const imageEl = el.querySelector(".thumb img");
    const thumbEl = el.querySelector(".thumb");
    if (imageEl) {
      const applyFit = () => {
        if (!thumbEl) return;
        thumbEl.classList.toggle("fitContain", shouldContainFit(imageEl));
      };
      imageEl.addEventListener("load", applyFit);
      if (typeof imageEl.decode === "function") {
        imageEl.decode().then(applyFit).catch(() => {});
      } else {
        setTimeout(applyFit, 0);
      }
      if (imageEl.complete) applyFit();
      imageEl.addEventListener("error", () => {
        if (!thumbEl || thumbEl.querySelector(".thumbPlaceholder")) return;
        imageEl.remove();
        const placeholder = document.createElement("div");
        placeholder.className = "thumbPlaceholder";
        const text = document.createElement("div");
        text.className = "thumbPlaceholderText";
        text.textContent = placeholderLabel;
        placeholder.appendChild(text);
        thumbEl.prepend(placeholder);
      });
    }
    const checkbox = el.querySelector("input");
    checkbox.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleSelect(a.id);
      updateCardState(a.id);
    });
    el.querySelector("[data-annotate]").addEventListener("click", (e) => {
      e.stopPropagation();
      openModal(a);
    });
    const sourceLinkEl = el.querySelector(".sourceRefInline");
    if (sourceLinkEl) {
      sourceLinkEl.addEventListener("click", (e) => {
        e.stopPropagation();
        e.preventDefault();
        const href = sourceLinkEl.getAttribute("href");
        if (href) window.open(href, "_blank", "noopener,noreferrer");
      });
    }
    el.onclick = () => {
      if (state.expanded.has(a.id)) state.expanded.delete(a.id);
      else state.expanded.add(a.id);
      updateCardState(a.id);
    };
    wrap.appendChild(el);
  }
  setStats();
}

function updateCardState(id) {
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (!el) return;
  el.classList.toggle("selected", state.selected.has(id));
  el.classList.toggle("expanded", state.expanded.has(id));
  const cb = el.querySelector("input[type=checkbox]");
  if (cb) cb.checked = state.selected.has(id);
  setStats();
}

function toggleSelect(id) {
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  setStats();
}

async function loadCollections() {
  const data = await api("/api/collections");
  state.collections = data.collections;
  if (state.activeCollectionId && !state.collections.some((c) => c.id === state.activeCollectionId)) {
    state.activeCollectionId = "";
  }
  if (state.viewCollectionId && !state.collections.some((c) => c.id === state.viewCollectionId)) {
    state.viewCollectionId = "";
  }
  renderCollections();
  setStats();
}

async function loadTray() {
  const data = await api("/api/tray");
  state.tray = data.items;
  renderTray();
  setStats();
  if (state.canvasMode === "tray") {
    await loadAssets();
  }
}

function assetMatchesClientFilters(asset) {
  if (state.mediaStatuses.size > 0 && !state.mediaStatuses.has(`${asset.media_status || ""}`)) return false;
  if (state.contentKinds.size > 0 && !state.contentKinds.has(`${asset.content_kind || ""}`)) return false;
  if (state.creators.size > 0 && !state.creators.has(`${asset.creator_name || ""}`)) return false;
  return true;
}

async function loadAssets(append = false) {
  if (append && (state.loadingAssets || !state.hasMore || state.semanticMode || state.canvasMode === "tray")) return;
  const requestSeq = append ? state.assetsRequestSeq : ++state.assetsRequestSeq;
  const semanticQuery = state.canvasMode === "tray" ? "" : semanticQueryFromInput(state.q);
  state.semanticMode = state.canvasMode === "tray" ? false : !!semanticQuery;
  state.loadingAssets = true;
  if (!append) renderSkeletons();
  updateLoadMoreButton();
  try {
    if (state.canvasMode === "tray") {
      const query = `${state.q || ""}`.trim().toLowerCase();
      const rows = state.tray
        .map((item) => ({ ...item, ai: parseAi(item) }))
        .filter((item) => {
          if (!query) return true;
          const haystack = [
            displayTitle(item),
            item.description || "",
            item.source_ref || "",
            item.source || "",
            item.board || "",
          ]
            .join(" ")
            .toLowerCase();
          return haystack.includes(query);
        });
      if (requestSeq !== state.assetsRequestSeq) return;
      state.error = "";
      state.assets = rows;
      state.hasMore = false;
      renderGrid();
      return;
    }

    if (semanticQuery) {
      const source = encodeURIComponent(semanticSourceFilter());
      const q = encodeURIComponent(semanticQuery);
      const data = await api(`/api/search/similar?q=${q}&source=${source}&limit=${ASSETS_PAGE_SIZE}`);
      if (requestSeq !== state.assetsRequestSeq) return;
      state.error = "";
      const rows = (data.results || []).map((a) => ({ ...a, ai: parseAi(a) })).filter(assetMatchesClientFilters);
      state.assets = rows;
      state.hasMore = false;
      renderGrid();
      return;
    }

    const q = encodeURIComponent(state.q || "");
    const source = encodeURIComponent(Array.from(state.sources).join(","));
    const board = encodeURIComponent(Array.from(state.boards).join(","));
    const label = encodeURIComponent(Array.from(state.labels).join(","));
    const labelMode = encodeURIComponent(state.labelMatchMode || "any");
    const mediaStatus = encodeURIComponent(Array.from(state.mediaStatuses).join(","));
    const contentKind = encodeURIComponent(Array.from(state.contentKinds).join(","));
    const creator = encodeURIComponent(Array.from(state.creators).join(","));
    const col = encodeURIComponent(state.viewCollectionId || "");
    const offset = append ? state.assets.length : 0;
    const data = await api(
      `/api/assets?q=${q}&source=${source}&board=${board}&label=${label}&label_mode=${labelMode}&media_status=${mediaStatus}&content_kind=${contentKind}&creator=${creator}&collection_id=${col}&limit=${ASSETS_PAGE_SIZE}&offset=${offset}`
    );
    if (requestSeq !== state.assetsRequestSeq) return;
    state.error = "";
    const rows = (data.assets || []).map((a) => ({ ...a, ai: parseAi(a) }));
    state.assets = append ? [...state.assets, ...rows] : rows;
    state.hasMore = rows.length === ASSETS_PAGE_SIZE;
    renderGrid();
  } catch (err) {
    if (requestSeq !== state.assetsRequestSeq) return;
    if (!append) {
      state.assets = [];
      state.hasMore = false;
    }
    state.error = formatApiError(err);
    renderGrid();
  } finally {
    if (requestSeq === state.assetsRequestSeq) {
      state.loadingAssets = false;
      updateLoadMoreButton();
    }
  }
}

function printModalAsset(asset) {
  if (!asset) return;
  const title = escapeHtml(displayTitle(asset));
  const metaParts = [];
  if (asset.source) metaParts.push(`Source: ${asset.source}`);
  if (asset.creator_name) metaParts.push(`Creator: ${asset.creator_name}`);
  if (asset.content_kind) metaParts.push(`Record type: ${asset.content_kind}`);
  const meta = escapeHtml(metaParts.join(" • "));
  const src = thumbFor(asset) || (asset.image_url ? escapeHtml(asset.image_url) : "");
  const notes = escapeHtml(asset.notes || "");
  const rawSourceRef = `${asset.source_ref || ""}`.trim();
  const sourceRef = escapeHtml(rawSourceRef);
  const sourceRefBlock = sourceRef
    ? isHttpUrl(rawSourceRef)
      ? `<div><a href="${sourceRef}" target="_blank" rel="noopener">Open source</a></div>`
      : `<div class="notes"><strong>Source:</strong> ${sourceRef}</div>`
    : "";
  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>${title}</title>
  <style>
    body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 22px; color: #1f2937; }
    h1 { margin: 0 0 6px 0; font-size: 20px; }
    .meta { margin-bottom: 14px; color: #4b5563; font-size: 13px; }
    .card { border: 1px solid #d1d5db; border-radius: 12px; padding: 16px; }
    img { max-width: 100%; border-radius: 8px; display: block; margin-bottom: 12px; }
    .notes { margin-top: 12px; white-space: pre-wrap; font-size: 14px; line-height: 1.4; }
    a { color: #1d4ed8; text-decoration: none; }
    @media print { body { margin: 0.35in; } .card { border: none; padding: 0; } }
  </style>
</head>
<body>
  <div class="card">
    <h1>${title}</h1>
    <div class="meta">${meta}</div>
    ${src ? `<img src="${src}" alt="" />` : ""}
    ${sourceRefBlock}
    ${notes ? `<div class="notes"><strong>Notes:</strong><br/>${notes}</div>` : ""}
  </div>
</body>
</html>`;
  const openPrintWindow = window.open("", "_blank");
  if (openPrintWindow) {
    try {
      openPrintWindow.document.write(html);
      openPrintWindow.document.close();
      setTimeout(() => {
        try {
          openPrintWindow.focus();
          openPrintWindow.print();
        } catch (err) {
          Shared.showToast(`Print failed: ${err && err.message ? err.message : err}`, { type: "error" });
        }
      }, 140);
      return;
    } catch {}
  }
  const frame = document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.right = "0";
  frame.style.bottom = "0";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.style.opacity = "0";
  frame.style.border = "0";
  frame.setAttribute("aria-hidden", "true");
  document.body.appendChild(frame);
  const cleanup = () => {
    setTimeout(() => {
      if (frame.parentNode) frame.parentNode.removeChild(frame);
    }, 1200);
  };
  try {
    const doc = frame.contentWindow && frame.contentWindow.document;
    if (!doc || !frame.contentWindow) throw new Error("embedded print frame unavailable");
    doc.open();
    doc.write(html);
    doc.close();
    setTimeout(() => {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch (err) {
        Shared.showToast(`Print failed: ${err && err.message ? err.message : err}`, { type: "error" });
      } finally {
        cleanup();
      }
    }, 160);
  } catch (err) {
    cleanup();
    Shared.showToast(`Print failed: ${err && err.message ? err.message : err}`, { type: "error" });
  }
}

function isViewingHiddenCollection() {
  const hidden = getHiddenCollection();
  if (!hidden) return false;
  return hidden.id === state.viewCollectionId;
}

async function openModal(asset) {
  state.modalAsset = asset;
  $("#modalTitle").textContent = displayTitle(asset);
  $("#modalMeta").textContent = `${asset.source} • ${asset.source_ref || ""}`;
  const hideBtn = $("#hideAssetBtn");
  if (hideBtn) hideBtn.textContent = isViewingHiddenCollection() ? "Unhide" : "Hide to Hidden";

  // Progressive image loading: show thumb immediately, swap to original when ready
  const modalImage = $("#modalImage");
  const previewUrl = thumbFor(asset);
  const hasThumb = !!asset.thumb_path;
  const originalUrl = asset.stored_path ? `/media/${asset.id}?kind=original` : null;
  if (previewUrl) {
    modalImage.src = previewUrl;
    modalImage.style.display = "block";
    modalImage.onload = () => {
      renderMarkers();
      renderFloatingNote();
      // Background-load higher-res original if we started with a thumbnail
      if (hasThumb && originalUrl && originalUrl !== previewUrl) {
        const hires = new Image();
        hires.onload = () => {
          if (state.modalAsset === asset) {
            modalImage.src = originalUrl;
            renderMarkers();
          }
        };
        hires.src = originalUrl;
      }
    };
  } else {
    modalImage.removeAttribute("src");
    modalImage.style.display = "none";
  }

  // Source link in notes area
  $("#assetNotes").value = asset.notes || "";
  const link = $("#sourceLink");
  if (asset.source_ref) {
    link.href = asset.source_ref;
    link.textContent = "Open original";
  } else {
    link.href = "#";
    link.textContent = "No source";
  }

  // View Source button: scan → original PDF, external source → source_ref, photo → stored file
  const viewSourceBtn = $("#viewSourceBtn");
  if (viewSourceBtn) {
    let targetUrl = null;
    if (asset.source === "scan") {
      targetUrl = `/media/${asset.id}?kind=pdf`;
    } else if (isHttpUrl(asset.source_ref)) {
      targetUrl = asset.source_ref;
    } else if (asset.stored_path) {
      targetUrl = `/media/${asset.id}?kind=original`;
    }
    if (targetUrl) {
      viewSourceBtn.style.display = "";
      viewSourceBtn.onclick = () => window.open(targetUrl, "_blank", "noopener");
    } else {
      viewSourceBtn.style.display = "none";
    }
  }

  $("#modal").classList.remove("hidden");
  await loadAnnotations(asset.id);
  renderAnnotations();
  renderMarkers();
}

function closeModal() {
  $("#modal").classList.add("hidden");
  state.modalAsset = null;
  state.annotations = [];
  $("#modalImage").style.display = "block";
}

async function hideModalAsset() {
  const asset = state.modalAsset;
  if (!asset) return;
  const memberIds = memberAssetIds(asset);
  const assetTitle = displayTitle(asset);
  if (isViewingHiddenCollection()) {
    const hidden = getHiddenCollection();
    if (!hidden) return;
    try {
      await api(`/api/collections/${encodeURIComponent(hidden.id)}/items/remove`, {
        method: "POST",
        body: JSON.stringify({ asset_ids: memberIds }),
      });
      const hiddenId = hidden.id;
      closeModal();
      await loadCollections();
      await loadAssets();
      Shared.showToast(`Unhid "${assetTitle}"`, {
        type: "success",
        actionLabel: "Undo",
        onAction: async () => {
          await api(`/api/collections/${encodeURIComponent(hiddenId)}/items`, {
            method: "POST",
            body: JSON.stringify({ asset_ids: memberIds }),
          });
          await loadCollections();
          await loadAssets();
          Shared.showToast("Restored to hidden.", { type: "info" });
        },
      });
    } catch (e) {
      Shared.showToast(`Unhide failed: ${formatApiError(e)}`, { type: "error" });
    }
    return;
  }
  try {
    const firstId = memberIds[0];
    if (!firstId) return;
    const hiddenRes = await api(`/api/assets/${encodeURIComponent(firstId)}/hide`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    const hiddenCollectionId = `${hiddenRes.hidden_collection_id || ""}`.trim();
    if (hiddenCollectionId && memberIds.length > 1) {
      await api(`/api/collections/${encodeURIComponent(hiddenCollectionId)}/items`, {
        method: "POST",
        body: JSON.stringify({ asset_ids: memberIds.slice(1) }),
      });
    }
    closeModal();
    await loadCollections();
    await loadAssets();
    Shared.showToast(`Hidden "${assetTitle}"`, {
      type: "success",
      actionLabel: "Undo",
      onAction: async () => {
        if (!hiddenCollectionId) return;
        await api(`/api/collections/${encodeURIComponent(hiddenCollectionId)}/items/remove`, {
          method: "POST",
          body: JSON.stringify({ asset_ids: memberIds }),
        });
        await loadCollections();
        await loadAssets();
        Shared.showToast("Asset restored to canvas.", { type: "info" });
      },
    });
  } catch (e) {
    Shared.showToast(`Hide failed: ${formatApiError(e)}`, { type: "error" });
  }
}

async function deleteAnnotationWithUndo(ann) {
  const { id, x, y, text } = ann;
  const assetId = state.modalAsset && state.modalAsset.id;
  await api(`/api/annotations/${id}`, { method: "DELETE" });
  state.annotations = state.annotations.filter((a) => a.id !== id);
  if (state.activeAnnotationId === id) state.activeAnnotationId = null;
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
  Shared.showToast("Annotation deleted", {
    type: "info",
    actionLabel: "Undo",
    onAction: async () => {
      if (!assetId) return;
      const res = await api("/api/annotations", {
        method: "POST",
        body: JSON.stringify({ asset_id: assetId, x, y, text: text || "" }),
      });
      state.annotations.push(res.annotation);
      renderAnnotations();
      renderMarkers();
      renderFloatingNote();
    },
  });
}

async function loadAnnotations(assetId) {
  const data = await api(`/api/annotations?asset_id=${encodeURIComponent(assetId)}`);
  state.annotations = data.annotations;
}

function renderAnnotations() {
  const wrap = $("#annList");
  wrap.innerHTML = "";
  state.annotations.forEach((ann, idx) => {
    const el = document.createElement("div");
    el.className = `listItem annItem ${state.activeAnnotationId === ann.id ? "active" : ""}`;
    el.innerHTML = `
      <div class="annHeader">
        <strong>#${idx + 1}</strong>
        <button class="iconBtn danger" data-del="${ann.id}">×</button>
      </div>
      <textarea data-ann="${ann.id}">${ann.text || ""}</textarea>
    `;
    el.onclick = () => setActiveAnnotation(ann.id);
    const ta = el.querySelector("textarea");
    ta.addEventListener("input", async () => {
      ann.text = ta.value;
      syncFloatingText(ann.id, ta.value);
      scheduleAnnotationUpdate(ann.id, { text: ta.value });
    });
    el.querySelector("[data-del]").onclick = async () => {
      await deleteAnnotationWithUndo(ann);
    };
    wrap.appendChild(el);
  });
}

function modalImageGeometry() {
  const stage = $("#imageStage");
  const img = $("#modalImage");
  const stageRect = stage.getBoundingClientRect();
  const stageWidth = stageRect.width;
  const stageHeight = stageRect.height;
  if (!img || img.style.display === "none" || !img.naturalWidth || !img.naturalHeight || stageWidth <= 0 || stageHeight <= 0) {
    return { stageRect, left: 0, top: 0, width: stageWidth, height: stageHeight };
  }
  const scale = Math.min(stageWidth / img.naturalWidth, stageHeight / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  const left = (stageWidth - width) / 2;
  const top = (stageHeight - height) / 2;
  return { stageRect, left, top, width, height };
}

function stagePointToNormalized(clientX, clientY, clamp = false) {
  const geo = modalImageGeometry();
  if (geo.width <= 0 || geo.height <= 0) return null;
  let x = (clientX - geo.stageRect.left - geo.left) / geo.width;
  let y = (clientY - geo.stageRect.top - geo.top) / geo.height;
  if (clamp) {
    x = Math.max(0, Math.min(1, x));
    y = Math.max(0, Math.min(1, y));
    return { x, y, geo };
  }
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x, y, geo };
}

function normalizedToStagePoint(x, y) {
  const geo = modalImageGeometry();
  return {
    left: geo.left + x * geo.width,
    top: geo.top + y * geo.height,
    geo,
  };
}

function renderMarkers() {
  $$(".marker").forEach((m) => m.remove());
  const stage = $("#imageStage");
  state.annotations.forEach((ann, idx) => {
    const m = document.createElement("div");
    m.className = "marker";
    const pt = normalizedToStagePoint(ann.x, ann.y);
    m.style.left = `${pt.left}px`;
    m.style.top = `${pt.top}px`;
    m.dataset.id = ann.id;
    m.style.background = markerColor(idx);
    m.innerHTML = `
      <span style="color: #F2F2F6;">${idx + 1}</span>
      <div class="badgeIcons">
        <button class="ok" data-ok="${ann.id}" aria-label="Done">
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path d="M3.2 8.4l2.3 2.3L12.8 3.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
        <button class="del" data-del="${ann.id}" aria-label="Delete">
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    `;
    m.onpointerdown = (e) => {
      if (e.target.closest(".badgeIcons")) return;
      e.stopPropagation();
      m.setPointerCapture(e.pointerId);
      state.dragging = { id: ann.id, pointerId: e.pointerId, moved: false };
    };
    m.onclick = (e) => {
      e.stopPropagation();
      setActiveAnnotation(ann.id);
    };
    if (state.activeAnnotationId === ann.id) m.classList.add("active");
    m.querySelector("[data-ok]").onclick = (e) => {
      e.stopPropagation();
      state.activeAnnotationId = null;
      renderAnnotations();
      renderMarkers();
      renderFloatingNote();
    };
    m.querySelector("[data-del]").onclick = async (e) => {
      e.stopPropagation();
      await deleteAnnotationWithUndo(ann);
    };
    stage.appendChild(m);
  });
}

$("#imageStage").addEventListener("click", async (e) => {
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
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
});

$("#imageStage").addEventListener("pointermove", async (e) => {
  if (!state.dragging) return;
  const point = stagePointToNormalized(e.clientX, e.clientY, true);
  if (!point) return;
  const ann = state.annotations.find((a) => a.id === state.dragging.id);
  if (!ann) return;
  ann.x = point.x;
  ann.y = point.y;
  state.dragging.moved = true;
  renderMarkers();
  renderFloatingNote();
});

$("#imageStage").addEventListener("pointerup", async (e) => {
  if (!state.dragging) return;
  const ann = state.annotations.find((a) => a.id === state.dragging.id);
  if (ann) {
    await api(`/api/annotations/${ann.id}`, {
      method: "PUT",
      body: JSON.stringify({ x: ann.x, y: ann.y }),
    });
  }
  state.dragging = null;
});

$("#closeModal").onclick = () => closeModal();
$("#modal").onclick = (e) => {
  if (e.target.id === "modal") closeModal();
};
const hideAssetBtn = $("#hideAssetBtn");
if (hideAssetBtn) {
  hideAssetBtn.onclick = async () => {
    await hideModalAsset();
  };
}
const printAssetBtn = $("#printAssetBtn");
if (printAssetBtn) {
  printAssetBtn.onclick = () => {
    if (!state.modalAsset) return;
    printModalAsset(state.modalAsset);
  };
}

$("#search").addEventListener("input", (e) => {
  state.q = e.target.value || "";
  if (state.canvasMode !== "tray" && semanticQueryFromInput(state.q)) {
    setStats();
    return;
  }
  loadAssets();
});

$("#search").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  loadAssets();
});
// top source dropdown not used; filters panel handles sources
function resetFiltersAndSearch() {
  state.q = "";
  $("#search").value = "";
  state.sources.clear();
  state.boards.clear();
  state.labels.clear();
  state.mediaStatuses.clear();
  state.contentKinds.clear();
  state.creators.clear();
  state.selected.clear();
  state.expanded.clear();
  state.labelMatchMode = "any";
  updateLabelModeButton();
}

$("#showAll").onclick = async () => {
  resetFiltersAndSearch();
  state.canvasMode = "main";
  state.viewCollectionId = "";
  renderCollections();
  setStats();
  closeMobilePanels();
  await loadFacets({ seedDefaultMedia: false });
  await loadAssets();
};

$("#showTrayCanvas").onclick = async () => {
  state.canvasMode = "tray";
  state.viewCollectionId = "";
  renderCollections();
  setStats();
  closeMobilePanels();
  await loadAssets();
};

$("#reviewCollection").onclick = () => {
  const viewCollection = getViewCollection();
  if (!viewCollection) return;
  const dataUrl = `/api/cluster/review?collection_id=${encodeURIComponent(viewCollection.id)}&include_neighbors=0`;
  const url = `/tools/cluster_explorer.html?data=${encodeURIComponent(dataUrl)}`;
  window.open(url, "_blank");
};

$("#loadMore").onclick = async () => {
  await loadAssets(true);
};

$(".content").addEventListener("scroll", () => {
  const content = $(".content");
  if (!content || state.semanticMode || state.loadingAssets || !state.hasMore) return;
  if (content.scrollTop + content.clientHeight >= content.scrollHeight - 220) {
    loadAssets(true);
  }
});

window.addEventListener("resize", () => {
  if (!isMobilePanelMode()) closeMobilePanels();
  if (!state.modalAsset) return;
  renderMarkers();
  renderFloatingNote();
});

// Filters accordion toggle
$("#filtersToggle")?.addEventListener("click", () => {
  state.filtersExpanded = !state.filtersExpanded;
  const filtersDiv = $("#filters");
  const chevron = $("#filtersChevron");
  if (filtersDiv) filtersDiv.style.display = state.filtersExpanded ? "" : "none";
  if (chevron) chevron.textContent = state.filtersExpanded ? "▾" : "▸";
  const toggle = $("#filtersToggle");
  if (toggle) toggle.setAttribute("aria-expanded", state.filtersExpanded ? "true" : "false");
});

// Group search filter
$("#groupSearch")?.addEventListener("input", () => renderGroups());

// Zoom control buttons
$("#zoomControl")?.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-zoom]");
  if (btn) setZoom(btn.dataset.zoom);
});

$("#selectAll").onclick = () => {
  for (const a of state.assets) state.selected.add(a.id);
  setStats();
  renderGrid();
};

$("#newCollection").onclick = async () => {
  const name = prompt("Collection name:", "Kitchen — Round 1");
  if (!name) return;
  const res = await api("/api/collections", { method: "POST", body: JSON.stringify({ name }) });
  await loadCollections();
  await selectCollection(res.collection.id);
};

$("#deleteCollection").onclick = async () => {
  const collectionId = state.activeCollectionId;
  if (!collectionId) return;
  const c = state.collections.find((x) => x.id === collectionId);
  const ok = confirm(`Delete collection "${c ? c.name : ""}"? This cannot be undone.`);
  if (!ok) return;
  try {
    await api(`/api/collections/${collectionId}`, { method: "DELETE" });
    state.activeCollectionId = "";
    if (state.viewCollectionId === collectionId) state.viewCollectionId = "";
    await loadCollections();
    await loadAssets();
  } catch (e) {
    // fallback for servers that only support JSON body for DELETE
    try {
      await api(`/api/collections`, {
        method: "DELETE",
        body: JSON.stringify({ id: collectionId }),
      });
      state.activeCollectionId = "";
      if (state.viewCollectionId === collectionId) state.viewCollectionId = "";
      await loadCollections();
      await loadAssets();
    } catch (e2) {
      Shared.showToast(`Delete failed: ${e2.message || e2}`, { type: "error" });
    }
  }
};

$("#addSelected").onclick = async () => {
  const ids = expandAssetIds(Array.from(state.selected));
  if (!ids.length) return;
  await api(`/api/tray/add`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: ids }),
  });
  state.selected.clear();
  await loadTray();
  await loadAssets();
};

$("#addSelectedToCollection").onclick = async () => {
  if (!state.activeCollectionId || state.selected.size === 0) return;
  const ids = expandAssetIds(Array.from(state.selected));
  if (!ids.length) return;
  try {
    await api(`/api/collections/${state.activeCollectionId}/items`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    state.selected.clear();
    await loadCollections();
    await loadAssets();
  } catch (e) {
    Shared.showToast(`Add failed: ${e.message || e}`, { type: "error" });
  }
};

$("#removeSelectedFromCollection").onclick = async () => {
  if (!state.viewCollectionId || state.selected.size === 0) return;
  const ids = expandAssetIds(Array.from(state.selected));
  if (!ids.length) return;
  const col = getViewCollection();
  const colId = state.viewCollectionId;
  const colName = col ? col.name : "this collection";
  const count = state.selected.size;
  try {
    await api(`/api/collections/${colId}/items/remove`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    state.selected.clear();
    await loadCollections();
    await loadAssets();
    Shared.showToast(`Removed ${count} item${count === 1 ? "" : "s"} from "${colName}"`, {
      type: "success",
      actionLabel: "Undo",
      onAction: async () => {
        await api(`/api/collections/${colId}/items`, {
          method: "POST",
          body: JSON.stringify({ asset_ids: ids }),
        });
        await loadCollections();
        await loadAssets();
        Shared.showToast("Restored items.", { type: "info" });
      },
    });
  } catch (e) {
    Shared.showToast(`Remove failed: ${e.message || e}`, { type: "error" });
  }
};

$("#removeSelectedFromTray").onclick = async () => {
  const trayIds = trayAssetIdsSet();
  const selectedTrayIds = Array.from(state.selected).filter((id) => trayIds.has(id));
  const ids = expandAssetIds(selectedTrayIds);
  if (!ids.length) return;
  await api("/api/tray/remove", {
    method: "POST",
    body: JSON.stringify({ asset_ids: ids }),
  });
  selectedTrayIds.forEach((id) => state.selected.delete(id));
  await loadTray();
  await loadAssets();
};

$("#addFiltered").onclick = async () => {
  const ids = expandAssetIds(state.assets.map((a) => a.id));
  if (!ids.length) return;
  if (state.activeCollectionId) {
    await api(`/api/collections/${state.activeCollectionId}/items`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    await loadCollections();
  } else {
    await api(`/api/tray/add`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    await loadTray();
  }
  state.selected.clear();
  await loadAssets();
};

$("#clearSelection").onclick = (e) => {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  state.selected.clear();
  renderGrid();
};

$("#assetNotes").addEventListener("input", async (e) => {
  if (!state.modalAsset) return;
  await api(`/api/assets/${state.modalAsset.id}`, {
    method: "PUT",
    body: JSON.stringify({ notes: e.target.value }),
  });
});

function markerColor(idx) {
  return "#6F5AA8";
}

function setActiveAnnotation(id) {
  state.activeAnnotationId = id;
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
  const ta = document.querySelector(`textarea[data-ann="${id}"]`);
  if (ta) ta.focus();
}

function renderFloatingNote() {
  const box = $("#floatingNote");
  const ta = $("#floatingText");
  if (!state.activeAnnotationId) {
    box.classList.add("hidden");
    return;
  }
  const ann = state.annotations.find((a) => a.id === state.activeAnnotationId);
  if (!ann) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  ta.value = ann.text || "";
  const pt = normalizedToStagePoint(ann.x, ann.y);
  const left = Math.min(pt.geo.left + pt.geo.width - 240, Math.max(10, pt.left + 12));
  const top = Math.min(pt.geo.top + pt.geo.height - 140, Math.max(10, pt.top + 12));
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
  setTimeout(() => ta.focus(), 0);
}

function syncFloatingText(id, text) {
  if (state.activeAnnotationId !== id) return;
  $("#floatingText").value = text;
}

function scheduleAnnotationUpdate(id, payload) {
  if (state.noteTimers[id]) clearTimeout(state.noteTimers[id]);
  state.noteTimers[id] = setTimeout(async () => {
    await api(`/api/annotations/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }, 250);
}

$("#floatingText").addEventListener("input", (e) => {
  if (!state.activeAnnotationId) return;
  const ann = state.annotations.find((a) => a.id === state.activeAnnotationId);
  if (!ann) return;
  ann.text = e.target.value;
  const listTa = document.querySelector(`textarea[data-ann="${ann.id}"]`);
  if (listTa) listTa.value = e.target.value;
  scheduleAnnotationUpdate(ann.id, { text: e.target.value });
});

$("#floatingText").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    state.activeAnnotationId = null;
    renderAnnotations();
    renderMarkers();
    renderFloatingNote();
  }
});

// refresh button removed

async function init() {
  applyZoom();
  try {
    await loadCollections();
    await loadFacets();
    await loadTray();
    await loadAssets();
    state.initComplete = true;
  } catch (err) {
    console.error("App initialization failed", err);
    showFatalUiError(err);
  }
}

init();

document.querySelectorAll('.toolbar .row').forEach(row => {
  row.addEventListener('scroll', () => {
    const atEnd = row.scrollLeft + row.clientWidth >= row.scrollWidth - 8;
    row.classList.toggle('scrolled-end', atEnd);
  });
});

function facetContextQueryString() {
  const source = encodeURIComponent(Array.from(state.sources).join(","));
  const mediaStatus = encodeURIComponent(Array.from(state.mediaStatuses).join(","));
  return `source=${source}&media_status=${mediaStatus}`;
}

async function loadFacets(options = {}) {
  const seedDefaultMedia = options.seedDefaultMedia !== false;
  const data = await api(`/api/facets?${facetContextQueryString()}`);
  state.facets = data.facets;
  const mediaItems = state.facets.media_statuses || [];
  let seededDefaultMedia = false;
  if (seedDefaultMedia && !state.mediaDefaultsSeeded && state.mediaStatuses.size === 0 && mediaItems.length) {
    mediaItems.forEach((it) => {
      const value = `${it.media_status || ""}`.trim();
      if (!value || value === "metadata_only") return;
      state.mediaStatuses.add(value);
    });
    if (state.mediaStatuses.size === 0) {
      mediaItems.forEach((it) => {
        const value = `${it.media_status || ""}`.trim();
        if (value) state.mediaStatuses.add(value);
      });
    }
    seededDefaultMedia = state.mediaStatuses.size > 0;
    if (seededDefaultMedia) state.mediaDefaultsSeeded = true;
  }
  if (seededDefaultMedia) {
    // Recompute context-sensitive content kinds with the default media filter now applied.
    const data2 = await api(`/api/facets?${facetContextQueryString()}`);
    state.facets = data2.facets;
  }
  renderFilters();
  renderGroups();
  updateFiltersBadge();
}

function prettyFacetValue(groupKey, value) {
  if (groupKey === "media_statuses") {
    if (value === "image") return "Image";
    if (value === "link_only") return "Link only";
    if (value === "metadata_only") return "Metadata only";
  }
  if (groupKey === "content_kinds") {
    return value.replace(/_/g, " ");
  }
  return value;
}

window.addEventListener("error", (event) => {
  if (!event || !event.error) return;
  if (event.target && event.target !== window) return;
  if (state.initComplete) {
    console.error("Unhandled runtime error", event.error);
    return;
  }
  showFatalUiError(event.error || event.message || "Unexpected error");
});

window.addEventListener("unhandledrejection", (event) => {
  if (state.initComplete) {
    console.error("Unhandled promise rejection", event && event.reason);
    return;
  }
  showFatalUiError((event && event.reason) || "Unexpected async error");
});

function isFilterGroupOpen(key) {
  if (Object.prototype.hasOwnProperty.call(state.filterOpen, key)) {
    return !!state.filterOpen[key];
  }
  return key === "sources";
}

function renderFilters() {
  const wrap = $("#filters");
  if (!wrap) return;
  wrap.innerHTML = "";
  const groups = [
    { key: "sources", label: "Source", set: state.sources, valueKey: "source" },
    { key: "labels", label: "AI Tags", set: state.labels, valueKey: "label" },
    { key: "media_statuses", label: "Media Type", set: state.mediaStatuses, valueKey: "media_status" },
    { key: "content_kinds", label: "Record Type", set: state.contentKinds, valueKey: "content_kind" },
    { key: "creators", label: "Creator / Page", set: state.creators, valueKey: "creator_name" },
  ];

  for (const g of groups) {
    let items = state.facets[g.key] || [];
    const hasContextCounts = Array.isArray(state.facets.content_kinds_context);
    if (g.key === "content_kinds") {
      const contextual = hasContextCounts ? state.facets.content_kinds_context : [];
      const contextCounts = new Map(contextual.map((it) => [`${it.content_kind || ""}`.trim(), Number(it.n || 0)]));
      items = (state.facets.content_kinds || []).map((it) => {
        const value = `${it.content_kind || ""}`.trim();
        return {
          ...it,
          n_context: hasContextCounts ? (value ? contextCounts.get(value) || 0 : 0) : Number(it.n || 0),
        };
      });
    }
    if (!items.length) continue;
    const isOpen = isFilterGroupOpen(g.key);
    const group = document.createElement("div");
    group.className = "filterGroup";
    group.innerHTML = `
      <button type="button" class="filterToggle" aria-expanded="${isOpen ? "true" : "false"}">
        <span>${escapeHtml(g.label)}</span>
        <span class="filterChevron">${isOpen ? "▾" : "▸"}</span>
      </button>
    `;
    const list = document.createElement("div");
    list.className = `filterList ${isOpen ? "" : "collapsed"}`;
    items.forEach((it) => {
      const raw = it[g.valueKey];
      const value = `${raw || ""}`.trim();
      if (!value) return;
      const contextualCount = g.key === "content_kinds" ? Number(it.n_context || 0) : Number(it.n || 0);
      const isSelected = g.set.has(value);
      const isZeroOption = g.key === "content_kinds" && hasContextCounts && contextualCount === 0;
      const disabled = isZeroOption && !isSelected;
      const row = document.createElement("label");
      row.className = `filterItem${isZeroOption ? " zeroOption" : ""}`;
      row.innerHTML = `<input type="checkbox" ${isSelected ? "checked" : ""} ${disabled ? "disabled" : ""} /> ${escapeHtml(prettyFacetValue(g.key, value))} <span class="muted">(${contextualCount})</span>`;
      row.querySelector("input").addEventListener("change", async (e) => {
        if (e.target.checked) g.set.add(value);
        else g.set.delete(value);
        updateFiltersBadge();
        if (g.key === "sources" || g.key === "media_statuses") {
          await loadFacets();
        }
        await loadAssets();
      });
      list.appendChild(row);
    });
    group.querySelector(".filterToggle").addEventListener("click", () => {
      state.filterOpen[g.key] = !isFilterGroupOpen(g.key);
      renderFilters();
    });
    group.appendChild(list);
    wrap.appendChild(group);
  }
}

function renderTray() {
  const wrap = $("#tray");
  wrap.innerHTML = "";
  for (const item of state.tray) {
    const el = document.createElement("div");
    el.className = "listItem trayItem";
    const preview = previewForAsset(item);
    el.innerHTML = `
      <div class="trayItemRow">
        ${
          preview.url
            ? `<img class="trayThumb" src="${escapeHtml(preview.url)}" loading="lazy" alt="" />`
            : `<div class="trayThumb trayThumbEmpty">No image</div>`
        }
        <div class="trayText">
          <div class="trayTitle">${escapeHtml(displayTitle(item))}</div>
          <div class="muted">${escapeHtml(item.source || "")}</div>
        </div>
        <button class="miniBtn trayRemove">Remove</button>
      </div>
    `;
    el.querySelector(".trayRemove").onclick = async (e) => {
      e.stopPropagation();
      await api("/api/tray/remove", {
        method: "POST",
        body: JSON.stringify({ asset_ids: memberAssetIds(item) }),
      });
      await loadTray();
    };
    el.onclick = () => {
      openModal(item);
    };
    wrap.appendChild(el);
  }
}

function setScanImportButtonState() {
  const button = $("#addScanPdf");
  if (!button) return;
  button.disabled = !!state.scanImportBusy || !!state.photoImportBusy;
  button.textContent = state.scanImportBusy ? "Importing..." : "Add Scan PDF";
  const runButton = $("#runScanImport");
  if (runButton) runButton.disabled = !!state.scanImportBusy || !!state.photoImportBusy || !currentScanImportFile();
}

function currentScanImportFile() {
  const input = $("#scanPdfInput");
  return state.scanImportFile || (input && input.files && input.files[0]) || null;
}

function openScanImportModal() {
  const modal = $("#scanImportModal");
  if (!modal) return;
  modal.classList.remove("hidden");
}

function closeScanImportModal() {
  const modal = $("#scanImportModal");
  if (!modal) return;
  modal.classList.add("hidden");
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
  const name = `${file.name || ""}`.trim();
  if (!isPdfFile(file)) {
    Shared.showToast("Please choose a PDF file.", { type: "error" });
    return;
  }
  const useFormParser = !!opts.useFormParser;
  const detectDelimiters = opts.detectDelimiters !== false;

  state.scanImportBusy = true;
  setScanImportButtonState();
  setPhotoImportButtonState();
  const narrative = $("#canvasNarrative");
  const previousNarrative = narrative ? narrative.textContent : "";
  if (narrative) {
    narrative.textContent = `Importing "${name}" into scans...`;
  }

  try {
    const formData = new FormData();
    formData.append("file", file, name);
    formData.append("use_form_parser", useFormParser ? "1" : "0");
    formData.append("split_on_delimiters", detectDelimiters ? "1" : "0");
    const payload = await apiUpload("/api/import/scans", formData);
    const importReport = payload.import || {};
    const created = Number(importReport.created_assets || 0);
    const docs = Number(importReport.detected_documents || 0);
    const delimiters = Number(importReport.delimiter_pages_skipped || 0);
    const errors = Array.isArray(importReport.errors) ? importReport.errors.length : 0;

    await loadFacets();
    await loadAssets();

    let msg = `Imported ${created} scan page${created === 1 ? "" : "s"} from "${name}".`;
    if (docs > 0) {
      msg += ` These are grouped into ${docs} scan document card${docs === 1 ? "" : "s"} in the canvas.`;
    } else {
      msg += " This appears as one scan document card in the canvas.";
    }
    if (detectDelimiters && delimiters > 0) {
      msg += ` Skipped ${delimiters} blank delimiter page${delimiters === 1 ? "" : "s"}.`;
    }
    if (!detectDelimiters) msg += " Delimiter detection was turned off.";
    if (errors > 0) msg += ` ${errors} import error${errors === 1 ? "" : "s"} were reported.`;
    if (useFormParser) msg += " Form Parser option was requested.";
    Shared.showToast(msg, { type: "success" });
    closeScanImportModal();
  } catch (e) {
    Shared.showToast(`Scan import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.scanImportBusy = false;
    setScanImportButtonState();
    setPhotoImportButtonState();
    const input = $("#scanPdfInput");
    setSingleFileSelection(input, null, "scanImportFile");
    if (narrative) narrative.textContent = previousNarrative;
    setStats();
  }
}

function setPhotoImportButtonState() {
  const button = $("#addPhotos");
  if (!button) return;
  button.disabled = !!state.photoImportBusy || !!state.scanImportBusy;
  button.textContent = state.photoImportBusy ? "Importing..." : "Add Photos";
  const runButton = $("#runPhotoImport");
  if (runButton) runButton.disabled = !!state.photoImportBusy || !!state.scanImportBusy || !currentPhotoImportFile();
}

function currentPhotoImportFile() {
  const input = $("#photoInput");
  return state.photoImportFile || (input && input.files && input.files[0]) || null;
}

function openPhotoImportModal() {
  const modal = $("#photoImportModal");
  if (!modal) return;
  modal.classList.remove("hidden");
}

function closePhotoImportModal() {
  const modal = $("#photoImportModal");
  if (!modal) return;
  modal.classList.add("hidden");
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
  const name = `${file.name || ""}`.trim();
  if (!name) return;
  if (!isImageFile(file)) {
    Shared.showToast("Please choose an image file.", { type: "error" });
    return;
  }
  state.photoImportBusy = true;
  setPhotoImportButtonState();
  setScanImportButtonState();
  const narrative = $("#canvasNarrative");
  const previousNarrative = narrative ? narrative.textContent : "";
  if (narrative) narrative.textContent = `Importing "${name}" into photos...`;

  try {
    const formData = new FormData();
    formData.append("file", file, name);
    const payload = await apiUpload("/api/import/photos", formData);
    const importReport = payload.import || {};
    const created = Number(importReport.created_assets || 0);
    const errors = Array.isArray(importReport.errors) ? importReport.errors.length : 0;
    await loadFacets();
    await loadAssets();
    let msg = `Imported ${created} photo item${created === 1 ? "" : "s"} from "${name}".`;
    if (errors > 0) msg += ` ${errors} import error${errors === 1 ? "" : "s"} were reported.`;
    Shared.showToast(msg, { type: "success" });
    closePhotoImportModal();
  } catch (e) {
    Shared.showToast(`Photo import failed: ${formatApiError(e)}`, { type: "error", duration: 8000 });
  } finally {
    state.photoImportBusy = false;
    setPhotoImportButtonState();
    setScanImportButtonState();
    const input = $("#photoInput");
    setSingleFileSelection(input, null, "photoImportFile");
    if (narrative) narrative.textContent = previousNarrative;
    setStats();
  }
}

async function clearTray() {
  if (!state.tray.length) return;
  const clearedIds = expandAssetIds(state.tray.map((x) => x.id));
  await api("/api/tray/clear", { method: "POST" });
  await loadTray();
  Shared.showToast(`Cleared ${clearedIds.length} item${clearedIds.length === 1 ? "" : "s"} from tray`, {
    type: "success",
    actionLabel: "Undo",
    onAction: async () => {
      await api("/api/tray/add", {
        method: "POST",
        body: JSON.stringify({ asset_ids: clearedIds }),
      });
      await loadTray();
      Shared.showToast("Tray restored.", { type: "info" });
    },
  });
}

async function createCollectionFromTray() {
  if (!state.tray.length) return;
  const name = prompt("Collection name:", "Curated — Round 1");
  if (!name) return;
  const res = await api("/api/tray/create-collection", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await loadCollections();
  await loadTray();
  await selectCollection(res.collection.id);
}

async function addTrayToActiveCollection() {
  if (!state.activeCollectionId || state.tray.length === 0) return;
  const ids = expandAssetIds(state.tray.map((x) => x.id));
  if (!ids.length) return;
  try {
    await api(`/api/collections/${state.activeCollectionId}/items`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    await api("/api/tray/clear", { method: "POST" });
    await loadCollections();
    await loadTray();
    await loadAssets();
  } catch (e) {
    Shared.showToast(`Add to collection failed: ${e.message || e}`, { type: "error" });
  }
}

$("#clearTray").onclick = clearTray;
$("#clearTrayTop").onclick = clearTray;
$("#createFromTray").onclick = createCollectionFromTray;
$("#createFromTrayTop").onclick = createCollectionFromTray;
$("#addTrayToCollection").onclick = addTrayToActiveCollection;
$("#addTrayToCollectionTop").onclick = addTrayToActiveCollection;
const toggleLabelModeBtn = $("#toggleLabelMode");
if (toggleLabelModeBtn) {
  toggleLabelModeBtn.onclick = async () => {
    state.labelMatchMode = state.labelMatchMode === "all" ? "any" : "all";
    updateLabelModeButton();
    await loadAssets();
  };
  updateLabelModeButton();
}

const addScanPdfBtn = $("#addScanPdf");
const scanPdfInput = $("#scanPdfInput");
const scanDropZone = $("#scanDropZone");
const runScanImportBtn = $("#runScanImport");
const cancelScanImportBtn = $("#cancelScanImport");
const closeScanImportBtn = $("#closeScanImport");
if (addScanPdfBtn && scanPdfInput && runScanImportBtn) {
  addScanPdfBtn.onclick = () => {
    if (state.scanImportBusy) return;
    openScanImportModal();
    resetScanImportModal();
  };
  scanPdfInput.addEventListener("change", () => {
    const file = (scanPdfInput.files && scanPdfInput.files[0]) || null;
    if (file && !isPdfFile(file)) {
      Shared.showToast("Please choose a PDF file.", { type: "error" });
      setSingleFileSelection(scanPdfInput, null, "scanImportFile");
      setScanImportButtonState();
      return;
    }
    state.scanImportFile = file || null;
    setScanImportButtonState();
  });
  wireSingleFileDropZone({
    zone: scanDropZone,
    input: scanPdfInput,
    stateKey: "scanImportFile",
    accept: isPdfFile,
    invalidMessage: "Please drop a PDF file.",
    isBusy: () => state.scanImportBusy || state.photoImportBusy,
    onSelected: () => setScanImportButtonState(),
  });
  runScanImportBtn.addEventListener("click", async () => {
    if (state.scanImportBusy) return;
    const file = currentScanImportFile();
    const useFormParser = !!($("#scanUseFormParser") && $("#scanUseFormParser").checked);
    const detectDelimiters = !!($("#scanDetectDelimiters") && $("#scanDetectDelimiters").checked);
    await importScanPdf(file, { useFormParser, detectDelimiters });
  });
  if (cancelScanImportBtn) {
    cancelScanImportBtn.onclick = () => {
      if (state.scanImportBusy) return;
      closeScanImportModal();
      resetScanImportModal();
    };
  }
  if (closeScanImportBtn) {
    closeScanImportBtn.onclick = () => {
      if (state.scanImportBusy) return;
      closeScanImportModal();
      resetScanImportModal();
    };
  }
  setScanImportButtonState();
}
const addPhotosBtn = $("#addPhotos");
const photoInput = $("#photoInput");
const photoDropZone = $("#photoDropZone");
const runPhotoImportBtn = $("#runPhotoImport");
const cancelPhotoImportBtn = $("#cancelPhotoImport");
const closePhotoImportBtn = $("#closePhotoImport");
if (addPhotosBtn && photoInput && runPhotoImportBtn) {
  addPhotosBtn.onclick = () => {
    if (state.photoImportBusy || state.scanImportBusy) return;
    openPhotoImportModal();
    resetPhotoImportModal();
  };
  photoInput.addEventListener("change", () => {
    const file = (photoInput.files && photoInput.files[0]) || null;
    if (file && !isImageFile(file)) {
      Shared.showToast("Please choose an image file.", { type: "error" });
      setSingleFileSelection(photoInput, null, "photoImportFile");
      setPhotoImportButtonState();
      return;
    }
    state.photoImportFile = file || null;
    setPhotoImportButtonState();
  });
  wireSingleFileDropZone({
    zone: photoDropZone,
    input: photoInput,
    stateKey: "photoImportFile",
    accept: isImageFile,
    invalidMessage: "Please drop an image file.",
    isBusy: () => state.photoImportBusy || state.scanImportBusy,
    onSelected: () => setPhotoImportButtonState(),
  });
  runPhotoImportBtn.addEventListener("click", async () => {
    if (state.photoImportBusy || state.scanImportBusy) return;
    const file = currentPhotoImportFile();
    await importPhoto(file);
  });
  if (cancelPhotoImportBtn) {
    cancelPhotoImportBtn.onclick = () => {
      if (state.photoImportBusy) return;
      closePhotoImportModal();
      resetPhotoImportModal();
    };
  }
  if (closePhotoImportBtn) {
    closePhotoImportBtn.onclick = () => {
      if (state.photoImportBusy) return;
      closePhotoImportModal();
      resetPhotoImportModal();
    };
  }
  setPhotoImportButtonState();
}

const openLeftSidebarBtn = $("#openLeftSidebar");
if (openLeftSidebarBtn) {
  openLeftSidebarBtn.onclick = () => openMobilePanel("left");
}
const openRightSidebarBtn = $("#openRightSidebar");
if (openRightSidebarBtn) {
  openRightSidebarBtn.onclick = () => openMobilePanel("right");
}
const closeLeftSidebarBtn = $("#closeLeftSidebar");
if (closeLeftSidebarBtn) {
  closeLeftSidebarBtn.onclick = () => closeMobilePanels();
}
const closeRightSidebarBtn = $("#closeRightSidebar");
if (closeRightSidebarBtn) {
  closeRightSidebarBtn.onclick = () => closeMobilePanels();
}
const mobileOverlay = $("#mobileOverlay");
if (mobileOverlay) {
  mobileOverlay.onclick = () => closeMobilePanels();
}
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeMobilePanels();
    closeSearchHelp();
    if (!state.scanImportBusy) closeScanImportModal();
    if (!state.photoImportBusy) closePhotoImportModal();
  }
});

const searchHelpWrap = $(".searchHelpWrap");
const searchHelpBtn = $("#searchHelp");
function closeSearchHelp() {
  if (!searchHelpWrap || !searchHelpBtn) return;
  searchHelpWrap.classList.remove("open");
  searchHelpBtn.setAttribute("aria-expanded", "false");
}

if (searchHelpWrap && searchHelpBtn) {
  searchHelpBtn.onclick = (e) => {
    e.stopPropagation();
    const willOpen = !searchHelpWrap.classList.contains("open");
    if (willOpen) searchHelpWrap.classList.add("open");
    else searchHelpWrap.classList.remove("open");
    searchHelpBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  };
}

document.addEventListener("click", (e) => {
  if (!searchHelpWrap || !searchHelpWrap.classList.contains("open")) return;
  if (searchHelpWrap.contains(e.target)) return;
  closeSearchHelp();
});

// ─── Explorer view ────────────────────────────────────────────────────────────

let _explorerInited = false;
let _explorerLoading = false;

async function switchToExplore() {
  if (state.view === "explore") return;
  state.view = "explore";

  const grid = $("#grid");
  const loadMore = $("#loadMore");
  const explorerContainer = $("#explorerContainer");
  const viewGrid = $("#viewGrid");
  const viewExplore = $("#viewExplore");
  const zoomControl = $("#zoomControl");

  if (grid) grid.style.display = "none";
  if (loadMore) loadMore.hidden = true;
  if (explorerContainer) explorerContainer.style.display = "";
  if (zoomControl) zoomControl.style.display = "none";
  if (viewGrid) { viewGrid.classList.remove("active"); viewGrid.setAttribute("aria-pressed", "false"); }
  if (viewExplore) { viewExplore.classList.add("active"); viewExplore.setAttribute("aria-pressed", "true"); }

  const explorer = window.Explorer;
  if (!explorer) return;

  if (!_explorerInited) {
    explorer.init("explorerContainer");
    explorer.onClickNode((nodeId, node) => {
      const asset = state.assets.find((a) => a.id === nodeId);
      if (asset) openModal(asset);
    });
    explorer.onSelect((ids) => {
      state.selected = new Set(ids);
      ids.forEach((id) => updateCardState(id));
      setStats();
    });
    _explorerInited = true;
  }

  explorer.resume();

  if (!_explorerLoading) {
    _explorerLoading = true;
    try {
      const params = new URLSearchParams();
      if (state.activeCollectionId) params.set("collection_id", state.activeCollectionId);
      const res = await fetch(`/api/explorer/layout?${params}`);
      if (res.ok) {
        const data = await res.json();
        explorer.loadData(data);
        // Apply current filter/search state
        _syncExplorerFilter();
      }
    } catch (e) {
      console.error("[Explorer] Failed to load layout:", e);
    } finally {
      _explorerLoading = false;
    }
  }
}

function switchToGrid() {
  if (state.view === "grid") return;
  state.view = "grid";

  const grid = $("#grid");
  const loadMore = $("#loadMore");
  const explorerContainer = $("#explorerContainer");
  const viewGrid = $("#viewGrid");
  const viewExplore = $("#viewExplore");
  const zoomControl = $("#zoomControl");

  if (grid) grid.style.display = "";
  if (explorerContainer) explorerContainer.style.display = "none";
  if (zoomControl) zoomControl.style.display = "";
  if (viewGrid) { viewGrid.classList.add("active"); viewGrid.setAttribute("aria-pressed", "true"); }
  if (viewExplore) { viewExplore.classList.remove("active"); viewExplore.setAttribute("aria-pressed", "false"); }

  if (window.Explorer) window.Explorer.pause();
}

function _syncExplorerFilter() {
  if (state.view !== "explore" || !window.Explorer) return;
  const q = (state.q || "").trim().toLowerCase();
  if (q && !state.semanticMode) {
    const matched = state.assets.filter((a) => (a.title || "").toLowerCase().includes(q)).map((a) => a.id);
    window.Explorer.highlight(matched.length ? matched : null);
  } else {
    window.Explorer.highlight(null);
  }
  if (state.activeCollectionId) {
    const ids = state.assets.map((a) => a.id);
    window.Explorer.setFilter(ids);
  } else {
    window.Explorer.setFilter(null);
  }
}

const viewGridBtn = $("#viewGrid");
const viewExploreBtn = $("#viewExplore");
if (viewGridBtn) viewGridBtn.addEventListener("click", switchToGrid);
if (viewExploreBtn) viewExploreBtn.addEventListener("click", switchToExplore);
