"""SIEM connector interface (box 3, D-037, docs/extensibility.md).

A connector asks one SIEM for the alerts and events after a cursor and returns
their C2 SiemAlert content without ``source_record_id``: the core entry
(``soc.ingest.connector``) assigns that ID and validates the C2. The cursor is
an opaque string only the adapter reads; the caller stores it and hands it back.
Changing this interface breaks plugins, so it follows the contract change
procedure (docs/data-contracts.md).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from soc.config import SiemSettings


class InvalidCursorError(ValueError):
    """The cursor was not made by this connector."""


@dataclass(frozen=True)
class FetchBatch:
    """What one fetch returned.

    Each item is a C2 SiemAlert as a dict (``kind``, ``scenario``, ``raw_ids``,
    ``fields``) without ``source_record_id``; an item carrying one is rejected.
    ``next_cursor`` points after the last item; when nothing is new it equals the
    cursor that was passed in. ``skipped`` counts source records the adapter could
    not turn into C2 (they still move the cursor).
    """

    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    skipped: int = 0


@dataclass(frozen=True)
class HealthStatus:
    """Connection check result. ``detail`` never holds secrets or log content."""

    ok: bool
    detail: str


class SiemConnector(Protocol):
    def fetch(self, cursor: str | None, limit: int) -> FetchBatch:
        """Return at most ``limit`` (>= 1) C2 contents after ``cursor`` (None: from the start).

        The same cursor gives the same items, so a failed store can retry.
        """
        ...

    def health_check(self) -> HealthStatus:
        """Report whether the SIEM can be reached. Report failure, do not raise it."""
        ...


class SiemConnectorFactory(Protocol):
    """What an adapter registers in the ``siem`` registry.

    Address and options come from ``settings``; secrets are read from ``environ``
    through ``soc.config.read_secret(settings.token_env, environ)``.
    """

    def __call__(self, settings: SiemSettings, environ: Mapping[str, str]) -> SiemConnector: ...
