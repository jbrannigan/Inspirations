#!/usr/bin/env python3
"""Scrape Facebook Saved Items via Chrome AppleScript automation.

Navigates each Facebook collection, scrolls to load all items,
captures metadata and images, writes batch JSON files.
"""

import base64
import json
import os
import re
import subprocess
import time

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "scrape")

# All collections from DB + new ones from HTML export (Feb 21, 2026)
COLLECTIONS = [
    "2b/2b", "ADA", "Fireplace", "Gutters", "Home & Garden",
    "Inspection", "Insurance", "Mortgage", "Selling home", "Sheet rock",
    "Trust", "Water heater", "aging in place", "appliances", "architect",
    "bathroom", "bedroom", "brick", "building", "cabinet", "cabinets",
    "carpet", "caulk", "ceiling fan", "clothes", "concrete",
    "construction draws", "contract", "cooking", "cottage of the year",
    "door", "drain pan", "drywall", "electric", "estimates", "exercise",
    "floor plans", "flooring", "foundation", "freeze", "funny",
    "furniture", "garage", "garden", "generator", "health",
    "home insurance", "hvac", "insulation", "insurance",
    "interior design", "interior design/architect", "internet", "iphone",
    "kitchen", "kitchen 2", "land", "land clearing", "laundry",
    "legal", "lighting", "living room", "lot", "makeup", "misc.",
    "mold", "molding", "mudroom", "paint", "pest control", "plumbing",
    "pocket door", "porch", "propane", "punch list", "quartzite",
    "re: builders", "recipe", "roofing", "security", "septic",
    "skincare", "soil test", "solar", "stairs", "stone", "style board",
    "survey", "tile", "water", "water heater", "water softener",
    "well", "windows",
]

# Map of collection name -> Facebook list_id (populated dynamically)
COLLECTION_IDS = {}


def run_applescript(script: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["osascript"], input=script,
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()[:300]}"
    return result.stdout.strip()


def chrome_js(js: str, timeout: int = 30) -> str:
    escaped = js.replace("\\", "\\\\").replace('"', '\\"')
    applescript = (
        'tell application "Google Chrome"\n'
        f'execute active tab of front window javascript "{escaped}"\n'
        'end tell\n'
    )
    return run_applescript(applescript, timeout)


def chrome_navigate(url: str, wait: float = 4.0):
    applescript = f'tell application "Google Chrome" to set URL of active tab of front window to "{url}"'
    run_applescript(applescript)
    time.sleep(wait)


def discover_collections():
    """Navigate to Facebook Saved page and find collection list_ids."""
    print("Discovering collections on Facebook Saved page...")
    chrome_navigate("https://www.facebook.com/saved/", wait=5.0)

    # Scroll the sidebar to load all collections
    for i in range(10):
        chrome_js(r"""
        (function() {
          var sidebar = document.querySelector('[role="navigation"]');
          if (sidebar) sidebar.scrollTop = sidebar.scrollHeight;
          else window.scrollBy(0, 500);
        })();
        """)
        time.sleep(1)

    # Extract collection links with list_ids
    raw = chrome_js(r"""
    (function() {
      var links = document.querySelectorAll('a[href*="list_id="]');
      var colls = {};
      for (var i = 0; i < links.length; i++) {
        var href = links[i].href;
        var m = href.match(/list_id=(\d+)/);
        if (!m) continue;
        var text = links[i].textContent.trim().replace(/Only me/g, '').trim();
        if (text && text.length < 60 && !colls[m[1]]) {
          colls[m[1]] = text;
        }
      }
      return JSON.stringify(colls);
    })();
    """)

    try:
        id_map = json.loads(raw)
        for list_id, name in id_map.items():
            COLLECTION_IDS[name] = list_id
        print(f"  Found {len(COLLECTION_IDS)} collections with list_ids")
        for name, lid in sorted(COLLECTION_IDS.items()):
            print(f"    {name}: {lid}")
    except json.JSONDecodeError:
        print(f"  WARNING: Could not parse collection IDs")


