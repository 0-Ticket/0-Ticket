"""알럿↔원본 이벤트 연결(raw_links)을 실제 PostgreSQL로 확인한다(#218 후속, db 마커).

연결 키를 알럿 문서의 어느 필드에서 읽는지는 아직 확인되지 않아 다루지 않는다.
합성 siem_ref 쌍으로 저장 규칙만 본다.
"""

from collections.abc import Iterator

import psycopg
import pytest

from soc.db.migrate import migrate
from soc.ingest.store import link_by_refs

pytestmark = pytest.mark.db

PROFILE = "elk-test"


@pytest.fixture
def conn(temp_database: str) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def insert_raw(conn: psycopg.Connection, ref: str, kind: str, profile: str = PROFILE) -> None:
    """siem_ref가 ref인 원본 한 행을 넣는다. id는 ref에서 만든다."""
    conn.execute(
        "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original)"
        " VALUES (%s, %s, %s, %s, now(), '{}'::jsonb)",
        (f"raw_{profile}_{ref}", kind, profile, ref),
    )


def link_rows(conn: psycopg.Connection) -> set[tuple[str, str]]:
    """저장된 연결을 (알럿 siem_ref, 이벤트 siem_ref) 집합으로 읽는다."""
    rows = conn.execute(
        "SELECT a.siem_ref, e.siem_ref FROM raw_links l"
        " JOIN raw_records a ON a.id = l.raw_id JOIN raw_records e ON e.id = l.source_raw_id"
    ).fetchall()
    return set(rows)


def test_links_are_saved_and_many_to_many_works(conn: psycopg.Connection) -> None:
    for ref in ("idx/a1", "idx/a2"):
        insert_raw(conn, ref, "alert")
    for ref in ("idx/e1", "idx/e2"):
        insert_raw(conn, ref, "event")
    # 알럿 하나가 이벤트 둘을 가리키고, 이벤트 하나가 알럿 둘에 쓰인다
    pairs = [("idx/a1", "idx/e1"), ("idx/a1", "idx/e2"), ("idx/a2", "idx/e1")]

    assert link_by_refs(conn, PROFILE, pairs) == (3, [])
    assert link_rows(conn) == set(pairs)


def test_saving_the_same_pairs_again_links_nothing_and_is_not_pending(
    conn: psycopg.Connection,
) -> None:
    insert_raw(conn, "idx/a1", "alert")
    insert_raw(conn, "idx/e1", "event")
    link_by_refs(conn, PROFILE, [("idx/a1", "idx/e1")])

    assert link_by_refs(conn, PROFILE, [("idx/a1", "idx/e1")]) == (0, [])
    assert link_rows(conn) == {("idx/a1", "idx/e1")}


def test_missing_event_is_pending_then_links_after_it_arrives(conn: psycopg.Connection) -> None:
    insert_raw(conn, "idx/a1", "alert")
    pair = ("idx/a1", "idx/e1")

    # 이벤트 원본이 아직 없으면 연결하지 않고 보류로 돌려준다
    assert link_by_refs(conn, PROFILE, [pair]) == (0, [pair])
    assert link_rows(conn) == set()

    # 이벤트가 들어온 뒤 같은 쌍을 다시 넘기면 연결된다(순서 무관)
    insert_raw(conn, "idx/e1", "event")
    assert link_by_refs(conn, PROFILE, [pair]) == (1, [])


def test_missing_alert_is_pending(conn: psycopg.Connection) -> None:
    insert_raw(conn, "idx/e1", "event")
    pair = ("idx/a1", "idx/e1")

    assert link_by_refs(conn, PROFILE, [pair]) == (0, [pair])


def test_pending_pair_does_not_block_the_others(conn: psycopg.Connection) -> None:
    insert_raw(conn, "idx/a1", "alert")
    insert_raw(conn, "idx/e1", "event")

    result = link_by_refs(conn, PROFILE, [("idx/a1", "idx/missing"), ("idx/a1", "idx/e1")])

    assert result == (1, [("idx/a1", "idx/missing")])
    assert link_rows(conn) == {("idx/a1", "idx/e1")}


def test_only_the_given_profile_and_kind_are_matched(conn: psycopg.Connection) -> None:
    insert_raw(conn, "idx/a1", "alert")
    insert_raw(conn, "idx/e1", "event", profile="other-siem")  # 다른 프로필의 이벤트
    insert_raw(conn, "idx/e2", "alert")  # 이벤트 자리에 알럿 원본

    pairs = [("idx/a1", "idx/e1"), ("idx/a1", "idx/e2")]

    assert link_by_refs(conn, PROFILE, pairs) == (0, pairs)
    assert link_rows(conn) == set()


def test_failure_rolls_back_the_whole_batch(conn: psycopg.Connection) -> None:
    for ref in ("idx/e1", "idx/e2"):
        insert_raw(conn, ref, "event")
    insert_raw(conn, "idx/a1", "alert")
    # 두 번째 연결을 넣을 때 실패하도록 DB에서 막는다
    conn.execute(
        "CREATE FUNCTION reject_second() RETURNS trigger AS $$ BEGIN"
        " IF NEW.source_raw_id = 'raw_elk-test_idx/e2' THEN RAISE EXCEPTION 'blocked'; END IF;"
        " RETURN NEW; END $$ LANGUAGE plpgsql"
    )
    conn.execute(
        "CREATE TRIGGER reject_second BEFORE INSERT ON raw_links"
        " FOR EACH ROW EXECUTE FUNCTION reject_second()"
    )

    with pytest.raises(psycopg.errors.RaiseException):
        link_by_refs(conn, PROFILE, [("idx/a1", "idx/e1"), ("idx/a1", "idx/e2")])

    assert link_rows(conn) == set()
