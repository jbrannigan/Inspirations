# Round 1 Bug Fixes — Implementation Brief

## Before You Start

Read these files first:
- `CLAUDE.md` — project conventions, common commands
- `DECISIONS.md` — architectural constraints
- `app/index.html` — current modal HTML structure (lines 221-254)
- `app/app.js` — `openModal()` at ~line 1121, `renderGrid()` at ~line 740, `setStats()` at ~line 585, Review button handler at ~line 1528, `renderGroups()` board click handler at ~line 670

Run verification after each fix:
```bash
PYTHONPATH=src python3 -m inspirations serve --reload
# Open http://127.0.0.1:8000
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
```

---

## Fix 1: Modal Close Button Should Be a Big × (not a peer to action buttons)

**Problem:** The modal header has four buttons in a row: `[Hide] [View Source] [Print] [Close]`. Close looks identical to the content actions. It should be a standard × in the top-right corner.

**In `app/index.html`:**

The current modal header structure (around line 222) has all four buttons inside `.modalActions`:
```html
<div class="row modalActions">
  <button id="hideAssetBtn" type="button">Hide</button>
  <button id="viewSourceBtn" type="button">View Source</button>
  <button id="printAssetBtn" type="button">Print</button>
  <button id="closeModal">Close</button>
</div>
```

Change it to:
- Remove `closeModal` from the `.modalActions` row
- Add it as a standalone button directly inside `.modalContent`, outside the header:
```html
<button id="closeModal" class="modalCloseX" type="button" aria-label="Close">&times;</button>
```

**In `app/styles.css`:**

- Add `.modalContent { position: relative; }` (if not already)
- Add `.modalCloseX` styles:
  - `position: absolute; top: 12px; right: 12px;`
  - `width: 36px; height: 36px;` (large click target)
  - `font-size: 22px; line-height: 36px; text-align: center;`
  - `background: transparent; border: none; cursor: pointer;`
  - `color: var(--muted); border-radius: 8px;`
  - Hover: `background: var(--surface-subtle); color: var(--text);`
  - `z-index: 10;` to stay above content

**In `app/app.js`:** No changes needed — the `#closeModal` onclick handler at ~line 1461 will still find the element by ID.

---

## Fix 2: "Open Original" / "View Source" Broken for Scans

**Problem:** Two links fail for scan-source assets:

1. The "Open original" link in the notes panel (`#sourceLink`) sets its `href` to the raw `source_ref` like `scan://abc123#p1` — that's not a clickable URL.
2. The "View Source" button opens `/media/{id}?kind=pdf` which may trigger a download instead of displaying inline.

**In `app/app.js` — `openModal()` source link section (~line 1156-1165):**

Current code:
```javascript
const link = $("#sourceLink");
if (asset.source_ref) {
  link.href = asset.source_ref;
  link.textContent = "Open original";
} else {
  link.href = "#";
  link.textContent = "No source";
}
```

Change to handle scans specially:
- If `asset.source === "scan"`: set `href` to `/media/${asset.id}?kind=pdf`. Parse the page number from `source_ref` — if it matches `scan://...#p{N}`, append `#page=${N}` to the URL so the browser's PDF viewer jumps to that page. Set text to "Open PDF".
- If `source_ref` is an HTTP URL (use existing `isHttpUrl()` helper): keep existing behavior (`href = source_ref`, text "Open original")
- If `asset.stored_path` and source is not scan: set href to `/media/${asset.id}?kind=original`, text "Open original"
- Otherwise: `href = "#"`, text "No source"

**In `app/app.js` — `openModal()` View Source button section (~line 1167-1184):**

Currently for scans: `targetUrl = /media/${asset.id}?kind=pdf`

Add page fragment: parse page number from `source_ref` using regex. The `source_ref` format for multipage scans is `scan://{sha}#p{N}`. Extract N and append `#page=${N}` to the URL. This tells the browser PDF viewer to open to that page.

Change button text for scans: instead of "View Source", use "View PDF".

**In `src/inspirations/server.py` — `_serve_media()` (~line 792-828):**

When serving a PDF (`kind == "pdf"`), add `Content-Disposition: inline` header so the browser displays it instead of downloading. The current code just sends the bytes with a Content-Type from `_guess_mime()`. Verify that `_guess_mime()` returns `application/pdf` for `.pdf` files — check the function at ~line 831. If `.pdf` isn't handled, add it.

After `self.send_header("Content-Type", ...)` add:
```python
if path.lower().endswith(".pdf"):
    self.send_header("Content-Disposition", "inline")
```

---

## Fix 3: Multipage Scan Page Navigation

**Problem:** Multipage PDF scans are split into individual page assets. The grid shows "Pages: 3" in metadata, but there's no way to flip through pages. Users need to browse all pages of the same document.

**Background — how multipage scans work in the data model:**

- Each page of a PDF becomes a separate asset row in the database
- The backend's `_collapse_scan_rows()` in `src/inspirations/store.py` groups pages by document and adds these fields to the first page's row:
  - `scan_group_member_ids`: array of all page asset IDs (ordered by page number)
  - `scan_doc_pages`: total number of pages
  - `scan_group_id`: unique group identifier
- Only the first page of each document appears in the grid (collapsed)
- Each page asset has its own `id`, `thumb_path`, and `source_ref` (`scan://sha#p{N}`)

**In `app/app.js` — `renderGrid()` (~line 779):**

When rendering a card for a multipage scan (`a.source === "scan" && Number(a.scan_doc_pages || 0) > 1`):

- Add page navigation controls overlaid on the thumbnail area:
  ```html
  <div class="scanPageNav">
    <button class="scanPagePrev" aria-label="Previous page">‹</button>
    <span class="scanPageIndicator">1 / 3</span>
    <button class="scanPageNext" aria-label="Next page">›</button>
  </div>
  ```
