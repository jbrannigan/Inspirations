# Next Steps (Resume After Restart)

## Current checkpoint (February 19, 2026, 01:55 UTC)
- Main app scan behavior is now explicitly document-first:
  - multipage scans are shown as one card in canvas/tray
  - doc actions (add/remove/hide/unhide) apply to all pages in the document
  - visible card title is content-first (no visible `- doc X` / `pY` suffix)
- Scan page-level rows are still retained internally for ingestion fidelity and metadata.
- Upload flow in app is active for `Add Scan PDF` (single-file workflow now); delimiter splitting and richer drag/drop remain optional follow-up work.
- Cluster Explorer workstream is still active and should resume after scan-ingest UX stabilization.
- Most recent checkpoint entry is in `docs/handoff.md`:
  - `Session Checkpoint (2026-02-19T01:55:35.556223+00:00)`
  - next actions recorded there:
    1. review separator-page handling + drag/drop nice-to-have
    2. continue cluster-review UX integration into main app

## Previous checkpoint (February 14, 2026, 00:02 CST)
- Cluster Explorer planning has a new canonical spec: `docs/CLUSTER_EXPLORER_SPEC-v2.md`.
- Prior spec file was retained as historical reference: `docs/CLUSTER_EXPLORER_SPEC-old.md`.
- Current runnable tooling in this repo is:
  - `tools/export_clusters.py`
  - `tools/serve_explorer.py`
  - `tools/cluster_explorer.html`
  - `tools/cluster_data.json` (latest snapshot generated)
- Verified snapshot from `tools/cluster_data.json`:
  - `nodes=95`
  - `links=265`
  - `clusters=8`
  - `source_db=data/inspirations.sqlite`
  - `collection_id=55205463-0101-4cbf-8880-b38fa68c24bc` (`CB: Kitchen`)
  - `include_neighbors=15`
  - `focus_count=80`, `nearby_count=15` (when exported with current tooling)
  - `api_base=''` (session-only delete mode)
  - `similarity_threshold=0.72`

### Cluster explorer status at resume
- Implemented now:
  - Export embeddings and graph links with `tools/export_clusters.py` (v2 schema fields and outlier metrics).
  - Collection-scoped exports mark each node as `in_focus_collection` vs `is_nearby_context`.
  - Serve the explorer with `tools/serve_explorer.py` (allowlisted routes + cache policy).
  - Discover/Outliers visual modes in `tools/cluster_explorer.html`.
  - In collection-scoped review, nearby context is hidden by default and can be toggled with `Show nearby (...)`.
  - Duplicate review workflow:
    - grouped duplicate sets with left/right navigation
    - mark keeper/losers
    - queue losers
    - apply delete per-group or queued
  - Detail-panel remove action for collection-focused runs when `meta.api_base` is present.
- Not implemented yet (documented in v2 spec):
  - Advanced curation mode (lasso/tray multi-action workflow).

### Recommended restart path for clustering work
1. Recreate isolated venv for clustering dependency:
```bash
python3 -m venv /private/tmp/inspirations-cluster-venv
source /private/tmp/inspirations-cluster-venv/bin/activate
python -m pip install scikit-learn
```
2. Re-export fresh cluster graph JSON:
```bash
python3 tools/export_clusters.py \
  --db data/inspirations.sqlite \
  --out tools/cluster_data.json \
  --clusters auto \
  --similarity-threshold 0.72 \
  --max-neighbors 6
```
3. Serve explorer over HTTP (primary mode):
```bash
python3 tools/serve_explorer.py --port 8080 --data tools/cluster_data.json --project-root .
```
4. Open `http://127.0.0.1:8080` and review outliers.
5. For collection-focused trimming with direct remove action:
```bash
python3 tools/export_clusters.py \
  --db data/inspirations.sqlite \
  --out tools/cluster_data.json \
  --collection-id <COLLECTION_ID> \
  --include-neighbors 15 \
  --api-base http://127.0.0.1:8000
```

## 0) Resume Codex collaboration
When you restart, open a new Codex terminal in this repo and read:
- `docs/handoff.md` — full history + key commands
- `docs/pr_summary.md` — PR summary of latest changes
- `docs/next_steps.md` — this file
- `docs/potential_future_options.md` — roadmap and ingestion/sync options

Before you stop work, always create a durable checkpoint entry:
```bash
PYTHONPATH=src python3 tools/session_checkpoint.py \
  --note "short summary of this session" \
  --next "first concrete next action" \
  --next "second concrete next action"
```

Automatic safety net is now in place:
- Local Git `post-merge` hook runs maintenance + local checkpoint writes automatically.
- Hook outputs:
  - `data/session_checkpoints/last_checkpoint.json`
  - `data/session_checkpoints/checkpoint_*.json`
  - `data/session_checkpoints/post_merge_hook.log`
- If hooks are disabled in a new clone/session, re-enable with:
  - `git config core.hooksPath .githooks`

### Coordination checklist (for multiple Codex instances)
1. **Declare intent** in chat: what you plan to change and why.
2. **Read shared context**: `docs/handoff.md` + `docs/next_steps.md`.
3. **Verify DB state** (see section 2 below) before any tagging re‑runs.
4. **Avoid duplicate work**: confirm no other instance is running a batch or ingest.
5. **Update handoff** after every material change.

