"""#99: the ELK demo settings in config/demo-elk/ load and agree with the elastic alias tables."""

import json
from pathlib import Path

from soc.branch.rules import load_scenario_rules
from soc.config import load_config
from soc.contracts import validate_contract
from soc.ingest.connector import to_c2
from soc.ingest.siem.elastic import ALERT_SCENARIO, EVENT_SCENARIO, hit_to_c2
from soc.l1.specialists import SPECIALISTS
from soc.normalize.alias import load_alias_tables
from soc.normalize.normalizer import Normalizer

ROOT = Path(__file__).resolve().parents[2]
DEMO_ELK = ROOT / "config" / "demo-elk"
LAB_RULE_ID = "a2a-web-attack-juice-shop"


def _settings():
    return load_config(DEMO_ELK / "settings.toml", environ={})


def _rules():
    return load_scenario_rules(ROOT / _settings().branch.rules_dir, SPECIALISTS.names())


def test_demo_elk_settings_load_and_select_elastic():
    settings = _settings()
    assert settings.siem.adapter == "elastic"
    assert settings.siem.base_url == "http://localhost:9200"
    assert settings.siem.token_env == "SIEM_TOKEN"
    assert settings.siem.elastic.alert_index == ".alerts-security.alerts-*"
    assert settings.siem.elastic.event_index == "logs-*"
    tables = load_alias_tables(None)
    assert tables[ALERT_SCENARIO].table.kind == "alert"
    assert tables[EVENT_SCENARIO].table.kind == "event"


def test_demo_elk_does_not_touch_the_ait_demo():
    assert _settings().branch.rules_dir == "config/demo-elk/rules"


def test_demo_elk_scenario_rule_matches_lab_rule_id():
    rules = _rules()
    assert [rule.id for rule in rules.rules] == ["elk_web_attack"]
    rule = rules.rules[0]
    assert rule.rule_ids == frozenset({LAB_RULE_ID})
    assert (rule.handling_type, rule.specialist) == ("web_attack", "web")

    hit = json.loads((ROOT / "tests/fixtures/elastic/alert_hits.json").read_text("utf-8"))[0]
    c2 = to_c2(hit_to_c2(hit, "alert", ALERT_SCENARIO))
    alert = Normalizer(load_alias_tables(None), 16_384).normalize(c2, 0)
    record = validate_contract(
        "AlertRecord",
        {
            "alert_id": "al_test",
            "source_record_id": c2.source_record_id,
            **alert.model_dump(mode="json"),
            "src_asset": None,
            "dst_asset": None,
            "user_info": None,
            "count": 1,
            "first_seen": alert.time,
            "last_seen": alert.time,
        },
    )
    assert rules.match(record).id == "elk_web_attack"
