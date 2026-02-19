# Inspirations UX Refactor — Full Audit Sweep

## Context

The UX audit (`docs/ux_audit_2026-02-16.md`) identified 28 findings across visual hierarchy, spacing, accessibility, and modern UI patterns. This plan addresses all findings. Per owner decision, accessibility tier is **C (Personal)** — so we skip pure a11y items and focus on visual/UX improvements.

**Findings skipped (Tier C):** A-1 (skip nav), A-3 (ARIA labels), A-4 (focus management), A-5 (focus trap), A-6 (keyboard cards), A-8 (focus indicators), A-9 (alt text), A-10 (tooltip), A-11 (keyboard collections) — 9 items

**Findings addressed:** 19 items across 5 phases

## Files Modified

| File | Changes |
|------|---------|
| `app/shared.js` | **NEW** — extracted shared utilities (escapeHtml, api, formatApiError, showToast) |
| `app/styles.css` | Type scale, spacing utilities, contrast fixes, toast styles, skeleton animations, toolbar layout, empty state, mobile fixes |
| `app/index.html` | Remove inline styles, toolbar restructure, toast container, utility classes |
| `app/app.js` | Grid perf fix, toolbar state logic, toast replacements, undo patterns, loading skeletons, displayTitle fix, empty state, card footer simplification |
| `app/admin.html` | Add shared.js script tag, admin shell class |
| `app/admin.js` | Replace duplicated functions with Shared.* calls |

## Key Architecture Constraints

- **Vanilla JS only** (D004) — no React/Vue/build step
- **No external dependencies** (D001) — no npm packages
- **Single app.js, single styles.css** — no module bundler
- Grid renders 240 items per page (`ASSETS_PAGE_SIZE = 240` in app.js line 46)
- Cards use `el.innerHTML = "..."` pattern throughout
- The project has Python tests but no frontend tests
- `app.js` has an `init()` function called on load (line 1618) — do NOT load app.js from admin.html

---

## Phase 1: Foundation — CSS System + Shared Utils
**Findings: SP-1, SP-2, SP-3, SP-6, VH-1, UI-5**

### 1a. Create `app/shared.js` (UI-5)
Extract from app.js and admin.js into a new shared file:
- `escapeHtml(value)` — from app.js:48-56
- `api(path, opts)` — from app.js:152-162
- `formatApiError(err)` — from app.js:176-184
- Expose as `window.Shared = { escapeHtml, api, formatApiError }`

Update index.html and admin.html to load `<script src="/app/shared.js"></script>` before page-specific scripts.

In app.js: alias `const escapeHtml = Shared.escapeHtml` etc at the top, remove the original function definitions.

In admin.js: remove the duplicated `escapeHtml()` (lines 10-18) and base `api()` (lines 20-29). Replace with:
```javascript
const escapeHtml = Shared.escapeHtml;
const formatApiError = Shared.formatApiError;

async function api(path, opts = {}, requireAuth = false) {
  const headers = { ...(opts.headers || {}) };
  if (requireAuth) headers["X-Admin-Token"] = state.token;
  return Shared.api(path, { ...opts, headers });
}
```

### 1b. CSS spacing utilities + remove inline styles (SP-1, SP-2)
Add utility classes to styles.css (after the `:root` block):
```css
.mt-1 { margin-top: 4px; }
.mt-2 { margin-top: 8px; }
.mt-3 { margin-top: 12px; }
.mt-4 { margin-top: 16px; }
.flex-wrap { flex-wrap: wrap; }
```

Replace all 8 inline `style` attributes in index.html with utility classes:
- Line 67: `style="margin-top: 8px"` → add `mt-2` to class
- Line 71: `style="margin-top: 6px"` → add `mt-2` to class (round 6→8)
- Line 100: `style="margin-top: 10px"` → add `mt-3` to class (round 10→12)
- Line 113: `style="margin-top: 8px; flex-wrap: wrap"` → add `mt-2 flex-wrap` to class
- Line 118: `style="margin-top: 8px"` → add `mt-2` to class
- Line 119: `style="margin-top: 6px"` → add `mt-2` to class
- Line 201 (in modal): `style="margin-top: 12px"` → add `mt-3` to class
- Line 203 (in modal): `style="margin-top: 6px"` → add `mt-2` to class

