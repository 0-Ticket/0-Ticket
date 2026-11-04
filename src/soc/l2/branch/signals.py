"""엔티티 값을 비교 가능한 모양으로 만들고 분류 신호 등급을 매긴다."""

import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from soc.l2.config import BranchSettings

SignalLevel = Literal["strong", "weak", "shared"]
_LOWER_TYPES = {"host", "domain", "file_hash", "user"}


@dataclass(frozen=True)
class EntitySignal:
    type: str
    value: str
    role: str | None
    level: SignalLevel

    @property
    def key(self) -> tuple[str, str]:
        return self.type, self.value


def normalize_value(entity_type: str, value: str) -> str:
    """Entity type의 비교 규칙으로 값 하나를 정규화한다."""
    value = value.strip()
    if entity_type == "ip":
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return value.lower()
    if entity_type in _LOWER_TYPES:
        return value.lower()
    return value


def classify_entities(
    entities: Iterable[Mapping[str, Any]], settings: BranchSettings
) -> tuple[EntitySignal, ...]:
    """role을 보존하되 (type, value) 중복은 처음 한 번만 남긴다."""
    signals = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        entity_type = cast(str, entity["type"])
        value = normalize_value(entity_type, cast(str, entity["value"]))
        key = (entity_type, value)
        if key in seen:
            continue
        seen.add(key)
        shared = any(
            normalize_value(entity_type, configured) == value
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
