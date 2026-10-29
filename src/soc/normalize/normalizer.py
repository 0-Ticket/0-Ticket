"""C2 -> C3 (alert) / C13 (event) / C12 (failure) by alias tables only (box 4, D-029).

Rules, in docs/data-contracts.md C20:
- ``parse`` splits one text field with a named-group pattern first. A value
  longer than ``max_parse_length`` is a ``bad_value`` without running the
  pattern; a value the pattern does not match leaves its fields missing.
- Each target field takes the first candidate that has a value. An empty
  string, an empty list and a missing key are "no value".
- Values are converted to the contract type; a value that does not convert is
  a ``bad_value``. Times need a time zone. Severity goes through severity_map.
- An optional integer (ports, HTTP status) that does not convert is null instead,
  never a made-up number; its source value stays in ``unmapped``.
- Source fields no candidate used stay in ``unmapped`` in their original shape.

Field values come from logs an attacker may have written. They are only data:
C12 ``detail`` names fields and reasons and never repeats a value.
"""

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from soc.config import Settings
from soc.contracts import (
    EventRecord,
    NormalizedAlert,
    NormalizeFailure,
    SiemAlert,
    validate_contract,
)

from .alias import CompiledAliasTable, load_alias_tables
from .ids import event_id_for

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ONE_MS = timedelta(milliseconds=1)
INTEGER_TEXT = re.compile(r"-?[0-9]+")

ALERT_REQUIRED = ("time", "severity_id", "rule_id", "rule_name")
ALERT_ENTITIES = ("src_ip", "dst_ip", "host")
EVENT_REQUIRED = ("time",)
# Integer fields; all optional, so a value that does not convert becomes null.
INT_FIELDS = frozenset({"src_port", "dst_port", "http_status", "http_bytes"})
NON_NEGATIVE_INT_FIELDS = frozenset({"http_bytes"})
ALERT_OPTIONAL = (
    "src_ip",
    "src_port",
    "dst_ip",
    "dst_port",
    "host",
    "user",
    "http_url",
    "http_status",
)
EVENT_OPTIONAL = (
    "src_ip",
    "dst_ip",
    "host",
    "user",
    "http_url",
    "http_status",
    "http_bytes",
    "api_operation",
    "status",
)

Path = tuple[str, ...]
Result = NormalizedAlert | EventRecord | NormalizeFailure


class BadValue(ValueError):
    """A value that does not convert. The message is a reason, never the value."""


@dataclass
class _Draft:
    """What one record yields before it becomes C3, C13 or C12."""

    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Path] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
    extension_paths: set[Path] = field(default_factory=set)
    used: set[Path] = field(default_factory=set)
    bad: str | None = None
    parse_note: str | None = None


class Normalizer:
    def __init__(self, tables: Mapping[str, CompiledAliasTable], max_parse_length: int):
        if max_parse_length < 1:
            raise ValueError("max_parse_length must be at least 1")
        self._tables = dict(tables)
        self._max_parse_length = max_parse_length

    @classmethod
    def from_settings(cls, settings: Settings) -> "Normalizer":
        """Default tables plus ``[normalize] alias_dir``; fails if any table is invalid."""
        tables = load_alias_tables(settings.normalize.alias_dir or None)
        return cls(tables, settings.normalize.max_parse_length)

    def normalize(self, source: SiemAlert, now: int) -> Result:
        """One stored C2 to C3 (alert) or C13 (event), or C12 stamped ``now``."""
        compiled = self._tables.get(source.scenario)
        if compiled is None:
            return _failure(source, now, "unknown_scenario", [], "no alias table for this scenario")
        table = compiled.table
        if table.kind != source.kind:
            detail = f"alias table is for {table.kind} records, not {source.kind}"
            return _failure(source, now, "unknown_scenario", [], detail)

        view = copy.deepcopy(source.fields)
        draft = _Draft()
        if compiled.pattern is not None:
            too_long = self._parse(view, table.parse.field, compiled.pattern, draft)
            if too_long:
                return _failure(source, now, "bad_value", [], too_long)
        _pick(view, table.fields, table.extensions_map or {}, draft)
        converted = _convert(draft, table.time_format, table.severity_map or {})

        # Missing means no value was found; a value that did not convert is bad, not missing.
        found = draft.values
        if source.kind == "alert":
            missing = [name for name in ALERT_REQUIRED if name not in found]
            if not any(name in found for name in ALERT_ENTITIES):
                missing += list(ALERT_ENTITIES)
        else:
            missing = [name for name in EVENT_REQUIRED if name not in found]
        if draft.bad:
            return _failure(source, now, "bad_value", missing, draft.bad)
        if missing:
            detail = draft.parse_note or f"required fields not found: {', '.join(missing)}"
            return _failure(source, now, "missing_required", missing, detail)

        common = {
            "time": converted["time"],
            "raw_ids": list(source.raw_ids),
            "unmapped": _unused(view, draft.used),
            "extensions": draft.extensions,
        }
        if source.kind == "alert":
            techniques = converted.get("techniques") or list(table.default_techniques or [])
            return validate_contract(
                "NormalizedAlert",
                {
                    "class_uid": table.class_uid,
                    "severity_id": converted["severity_id"],
                    "rule_id": converted["rule_id"],
                    "rule_name": converted["rule_name"],
                    **{name: converted.get(name) for name in ALERT_OPTIONAL},
                    "techniques": techniques,
                    **common,
                },
            )
        return validate_contract(
            "EventRecord",
            {
                "event_id": event_id_for(source.source_record_id),
                "source_record_id": source.source_record_id,
                "class_uid": table.class_uid,
                "activity": table.activity,
                **{name: converted.get(name) for name in EVENT_OPTIONAL},
                "src_asset": None,
                "dst_asset": None,
                "user_info": None,
                **common,
            },
        )

    def _parse(
        self, view: dict, field_name: str, pattern: re.Pattern[str], draft: _Draft
    ) -> str | None:
        """Replace the text at ``field_name`` with its named groups. Returns a too-long reason."""
        path = _path(field_name)
        text = _get(view, path)
        if not isinstance(text, str):
            draft.parse_note = f"{field_name}: no text to parse"
            return None
        if len(text) > self._max_parse_length:
            return f"{field_name}: longer than normalize.max_parse_length"
        match = pattern.fullmatch(text)
        if match is None:
            draft.parse_note = f"{field_name}: parse.pattern did not match"
            return None
        _set(
            view,
            path,
            {name: value for name, value in match.groupdict().items() if value is not None},
        )
        return None


