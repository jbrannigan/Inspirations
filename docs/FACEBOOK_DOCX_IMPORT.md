# Facebook Word Doc Import — Implementation Brief

## Before You Start

Read these files first:
- `CLAUDE.md` — project conventions, common commands
- `DECISIONS.md` — architectural constraints (especially D001: no external Python deps)
- `src/inspirations/importers/facebook_saved.py` — existing JSON importer to reference for field names, content_kind detection, creator extraction patterns, dedup approach
- `src/inspirations/db.py` — schema (assets table columns, unique index on `(source, source_ref)`)
- `src/inspirations/cli.py` — existing CLI subcommands to follow the pattern

## What You're Building

A new importer that reads Leslie's Facebook saves from a copy-pasted Word document (DOCX format). The DOCX contains ~3,853 structured entries with titles, Facebook URLs, embedded JPEG thumbnails, collection assignments, content types, and creator names. We import only home/design-related collections (~1,506 items).

The Word doc is at `imports/raw/Leslies Facebook Saves.docx` (81MB, 5,673 embedded JPEGs).

## Constraint: stdlib only

The DOCX format is a ZIP containing XML files. Parse it with `zipfile`, `xml.etree.ElementTree`, and `re`. Do NOT use `python-docx` or any external package (Decision D001).

## The DOCX Structure

A DOCX is a ZIP archive. The key files inside:

- `word/document.xml` — all paragraphs and text content (63MB)
- `word/_rels/document.xml.rels` — hyperlink relationships (rId → URL mapping)
- `word/media/image{N}.jpeg` — 5,673 embedded thumbnail images (~14KB avg)

### XML Namespaces

```
w  = http://schemas.openxmlformats.org/wordprocessingml/2006/main
r  = http://schemas.openxmlformats.org/officeDocument/2006/relationships
wp = http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing
a  = http://schemas.openxmlformats.org/drawingml/2006/main
pic = http://schemas.openxmlformats.org/drawingml/2006/picture
```

### Paragraph Structure

Each entry follows a repeating pattern of 3-4 paragraphs:

```
Paragraph 1 (optional): Duration like "00:25" — plain text, no hyperlink
Paragraph 2: Title text — contains a <w:hyperlink> linking to the Facebook URL
Paragraph 3: "Reels • Saved to recipe" or "Post • Saved to kitchen" — hyperlink on collection name
Paragraph 4: "Saved from Taste.com.au's post" — hyperlink(s) on creator name and optional group
```

