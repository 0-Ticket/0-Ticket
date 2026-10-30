"""Attack scenario rules (boxes 10-13): TOML files, organization files win by name.

The default rules ship in ``soc/branch/rules/``. ``[branch] rules_dir`` names an
organization folder; a ``<name>.toml`` there replaces the default file of the
same name whole, and other names add rules (docs/extensibility.md 6). Files are
read in name order and rules in file order; the first rule an alert matches
wins. Every file is checked when loaded, so a broken rule stops the run before
any alert is branched. Errors name the file and the key, never a value.
"""

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from soc.config import ConfigError
from soc.contracts import AlertRecord

RULE_ID = re.compile(r"^[a-z0-9_]+$")
RULE_KEYS = frozenset({"id", "rule_ids", "techniques", "handling_type", "specialist"})
NO_SPECIALIST = "none"


class ScenarioRuleError(ConfigError):
    """A scenario rule file is malformed or breaks a rule."""


@dataclass(frozen=True)
class ScenarioRule:
    id: str
    rule_ids: frozenset[str]
    techniques: frozenset[str]
    handling_type: str
    specialist: str

    def matches(self, alert: AlertRecord) -> bool:
        return alert.rule_id in self.rule_ids or not self.techniques.isdisjoint(alert.techniques)


@dataclass(frozen=True)
class ScenarioRules:
    rules: tuple[ScenarioRule, ...]

    def match(self, alert: AlertRecord) -> ScenarioRule | None:
        """The first rule ``alert`` matches, or None."""
        return next((rule for rule in self.rules if rule.matches(alert)), None)


def default_rules_dir() -> Traversable:
    return files(__package__).joinpath("rules")


def load_scenario_rules(org_dir: str | Path | None, specialists: Iterable[str]) -> ScenarioRules:
    """Default files, then the organization folder's files over them by file name.

    ``specialists`` are the registered specialist names a rule may pick besides "none".
    """
    allowed = frozenset(specialists) | {NO_SPECIALIST}
    files_by_name: dict[str, Traversable] = {
        entry.name: entry for entry in default_rules_dir().iterdir() if entry.name.endswith(".toml")
    }
    if org_dir:
        folder = Path(org_dir)
        if not folder.is_dir():
            raise ConfigError(f"branch.rules_dir is not a folder: {folder}")
        files_by_name.update({entry.name: entry for entry in folder.glob("*.toml")})
    rules: list[ScenarioRule] = []
    seen: set[str] = set()
    for name, entry in sorted(files_by_name.items()):
        for rule in _load_file(name, entry.read_text(encoding="utf-8"), allowed):
            if rule.id in seen:
                raise ScenarioRuleError(f"{name}: scenario.id is used by another rule")
            seen.add(rule.id)
            rules.append(rule)
    return ScenarioRules(tuple(rules))


def _load_file(name: str, text: str, specialists: frozenset[str]) -> list[ScenarioRule]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ScenarioRuleError(f"{name}: not valid TOML: {error}") from None
    unknown = set(data) - {"scenario"}
    if unknown:
        raise ScenarioRuleError(f"{name}: unknown top-level key {sorted(unknown)[0]}")
    entries = data.get("scenario", [])
    if not isinstance(entries, list):
        raise ScenarioRuleError(f"{name}: scenario must be [[scenario]] tables")
    return [_rule(f"{name}: scenario[{i}]", entry, specialists) for i, entry in enumerate(entries)]


def _rule(where: str, entry: Any, specialists: frozenset[str]) -> ScenarioRule:
    if not isinstance(entry, dict):
        raise ScenarioRuleError(f"{where} must be a table")
    unknown = set(entry) - RULE_KEYS
    if unknown:
        raise ScenarioRuleError(f"{where}: unknown key {sorted(unknown)[0]}")
    rule_id = entry.get("id")
    if not isinstance(rule_id, str) or not RULE_ID.match(rule_id):
        raise ScenarioRuleError(f"{where}.id must be lowercase letters, digits and _")
    rule_ids = _strings(where, entry, "rule_ids")
    techniques = _strings(where, entry, "techniques")
    if not rule_ids and not techniques:
        raise ScenarioRuleError(f"{where} needs rule_ids or techniques")
    handling_type = entry.get("handling_type")
    if not isinstance(handling_type, str) or not handling_type.strip():
        raise ScenarioRuleError(f"{where}.handling_type must be a non-empty string")
    specialist = entry.get("specialist")
    if not isinstance(specialist, str) or specialist not in specialists:
        raise ScenarioRuleError(f"{where}.specialist must be a registered specialist or none")
    return ScenarioRule(rule_id, rule_ids, techniques, handling_type, specialist)


def _strings(where: str, entry: dict[str, Any], key: str) -> frozenset[str]:
    values = entry.get(key, [])
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise ScenarioRuleError(f"{where}.{key} must be a list of non-empty strings")
    return frozenset(values)
