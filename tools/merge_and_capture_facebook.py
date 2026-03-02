#!/usr/bin/env python3
"""Merge Facebook metadata from all sources and capture high-res images.

Sources:
1. Live scrape (data/scrape/facebook_scrape_*.json) — post URLs, thumbnails
2. HTML export (/tmp/fb_export/) — dates, creator names
3. Old DB (data/inspirations.sqlite) — collection assignments, post text

Then visits each URL in Chrome to capture the main image as base64.
Writes final batch files to data/scrape/facebook_scrape_*.json.

Resumable: saves progress after each item.
"""

import glob
import json
import os
import re
import sqlite3
import subprocess
import time

PROJECT = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(PROJECT, "data", "scrape")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "facebook_capture_progress.json")
DB_PATH = os.path.join(PROJECT, "data", "inspirations.sqlite")


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


def chrome_navigate(url: str, wait: float = 3.0):
    applescript = f'tell application "Google Chrome" to set URL of active tab of front window to "{url}"'
    run_applescript(applescript)
    time.sleep(wait)


def normalize_url(url: str) -> str:
    """Normalize a Facebook URL for matching."""
    url = url.split("?")[0].rstrip("/")
    # Remove tracking params
    url = re.sub(r"[?&]ref=saved", "", url)
    return url


def load_live_scrape() -> list:
    """Load items from the live scrape batch files."""
    items = []
    for f in sorted(glob.glob(os.path.join(OUTPUT_DIR, "facebook_scrape_*.json"))):
        if "progress" in f:
            continue
        with open(f) as fh:
            items.extend(json.load(fh))
    return items


def load_html_export() -> dict:
    """Load parsed HTML export data. Returns {action+date -> item}."""
    path = "/tmp/fb_export/parsed_saved_items.json"
    if not os.path.exists(path):
        print("  HTML export not found, skipping")
        return {}
    with open(path) as f:
        data = json.load(f)
    # Build lookup by date since URLs don't match (redirect vs direct)
    items_by_date = {}
    for item in data.get("items", []):
        date = item.get("date", "")
        creator = item.get("creator_name", "")
        if date:
            key = f"{date}|{creator}"
            items_by_date[key] = item
    return items_by_date


def load_old_db() -> dict:
    """Load old DB Facebook items. Returns {normalized_url -> {board, title, image_url}}."""
    if not os.path.exists(DB_PATH):
        print("  DB not found, skipping")
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT source_ref, board, title, image_url, description FROM assets WHERE source='facebook'"
    ).fetchall()
    conn.close()

    db_map = {}
    for row in rows:
        url = normalize_url(row["source_ref"])
        db_map[url] = {
            "board": row["board"] or "",
            "title": row["title"] or "",
            "image_url": row["image_url"] or "",
            "description": row["description"] or "",
        }
    return db_map


def capture_image(post_url: str) -> dict | None:
    """Navigate to a post URL and capture the best image as base64."""
    chrome_navigate(post_url, wait=4.0)

    # Extra wait for dynamic content
    time.sleep(1)

    result = chrome_js(r"""
    (function() {
      var imgs = document.querySelectorAll('img');
      var best = null;
      var bestSize = 0;
      for (var i = 0; i < imgs.length; i++) {
        var src = imgs[i].src || '';
        if (src.indexOf('fbcdn') === -1 && src.indexOf('facebook') === -1) continue;
        // Skip tiny icons, profile pics, emoji
        if (src.indexOf('emoji') > -1) continue;
        var w = imgs[i].naturalWidth || 0;
        var h = imgs[i].naturalHeight || 0;
        var size = w * h;
        if (size > bestSize && w > 150 && h > 150) {
          bestSize = size;
          best = imgs[i];
        }
      }
      if (!best) return JSON.stringify({error: 'no image'});

      try {
        var canvas = document.createElement('canvas');
        canvas.width = best.naturalWidth;
        canvas.height = best.naturalHeight;
        var ctx = canvas.getContext('2d');
        ctx.drawImage(best, 0, 0);
        var dataUrl = canvas.toDataURL('image/jpeg', 0.90);
        return JSON.stringify({
          base64: dataUrl,
          width: best.naturalWidth,
          height: best.naturalHeight
        });
      } catch(e) {
        // CORS - try XHR blob fetch instead
        return JSON.stringify({error: 'canvas_blocked', src: best.src, w: best.naturalWidth, h: best.naturalHeight});
      }
    })();
    """, timeout=20)

    try:
        data = json.loads(result)
        if data.get("error") == "canvas_blocked":
            # Try XHR blob fetch
            return capture_image_xhr(data.get("src", ""), data.get("w", 0), data.get("h", 0))
        if data.get("error"):
            return None
        if data.get("base64"):
            return data
        return None
    except json.JSONDecodeError:
        return None