**Sometimes paragraph 1 is missing** (posts don't have durations). The "Saved to" line is the reliable delimiter.

### Hyperlink Extraction

In `word/_rels/document.xml.rels`, each `<Relationship>` element has:
- `Id` = "rId12345"
- `Type` = "...hyperlink" (filter for hyperlink type only)
- `Target` = the URL

In `word/document.xml`, hyperlinks appear as:
```xml
<w:hyperlink r:id="rId12345">
  <w:r><w:t>link text</w:t></w:r>
</w:hyperlink>
```

Map `r:id` to the URL from the relationships file.

### Image-to-Entry Association

Each entry's image is in a paragraph containing a `<w:drawing>` element. Inside:
```xml
<w:drawing>
  <wp:inline>
    <a:graphic>
      <a:graphicData>
        <pic:pic>
          <pic:blipFill>
            <a:blip r:embed="rId99999"/>
          </pic:blipFill>
        </pic:pic>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>
```

The `r:embed` attribute maps to a relationship in `document.xml.rels` where the Target is like `media/image123.jpeg`. This is the path inside the DOCX ZIP.

Image paragraphs appear near title paragraphs — they're typically the same paragraph as the title (the image and title text coexist in one `<w:p>` element), or they're an adjacent paragraph.

**Strategy:** As you walk paragraphs, if a paragraph contains both a `<w:drawing>` (image) and a `<w:hyperlink>` (title link), associate the image with that entry. If the image is in a separate adjacent paragraph, associate it with the most recent entry being built.

## Entry Parsing Algorithm

```python
entries = []
current = {}

for paragraph in all_paragraphs:
    text = extract_text(paragraph)
    links = extract_hyperlinks(paragraph)
    image_path = extract_image_ref(paragraph)  # from <a:blip r:embed>

    # Duration line: "00:25" pattern
    if re.match(r'^\d{2}:\d{2}$', text):
        if current and 'title' in current:
            entries.append(current)
        current = {'duration': text}
        continue

    # "Saved to" line: "Reels • Saved to kitchen"
    saved_to_match = re.match(r'^(.*?)\s*[•·]\s*Saved to\s+(.+)$', text)
    if saved_to_match:
        content_type = saved_to_match.group(1).strip()  # "Reels", "Post", "Link"
        collection = saved_to_match.group(2).strip()     # "kitchen", "building"
        if current:
            current['content_type'] = content_type
            current['collection'] = collection
        continue

    # "Saved from" line: "Saved from Taste.com.au's post"
    if text.startswith('Saved from'):
        creator_match = re.match(r"Saved from (.+?)'s (?:post|video|reel)", text)
        if creator_match and current:
            current['creator_name'] = creator_match.group(1).strip()
        # This is the last line of an entry — append it
        if current and 'title' in current:
            entries.append(current)
            current = {}
        continue

    # Otherwise: title/content line
    if not current.get('title'):
        current['title'] = text
        if links:
            current['url'] = links[0]['url']
        if image_path:
            current['image_path'] = image_path
    elif image_path and 'image_path' not in current:
        current['image_path'] = image_path
```

## Home/Design Collection Whitelist

Only import entries whose collection name is in this set (case-sensitive match, since that's how the data appears):

```python
HOME_DESIGN_COLLECTIONS = {
    'kitchen', 'building', 'bathroom', 'door', 'floor plans', 'paint',
    'furniture', 'flooring', 'lighting', 'windows', 'garage', 'hvac',
    'insulation', 'roofing', 'interior design', 'interior design/architect',
    'cabinet', 'cabinets', 'tile', 'concrete', 'stone', 'brick', 'mudroom',
    'laundry', 'drywall', 'ceiling fan', 'molding', 'appliances',
    'style board', 'living room', 'bedroom', 'Fireplace', 'aging in place',
    'pocket door', 'quartzite', 'carpet', 'Sheet rock', 'foundation',
    'propane', 'electric', 'generator', 'plumbing', 'water heater',
    'Water heater', 'water', 'well', 'septic', 'Inspection', 'Gutters',
    'land', 'lot', 'survey', 'soil test', 'architect', 'contract',
    'estimates', 'punch list', 'Selling home', 'Mortgage', 'Insurance',
    'insurance', 'home insurance', 'Trust', 'legal', 'Home & Garden',
    'garden', '2b/2b', 're: builders', 'cottage of the year', 'freeze',
    'mold', 'security', 'internet', 'solar', 'land clearing', 'caulk',
    'drain pan', 'water softener', 'ADA',
}
```

Some entries have "kitchen 2 + 1 other" or "paint + 1 other" — strip the " + 1 other" suffix before matching, and use the base collection name.

Expected result: ~1,506 items imported.

## Asset Row Mapping

For each filtered entry, create a DB row:

| Column | Value |
|--------|-------|
| `id` | `uuid.uuid4()` |
| `source` | `"facebook"` |
| `source_ref` | Facebook URL from entry. If no URL, `hashlib.sha256(f"{title}|{collection}".encode()).hexdigest()` |
| `title` | Entry title text (already clean — no "Leslie Brannigan saved" prefix in Word doc) |
| `description` | None |
| `board` | Collection name (e.g., "kitchen", "building") |
| `created_at` | None (timestamps not available in Word doc; enriched later) |
| `imported_at` | Current ISO timestamp |
| `image_url` | None (images are embedded, not URLs) |
| `stored_path` | Path to extracted JPEG if available, else None |
| `media_status` | `"image"` if JPEG extracted, else `"metadata_only"` |
| `content_kind` | Map from content type: "Reels"/"Reel" → `"reel"`, "Post" → `"post"`, "Link" → `"link"`, else `"other"` |
| `creator_name` | From "Saved from X's post" line |
| `source_domain` | Parse domain from Facebook URL (e.g., `"facebook.com"`) |
| `source_name` | Creator name (same as creator_name for Facebook) |

**Dedup key:** Unique index `(source, source_ref)`. Use `INSERT OR IGNORE` to prevent duplicates on re-run.

## Image Extraction

For entries with an associated image path (like `media/image123.jpeg`):

1. Read the JPEG bytes from the DOCX ZIP
2. Compute SHA256 of the bytes
3. Save to `{store_dir}/originals/facebook/{sha256}.jpg`
4. Create `{store_dir}/originals/facebook/` directory if it doesn't exist
5. Set `stored_path` on the asset row to the relative path
6. Set `sha256` on the asset row

The `store_dir` is the same one used by other importers. Look at how `facebook_saved.py` or the Pinterest importer determines the store directory path from CLI arguments.

## CLI Command

**File:** `src/inspirations/cli.py`

Add a new subcommand following the existing pattern:

```python
def cmd_import_facebook_docx(args):
    db_path = _p(args.db)
    store_dir = _p(args.store)
    docx_path = _p(args.docx)

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_facebook_docx(
            db=db,
            docx_path=docx_path,
            store_dir=store_dir,
            collections_filter=args.collections_filter,
        )

    print(json.dumps(report, indent=2))
    return 0
```

Wire it into argparse:
```python
sp = sub.add_parser("import", ...).add_subparsers(...)
# Or add alongside existing import subcommands:
fb_docx = sub.add_parser("import-facebook-docx", help="Import Facebook saves from Word doc")
fb_docx.add_argument("--docx", required=True, help="Path to DOCX file")
fb_docx.add_argument("--db", required=True)
fb_docx.add_argument("--store", required=True)
fb_docx.add_argument("--collections-filter", choices=["home-design", "all"], default="home-design")
fb_docx.set_defaults(func=cmd_import_facebook_docx)
```

**Check how the existing import commands are structured** in cli.py — the Pinterest and Facebook JSON imports use a specific subparser pattern. Follow the same pattern exactly.

## Import Report

Return a JSON report similar to the existing Facebook importer (`facebook_saved.py:284-307`):

```json
{
  "source_file": "Leslies Facebook Saves.docx",
  "total_entries_parsed": 3853,
  "filtered_home_design": 1506,
  "imported_assets": 1506,
  "existing_assets": 0,
  "images_extracted": 1200,
  "metadata_only": 306,
  "collections_seen": ["kitchen", "building", "bathroom", ...],
  "content_kind_counts": {"reel": 800, "post": 600, "link": 50, "other": 56}
}
```

## Tests

**File:** `tests/test_facebook_docx_import.py`

Create a minimal synthetic DOCX for testing (a ZIP containing the necessary XML files with 2-3 test entries). Test:

1. Entry parsing: correct title, URL, collection, content_type, creator extraction
2. Collection filtering: home-design entries pass, recipe/exercise entries are skipped
3. Image extraction: JPEG saved to correct path with SHA256 name
4. Dedup: running import twice produces same count (idempotent)
5. "Saved to" suffix stripping: "kitchen 2 + 1 other" → "kitchen 2"

Look at `tests/test_facebook_import.py` for the test pattern — it creates a synthetic ZIP with known data and verifies the import results.

## Verification

```bash
# Import from Word doc
PYTHONPATH=src python3 -m inspirations import-facebook-docx \
  --docx imports/raw/Leslies\ Facebook\ Saves.docx \
  --db data/inspirations.db \
  --store data/ \
  --collections-filter home-design

# Should print JSON report with ~1,506 imported assets

# Check DB
PYTHONPATH=src python3 -m inspirations list --db data/inspirations.db
# Should show facebook source with ~1,506 assets

# Generate thumbnails
PYTHONPATH=src python3 -m inspirations thumbs --source facebook --db data/inspirations.db --store data/

# Start server and check
PYTHONPATH=src python3 -m inspirations serve --reload
# Open http://127.0.0.1:8000
# Filter by Source: facebook
# Should see items with thumbnails, board values (kitchen, building, etc.)
# Click an item → detail view shows title, creator, board
# "View Source" should open the Facebook URL

# Tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
```

## Files Summary

**Create:**
- `src/inspirations/importers/facebook_docx.py` — Word doc parser + DB insertion
- `tests/test_facebook_docx_import.py` — tests with synthetic DOCX

**Modify:**
- `src/inspirations/cli.py` — add `import-facebook-docx` subcommand

**Reference (don't modify):**
- `src/inspirations/importers/facebook_saved.py` — field patterns, content_kind mapping
- `src/inspirations/db.py` — schema reference
- `tests/test_facebook_import.py` — test pattern reference
