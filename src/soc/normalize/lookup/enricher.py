"""Lookup join step (box 4 -> 5): fills src_asset, dst_asset and user_info of C5 and C13.

The enricher is core; what it asks is the configured provider. Provider output
is plugin output, so it is checked as C4 before it is joined.
"""

from dataclasses import dataclass

from soc.contracts import AssetInfo, UserInfo, validate_contract

from .base import LookupProvider


@dataclass(frozen=True)
class Enrichment:
    src_asset: AssetInfo | None
    dst_asset: AssetInfo | None
    user_info: UserInfo | None


class LookupEnricher:
    def __init__(self, provider: LookupProvider):
        self._provider = provider

    def enrich(
        self, src_ip: str | None, dst_ip: str | None, user: str | None, at: int
    ) -> Enrichment:
        """Look up each entity the record has, as of the record's time ``at``."""
        return Enrichment(
            src_asset=self._asset(src_ip, at),
            dst_asset=self._asset(dst_ip, at),
            user_info=self._user(user, at),
        )

    def _asset(self, value: str | None, at: int) -> AssetInfo | None:
        if value is None:
            return None
        return _checked("AssetInfo", self._provider.find_asset(value, at))

    def _user(self, user: str | None, at: int) -> UserInfo | None:
        if user is None:
            return None
        return _checked("UserInfo", self._provider.find_user(user, at))


def _checked(contract: str, found):
    if found is None:
        return None
    data = found.model_dump(mode="json") if hasattr(found, "model_dump") else found
    return validate_contract(contract, data)
