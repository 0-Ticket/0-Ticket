"""Box 5 Lookup: CSV asset and account tables, loaded into the store, joined by the csv provider.

K7: web-01 gets criticality 5, the proxy is shared, an unknown IP is null, an
expired mapping is not used, and lookups live in the store (RDB) only.
"""

from datetime import datetime
from pathlib import Path

import pytest
from fake_lookup_store import FakeLookupStore
from fake_store import FakeRecordStore
from lookup_fakes import FakeLookup
from lookup_store_contract import asset, user
from normalize_fixtures import NOW, load_ait_c2

from soc.config import load_config
from soc.l1.tickets import create_ticket
from soc.normalize.lookup import LOOKUPS, open_lookup
from soc.normalize.lookup.enricher import LookupEnricher
from soc.normalize.lookup.load import load_csv
from soc.normalize.lookup.load import main as load_main
from soc.normalize.lookup.table import TableLookup
from soc.normalize.lookup.table_csv import LookupTableError, parse_assets_csv, parse_users_csv
from soc.normalize.normalizer import Normalizer
from soc.normalize.runner import alert_id_for, normalize_pending
from soc.plugins import PluginRegistry

ROOT = Path(__file__).resolve().parents[2]
LOOKUP = ROOT / "tests" / "fixtures" / "lookup"
T = 1642500341120  # 2022-01-18, the AIT sample alert time.


def ms(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


@pytest.fixture
def lookup():
    store = FakeLookupStore()
    load_csv(store, "assets", LOOKUP / "assets.csv")
    load_csv(store, "users", LOOKUP / "users.csv")
    return TableLookup(store)


# CSV parsing


def test_assets_csv_becomes_c4_rows():
    rows = parse_assets_csv((LOOKUP / "assets.csv").read_text(encoding="utf-8"))
    web = rows[0].model_dump(mode="json")
    assert web == {
        "match": "192.0.2.80",
        "hostname": "web-01",
        "criticality": 5,
        "owner": "web-team@example.com",
        "zone": "dmz",
        "shared": False,
        "valid_from": ms("2021-01-01T00:00:00+00:00"),
        "valid_to": None,
        "extensions": {"acme.cost_center": "cc-100"},
    }
    # An empty extension cell is left out; empty optional cells are null.
    dc = rows[4].model_dump(mode="json")
    assert (dc["hostname"], dc["shared"], dc["extensions"]) == ("dc-01", True, {})
    assert rows[5].owner is None


def test_users_csv_keeps_validity_beside_c4():
    rows = parse_users_csv((LOOKUP / "users.csv").read_text(encoding="utf-8"))
    admin = rows[1]
    assert admin.user.model_dump(mode="json") == {
        "user": "admin@example.com",
        "dept": "it",
        "privileged": True,
        "extensions": {"acme.employee_id": "e-001"},
    }
    bob = rows[2]
    assert (bob.valid_from, bob.valid_to) == (
        ms("2020-01-01T00:00:00+00:00"),
        ms("2021-06-30T00:00:00+00:00"),
    )


def test_epoch_ms_and_iso_times_are_both_accepted():
    text = "match,hostname,criticality,shared,valid_from,valid_to\n"
    text += "192.0.2.80,web-01,5,TRUE,1600000000000,2021-01-01T09:00:00+09:00\n"
    (row,) = parse_assets_csv(text)
    assert (row.shared, row.valid_from, row.valid_to) == (
        True,
        1600000000000,
        ms("2021-01-01T00:00:00+00:00"),
    )


def test_utf8_bom_and_surrounding_spaces_are_ignored():
    text = "﻿user , privileged\n alice@example.com , false \n"
    (row,) = parse_users_csv(text)
    assert (row.user.user, row.user.privileged) == ("alice@example.com", False)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("criticality_out_of_range.csv", "line 2: column criticality"),
        ("missing_shared.csv", "line 2: column shared"),
        ("cidr_host_bits.csv", "line 2: column match"),
        ("overlapping_validity.csv", "line 3: column match"),
        ("time_without_zone.csv", "line 2: column valid_from"),
    ],
)
def test_bad_csv_is_rejected_and_table_is_unchanged(name, message):
    store = FakeLookupStore()
    load_csv(store, "assets", LOOKUP / "assets.csv")
    with pytest.raises(LookupTableError, match=message) as caught:
        load_csv(store, "assets", LOOKUP / "bad" / name)
    # Errors name the line and column, never the cell value.
    assert "192.0.2" not in str(caught.value)
    assert TableLookup(store).find_asset("192.0.2.80", T).hostname == "web-01"


@pytest.mark.parametrize(
    "header",
    [
        "match,hostname,criticality",  # shared missing
        "match,hostname,criticality,shared,colour",  # unknown, not an extension
        "match,hostname,criticality,shared,shared",  # repeated
    ],
)
def test_bad_header_is_rejected(header):
    with pytest.raises(LookupTableError, match="line 1"):
        parse_assets_csv(header + "\n")


def test_row_with_extra_cells_is_rejected():
    with pytest.raises(LookupTableError, match="line 2"):
        parse_users_csv("user,privileged\nalice@example.com,false,extra\n")


# Matching and priority


def test_web_01_gets_criticality_5_proxy_is_shared_unknown_ip_is_null(lookup):
    web = lookup.find_asset("192.0.2.80", T)
    assert (web.hostname, web.criticality, web.shared) == ("web-01", 5, False)
    proxy = lookup.find_asset("192.0.2.10", T)
    assert (proxy.hostname, proxy.shared) == ("proxy-01", True)
    assert lookup.find_asset("198.51.100.23", T) is None
    assert lookup.find_user("nobody@example.com", T) is None


