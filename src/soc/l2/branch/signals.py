"""엔티티 값을 비교 가능한 모양으로 만들고 분류 신호 등급을 매긴다."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from soc.entities import normalize_entity_value
from soc.l2.config import BranchSettings

SignalLevel = Literal["strong", "weak", "shared"]


@dataclass(frozen=True)
class EntitySignal:
    type: str
    value: str
    role: str | None
    level: SignalLevel

    @property
    def key(self) -> tuple[str, str]:
        return self.type, self.value


def classify_entities(
    entities: Iterable[Mapping[str, Any]], settings: BranchSettings
) -> tuple[EntitySignal, ...]:
    """role을 보존하되 (type, value) 중복은 처음 한 번만 남긴다."""
    signals = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        entity_type = cast(str, entity["type"])
        value = normalize_entity_value(entity_type, cast(str, entity["value"]))
        key = (entity_type, value)
        if key in seen:
            continue
        seen.add(key)
        shared = any(
            normalize_entity_value(entity_type, configured) == value
            for configured in settings.shared_entity_values
        )
        if shared:
            level: SignalLevel = "shared"
        elif entity_type in settings.strong_signal_types:
            level = "strong"
        elif entity_type in settings.weak_signal_types:
            level = "weak"
        else:
            raise ValueError("설정에 없는 Entity type이다")
        signals.append(
            EntitySignal(entity_type, value, cast(str | None, entity.get("role")), level)
        )
    return tuple(signals)