def install_item_collector():
    """Install JS collector for Facebook saved items."""
    return chrome_js(r"""
    (function() {
      window.__FB_ITEMS__ = {};
      window.__FB_COUNT__ = 0;

      window.__COLLECT_FB_ITEMS__ = function() {
        // Find saved item cards in the main content
        var main = document.querySelector('[role="main"]');
        if (!main) return window.__FB_COUNT__;

        // Each saved item has a post link and possibly an image
        var links = main.querySelectorAll('a');
        for (var i = 0; i < links.length; i++) {
          var href = links[i].href || '';
          // Match post URLs: /reel/ID, /watch/?v=ID, /groups/.../permalink/ID, /photo/
          var postMatch = href.match(/\/(reel|watch|photo|permalink|posts)\//);
          if (!postMatch) continue;

          // Deduplicate by URL
          var key = href.replace(/\?.*$/, '').replace(/\/$/, '');
          if (window.__FB_ITEMS__[key]) continue;

          var item = {post_url: href};

          // Get text content near this link
          var parent = links[i].closest('[class]');
          if (parent) {
            var text = parent.textContent.trim().substring(0, 500);
            // Extract creator name from "Saved from X's post" pattern
            var creatorMatch = text.match(/Saved from (.+?)(?:'s post|'s reel)/);
            if (creatorMatch) item.creator_name = creatorMatch[1];

            // Extract collection label from "Saved to X" pattern
            var collMatch = text.match(/Saved to (\w[\w\s&/]*)/);
            if (collMatch) item.collection_name = collMatch[1].trim();

            // Get any descriptive text
            item.text_snippet = text.substring(0, 200);
          }

          // Find associated image
          var imgEl = null;
          var card = links[i].closest('div');
          for (var j = 0; j < 5 && card; j++) {
            imgEl = card.querySelector('img[src*="fbcdn"]');
            if (imgEl) break;
            card = card.parentElement;
          }
          if (imgEl) {
            item.thumbnail_url = imgEl.src;
            item.alt_text = imgEl.alt || '';
          }

          // Content type from URL
          if (href.indexOf('/reel/') > -1) item.content_type = 'reel';
          else if (href.indexOf('/watch/') > -1) item.content_type = 'video';
          else if (href.indexOf('/photo') > -1) item.content_type = 'photo';
          else item.content_type = 'post';

          window.__FB_ITEMS__[key] = item;
          window.__FB_COUNT__++;
        }
        return window.__FB_COUNT__;
      };

      window.__COLLECT_FB_ITEMS__();
      return 'Collector installed, initial: ' + window.__FB_COUNT__;
    })();
    """)


def collect_and_scroll():
    """Collect current items and scroll down."""
    result = chrome_js(r"""
    (function() {
      window.__COLLECT_FB_ITEMS__();
      window.scrollBy(0, 800);
      return String(window.__FB_COUNT__);
    })();
    """)
    try:
        return int(result)
    except (ValueError, TypeError):
        return -1


def get_collected_items() -> list:
    """Retrieve all collected items from JS global."""
    raw = chrome_js(r"""
    (function() {
      var items = [];
      var keys = Object.keys(window.__FB_ITEMS__ || {});
      for (var i = 0; i < keys.length; i++) {
        items.push(window.__FB_ITEMS__[keys[i]]);
      }
      return JSON.stringify(items);
    })();
    """, timeout=60)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"    WARN: full retrieval failed (len={len(raw)}), trying chunks")
        return get_items_chunked()


def get_items_chunked() -> list:
    count_str = chrome_js("String(window.__FB_COUNT__ || 0);")
    try:
        total = int(count_str)
    except (ValueError, TypeError):
        return []

    all_items = []
    chunk = 50
    for offset in range(0, total, chunk):
        js = f"""
        (function() {{
          var items = [];
          var keys = Object.keys(window.__FB_ITEMS__ || {{}});
          for (var i = {offset}; i < Math.min({offset + chunk}, keys.length); i++) {{
            items.push(window.__FB_ITEMS__[keys[i]]);
          }}
          return JSON.stringify(items);
        }})();
        """
        raw = chrome_js(js, timeout=30)
        try:
            all_items.extend(json.loads(raw))
        except json.JSONDecodeError:
            print(f"    WARN: chunk {offset} failed")
    return all_items


