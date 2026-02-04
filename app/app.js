const state = {
  assets: [],
  collections: [],
  activeCollectionId: "",
  targetCollectionId: "",
  selected: new Set(),
  q: "",
  source: "",
  modalAsset: null,
  annotations: [],
  selectMode: true,
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
  return a.thumb_path || a.stored_path || a.image_url || "";
}

function setStats() {
  const viewLabel = state.activeCollectionId ? "Viewing collection" : "Viewing all items";
  $("#stats").textContent = `${viewLabel} • ${state.assets.length} items`;
  $("#selectionCount").textContent = `${state.selected.size} selected`;
  $("#addSelected").disabled = state.selected.size === 0 || !state.targetCollectionId;
  $("#addFiltered").disabled = state.assets.length === 0 || !state.targetCollectionId;
  $("#removeSelected").disabled = state.selected.size === 0 || !state.activeCollectionId;
  $("#clearSelection").disabled = state.selected.size === 0;
  $("#collectionHint").textContent = state.targetCollectionId
    ? "Ready to add selected items."
    : "Create or pick a collection first.";
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

async function loadAssets() {
  const q = encodeURIComponent(state.q || "");
  const source = encodeURIComponent(state.source || "");
  const col = encodeURIComponent(state.activeCollectionId || "");
  const data = await api(`/api/assets?q=${q}&source=${source}&collection_id=${col}`);
  state.assets = data.assets;
  renderGrid();
}

async function openModal(asset) {
  state.modalAsset = asset;
  $("#modalTitle").textContent = asset.title || "(untitled)";
  $("#modalMeta").textContent = `${asset.source} • ${asset.source_ref || ""}`;
  $("#modalImage").src = thumbFor(asset);
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
    el.innerHTML = `<div><strong>#${idx + 1}</strong> ${ann.text || ""}</div>`;
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
    stage.appendChild(m);
  });
}

$("#imageStage").addEventListener("click", async (e) => {
  if (!state.modalAsset) return;
  const r = $("#imageStage").getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width;
  const y = (e.clientY - r.top) / r.height;
  const text = prompt("Note:", "");
  const res = await api("/api/annotations", {
    method: "POST",
    body: JSON.stringify({ asset_id: state.modalAsset.id, x, y, text }),
  });
  state.annotations.push(res.annotation);
  renderAnnotations();
  renderMarkers();
});

$("#closeModal").onclick = () => closeModal();
$("#modal").onclick = (e) => {
  if (e.target.id === "modal") closeModal();
};

$("#search").addEventListener("input", (e) => {
  state.q = e.target.value || "";
  loadAssets();
});
$("#source").addEventListener("change", (e) => {
  state.source = e.target.value || "";
  loadAssets();
});
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
  if (!state.targetCollectionId) return;
  await api(`/api/collections/${state.targetCollectionId}/items`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: Array.from(state.selected) }),
  });
  state.selected.clear();
  await loadCollections();
  await loadAssets();
};

$("#addFiltered").onclick = async () => {
  if (!state.targetCollectionId) return;
  const ids = state.assets.map((a) => a.id);
  await api(`/api/collections/${state.targetCollectionId}/items`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: ids }),
  });
  state.selected.clear();
  await loadCollections();
  await loadAssets();
};

$("#removeSelected").onclick = async () => {
  if (!state.activeCollectionId) return;
  const ids = Array.from(state.selected);
  for (const id of ids) {
    await api(`/api/collections/${state.activeCollectionId}/items/${id}`, { method: "DELETE" });
  }
  state.selected.clear();
  await loadCollections();
  await loadAssets();
};
$("#clearSelection").onclick = () => {
  state.selected.clear();
  setStats();
};

$("#collectionSelect").onchange = (e) => {
  state.targetCollectionId = e.target.value || "";
  renderCollections();
  setStats();
};

// refresh button removed

async function init() {
  await loadCollections();
  await loadAssets();
}

init();
