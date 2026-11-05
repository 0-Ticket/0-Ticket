"""자산 조회(#241). Entity의 자산 정보를 찾아 붙인다.

- 조회 키는 (Entity type, 정규화한 Entity 값)이다. role은 쓰지 않는다.
- 자산이 없는 키는 결과에 넣지 않는다(성공한 불일치). 조회를 끝내지 못하면 AssetLookupError다.
- 예외 메시지에는 SQL, 주소, Entity 원문을 넣지 않는다.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from soc.entities import normalize_entity_value

BATCH_SIZE = 500

_QUERY = """
SELECT i.entity_type, i.entity_value, a.name, a.criticality, a.owner
FROM asset_identifiers i
JOIN assets a USING (asset_id)
WHERE (i.entity_type, i.entity_value) IN (
    SELECT * FROM unnest(%s::text[], %s::text[])
)
"""


class AssetLookupError(Exception):
    """조회를 끝내지 못했다. 성공한 불일치와 다르다.

    Attributes:
        code: 항상 "asset_lookup_failed".
    """

    code = "asset_lookup_failed"


def lookup_assets(
    conn: psycopg.Connection, entities: Sequence[Mapping[str, Any]], statement_timeout_ms: int
) -> list[dict[str, Any]]:
    """Entity 목록에 일치하는 자산을 요청에 처음 나온 키 순서로 돌려준다.

    조회는 읽기만 하는 한 트랜잭션이고, 문장 시간 상한은 그 트랜잭션에만 적용된다.

    Args:
        conn: DB 연결(autocommit).
        entities: type, value 키를 가진 Entity 객체 목록. 같은 키는 한 번만 조회하고,
            공백을 지운 값이 비면 조회하지 않는다.
        statement_timeout_ms: 조회 문장 하나의 시간 상한(밀리초).

    Raises:
        AssetLookupError: 조회를 끝내지 못했다.
    """
    keys = _unique_keys(entities)
    found: dict[tuple[str, str], tuple[Any, Any, Any]] = {}
    try:
        with conn.transaction():
            conn.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(statement_timeout_ms),)
            )
            for start in range(0, len(keys), BATCH_SIZE):
                batch = keys[start : start + BATCH_SIZE]
                rows = conn.execute(_QUERY, ([k[0] for k in batch], [k[1] for k in batch]))
                for entity_type, value, name, criticality, owner in rows.fetchall():
                    found[(entity_type, value)] = (name, criticality, owner)
    except psycopg.Error:
        raise AssetLookupError from None
    return [
        {
            "entity": {"type": key[0], "value": key[1]},
            "name": found[key][0],
            "criticality": found[key][1],
            "owner": found[key][2],
        }
        for key in keys
        if key in found
    ]


def _unique_keys(entities: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """조회 키(type, 정규화한 값)를 처음 나온 순서로 중복 없이 만든다. 값이 비면 건너뛴다.

    Args:
        entities: type, value 키를 가진 Entity 객체 목록.
    """
    keys: dict[tuple[str, str], None] = {}
    for entity in entities:
        value = normalize_entity_value(entity["type"], entity["value"])
        if value:
            keys[(entity["type"], value)] = None
    return list(keys)
