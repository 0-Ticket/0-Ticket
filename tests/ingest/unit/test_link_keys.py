"""link_by_refs는 저장 키 쌍만 받는다. DB 없이 조회 키 글자만 본다(#277, D-049)."""

import contextlib
from typing import Any

from soc.ids import siem_ref_key
from soc.ingest.store import link_by_refs

PROFILE = "elk-test"
ODD_REF = '.ds-logs-web-default-2026.11.04-000001/q"b\\s\x01z\x00한글'
EVENT_REF = ".ds-logs-web-default-2026.11.04-000002/evt-plain"


class StoredKeysConn:
    """raw_records에 저장 키 행이 있다고 치는 가짜 연결. 조회한 키를 기록한다."""

    def __init__(self, stored: set[tuple[str, str, str]]) -> None:
        self.stored = stored
        self.lookups: list[tuple[str, str, str]] = []
        self.links = 0

    def transaction(self) -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()

    def execute(self, sql: str, params: tuple[Any, ...]) -> "StoredKeysConn":
        if "INSERT INTO raw_links" in sql:
            self.links += 1
            self.rowcount = 1
        else:
            self.lookups.append(params)
            self.row = (params,) if params in self.stored else None
        return self

    def fetchone(self) -> Any:
        return self.row


def stored() -> set[tuple[str, str, str]]:
    return {
        (PROFILE, "alert", siem_ref_key(ODD_REF)),
        (PROFILE, "event", siem_ref_key(EVENT_REF)),
    }


def test_original_form_with_a_quote_does_not_match_and_is_pending() -> None:
    conn = StoredKeysConn(stored())
    pair = (ODD_REF, EVENT_REF)

    linked, pending = link_by_refs(conn, PROFILE, [pair])  # type: ignore[arg-type]

    assert (linked, pending) == (0, [pair])
    # 조회는 받은 글자 그대로 한다(이 함수 안에서 이스케이프하지 않는다)
    assert conn.lookups[0] == (PROFILE, "alert", ODD_REF)


def test_stored_key_matches_and_links() -> None:
    conn = StoredKeysConn(stored())
    pair = (siem_ref_key(ODD_REF), siem_ref_key(EVENT_REF))

    linked, pending = link_by_refs(conn, PROFILE, [pair])

    assert (linked, pending) == (1, [])
    assert conn.lookups == [(PROFILE, "alert", pair[0]), (PROFILE, "event", pair[1])]
