// shared.js — utilities used by both index.html (app.js) and admin.html (admin.js)
(function () {
  // --- Actor token detection (magic links) ---
  // Check URL for ?actor=TOKEN on first visit, persist in localStorage
  const _urlActorToken = new URLSearchParams(window.location.search).get("actor");
  if (_urlActorToken) {
    localStorage.setItem("actorToken", _urlActorToken);
    // Also set a cookie so the token works across hostnames (localhost vs minime.local)
    document.cookie = `actorToken=${_urlActorToken}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    // Clean the URL so the token isn't visible / bookmarkable
    const cleaned = new URL(window.location);
    cleaned.searchParams.delete("actor");
    window.history.replaceState({}, "", cleaned.toString());
  }
  // Try localStorage first, fall back to cookie
  const actorToken = localStorage.getItem("actorToken")
    || (document.cookie.match(/(?:^|;\s*)actorToken=([^;]+)/) || [])[1]
    || "";

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
    const headers = {
      "Content-Type": "application/json",
      ...(actorToken ? { "X-Actor-Token": actorToken } : {}),
      ...(opts.headers || {}),
    };
    const res = await fetch(path, { ...opts, headers });
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

  function getActorToken() { return actorToken; }

  window.Shared = { escapeHtml, api, formatApiError, showToast, _removeToast, getActorToken };
})();