- Store `data-page-index="0"` and the member IDs array on the card element (e.g., as `data-scan-members` JSON attribute)
- Prev/Next click handlers:
  - Read current page index from the card's data attribute
  - Increment/decrement (clamp to 0..N-1)
  - Get the asset ID for that page from `scan_group_member_ids[newIndex]`
  - Swap the card's `<img>` src to `/media/${memberAssetId}?kind=thumb`
  - Update the page indicator text
  - Update `data-page-index`
  - Stop event propagation so clicking arrows doesn't toggle card expansion
- When the card is clicked to open the modal, use the currently-displayed page's asset ID (not always the first page)

**In `app/app.js` — `openModal()` (~line 1121):**

When opening a multipage scan asset:

- Add page navigation arrows to the image stage area:
  - Left arrow `‹` and right arrow `›` overlaid on the image edges
  - Page indicator `"Page 1 of 3"` shown below or overlaid on the image
- Store the member IDs array and current page index in state (e.g., `state.modalScanPages` and `state.modalScanPageIndex`)
- Prev/Next handlers:
  - Load the sibling asset: fetch `/api/assets/{siblingId}` if not in `state.assets`, or find it in the loaded assets
  - Update the modal: swap image src (with progressive loading — thumb then original), update title via `displayTitle()`, reload annotations, update source link, update View Source/PDF button URL
  - Essentially call the relevant parts of `openModal()` again for the sibling asset
- When navigating pages in the modal, also update which page the grid card shows (so they stay in sync when the modal closes)

**In `app/styles.css`:**

- `.scanPageNav`: position absolute, bottom of thumbnail area, centered, semi-transparent warm background, flex row, gap
- `.scanPagePrev`, `.scanPageNext`: small round buttons (28×28px), warm semi-transparent background, hover darkens
- `.scanPageIndicator`: small text (--fs-xs or --fs-sm), warm muted color
- Modal page nav arrows: larger, positioned at left/right edges of `.imageStage`, vertically centered, semi-transparent, hover to opaque

---

## Fix 4: Review/Curate Workflow Should Work for Boards Too

**Problem:** The unified Groups sidebar treats boards and collections as co-equal, but the Review button only enables for collections (`reviewBtn.disabled = !viewCollection || trayMode`). Clicking a board in the sidebar never sets `viewCollectionId`, so Review stays disabled.

**In `app/app.js`:**

1. Add `state.viewBoardName = ""` to the state object (near line 1, alongside other state properties)

2. Board click handler in `renderGroups()` (~line 675): Currently boards toggle `state.boards` Set. Change the behavior:
   - Single-clicking a board sets `state.viewBoardName = it.board` and clears `state.viewCollectionId`
   - Clear `state.boards` first, then add just the clicked board (single-select, like collections)
   - Clicking the same board again clears it (deselects: `state.viewBoardName = ""`, remove from `state.boards`)
   - Call `setStats()` to update button states

3. Collection click handler (`selectCollection()` at line 576): Clear `state.viewBoardName = ""` when selecting a collection

4. `setStats()` (~line 585): Update review button logic:
   ```javascript
   const canReview = (viewCollection || state.viewBoardName) && !trayMode;
   reviewBtn.disabled = !canReview;
   if (viewCollection) {
     reviewBtn.textContent = `Review "${viewCollection.name}"`;
   } else if (state.viewBoardName) {
     reviewBtn.textContent = `Review "${state.viewBoardName}"`;
   } else {
     reviewBtn.textContent = "Review";
   }
   reviewBtn.classList.toggle("primaryAction", canReview);
   ```

5. Review button click handler (~line 1528): Currently only handles `viewCollection`. Add board path:
   ```javascript
   if (state.viewBoardName) {
     const dataUrl = `/api/cluster/review?board=${encodeURIComponent(state.viewBoardName)}&include_neighbors=0`;
     const url = `/tools/cluster_explorer.html?data=${encodeURIComponent(dataUrl)}`;
     window.open(url, "_blank");
     return;
   }
   ```

**In `src/inspirations/server.py` — `/api/cluster/review` endpoint (~line 218):**

Currently requires `collection_id`. Add `board` as an alternative parameter:
- Read `board = q.get("board", [""])[0].strip()`
- If `board` is provided (and `collection_id` is not), pass it through to `_export_cluster_review_payload()`
- If neither is provided, return 400 error: "collection_id or board required"

**In `src/inspirations/server.py` — `_export_cluster_review_payload()` (~line 744):**

- Accept optional `board` parameter
- When building the subprocess command for `tools/export_clusters.py`, add `--board` argument if provided

**In `tools/export_clusters.py`:**

Read this file first to understand its argument parsing and how it queries assets for a collection. Then:
- Add `--board` argument to argparse
- When `--board` is provided: query assets filtered by `board = ?` instead of collection membership
- Feed those assets into the same clustering/similarity pipeline
- Set `meta.collection_name` to the board name (or add `meta.board_name`) so the explorer shows the right title

---

## Implementation Order

Do them in this order (smallest to largest):
1. Fix 1: Modal close × (HTML + CSS only)
2. Fix 2: Scan source links (small app.js + server.py change)
3. Fix 3: Multipage scan navigation (medium, frontend-only)
4. Fix 4: Board review (largest, backend + tools)

Run verification after each fix. Commit after each one.

## Files Summary

**Modify:**
- `app/index.html` — move close button out of actions row
- `app/styles.css` — modalCloseX, scanPageNav, modal page arrows
- `app/app.js` — openModal source links, scan page nav, board review, state.viewBoardName
- `src/inspirations/server.py` — PDF Content-Disposition header, board param on cluster review
- `tools/export_clusters.py` — add --board argument
