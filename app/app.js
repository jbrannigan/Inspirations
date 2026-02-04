const state = {
  assets: [],
  collections: [],
  activeCollectionId: "",
  targetCollectionId: "",
  selected: new Set(),
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
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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

function thumbFor(a) {
  if (a.thumb_path) return `/media/${a.id}?kind=thumb`;
  if (a.stored_path) return `/media/${a.id}?kind=original`;
  return a.image_url || "";
}

function setStats() {
  const viewLabel = state.activeCollectionId ? "Viewing collection" : "Viewing all items";
  $("#stats").textContent = `${viewLabel} • ${state.assets.length} items`;
  $("#addSelected").disabled = state.selected.size === 0;
  $("#addFiltered").disabled = state.assets.length === 0;
  $("#clearSelection").disabled = state.selected.size === 0;
  $("#collectionHint").textContent = state.targetCollectionId
    ? "Ready to add selected items."
    : "Create or pick a collection first.";
  $("#trayCount").textContent = `${state.tray.length} items`;
  $("#createFromTray").disabled = state.tray.length === 0;
  $("#clearTray").disabled = state.tray.length === 0;
}

function renderCollections() {
  const wrap = $("#collections");
  wrap.innerHTML = "";
  for (const c of state.collections) {
    const el = document.createElement("div");
    el.className = `listItem ${c.id === state.activeCollectionId ? "on" : ""}`;
    el.innerHTML = `<div><strong>${c.name}</strong></div><div class="muted">${c.count} items</div>`;
    el.onclick = () => {
      state.targetCollectionId = c.id;
      $("#collectionSelect").value = c.id;
      renderCollections();
      setStats();
    };
    wrap.appendChild(el);
  }

  const sel = $("#collectionSelect");
  sel.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Select collection…";
  sel.appendChild(placeholder);
  for (const c of state.collections) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = c.name;
    sel.appendChild(opt);
  }
  if (!state.targetCollectionId && state.collections.length) {
    state.targetCollectionId = state.collections[0].id;
  }
  if (state.targetCollectionId) sel.value = state.targetCollectionId;
}

function renderGrid() {
  const wrap = $("#grid");
  wrap.innerHTML = "";
  for (const a of state.assets) {
    const el = document.createElement("div");
    el.className = `card ${state.selected.has(a.id) ? "selected" : ""}`;
    const img = thumbFor(a);
    el.innerHTML = `
      <div class="thumb">
        ${img ? `<img src="${img}" />` : ""}
        <div class="badge">${a.source}</div>
        <label class="selectBox"><input type="checkbox" ${state.selected.has(a.id) ? "checked" : ""} /></label>
      </div>
      <div class="cardBody">${a.title || "(untitled)"}</div>
    `;
    const checkbox = el.querySelector("input");
    checkbox.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleSelect(a.id);
      renderGrid();
    });
    el.onclick = () => openModal(a);
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
  renderCollections();
}

async function loadTray() {
  const data = await api("/api/tray");
  state.tray = data.items;
  renderTray();
  setStats();
}

async function loadAssets() {
  const q = encodeURIComponent(state.q || "");
  const source = encodeURIComponent(Array.from(state.sources).join(","));
  const board = encodeURIComponent(Array.from(state.boards).join(","));
  const label = encodeURIComponent(Array.from(state.labels).join(","));
  const col = encodeURIComponent(state.activeCollectionId || "");
  const data = await api(`/api/assets?q=${q}&source=${source}&board=${board}&label=${label}&collection_id=${col}`);
  state.assets = data.assets;
  renderGrid();
}

async function openModal(asset) {
  state.modalAsset = asset;
  $("#modalTitle").textContent = asset.title || "(untitled)";
  $("#modalMeta").textContent = `${asset.source} • ${asset.source_ref || ""}`;
  $("#modalImage").src = thumbFor(asset);
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
    el.className = "listItem";
    el.innerHTML = `
      <div><strong>#${idx + 1}</strong></div>
      <textarea data-ann="${ann.id}">${ann.text || ""}</textarea>
      <div class="row" style="margin-top:6px">
        <button data-del="${ann.id}">Delete</button>
      </div>
    `;
    const ta = el.querySelector("textarea");
    ta.addEventListener("input", async () => {
      await api(`/api/annotations/${ann.id}`, {
        method: "PUT",
        body: JSON.stringify({ text: ta.value }),
      });
    });
    el.querySelector("[data-del]").onclick = async () => {
      await api(`/api/annotations/${ann.id}`, { method: "DELETE" });
      state.annotations = state.annotations.filter((x) => x.id !== ann.id);
      renderAnnotations();
      renderMarkers();
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
    m.onpointerdown = (e) => {
      e.stopPropagation();
      m.setPointerCapture(e.pointerId);
      state.dragging = { id: ann.id, pointerId: e.pointerId };
    };
    stage.appendChild(m);
  });
}

$("#imageStage").addEventListener("click", async (e) => {
  if (!state.modalAsset) return;
  if (state.dragging) return;
  const r = $("#imageStage").getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width;
  const y = (e.clientY - r.top) / r.height;
  const res = await api("/api/annotations", {
    method: "POST",
    body: JSON.stringify({ asset_id: state.modalAsset.id, x, y, text: "" }),
  });
  state.annotations.push(res.annotation);
  renderAnnotations();
  renderMarkers();
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
  renderMarkers();
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
  loadAssets();
});
// top source dropdown not used; filters panel handles sources
$("#showAll").onclick = () => {
  state.activeCollectionId = "";
  renderCollections();
  loadAssets();
};

$("#viewCollection").onclick = () => {
  if (!state.targetCollectionId) return;
  state.activeCollectionId = state.targetCollectionId;
  renderCollections();
  loadAssets();
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
  state.collections.unshift(res.collection);
  state.targetCollectionId = res.collection.id;
  renderCollections();
};

$("#deleteCollection").onclick = async () => {
  if (!state.targetCollectionId) return;
  const c = state.collections.find((x) => x.id === state.targetCollectionId);
  const ok = confirm(`Delete collection "${c ? c.name : ""}"? This cannot be undone.`);
  if (!ok) return;
  try {
    await api(`/api/collections/${state.targetCollectionId}`, { method: "DELETE" });
    state.collections = state.collections.filter((x) => x.id !== state.targetCollectionId);
    state.targetCollectionId = "";
    state.activeCollectionId = "";
    renderCollections();
    await loadCollections();
    await loadAssets();
  } catch (e) {
    // fallback for servers that only support JSON body for DELETE
    try {
      await api(`/api/collections`, {
        method: "DELETE",
        body: JSON.stringify({ id: state.targetCollectionId }),
      });
      state.collections = state.collections.filter((x) => x.id !== state.targetCollectionId);
      state.targetCollectionId = "";
      state.activeCollectionId = "";
      renderCollections();
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

$("#collectionSelect").onchange = (e) => {
  state.targetCollectionId = e.target.value || "";
  renderCollections();
  setStats();
};

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
  await api("/api/tray/create-collection", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await loadCollections();
  await loadTray();
};