Standardize gap values in existing CSS rules to 4px-based scale:
- `.searchInputRow` gap: 6px → 8px
- `.chips` gap: 6px → 8px
- `.compactTags` gap: 6px → 8px
- `.filterList` gap: 6px → 8px
- `.grid` gap: 10px → 12px

### 1c. Type scale (VH-1)
Add CSS custom properties to `:root`:
```css
--fs-xs: 10px;
--fs-sm: 12px;
--fs-base: 14px;
--fs-md: 16px;
--fs-lg: 18px;
--fs-xl: 22px;
```
Apply type scale changes in styles.css:
- `.title`: 14px → `var(--fs-lg)` (18px)
- `.sectionTitle`: 12px → `var(--fs-base)` (14px)
- `.cardTitle`: 13px → `var(--fs-base)` (14px)
- `.modalTitle`: 14px → `var(--fs-md)` (16px)
- Keep `.muted`, `.cardMeta`, `.cardSummary` at `var(--fs-sm)` (12px)
- Keep `.chip`, `.tagTitle`, `.badge` at `var(--fs-xs)` (10-11px)

### 1d. Sidebar width fix (SP-3)
Change `.layout.three` from `grid-template-columns: 260px 1fr 260px` to `280px 1fr 280px`

### 1e. Admin shell (SP-6)
Add to styles.css:
```css
.adminShell { max-width: 800px; margin: 0 auto; padding: 24px 16px; }
```
Ensure admin.html uses `class="adminShell"` on its content wrapper.

---

## Phase 2: Toolbar Redesign + Grid Performance
**Findings: VH-2, VH-3, VH-4, UI-1, UI-8**

### 2a. Contextual toolbar (VH-2, VH-3, VH-4)
Replace the current toolbar HTML (index.html lines 76-97) with contextual sections. The key insight: **hide inapplicable buttons instead of showing them disabled**.

New structure:
```html
<div class="toolbar">
  <div class="toolbarMeta">
    <div id="stats" class="muted">Loading...</div>
    <div id="canvasControls" class="row toolbar-section">
      <button id="toggleLabelMode" type="button">AI Tags: Any</button>
      <button id="showAll">Show All</button>
      <button id="showTrayCanvas">Show Tray Canvas</button>
      <button id="reviewCollection" disabled>Review Collection</button>
    </div>
  </div>

  <!-- Selection actions: hidden when nothing selected -->
  <div id="selectionBar" class="toolbar-section" hidden>
    <div class="toolbar-divider"></div>
    <div class="row">
      <span class="toolbar-label" id="selectionLabel">0 selected</span>
      <button id="addSelectedToCollection" class="primaryAction" disabled>Add to Collection</button>
      <button id="addSelected" disabled>Add to Tray</button>
      <button id="removeSelectedFromCollection" disabled>Remove from Collection</button>
      <button id="removeSelectedFromTray" disabled>Remove from Tray</button>
      <button id="clearSelection">Clear</button>
    </div>
  </div>

  <!-- Bulk/tray actions -->
  <div id="trayToolbar" class="toolbar-section">
    <div class="row">
      <button id="selectAll">Select All</button>
      <button id="addFiltered" disabled>Add Filtered</button>
      <button id="createFromTrayTop" disabled>Create Collection</button>
      <button id="addTrayToCollectionTop" disabled>Add Tray to Collection</button>
      <button id="clearTrayTop" disabled>Clear Tray</button>
    </div>
  </div>
</div>
```

In `setStats()` (app.js ~line 590), add logic to show/hide `#selectionBar`:
```javascript
const selectionBar = $("#selectionBar");
if (selectionBar) {
  selectionBar.hidden = state.selected.size === 0;
  const label = $("#selectionLabel");
  if (label) label.textContent = `${state.selected.size} selected`;
}
```

CSS additions:
```css
.toolbar-section { margin-top: 4px; }
.toolbar-divider { height: 1px; background: var(--border); margin: 4px 0; }
.toolbar-label { font-size: var(--fs-sm); color: var(--muted); white-space: nowrap; }
.toolbar-section + .toolbar-section { padding-top: 4px; border-top: 1px solid rgba(255, 255, 255, 0.04); }
```

