"""incident_reviews 표(0307, #375, D-082)의 제약과 에이전트 읽기 역할의 접근 차단(db 마커).

샘플: tests/fixtures/api/ui_seed.json(손으로 만든 시드). Incident 2가 awaiting_review다.
"""

import psycopg
import pytest
from psycopg import errors
from test_api_ui import INC, SEED, insert_row

from soc.db.migrate import migrate

pytestmark = pytest.mark.db

REVIEW = INC["2"]
READER = "soc_agent_reader"


@pytest.fixture
def conn(temp_database):
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as c:
        for table, rows in SEED.items():
            for row in rows:
                insert_row(c, table, row)
        yield c


def add(conn, **values):
    row = {
        "incident_id": REVIEW,
        "decision": "reject",
        "reason": None,
        "decided_by": "tester",
        "review_round": 1,
        "analysis_round": 0,
        **values,
    }
    return conn.execute(
        "INSERT INTO incident_reviews (incident_id, decision, reason, decided_by, review_round, "
        "analysis_round) VALUES (%(incident_id)s, %(decision)s, %(reason)s, %(decided_by)s, "
        "%(review_round)s, %(analysis_round)s) RETURNING id",
        row,
    ).fetchone()[0]


def test_primary_key_is_a_generated_integer_with_no_id_prefix(conn):
    first, second = add(conn), add(conn, review_round=2)
    assert isinstance(first, int) and second == first + 1
    with pytest.raises(errors.GeneratedAlways):
        conn.execute(
            "INSERT INTO incident_reviews (id, incident_id, decision, decided_by, "
            "review_round, analysis_round) VALUES (99, %s, 'reject', 'u', 3, 0)",
            (REVIEW,),
        )


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"decision": "dismiss"}, errors.CheckViolation),
        ({"reason": ""}, errors.CheckViolation),
        ({"reason": "가" * 501}, errors.CheckViolation),
        ({"decision": "approve", "reason": "승인에는 사유가 없다"}, errors.CheckViolation),
        ({"review_round": 0}, errors.CheckViolation),
        ({"analysis_round": -1}, errors.CheckViolation),
        ({"decided_by": None}, errors.NotNullViolation),
        ({"incident_id": "inc_01a19f93-1266-7000-8000-0000000000ff"}, errors.ForeignKeyViolation),
    ],
)
def test_constraints_refuse_bad_rows(conn, values, error):
    with pytest.raises(error):
        add(conn, **values)


def test_a_reason_of_500_code_points_is_stored(conn):
    add(conn, reason="😀" * 500)


def test_one_incident_cannot_have_two_rows_for_the_same_review_round(conn):
    add(conn)
    with pytest.raises(errors.UniqueViolation):
        add(conn, decision="approve")
    add(conn, incident_id=INC["1"])  # 다른 Incident는 같은 번호를 쓸 수 있다


def test_agent_reader_cannot_read_incident_reviews(conn):
    """사람이 쓴 사유를 에이전트 도구가 읽지 못한다. 표 단위와 열 단위 권한 모두 없다."""
    add(conn, reason="비공개 사유")
    assert conn.execute(
        "SELECT has_table_privilege(%s, 'incident_reviews', 'SELECT')", (READER,)
    ).fetchone() == (False,)
    assert conn.execute(
        "SELECT has_any_column_privilege(%s, 'incident_reviews', 'SELECT')", (READER,)
    ).fetchone() == (False,)
    conn.execute(f"SET ROLE {READER}")
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT reason FROM incident_reviews")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM incident_reviews")
    finally:
        conn.execute("RESET ROLE")
