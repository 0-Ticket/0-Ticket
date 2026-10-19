"""Lookup store interface (box 5, D-002): the asset and account tables (C4) in the RDB.

Tables are replaced whole, from CSV or another source, and searched by value
and moment. The store returns every row that matches (``checks.asset_matches``
for assets, exact name for users) and is valid at that moment; which one wins
is the lookup provider's job. Every replace goes through ``checks``, so both
implementations reject the same rows.

Implementations are registered in the ``stores`` registry as
``<backend>.lookups`` and opened with ``soc.store.open_store("lookups", ...)``.
Changing this interface breaks plugins, so it follows the contract change
procedure (docs/data-contracts.md).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from soc.contracts import AssetInfo, UserInfo

STORE_KIND = "lookups"


class InvalidLookupRows(ValueError):
    """Rows a table would not accept. ``index`` is the 0-based row, ``field`` the column."""

    def __init__(self, index: int, field: str, reason: str):
        super().__init__(f"row {index + 1}: {field}: {reason}")
        self.index = index
        self.field = field
        self.reason = reason


@dataclass(frozen=True)
class UserRow:
    """A C4 UserInfo with the period it holds. UserInfo itself has no validity fields."""

    user: UserInfo
    valid_from: int | None
    valid_to: int | None


class LookupStore(Protocol):
    def replace_assets(self, rows: Sequence[AssetInfo]) -> int:
        """Replace the asset table with ``rows``, all or nothing. Returns the row count.

        Raises InvalidLookupRows and keeps the old table when any row is rejected.
        """
        ...

    def replace_users(self, rows: Sequence[UserRow]) -> int:
        """Replace the account table with ``rows``, all or nothing. Returns the row count."""
        ...

    def asset_candidates(self, value: str, at: int) -> list[AssetInfo]:
        """Assets valid at ``at`` whose network holds the IP ``value``, or whose
        hostname equals ``value`` ignoring case when it is not an IP."""
        ...

    def user_candidates(self, user: str, at: int) -> list[UserRow]:
        """Accounts named exactly ``user`` and valid at ``at``."""
        ...

    def close(self) -> None: ...
