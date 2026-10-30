"""The ``none`` lookup provider: knows no asset and no account, so every join is null.

It is the default until a real provider (box 7) is configured.
"""

from collections.abc import Mapping

from soc.config import Settings
from soc.contracts import AssetInfo, UserInfo


class NoneLookup:
    def find_asset(self, value: str, at: int) -> AssetInfo | None:
        return None

    def find_user(self, user: str, at: int) -> UserInfo | None:
        return None


def create_none_lookup(settings: Settings, environ: Mapping[str, str]) -> NoneLookup:
    return NoneLookup()
