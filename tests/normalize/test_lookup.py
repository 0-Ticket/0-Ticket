"""Lookup join (boxes 6 -> 7): providers in the ``lookups`` group, the enricher on top (K31)."""

import pytest
from lookup_fakes import ALICE, WEB_01, FakeLookup, T

from soc.config import load_config
from soc.contracts import ContractValidationError
from soc.normalize.lookup import LOOKUPS, open_lookup
from soc.normalize.lookup.enricher import Enrichment, LookupEnricher
from soc.normalize.lookup.none import NoneLookup
from soc.plugins import PluginRegistry


def test_none_lookup_finds_nothing():
    lookup = NoneLookup()
    assert lookup.find_asset("192.0.2.80", T) is None
    assert lookup.find_user("alice", T) is None


def test_none_provider_is_chosen_by_setting(tmp_path):
    # The default became "csv" in box 7 (#60); "none" stays available by setting.
    org = tmp_path / "org.toml"
    org.write_text('[lookup]\nprovider = "none"\n', encoding="utf-8")
    settings = load_config(org, environ={})
    assert isinstance(open_lookup(settings, environ={}), NoneLookup)
    assert "none" in LOOKUPS.names()


def test_none_provider_fills_nulls():
    result = LookupEnricher(NoneLookup()).enrich("198.51.100.23", "192.0.2.80", "alice", T)
    assert result == Enrichment(None, None, None)


def test_enricher_asks_the_provider_for_each_entity_at_the_record_time():
    lookup = FakeLookup({"192.0.2.80": WEB_01}, {"alice": ALICE})
    result = LookupEnricher(lookup).enrich("198.51.100.23", "192.0.2.80", "alice", T)
    assert result == Enrichment(None, WEB_01, ALICE)
    assert lookup.calls == [
        ("asset", "198.51.100.23", T),
        ("asset", "192.0.2.80", T),
        ("user", "alice", T),
    ]


def test_enricher_skips_missing_entities():
    lookup = FakeLookup()
    assert LookupEnricher(lookup).enrich(None, None, None, T) == Enrichment(None, None, None)
    assert lookup.calls == []


def test_enricher_rejects_provider_output_that_is_not_c4():
    class Broken(FakeLookup):
        def find_asset(self, value, at):
            return {"match": value}

    with pytest.raises(ContractValidationError):
        LookupEnricher(Broken()).enrich("192.0.2.80", None, None, T)


def test_fake_lookup_replaces_none_by_setting(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text('[lookup]\nprovider = "fake"\n', encoding="utf-8")
    settings = load_config(org, environ={})
    fake = FakeLookup({"192.0.2.80": WEB_01})
    registry = PluginRegistry("lookups")
    registry.register("fake", lambda s, e: fake)

    opened = open_lookup(settings, environ={}, registry=registry)

    assert opened is fake
    assert LookupEnricher(opened).enrich(None, "192.0.2.80", None, T).dst_asset == WEB_01
