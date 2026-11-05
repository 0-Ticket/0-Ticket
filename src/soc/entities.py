"""Entity 값을 비교 가능한 모양으로 만든다. L2 분류와 자산 조회가 같은 규칙을 쓴다."""

import ipaddress

_LOWER_TYPES = {"host", "domain", "file_hash", "user"}


def normalize_entity_value(entity_type: str, value: str) -> str:
    """Entity type의 비교 규칙으로 값 하나를 정규화한다.

    Args:
        entity_type: Entity 종류(ip, host, user, domain, url, file_hash, process).
        value: 정규화할 원래 값.
    """
    value = value.strip()
    if entity_type == "ip":
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return value.lower()
    if entity_type in _LOWER_TYPES:
        return value.lower()
    return value
