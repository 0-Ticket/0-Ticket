"""`python -m soc.normalize`: one run per kind by default, until no source is left with --all.

The lookup join uses the configured provider: here the csv provider over the
sample tables, so the AIT alert to 192.0.2.80 gets web-01 (boxes 6 -> 7, K7).
"""

from pathlib import Path

import pytest
from fake_lookup_store import FakeLookupStore
from fake_store import FakeRecordStore
from normalize_fixtures import load_ait_c2

from soc.normalize.__main__ import main
from soc.normalize.lookup.load import load_csv
from soc.normalize.lookup.table import TableLookup
from soc.normalize.runner import alert_id_for
from soc.plugins import PluginRegistry

LOOKUP = Path(__file__).resolve().parents[1] / "fixtures" / "lookup"


@pytest.fixture
def setup(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text("[normalize]\nbatch_size = 1\n", encoding="utf-8")
    records = FakeRecordStore()
    records.save_source_records(load_ait_c2(), "direct", "c1")
    tables = FakeLookupStore()
    load_csv(tables, "assets", LOOKUP / "assets.csv")
    stores = PluginRegistry("stores")
    stores.register("postgresql.records", lambda s, e: records)
    lookups = PluginRegistry("lookups")
    lookups.register("csv", lambda s, e: TableLookup(tables))
    return {"ZT_CONFIG": str(org)}, records, tables, stores, lookups


def alerts(records):
    return [
        records.get_alert_record(alert_id_for(s.record.source_record_id))
        for s in records.list_source_records("alert", None, 100)
    ]


def test_normalize_command_runs_each_kind_once_by_default(setup, capsys):
    environ, records, tables, stores, lookups = setup

    assert main([], environ=environ, stores=stores, lookups=lookups) == 0

    assert capsys.readouterr().out.splitlines() == [
        "alert: read 1, normalized 1, failed 0",
        "event: read 1, normalized 1, failed 0",
    ]
    assert sum(a is not None for a in alerts(records)) == 1
    assert records.closed and tables.closed


def test_normalize_command_with_all_runs_until_no_source_is_left(setup, capsys):
    environ, records, _, stores, lookups = setup

    assert main(["--all"], environ=environ, stores=stores, lookups=lookups) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines.count("alert: read 1, normalized 1, failed 0") == 2
    assert lines.count("event: read 1, normalized 1, failed 0") == 4
    assert lines[-1] == "event: read 0, normalized 0, failed 0"
    saved = alerts(records)
    assert len(saved) == 2
    for alert in saved:
        assert (alert.dst_asset.hostname, alert.dst_asset.criticality) == ("web-01", 5)
        assert alert.src_asset is None  # 198.51.100.23 is in no table.
