"""Normalized record IDs, taken from the source record they come from.

A source record has at most one normalized result, so its hash is a stable,
unique ID: running normalization again names the same record the same way.
"""

SOURCE_PREFIX = "src_"


def alert_id_for(source_record_id: str) -> str:
    return "al_" + source_record_id.removeprefix(SOURCE_PREFIX)


def event_id_for(source_record_id: str) -> str:
    return "ev_" + source_record_id.removeprefix(SOURCE_PREFIX)
