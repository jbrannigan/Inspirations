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
  modalAsset: null,
  annotations: [],
  selectMode: true,
  facets: { sources: [], boards: [], labels: [] },
  tray: [],
  dragging: null,
  activeAnnotationId: null,
  noteTimers: {},
  assetsRequestSeq: 0,
  semanticMode: false,
  error: "",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const IMAGE_SUFFIX_RE = /\.(jpg|jpeg|png|webp|gif|bmp|svg)(\?.*)?$/i;

function escapeHtml(value) {
  return (value || "")
    .toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

function formatApiError(err) {
  const msg = `${(err && err.message) || err || "Request failed"}`.trim();
  if (!msg) return "Request failed";
  try {
    const parsed = JSON.parse(msg);
    if (parsed && typeof parsed.error === "string" && parsed.error.trim()) return parsed.error.trim();
  } catch {}
  return msg;
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

function thumbFor(a) {
  return previewForAsset(a).url;
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

function activeFilterParts() {
  const parts = [];
  const semanticQuery = semanticQueryFromInput(state.q);
  if (semanticQuery) parts.push(`semantic "${semanticQuery}"`);
  else if (state.q.trim()) parts.push(`search "${state.q.trim()}"`);
  if (state.sources.size > 0) parts.push(`${state.sources.size} source filter${state.sources.size === 1 ? "" : "s"}`);
  if (state.boards.size > 0) parts.push(`${state.boards.size} source tag filter${state.boards.size === 1 ? "" : "s"}`);
  if (state.labels.size > 0) parts.push(`${state.labels.size} AI tag filter${state.labels.size === 1 ? "" : "s"}`);
  return parts;
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
  return Array.from(state.sources)[0] || "";
}

function shortRef(value, max = 64) {
  const text = `${value || ""}`.trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

async function selectCollection(collectionId) {
  state.activeCollectionId = collectionId || "";
  state.viewCollectionId = collectionId || "";
  renderCollections();
  setStats();
  await loadAssets();
}

function setStats() {
  const activeCollection = getActiveCollection();
  const viewCollection = getViewCollection();
  const filters = activeFilterParts();
  const scope = viewCollection ? `Collection "${viewCollection.name}"` : "All items";
  const filterState = filters.length ? "Filtered" : "Unfiltered";
  const destination = activeCollection ? ` • Add-to "${activeCollection.name}"` : "";
  $("#canvasContext").textContent = `Canvas: ${scope} • ${filterState}${destination}`;
  const statsBase = `${state.assets.length} items shown${filters.length ? ` • ${filters.join(" • ")}` : ""}`;
  $("#stats").textContent = state.error ? `${statsBase} • Error: ${state.error}` : statsBase;
  $("#addSelected").disabled = state.selected.size === 0;
  $("#addSelectedToCollection").textContent = activeCollection ? `Add Selected to "${activeCollection.name}"` : "Add Selected to Collection";
  $("#addSelectedToCollection").disabled = state.selected.size === 0 || !activeCollection;
  $("#removeSelectedFromCollection").textContent = viewCollection
    ? `Remove Selected from "${viewCollection.name}"`
    : "Remove Selected from Collection";
  $("#removeSelectedFromCollection").disabled = state.selected.size === 0 || !viewCollection;
  $("#addFiltered").disabled = state.assets.length === 0;
  $("#clearSelection").disabled = state.selected.size === 0;
  if (!activeCollection) {
    $("#collectionHint").textContent =
      state.selected.size > 0
        ? 'Pick a collection to enable "Add Selected to Collection".'
        : "No collection selected. Pick one to enable direct add and tray add.";
  } else if (!viewCollection) {
    $("#collectionHint").textContent = `Selected collection: "${activeCollection.name}". Canvas is showing all items.`;
  } else if (state.tray.length > 0) {
    $("#collectionHint").textContent = `Selected collection: "${activeCollection.name}". Ready to add ${state.tray.length} tray item${state.tray.length === 1 ? "" : "s"}.`;
  } else {
    $("#collectionHint").textContent = `Selected collection: "${activeCollection.name}". Add selected items, remove selected items, or use tray for batch curation.`;
  }
  $("#trayCount").textContent = `${state.tray.length} items`;
  $("#createFromTray").disabled = state.tray.length === 0;
  $("#addTrayToCollection").textContent = activeCollection ? `Add Tray to "${activeCollection.name}"` : "Add Tray to Collection";
  $("#addTrayToCollection").disabled = state.tray.length === 0 || !activeCollection;
  $("#clearTray").disabled = state.tray.length === 0;
}

function renderCollections() {
  const wrap = $("#collections");
  wrap.innerHTML = "";
  if (!state.collections.length) {
    wrap.innerHTML = '<div class="muted">No collections yet.</div>';
    return;
  }
  for (const c of state.collections) {
    const isViewing = c.id === state.viewCollectionId;
    const isDestination = c.id === state.activeCollectionId;
    const stateText = isViewing ? "Viewing" : isDestination ? "Destination" : "";
    const el = document.createElement("div");
    el.className = `listItem ${isViewing ? "on" : ""}`;
    el.innerHTML = `<div><strong>${c.name}</strong></div><div class="muted">${c.count} items${stateText ? ` • ${stateText}` : ""}</div>`;
    el.onclick = async () => {
      await selectCollection(c.id);
    };
    wrap.appendChild(el);
  }
}

function renderGrid() {
  const wrap = $("#grid");
  wrap.innerHTML = "";
  if (!state.assets.length) {
    const message = state.error ? `Unable to load items: ${state.error}` : "No items match current filters.";
    wrap.innerHTML = `<div class="muted">${escapeHtml(message)}</div>`;
    setStats();
    return;
  }
  for (const a of state.assets) {
    const el = document.createElement("div");
    el.className = `card ${state.selected.has(a.id) ? "selected" : ""} ${state.expanded.has(a.id) ? "expanded" : ""}`;
    const preview = previewForAsset(a);
    const img = preview.url;
    const ai = a.ai;
    const summary = ai?.summary || a.ai_summary || a.description || "";
    const imageType = ai?.image_type ? `${ai.image_type}` : "";
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
    if (imageType) metaParts.push(`Type: ${imageType}`);
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
        <div class="cardTitle">${escapeHtml(a.title || "(untitled)")}</div>
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
        </div>
        <div class="cardFooter">
          <div>AI: ${escapeHtml(a.ai_model || a.ai_provider || "—")} • ${labelCount} tags</div>
          <button class="miniBtn" data-annotate>Annotate</button>
        </div>
      </div>
    `;
    const imageEl = el.querySelector(".thumb img");
    if (imageEl) {
      imageEl.addEventListener("error", () => {
        const thumbEl = el.querySelector(".thumb");
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
      renderGrid();
    });
    el.querySelector("[data-annotate]").addEventListener("click", (e) => {
      e.stopPropagation();
      openModal(a);
    });
    el.onclick = () => {
      if (state.expanded.has(a.id)) state.expanded.delete(a.id);
      else state.expanded.add(a.id);
      renderGrid();
    };
    wrap.appendChild(el);
  }
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
}

async function loadAssets() {
  const requestSeq = ++state.assetsRequestSeq;
  const semanticQuery = semanticQueryFromInput(state.q);
  state.semanticMode = !!semanticQuery;
  try {
    if (semanticQuery) {
      const source = encodeURIComponent(semanticSourceFilter());
      const q = encodeURIComponent(semanticQuery);
      const data = await api(`/api/search/similar?q=${q}&source=${source}&limit=120`);
      if (requestSeq !== state.assetsRequestSeq) return;
      state.error = "";
      state.assets = (data.results || []).map((a) => ({ ...a, ai: parseAi(a) }));
      renderGrid();
      return;
    }

    const q = encodeURIComponent(state.q || "");
    const source = encodeURIComponent(Array.from(state.sources).join(","));
    const board = encodeURIComponent(Array.from(state.boards).join(","));
    const label = encodeURIComponent(Array.from(state.labels).join(","));
    const col = encodeURIComponent(state.viewCollectionId || "");
    const data = await api(`/api/assets?q=${q}&source=${source}&board=${board}&label=${label}&collection_id=${col}`);
    if (requestSeq !== state.assetsRequestSeq) return;
    state.error = "";
    state.assets = data.assets.map((a) => ({ ...a, ai: parseAi(a) }));
    renderGrid();
  } catch (err) {
    if (requestSeq !== state.assetsRequestSeq) return;
    state.assets = [];
    state.error = formatApiError(err);
    renderGrid();
  }
}

async function openModal(asset) {
  state.modalAsset = asset;
  $("#modalTitle").textContent = asset.title || "(untitled)";
  $("#modalMeta").textContent = `${asset.source} • ${asset.source_ref || ""}`;
  const modalImage = $("#modalImage");
  const previewUrl = thumbFor(asset);
  if (previewUrl) {
    modalImage.src = previewUrl;
    modalImage.style.display = "block";
  } else {
    modalImage.removeAttribute("src");
    modalImage.style.display = "none";
  }
  $("#assetNotes").value = asset.notes || "";
  const link = $("#sourceLink");
  if (asset.source_ref) {
    link.href = asset.source_ref;
    link.textContent = "Open original";
  } else {
    link.href = "#";
    link.textContent = "No source";
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
      await api(`/api/annotations/${ann.id}`, { method: "DELETE" });
      state.annotations = state.annotations.filter((x) => x.id !== ann.id);
      if (state.activeAnnotationId === ann.id) state.activeAnnotationId = null;
      renderAnnotations();
      renderMarkers();
      renderFloatingNote();
    };
    wrap.appendChild(el);
  });
}

function renderMarkers() {
  $$(".marker").forEach((m) => m.remove());
  const stage = $("#imageStage");
  state.annotations.forEach((ann, idx) => {
    const m = document.createElement("div");
    m.className = "marker";
    m.textContent = idx + 1;
    m.style.left = `${ann.x * 100}%`;
    m.style.top = `${ann.y * 100}%`;
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
      await api(`/api/annotations/${ann.id}`, { method: "DELETE" });
      state.annotations = state.annotations.filter((x) => x.id !== ann.id);
      if (state.activeAnnotationId === ann.id) state.activeAnnotationId = null;
      renderAnnotations();
      renderMarkers();
      renderFloatingNote();
    };
    stage.appendChild(m);
  });
}

$("#imageStage").addEventListener("click", async (e) => {
  if (!state.modalAsset) return;
  if (e.target.closest(".marker") || e.target.closest(".floatingNote")) return;
  const r = $("#imageStage").getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width;
  const y = (e.clientY - r.top) / r.height;
  const res = await api("/api/annotations", {
    method: "POST",
    body: JSON.stringify({ asset_id: state.modalAsset.id, x, y, text: "" }),
  });
  state.annotations.push(res.annotation);
  state.activeAnnotationId = res.annotation.id;
  renderAnnotations();
  renderMarkers();
  renderFloatingNote();
});

$("#imageStage").addEventListener("pointermove", async (e) => {
  if (!state.dragging) return;
  const r = $("#imageStage").getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width;
  const y = (e.clientY - r.top) / r.height;
  const ann = state.annotations.find((a) => a.id === state.dragging.id);
  if (!ann) return;
  ann.x = Math.max(0, Math.min(1, x));
  ann.y = Math.max(0, Math.min(1, y));
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

$("#search").addEventListener("input", (e) => {
  state.q = e.target.value || "";
  if (semanticQueryFromInput(state.q)) {
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
$("#showAll").onclick = async () => {
  state.viewCollectionId = "";
  renderCollections();
  setStats();
  await loadAssets();
};

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
      alert(`Delete failed: ${e2.message || e2}`);
    }
  }
};

$("#addSelected").onclick = async () => {
  await api(`/api/tray/add`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: Array.from(state.selected) }),
  });
  state.selected.clear();
  await loadTray();
  await loadAssets();
};

$("#addSelectedToCollection").onclick = async () => {
  if (!state.activeCollectionId || state.selected.size === 0) return;
  try {
    await api(`/api/collections/${state.activeCollectionId}/items`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: Array.from(state.selected) }),
    });
    state.selected.clear();
    await loadCollections();
    await loadAssets();
  } catch (e) {
    alert(`Add selected to collection failed: ${e.message || e}`);
  }
};

$("#removeSelectedFromCollection").onclick = async () => {
  if (!state.viewCollectionId || state.selected.size === 0) return;
  const ids = Array.from(state.selected);
  const col = getViewCollection();
  const ok = confirm(
    `Remove ${ids.length} selected item${ids.length === 1 ? "" : "s"} from "${col ? col.name : "this collection"}"?`
  );
  if (!ok) return;
  try {
    await api(`/api/collections/${state.viewCollectionId}/items/remove`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: ids }),
    });
    state.selected.clear();
    await loadCollections();
    await loadAssets();
  } catch (e) {
    alert(`Remove from collection failed: ${e.message || e}`);
  }
};

$("#addFiltered").onclick = async () => {
  const ids = state.assets.map((a) => a.id);
  await api(`/api/tray/add`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: ids }),
  });
  state.selected.clear();
  await loadTray();
  await loadAssets();
};

$("#clearSelection").onclick = () => {
  state.selected.clear();
  setStats();
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
  const stage = $("#imageStage");
  const r = stage.getBoundingClientRect();
  const x = ann.x * r.width;
  const y = ann.y * r.height;
  const left = Math.min(r.width - 240, Math.max(10, x + 12));
  const top = Math.min(r.height - 140, Math.max(10, y + 12));
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
  await loadCollections();
  await loadFacets();
  await loadTray();
  await loadAssets();
}

init();

async function loadFacets() {
  const data = await api("/api/facets");
  state.facets = data.facets;
  renderFilters();
}

function renderFilters() {
  const wrap = $("#filters");
  wrap.innerHTML = "";
  const groups = [
    { key: "sources", label: "Source", set: state.sources },
    { key: "boards", label: "Source Tags", set: state.boards },
    { key: "labels", label: "AI Tags", set: state.labels },
  ];

  for (const g of groups) {
    const items = state.facets[g.key] || [];
    if (!items.length) continue;
    const group = document.createElement("div");
    group.className = "filterGroup";
    group.innerHTML = `<div class="filterTitle">${g.label}</div>`;
    const list = document.createElement("div");
    list.className = "filterList";
    items.slice(0, 15).forEach((it) => {
      const value = it.source || it.board || it.label;
      const row = document.createElement("label");
      row.className = "filterItem";
      row.innerHTML = `<input type="checkbox" ${g.set.has(value) ? "checked" : ""} /> ${value} <span class="muted">(${it.n})</span>`;
      row.querySelector("input").addEventListener("change", (e) => {
        if (e.target.checked) g.set.add(value);
        else g.set.delete(value);
        loadAssets();
      });
      list.appendChild(row);
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
    el.className = "listItem";
    el.innerHTML = `<div><strong>${item.title || "(untitled)"}</strong></div><div class="muted">${item.source}</div>`;
    el.onclick = async () => {
      await api("/api/tray/remove", {
        method: "POST",
        body: JSON.stringify({ asset_ids: [item.id] }),
      });
      await loadTray();
    };
    wrap.appendChild(el);
  }
}

$("#clearTray").onclick = async () => {
  await api("/api/tray/clear", { method: "POST" });
  await loadTray();
};

$("#createFromTray").onclick = async () => {
  const name = prompt("Collection name:", "Curated — Round 1");
  if (!name) return;
  const res = await api("/api/tray/create-collection", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await loadCollections();
  await loadTray();
  await selectCollection(res.collection.id);
};

$("#addTrayToCollection").onclick = async () => {
  if (!state.activeCollectionId || state.tray.length === 0) return;
  try {
    await api(`/api/collections/${state.activeCollectionId}/items`, {
      method: "POST",
      body: JSON.stringify({ asset_ids: state.tray.map((x) => x.id) }),
    });
    await api("/api/tray/clear", { method: "POST" });
    await loadCollections();
    await loadTray();
    await loadAssets();
  } catch (e) {
    alert(`Add to collection failed: ${e.message || e}`);
  }
};
