"""C3 -> OCSF 1.9.0 Detection Finding (K6), checked against the official class schema."""

import jsonschema
import pytest
from normalize_fixtures import NORMALIZE, NOW, OCSF, fake_waf_c2, load_ait_c2, read_json

from soc.contracts import validate_contract
from soc.normalize.alias import load_alias_tables
from soc.normalize.normalizer import Normalizer
from soc.normalize.ocsf import OCSF_VERSION, to_ocsf_detection_finding

VALIDATOR = jsonschema.Draft7Validator(read_json(OCSF / "detection_finding_1.9.0.schema.json"))


def normalized_alerts():
    normalizer = Normalizer(load_alias_tables(NORMALIZE / "aliases"), 16_384)
    items = [item for item in load_ait_c2() if item.kind == "alert"] + [fake_waf_c2()]
    return [normalizer.normalize(item, NOW) for item in items]


def test_schema_file_is_ocsf_1_9_0_detection_finding():
    schema = VALIDATOR.schema
    assert schema["properties"]["class_uid"]["const"] == 2004
    assert OCSF_VERSION == "1.9.0"


def test_ocsf_export_matches_expected():
    waf = normalized_alerts()[-1]
    assert to_ocsf_detection_finding(waf, "al_sample_waf") == read_json(
        OCSF / "expected_detection_finding.json"
    )


@pytest.mark.parametrize("index", range(3))
def test_ocsf_export_passes_ocsf_1_9_0_schema(index):
    alert = normalized_alerts()[index]
    VALIDATOR.validate(to_ocsf_detection_finding(alert, "al_sample"))


def test_alert_record_exports_the_same_way():
    record = validate_contract(
        "AlertRecord", read_json(NORMALIZE.parent / "store" / "alert_records.json")[0]
    )
    exported = to_ocsf_detection_finding(record, record.alert_id)
    VALIDATOR.validate(exported)
    assert exported["finding_info"]["uid"] == record.alert_id
    assert exported["finding_info"]["attacks"] == [{"technique": {"uid": "T1595"}}]


def test_host_only_alert_still_has_valid_evidence():
    waf = normalized_alerts()[-1].model_copy(update={"src_ip": None, "dst_ip": None, "src_port": 1})
    exported = to_ocsf_detection_finding(waf, "al_sample")
    VALIDATOR.validate(exported)
    assert "src_endpoint" not in exported["evidences"][0]


def test_user_goes_to_the_evidence():
    alert = normalized_alerts()[0].model_copy(update={"user": "alice"})
    exported = to_ocsf_detection_finding(alert, "al_sample")
    VALIDATOR.validate(exported)
    assert exported["evidences"][0]["user"] == {"name": "alice"}