def test_expired_mapping_is_not_used(lookup):
    assert lookup.find_asset("192.0.2.80", ms("2020-06-01T00:00:00+00:00")).hostname == (
        "legacy-web"
    )
    # valid_to is exclusive: from 2021-01-01 the new mapping applies.
    assert lookup.find_asset("192.0.2.80", ms("2021-01-01T00:00:00+00:00")).hostname == "web-01"
    assert lookup.find_asset("192.0.2.80", ms("2018-06-01T00:00:00+00:00")).hostname == (
        "office-net"
    )
    assert lookup.find_user("bob@example.com", ms("2021-01-01T00:00:00+00:00")).dept == "sales"
    assert lookup.find_user("bob@example.com", T) is None


def test_exact_ip_beats_narrower_cidr_beats_wider_cidr():
    store = FakeLookupStore()
    store.replace_assets(
        [
            asset("192.0.2.0/24", "office-net"),
            asset("192.0.2.64/26", "web-net"),
            asset("192.0.2.80", "web-01"),
        ]
    )
    lookup = TableLookup(store)
    assert lookup.find_asset("192.0.2.80", T).hostname == "web-01"
    assert lookup.find_asset("192.0.2.70", T).hostname == "web-net"
    assert lookup.find_asset("192.0.2.5", T).hostname == "office-net"


def test_hostname_matches_case_insensitively(lookup):
    assert lookup.find_asset("WEB-01", T).match == "192.0.2.80"
    assert lookup.find_asset("Proxy-01", T).shared is True


def test_hostname_with_several_rows_prefers_a_single_address():
    store = FakeLookupStore()
    store.replace_assets(
        [
            asset("192.0.2.0/24", "web-01"),
            asset("192.0.2.81", "web-01", valid_from=T - 1),
            asset("192.0.2.80", "web-01", valid_from=T - 2),
        ]
    )
    # Single addresses first, then the later valid_from.
    assert TableLookup(store).find_asset("web-01", T).match == "192.0.2.81"


def test_user_matches_exactly(lookup):
    assert lookup.find_user("admin@example.com", T).privileged is True
    assert lookup.find_user("ADMIN@example.com", T) is None


def test_lookup_survives_csv_deletion(tmp_path):
    copy = tmp_path / "assets.csv"
    copy.write_text((LOOKUP / "assets.csv").read_text(encoding="utf-8"), encoding="utf-8")
    store = FakeLookupStore()
    load_csv(store, "assets", copy)
    copy.unlink()
    # The provider reads the store, never the file.
    assert TableLookup(store).find_asset("192.0.2.80", T).criticality == 5


# Provider selection and sharing


def test_default_settings_pick_the_csv_provider():
    assert load_config(environ={}).lookup.provider == "csv"
    assert "csv" in LOOKUPS.names()


def test_csv_provider_opens_the_lookups_store(tmp_path):
    store = FakeLookupStore()
    stores = PluginRegistry("stores")
    stores.register("postgresql.lookups", lambda s, e: store)
    factory = LOOKUPS.get("csv")

    opened = factory(load_config(environ={}), {}, stores=stores)
    opened.close()

    assert isinstance(opened, TableLookup)
    assert store.closed


def test_fake_lookup_replaces_csv_by_setting(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text('[lookup]\nprovider = "fake"\n', encoding="utf-8")
    fake = FakeLookup()
    registry = PluginRegistry("lookups")
    registry.register("csv", lambda s, e: pytest.fail("csv provider must not be opened"))
    registry.register("fake", lambda s, e: fake)

    assert open_lookup(load_config(org, environ={}), environ={}, registry=registry) is fake


def test_ticket_priority_uses_criticality_from_lookup(lookup):
    records = FakeRecordStore()
    records.save_source_records(load_ait_c2(), "direct", "c1")
    normalize_pending(
        records,
        Normalizer.from_settings(load_config(environ={})),
        LookupEnricher(lookup),
        100,
        lambda: NOW,
    )
    alerts = [
        records.get_alert_record(alert_id_for(s.record.source_record_id))
        for s in records.list_source_records("alert", None, 100)
    ]
    target = next(a for a in alerts if a.dst_ip == "192.0.2.80")
    assert target.dst_asset.criticality == 5

    ticket = create_ticket(
        target.model_dump(mode="json"), origin="scenario", entities=[], now_ms=NOW
    )

    assert ticket["priority"] == target.severity_id * 5


def test_load_command_reports_rows(tmp_path, capsys):
    store = FakeLookupStore()
    stores = PluginRegistry("stores")
    stores.register("postgresql.lookups", lambda s, e: store)

    code = load_main(["assets", str(LOOKUP / "assets.csv")], environ={}, stores=stores)

    assert code == 0
    assert capsys.readouterr().out.strip() == "loaded 6 assets"
    assert store.closed
    assert TableLookup(store).find_asset("192.0.2.10", T).shared is True


def test_load_command_reports_a_bad_file_without_loading(tmp_path, capsys):
    store = FakeLookupStore()
    store.replace_users([user("alice@example.com")])
    stores = PluginRegistry("stores")
    stores.register("postgresql.lookups", lambda s, e: store)
    bad = tmp_path / "users.csv"
    bad.write_text("user,privileged\nalice@example.com,maybe\n", encoding="utf-8")

    code = load_main(["users", str(bad)], environ={}, stores=stores)

    assert code == 1
    assert "line 2: column privileged" in capsys.readouterr().err
    assert TableLookup(store).find_user("alice@example.com", T) is not None
