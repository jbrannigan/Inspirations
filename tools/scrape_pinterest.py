#!/usr/bin/env python3
"""Scrape Pinterest boards via Chrome AppleScript automation.

Pinterest virtualizes the DOM — only ~20 pins are rendered at once.
This script extracts pins incrementally during scrolling, accumulating
them in a JS global before collecting at the end.
"""

import json
import os
import re
import subprocess
import time

USERNAME = "lacbhou1"
BASE_URL = f"https://www.pinterest.com/{USERNAME}"
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "scrape", "pinterest_scrape.json")

BOARDS = [
    "bathroom", "bathroom-remodel", "bedroom", "brick", "cabinet",
    "cleaning", "door", "favorite-places-spaces", "flooring", "food",
    "for-the-home", "furniture", "garage", "garden", "gym",
    "house-plans", "house-plans-with-attached-guest-house", "ikea-hacks",
    "kitchen", "kitchen-remodel", "laundry-room", "leather-furniture",
    "lighting", "makeup", "misc", "my-style", "new-house-ideas",
    "paint", "products-i-love", "recipes-to-cook", "slab", "sofa",
    "stone-exterior-houses", "throw-pillow", "tile", "windows", "workout",
]


def run_applescript(script: str, timeout: int = 30) -> str:
    """Run AppleScript via stdin to avoid shell escaping issues."""
    result = subprocess.run(
        ["osascript"],
        input=script, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()[:300]}"
    return result.stdout.strip()


def chrome_js(js: str, timeout: int = 30) -> str:
    """Execute JavaScript in Chrome via AppleScript stdin."""
    escaped = js.replace("\\", "\\\\").replace('"', '\\"')
    applescript = (
        'tell application "Google Chrome"\n'
        f'execute active tab of front window javascript "{escaped}"\n'
        'end tell\n'
    )
    return run_applescript(applescript, timeout)


def chrome_navigate(url: str, wait: float = 4.0):
    """Navigate Chrome to a URL and wait."""
    applescript = f'tell application "Google Chrome" to set URL of active tab of front window to "{url}"'
    run_applescript(applescript)
    time.sleep(wait)


def install_collector():
    """Install a JS collector that accumulates pins as they appear in the DOM."""
    js = r"""
    (function() {
      window.__ALL_PINS__ = {};
      window.__PIN_COUNT__ = 0;

      window.__COLLECT_PINS__ = function() {
        var links = document.querySelectorAll('a');
        var newCount = 0;
        for (var i = 0; i < links.length; i++) {
          var href = links[i].href || '';
          var m = href.match(/\/pin\/(\d+)/);
          if (!m || window.__ALL_PINS__[m[1]]) continue;

          var img = links[i].querySelector('img');
          var src = '', alt = '';
          if (img) { src = img.src || ''; alt = img.alt || ''; }

          window.__ALL_PINS__[m[1]] = {
            pin_id: m[1],
            image_url: src,
            seo_alt_text: alt
          };
          window.__PIN_COUNT__++;
          newCount++;
        }
        return window.__PIN_COUNT__;
      };

      window.__COLLECT_PINS__();
      return 'Collector installed, initial: ' + window.__PIN_COUNT__;
    })();
    """
    return chrome_js(js)


def collect_and_scroll():
    """Collect current DOM pins, then scroll down."""
    js = r"""
    (function() {
      window.__COLLECT_PINS__();
      window.scrollBy(0, 800);
      return String(window.__PIN_COUNT__);
    })();
    """
    result = chrome_js(js)
    try:
        return int(result)
    except (ValueError, TypeError):
        return -1


def get_collected_pins() -> list:
    """Retrieve all collected pins from the JS global."""
    js = r"""
    (function() {
      var pins = [];
      var all = window.__ALL_PINS__ || {};
      var keys = Object.keys(all);
      for (var i = 0; i < keys.length; i++) {
        pins.push(all[keys[i]]);
      }
      return JSON.stringify(pins);
    })();
    """
    raw = chrome_js(js, timeout=60)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"    WARN: parse failed, len={len(raw)}")
        # Try chunked retrieval
        return get_collected_pins_chunked()


