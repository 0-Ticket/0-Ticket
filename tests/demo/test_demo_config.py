"""#79: the demo settings in config/demo/ load and agree with each other.

These read only the committed files, never the dataset slice under data/.
"""

import csv
import json
from pathlib import Path

from soc.branch.rules import load_scenario_rules
from soc.config import load_config
from soc.l1.specialists import SPECIALISTS
from soc.normalize.alias import load_alias_tables
from soc.normalize.lookup.table_csv import parse_assets_csv, parse_users_csv

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "config" / "demo"
ALERT_DECISIONS = {"l1_escalated", "held", "-"}
TICKET_DECISIONS = {"closed_fp", "l2_escalated", "held", "-"}


def _settings():
    return load_config(DEMO / "settings.toml", environ={})


def _rows(name: str) -> list[dict[str, str]]:
    with (DEMO / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _rules():
    return load_scenario_rules(ROOT / _settings().branch.rules_dir, SPECIALISTS.names())


def test_demo_settings_load_and_replay_with_direct():
    settings = _settings()
    assert settings.siem.adapter == "direct"
    tables = load_alias_tables(None)
    for entry in settings.siem.direct.files:
        assert entry.path.startswith("data/")  # the dataset slice is never committed
        assert tables[entry.scenario].table.kind == entry.kind
    assert {"l1", "web_specialist"} <= set(settings.mcp.allowed_tools)
    assert "query_http_flow" in settings.mcp.allowed_tools["web_specialist"]


def test_demo_rules_replace_the_default_sample():
    rules = _rules()
    assert [rule.id for rule in rules.rules] == ["demo_web_attack"]
    assert rules.rules[0].rule_ids == frozenset({"31104"})
    assert rules.rules[0].specialist == "web"


def test_demo_lookup_csvs_parse():
    assets = parse_assets_csv((DEMO / "assets.csv").read_text(encoding="utf-8"))
    users = parse_users_csv((DEMO / "users.csv").read_text(encoding="utf-8"))
    by_host = {asset.hostname: asset for asset in assets}
    assert by_host["intranet-server"].criticality == 5
    assert by_host["inet-firewall"].shared and by_host["webserver"].shared
    assert users


def test_expected_table_is_consistent():
    rows = _rows("expected.csv")
    rules = _rules()
    scenario_ids = {rule_id for rule in rules.rules for rule_id in rule.rule_ids}
    schema = json.loads((ROOT / "contracts" / "branch_result.schema.json").read_text("utf-8"))
    paths = set(schema["properties"]["path"]["enum"])
    assert len({row["raw_id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["raw_id"].startswith("raw_wazuh_alert.jsonl_")
        assert row["expected_path"] in paths
        # Only representatives are listed; duplicates are counted in expected_counts.csv.
        assert row["expected_path"] != "deduplicated"
        assert (row["rule_id"] in scenario_ids) == (row["expected_path"] == "scenario_ticket")
        assert row["expected_alert_decision"] in ALERT_DECISIONS
        assert row["expected_ticket_decision"] in TICKET_DECISIONS
        # A scenario Ticket skips the Alert decision; a held Alert never gets a Ticket.
        if row["expected_path"] == "scenario_ticket":
            assert row["expected_alert_decision"] == "-"
        if row["expected_alert_decision"] == "held":
            assert row["expected_ticket_decision"] == "-"
    shown = {row["expected_path"] for row in rows}
    assert {"scenario_ticket", "l1_entity_lookup"} <= shown
    assert "held" in {row["expected_alert_decision"] for row in rows}
    assert "l2_escalated" in {row["expected_ticket_decision"] for row in rows}


def test_expected_counts_match_the_representatives():
    counts = {row["rule_id"]: row for row in _rows("expected_counts.csv")}
    total = counts.pop("total")
    rows = _rows("expected.csv")
    for rule_id, row in counts.items():
        alerts, representatives, deduplicated = (
            int(row[key]) for key in ("alerts", "representatives", "deduplicated")
        )
        assert alerts == representatives + deduplicated
        assert representatives == sum(1 for r in rows if r["rule_id"] == rule_id)
    assert int(total["representatives"]) == len(rows)
    assert int(total["alerts"]) == sum(int(row["alerts"]) for row in counts.values())
    # The duplicate case the demo shows: the repeated 31101 400 errors fold into a few alerts.
    assert int(counts["31101"]["deduplicated"]) > 0
