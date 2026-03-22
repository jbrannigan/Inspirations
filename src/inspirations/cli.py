from __future__ import annotations

import argparse
import json
from pathlib import Path

import shutil
import sys
from datetime import datetime

from .db import Db, ensure_schema
from .importers.scans import audit_scan_separator_pages, import_scans_inbox, repair_scan_document_grouping
from .importers.pinterest_scrape import import_pinterest_scrape
from .importers.facebook_scrape import import_facebook_scrape
from .importers.houzz import import_houzz_ideabook
from .thumbnails import generate_thumbnails
from .ai import (
    DEFAULT_GEMINI_EMBEDDING_MODEL,
    apply_reel_recommendations,
    download_facebook_reels,
    get_gemini_api_key,
    run_ai_error_triage,
    run_ai_labeler,
    run_gemini_text_embedder,
    run_gemini_video_labeler,
    run_similarity_search,
)
from .catalog import generate_catalog
from .classification_v2 import run_multi_axis_inference_v2, run_track_gate_v2
from .curation import (
    DEFAULT_GEMINI_MODEL as DEFAULT_CURATION_GEMINI_MODEL,
    DEFAULT_GEMINI_RECITATION_FALLBACK_MODEL as DEFAULT_CURATION_GEMINI_RECITATION_FALLBACK_MODEL,
    render_curation_html,
    run_curation_pipeline,
)
from .export import export_html_gallery, export_static_share_portal
from .server import run_server
from .source_link_enrichment import default_auth_browser_profile_dir, run_source_link_enrichment
from .source_link_qc import run_source_link_qc
from .store import create_collection, add_items_to_collection
from .storage import backfill_previews_from_source_ref
from .title_audit import (
    apply_title_audit_batch,
    edit_title_audit_candidate,
    mark_title_audit_candidates,
    review_title_audit_batch,
    run_title_audit,
    stage_title_audit_batch,
    undo_title_audit_batch,
)


def _p(p: str) -> Path:
    return Path(p).expanduser().resolve()


def _csv_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        for part in str(raw or "").split(","):
            value = part.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
    return out


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


