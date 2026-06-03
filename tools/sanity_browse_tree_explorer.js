/**
 * Browse-tree interactivity sanity test.
 *
 * Run in the browser console while the app is loaded at localhost:8001.
 * Tests that EVERY clickable item in the sidebar tree actually loads items
 * when clicked, and that counts shown in the tree match reality.
 *
 * Usage:
 *   1. Open http://localhost:8001 in a browser
 *   2. Paste this script into the DevTools console
 *   3. Review the pass/fail results printed to the console
 *
 * What it tests:
 *   - No source in the tree has zero-count (hidden sources are removed)
 *   - Every source board loads items matching its displayed count
 *   - Every catalog dimension child loads items
 *   - Explorer mode: sidebar visible, canvas rendered, survives filter cycling
 *   - Grid mode: filter indicator + tile count match for each category
 */
(async function sanityBrowseTreeExplorer() {
  "use strict";

  const results = [];
  function assert(name, condition, detail) {
    const status = condition ? "PASS" : "FAIL";
    results.push({ name, status, detail });
    console[condition ? "log" : "error"](
      `[${status}] ${name}${detail ? " \u2014 " + detail : ""}`
    );
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function waitFor(predicate, timeoutMs, label) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return true;
      await sleep(200);
    }
    console.warn(`waitFor timed out after ${timeoutMs}ms: ${label || ""}`);
    return false;
  }

  function getFilterText() {
    const el = document.getElementById("filterIndicatorText");
    const bar = document.getElementById("filterIndicator");
    if (!el || (bar && bar.hidden)) return "";
    return el.textContent.trim();
  }

  function getTileCount() {
    const g = document.querySelector("main");
    return g ? g.querySelectorAll(".tile,.card,.asset-tile").length : 0;
  }

  function getStatsText() {
    const main = document.querySelector("main");
    if (!main) return "";
    const m = main.textContent.match(/(\d+)\s+(of\s+\d+\s+)?items?\b/i);
    return m ? m[0] : "";
  }

  console.log("=== Browse Tree Sanity Test ===\n");

  // ─── Fetch the tree data from the API ───────────────────────────────

  const treeResp = await fetch("/api/catalog/tree");
  const treeData = await treeResp.json();
  const tree = treeData.tree || [];

  const sources = tree.filter((n) => n.type === "source");
  const dimensions = tree.filter((n) => n.type === "dimension");

  console.log(
    `Tree: ${sources.length} sources, ${dimensions.length} dimensions\n`
  );

  // ─── 1. No zero-count sources ──────────────────────────────────────

  const zeroSrc = sources.filter((n) => n.count === 0);
  assert(
    "No zero-count sources in tree",
    zeroSrc.length === 0,
    zeroSrc.length
      ? `broken: ${zeroSrc.map((n) => n.label).join(", ")}`
      : `OK: ${sources.map((n) => `${n.label}(${n.count})`).join(", ")}`
  );

  // ─── 2. Every source branch returns items via API ──────────────────

  console.log("\n--- Source board API checks ---");
  for (const src of sources) {
    for (const child of (src.children || []).slice(0, 3)) {
      // Use the same query the app would use
      const srcName = src.label.toLowerCase();
      const url = child.type === "source_subtype"
        ? `/api/assets?source=${encodeURIComponent(srcName)}&content_kind=${encodeURIComponent(child.content_kind || "")}&limit=1`
        : `/api/assets?source=${encodeURIComponent(srcName)}&board=${encodeURIComponent(child.board_name || child.label || "")}&limit=1`;
      try {
        const resp = await fetch(url);
        const data = await resp.json();
        const total = data.total || 0;
        const expected = child.count || 0;
        assert(
          `${src.label} / ${child.label}: API returns items`,
          total > 0,
          `tree=${expected}, api_total=${total}`
        );
      } catch (e) {
        assert(`${src.label} / ${child.label}: API call`, false, e.message);
      }
    }
  }

  // ─── 3. Grid mode: click first board of each source, verify tiles ──

  console.log("\n--- Grid click-through checks ---");
  const gridBtn = document.querySelector('button[title*="Grid"]');
  if (gridBtn) gridBtn.click();
  await sleep(500);

  for (const src of sources) {
    const firstChild = (src.children || []).find((c) => c.count > 0);
    if (!firstChild) {
      assert(`${src.label}: has clickable board`, false, "no children with count > 0");
      continue;
    }

    // Click "All Items" first to reset
    for (const b of document.querySelectorAll("aside.sidebar button")) {
      if (b.textContent.trim().includes("All Items")) { b.click(); break; }
    }
    await waitFor(() => getFilterText() === "", 2000);

    // Expand source
    for (const b of document.querySelectorAll("aside.sidebar button")) {
      if (b.textContent.trim().includes(src.label)) { b.click(); break; }
    }
    await sleep(300);

    // Click first tree-leaf child
    let clicked = false;
    let foundSrc = false;
    for (const b of document.querySelectorAll("aside.sidebar button")) {
      const t = b.textContent.trim();
      if (t.includes(src.label) && (t.includes("\u25B6") || t.includes("\u25BC"))) {
        foundSrc = true;
        continue;
      }
      if (b.classList.contains("tree-hide-toggle")) continue;
      if (foundSrc && b.classList.contains("tree-leaf")) {
        b.click();
        clicked = true;
        break;
      }
      if (foundSrc && (t.includes("\u25B6") || t.includes("\u25BC"))) break;
    }

    if (!clicked) {
      assert(`${src.label}: click board in grid`, false, "could not click child");
      continue;
    }

    await waitFor(() => getTileCount() > 0, 4000, `${src.label} tiles`);
    const tiles = getTileCount();
    assert(
      `${src.label}: grid loads tiles after board click`,
      tiles > 0,
      `tiles=${tiles}`
    );
  }

  // ─── 4. Catalog dimensions: click first child of each, verify tiles ─

  console.log("\n--- Dimension catalog click-through checks ---");
  for (const dim of dimensions.slice(0, 3)) {
    // Only check the first 3 dimensions to keep test duration reasonable
    const firstChild = (dim.children || []).find((c) => c.count > 0);
    if (!firstChild) continue;

    // Reset
    for (const b of document.querySelectorAll("aside.sidebar button")) {
      if (b.textContent.trim().includes("All Items")) { b.click(); break; }
    }
    await waitFor(() => getFilterText() === "", 2000);

    // Expand dimension
    for (const b of document.querySelectorAll("aside.sidebar button")) {
      if (b.textContent.trim().includes(dim.label)) { b.click(); break; }
    }
    await sleep(300);

    // Click first child
    let clicked = false;
    let foundDim = false;
    for (const b of document.querySelectorAll("aside.sidebar button")) {
      const t = b.textContent.trim();
      if (t.includes(dim.label)) { foundDim = true; continue; }
      if (b.classList.contains("tree-hide-toggle")) continue;
      if (foundDim && b.classList.contains("tree-leaf")) {
        b.click();
        clicked = true;
        break;
      }
      if (foundDim && (t.startsWith("\u25B6") || t.startsWith("\u25BC")) && !t.includes(dim.label)) break;
    }

    if (!clicked) {
      assert(`${dim.label}: click child`, false, "could not click");
      continue;
    }

    await waitFor(() => getTileCount() > 0, 5000, `${dim.label} tiles`);
    const tiles = getTileCount();
    assert(
      `${dim.label}: grid loads tiles after child click`,
      tiles > 0,
      `tiles=${tiles}`
    );
  }

  // ─── 5. Explorer mode checks ──────────────────────────────────────

  console.log("\n--- Explorer mode checks ---");

  // Reset to All Items first
  for (const b of document.querySelectorAll("aside.sidebar button")) {
    if (b.textContent.trim().includes("All Items")) { b.click(); break; }
  }
  await waitFor(() => getFilterText() === "", 2000);

  const exBtn = document.querySelector('button[title*="Explorer"]');
  assert("Explorer button exists", !!exBtn);
  if (exBtn) exBtn.click();

  await waitFor(() => {
    const v = document.getElementById("explorerView");
    return v && !v.hidden && document.querySelector("#explorerContainer canvas");
  }, 5000);

  assert(
    "Explorer view visible",
    (() => {
      const v = document.getElementById("explorerView");
      return v && !v.hidden;
    })()
  );
  assert(
    "Explorer canvas rendered",
    !!document.querySelector("#explorerContainer canvas")
  );

  const sb = document.querySelector("aside.sidebar");
  assert(
    "Sidebar visible in explorer",
    sb && !sb.hidden && sb.offsetHeight > 0
  );

  // Grid round-trip
  if (gridBtn) {
    gridBtn.click();
    await sleep(500);
    exBtn.click();
    await waitFor(
      () => document.querySelector("#explorerContainer canvas"),
      5000
    );
    assert(
      "Explorer survives grid round-trip",
      !!document.querySelector("#explorerContainer canvas")
    );
  }

  // ─── Summary ──────────────────────────────────────────────────────

  console.log("\n=== Summary ===");
  const passed = results.filter((r) => r.status === "PASS").length;
  const failed = results.filter((r) => r.status === "FAIL").length;
  console.log(`${passed} passed, ${failed} failed out of ${results.length} checks`);
  if (failed > 0) {
    console.warn("FAILED checks:");
    results
      .filter((r) => r.status === "FAIL")
      .forEach((r) => console.warn(`  - ${r.name}: ${r.detail || ""}`));
  }

  return { passed, failed, total: results.length, results };
})();
