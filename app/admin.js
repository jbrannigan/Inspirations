const state = {
  token: "",
  assets: [],
  selected: new Set(),
  q: "",
  configured: null,
  setupAllowed: false,
  pendingMediaRepairs: [],
  refreshingMediaRepairs: false,
  optimizingDb: false,
  authMessage: "",
};

const $ = (sel) => document.querySelector(sel);
const escapeHtml = Shared.escapeHtml;
const formatApiError = Shared.formatApiError;

async function api(path, opts = {}, requireAuth = false) {
  const headers = { ...(opts.headers || {}) };
  if (requireAuth) headers["X-Admin-Token"] = state.token;
  return Shared.api(path, { ...opts, headers });
}

function setUiState() {
  const unlocked = !!state.token;
  const configured = state.configured === true;
  $("#adminPassword").disabled = unlocked || !configured;
  $("#unlockAdmin").disabled = unlocked || !configured;
  $("#lockAdmin").disabled = !unlocked;
  $("#adminSearch").disabled = !unlocked;
  $("#reloadAssets").disabled = !unlocked;
  $("#selectAllAssets").disabled = !unlocked || state.assets.length === 0;
  $("#clearAssetSelection").disabled = !unlocked || state.selected.size === 0;
  $("#deleteFromDb").disabled = !unlocked || state.selected.size === 0;
  $("#optimizeDb").disabled = !unlocked || state.optimizingDb;
  $("#refreshMediaRepairs").disabled =
    !unlocked || state.refreshingMediaRepairs || state.pendingMediaRepairs.length === 0;
  $("#selectionCount").textContent = `${state.selected.size} selected`;
  $("#adminSetup").hidden = configured;
  $("#setupForm").hidden = !state.setupAllowed;
  if (state.authMessage) {
    $("#authStatus").textContent = state.authMessage;
  } else if (!configured) {
    $("#authStatus").textContent = "Admin mode needs a password before it can be entered.";
  } else if (!unlocked) {
    $("#authStatus").textContent = "Enter the admin password to unlock maintenance actions.";
  } else {
    $("#authStatus").textContent = "Admin mode unlocked. Maintenance actions are available.";
  }
}

function renderMediaRepairs() {
  const wrap = $("#mediaRepairItems");
  wrap.innerHTML = "";
  if (!state.pendingMediaRepairs.length) {
    $("#mediaRepairStatus").textContent = "No repaired items are waiting for search-evidence refresh.";
    setUiState();
    return;
  }
  $("#mediaRepairStatus").textContent =
    `${state.pendingMediaRepairs.length} repaired item${state.pendingMediaRepairs.length === 1 ? "" : "s"} waiting for refresh.`;
  for (const item of state.pendingMediaRepairs) {
    const el = document.createElement("div");
    el.className = "listItem";
    el.innerHTML = `
      <strong>${escapeHtml(item.title || "(untitled)")}</strong>
      <span class="muted" style="display: block">${escapeHtml(item.repair_kind || "replacement media")} • id: ${escapeHtml(item.asset_id || "")}</span>
    `;
    wrap.appendChild(el);
  }
  setUiState();
}

async function loadAdminStatus() {
  const res = await api("/api/admin/status");
  state.configured = !!res.configured;
  state.setupAllowed = !!res.setup_allowed;
  state.pendingMediaRepairs = res.pending_media_repairs || [];
  if (!state.configured) {
    $("#setupHelp").textContent = state.setupAllowed
      ? "First-time setup: choose an admin password. It will be stored privately on this Mac."
      : "First-time setup must be completed on the Mac itself. Open http://localhost:8001/app/admin.html on the Mac.";
  }
  renderMediaRepairs();
  setUiState();
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
    state.authMessage = "";
    $("#adminPassword").value = "";
    $("#deleteStatus").textContent = "Admin mode ready. Load assets and choose what to delete from DB.";
    await loadAssets();
  } catch (e) {
    state.authMessage = `Login failed: ${e.message || e}`;
  } finally {
    setUiState();
  }
};

$("#setupAdmin").onclick = async () => {
  const password = ($("#newAdminPassword").value || "").trim();
  const confirmPassword = ($("#confirmAdminPassword").value || "").trim();
  try {
    await api("/api/admin/setup", {
      method: "POST",
      body: JSON.stringify({ password, confirm_password: confirmPassword }),
    });
    $("#newAdminPassword").value = "";
    $("#confirmAdminPassword").value = "";
    state.authMessage = "Admin password created. Enter it below to unlock maintenance actions.";
    await loadAdminStatus();
  } catch (e) {
    state.authMessage = `Setup failed: ${e.message || e}`;
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
  state.authMessage = "";
  state.assets = [];
  state.selected.clear();
  $("#adminAssets").innerHTML = '<div class="muted">No assets loaded.</div>';
  setUiState();
};

$("#reloadMediaRepairs").onclick = async () => {
  try {
    await loadAdminStatus();
  } catch (e) {
    $("#mediaRepairStatus").textContent = `Check failed: ${e.message || e}`;
  }
};

$("#refreshMediaRepairs").onclick = async () => {
  if (!state.token || state.pendingMediaRepairs.length === 0) return;
  state.refreshingMediaRepairs = true;
  $("#mediaRepairStatus").textContent = "Refreshing repaired items. This can take a little while...";
  setUiState();
  try {
    const res = await api("/api/admin/media-repairs/refresh", { method: "POST" }, true);
    const failed = (res.failed || []).length;
    $("#mediaRepairStatus").textContent =
      `Refreshed ${res.refreshed || 0} item${res.refreshed === 1 ? "" : "s"}.` +
      (failed ? ` ${failed} item${failed === 1 ? "" : "s"} still need attention.` : "");
    await loadAdminStatus();
  } catch (e) {
    $("#mediaRepairStatus").textContent = `Refresh failed: ${e.message || e}`;
  } finally {
    state.refreshingMediaRepairs = false;
    setUiState();
  }
};

$("#optimizeDb").onclick = async () => {
  if (!state.token || state.optimizingDb) return;
  state.optimizingDb = true;
  $("#dbOptimizeStatus").textContent = "Optimizing database and rebuilding text search...";
  setUiState();
  try {
    const res = await api(
      "/api/admin/database/optimize",
      {
        method: "POST",
        body: JSON.stringify({ rebuild_search: true }),
      },
      true
    );
    const after = res.search_index_after || {};
    const duration = typeof res.duration_ms === "number" ? `${res.duration_ms} ms` : "complete";
    $("#dbOptimizeStatus").textContent =
      `Optimized in ${duration}. Search index: ${after.indexed_assets || 0}/${after.asset_count || 0} assets.`;
  } catch (e) {
    $("#dbOptimizeStatus").textContent = `Optimize failed: ${e.message || e}`;
  } finally {
    state.optimizingDb = false;
    setUiState();
  }
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
loadAdminStatus().catch((e) => {
  $("#authStatus").textContent = `Could not check admin setup: ${e.message || e}`;
  $("#mediaRepairStatus").textContent = "Could not check pending repairs.";
});
