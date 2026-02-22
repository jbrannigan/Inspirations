# Fast Path Checklist (5-Minute Restart)

## 1) Read shared context
- `docs/handoff.md`
- `docs/next_steps.md`
- `docs/pr_summary.md`

## 2) Sanity-check DB status
```bash
PYTHONPATH=src python3 tools/session_sync.py
```

Optional manual query fallback:
```bash
sqlite3 /Users/minime/Projects/Inspirations/data/inspirations.sqlite \
  "select count(*) from asset_ai where provider='gemini' and model='gemini-2.5-flash';"

sqlite3 /Users/minime/Projects/Inspirations/data/inspirations.sqlite \
  "select count(*) from assets where source='pinterest' and id not in (select asset_id from asset_ai where provider='gemini' and model='gemini-2.5-flash');"
```

## 3) Start the app server
```bash
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000 --app app --store store --reload
```

## 4) Run tagging only if needed
If remaining > 0, use the pipeline:
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_pipeline.py --mode auto --limit 0
```

## 5) Update coordination docs
- Append to `docs/handoff.md` with date/time, commands, and counts
- Update `docs/pr_summary.md` if behavior changed

## 6) If multiple Codex instances are active
- Declare intent before changes
- Confirm no other batch or ingest is running
- Avoid reruns unless counts changed
