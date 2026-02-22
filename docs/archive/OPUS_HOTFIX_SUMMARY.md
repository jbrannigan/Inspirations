# Opus Hotfix: Facebook Image Quality + Orphan Recovery

## What Changed (done directly, no code changes needed)

### 1. Upgraded 23 Facebook images to high-res originals
The Word doc import extracted tiny Facebook thumbnails (avg 16KB). The old JSON import had previously downloaded full-resolution images from the source websites (avg 400KB, ~22x bigger). For 23 items that existed in both imports, I swapped the stored image files and updated `stored_path` and `sha256` in the DB.

### 2. Recovered 46 orphan Facebook items
These were "saved link" items (architectural firms, house plans, home products, recipes, etc.) that had real downloaded images from the old JSON import but were NOT in any Facebook collection — so the Word doc didn't include them. I inserted them as new asset rows with `source='facebook'`, `media_status='image'`, no `board` value. Their image files were already on disk from the previous import.

### 3. Cleaned up 14 fake image files
14 files from the old JSON import were actually HTML pages saved with `.jpg` extensions (the old downloader grabbed the webpage instead of an image). Deleted those files, set `stored_path=NULL`, `media_status='metadata_only'` on those rows.

### 4. Generated thumbnails
Ran `thumbs --source facebook` — created thumbs for all 46 new items (32 real images got thumbs, 14 fake ones were caught and cleaned up above).

### 5. Cleanup
- Deleted `store/originals/facebook/` (132 orphaned UUID-named files, 51.9MB) — all useful content already copied to `data/originals/facebook/`
- Deleted `data/inspirations.db` (0 bytes, empty file created by mistake when import ran against wrong DB path)

## Current Database State

```
ASSETS:  5,072 total
  pinterest    3,661 image
  facebook       997 image + 307 metadata_only = 1,304
  scan           107 image

COLLECTIONS: 114 total
  12  CB: collections (808 items, all Pinterest)
  102 pins: promoted board collections (3,661 items, all Pinterest)

AI COVERAGE:
  pinterest:  tagged 3661/3661 (100%), embedded 3661/3661 (100%)
  facebook:   tagged  949/1304  (72%), embedded 1258/1304  (96%)
  scan:       tagged  107/107  (100%), embedded    0/107    (0%)

FILES: All 997+3661+107 = 4,765 image files verified on disk. All thumbs OK.
```

## What Still Needs Doing

### Immediate (run these commands)

**Tag the 355 untagged Facebook items:**
```bash
PYTHONPATH=src python3 -m inspirations --db data/inspirations.sqlite ai tag --source facebook
```

**Embed the 46 new orphan items + 107 scans:**
```bash
PYTHONPATH=src python3 -m inspirations --db data/inspirations.sqlite ai embed --source facebook
PYTHONPATH=src python3 -m inspirations --db data/inspirations.sqlite ai embed --source scan
```

### Note on the 46 orphan items
These have `board IS NULL` — they weren't saved to any Facebook collection. They're a mix of home-related links (architectural firms, house plans, building products, paint colors) and non-home stuff (recipes, health, fashion). They'll need categorization later as part of the collection audit/triage work.
