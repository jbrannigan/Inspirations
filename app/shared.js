// shared.js — utilities used by both index.html (app.js) and admin.html (admin.js)
(function () {
  function escapeHtml(value) {
    return (value || "")
      .toString()
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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

  function showToast(message, options) {
    const { type = "info", duration = 5000, actionLabel, onAction } = options || {};
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span class="toast-message">${escapeHtml(message)}</span>`;
    if (actionLabel && onAction) {
      const btn = document.createElement("button");
      btn.className = "toast-action";
      btn.textContent = actionLabel;
      btn.onclick = () => { onAction(); _removeToast(toast); };
      toast.appendChild(btn);
    }
    container.appendChild(toast);
    toast._timer = setTimeout(() => _removeToast(toast), duration);
  }

  function _removeToast(toast) {
    if (toast._removed) return;
    toast._removed = true;
    clearTimeout(toast._timer);
    toast.classList.add("toast-exit");
    toast.addEventListener("animationend", () => toast.remove());
  }

  window.Shared = { escapeHtml, api, formatApiError, showToast, _removeToast };
})();
