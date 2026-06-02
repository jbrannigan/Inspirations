// shared.js — utilities used by both index.html (app.js) and admin.html (admin.js)
(function () {
  const _basePath = (window.__BASE_PATH || "").replace(/\/+$/, "");

  // Legacy magic-link tokens are no longer used by the local app. Strip them
  // from URLs so old bookmarks do not keep exposing stale collaborator tokens.
  const _urlActorToken = (new URLSearchParams(window.location.search).get("actor") || "").trim();
  if (_urlActorToken) {
    const cleaned = new URL(window.location);
    cleaned.searchParams.delete("actor");
    window.history.replaceState({}, "", cleaned.toString());
  }

  function escapeHtml(value) {
    return (value || "")
      .toString()
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function prefixPath(path) {
    if (_basePath && typeof path === "string" && path.startsWith("/")) {
      return _basePath + path;
    }
    return path;
  }

  async function api(path, opts = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    };
    const res = await fetch(prefixPath(path), { ...opts, headers });
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
    if (/^\s*<!doctype html>/i.test(msg) || /^\s*<html/i.test(msg)) {
      const codeMatch = msg.match(/Error code:\s*([0-9]{3})/i);
      const messageMatch = msg.match(/Message:\s*([^<\n\r]+)/i);
      const code = codeMatch ? codeMatch[1] : "";
      const detail = messageMatch ? messageMatch[1].trim().replace(/\.$/, "") : "";
      if (code && detail) return `${code}: ${detail}`;
      if (code) return `Request failed (${code})`;
      return "Request failed";
    }
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

  function getActorToken() { return ""; }

  window.Shared = { escapeHtml, api, formatApiError, showToast, _removeToast, getActorToken, basePath: _basePath, prefixPath };
})();
