"""Box 4 core rules: no LLM at run time, no scenario or SIEM name in code (K37, D-029)."""

import ast
from pathlib import Path

import soc.normalize

CORE = Path(soc.normalize.__file__).resolve().parent
CODE = sorted(CORE.rglob("*.py"))
NAMES = ("ait_", "suricata", "apache", "wazuh", "splunk", "elk", "direct", "csv")


def test_normalize_does_not_import_llm():
    for path in CODE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("soc.llm"), path.name
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("soc.llm") for alias in node.names), path.name


def test_normalize_core_has_no_scenario_or_siem_name_branch():
    for path in CODE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                assert not any(name in lowered for name in NAMES), f"{path.name}: {node.value!r}"


def test_default_alias_tables_ship_with_the_package():
    names = {path.name for path in (CORE / "aliases").glob("*.toml")}
    assert {"ait_suricata_alert.toml", "ait_apache_access.toml"} <= names