### Standard sync prompt (copy/paste)
```
Please read docs/handoff.md and docs/next_steps.md, then summarize current state, active processes, and open tasks. 
Run `PYTHONPATH=src python3 tools/session_sync.py` and report results before making changes.
```

### Standard checkpoint prompt (copy/paste before pausing)
```
Run `PYTHONPATH=src python3 tools/session_checkpoint.py --note "<session summary>" --next "<next action>"`.
Confirm the latest checkpoint section was appended to docs/handoff.md and list the recorded next actions.
```

### Roles (optional but helpful)
- **Driver**: Executes commands and edits files.
- **Navigator**: Reviews, checks docs, calls out risks or missing tests.
- **Reporter**: Updates `docs/handoff.md` and `docs/pr_summary.md`.

If you are solo, you can “rotate” roles: run → review → document.

### Branching / PR conventions (lightweight)
- Use a feature branch named with date + topic, e.g. `2026-02-05-tagging-pipeline`.
- One PR per theme (e.g., UI changes separate from pipeline changes if possible).
- Include `docs/pr_summary.md` content in the PR description.
- Avoid committing secrets or API keys.

### Handoff discipline
- Always append to `docs/handoff.md` with **date + timestamp**.
- Include: what changed, commands run, counts, and any errors.
- If you started a long‑running job, note how to monitor or resume it.

### Safety rules
- Do **not** re‑run tagging blindly.
- Always check `asset_ai_errors` and counts first.
- If a batch is pending, wait or ingest output instead of re‑submitting.

### Fast path (5‑minute restart checklist)
See `docs/fast_path.md` for the step-by-step checklist.

## 1) Start the app server
```bash
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000 --app app --store store --reload
```
Open:
- http://127.0.0.1:8000

## 2) Verify tagging status
```bash
PYTHONPATH=src python3 tools/session_sync.py

sqlite3 /Users/minime/Projects/Inspirations/data/inspirations.sqlite \
  "select count(*) from asset_ai where provider='gemini' and model='gemini-2.5-flash';"

sqlite3 /Users/minime/Projects/Inspirations/data/inspirations.sqlite \
  "select count(*) from assets where source='pinterest' and id not in (select asset_id from asset_ai where provider='gemini' and model='gemini-2.5-flash');"
```

Expected as of February 8, 2026:
- `asset_ai(gemini-2.5-flash)=3654`
- `remaining(pinterest, gemini-2.5-flash)=7` (RECITATION-blocked)
- `remaining(pinterest, gemini any-model)=0`

## 3) Retry remaining assets (optional, model-specific only)
Pipeline uses provider-level candidate selection and will no-op when provider coverage is complete.
Do not run this unless you explicitly want to replace the 7 recitation-fallback rows with a different model outcome:
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_pipeline.py --mode auto --limit 0
```

## 4) Review in the UI
- Cards are compact by default
- Click a card to expand full tag buckets
- Click **Annotate** to open the note/badge modal

## 5) Investigate failures (triage command)
Use the triage command to separate actionable errors from already-resolved historical rows:
```bash
PYTHONPATH=src python3 -m inspirations ai errors \
  --source pinterest --provider gemini --model gemini-2.5-flash
```

Raw SQL fallback:
```bash
sqlite3 /Users/minime/Projects/Inspirations/data/inspirations.sqlite \
  "select error, count(*) from asset_ai_errors group by error order by count(*) desc;"
```

## 6) Current product priorities
1. Backfill embeddings:
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai embed --source pinterest --model gemini-embedding-001
```
2. Validate similarity quality:
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai similar --query "warm kitchen with white oak cabinets" --source pinterest --limit 20
```
3. Tune semantic relevance and ranking quality after embedding backfill (prompt text, filters, and score cutoffs).

## 7) New workstream: scanned recipes + split UX

### Objective
- Add a reliable scanned-recipe intake flow.
- Prepare a future split where Inspirations excludes recipes by default and a separate iPad-first recipe UX handles kitchen usage.

### Immediate execution plan
1. Stand up recipe scan intake convention:
```bash
mkdir -p imports/scans/inbox/recipes imports/scans/inbox/inspirations
```
2. Import new scans in batches and generate thumbs:
```bash
PYTHONPATH=src python3 -m inspirations import scans --inbox imports/scans/inbox --format jpg
PYTHONPATH=src python3 -m inspirations thumbs --size 512 --source scan
```
3. Create a working collection for scanned recipes and move known recipe scans there.
4. Define classification target field (`recipe` vs `inspiration`) and apply first pass manually.
5. Plan OCR + recipe-text extraction spike so recipe search quality does not depend only on titles.

### Medium-term delivery milestones
1. Add scan import telemetry (seen/imported/skipped/errors).
2. Add recipe classification and filtering in API + UI.
3. Add OCR-backed searchable text for scanned recipes.
4. Add `/kitchen` recipe-focused route, then make it installable as a PWA for iPad.

## Files to know
- `docs/handoff.md` — detailed run history + commands
- `docs/tagging_pipeline.md` — pipeline flow + flags
- `docs/AI_TAGGING_PLAN.md` — schema + tagging commands
