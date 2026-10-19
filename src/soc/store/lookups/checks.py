"""Rules every Lookup store applies (box 5): row checks before a replace, and matching.

Rows are C4. On top of the contract, an asset ``match`` must be an IP or a CIDR
without host bits, a period must end after it starts (valid_to is exclusive),
and the same network (or account name) must not have two rows whose periods
overlap. Errors name the row and the field, never the value.
"""

import ipaddress
from collections.abc import Hashable, Mapping, Sequence
from typing import Any

from soc.contracts import AssetInfo, ContractValidationError, validate_contract

from .base import InvalidLookupRows, UserRow

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_ip(value: str) -> IPAddress | None:
    """``value`` as an IP address, or None when it is not one (then it is a host name)."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if getattr(address, "scope_id", None):
        # fe80::1%eth0: the zone is not part of the address a table can hold.
        address = type(address)(int(address))
    return address


def network_of(match: str) -> IPNetwork:
    """The network an asset ``match`` names. An IP is a /32 or /128. Raises ValueError."""
    return ipaddress.ip_network(match, strict=True)


def valid_at(valid_from: int | None, valid_to: int | None, at: int) -> bool:
    """valid_from <= at < valid_to, with None as an open end."""
    return (valid_from is None or valid_from <= at) and (valid_to is None or at < valid_to)


def asset_matches(asset: AssetInfo, value: str, at: int) -> bool:
    """Whether ``asset`` is a candidate for ``value`` at ``at`` (see LookupStore)."""
    if not valid_at(asset.valid_from, asset.valid_to, at):
        return False
    address = parse_ip(value)
    if address is None:
        return asset.hostname.lower() == value.lower()
    return address in network_of(asset.match)


def check_assets(rows: Sequence[AssetInfo | Mapping[str, Any]]) -> list[AssetInfo]:
    """Validate a whole asset table. Raises InvalidLookupRows for the first bad row."""
    checked = [_contract("AssetInfo", index, row) for index, row in enumerate(rows)]
    networks = []
    for index, asset in enumerate(checked):
        try:
            networks.append(network_of(asset.match))
        except ValueError:
            raise InvalidLookupRows(
                index, "match", "not an IP or a CIDR without host bits"
            ) from None
        _check_period(index, asset.valid_from, asset.valid_to)
    _check_overlaps(
        [(net, a.valid_from, a.valid_to) for net, a in zip(networks, checked, strict=True)],
        "match",
    )
    return checked


def check_users(rows: Sequence[UserRow | Mapping[str, Any]]) -> list[UserRow]:
    """Validate a whole account table. Raises InvalidLookupRows for the first bad row.

    A row is a UserRow, or a mapping of the UserInfo fields plus ``valid_from`` and
    ``valid_to`` (as the CSV reader gives it).
    """
    checked = []
    for index, row in enumerate(rows):
        if isinstance(row, UserRow):
            data, valid_from, valid_to = row.user, row.valid_from, row.valid_to
        else:
            data = dict(row)
            valid_from, valid_to = data.pop("valid_from", None), data.pop("valid_to", None)
        user = _contract("UserInfo", index, data)
        for field, value in (("valid_from", valid_from), ("valid_to", valid_to)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise InvalidLookupRows(index, field, "not an integer epoch ms")
        _check_period(index, valid_from, valid_to)
        checked.append(UserRow(user, valid_from, valid_to))
    _check_overlaps([(r.user.user, r.valid_from, r.valid_to) for r in checked], "user")
    return checked


def _contract(name: str, index: int, row: Any):
    data = row.model_dump(mode="json") if hasattr(row, "model_dump") else row
    try:
        return validate_contract(name, data)
    except ContractValidationError as error:
        field = error.path.strip("/").split("/")[0] or "row"
        raise InvalidLookupRows(index, field, f"breaks {name} ({error.rule})") from None


def _check_period(index: int, valid_from: int | None, valid_to: int | None) -> None:
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise InvalidLookupRows(index, "valid_to", "must be after valid_from")


def _check_overlaps(periods: Sequence[tuple[Hashable, int | None, int | None]], field: str) -> None:
    """No two rows of the same key may share a moment. Reports the later of the two rows."""
    by_key: dict[Hashable, list[int]] = {}
    for index, (key, _, _) in enumerate(periods):
        by_key.setdefault(key, []).append(index)

    def start(index: int) -> float:
        return _bound(periods[index][1], float("-inf"))

    for indexes in by_key.values():
        latest_end, latest_index = float("-inf"), -1
        for index in sorted(indexes, key=start):
            if latest_end > start(index):
                raise InvalidLookupRows(
                    max(index, latest_index), field, "overlaps another row's valid period"
                )
            end = _bound(periods[index][2], float("inf"))
            if end > latest_end:
                latest_end, latest_index = end, index


def _bound(value: int | None, default: float) -> float:
    return default if value is None else value