def capture_image_for_item(post_url: str) -> dict | None:
    """Navigate to a post and capture the high-res image as base64.
    Returns {base64: str, width: int, height: int} or None."""
    chrome_navigate(post_url, wait=4.0)

    # Wait for image to load, then capture the main content image
    result = chrome_js(r"""
    (function() {
      // Find the main image on the page
      var imgs = document.querySelectorAll('img[src*="fbcdn"]');
      var best = null;
      var bestSize = 0;
      for (var i = 0; i < imgs.length; i++) {
        var w = imgs[i].naturalWidth || 0;
        var h = imgs[i].naturalHeight || 0;
        var size = w * h;
        if (size > bestSize && w > 100) {
          bestSize = size;
          best = imgs[i];
        }
      }
      if (!best) return JSON.stringify({error: 'no image found'});

      // Draw to canvas and get base64
      var canvas = document.createElement('canvas');
      canvas.width = best.naturalWidth;
      canvas.height = best.naturalHeight;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(best, 0, 0);
      var dataUrl = canvas.toDataURL('image/jpeg', 0.92);
      return JSON.stringify({
        base64: dataUrl,
        width: best.naturalWidth,
        height: best.naturalHeight
      });
    })();
    """, timeout=15)

    try:
        data = json.loads(result)
        if data.get("error"):
            return None
        return data
    except json.JSONDecodeError:
        return None


def scrape_collection_view(collection_name: str, list_id: str = None) -> list:
    """Scrape items from a specific collection or all saved items."""
    if list_id:
        url = f"https://www.facebook.com/saved/?list_id={list_id}"
    else:
        url = "https://www.facebook.com/saved/"

    print(f"  -> {url}")
    chrome_navigate(url, wait=5.0)

    result = install_item_collector()
    print(f"  {result}")

    # Scroll to load all items
    prev_count = 0
    stale = 0
    for i in range(500):
        count = collect_and_scroll()
        if i % 10 == 0:
            print(f"    scroll {i}: {count} items")
        if count == prev_count:
            stale += 1
            if stale >= 6:
                break
        else:
            stale = 0
        prev_count = count
        time.sleep(0.8)

    print(f"  total: {prev_count}")

    items = get_collected_items()

    # Tag with collection name
    for item in items:
        if not item.get("collection_name"):
            item["collection_name"] = collection_name

    print(f"  got {len(items)} items")
    return items


def save_batch(items: list, batch_num: int):
    """Save a batch of items to a JSON file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"facebook_scrape_{batch_num:03d}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(items, f, indent=2)
    print(f"  Saved {len(items)} items to {filename}")


def main():
    total_start = time.time()
    all_items = []

    # Step 1: Discover collection list_ids from the Facebook page
    discover_collections()

    # Step 2: Scrape "All Saved Items" (the main view)
    print(f"\n{'='*60}")
    print("Scraping All Saved Items...")
    items = scrape_collection_view("", list_id=None)

    # Step 3: Scrape individual collections for items that might not appear in All view
    for coll_name, list_id in sorted(COLLECTION_IDS.items()):
        print(f"\n[Collection] {coll_name}")
        coll_items = scrape_collection_view(coll_name, list_id=list_id)

        # Only add items not already captured
        existing_urls = {item.get("post_url", "").split("?")[0].rstrip("/")
                        for item in items}
        new_items = []
        for ci in coll_items:
            key = ci.get("post_url", "").split("?")[0].rstrip("/")
            if key not in existing_urls:
                new_items.append(ci)
                existing_urls.add(key)
            else:
                # Update collection_name for existing items
                for item in items:
                    item_key = item.get("post_url", "").split("?")[0].rstrip("/")
                    if item_key == key and not item.get("collection_name"):
                        item["collection_name"] = coll_name

        if new_items:
            print(f"  {len(new_items)} new items")
            items.extend(new_items)
        else:
            print(f"  all items already captured")

    all_items = items
    print(f"\n{'='*60}")
    print(f"Total unique items: {len(all_items)}")

    # Step 4: Save in batches of 100
    batch_size = 100
    for i in range(0, len(all_items), batch_size):
        batch = all_items[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        save_batch(batch, batch_num)

    total_elapsed = time.time() - total_start
    print(f"\nDone in {total_elapsed:.0f}s")
    print(f"Total items: {len(all_items)}")
    print(f"Batch files: {(len(all_items) + batch_size - 1) // batch_size}")

    # Collection stats
    coll_counts = {}
    for item in all_items:
        coll = item.get("collection_name", "(uncategorized)")
        coll_counts[coll] = coll_counts.get(coll, 0) + 1
    print(f"\nPer-collection:")
    for coll, count in sorted(coll_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {coll}: {count}")


if __name__ == "__main__":
    main()
