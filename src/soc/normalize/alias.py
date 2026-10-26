"""Alias tables (C20): one TOML file per scenario, organization files win by name.

The default tables ship in ``soc/normalize/aliases/``. ``[normalize] alias_dir``
names an organization folder; a ``<scenario>.toml`` there replaces the default
file of the same name whole (docs/extensibility.md 6). Every table is checked
when loaded, so a broken table stops the run before any record is touched.
Errors name the file and the key, never a value from it.
"""

import re
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from soc.config import ConfigError
from soc.contracts import AliasTable, ContractValidationError, validate_contract

# C20 fields a TOML file may leave out; TOML has no null, so they become None.
OPTIONAL_KEYS = (
    "class_uid",
    "activity",
    "severity_map",
    "default_techniques",
    "extensions_map",
    "parse",
)

TIME_KEYWORDS = frozenset({"iso8601", "epoch_s", "epoch_ms"})
EXTENSION_KEY = re.compile(r"^[^.]+\..+$")

# C3 / C13 fields a table may fill from the source. The rest come from the table
# itself (class_uid, activity), the record (raw_ids, IDs) or later boxes (assets).
ALERT_TARGETS = frozenset(
    {
        "time",
        "severity_id",
        "rule_id",
        "rule_name",
        "src_ip",
        "src_port",
        "dst_ip",
        "dst_port",
        "host",
        "user",
        "http_url",
        "http_status",
        "techniques",
    }
)
EVENT_TARGETS = frozenset(
    {
        "time",
        "src_ip",
        "dst_ip",
        "host",
        "user",
        "http_url",
        "http_status",
        "http_bytes",
        "api_operation",
        "status",
    }
)


class AliasTableError(ConfigError):
    """An alias table file is not valid C20 or breaks a core rule."""


@dataclass(frozen=True)
class CompiledAliasTable:
    """A checked C20 with its parse pattern compiled once."""

    table: AliasTable
    pattern: re.Pattern[str] | None


def default_alias_dir() -> Traversable:
    return files(__package__).joinpath("aliases")


def load_alias_tables(org_dir: str | Path | None) -> dict[str, CompiledAliasTable]:
    """Default tables, then the organization folder's files over them by file name."""
    files_by_name: dict[str, Traversable] = {
        entry.name: entry for entry in default_alias_dir().iterdir() if entry.name.endswith(".toml")
    }
    if org_dir:
        folder = Path(org_dir)
        if not folder.is_dir():
            raise ConfigError(f"normalize.alias_dir is not a folder: {folder}")
        files_by_name.update({entry.name: entry for entry in folder.glob("*.toml")})
    tables = {}
    for name, entry in sorted(files_by_name.items()):
        compiled = _load_file(name, entry.read_text(encoding="utf-8"))
        tables[compiled.table.scenario] = compiled
    return tables


def _load_file(name: str, text: str) -> CompiledAliasTable:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise AliasTableError(f"{name}: not valid TOML: {error}") from None
    for key in OPTIONAL_KEYS:
        data.setdefault(key, None)
    try:
        table = validate_contract("AliasTable", data)
    except ContractValidationError as error:
        raise AliasTableError(
            f"{name}: not a valid AliasTable at {error.path} ({error.rule})"
        ) from None
    _check(name, table)
    return CompiledAliasTable(table, _compile(name, table))


def _check(name: str, table: AliasTable) -> None:
    if name != f"{table.scenario}.toml":
        raise AliasTableError(f"{name}: file name must be <scenario>.toml of its scenario")
    if table.kind == "event" and (table.class_uid is None or not table.activity):
        raise AliasTableError(f"{name}: an event table needs class_uid and activity")
    targets = ALERT_TARGETS if table.kind == "alert" else EVENT_TARGETS
    for target, candidates in table.fields.items():
        if target not in targets:
            raise AliasTableError(
                f"{name}: fields.{target} is not a {table.kind} field it can fill"
            )
        if not candidates or not all(candidates):
            raise AliasTableError(f"{name}: fields.{target} needs at least one source field name")
    if table.time_format not in TIME_KEYWORDS and "%" not in table.time_format:
        raise AliasTableError(f"{name}: time_format must be iso8601, epoch_s, epoch_ms or strftime")
    for source, key in (table.extensions_map or {}).items():
        if not EXTENSION_KEY.match(key):
            raise AliasTableError(f"{name}: extensions_map.{source} must name <org>.<field>")


def _compile(name: str, table: AliasTable) -> re.Pattern[str] | None:
    if table.parse is None:
        return None
    try:
        pattern = re.compile(table.parse.pattern)
    except re.error:
        raise AliasTableError(f"{name}: parse.pattern is not a valid regular expression") from None
    if not pattern.groupindex:
        raise AliasTableError(f"{name}: parse.pattern needs named groups (?P<name>...)")
    return pattern