def get_collected_pins_chunked() -> list:
    """Retrieve pins in chunks if the full dump is too large for AppleScript."""
    # Get count
    count_str = chrome_js("String(window.__PIN_COUNT__ || 0);")
    try:
        total = int(count_str)
    except (ValueError, TypeError):
        return []

    all_pins = []
    chunk = 100
    for offset in range(0, total, chunk):
        js = f"""
        (function() {{
          var pins = [];
          var all = window.__ALL_PINS__ || {{}};
          var keys = Object.keys(all);
          for (var i = {offset}; i < Math.min({offset + chunk}, keys.length); i++) {{
            pins.push(all[keys[i]]);
          }}
          return JSON.stringify(pins);
        }})();
        """
        raw = chrome_js(js, timeout=30)
        try:
            chunk_pins = json.loads(raw)
            all_pins.extend(chunk_pins)
        except json.JSONDecodeError:
            print(f"    WARN: chunk {offset} failed")
    return all_pins


def upgrade_image_url(url: str) -> str:
    """Convert thumbnail URL to /originals/ URL."""
    if not url or "pinimg.com" not in url:
        return url
    return re.sub(r"/\d+x(?:_RS)?/", "/originals/", url)


def scrape_board(board_slug: str) -> list:
    """Scrape all pins from a single board using incremental collection."""
    url = f"{BASE_URL}/{board_slug}/"
    print(f"  -> {url}")
    chrome_navigate(url, wait=5.0)

    # Install the collector
    result = install_collector()
    print(f"  {result}")

    # Scroll incrementally, collecting at each step
    # Use smaller scroll increments (800px) to catch all virtualized elements
    prev_count = 0
    stale = 0
    max_scrolls = 500  # enough for ~850 pin boards
    for i in range(max_scrolls):
        count = collect_and_scroll()
        if i % 10 == 0:
            print(f"    scroll {i}: {count} pins collected")
        if count == prev_count:
            stale += 1
            if stale >= 6:  # more patience for lazy loading
                break
        else:
            stale = 0
        prev_count = count
        time.sleep(0.8)

    print(f"  total collected: {prev_count}")

    # Retrieve all collected pins
    print(f"  retrieving...")
    pins = get_collected_pins()

    for p in pins:
        p["image_url"] = upgrade_image_url(p.get("image_url", ""))
        p["board"] = board_slug
        p["pin_url"] = f"https://www.pinterest.com/pin/{p['pin_id']}/"

    print(f"  got {len(pins)} pins")
    return pins


def main():
    all_pins = []
    board_stats = {}
    total_start = time.time()

    # Resume support
    resume_from = 0
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT) as f:
                existing = json.load(f)
            if existing.get("pins"):
                scraped_boards = {p.get("board") for p in existing["pins"]}
                completed = [b for b in BOARDS if b in scraped_boards
                             and any(p["board"] == b for p in existing["pins"])]
                if completed:
                    for idx, b in enumerate(BOARDS):
                        if b not in completed:
                            resume_from = idx
                            break
                    else:
                        resume_from = len(BOARDS)
                    all_pins = [p for p in existing["pins"] if p.get("board") in completed]
                    for b in completed:
                        board_stats[b] = sum(1 for p in all_pins if p["board"] == b)
                    print(f"Resuming: {len(all_pins)} pins from {len(completed)} boards")
        except (json.JSONDecodeError, KeyError):
            pass

    boards_to_scrape = BOARDS[resume_from:]
    if not boards_to_scrape:
        print("All boards already scraped!")
        return

    print(f"\nScraping {len(boards_to_scrape)} boards for '{USERNAME}'...\n")

    for i, board in enumerate(boards_to_scrape):
        board_num = resume_from + i + 1
        print(f"[{board_num}/{len(BOARDS)}] {board}")
        start = time.time()

        try:
            pins = scrape_board(board)
            all_pins.extend(pins)
            board_stats[board] = len(pins)
            elapsed = time.time() - start
            print(f"  {elapsed:.0f}s\n")
        except Exception as e:
            print(f"  ERROR: {e}\n")
            import traceback
            traceback.print_exc()
            board_stats[board] = -1

        # Save after each board
        output_data = {
            "username": USERNAME,
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "board_stats": board_stats,
            "total_pins": len(all_pins),
            "pins": all_pins,
        }
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump(output_data, f, indent=2)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"Done in {total_elapsed:.0f}s | {len(all_pins)} total pins")
    for board, count in sorted(board_stats.items()):
        print(f"  {board}: {count if count >= 0 else 'ERROR'}")
    print(f"\nSaved: {OUTPUT}")


if __name__ == "__main__":
    main()
