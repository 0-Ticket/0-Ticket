"""Lookup provider interface (box 5 extension point, ``lookups`` group).

A provider answers one question at a time: which asset (C4 AssetInfo) an IP or
host name was at a moment, and which account (C4 UserInfo) a user name is. The
normalization join (``LookupEnricher``) and the evidence queue's lookup handler
both use it. ``[lookup] provider`` picks the registered name; the core never
names an implementation. Changing this interface breaks plugins, so it follows
the contract change procedure (docs/data-contracts.md).
"""

from collections.abc import Mapping
from typing import Protocol

from soc.config import Settings
from soc.contracts import AssetInfo, UserInfo


class LookupProvider(Protocol):
    def find_asset(self, value: str, at: int) -> AssetInfo | None:
        """The asset ``value`` (an IP or host name) matched at ``at`` (epoch ms), or None."""
        ...

    def find_user(self, user: str, at: int) -> UserInfo | None:
        """The account ``user`` names at ``at`` (epoch ms); None if unknown."""
        ...


class LookupProviderFactory(Protocol):
    """What an implementation registers in the ``lookups`` group."""

    def __call__(self, settings: Settings, environ: Mapping[str, str]) -> LookupProvider: ...