def cmd_import_pinterest_scrape(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    json_path = _p(args.json)
    image_map_path = _p(args.image_map) if args.image_map else None

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_pinterest_scrape(
            db=db,
            json_path=json_path,
            store_dir=store_dir,
            image_map_path=image_map_path,
            download_missing=not args.no_download,
            limit=args.limit,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_import_facebook_scrape(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    json_dir = _p(args.json_dir)

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_facebook_scrape(
            db=db,
            json_dir=json_dir,
            store_dir=store_dir,
            limit=args.limit,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_import_houzz(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    json_path = _p(args.json)

    with Db(db_path) as db:
        ensure_schema(db)
        report = import_houzz_ideabook(
            db=db,
            json_path=json_path,
            store_dir=store_dir,
            download_images=not args.no_download,
            limit=args.limit,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_rebuild_db(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)

    # Step 1: Backup current DB
    if db_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"pre-rebuild-{ts}.sqlite"
        shutil.copy2(db_path, backup_path)
        print(f"[rebuild-db] Backed up DB → {backup_path}", file=sys.stderr)
        db_path.unlink()
        print("[rebuild-db] Deleted old DB", file=sys.stderr)

    # Step 2: Create fresh schema
    with Db(db_path) as db:
        ensure_schema(db)
    print("[rebuild-db] Fresh schema created", file=sys.stderr)

    summary: dict = {}

    # Step 3: Scan import
    if args.scan_inbox:
        inbox = _p(args.scan_inbox)
        print(f"[rebuild-db] Importing scans from {inbox}", file=sys.stderr)
        with Db(db_path) as db:
            ensure_schema(db)
            r = import_scans_inbox(db, inbox_dir=inbox, store_dir=store_dir)
        summary["scans"] = r

    # Step 4: Pinterest scrape import
    if args.pinterest_json:
        pj = _p(args.pinterest_json)
        image_map = _p(args.pinterest_image_map) if args.pinterest_image_map else None
        print(f"[rebuild-db] Importing Pinterest from {pj}", file=sys.stderr)
        with Db(db_path) as db:
            ensure_schema(db)
            r = import_pinterest_scrape(db=db, json_path=pj, store_dir=store_dir, image_map_path=image_map)
        summary["pinterest"] = r

    # Step 5: Facebook scrape import
    if args.facebook_json_dir:
        fj = _p(args.facebook_json_dir)
        print(f"[rebuild-db] Importing Facebook from {fj}", file=sys.stderr)
        with Db(db_path) as db:
            ensure_schema(db)
            r = import_facebook_scrape(db=db, json_dir=fj, store_dir=store_dir)
        summary["facebook"] = r

    # Step 6: Generate thumbnails
    print("[rebuild-db] Generating thumbnails", file=sys.stderr)
    with Db(db_path) as db:
        ensure_schema(db)
        r = generate_thumbnails(db, store_dir=store_dir)
    summary["thumbnails"] = r

    # Step 7: Create collections from boards
    print("[rebuild-db] Creating collections from boards", file=sys.stderr)
    with Db(db_path) as db:
        ensure_schema(db)
        boards = db.query(
            "select distinct board from assets where board is not null and board != '' order by board"
        )
        collections_created = 0
        collection_items_total = 0
        for row in boards:
            board_name = row["board"]
            col = create_collection(db, name=board_name)
            asset_rows = db.query("select id from assets where board = ?", (board_name,))
            asset_ids = [r["id"] for r in asset_rows]
            n = add_items_to_collection(db, collection_id=col["id"], asset_ids=asset_ids)
            collections_created += 1
            collection_items_total += n
        print(f"[rebuild-db] Created {collections_created} collections, {collection_items_total} items linked", file=sys.stderr)
    summary["collections"] = {"created": collections_created, "items": collection_items_total}

    # Step 8: Null out bad Facebook images (SHA256 appearing on 5+ assets = wrong capture)
    print("[rebuild-db] Checking for duplicate Facebook images", file=sys.stderr)
    with Db(db_path) as db:
        ensure_schema(db)
        bad_rows = db.query(
            """
            select sha256, count(*) as cnt
            from assets
            where source = 'facebook' and sha256 is not null and sha256 != ''
            group by sha256
            having count(*) >= 5
            """
        )
        nulled = 0
        for row in bad_rows:
            db.exec(
                "update assets set stored_path = null, thumb_path = null where source = 'facebook' and sha256 = ?",
                (row["sha256"],),
            )
            nulled += row["cnt"]
        if nulled:
            print(f"[rebuild-db] Nulled stored_path/thumb_path for {nulled} bad Facebook images", file=sys.stderr)
    summary["bad_facebook_images_nulled"] = nulled

    # Step 9: Dedup Facebook assets by SHA256 — keep the best version per SHA256
    print("[rebuild-db] Deduplicating Facebook assets by SHA256", file=sys.stderr)
    with Db(db_path) as db:
        ensure_schema(db)
        dupe_groups = db.query(
            """
            select sha256, count(*) as cnt
            from assets
            where source = 'facebook' and sha256 is not null and sha256 != ''
            group by sha256
            having count(*) >= 2
            """
        )
        total_removed = 0
        for group in dupe_groups:
            sha = group["sha256"]
            rows = db.query(
                """
                select id, title, post_text, board, image_url, hashtags, creator_name
                from assets
                where source = 'facebook' and sha256 = ?
                order by
                    (case when title is not null and title != '' then 1 else 0 end)
                    + (case when post_text is not null and post_text != '' then 1 else 0 end)
                    + (case when board is not null and board != '' then 1 else 0 end)
                    + (case when image_url is not null and image_url != '' then 1 else 0 end)
                    + (case when hashtags is not null and hashtags != '' then 1 else 0 end)
                    + (case when creator_name is not null and creator_name != '' then 1 else 0 end)
                  desc,
                  id asc
                """,
                (sha,),
            )
            if len(rows) <= 1:
                continue
            # rows[0] is the keeper (most metadata); delete the rest
            remove_ids = [r["id"] for r in rows[1:]]
            placeholders = ",".join(["?"] * len(remove_ids))
            db.exec(f"delete from collection_items where asset_id in ({placeholders})", tuple(remove_ids))
            db.exec(f"delete from tray_items where asset_id in ({placeholders})", tuple(remove_ids))
            db.exec(f"delete from annotations where asset_id in ({placeholders})", tuple(remove_ids))
            db.exec(f"delete from assets where id in ({placeholders})", tuple(remove_ids))
            total_removed += len(remove_ids)
        if total_removed:
            print(f"[rebuild-db] Removed {total_removed} duplicate Facebook assets", file=sys.stderr)
    summary["facebook_deduped"] = total_removed

    print(json.dumps(summary, indent=2))
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


def cmd_audit_scan_separators(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    with Db(db_path) as db:
        ensure_schema(db)
        report = audit_scan_separator_pages(
            db,
            store_dir=store_dir,
            renderer=args.renderer,
            max_pages=args.max_pages,
            limit=args.limit,
            pdf_sha256s=args.pdf_sha,
            apply=args.apply,
            actor=args.actor,
            note=args.note,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_repair_scan_grouping(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    with Db(db_path) as db:
        ensure_schema(db)
        report = repair_scan_document_grouping(
            db,
            store_dir=store_dir,
            pdf_sha256=args.pdf_sha,
            renderer=args.renderer,
            max_pages=args.max_pages,
            apply=args.apply,
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


def cmd_backfill_previews(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    store_dir = _p(args.store)
    with Db(db_path) as db:
        ensure_schema(db)
        report = backfill_previews_from_source_ref(
            db,
            store_dir=store_dir,
            source=args.source,
            media_status=args.media_status,
            include_hidden=args.include_hidden,
            limit=args.limit,
            force=args.force,
            dry_run=args.dry_run,
            regenerate_thumbs=args.regenerate_thumbs,
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
    api_key = get_gemini_api_key(args.api_key)
    if not api_key:
        raise ValueError(
            "Gemini API key required (set --api-key, GEMINI_API_KEY, "
            "or macOS Keychain service inspirations_gemini_api_key)"
        )
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
    api_key = get_gemini_api_key(args.api_key)
    if not api_key:
        raise ValueError(
            "Gemini API key required (set --api-key, GEMINI_API_KEY, "
            "or macOS Keychain service inspirations_gemini_api_key)"
        )
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
            semantic_weight=args.semantic_weight,
            lexical_weight=args.lexical_weight,
            min_score=args.min_score,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    table_out = _p(args.table_out) if args.table_out else None
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_title_audit(
            db,
            source=args.source,
            include_hidden=bool(args.include_hidden),
            limit=int(args.limit or 0),
            table_out=table_out,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit_stage(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    table_out = _p(args.table_out) if args.table_out else None
    with Db(db_path) as db:
        ensure_schema(db)
        report = stage_title_audit_batch(
            db,
            source=args.source,
            include_hidden=bool(args.include_hidden),
            limit=int(args.limit or 0),
            actor=args.actor,
            notes=args.notes,
            table_out=table_out,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit_review(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    table_out = _p(args.table_out) if args.table_out else None
    with Db(db_path) as db:
        ensure_schema(db)
        report = review_title_audit_batch(
            db,
            batch_id=args.batch_id,
            status=args.status,
            limit=int(args.limit or 0),
            offset=int(args.offset or 0),
            table_out=table_out,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit_mark(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    asset_ids = _csv_unique(list(args.asset_id or []))
    with Db(db_path) as db:
        ensure_schema(db)
        report = mark_title_audit_candidates(
            db,
            batch_id=args.batch_id,
            status=args.status,
            asset_ids=asset_ids,
            mark_all=bool(args.all),
            where_status=args.where_status,
            note=args.note,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit_edit(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = edit_title_audit_candidate(
            db,
            batch_id=args.batch_id,
            asset_id=args.asset_id,
            new_title=args.new_title,
            note=args.note,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit_apply(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = apply_title_audit_batch(
            db,
            batch_id=args.batch_id,
            dry_run=bool(args.dry_run),
            force=bool(args.force),
            limit=int(args.limit or 0),
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_title_audit_undo(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = undo_title_audit_batch(
            db,
            batch_id=args.batch_id,
            dry_run=bool(args.dry_run),
            force=bool(args.force),
            limit=int(args.limit or 0),
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_ai_reels(args: argparse.Namespace) -> int:
    """Download, analyze, and apply recommendations for Facebook reels."""
    db_path = _p(args.db)
    store_dir = _p(args.store)
    api_key = get_gemini_api_key(args.api_key)
    do_download = not args.analyze_only and not args.apply_only
    do_analyze = not args.download_only and not args.apply_only
    do_apply = not args.download_only and not args.analyze_only

    with Db(db_path) as db:
        ensure_schema(db)

        if do_download:
            print("=== Phase 1: Downloading reels via yt-dlp ===")
            dl_report = download_facebook_reels(
                db,
                store_dir,
                limit=args.limit,
                force=args.force,
            )
            print(json.dumps(dl_report, indent=2))
            print()

        if do_analyze:
            if not api_key:
                raise ValueError(
                    "Gemini API key required for analysis (set --api-key, GEMINI_API_KEY, "
                    "or macOS Keychain service inspirations_gemini_api_key)"
                )
            print("=== Phase 2: Analyzing reels with Gemini ===")
            analyze_report = run_gemini_video_labeler(
                db,
                api_key=api_key,
                model=args.model or "gemini-2.5-flash",
                limit=args.limit,
                force=args.force,
                store_dir=store_dir,
            )
            print(json.dumps(analyze_report, indent=2))
            print()

        if do_apply:
            print("=== Phase 3: Applying recommendations ===")
            apply_report = apply_reel_recommendations(
                db,
                dry_run=args.dry_run,
            )
            print(json.dumps(apply_report, indent=2))

    return 0


def cmd_catalog_generate(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    catalog_dir = _p(args.out)
    with Db(db_path) as db:
        ensure_schema(db)
        report = generate_catalog(db, catalog_dir)
    print(json.dumps(report, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    app_dir = _p(args.app)
    store_dir = _p(args.store)
    reload_mode = bool(args.reload or getattr(args, "dev", False))
    if reload_mode:
        from .devserver import run_with_reload

        run_with_reload(host=args.host, port=args.port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
        return 0
    run_server(host=args.host, port=args.port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
    return 0


def cmd_export_html(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    out_path = _p(args.out)
    with Db(db_path) as db:
        ensure_schema(db)
        report = export_html_gallery(
            db,
            out_path=out_path,
            source=args.source,
            collection_id=args.collection_id,
            limit=args.limit,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_export_portal(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    out_path = _p(args.out)
    collection_ids = _csv_unique(list(args.collection_ids or []))
    with Db(db_path) as db:
        ensure_schema(db)
        report = export_static_share_portal(
            db,
            out_path=out_path,
            source=args.source,
            collection_ids=collection_ids,
            include_unassigned=args.include_unassigned,
            limit=args.limit,
            title=args.title,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_curation_run(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    out_dir = _p(args.out_dir)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_curation_pipeline(
            db,
            out_dir=out_dir,
            triage_status=args.triage_status,
            source=args.source,
            limit=args.limit,
            provider=args.provider,
            summary_provider=args.summary_provider,
            model=args.model,
            recitation_fallback_model=args.recitation_fallback_model,
            api_key=args.api_key,
            batch_size=args.batch_size,
            timeout_s=float(args.timeout),
            summarize=bool(args.summarize),
            summary_sample_size=args.summary_sample_size,
            style_ranking_mode=args.style_ranking_mode,
            best_of_min_rating=args.best_of_min_rating,
            best_of_max_total=args.best_of_max_total,
            best_of_max_per_room=args.best_of_max_per_room,
            best_of_target_per_room=args.best_of_target_per_room,
            best_of_tie_max_per_room=args.best_of_tie_max_per_room,
            best_of_backfill_if_short=bool(args.best_of_backfill_if_short),
            best_of_show_all_if_under_target=bool(args.best_of_show_all_if_under_target),
            pairwise_votes_path=args.pairwise_votes_path,
            pairwise_max_candidates_per_room=args.pairwise_max_candidates_per_room,
            pairwise_rounds_per_room=args.pairwise_rounds_per_room,
            pairwise_max_pairs_per_room=args.pairwise_max_pairs_per_room,
            pairwise_elo_k=float(args.pairwise_elo_k),
            render_html=bool(args.render_html),
            media_base=args.media_base,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_curation_render_html(args: argparse.Namespace) -> int:
    report = render_curation_html(
        out_dir=_p(args.out_dir),
        media_base=args.media_base,
        db_path=_p(args.db),
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_curation_track_gate_v2(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_track_gate_v2(
            db,
            triage_status=args.triage_status,
            source=args.source,
            limit=args.limit,
            notes=args.notes,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_curation_axis_infer_v2(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_multi_axis_inference_v2(
            db,
            track_run_id=args.track_run_id,
            limit=args.limit,
            notes=args.notes,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_curation_enrich_source_links_v2(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    profile_dir_arg = str(getattr(args, "browser_profile_dir", "") or "").strip()
    browser_profile_dir = Path(profile_dir_arg).expanduser() if profile_dir_arg else default_auth_browser_profile_dir()
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_source_link_enrichment(
            db,
            track_run_id=args.track_run_id,
            only_ambiguous=bool(args.only_ambiguous),
            source=args.source,
            collection_id=args.collection_id,
            limit=args.limit,
            offset=int(args.offset),
            notes=args.notes,
            timeout_s=float(args.timeout_s),
            max_bytes=int(args.max_bytes),
            max_redirects=int(args.max_redirects),
            allow_http=bool(args.allow_http),
            include_platform_hosts=bool(args.include_platform_hosts),
            browser_platform_hosts=bool(args.browser_platform_hosts),
            promote_best_source_url=bool(args.promote_best_source_url),
            store_dir=_p(args.store),
            promote_hero_image=bool(args.promote_hero_image),
            progress_every=int(args.progress_every),
            browser_profile_dir=browser_profile_dir,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_curation_source_link_qc_v2(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        report = run_source_link_qc(
            db,
            track_run_id=args.track_run_id,
            source=args.source,
            limit=args.limit,
            notes=args.notes,
        )
    print(json.dumps(report, indent=2))
    return 0


def cmd_promote_boards(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)
        boards = db.query(
            "select distinct board from assets where board is not null and board != '' order by board"
        )
        created = 0
        skipped = 0
        total_items = 0
        for row in boards:
            board_name = row["board"]
            collection_name = f"pins: {board_name}"
            existing = db.query("select id from collections where name = ?", (collection_name,))
            if existing:
                skipped += 1
                continue
            col = create_collection(db, name=collection_name)
            cid = col["id"]
            asset_rows = db.query("select id from assets where board = ?", (board_name,))
            asset_ids = [r["id"] for r in asset_rows]
            n = add_items_to_collection(db, collection_id=cid, asset_ids=asset_ids)
            created += 1
            total_items += n
            print(f"  Created '{collection_name}' with {n} items")
    print(f"\nDone. Created {created} collections, skipped {skipped} existing, {total_items} total items linked.")
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

    pin_sc = imp_sub.add_parser("pinterest-scrape", help="Import Pinterest from browser scrape JSON")
    pin_sc.add_argument("--json", required=True, help="Path to pinterest_scrape.json")
    pin_sc.add_argument("--image-map", default="", help="Path to pinterest_image_map.json (optional)")
    pin_sc.add_argument("--no-download", action="store_true", help="Skip downloading missing images")
    pin_sc.add_argument("--limit", type=int, default=0, help="Limit pins (0 = no limit)")
    pin_sc.set_defaults(func=cmd_import_pinterest_scrape)

    fb_sc = imp_sub.add_parser("facebook-scrape", help="Import Facebook from browser scrape JSON")
    fb_sc.add_argument("--json-dir", required=True, help="Directory containing facebook_scrape_*.json files")
    fb_sc.add_argument("--limit", type=int, default=0, help="Limit posts (0 = no limit)")
    fb_sc.set_defaults(func=cmd_import_facebook_scrape)

    hz = imp_sub.add_parser("houzz", help="Import Houzz ideabook from scraped JSON")
    hz.add_argument("--json", required=True, help="Path to houzz_ideabook_final.json")
    hz.add_argument("--no-download", action="store_true", help="Skip downloading images from Houzz CDN")
    hz.add_argument("--limit", type=int, default=0, help="Limit items (0 = no limit)")
    hz.set_defaults(func=cmd_import_houzz)

    sc = imp_sub.add_parser("scans", help="Import scans from an inbox folder")
    sc.add_argument("--inbox", required=True, help="Path to scans inbox folder")
    sc.add_argument("--format", default="jpg", help="Page image format: jpg or png")
    sc.add_argument("--renderer", default="auto", help="PDF renderer: auto | pdftoppm | mutool")
    sc.add_argument("--max-pages", type=int, default=0, help="Max pages per PDF (0 = all)")
    sc.add_argument("--limit", type=int, default=0, help="Limit files (0 = no limit)")
    sc.set_defaults(func=cmd_import_scans)

    scan_sep = sub.add_parser(
        "audit-scan-separators",
        help="Audit stored scan PDFs for likely blank separator pages and optionally apply irrelevant overrides",
    )
    scan_sep.add_argument("--renderer", default="auto", help="PDF renderer: auto | pdftoppm | mutool")
    scan_sep.add_argument("--max-pages", type=int, default=0, help="Max pages per PDF (0 = all)")
    scan_sep.add_argument("--limit", type=int, default=0, help="Limit PDFs scanned (0 = all)")
    scan_sep.add_argument(
        "--pdf-sha",
        action="append",
        default=[],
        help="Only audit one specific stored scan PDF SHA-256 (repeatable)",
    )
    scan_sep.add_argument("--apply", action="store_true", help="Apply irrelevant track overrides to detected separator pages")
    scan_sep.add_argument("--actor", default="scan_separator_audit", help="Actor name recorded on applied overrides")
    scan_sep.add_argument(
        "--note",
        default="auto-detected blank/separator scan page",
        help="Note recorded on applied overrides",
    )
    scan_sep.set_defaults(func=cmd_audit_scan_separators)

    scan_repair = sub.add_parser(
        "repair-scan-grouping",
        help="Repair logical scan document grouping for one stored scan PDF by rewriting page titles",
    )
    scan_repair.add_argument("--pdf-sha", required=True, help="Stored scan PDF SHA-256 to regroup")
    scan_repair.add_argument("--renderer", default="auto", help="PDF renderer: auto | pdftoppm | mutool")
    scan_repair.add_argument("--max-pages", type=int, default=0, help="Max pages inspected (0 = all)")
    scan_repair.add_argument("--apply", action="store_true", help="Apply regrouped titles to the DB")
    scan_repair.set_defaults(func=cmd_repair_scan_grouping)


    thumbs = sub.add_parser("thumbs", help="Generate thumbnails from stored originals/pages")
    thumbs.add_argument("--size", type=int, default=512, help="Max dimension in pixels")
    thumbs.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    thumbs.add_argument("--source", default="", help="Only generate for a source (pinterest/facebook/scan)")
    thumbs.add_argument("--tool", default="auto", help="Tool: auto | sips | magick")
    thumbs.set_defaults(func=cmd_thumbs)

    backfill = sub.add_parser(
        "backfill-previews",
        help="Resolve source_ref URLs to real images and regenerate thumbnails",
    )
    backfill.add_argument("--source", default="facebook", help="Asset source to process (default facebook)")
    backfill.add_argument(
        "--media-status",
        default="placeholder",
        help="Only process this media_status (default placeholder, pass empty for all)",
    )
    backfill.add_argument("--include-hidden", action="store_true", help="Include hidden assets")
    backfill.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    backfill.add_argument(
        "--force",
        action="store_true",
        help="Redownload even when resolved URL matches current image_url",
    )
    backfill.add_argument("--dry-run", action="store_true", help="Resolve only; do not write files or DB")
    backfill.add_argument(
        "--regenerate-thumbs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Regenerate thumbnails for updated items (default true)",
    )
    backfill.set_defaults(func=cmd_backfill_previews)

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

    reels = ai_sub.add_parser("reels", help="Download, analyze, and classify Facebook reels")
    reels.add_argument("--limit", type=int, default=0, help="Limit reels (0 = no limit)")
    reels.add_argument("--download-only", action="store_true", help="Only download, don't analyze or apply")
    reels.add_argument("--analyze-only", action="store_true", help="Only analyze downloaded reels, don't download or apply")
    reels.add_argument("--apply-only", action="store_true", help="Only apply existing analysis results")
    reels.add_argument("--force", action="store_true", help="Re-process even if already done")
    reels.add_argument("--dry-run", action="store_true", help="Show what would be applied without making changes")
    reels.add_argument("--model", default="", help="Gemini model (default gemini-2.5-flash)")
    reels.add_argument("--api-key", default="", help="Gemini API key (or set GEMINI_API_KEY)")
    reels.set_defaults(func=cmd_ai_reels)

    similar = ai_sub.add_parser("similar", help="Run similarity search against stored embeddings")
    similar.add_argument("--query", required=True, help="Natural-language query text")
    similar.add_argument("--source", default="", help="Optional source filter")
    similar.add_argument("--limit", type=int, default=25, help="Top results to return")
    similar.add_argument("--model", default=DEFAULT_GEMINI_EMBEDDING_MODEL, help="Embedding model")
    similar.add_argument("--semantic-weight", type=float, default=0.85, help="Weight for cosine similarity")
    similar.add_argument("--lexical-weight", type=float, default=0.15, help="Weight for lexical overlap")
    similar.add_argument("--min-score", type=float, default=0.0, help="Discard results below this blended score")
    similar.add_argument("--api-key", default="", help="Gemini API key (or set GEMINI_API_KEY)")
    similar.set_defaults(func=cmd_ai_similar)

    title_audit = ai_sub.add_parser("title-audit", help="Generate candidate title replacements (dry-run)")
    title_audit.add_argument("--source", default="", help="Optional source filter")
    title_audit.add_argument(
        "--include-hidden",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include hidden assets (default true)",
    )
    title_audit.add_argument("--limit", type=int, default=0, help="Limit assets scanned (0 = no limit)")
    title_audit.add_argument(
        "--table-out",
        default="",
        help="Optional markdown output path for impact table",
    )
    title_audit.set_defaults(func=cmd_ai_title_audit)

    title_audit_stage = ai_sub.add_parser("title-audit-stage", help="Stage title-audit candidates into a review batch")
    title_audit_stage.add_argument("--source", default="", help="Optional source filter")
    title_audit_stage.add_argument(
        "--include-hidden",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include hidden assets while staging (default true)",
    )
    title_audit_stage.add_argument("--limit", type=int, default=0, help="Limit assets scanned (0 = no limit)")
    title_audit_stage.add_argument("--actor", default="cli", help="Who staged this batch")
    title_audit_stage.add_argument("--notes", default="", help="Optional notes")
    title_audit_stage.add_argument("--table-out", default="", help="Optional markdown table path")
    title_audit_stage.set_defaults(func=cmd_ai_title_audit_stage)

    title_audit_review = ai_sub.add_parser("title-audit-review", help="Review a staged title-audit batch")
    title_audit_review.add_argument("--batch-id", required=True, help="Batch id from title-audit-stage output")
    title_audit_review.add_argument(
        "--status",
        default="",
        help="Optional filter: pending|approved|rejected|edited|ready|applied",
    )
    title_audit_review.add_argument("--limit", type=int, default=100, help="Rows to return (default 100)")
    title_audit_review.add_argument("--offset", type=int, default=0, help="Row offset (default 0)")
    title_audit_review.add_argument("--table-out", default="", help="Optional markdown table path")
    title_audit_review.set_defaults(func=cmd_ai_title_audit_review)

    title_audit_mark = ai_sub.add_parser("title-audit-mark", help="Set review status for staged candidates")
    title_audit_mark.add_argument("--batch-id", required=True, help="Batch id")
    title_audit_mark.add_argument(
        "--status",
        required=True,
        choices=["pending", "approved", "rejected"],
        help="Target review status",
    )
    title_audit_mark.add_argument(
        "--asset-id",
        action="append",
        default=[],
        help="Asset id to update (repeat or pass comma-separated ids)",
    )
    title_audit_mark.add_argument("--all", action="store_true", help="Apply to all rows in batch (or filtered subset)")
    title_audit_mark.add_argument(
        "--where-status",
        default="",
        help="When using --all, optional filter: pending|approved|rejected|edited|ready",
    )
    title_audit_mark.add_argument("--note", default="", help="Optional review note")
    title_audit_mark.set_defaults(func=cmd_ai_title_audit_mark)

    title_audit_edit = ai_sub.add_parser("title-audit-edit", help="Edit a staged candidate title and mark as edited")
    title_audit_edit.add_argument("--batch-id", required=True, help="Batch id")
    title_audit_edit.add_argument("--asset-id", required=True, help="Asset id to edit")
    title_audit_edit.add_argument("--new-title", required=True, help="Replacement title")
    title_audit_edit.add_argument("--note", default="", help="Optional edit note")
    title_audit_edit.set_defaults(func=cmd_ai_title_audit_edit)

    title_audit_apply = ai_sub.add_parser("title-audit-apply", help="Apply approved/edited staged title changes")
    title_audit_apply.add_argument("--batch-id", required=True, help="Batch id")
    title_audit_apply.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    title_audit_apply.add_argument("--force", action="store_true", help="Apply even when live title drifted from old title")
    title_audit_apply.add_argument("--limit", type=int, default=0, help="Limit rows applied (0 = no limit)")
    title_audit_apply.set_defaults(func=cmd_ai_title_audit_apply)

    title_audit_undo = ai_sub.add_parser("title-audit-undo", help="Undo title changes applied from a staged batch")
    title_audit_undo.add_argument("--batch-id", required=True, help="Batch id")
    title_audit_undo.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    title_audit_undo.add_argument("--force", action="store_true", help="Undo even if current title drifted from applied title")
    title_audit_undo.add_argument("--limit", type=int, default=0, help="Limit rows undone (0 = no limit)")
    title_audit_undo.set_defaults(func=cmd_ai_title_audit_undo)

    rebuild = sub.add_parser("rebuild-db", help="Nuke DB and reimport from scrape data")
    rebuild.add_argument("--pinterest-json", default="", help="Path to pinterest_scrape.json")
    rebuild.add_argument("--pinterest-image-map", default="", help="Path to pinterest_image_map.json")
    rebuild.add_argument("--facebook-json-dir", default="", help="Directory with facebook_scrape_*.json")
    rebuild.add_argument("--scan-inbox", default="", help="Scan inbox directory")
    rebuild.set_defaults(func=cmd_rebuild_db)

    cat = sub.add_parser("catalog", help="Manage markdown catalog for AI chat")
    cat_sub = cat.add_subparsers(dest="catalog_cmd")
    cat_gen = cat_sub.add_parser("generate", help="Regenerate the full catalog from DB")
    cat_gen.add_argument("--out", default="data/catalog", help="Output directory (default data/catalog)")
    cat_gen.set_defaults(func=cmd_catalog_generate)

    pb = sub.add_parser("promote-boards", help="Convert boards to collections (one-time migration)")
    pb.add_argument("--db", required=True)
    pb.set_defaults(func=cmd_promote_boards)

    serve = sub.add_parser("serve", help="Run local web app")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8001, help="Port")
    serve.add_argument("--app", default="app", help="App directory (static files)")
    serve.add_argument("--store", default="store", help="Store directory (originals/thumbs)")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on file changes")
    # Backward compatibility for older local launch configs.
    serve.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)
    serve.set_defaults(func=cmd_serve)

    exp = sub.add_parser("export", help="Export artifacts")
    exp.set_defaults(func=lambda _: exp.print_help() or 2)
    exp_sub = exp.add_subparsers(dest="export_cmd")
    exp_html = exp_sub.add_parser("html", help="Export a shareable HTML gallery")
    exp_html.add_argument("--out", default="data/exports/gallery.html", help="Output .html path")
    exp_html.add_argument("--source", default="", help="Optional source filter")
    exp_html.add_argument("--collection-id", default="", help="Optional collection id filter")
    exp_html.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    exp_html.set_defaults(func=cmd_export_html)
    exp_portal = exp_sub.add_parser(
        "portal",
        help="Export a static share portal (browse-only, semantic search disabled)",
    )
    exp_portal.add_argument("--out", default="data/exports/portal.html", help="Output .html path")
    exp_portal.add_argument("--title", default="Inspirations Share Portal", help="Portal title text")
    exp_portal.add_argument("--source", default="", help="Optional source filter")
    exp_portal.add_argument(
        "--collection-id",
        action="append",
        dest="collection_ids",
        default=[],
        help="Optional collection id filter (repeat flag or pass comma-separated ids)",
    )
    exp_portal.add_argument(
        "--include-unassigned",
        action="store_true",
        help="Include assets not in a collection (default exports collection-assigned items only)",
    )
    exp_portal.add_argument("--limit", type=int, default=0, help="Limit assets (0 = no limit)")
    exp_portal.set_defaults(func=cmd_export_portal)

    curation = sub.add_parser("curation", help="AI curation pipeline")
    curation.set_defaults(func=lambda _: curation.print_help() or 2)
    curation_sub = curation.add_subparsers(dest="curation_cmd")

    curation_run = curation_sub.add_parser(
        "run",
        help="Run hybrid curation (collect -> classify -> organize -> synthesize -> export) without human overrides",
    )
    curation_run.add_argument(
        "--out-dir",
        default="data/exports/curation",
        help="Output directory for style-best-of.json, construction-concerns.json, and manifest",
    )
    curation_run.add_argument(
        "--triage-status",
        default="pending,keeper",
        help="Comma-separated triage scope (default pending,keeper)",
    )
    curation_run.add_argument("--source", default="", help="Optional source filter (comma-separated)")
    curation_run.add_argument("--limit", type=int, default=0, help="Limit candidates (0 = no limit)")
    curation_run.add_argument(
        "--provider",
        default="gemini",
        choices=["gemini", "heuristic"],
        help="Classifier provider (default gemini)",
    )
    curation_run.add_argument(
        "--summary-provider",
        default="auto",
        choices=["auto", "gemini", "heuristic"],
        help="Summary provider: auto uses classifier provider, or force gemini/heuristic",
    )
    curation_run.add_argument(
        "--model",
        default=DEFAULT_CURATION_GEMINI_MODEL,
        help=f"Gemini model (default {DEFAULT_CURATION_GEMINI_MODEL})",
    )
    curation_run.add_argument(
        "--recitation-fallback-model",
        default=DEFAULT_CURATION_GEMINI_RECITATION_FALLBACK_MODEL,
        help=(
            "Fallback model when primary returns finishReason=RECITATION "
            f"(default {DEFAULT_CURATION_GEMINI_RECITATION_FALLBACK_MODEL})"
        ),
    )
    curation_run.add_argument("--api-key", default="", help="Gemini API key (or set GEMINI_API_KEY)")
    curation_run.add_argument("--batch-size", type=int, default=24, help="Items per classification batch")
    curation_run.add_argument("--timeout", type=float, default=90.0, help="Per-request timeout (seconds)")
    curation_run.add_argument(
        "--summarize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate group summaries (default true)",
    )
    curation_run.add_argument(
        "--summary-sample-size",
        type=int,
        default=60,
        help="Max items sampled per room/concern summary prompt",
    )
    curation_run.add_argument(
        "--style-ranking-mode",
        default="stars",
        choices=["stars", "pairwise"],
        help="Style ranking mode: stars (default) or pairwise",
    )
    curation_run.add_argument(
        "--best-of-min-rating",
        type=int,
        default=4,
        help="Minimum star rating considered for initial Best Of candidates (default 4)",
    )
    curation_run.add_argument(
        "--best-of-max-total",
        type=int,
        default=0,
        help="Cap Best Of item count globally (0 = no cap; use 10 for top-10)",
    )
    curation_run.add_argument(
        "--best-of-max-per-room",
        type=int,
        default=0,
        help="Cap Best Of items per room (0 = no per-room cap)",
    )
    curation_run.add_argument(
        "--best-of-target-per-room",
        type=int,
        default=0,
        help="Select top N items for every style room/category (0 = disabled)",
    )
    curation_run.add_argument(
        "--best-of-tie-max-per-room",
        type=int,
        default=0,
        help=(
            "When target-per-room is set, allow expansion up to this cap for items tied at the room cutoff "
            "(0 = no tie expansion)"
        ),
    )
    curation_run.add_argument(
        "--best-of-backfill-if-short",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If Best Of is under target, backfill with lower-rated style items (default true)",
    )
    curation_run.add_argument(
        "--best-of-show-all-if-under-target",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If total style corpus is smaller than target, include all style items in Best Of (default true)",
    )
    curation_run.add_argument(
        "--pairwise-votes-path",
        default="",
        help="Optional JSON/JSONL file with human pairwise votes for style ranking",
    )
    curation_run.add_argument(
        "--pairwise-max-candidates-per-room",
        type=int,
        default=60,
        help="Maximum room candidates included in pairwise ranking (0 = all)",
    )
    curation_run.add_argument(
        "--pairwise-rounds-per-room",
        type=int,
        default=5,
        help="Pairwise comparison rounds per room (higher = more comparisons)",
    )
    curation_run.add_argument(
        "--pairwise-max-pairs-per-room",
        type=int,
        default=200,
        help="Hard cap on pairwise comparisons per room (0 = no cap)",
    )
    curation_run.add_argument(
        "--pairwise-elo-k",
        type=float,
        default=24.0,
        help="Elo K-factor used for pairwise ranking updates (default 24.0)",
    )
    curation_run.add_argument(
        "--render-html",
        action="store_true",
        help="Also render style-best-of.html and construction-concerns.html after JSON export",
    )
    curation_run.add_argument(
        "--media-base",
        default="",
        help="Optional absolute base URL prepended to /media/... image paths in HTML (example http://localhost:8001)",
    )
    curation_run.set_defaults(func=cmd_curation_run)

    curation_track_gate_v2 = curation_sub.add_parser(
        "track-gate-v2",
        help="Run provenance-aware v2 track classification and write results into classification tables",
    )
    curation_track_gate_v2.add_argument(
        "--triage-status",
        default="pending,keeper",
        help="Comma-separated triage scope (default pending,keeper)",
    )
    curation_track_gate_v2.add_argument("--source", default="", help="Optional source filter (comma-separated)")
    curation_track_gate_v2.add_argument("--limit", type=int, default=0, help="Limit candidates (0 = no limit)")
    curation_track_gate_v2.add_argument("--notes", default="", help="Optional run notes")
    curation_track_gate_v2.set_defaults(func=cmd_curation_track_gate_v2)

    curation_axis_infer_v2 = curation_sub.add_parser(
        "axis-infer-v2",
        help="Run multi-axis v2 categorization for style and construction items from a v2 track-gate run",
    )
    curation_axis_infer_v2.add_argument(
        "--track-run-id",
        default="",
        help="Optional classification_runs.id from track-gate-v2 (defaults to latest v2 track_gate run)",
    )
    curation_axis_infer_v2.add_argument("--limit", type=int, default=0, help="Limit candidates (0 = no limit)")
    curation_axis_infer_v2.add_argument("--notes", default="", help="Optional run notes")
    curation_axis_infer_v2.set_defaults(func=cmd_curation_axis_infer_v2)

    curation_enrich_source_links_v2 = curation_sub.add_parser(
        "enrich-source-links-v2",
        help="Fetch source-page title/meta evidence for URL-backed assets and store it alongside v2 classification runs",
    )
    curation_enrich_source_links_v2.add_argument(
        "--track-run-id",
        default="",
        help="Optional classification_runs.id from track-gate-v2 (defaults to latest v2 track_gate run)",
    )
    curation_enrich_source_links_v2.add_argument(
        "--only-ambiguous",
        action="store_true",
        help="Only fetch source pages for ambiguous items from the chosen track run",
    )
    curation_enrich_source_links_v2.add_argument("--source", default="", help="Optional source filter (comma-separated)")
    curation_enrich_source_links_v2.add_argument(
        "--collection-id",
        default="",
        help="Optional collection scope; only enrich source links for assets in this collection",
    )
    curation_enrich_source_links_v2.add_argument("--limit", type=int, default=0, help="Limit candidates (0 = no limit)")
    curation_enrich_source_links_v2.add_argument("--offset", type=int, default=0, help="Skip this many candidates before fetching")
    curation_enrich_source_links_v2.add_argument("--timeout-s", type=float, default=8.0, help="Per-request timeout in seconds")
    curation_enrich_source_links_v2.add_argument("--max-bytes", type=int, default=262144, help="Maximum bytes to read per page")
    curation_enrich_source_links_v2.add_argument("--max-redirects", type=int, default=4, help="Maximum safe redirects to follow")
    curation_enrich_source_links_v2.add_argument(
        "--allow-http",
        action="store_true",
        help="Allow http:// source pages if they pass public-URL safety checks",
    )
    curation_enrich_source_links_v2.add_argument(
        "--include-platform-hosts",
        action="store_true",
        help="Also fetch pinterest.com/facebook.com wrapper pages instead of skipping them",
    )
    curation_enrich_source_links_v2.add_argument(
        "--browser-platform-hosts",
        action="store_true",
        help="For Pinterest/Facebook wrapper URLs, use a Playwright browser session to capture page title and visible text evidence",
    )
    curation_enrich_source_links_v2.add_argument(
        "--browser-profile-dir",
        default="",
        help="Optional persistent Playwright profile directory for authenticated wrapper capture (defaults to data/playwright_profiles/media_repair_auth)",
    )
    curation_enrich_source_links_v2.add_argument(
        "--promote-best-source-url",
        action="store_true",
        help="Promote a fetched non-wrapper canonical/final URL into assets.source_url when it is better than the current working link",
    )
    curation_enrich_source_links_v2.add_argument(
        "--promote-hero-image",
        action="store_true",
        help="When browser wrapper enrichment finds a likely hero image near the top of the destination page, download it into store/originals, generate a thumb, and promote it into the asset media",
    )
    curation_enrich_source_links_v2.add_argument(
        "--progress-every",
        type=int,
        default=0,
        help="Emit progress lines to stderr every N items (0 = final JSON only)",
    )
    curation_enrich_source_links_v2.add_argument("--notes", default="", help="Optional run notes")
    curation_enrich_source_links_v2.set_defaults(func=cmd_curation_enrich_source_links_v2, only_ambiguous=False)

    curation_source_link_qc_v2 = curation_sub.add_parser(
        "source-link-qc-v2",
        help="Assess whether fetched source-page evidence supports or conflicts with the current track classification",
    )
    curation_source_link_qc_v2.add_argument(
        "--track-run-id",
        default="",
        help="Optional classification_runs.id from track-gate-v2 (defaults to latest v2 track_gate run)",
    )
    curation_source_link_qc_v2.add_argument("--source", default="", help="Optional source filter (comma-separated)")
    curation_source_link_qc_v2.add_argument("--limit", type=int, default=0, help="Limit candidates (0 = no limit)")
    curation_source_link_qc_v2.add_argument("--notes", default="", help="Optional run notes")
    curation_source_link_qc_v2.set_defaults(func=cmd_curation_source_link_qc_v2)

    curation_render = curation_sub.add_parser(
        "render-html",
        help="Render HTML reports from existing curation JSON outputs",
    )
    curation_render.add_argument(
        "--out-dir",
        default="data/exports/curation",
        help="Directory containing style-best-of.json and construction-concerns.json",
    )
    curation_render.add_argument(
        "--media-base",
        default="",
        help="Optional absolute base URL prepended to /media/... image paths (example http://localhost:8001)",
    )
    curation_render.set_defaults(func=cmd_curation_render_html)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
