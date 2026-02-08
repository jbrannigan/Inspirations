# Next Steps (Resume After Restart)

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