### 2b. Grid performance fix (UI-1)
The problem: `renderGrid()` calls `wrap.innerHTML = ""` and rebuilds all 240 cards on every checkbox click and card expansion.

**Fix:** Add `data-id` to each card, then do targeted updates instead of full rebuild.

In `renderGrid()` (app.js line 685), add:
```javascript
el.dataset.id = a.id;
```

New function:
```javascript
function updateCardState(id) {
  const el = document.querySelector(`.card[data-id="${id}"]`);
  if (!el) return;
  el.classList.toggle("selected", state.selected.has(id));
  el.classList.toggle("expanded", state.expanded.has(id));
  const cb = el.querySelector("input[type=checkbox]");
  if (cb) cb.checked = state.selected.has(id);
  setStats();
}
```

Change checkbox click handler (app.js ~line 783):
```javascript
checkbox.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleSelect(a.id);
  updateCardState(a.id);  // was: renderGrid()
});
```

Change card click handler (app.js ~line 801):
```javascript
el.onclick = () => {
  if (state.expanded.has(a.id)) state.expanded.delete(a.id);
  else state.expanded.add(a.id);
  updateCardState(a.id);  // was: renderGrid()
};
```

Keep `renderGrid()` for: data loads, filter changes, selectAll, clearSelection.

### 2c. Mobile toolbar scroll affordance (UI-8)
At ≤700px breakpoint, add CSS mask to hint at scrollable content:
```css
@media (max-width: 700px) {
  .toolbar .row {
    -webkit-mask-image: linear-gradient(to right, black 85%, transparent 100%);
    mask-image: linear-gradient(to right, black 85%, transparent 100%);
  }
  .toolbar .row.scrolled-end {
    -webkit-mask-image: none;
    mask-image: none;
  }
}
```

Add scroll listener in app.js init:
```javascript
document.querySelectorAll('.toolbar .row').forEach(row => {
  row.addEventListener('scroll', () => {
    const atEnd = row.scrollLeft + row.clientWidth >= row.scrollWidth - 8;
    row.classList.toggle('scrolled-end', atEnd);
  });
});
```

---

## Phase 3: Toast System + Alert/Confirm Replacement
**Findings: UI-3, UI-4, A-2, A-7**

### 3a. Toast notification system
Add `showToast()` and `removeToast()` to `shared.js`:
```javascript
Shared.showToast = function(message, options = {}) {
  const { type = "info", duration = 5000, actionLabel, onAction } = options;
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-message">${Shared.escapeHtml(message)}</span>`;
  if (actionLabel && onAction) {
    const btn = document.createElement("button");
    btn.className = "toast-action";
    btn.textContent = actionLabel;
    btn.onclick = () => { onAction(); Shared._removeToast(toast); };
    toast.appendChild(btn);
  }
  container.appendChild(toast);
  toast._timer = setTimeout(() => Shared._removeToast(toast), duration);
};

