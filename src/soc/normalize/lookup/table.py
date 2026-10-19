"""The ``csv`` lookup provider (box 5): reads the asset and account tables loaded from CSV.

The tables live in the Lookup store (RDB, D-002), opened with
``open_store("lookups", ...)``; the CSV files are only the load input
(``python -m soc.normalize.lookup.load``). The store gives every row that
matches; this provider picks one:

- asset: single addresses first (an exact IP row), then the longest prefix,
  then the latest ``valid_from``, then ``match`` text order.
- account: the latest ``valid_from`` (periods of one name never overlap).
"""

from collections.abc import Mapping

from soc.config import Settings
from soc.contracts import AssetInfo, UserInfo
from soc.plugins import PluginRegistry
from soc.store import open_store
from soc.store.lookups.base import STORE_KIND, LookupStore
from soc.store.lookups.checks import network_of


class TableLookup:
    def __init__(self, store: LookupStore):
        self._store = store

    def find_asset(self, value: str, at: int) -> AssetInfo | None:
        return min(self._store.asset_candidates(value, at), key=_asset_rank, default=None)

    def find_user(self, user: str, at: int) -> UserInfo | None:
        rows = self._store.user_candidates(user, at)
        best = max(rows, key=lambda row: _start(row.valid_from), default=None)
        return None if best is None else best.user

    def close(self) -> None:
        self._store.close()


def _start(valid_from: int | None) -> float:
    return float("-inf") if valid_from is None else valid_from


def _asset_rank(asset: AssetInfo) -> tuple[int, int, float, str]:
    network = network_of(asset.match)
    single = 0 if network.num_addresses == 1 else 1
    return (single, -network.prefixlen, -_start(asset.valid_from), asset.match)


def create_csv_lookup(
    settings: Settings, environ: Mapping[str, str], *, stores: PluginRegistry | None = None
) -> TableLookup:
    """The ``csv`` factory. ``stores`` replaces the stores registry in tests."""
    return TableLookup(open_store(STORE_KIND, settings, environ, registry=stores))
