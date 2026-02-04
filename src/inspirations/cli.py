from __future__ import annotations

import argparse
import json
from pathlib import Path

from .db import Db, ensure_schema
from .importers.facebook_saved import import_facebook_saved_zip
from .importers.pinterest_crawler import import_pinterest_crawler_zip
from .storage import download_and_attach_originals


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
                db=db, store_dir=store_dir, source="facebook", limit=args.download_limit
            )
        report["downloaded"] = dl

    print(json.dumps(report, indent=2))
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
    fb.set_defaults(func=cmd_import_facebook)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))

