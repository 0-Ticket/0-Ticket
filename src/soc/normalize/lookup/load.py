"""Command: load an asset or account CSV table into the Lookup store (box 7).

Usage: `uv run python -m soc.normalize.lookup.load assets|users <file.csv>`

The table is replaced whole. The file is read and checked before the store is
opened, so a bad file changes nothing. CSV format: ``table_csv``.
"""

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from soc.config import load_config
from soc.plugins import PluginRegistry
from soc.store import open_store
from soc.store.lookups.base import STORE_KIND, LookupStore

from .table_csv import LookupTableError, parse_assets_csv, parse_users_csv

TABLES = ("assets", "users")


def load_csv(store: LookupStore, table: str, path: str | Path) -> int:
    """Replace ``table`` in ``store`` with the CSV at ``path``. Returns the row count."""
    text = Path(path).read_text(encoding="utf-8")
    if table == "assets":
        return store.replace_assets(parse_assets_csv(text))
    if table == "users":
        return store.replace_users(parse_users_csv(text))
    raise ValueError(f"table must be one of {', '.join(TABLES)}")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: PluginRegistry | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soc.normalize.lookup.load",
        description="Replace the asset or account Lookup table with a CSV file.",
    )
    parser.add_argument("table", choices=TABLES)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    try:
        text = args.path.read_text(encoding="utf-8")
        rows = parse_assets_csv(text) if args.table == "assets" else parse_users_csv(text)
    except (OSError, UnicodeDecodeError, LookupTableError) as error:
        reason = error if isinstance(error, LookupTableError) else type(error).__name__
        print(f"{args.path}: not loaded: {reason}", file=sys.stderr)
        return 1

    settings = load_config(environ=environ)
    store = open_store(STORE_KIND, settings, environ, registry=stores)
    try:
        count = store.replace_assets(rows) if args.table == "assets" else store.replace_users(rows)
    finally:
        store.close()
    print(f"loaded {count} {args.table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