def capture_image_xhr(img_src: str, width: int, height: int) -> dict | None:
    """Fetch image via XHR and convert to base64 (bypasses canvas CORS)."""
    if not img_src:
        return None

    # Escape the URL for JS
    safe_src = img_src.replace("'", "\\'")
    result = chrome_js(f"""
    (function() {{
      return new Promise(function(resolve) {{
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '{safe_src}', true);
        xhr.responseType = 'blob';
        xhr.onload = function() {{
          if (xhr.status === 200) {{
            var reader = new FileReader();
            reader.onloadend = function() {{
              window.__XHR_RESULT__ = JSON.stringify({{
                base64: reader.result,
                width: {width},
                height: {height}
              }});
            }};
            reader.readAsDataURL(xhr.response);
          }} else {{
            window.__XHR_RESULT__ = JSON.stringify({{error: 'xhr_' + xhr.status}});
          }}
        }};
        xhr.onerror = function() {{
          window.__XHR_RESULT__ = JSON.stringify({{error: 'xhr_error'}});
        }};
        xhr.send();
      }});
      return 'xhr_started';
    }})();
    """, timeout=15)

    # Wait for XHR to complete
    time.sleep(3)
    raw = chrome_js("window.__XHR_RESULT__ || 'pending';", timeout=10)

    if raw == "pending":
        time.sleep(3)
        raw = chrome_js("window.__XHR_RESULT__ || 'pending';", timeout=10)

    try:
        data = json.loads(raw)
        if data.get("base64"):
            return data
        return None
    except json.JSONDecodeError:
        return None


def save_final_batches(items: list, batch_size: int = 100):
    """Save items to final batch files, overwriting old ones."""
    # Remove old batch files
    for f in glob.glob(os.path.join(OUTPUT_DIR, "facebook_scrape_*.json")):
        if "progress" not in f:
            os.remove(f)

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        filepath = os.path.join(OUTPUT_DIR, f"facebook_scrape_{batch_num:03d}.json")
        with open(filepath, "w") as f:
            json.dump(batch, f, indent=2)
    print(f"Saved {len(items)} items to {(len(items) + batch_size - 1) // batch_size} batch files")


