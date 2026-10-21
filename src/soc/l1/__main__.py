"""Command: run L1 entity lookup and Ticket triage (box 11).

Usage: `uv run python -m soc.l1 [--all]`

Like ``soc.ingest`` and ``soc.branch``, ``main`` takes the environment and plugin
registries as keyword arguments so a test can run the command with fakes (#81).
"""

import argparse
from collections.abc import Mapping, Sequence

from soc.config import load_config
from soc.l1.runtime import build_runtime
from soc.plugins import PluginRegistry


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: PluginRegistry | None = None,
    lookups: PluginRegistry | None = None,
    siem: PluginRegistry | None = None,
    providers: PluginRegistry | None = None,
    vectors: PluginRegistry | None = None,
    embedders: PluginRegistry | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run L1 entity lookup and Ticket triage")
    parser.add_argument(
        "--all",
        action="store_true",
        help="process every pending C21 l1_entity_lookup Alert",
    )
    args = parser.parse_args(argv)
    runtime = build_runtime(
        load_config(environ=environ),
        environ,
        store_registry=stores,
        lookup_registry=lookups,
        siem_registry=siem,
        provider_registry=providers,
        vector_registry=vectors,
        embedder_registry=embedders,
    )
    try:
        processed = runtime.run(all_alerts=args.all)
        print(f"Processed {processed} L1 item(s)")
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
