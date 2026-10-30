"""Command: fetch from the configured SIEM and store the source records (SIEM connector -> 6, 7).

Usage: `uv run python -m soc.ingest [--all]`

Without options it runs ``ingest_once`` once. With ``--all`` it repeats until a
fetch brings nothing new. The cursor is kept per ``[siem] adapter``.
"""

import argparse
from collections.abc import Mapping, Sequence

from soc.config import load_config
from soc.plugins import PluginRegistry
from soc.store import open_store
from soc.store.ingest import ingest_once
from soc.store.records.base import STORE_KIND

from .connector import open_connector


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: PluginRegistry | None = None,
    siem: PluginRegistry | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soc.ingest", description="Fetch SIEM alerts and events and store them."
    )
    parser.add_argument("--all", action="store_true", help="repeat until nothing new is fetched")
    args = parser.parse_args(argv)

    settings = load_config(environ=environ)
    ingest = open_connector(settings, environ, registry=siem)
    store = open_store(STORE_KIND, settings, environ, registry=stores)
    try:
        while True:
            run = ingest_once(ingest, store, settings.siem.adapter)
            print(
                f"fetched {run.fetched}, stored {run.inserted}, "
                f"duplicates {run.duplicates}, skipped {run.skipped}"
            )
            # A batch of only skipped items still moved the cursor, so more may follow.
            if not args.all or run.fetched + run.skipped == 0:
                break
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