def main():
    total_start = time.time()

    # Step 1: Load all data sources
    print("Loading data sources...")
    live_items = load_live_scrape()
    print(f"  Live scrape: {len(live_items)} items")

    html_by_date = load_html_export()
    print(f"  HTML export: {len(html_by_date)} date-keyed items")

    db_map = load_old_db()
    print(f"  Old DB: {len(db_map)} items with collections")

    # Step 2: Merge metadata
    print("\nMerging metadata...")
    merged = []
    seen_urls = set()

    for item in live_items:
        post_url = item.get("post_url", "")
        norm_url = normalize_url(post_url)

        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        merged_item = {
            "post_url": post_url,
            "content_type": item.get("content_type", "post"),
            "collection_name": item.get("collection_name", ""),
            "thumbnail_url": item.get("thumbnail_url", ""),
            "alt_text": item.get("alt_text", ""),
            "text_snippet": item.get("text_snippet", ""),
        }

        # Enrich from old DB
        db_entry = db_map.get(norm_url)
        if db_entry:
            if not merged_item["collection_name"] and db_entry["board"]:
                merged_item["collection_name"] = db_entry["board"]
            if db_entry["title"]:
                merged_item["post_text"] = db_entry["title"]
            if db_entry["description"]:
                merged_item["description"] = db_entry["description"]

        merged.append(merged_item)

    # Add DB items that weren't in the live scrape
    for url, db_entry in db_map.items():
        if url not in seen_urls:
            seen_urls.add(url)
            merged.append({
                "post_url": url,
                "collection_name": db_entry["board"],
                "post_text": db_entry["title"],
                "content_type": "post",
                "thumbnail_url": db_entry.get("image_url", ""),
            })

    print(f"  Merged: {len(merged)} unique items")
    coll_assigned = sum(1 for i in merged if i.get("collection_name"))
    print(f"  With collection: {coll_assigned}")

    # Step 3: Load progress (resume support)
    completed_urls = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
        completed_urls = set(progress.get("completed_urls", []))
        # Restore image data from progress
        img_data = {item["post_url"]: item for item in progress.get("items_with_images", [])}
        for item in merged:
            if item["post_url"] in img_data:
                saved = img_data[item["post_url"]]
                if saved.get("images"):
                    item["images"] = saved["images"]
                if saved.get("unavailable"):
                    item["unavailable"] = saved["unavailable"]
        print(f"  Resuming: {len(completed_urls)} items already captured")

    # Step 4: Capture images
    remaining = [i for i in merged if normalize_url(i["post_url"]) not in completed_urls
                 and i["post_url"].startswith("http")]
    print(f"\nCapturing images for {len(remaining)} items...")
    print(f"Estimated time: ~{len(remaining) * 8 // 60} minutes\n")

    captured = 0
    failed = 0
    for idx, item in enumerate(remaining):
        url = item["post_url"]
        num = idx + 1 + len(completed_urls)
        total = len(merged)

        if num % 25 == 0 or num <= 3:
            elapsed = time.time() - total_start
            rate = num / max(elapsed, 1) * 60
            print(f"[{num}/{total}] {rate:.0f} items/min | capturing: {url[:80]}")

        try:
            img = capture_image(url)
            if img and img.get("base64"):
                item["images"] = [{
                    "base64": img["base64"],
                    "width": img["width"],
                    "height": img["height"],
                }]
                captured += 1
            else:
                item["images"] = []
                # Check if post is unavailable
                page_text = chrome_js("document.body ? document.body.innerText.substring(0, 200) : '';")
                if "content isn't available" in page_text.lower() or "removed" in page_text.lower():
                    item["unavailable"] = True
                failed += 1
        except Exception as e:
            item["images"] = []
            failed += 1
            if num % 50 == 0:
                print(f"  Error at {num}: {e}")

        completed_urls.add(normalize_url(url))

        # Save progress every 25 items
        if num % 25 == 0:
            items_with_images = [i for i in merged if i.get("images") or i.get("unavailable")]
            progress_data = {
                "completed_urls": list(completed_urls),
                "items_with_images": items_with_images,
                "captured": captured,
                "failed": failed,
            }
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress_data, f)
            print(f"  Progress saved: {captured} captured, {failed} failed")

    # Step 5: Save final batch files
    print(f"\nSaving final batch files...")
    save_final_batches(merged)

    # Clean up progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"Done in {total_elapsed/60:.0f} minutes")
    print(f"Total items: {len(merged)}")
    print(f"Images captured: {captured}")
    print(f"Failed/no image: {failed}")
    print(f"Unavailable posts: {sum(1 for i in merged if i.get('unavailable'))}")

    # Collection stats
    coll_counts = {}
    for item in merged:
        coll = item.get("collection_name") or "(uncategorized)"
        coll_counts[coll] = coll_counts.get(coll, 0) + 1
    print(f"\nPer-collection:")
    for coll, count in sorted(coll_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {coll}: {count}")


if __name__ == "__main__":
    main()
