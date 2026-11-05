"""자산 조회의 키 만들기, 묶음 나누기, 시간 상한, 실패 전달을 가짜 연결로 확인한다."""

from contextlib import nullcontext
from typing import Any

import psycopg
import pytest

from soc.asset_lookup import BATCH_SIZE, AssetLookupError, lookup_assets

TIMEOUT_MS = 5000


class FakeConn:
    """execute가 받은 문장과 매개변수를 모으고, 미리 정한 행을 돌려준다."""

    def __init__(self, rows: list[tuple[Any, ...]], error: Exception | None = None) -> None:
        """
        Args:
            rows: 자산 조회 문장이 돌려줄 행.
            error: 있으면 execute가 던질 예외.
        """
        self.rows = rows
        self.error = error
        self.timeouts: list[tuple[str]] = []
        self.lookups: list[tuple[list[str], list[str]]] = []
        self.current: list[tuple[Any, ...]] = []

    def transaction(self) -> Any:
        return nullcontext()

    def execute(self, query: str, params: tuple[Any, ...]) -> "FakeConn":
        """
        Args:
            query: 실행할 문장. set_config가 들었는지만 본다.
            params: set_config면 (시간 상한 문자열,), 조회면 (type 목록, 정규화한 값 목록).
        """
        if self.error:
            raise self.error
        if "set_config" in query:
            self.timeouts.append(params)
            self.current = []
        else:
            self.lookups.append(params)
            self.current = self.rows
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.current


def entity(entity_type: str, value: str) -> dict[str, str]:
    """조회에 넘길 Entity 객체를 만든다.

    Args:
        entity_type: Entity 종류.
        value: Entity 값.
    """
    return {"type": entity_type, "value": value}


def test_keys_are_normalized_and_deduplicated_in_request_order() -> None:
    conn = FakeConn(
        [("host", "web-01", "웹서버", 5, None), ("ip", "198.51.100.7", None, None, "팀")]
    )
    entities = [
        entity("ip", " 198.51.100.7 "),
        entity("host", "WEB-01"),
        entity("host", "web-01"),
        entity("user", "   "),
    ]

    assets = lookup_assets(conn, entities, TIMEOUT_MS)  # type: ignore[arg-type]

    assert conn.lookups == [(["ip", "host"], ["198.51.100.7", "web-01"])]
    assert assets == [
        {
            "entity": {"type": "ip", "value": "198.51.100.7"},
            "name": None,
            "criticality": None,
            "owner": "팀",
        },
        {
            "entity": {"type": "host", "value": "web-01"},
            "name": "웹서버",
            "criticality": 5,
            "owner": None,
        },
    ]


def test_unmatched_keys_are_left_out() -> None:
    conn = FakeConn([])

    assert lookup_assets(conn, [entity("host", "unknown-01")], TIMEOUT_MS) == []  # type: ignore[arg-type]


def test_no_entities_means_no_lookup_query() -> None:
    conn = FakeConn([])

    assert lookup_assets(conn, [], TIMEOUT_MS) == []  # type: ignore[arg-type]
    assert conn.lookups == []


def test_statement_timeout_is_set_for_the_lookup() -> None:
    conn = FakeConn([])

    lookup_assets(conn, [entity("host", "web-01")], 1234)  # type: ignore[arg-type]

    assert conn.timeouts == [("1234",)]


def test_keys_are_sent_in_batches() -> None:
    conn = FakeConn([])
    entities = [entity("ip", f"192.0.2.{n % 256}.{n // 256}") for n in range(BATCH_SIZE * 2 + 1)]

    lookup_assets(conn, entities, TIMEOUT_MS)  # type: ignore[arg-type]

    assert [len(types) for types, _ in conn.lookups] == [BATCH_SIZE, BATCH_SIZE, 1]


@pytest.mark.parametrize(
    "error", [psycopg.OperationalError("secret detail"), psycopg.errors.QueryCanceled()]
)
def test_database_errors_become_one_safe_error(error: Exception) -> None:
    with pytest.raises(AssetLookupError) as raised:
        lookup_assets(FakeConn([], error), [entity("host", "web-01")], TIMEOUT_MS)  # type: ignore[arg-type]

    assert raised.value.code == "asset_lookup_failed"
    assert "secret" not in str(raised.value)
