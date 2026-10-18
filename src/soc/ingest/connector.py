"""Core SIEM entry (box 3, K3, K66).

The adapter is the one named in ``[siem] adapter``, found in the ``siem``
registry. Nothing here knows any adapter by name. Every item an adapter returns
is checked against C2, so a plugin cannot pass anything else downstream.
"""

import os
from collections.abc import Mapping

from soc.config import ConfigError, Settings
from soc.contracts import SiemAlert, validate_contract
from soc.plugins import PluginRegistry

from .siem import SIEM_CONNECTORS
from .siem.base import FetchBatch, HealthStatus, SiemConnector


class SiemIngest:
    """The configured connector with the batch size from settings and C2 checks."""

    def __init__(self, connector: SiemConnector, batch_size: int):
        self._connector = connector
        self._batch_size = batch_size

    def fetch(self, cursor: str | None) -> FetchBatch:
        batch = self._connector.fetch(cursor, self._batch_size)
        items = tuple(_as_c2(item) for item in batch.items)
        return FetchBatch(items=items, next_cursor=batch.next_cursor, skipped=batch.skipped)

    def health_check(self) -> HealthStatus:
        return self._connector.health_check()


def _as_c2(item: object) -> SiemAlert:
    data = item.model_dump(mode="json") if isinstance(item, SiemAlert) else item
    return validate_contract("SiemAlert", data)


def open_connector(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> SiemIngest:
    """Build the connector the settings select. Raises if none is selected."""
    environ = os.environ if environ is None else environ
    registry = SIEM_CONNECTORS if registry is None else registry
    siem = settings.siem
    if not siem.adapter:
        raise ConfigError(
            "Setting 'siem.adapter' is empty: choose a registered SIEM adapter in the "
            "organization settings (ZT_CONFIG)"
        )
    factory = registry.get(siem.adapter)
    return SiemIngest(factory(siem, environ), siem.batch_size)
