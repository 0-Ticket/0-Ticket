"""Scenario rule files (box 25): default file, organization override, checks."""

import shutil

import pytest
from branch_fixtures import FIXTURES, alert_data

from soc.branch.rules import ScenarioRuleError, load_scenario_rules
from soc.config import ConfigError
from soc.contracts import validate_contract

ORG = FIXTURES / "rules"


def alert(**changes):
    item = {**alert_data()[0], "source_record_id": "src_" + "0" * 64, **changes}
    return validate_contract("AlertRecord", item)


def test_default_rules_hold_the_sample_rule():
    rules = load_scenario_rules(None, ["web"])
    assert [r.id for r in rules.rules] == ["sample_web_sqli"]
    rule = rules.rules[0]
    assert (rule.handling_type, rule.specialist) == ("web_attack", "web")


def test_rule_matches_by_rule_id_or_technique():
    rules = load_scenario_rules(None, ["web"])
    assert rules.match(alert(rule_id="sample-31103", techniques=[])).id == "sample_web_sqli"
    assert rules.match(alert(techniques=["T1595", "T1190"])).id == "sample_web_sqli"
    assert rules.match(alert()) is None


def test_rules_org_file_replaces_the_default_by_name_and_adds_others():
    rules = load_scenario_rules(ORG, ["web"])
    # extra.toml sorts before scenarios.toml; the default sample rule is gone.
    assert [r.id for r in rules.rules] == ["org_policy", "org_wpscan"]
    assert rules.match(alert()).id == "org_wpscan"
    assert rules.match(alert(techniques=["T1190"], rule_id="1")) is None


def test_first_matching_rule_wins(tmp_path):
    (tmp_path / "scenarios.toml").write_text(
        '[[scenario]]\nid = "a"\nrule_ids = ["2008983"]\nhandling_type = "scan"\n'
        'specialist = "none"\n'
        '[[scenario]]\nid = "b"\ntechniques = ["T1595"]\nhandling_type = "other"\n'
        'specialist = "none"\n',
        encoding="utf-8",
    )
    assert load_scenario_rules(tmp_path, []).match(alert()).id == "a"


def test_empty_org_file_turns_scenarios_off(tmp_path):
    (tmp_path / "scenarios.toml").write_text("# no scenarios\n", encoding="utf-8")
    assert load_scenario_rules(tmp_path, ["web"]).rules == ()


GOOD = 'id = "r"\nrule_ids = ["1"]\nhandling_type = "scan"\nspecialist = "none"\n'


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[[scenario]\n", "not valid TOML"),
        ("[other]\nkey = 1\n", "unknown top-level key"),
        ('scenario = "x"\n', "[[scenario]] tables"),
        ("[[scenario]]\n" + GOOD + 'note = "secret-value"\n', "unknown key note"),
        ("[[scenario]]\n" + GOOD.replace('"r"', '"Bad-ID"'), "id must be"),
        ("[[scenario]]\n" + GOOD.replace('rule_ids = ["1"]', "rule_ids = []"), "needs rule_ids"),
        ("[[scenario]]\n" + GOOD.replace('["1"]', '[""]'), "rule_ids must be"),
        ("[[scenario]]\n" + GOOD.replace('"scan"', '" "'), "handling_type"),
        ("[[scenario]]\n" + GOOD.replace('"none"', '"secret-value"'), "specialist"),
        ("[[scenario]]\n" + GOOD + "[[scenario]]\n" + GOOD, "used by another rule"),
    ],
)
def test_rules_bad_file_stops_the_load_without_echoing_values(tmp_path, text, message):
    (tmp_path / "scenarios.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ScenarioRuleError, match="scenarios.toml") as caught:
        load_scenario_rules(tmp_path, ["web"])
    assert message in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_rule_id_repeated_across_files_is_rejected(tmp_path):
    shutil.copy(ORG / "scenarios.toml", tmp_path / "scenarios.toml")
    shutil.copy(ORG / "scenarios.toml", tmp_path / "again.toml")
    with pytest.raises(ScenarioRuleError, match="used by another rule"):
        load_scenario_rules(tmp_path, ["web"])


def test_specialist_must_be_registered(tmp_path):
    shutil.copy(ORG / "extra.toml", tmp_path / "extra.toml")
    with pytest.raises(ScenarioRuleError, match="specialist"):
        load_scenario_rules(tmp_path, [])


def test_missing_rules_dir_fails(tmp_path):
    with pytest.raises(ConfigError, match="rules_dir"):
        load_scenario_rules(tmp_path / "missing", ["web"])
