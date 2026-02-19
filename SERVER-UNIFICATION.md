# Server Unification — Inspirations

## Current State Assessment

| Aspect | Current |
|--------|---------|
| **Stack** | Python 3.11+ (stdlib only, no framework) |
| **Backend** | Custom `http.server.HTTPServer` + `BaseHTTPRequestHandler` |
| **Database** | SQLite 3 (file-based, `data/inspirations.sqlite`) |
| **Auth** | Optional admin password (token-based, 1-hour expiry, `X-Admin-Token` header) |
| **Dev Port** | 8000 (configurable via `--port`) |
| **External Services** | Google Gemini API (optional, for AI tagging + embeddings) |
| **Frontend** | Vanilla HTML/CSS/JS (no build step, served from `app/` directory) |
| **Media Storage** | Local filesystem (`store/originals/`, `store/thumbs/`) |
| **Deployment** | Local-only (single-user, designed for LAN access) |
| **Dev Command** | `PYTHONPATH=src python3 -m inspirations serve --port 8000 --app app --store store` |

## Containerization Plan

### Docker Compose Services

```yaml
# inspirations/docker-compose.yml
services:
  inspirations-app:
    build: .
    ports:
      - "8001:8000"   # Remap to avoid conflicts
    volumes:
      - ./data:/app/data          # SQLite DB + backups
      - ./store:/app/store        # Media files (originals + thumbnails)
      - ./imports:/app/imports    # Import staging area
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - INSPIRATIONS_ADMIN_PASSWORD=${INSPIRATIONS_ADMIN_PASSWORD:-}
```

### Dockerfile

Lightweight Python image:
```dockerfile
FROM python:3.12-slim
# Install optional system deps: sips (macOS only), imagemagick, poppler-utils
RUN apt-get update && apt-get install -y imagemagick poppler-utils && rm -rf /var/lib/apt/lists/*
COPY . /app
WORKDIR /app
RUN pip install -e .
EXPOSE 8000
CMD ["inspirations", "serve", "--host", "0.0.0.0", "--port", "8000", "--app", "app", "--store", "store"]
```

### What Changes

- **Host binding**: Must bind to `0.0.0.0` (not `127.0.0.1`) inside container
- **Port mapping**: Remap from 8000 to **8001** externally
- **Volume mounts**: SQLite DB, media store, and imports directory must be mounted volumes (data must persist across container restarts)
- **Thumbnail generation**: `sips` (macOS-only) won't be available in Linux container — falls back to ImageMagick or Pillow
- **PDF rendering**: `pdftoppm` or `mutool` needed in container image
- **Auto-reload**: Dev mode with `--reload` would need file-watching to work through Docker volume mounts

### Cloud Deployment Readiness

- **Challenge**: SQLite doesn't work well in cloud environments (no concurrent writes, file lock issues with network storage)
- **Migration path**: For cloud, would need to migrate from SQLite to PostgreSQL
- **Media storage**: Local filesystem won't work in cloud — would need S3/R2/Supabase Storage
- **AI tagging**: Gemini API calls work anywhere (just needs API key)
- **Recommendation**: Keep as local Docker container for now; cloud migration requires database and storage refactoring

## Authentication Considerations

- **Current**: Simple admin password → token exchange (no user accounts)
- **No multi-user auth** — designed as single-user local app
- **Unified approach**: Could add Supabase Auth or a shared JWT verification layer, but the app architecture assumes single-user local access
- **For unified auth**: The admin token system would need to be replaced with a proper auth middleware that validates tokens from the central auth provider
- **API endpoints**: All `/api/*` routes would need auth middleware added (currently only `/api/admin/*` routes require auth)

## Port Allocation (Proposed)

| Service | Internal Port | External Port |
|---------|--------------|---------------|
| Inspirations App | 8000 | **8001** |

## Migration Effort: Medium

- **Easy**: Python containerizes well; no build step for frontend
- **Medium**: Volume mount strategy for SQLite + media files needs careful planning
- **Challenge**: macOS-specific tools (`sips`) need Linux alternatives in container
- **Risk**: SQLite file locking with Docker volume mounts can be tricky
- **Dev workflow**: Hot reload through Docker volumes needs testing

## Special Considerations

- **Data volume**: Media files (originals + thumbnails) can be very large — container image should NOT include them
- **Import workflow**: Pinterest/Facebook ZIP imports need access to the imports directory
- **Cluster explorer**: `tools/serve_explorer.py` runs a separate HTTP server — may need its own service or port
- **Batch AI tagging**: Long-running Gemini batch jobs need process persistence
