"""Box 4 alias tables (C20): default files, organization folder override, load-time checks (K36)."""

import pytest
from normalize_fixtures import NORMALIZE, NOW, load_ait_c2

from soc.config import ConfigError
from soc.normalize.alias import AliasTableError, load_alias_tables
from soc.normalize.normalizer import Normalizer

VALID = """
scenario = "x_case"
kind = "alert"
class_uid = 2004
time_format = "epoch_ms"
[severity_map]
high = 4
[fields]
time = ["t"]
severity_id = ["s"]
rule_id = ["r"]
rule_name = ["r"]
src_ip = ["ip"]
"""


def write(directory, name, text):
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")
    return directory


def test_default_tables_cover_the_ait_scenarios():
    tables = load_alias_tables(None)
    assert {"ait_suricata_alert", "ait_apache_access", "ait_wazuh_alert"} <= set(tables)
    assert tables["ait_suricata_alert"].table.kind == "alert"
    assert tables["ait_wazuh_alert"].table.kind == "alert"
    assert tables["ait_apache_access"].table.kind == "event"


def test_org_alias_file_overrides_default_by_name():
    tables = load_alias_tables(NORMALIZE / "org_aliases")
    assert tables["ait_suricata_alert"].table.severity_map == {"1": 5, "2": 3, "3": 2}
    assert "ait_apache_access" in tables  # untouched defaults stay
    result = Normalizer(tables, 16_384).normalize(load_ait_c2()[0], NOW)
    assert result.severity_id == 5


def test_org_folder_adds_a_new_scenario():
    assert "fake_waf_alert" in load_alias_tables(NORMALIZE / "aliases")


def test_missing_org_folder_fails(tmp_path):
    with pytest.raises(ConfigError, match="alias_dir"):
        load_alias_tables(tmp_path / "nowhere")


def test_alias_table_error_is_a_config_error():
    assert issubclass(AliasTableError, ConfigError)


@pytest.mark.parametrize(
    ("name", "text", "match"),
    [
        ("other_name.toml", VALID, "scenario"),
        ("x_case.toml", VALID.replace("class_uid = 2004", "class_uid = 4002"), "AliasTable"),
        ("x_case.toml", VALID.replace('rule_name = ["r"]', 'rule_nam = ["r"]'), "rule_nam"),
        ("x_case.toml", VALID.replace('rule_name = ["r"]', "rule_name = []"), "rule_name"),
        ("x_case.toml", VALID + '\n[extensions_map]\nk = "nodot"\n', "extensions_map"),
        (
            "x_case.toml",
            VALID.replace('time_format = "epoch_ms"', 'time_format = "unix"'),
            "time_format",
        ),
        ("x_case.toml", VALID + '\n[parse]\nfield = "m"\npattern = "(unclosed"\n', "parse"),
        ("x_case.toml", VALID + '\n[parse]\nfield = "m"\npattern = "[a-z]+"\n', "parse"),
        ("x_case.toml", VALID + "\nunknown = 1\n", "AliasTable"),
        ("x_case.toml", "not = [valid", "TOML"),
        (
            "x_case.toml",
            VALID.replace('kind = "alert"', 'kind = "event"').replace("class_uid = 2004", ""),
            "class_uid",
        ),
    ],
)
def test_invalid_alias_table_fails_at_load(tmp_path, name, text, match):
    directory = write(tmp_path / "org", name, text)
    with pytest.raises(AliasTableError, match=match):
        load_alias_tables(directory)


def test_load_error_names_the_file_not_its_values(tmp_path):
    text = VALID.replace('time_format = "epoch_ms"', 'time_format = "secretmarker"')
    directory = write(tmp_path / "org", "x_case.toml", text)
    with pytest.raises(AliasTableError) as error:
        load_alias_tables(directory)
    assert "x_case.toml" in str(error.value)
    assert "secretmarker" not in str(error.value)


def test_event_table_fields_are_c13_fields(tmp_path):
    text = (
        'scenario = "e_case"\nkind = "event"\nclass_uid = 4002\nactivity = "http_request"\n'
        'time_format = "epoch_ms"\n[fields]\ntime = ["t"]\nrule_id = ["r"]\n'
    )
    directory = write(tmp_path / "org", "e_case.toml", text)
    with pytest.raises(AliasTableError, match="rule_id"):
        load_alias_tables(directory)
