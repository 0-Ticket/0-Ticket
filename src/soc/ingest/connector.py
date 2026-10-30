"""Core SIEM entry (box 3, K3, K66).

The adapter is the one named in ``[siem] adapter``, found in the ``siem``
registry. Nothing here knows any adapter by name. Adapters return C2 content
without ``source_record_id``; this module alone assigns that ID and validates
every item as C2, so a plugin cannot pass anything else downstream.
"""

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from soc.config import ConfigError, Settings
from soc.contracts import ContractValidationError, SiemAlert, validate_contract
from soc.normalize.alias import load_alias_tables, validate_mapping_selections
from soc.plugins import PluginRegistry

from .siem import SIEM_CONNECTORS
from .siem.base import HealthStatus, SiemConnector

SOURCE_RECORD_ID_PREFIX = "src_"
# The C2 fields the ID is computed from. source_record_id itself is not one of them.
C2_CONTENT_KEYS = ("kind", "scenario", "raw_ids", "fields")


def canonical_c2_content(content: Mapping[str, Any]) -> bytes:
    """The bytes a source_record_id hashes with mapping_profile under the old scenario key.

    Raises ValueError when a value is not plain JSON (NaN, infinity, lone surrogate).
    """
    subset = {
        key: content["mapping_profile"]
        if key == "scenario" and "mapping_profile" in content
        else content[key]
        for key in C2_CONTENT_KEYS
    }
    text = json.dumps(
        subset, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def source_record_id(content: Mapping[str, Any]) -> str:
    """``src_`` + full hex sha256 of the canonical C2 content. Same content, same ID."""
    return SOURCE_RECORD_ID_PREFIX + hashlib.sha256(canonical_c2_content(content)).hexdigest()


@dataclass(frozen=True)
class IngestBatch:
    """One fetch as C2, each item with its source_record_id."""

    items: tuple[SiemAlert, ...]
    next_cursor: str | None
    skipped: int = 0


class SiemIngest:
    """The configured connector with the batch size from settings, ID assignment and C2 checks."""

    def __init__(self, connector: SiemConnector, batch_size: int):
        self._connector = connector
        self._batch_size = batch_size

    def fetch(self, cursor: str | None) -> IngestBatch:
        batch = self._connector.fetch(cursor, self._batch_size)
        items = tuple(to_c2(item) for item in batch.items)
        return IngestBatch(items=items, next_cursor=batch.next_cursor, skipped=batch.skipped)

    def health_check(self) -> HealthStatus:
        return self._connector.health_check()


def to_c2(content: object) -> SiemAlert:
    """Turn one adapter item into C2 by assigning its source_record_id.

    An item that already carries a source_record_id is rejected, not overwritten,
    so the ID rule lives only here.
    """
    if not isinstance(content, Mapping):
        raise ContractValidationError("/", "object_type")
    if "source_record_id" in content:
        raise ContractValidationError("/source_record_id", "assigned_by_core")
    # Check the shape first with a placeholder ID so a missing field reports as such.
    validate_contract("SiemAlert", {**content, "source_record_id": SOURCE_RECORD_ID_PREFIX})
    # Hash the adapter's own values: a model dump would quietly turn NaN into null.
    try:
        record_id = source_record_id(content)
    except (TypeError, ValueError):
        raise ContractValidationError("/fields", "json_value") from None
    return validate_contract("SiemAlert", {**content, "source_record_id": record_id})


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
    selectors = getattr(factory, "mapping_selections", None)
    if callable(selectors):
        tables = load_alias_tables(settings.normalize.alias_dir or None)
        validate_mapping_selections(tables, selectors(siem))
        configured_factory = getattr(factory, "create_with_alias_tables", None)
        connector = (
            configured_factory(settings, environ, tables)
            if callable(configured_factory)
            else factory(siem, environ)
        )
    else:
        connector = factory(siem, environ)
    return SiemIngest(connector, siem.batch_size)
