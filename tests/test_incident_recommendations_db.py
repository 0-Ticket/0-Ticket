"""권고 조치 마이그레이션 0202: 옛 incident_proposals 행을 새 구조로 옮긴다(#344, D-072)."""

import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl

from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import MIGRATIONS_DIR, migrate
from soc.ticketing import TITLE_SPACES, clean_title

pytestmark = pytest.mark.db

MIGRATION = MIGRATIONS_DIR / "0202_incident_recommendations.sql"
LEGACY = json.loads(
    (Path(__file__).parent / "fixtures" / "l2" / "legacy_proposals.json").read_text("utf-8")
)
NOW = to_datetime(1_793_678_580_000)
INCIDENT_ID = "inc_01a19f93-1150-7000-8000-000000000001"
KIND_RENAMES = {"detection_rule": "detection", "response_action": "response"}


def artifact_id(n: int) -> str:
    return f"art_01a19f93-1150-7000-8000-{n:012d}"


def proposal_id(n: int) -> str:
    return f"prp_01a19f93-1150-7000-8000-{n:012d}"


def insert_incident_and_artifacts(conn: psycopg.Connection, count: int = 1) -> None:
    conn.execute(
        "INSERT INTO incidents (id, title, status, ticket_ids, entities, severity, analysis_round,"
        " review_round, created_at, updated_at, details)"
        " VALUES (%s, '임시 제목', 'awaiting_review', %s, '[]', 3, %s, 0, %s, %s, '{}')",
        (INCIDENT_ID, ["tkt_01a19f93-1150-7000-8000-000000000001"], count, NOW, NOW),
    )
    for round_no in range(1, count + 1):
        conn.execute(
            "INSERT INTO incident_artifacts (id, incident_id, analysis_round, verdict, summary,"
            " assessed_severity, timeline, techniques, impact, cause, further_risk, evidence_ids,"
            " created_at) VALUES (%s, %s, %s, 'attempted', '요약', 3, '[]', '[]', '', '', '',"
            " '{}', %s)",
            (artifact_id(round_no), INCIDENT_ID, round_no, NOW),
        )


def insert_legacy_proposal(
    conn: psycopg.Connection, n: int, kind: str, seq: int, body: str, artifact: int = 1
) -> None:
    """0202 이전 모양(kind가 detection_rule·response_action, body 컬럼)의 행."""
    conn.execute(
        "INSERT INTO incident_proposals (id, artifact_id, kind, seq, body, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (proposal_id(n), artifact_id(artifact), kind, seq, body, NOW),
    )


