"""pokehunt command line.

    python -m pokehunt categories        discover and print the eBay category ids
    python -m pokehunt scan [--dry-run]  one scan/alert pass
    python -m pokehunt settle            capture realised prices for ended lots
    python -m pokehunt import-outcomes   backfill realised prices from a CSV
    python -m pokehunt score [--days 30] score the alerts against reality
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import Config, ConfigError
from .context import build_clients
from .ebay.taxonomy import discover_categories
from .pipeline.scan import run_scan
from .pipeline.score import build_report, render, to_json
from .pipeline.settle import import_manual_outcomes, run_settle
from .store.db import Store


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


async def cmd_categories(args: argparse.Namespace) -> int:
    config = Config.from_env()
    async with build_clients(config) as clients:
        categories = await discover_categories(
            clients.taxonomy,
            config.ebay.marketplace_id,
            cache_dir=config.cache_dir,
            force_refresh=args.refresh,
        )
    print(f"category tree: {categories.tree_id} ({categories.marketplace_id})")
    print("singles:")
    for category in categories.singles:
        print(f"  {category.category_id:<10} {' > '.join(category.path + [category.name])}")
    print("lots:")
    for category in categories.lots:
        print(f"  {category.category_id:<10} {' > '.join(category.path + [category.name])}")
    return 0


async def cmd_scan(args: argparse.Namespace) -> int:
    config = Config.from_env()
    async with build_clients(config) as clients:
        report = await run_scan(
            clients, dry_run=args.dry_run, force_category_refresh=args.refresh
        )
    print(report.render())
    return 0


async def cmd_settle(args: argparse.Namespace) -> int:
    config = Config.from_env()
    async with build_clients(config) as clients:
        report = await run_settle(clients)
    print(report.render())
    return 0


async def cmd_import_outcomes(args: argparse.Namespace) -> int:
    config = Config.from_env()
    async with build_clients(config) as clients:
        count = import_manual_outcomes(clients, Path(args.csv))
    print(f"imported {count} outcomes from {args.csv}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    # Scoring is pure SQLite; no API credentials needed.
    store = Store(Path(args.db))
    try:
        report = build_report(
            store,
            days=args.days,
            bid_fraction=args.bid_fraction,
            resale_rate=args.resale_rate,
        )
    finally:
        store.close()

    if args.json:
        print(to_json(report))
    else:
        print(render(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pokehunt", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_categories = sub.add_parser("categories", help="discover eBay Pokemon category ids")
    p_categories.add_argument("--refresh", action="store_true", help="ignore the cache")

    p_scan = sub.add_parser("scan", help="run one scan and alert pass")
    p_scan.add_argument("--dry-run", action="store_true", help="do everything except post to Discord")
    p_scan.add_argument("--refresh", action="store_true", help="refresh category discovery first")

    sub.add_parser("settle", help="poll ended alerts for their realised price")

    p_import = sub.add_parser("import-outcomes", help="backfill realised prices from CSV")
    p_import.add_argument("csv", help="CSV with columns item_id,final_price[,sold][,notes]")

    p_score = sub.add_parser("score", help="score alerts against realised prices")
    p_score.add_argument("--days", type=int, default=30)
    p_score.add_argument("--db", default="pokehunt.db")
    p_score.add_argument("--json", action="store_true")
    p_score.add_argument(
        "--bid-fraction",
        type=float,
        default=0.5,
        help="simulated bid cap as a fraction of estimated value",
    )
    p_score.add_argument(
        "--resale-rate",
        type=float,
        default=0.6,
        help="fraction of estimated value you actually net reselling singles",
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        if args.command == "score":
            return cmd_score(args)

        handlers = {
            "categories": cmd_categories,
            "scan": cmd_scan,
            "settle": cmd_settle,
            "import-outcomes": cmd_import_outcomes,
        }
        return asyncio.run(handlers[args.command](args))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
