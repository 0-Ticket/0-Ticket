"""Shared contract tests for Lookup stores (box 7). Fake and PostgreSQL both run them.

A subclass provides a ``make_store`` fixture returning an empty store.
"""

import pytest

from soc.contracts import AssetInfo, UserInfo
from soc.store.lookups.base import InvalidLookupRows, UserRow

T = 1642500341120  # 2022-01-18, the AIT sample alert time.
DAY = 86_400_000


def asset(match, hostname="host", criticality=3, *, shared=False, valid_from=None, valid_to=None):
    return AssetInfo.model_validate(
        {
            "match": match,
            "hostname": hostname,
            "criticality": criticality,
            "owner": None,
            "zone": None,
            "shared": shared,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "extensions": {},
        }
    )


def user(name, *, privileged=False, valid_from=None, valid_to=None):
    info = UserInfo.model_validate(
        {"user": name, "dept": None, "privileged": privileged, "extensions": {}}
    )
    return UserRow(info, valid_from, valid_to)


def hostnames(found):
    return sorted(a.hostname for a in found)


class LookupStoreContract:
    def test_ip_matches_exact_ip_and_containing_cidrs(self, make_store):
        store = make_store()
        store.replace_assets(
            [
                asset("192.0.2.80", "web-01"),
                asset("192.0.2.0/24", "office-net"),
                asset("192.0.2.64/26", "web-net"),
                asset("198.51.100.0/24", "other-net"),
                asset("2001:db8::/32", "v6-net"),
            ]
        )
        assert hostnames(store.asset_candidates("192.0.2.80", T)) == [
            "office-net",
            "web-01",
            "web-net",
        ]
        assert hostnames(store.asset_candidates("192.0.2.5", T)) == ["office-net"]
        assert hostnames(store.asset_candidates("2001:db8::1", T)) == ["v6-net"]
        assert store.asset_candidates("203.0.113.10", T) == []

    def test_host_name_matches_without_case(self, make_store):
        store = make_store()
        store.replace_assets([asset("192.0.2.80", "Web-01"), asset("192.0.2.81", "web-02")])
        assert hostnames(store.asset_candidates("WEB-01", T)) == ["Web-01"]
        assert store.asset_candidates("web", T) == []

    def test_candidates_are_valid_at_the_moment(self, make_store):
        store = make_store()
        store.replace_assets(
            [
                asset("192.0.2.80", "old", valid_from=T - 10 * DAY, valid_to=T),
                asset("192.0.2.80", "new", valid_from=T),
                asset("192.0.2.81", "later", valid_from=T + DAY),
            ]
        )
        assert hostnames(store.asset_candidates("192.0.2.80", T - 1)) == ["old"]
        # valid_to is exclusive: at T the old mapping has ended.
        assert hostnames(store.asset_candidates("192.0.2.80", T)) == ["new"]
        assert store.asset_candidates("192.0.2.81", T) == []

    def test_users_match_exactly_and_by_validity(self, make_store):
        store = make_store()
        store.replace_users(
            [
                user("alice@example.com"),
                user("bob@example.com", valid_from=T - DAY, valid_to=T),
            ]
        )
        assert [r.user.user for r in store.user_candidates("alice@example.com", T)] == [
            "alice@example.com"
        ]
        assert store.user_candidates("Alice@example.com", T) == []
        assert store.user_candidates("bob@example.com", T) == []
        (bob,) = store.user_candidates("bob@example.com", T - 1)
        assert (bob.valid_from, bob.valid_to) == (T - DAY, T)

    def test_returned_rows_keep_every_c4_field(self, make_store):
        store = make_store()
        row = AssetInfo.model_validate(
            {
                "match": "192.0.2.80",
                "hostname": "web-01",
                "criticality": 5,
                "owner": "web-team@example.com",
                "zone": "dmz",
                "shared": False,
                "valid_from": T - DAY,
                "valid_to": None,
                "extensions": {"acme.cost_center": "cc-100"},
            }
        )
        store.replace_assets([row])
        assert store.asset_candidates("192.0.2.80", T) == [row]

    def test_replace_drops_the_previous_table(self, make_store):
        store = make_store()
        assert store.replace_assets([asset("192.0.2.80", "web-01")]) == 1
        assert store.replace_assets([asset("192.0.2.81", "web-02")]) == 1
        assert store.asset_candidates("192.0.2.80", T) == []
        assert hostnames(store.asset_candidates("192.0.2.81", T)) == ["web-02"]

    @pytest.mark.parametrize(
        "rows",
        [
            # The same network twice for overlapping periods.
            [asset("192.0.2.80", "a"), asset("192.0.2.80/32", "b", valid_from=T)],
            # A period that ends before it starts.
            [asset("192.0.2.80", "a", valid_from=T, valid_to=T)],
            # Host bits set in a CIDR.
            [asset("192.0.2.1/24", "a")],
        ],
    )
    def test_bad_rows_are_rejected_and_the_table_is_unchanged(self, make_store, rows):
        store = make_store()
        store.replace_assets([asset("192.0.2.80", "web-01")])
        with pytest.raises(InvalidLookupRows):
            store.replace_assets(rows)
        assert hostnames(store.asset_candidates("192.0.2.80", T)) == ["web-01"]

    def test_overlapping_users_are_rejected(self, make_store):
        store = make_store()
        with pytest.raises(InvalidLookupRows):
            store.replace_users([user("alice@example.com"), user("alice@example.com", valid_to=T)])

    def test_adjacent_periods_are_not_overlapping(self, make_store):
        store = make_store()
        store.replace_assets(
            [
                asset("192.0.2.80", "old", valid_to=T),
                asset("192.0.2.80", "new", valid_from=T),
            ]
        )
        store.replace_users(
            [user("alice@example.com", valid_to=T), user("alice@example.com", valid_from=T)]
        )
        assert hostnames(store.asset_candidates("192.0.2.80", T)) == ["new"]
