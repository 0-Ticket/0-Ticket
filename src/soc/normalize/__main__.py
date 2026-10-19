"""Command: normalize stored source records and join lookups (box 4 -> 5).

Usage: `uv run python -m soc.normalize [--all]`

Without options it runs ``normalize_once`` once for alerts and once for events.
With ``--all`` it repeats each kind until no source is left. The lookup join
uses the provider ``[lookup] provider`` names.
"""

import argparse
import time
from collections.abc import Mapping, Sequence

from soc.config import load_config
from soc.plugins import PluginRegistry
from soc.store import open_store
from soc.store.records.base import STORE_KIND

from .lookup import open_lookup
from .lookup.enricher import LookupEnricher
from .normalizer import Normalizer
from .runner import KINDS, normalize_once, normalize_pending


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: PluginRegistry | None = None,
    lookups: PluginRegistry | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soc.normalize",
        description="Normalize stored alerts and events to OCSF and join lookups.",
    )
    parser.add_argument("--all", action="store_true", help="repeat until no source is left")
    args = parser.parse_args(argv)

    settings = load_config(environ=environ)
    normalizer = Normalizer.from_settings(settings)
    batch_size = settings.normalize.batch_size
    store = open_store(STORE_KIND, settings, environ, registry=stores)
    try:
        lookup = open_lookup(settings, environ, registry=lookups)
        try:
            enricher = LookupEnricher(lookup)
            if args.all:
                runs = normalize_pending(store, normalizer, enricher, batch_size, _now_ms)
            else:
                runs = [
                    normalize_once(store, normalizer, enricher, kind, batch_size, _now_ms)
                    for kind in KINDS
                ]
        finally:
            # Providers that hold a connection (csv) close it; the interface does not require it.
            close = getattr(lookup, "close", None)
            if callable(close):
                close()
    finally:
        store.close()
    for run in runs:
        print(f"{run.kind}: read {run.read}, normalized {run.normalized}, failed {run.failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
