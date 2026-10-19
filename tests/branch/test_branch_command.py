"""`python -m soc.branch`: one page by default, until no alert is left with --all."""

import pytest
from branch_fixtures import alert_data, store_alerts
from fake_branch_store import FakeBranchStore
from fake_store import FakeRecordStore
from fake_ticket_store import FakeTicketStore

from soc.branch.__main__ import main
from soc.branch.rules import ScenarioRuleError
from soc.plugins import PluginRegistry


@pytest.fixture
def setup(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text("[branch]\nbatch_size = 4\n", encoding="utf-8")
    records = FakeRecordStore()
    store_alerts(records, alert_data())
    branches = FakeBranchStore()
    tickets = FakeTicketStore()
    stores = PluginRegistry("stores")
    stores.register("postgresql.records", lambda s, e: records)
    stores.register("postgresql.branches", lambda s, e: branches)
    stores.register("postgresql.tickets", lambda s, e: tickets)
    specialists = PluginRegistry("specialists")
    specialists.register("web", object())
    return {"ZT_CONFIG": str(org)}, records, branches, tickets, stores, specialists


def test_branch_command_runs_one_page_by_default(setup, capsys):
    environ, records, branches, tickets, stores, specialists = setup

    assert main([], environ=environ, stores=stores, specialists=specialists) == 0

    assert capsys.readouterr().out.splitlines() == [
        "alert: read 4, skipped 0, deduplicated 1, scenario_ticket 0, l1_entity_lookup 3",
    ]
    assert records.closed and branches.closed and tickets.closed


def test_branch_command_with_all_runs_until_no_alert_is_left(setup, capsys):
    environ, records, branches, tickets, stores, specialists = setup

    assert main(["--all"], environ=environ, stores=stores, specialists=specialists) == 0

    assert capsys.readouterr().out.splitlines() == [
        "alert: read 4, skipped 0, deduplicated 1, scenario_ticket 0, l1_entity_lookup 3",
        "alert: read 3, skipped 0, deduplicated 1, scenario_ticket 1, l1_entity_lookup 1",
        "alert: read 0, skipped 0, deduplicated 0, scenario_ticket 0, l1_entity_lookup 0",
    ]
    assert len(tickets.tickets) == 1


def test_branch_command_stops_on_a_bad_rule_file_before_opening_stores(setup, tmp_path):
    environ, records, branches, tickets, stores, specialists = setup
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "scenarios.toml").write_text("[[scenario]]\n", encoding="utf-8")
    org = tmp_path / "org.toml"
    org.write_text(f"[branch]\nrules_dir = {str(rules)!r}\n", encoding="utf-8")

    with pytest.raises(ScenarioRuleError):
        main([], environ={"ZT_CONFIG": str(org)}, stores=stores, specialists=specialists)
    assert records.load_branch_position() is None
    assert not records.closed
