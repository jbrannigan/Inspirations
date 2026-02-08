from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .db import Db, ensure_schema
from .importers.facebook_saved import import_facebook_saved_zip
from .importers.pinterest_crawler import import_pinterest_crawler_zip
from .importers.scans import import_scans_inbox
from .storage import download_and_attach_originals
from .thumbnails import generate_thumbnails
from .ai import (
    DEFAULT_GEMINI_EMBEDDING_MODEL,
    run_ai_error_triage,
    run_ai_labeler,
    run_gemini_text_embedder,
    run_similarity_search,
)
from .server import run_server


def _p(p: str) -> Path:
    return Path(p).expanduser().resolve()


def cmd_init(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    store_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with Db(db_path) as db:
        ensure_schema(db)
    print(json.dumps({"ok": True, "db": str(db_path), "store": str(store_dir)}))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        rows = db.query(
            "select source, count(*) as n from assets group by source order by n desc, source asc"
        )
        total = db.query_value("select count(*) from assets")
    out = {"total_assets": total, "by_source": [{"source": r["source"], "n": r["n"]} for r in rows]}
    print(json.dumps(out, indent=2))
    return 0


def cmd_import_pinterest(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    zip_path = _p(args.zip)

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_pinterest_crawler_zip(db, zip_path, limit=args.limit)

    if args.download:
        with Db(db_path) as db:
            ensure_schema(db)
            dl = download_and_attach_originals(
                db=db, store_dir=store_dir, source="pinterest", limit=args.download_limit
            )
        report["downloaded"] = dl

    print(json.dumps(report, indent=2))
    return 0


def cmd_import_facebook(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    zip_path = _p(args.zip)

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_facebook_saved_zip(db, zip_path, limit=args.limit)

    if args.download:
        with Db(db_path) as db:
            ensure_schema(db)
            dl = download_and_attach_originals(
                db=db,
                store_dir=store_dir,
                source="facebook",
                limit=args.download_limit,
                retry_non_image=args.retry_non_image,
            )
        report["downloaded"] = dl

    print(json.dumps(report, indent=2))
    return 0


def cmd_import_scans(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    inbox = _p(args.inbox)
    store_dir = _p(args.store)

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_scans_inbox(
            db,
            inbox_dir=inbox,
            store_dir=store_dir,
            format=args.format,
            limit=args.limit,
            max_pages=args.max_pages,
            renderer=args.renderer,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_thumbs(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    source = args.source.strip() or None
    with Db(db_path) as db:
        ensure_schema(db)
        report = generate_thumbnails(
            db,
            store_dir=store_dir,
            size=args.size,
            limit=args.limit,
            source=source,
            tool=args.tool,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_tag(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_ai_labeler(
            db,
            provider=args.provider,
            limit=args.limit,
            api_key=args.api_key,
            model=args.model,
            recitation_fallback_model=args.recitation_fallback_model,
            source=args.source,
            image_kind=args.image_kind,
            force=args.force,
            store_dir=_p(args.store),
            preflight=args.preflight,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_errors(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_ai_error_triage(
            db,
            source=args.source,
            provider=args.provider,
            model=args.model,
            days=args.days,
            limit=args.limit,
            examples_per_action=args.examples_per_action,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_embed(args: argparse.Namespace) -> int:
    provider = (args.provider or "gemini").strip().lower()
    if provider != "gemini":
        raise ValueError("Unsupported provider for embeddings. Use provider=gemini.")
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY") or ""
    if not api_key:
        raise ValueError("Gemini API key required (set --api-key or GEMINI_API_KEY)")
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_gemini_text_embedder(
            db,
            api_key=api_key,
            model=args.model or DEFAULT_GEMINI_EMBEDDING_MODEL,
            source=args.source,
            limit=args.limit,
            force=args.force,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_similar(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY") or ""
    if not api_key:
        raise ValueError("Gemini API key required (set --api-key or GEMINI_API_KEY)")
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_similarity_search(
            db,
            api_key=api_key,
            query=args.query,
            model=args.model or DEFAULT_GEMINI_EMBEDDING_MODEL,
            source=args.source,
            limit=args.limit,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    app_dir = _p(args.app)
    store_dir = _p(args.store)
    if args.reload:
        from .devserver import run_with_reload

        run_with_reload(host=args.host, port=args.port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
        return 0
    run_server(host=args.host, port=args.port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inspirations", description="Inspiration library utilities")
    p.set_defaults(func=lambda _: p.print_help() or 2)

    p.add_argument("--db", default="data/inspirations.sqlite", help="SQLite db path")
    p.add_argument("--store", default="store", help="Directory for downloaded originals/thumbnails")

    sub = p.add_subparsers(dest="cmd")

    init_p = sub.add_parser("init", help="Initialize database and store directory")
    init_p.set_defaults(func=cmd_init)

    list_p = sub.add_parser("list", help="Show counts")
    list_p.set_defaults(func=cmd_list)

    imp = sub.add_parser("import", help="Import from exports")
    imp_sub = imp.add_subparsers(dest="import_cmd")

    pin = imp_sub.add_parser("pinterest", help="Import Pinterest crawler export ZIP")
    pin.add_argument("--zip", required=True, help="Path to dataset_pinterest-crawler_*.zip")
    pin.add_argument("--limit", type=int, default=0, help="Limit parsed records (0 = no limit)")
    pin.add_argument("--download", action="store_true", help="Download originals after import")
    pin.add_argument("--download-limit", type=int, default=0, help="Limit downloads (0 = no limit)")
    pin.set_defaults(func=cmd_import_pinterest)

    fb = imp_sub.add_parser("facebook", help="Import Facebook saved items export ZIP")
    fb.add_argument("--zip", required=True, help="Path to facebook-*.zip")
    fb.add_argument("--limit", type=int, default=0, help="Limit parsed records (0 = no limit)")
    fb.add_argument("--download", action="store_true", help="Download originals after import")
    fb.add_argument("--download-limit", type=int, default=0, help="Limit downloads (0 = no limit)")
    fb.add_argument(
        "--retry-non-image",
        action="store_true",
        help="Retry downloads for items that previously saved as .bin (non-image)",
    )
    fb.set_defaults(func=cmd_import_facebook)

    sc = imp_sub.add_parser("scans", help="Import scans from an inbox folder")
    sc.add_argument("--inbox", required=True, help="Path to scans inbox folder")
    sc.add_argument("--format", default="jpg", help="Page image format: jpg or png")
    sc.add_argument("--renderer", default="auto", help="PDF renderer: auto | pdftoppm | mutool")
    sc.add_argument("--max-pages", type=int, default=0, help="Max pages per PDF (0 = all)")
    sc.add_argument("--limit", type=int, default=0, help="Limit files (0 = no limit)")
    sc.set_defaults(func=cmd_import_scans)

    thumbs = sub.add_parser("thumbs", help="Generate thumbnails from stored originals/pages")
    thumbs.add_argument("--size", type=int, default=512, help="Max dimension in pixels")
    thumbs.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    thumbs.add_argument("--source", default="", help="Only generate for a source (pinterest/facebook/scan)")
    thumbs.add_argument("--tool", default="auto", help="Tool: auto | sips | magick")
    thumbs.set_defaults(func=cmd_thumbs)

    ai = sub.add_parser("ai", help="AI utilities")
    ai_sub = ai.add_subparsers(dest="ai_cmd")
    tag = ai_sub.add_parser("tag", help="Run AI tagging")
    tag.add_argument("--provider", default="mock", help="Provider: mock | gemini")
    tag.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    tag.add_argument("--source", default="", help="Only tag a source (pinterest/facebook/scan)")
    tag.add_argument("--model", default="", help="Gemini model name (default gemini-2.5-flash)")
    tag.add_argument(
        "--recitation-fallback-model",
        default="",
        help="Fallback model when primary returns finishReason=RECITATION (default gemini-2.0-flash)",
    )
    tag.add_argument("--api-key", default="", help="Gemini API key (or set GEMINI_API_KEY)")
    tag.add_argument(
        "--image-kind",
        default="thumb",
        choices=["thumb", "original"],
        help="Tag from thumbnails or originals",
    )
    tag.add_argument("--force", action="store_true", help="Retag even if already tagged")
    tag.add_argument(
        "--preflight",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preflight checks (download missing originals + generate thumbs)",
    )
    tag.set_defaults(func=cmd_ai_tag)

    errors = ai_sub.add_parser("errors", help="Triage AI error rows")
    errors.add_argument("--source", default="", help="Only include one source (pinterest/facebook/scan)")
    errors.add_argument("--provider", default="gemini", help="Filter provider (default gemini)")
    errors.add_argument("--model", default="", help="Optional exact model filter")
    errors.add_argument("--days", type=int, default=0, help="Only include errors from last N days (0 = all)")
    errors.add_argument("--limit", type=int, default=0, help="Limit rows processed (0 = all)")
    errors.add_argument(
        "--examples-per-action",
        type=int,
        default=3,
        help="Number of example rows to include per triage action",
    )
    errors.set_defaults(func=cmd_ai_errors)

    embed = ai_sub.add_parser("embed", help="Generate Gemini text embeddings for assets")
    embed.add_argument("--provider", default="gemini", help="Provider: gemini")
    embed.add_argument("--model", default=DEFAULT_GEMINI_EMBEDDING_MODEL, help="Embedding model")
    embed.add_argument("--source", default="", help="Only embed one source (pinterest/facebook/scan)")
    embed.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    embed.add_argument("--force", action="store_true", help="Re-embed even if embedding already exists")
    embed.add_argument("--api-key", default="", help="Gemini API key (or set GEMINI_API_KEY)")
    embed.set_defaults(func=cmd_ai_embed)

    similar = ai_sub.add_parser("similar", help="Run similarity search against stored embeddings")
    similar.add_argument("--query", required=True, help="Natural-language query text")
    similar.add_argument("--source", default="", help="Optional source filter")
    similar.add_argument("--limit", type=int, default=25, help="Top results to return")
    similar.add_argument("--model", default=DEFAULT_GEMINI_EMBEDDING_MODEL, help="Embedding model")
    similar.add_argument("--api-key", default="", help="Gemini API key (or set GEMINI_API_KEY)")
    similar.set_defaults(func=cmd_ai_similar)

    serve = sub.add_parser("serve", help="Run local web app")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="Port")
    serve.add_argument("--app", default="app", help="App directory (static files)")
    serve.add_argument("--store", default="store", help="Store directory (originals/thumbs)")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on file changes")
    serve.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