def _pick(
    view: dict, fields: Mapping[str, list[str]], extensions_map: Mapping[str, str], draft: _Draft
) -> None:
    for target, candidates in fields.items():
        for candidate in candidates:
            path = _path(candidate)
            value = _get(view, path)
            if _has_value(value):
                draft.values[target] = value
                draft.sources[target] = path
                draft.used.add(path)
                break
    for source_field, key in extensions_map.items():
        path = _path(source_field)
        value = _get(view, path)
        if _has_value(value):
            draft.extensions[key] = value
            draft.extension_paths.add(path)
            draft.used.add(path)


def _convert(draft: _Draft, time_format: str, severity_map: Mapping[str, int]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    nulled: set[str] = set()
    for target, value in draft.values.items():
        try:
            if target == "time":
                converted[target] = _epoch_ms(value, time_format)
            elif target == "severity_id":
                converted[target] = _severity(value, severity_map)
            elif target in INT_FIELDS:
                integer = _integer(value)
                if target in NON_NEGATIVE_INT_FIELDS and integer < 0:
                    raise BadValue("must be non-negative")
                converted[target] = integer
            elif target == "techniques":
                converted[target] = _text_list(value)
            else:
                converted[target] = _text(value)
        except BadValue as error:
            if target in INT_FIELDS:
                converted[target] = None
                nulled.add(target)
            else:
                draft.bad = draft.bad or f"{target}: {error}"
    # A nulled value goes back to unmapped unless something else still uses its field.
    still_used = {path for target, path in draft.sources.items() if target not in nulled}
    still_used |= draft.extension_paths
    draft.used -= {draft.sources[target] for target in nulled} - still_used
    return converted


def _failure(
    source: SiemAlert, now: int, reason: str, missing: list[str], detail: str
) -> NormalizeFailure:
    return validate_contract(
        "NormalizeFailure",
        {
            "scenario": source.scenario,
            "raw_ids": list(source.raw_ids),
            "reason": reason,
            "missing_fields": missing,
            "detail": detail,
            "failed_at": now,
        },
    )


# Conversions. Each raises BadValue with a reason that does not quote the value.


def _epoch_ms(value: Any, time_format: str) -> int:
    if isinstance(value, bool):
        raise BadValue("does not match time_format")
    if time_format == "epoch_ms":
        return _integer(value, "does not match time_format")
    if time_format == "epoch_s":
        try:
            seconds = Decimal(str(value)) if isinstance(value, int | float | str) else None
        except InvalidOperation:
            seconds = None
        if seconds is None or not seconds.is_finite():
            raise BadValue("does not match time_format")
        return int((seconds * 1000).to_integral_value())
    if not isinstance(value, str):
        raise BadValue("does not match time_format")
    try:
        if time_format == "iso8601":
            moment = datetime.fromisoformat(value)
        else:
            moment = datetime.strptime(value, time_format)
    except ValueError:
        raise BadValue("does not match time_format") from None
    if moment.utcoffset() is None:
        raise BadValue("has no time zone")
    return (moment - EPOCH) // ONE_MS


def _severity(value: Any, severity_map: Mapping[str, int]) -> int:
    key = _text(value)
    if key not in severity_map:
        raise BadValue("value not in severity_map")
    return severity_map[key]


def _integer(value: Any, reason: str = "not an integer") -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and INTEGER_TEXT.fullmatch(value):
        try:
            return int(value)
        except ValueError:
            # Longer than Python's int digit limit; the limit stays as a DoS guard.
            raise BadValue(reason) from None
    raise BadValue(reason)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise BadValue("not text")


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return list(value)
    raise BadValue("not a list of text")


# Nested source fields, addressed by dotted names.


def _path(name: str) -> Path:
    return tuple(name.split("."))


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _get(view: Any, path: Path) -> Any:
    for key in path:
        if not isinstance(view, dict) or key not in view:
            return None
        view = view[key]
    return view


def _set(view: dict, path: Path, value: Any) -> None:
    for key in path[:-1]:
        view = view[key]
    view[path[-1]] = value


def _unused(view: dict, used: set[Path]) -> dict:
    """``view`` without the used values; tables left empty by that removal go too."""
    remaining = copy.deepcopy(view)
    # Shorter paths first, so a path inside one already removed is simply gone.
    for path in sorted(used, key=len):
        parents = [remaining]
        for key in path[:-1]:
            child = parents[-1].get(key)
            if not isinstance(child, dict):
                break
            parents.append(child)
        if len(parents) != len(path) or path[-1] not in parents[-1]:
            continue
        del parents[-1][path[-1]]
        for depth in range(len(path) - 1, 0, -1):
            if parents[depth]:
                break
            del parents[depth - 1][path[depth - 1]]
    return remaining
