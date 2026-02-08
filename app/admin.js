const state = {
  token: "",
  assets: [],
  selected: new Set(),
  q: "",
};

const $ = (sel) => document.querySelector(sel);

function escapeHtml(value) {
  return (value || "")
    .toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, opts = {}, requireAuth = false) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (requireAuth) headers["X-Admin-Token"] = state.token;
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

function setUiState() {
  const unlocked = !!state.token;
  $("#adminPassword").disabled = unlocked;
  $("#unlockAdmin").disabled = unlocked;
  $("#lockAdmin").disabled = !unlocked;
  $("#adminSearch").disabled = !unlocked;
  $("#reloadAssets").disabled = !unlocked;
  $("#selectAllAssets").disabled = !unlocked || state.assets.length === 0;
  $("#clearAssetSelection").disabled = !unlocked || state.selected.size === 0;
  $("#deleteFromDb").disabled = !unlocked || state.selected.size === 0;
  $("#selectionCount").textContent = `${state.selected.size} selected`;
  if (!unlocked) {
    $("#authStatus").textContent = "Enter admin password to unlock delete actions.";
  } else {
    $("#authStatus").textContent = "Admin mode unlocked. Deletions require DELETE confirmation text.";
  }
}

function renderAssets() {
  const wrap = $("#adminAssets");
  wrap.innerHTML = "";
  if (!state.assets.length) {
    wrap.innerHTML = '<div class="muted">No assets loaded.</div>';
    setUiState();
    return;
  }
  for (const a of state.assets) {
    const title = a.title || "(untitled)";
    const board = a.board || "no board";
    const el = document.createElement("div");
    el.className = "listItem";
    el.innerHTML = `
      <label class="filterItem">
        <input type="checkbox" ${state.selected.has(a.id) ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(title)}</strong>
          <span class="muted"> • ${escapeHtml(a.source)} • ${escapeHtml(board)}</span>
          <span class="muted" style="display: block">id: ${escapeHtml(a.id)}</span>
        </span>
      </label>
    `;
    const cb = el.querySelector("input");
    cb.addEventListener("change", () => {
      if (cb.checked) state.selected.add(a.id);
      else state.selected.delete(a.id);
      setUiState();
    });
    wrap.appendChild(el);
  }
  setUiState();
}

async function loadAssets() {
  if (!state.token) return;
  const q = encodeURIComponent(state.q || "");
  const data = await api(`/api/assets?q=${q}&limit=200`);
  state.assets = data.assets || [];
  state.selected.clear();
  renderAssets();
}

$("#unlockAdmin").onclick = async () => {
  const password = ($("#adminPassword").value || "").trim();
  if (!password) {
    $("#authStatus").textContent = "Password required.";
    return;
  }
  try {
    const res = await api("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    state.token = res.token || "";
    $("#adminPassword").value = "";
    $("#deleteStatus").textContent = "Admin mode ready. Load assets and choose what to delete from DB.";
    await loadAssets();
  } catch (e) {
    $("#authStatus").textContent = `Login failed: ${e.message || e}`;
  } finally {
    setUiState();
  }
};

$("#lockAdmin").onclick = async () => {
  try {
    if (state.token) {
      await api("/api/admin/logout", { method: "POST" }, true);
    }
  } catch {
    // no-op
  }
  state.token = "";
  state.assets = [];
  state.selected.clear();
  $("#adminAssets").innerHTML = '<div class="muted">No assets loaded.</div>';
  setUiState();
};

$("#reloadAssets").onclick = async () => {
  state.q = $("#adminSearch").value || "";
  try {
    await loadAssets();
    $("#deleteStatus").textContent = `Loaded ${state.assets.length} assets.`;
  } catch (e) {
    $("#deleteStatus").textContent = `Load failed: ${e.message || e}`;
  }
};

$("#adminSearch").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter") return;
  state.q = $("#adminSearch").value || "";
  try {
    await loadAssets();
    $("#deleteStatus").textContent = `Loaded ${state.assets.length} assets.`;
  } catch (err) {
    $("#deleteStatus").textContent = `Load failed: ${err.message || err}`;
  }
});

$("#selectAllAssets").onclick = () => {
  state.assets.forEach((a) => state.selected.add(a.id));
  renderAssets();
};

$("#clearAssetSelection").onclick = () => {
  state.selected.clear();
  renderAssets();
};

$("#deleteFromDb").onclick = async () => {
  if (!state.token || state.selected.size === 0) return;
  const ids = Array.from(state.selected);
  const ok = confirm(
    `Delete ${ids.length} selected media item${ids.length === 1 ? "" : "s"} from the primary database? A backup will be created first.`
  );
  if (!ok) return;
  const phrase = prompt("Type DELETE to continue:", "");
  if (phrase !== "DELETE") {
    $("#deleteStatus").textContent = "Delete canceled: confirmation text did not match.";
    return;
  }
  try {
    const res = await api(
      "/api/admin/assets/delete",
      {
        method: "POST",
        body: JSON.stringify({
          admin_mode: true,
          confirm: phrase,
          asset_ids: ids,
        }),
      },
      true
    );
    const deleted = res.deleted || 0;
    const backup = res.backup_path || "(unknown)";
    $("#deleteStatus").textContent = `Deleted ${deleted} media item${deleted === 1 ? "" : "s"}. Backup: ${backup}`;
    await loadAssets();
  } catch (e) {
    $("#deleteStatus").textContent = `Delete failed: ${e.message || e}`;
  }
};

setUiState();
renderAssets();
