"""Command: branch normalized alerts (boxes 10-13, stage 0).

Usage: `uv run python -m soc.branch [--all]`

Without options it branches one page (``[branch] batch_size``). With ``--all``
it repeats until no alert is left, as ``soc.ingest`` and ``soc.normalize`` do.
It prints counts only, never a value from a log.
"""

import argparse
import time
from collections.abc import Mapping, Sequence

from soc.config import load_config
from soc.l1.specialists import SPECIALISTS
from soc.l1.tickets import TicketService
from soc.plugins import PluginRegistry
from soc.store import open_store
from soc.store.branches.base import STORE_KIND as BRANCHES
from soc.store.records.base import STORE_KIND as RECORDS

from .rules import load_scenario_rules
from .runner import PATHS, Brancher


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: PluginRegistry | None = None,
    specialists: PluginRegistry | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soc.branch",
        description="Branch normalized alerts: dedup, scenario Tickets, L1 entity lookup.",
    )
    parser.add_argument("--all", action="store_true", help="repeat until no alert is left")
    args = parser.parse_args(argv)

    settings = load_config(environ=environ)
    specialists = SPECIALISTS if specialists is None else specialists
    # Rules are checked before any store is opened: a broken file changes nothing.
    rules = load_scenario_rules(settings.branch.rules_dir or None, specialists.names())
    records = open_store(RECORDS, settings, environ, registry=stores)
    try:
        branches = open_store(BRANCHES, settings, environ, registry=stores)
        try:
            ticket_store = open_store("tickets", settings, environ, registry=stores)
            try:
                brancher = Brancher(
                    records,
                    branches,
                    TicketService(ticket_store),
                    rules,
                    settings.branch,
                    _now_ms,
                )
                runs = brancher.branch_pending() if args.all else [brancher.branch_once()]
            finally:
                ticket_store.close()
        finally:
            branches.close()
    finally:
        records.close()
    for run in runs:
        counts = ", ".join(f"{path} {run.paths[path]}" for path in PATHS)
        print(f"alert: read {run.read}, skipped {run.skipped}, {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
