"""Alert -> entity list (boxes 25, 11; C5 -> list[Entity]).

The one place that says which C5 fields are entities, shared by box 25 (the
scenario Ticket's entities, the dedup key and the representative entity) and
box 11 (entity lookup). The order is fixed and documented in
docs/architecture.md 25: ``src_ip`` -> ip, ``dst_ip`` -> ip, ``host`` -> host,
``user`` -> user. The first entity is the alert's representative entity.

An empty value (None, "", or only whitespace) is left out, and an entity
already in the list is not repeated. Values are kept as they are: they come
from the log and are data only (docs/security-policy.md 3).
"""

from typing import Any

from soc.contracts import AlertRecord, validate_contract

# (C5 field, Entity type), in output order.
ENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("src_ip", "ip"),
    ("dst_ip", "ip"),
    ("host", "host"),
    ("user", "user"),
)


def alert_entities(alert: AlertRecord) -> list[dict[str, Any]]:
    """The C5's entities as validated Entity dicts, in the fixed order without repeats."""
    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for field, entity_type in ENTITY_FIELDS:
        value = getattr(alert, field)
        if value is None or not value.strip():
            continue
        key = (entity_type, value)
        if key in seen:
            continue
        seen.add(key)
        entity = {"type": entity_type, "value": value}
        entities.append(validate_contract("Entity", entity).model_dump(mode="json"))
    return entities