@pytest.fixture
def migrated_database(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(migrated_database: HiddenUrl) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        yield connection


@pytest.fixture
def legacy_database(temp_database: HiddenUrl, tmp_path: Path) -> HiddenUrl:
    """0202 앞 번호만 적용한 DB. 마이그레이션 전 데이터를 넣는 데 쓴다.

    뒤 번호는 0202이 만드는 칸을 쓸 수 있다(0312의 열 권한). 0202 없이 먼저 적용하면 실패하므로
    0202과 그 뒤는 함께 나중에 적용한다.
    """
    legacy_dir = tmp_path / "legacy_migrations"
    legacy_dir.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name < MIGRATION.name:
            shutil.copyfile(migration, legacy_dir / migration.name)
    migrate(temp_database, legacy_dir)
    return temp_database


def rows(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    cursor = conn.execute(
        "SELECT id, artifact_id, kind, seq, priority, title, detail, rationale, created_at"
        " FROM incident_proposals"
    )
    names = [column.name for column in cursor.description]
    return {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}


def legacy_first_line(body: str) -> str:
    """옛 본문의 첫 줄: 앞쪽 공백 목록을 떼고 첫 줄바꿈 앞까지."""
    stripped = re.sub(f"^[{TITLE_SPACES}]+", "", body)
    return re.split(r"[\r\n]", stripped, maxsplit=1)[0]


def test_migration_passes_on_an_empty_database(legacy_database: HiddenUrl) -> None:
    """옛 행이 0건이어도 적용된다."""
    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        assert rows(after) == {}


def test_new_columns_and_checks_exist_on_an_empty_database(conn: psycopg.Connection) -> None:
    columns = dict(
        conn.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'incident_proposals'"
        ).fetchall()
    )

    assert columns["title"] == "NO"
    assert columns["detail"] == "NO"
    assert columns["priority"] == "YES"
    assert columns["rationale"] == "YES"
    assert "body" not in columns


def test_migration_converts_legacy_rows_to_the_expected_values(
    legacy_database: HiddenUrl,
) -> None:
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        insert_incident_and_artifacts(legacy)
        for i, case in enumerate(LEGACY, start=1):
            insert_legacy_proposal(legacy, i, case["kind"], i, case["body"])

    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        got = rows(after)
    for i, case in enumerate(LEGACY, start=1):
        row = got[proposal_id(i)]
        assert row["kind"] == KIND_RENAMES[case["kind"]], case["case"]
        assert row["detail"] == case["body"], case["case"]
        assert row["title"] == case["expected_title"], case["case"]
        assert row["priority"] is None, case["case"]
        assert row["rationale"] is None, case["case"]


def test_sql_title_and_python_clean_title_agree_on_the_same_inputs(
    legacy_database: HiddenUrl,
) -> None:
    """같은 입력(legacy_proposals.json) 첫 줄의 파이썬 clean_title 값과 SQL 결과가 같다."""
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        insert_incident_and_artifacts(legacy)
        for i, case in enumerate(LEGACY, start=1):
            insert_legacy_proposal(legacy, i, case["kind"], i, case["body"])

    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        got = rows(after)
    for i, case in enumerate(LEGACY, start=1):
        python_title = clean_title(legacy_first_line(case["body"]))
        assert got[proposal_id(i)]["title"] == python_title, case["case"]
        assert python_title == case["expected_title"], case["case"]


def test_migrated_rows_pass_the_stored_contract(legacy_database: HiddenUrl) -> None:
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        insert_incident_and_artifacts(legacy)
        for i, case in enumerate(LEGACY, start=1):
            insert_legacy_proposal(legacy, i, case["kind"], i, case["body"])

    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        got = rows(after)
    for row in got.values():
        validate_contract("incident_proposal", {**row, "created_at": 1_793_678_580_000})


def test_legacy_seq_is_renumbered_across_kinds_detection_first(
    legacy_database: HiddenUrl,
) -> None:
    """옛 seq는 종류별 순번이었다. 이전 정렬(kind, seq)대로 탐지, 대응 순으로 1..n을 매긴다."""
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        insert_incident_and_artifacts(legacy, count=2)
        insert_legacy_proposal(legacy, 1, "response_action", 1, "대응 하나")
        insert_legacy_proposal(legacy, 2, "detection_rule", 1, "탐지 하나")
        insert_legacy_proposal(legacy, 3, "response_action", 2, "대응 둘")
        insert_legacy_proposal(legacy, 4, "detection_rule", 2, "탐지 둘")
        insert_legacy_proposal(legacy, 5, "response_action", 1, "다른 라운드 대응", artifact=2)

    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        got = rows(after)
    assert [
        (row["artifact_id"], row["seq"], row["kind"], row["detail"])
        for row in sorted(got.values(), key=lambda r: (r["artifact_id"], r["seq"]))
    ] == [
        (artifact_id(1), 1, "detection", "탐지 하나"),
        (artifact_id(1), 2, "detection", "탐지 둘"),
        (artifact_id(1), 3, "response", "대응 하나"),
        (artifact_id(1), 4, "response", "대응 둘"),
        (artifact_id(2), 1, "response", "다른 라운드 대응"),
    ]


def test_checks_reject_old_kinds_empty_title_and_bad_priority(conn: psycopg.Connection) -> None:
    insert_incident_and_artifacts(conn)

    def insert(n: int, **values: Any) -> None:
        row = {
            "kind": "detection",
            "seq": n,
            "priority": "high",
            "title": "제목",
            "detail": "상세",
            "rationale": "근거",
            **values,
        }
        conn.execute(
            "INSERT INTO incident_proposals (id, artifact_id, kind, seq, priority, title, detail,"
            " rationale, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                proposal_id(n),
                artifact_id(1),
                row["kind"],
                row["seq"],
                row["priority"],
                row["title"],
                row["detail"],
                row["rationale"],
                NOW,
            ),
        )

    insert(1)
    insert(2, priority=None, rationale=None)  # 옛 행만 갖는 모양이 저장은 허용된다
    for n, bad in enumerate(
        [
            {"kind": "detection_rule"},
            {"kind": "response_action"},
            {"priority": "critical"},
            {"title": ""},
            {"title": " \t　"},
            {"detail": ""},
        ],
        start=3,
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            insert(n, **bad)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert(9, seq=1)  # 같은 Artifact의 seq는 종류와 무관하게 하나다


def test_title_check_and_clean_title_use_the_same_spaces(conn: psycopg.Connection) -> None:
    """마이그레이션 파일의 title CHECK 정규식이 공백으로 보는 글자가 clean_title의 목록과 같다."""
    literal = re.search(r"title ~ E'([^']*)'", MIGRATION.read_text(encoding="utf-8"))
    assert literal is not None
    regex = literal.group(1).replace("\\\\", "\\")

    rows_ = conn.execute(
        "SELECT chr(i) FROM generate_series(1, 65535) AS i"
        " WHERE i NOT BETWEEN 55296 AND 57343 AND chr(i) !~ %s",
        (regex,),
    ).fetchall()

    assert {row[0] for row in rows_} == set(TITLE_SPACES)