Shared._removeToast = function(toast) {
  if (toast._removed) return;
  toast._removed = true;
  clearTimeout(toast._timer);
  toast.classList.add("toast-exit");
  toast.addEventListener("animationend", () => toast.remove());
};
```

Add toast container to index.html (before `</body>`):
```html
<div id="toastContainer" class="toast-container" aria-live="polite"></div>
```

Add toast CSS to styles.css:
```css
.toast-container {
  position: fixed; bottom: 16px; right: 16px;
  display: grid; gap: 8px; z-index: 90; max-width: min(400px, 90vw);
}
.toast {
  padding: 12px 16px; border-radius: 10px;
  background: rgba(16, 24, 36, 0.95); border: 1px solid var(--border);
  color: var(--text); font-size: var(--fs-sm);
  display: flex; align-items: center; gap: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  animation: toast-in 0.25s ease;
}
.toast.toast-exit { animation: toast-out 0.2s ease forwards; }
.toast-success { border-left: 3px solid var(--accent-2); }
.toast-error { border-left: 3px solid #ff7a7a; }
.toast-info { border-left: 3px solid var(--accent); }
.toast-message { flex: 1; }
.toast-action {
  background: none; border: none; color: var(--accent);
  font-weight: 600; cursor: pointer; padding: 4px 8px; white-space: nowrap;
}
@keyframes toast-in { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
@keyframes toast-out { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
```

### 3b. Replace all alert() calls (UI-3)
Replace every `alert()` in app.js with `Shared.showToast()`:

| Location | Current | Replacement |
|----------|---------|-------------|
| ~line 305 | `alert(options.invalidMessage)` | `Shared.showToast(options.invalidMessage, { type: "error" })` |
| ~line 981 | `alert("Print failed: " + err.message)` | `Shared.showToast("Print failed: " + err.message, { type: "error" })` |
| ~line 1013 | `alert("Print failed: " + err.message)` | `Shared.showToast("Print failed: " + err.message, { type: "error" })` |
| ~line 1020 | `alert("Print failed: " + err.message)` | `Shared.showToast("Print failed: " + err.message, { type: "error" })` |
| ~line 1089 | `alert("Unhide failed: " + ...)` | `Shared.showToast("Unhide failed: " + ..., { type: "error" })` |
| ~line 1115 | `alert("Hide failed: " + ...)` | `Shared.showToast("Hide failed: " + ..., { type: "error" })` |
| ~line 1426 | `alert("Delete failed: " + ...)` | `Shared.showToast("Delete failed: " + ..., { type: "error" })` |
| ~line 1456 | `alert("Add selected to collection failed: " + ...)` | `Shared.showToast("Add failed: " + ..., { type: "error" })` |
| ~line 1478 | `alert("Remove from collection failed: " + ...)` | `Shared.showToast("Remove failed: " + ..., { type: "error" })` |
| ~line 1880 | `alert(msg)` (scan import success) | `Shared.showToast(msg, { type: "success" })` |
| ~line 1883 | `alert("Scan import failed: " + ...)` | `Shared.showToast("Scan import failed: " + ..., { type: "error", duration: 8000 })` |
| ~line 1955 | `alert(msg)` (photo import success) | `Shared.showToast(msg, { type: "success" })` |
| ~line 1958 | `alert("Photo import failed: " + ...)` | `Shared.showToast("Photo import failed: " + ..., { type: "error", duration: 8000 })` |
| ~line 2038 | `alert("Please choose a PDF file.")` | `Shared.showToast("Please choose a PDF file.", { type: "error" })` |

### 3c. Replace confirm() with undo toasts where reversible (UI-4)
For reversible actions, execute immediately then show undo toast:

**Remove from collection** (~line 1465): Execute API remove, then:
```javascript
Shared.showToast(`Removed ${count} items from "${colName}"`, {
  type: "success",
  actionLabel: "Undo",
  onAction: async () => {
    await api(`/api/collections/${colId}/items`, {
      method: "POST", body: JSON.stringify({ asset_ids: removedIds })
    });
    await loadCollections(); await loadAssets();
    Shared.showToast("Restored items.", { type: "info" });
  }
});
```

**Hide asset** (~line 1093): Execute hide, show undo toast that calls unhide.
**Unhide asset** (~line 1078): Execute unhide, show undo toast that calls hide.
**Clear tray**: Capture tray IDs, clear, show undo toast that re-adds.

**Delete collection** (~line 1406): Keep `confirm()` — genuinely destructive, no API undo path.

### 3d. Annotation delete with undo (A-7)
In `renderAnnotations()` and marker delete handlers: execute delete, then show undo toast. On undo, POST to create new annotation with same x/y/text data.

### 3e. Color contrast fix (A-2)
In styles.css:
- `.filterItem.zeroOption`: Replace `opacity: 0.55` with `color: rgba(255, 255, 255, 0.52)` (maintains ~5:1 contrast ratio)
- `.badge`: Increase background opacity from `0.65` → `0.82`

---

## Phase 4: Modern UX Patterns
**Findings: UI-2, UI-6, UI-7, VH-5, UI-9**

### 4a. Loading skeletons (UI-2)
New function in app.js:
```javascript
function renderSkeletons(count = 12) {
  const wrap = $("#grid");
  wrap.innerHTML = "";
  for (let i = 0; i < count; i++) {
    const el = document.createElement("div");
    el.className = "skeleton-card";
    el.innerHTML = '<div class="skeleton-thumb"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div>';
    wrap.appendChild(el);
  }
}
```

Call `renderSkeletons()` at start of `loadAssets()` for fresh loads (not appends).

CSS:
```css
.skeleton-card { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: rgba(15,23,34,0.55); }
.skeleton-thumb { width: 100%; aspect-ratio: 4/3; background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; }
.skeleton-line { height: 12px; border-radius: 6px; background: rgba(255,255,255,0.06); margin: 8px 10px; }
.skeleton-line.short { width: 60%; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
```

### 4b. Remove hardcoded name (UI-6)
In `displayTitle()` (app.js ~line 550), replace:
```javascript
.replace(/^leslie brannigan saved a (?:link|product|video)(?: from)?\s+/i, "")
.replace(/^leslie brannigan saved a (?:link|product|video)\.?$/i, "")
```
With:
```javascript
.replace(/^.{1,40}\s+saved a (?:link|product|video)(?: from)?\s+/i, "")
.replace(/^.{1,40}\s+saved a (?:link|product|video)\.?$/i, "")
```

### 4c. Empty state design (UI-7)
In `renderGrid()` (~line 678), replace simple muted text with designed empty state:
```javascript
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
```

CSS:
```css
.empty-state { grid-column: 1 / -1; text-align: center; padding: 48px 16px; }
.empty-state-message { font-size: var(--fs-base); color: var(--muted); margin-bottom: 12px; }
```

### 4d. Simplify card footer (VH-5)
In `renderGrid()`, change card footer from:
```
AI: ${model} • ${labelCount} tags
```
To:
```javascript
const tagStatus = labelCount > 0 ? `${labelCount} tags` : "Not tagged";
```
Keep model info visible only in expanded `.expandedInfo` section.

Add CSS:
```css
.tag-status { font-size: var(--fs-xs); }
.tag-status.tagged { color: var(--accent-2); }
.tag-status.untagged { color: var(--muted); }
```

### 4e. Admin link on mobile (UI-9)
In styles.css, remove `.adminNav { display: none; }` from the 700px breakpoint. Replace with:
```css
.adminNav { font-size: 11px; padding: 5px 8px; }
```

---

## Phase 5: Layout Polish
**Findings: SP-4, SP-5**

### 5a. Mobile grid (SP-4)
At ≤700px, change `.grid` from `repeat(2, minmax(0, 1fr))` to:
```css
.grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
```

### 5b. Modal image stage (SP-5)
Replace `.imageStage` from:
```css
.imageStage { ... aspect-ratio: 4/3; }
.imageStage img { width: 100%; height: 100%; object-fit: contain; }
```
To:
```css
.imageStage {
  position: relative; border: 1px solid var(--border); border-radius: 12px;
  overflow: hidden; background: rgba(15,23,34,0.6);
  min-height: 200px; max-height: 70vh;
  display: flex; align-items: center; justify-content: center;
}
.imageStage img { max-width: 100%; max-height: 70vh; object-fit: contain; display: block; }
```

**Risk:** Annotation marker positioning uses normalized coordinates. The existing `modalImageGeometry()` computes from actual rendered dimensions, so it should adapt. Manual QA required after this change — test adding/viewing annotations on both landscape and portrait images.

---

## Verification

After each phase:
1. `PYTHONPATH=src python3 -m inspirations serve --reload` — start dev server
2. Open http://127.0.0.1:8000 — verify visually
3. `PYTHONPATH=src python3 -m unittest discover -s tests -v` — all tests pass
4. `ruff check src tests` — lint clean

### Phase-specific checks:
- **Phase 1:** Larger headings, consistent spacing, no inline styles, admin centered
- **Phase 2:** Rapid checkbox clicks are instant, toolbar shows/hides contextually
- **Phase 3:** Import success shows toast, remove-from-collection has undo, no alert() dialogs
- **Phase 4:** Loading shows shimmer skeletons, empty state has clear-filters button, card footer simplified
- **Phase 5:** iPhone SE shows 1-column grid, modal portrait images display properly
