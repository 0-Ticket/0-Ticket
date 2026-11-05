"""실제 LLM으로 L3 검증 run 1건(#224, llm·db 마커). 기본 실행과 CI에서는 돌지 않는다.

실행: DATABASE_URL=… LLM_API_KEY=… uv run pytest -m llm tests/test_l3_hunt_llm.py
- 모델 연결은 config/local.toml의 [llm](키는 환경변수 LLM_API_KEY), 도구 허용 목록도 그 설정을 쓴다
- 임시 DB에 개발용 시드를 넣고 위협 있음 Hunt 하나를 운영 경로(run_agent)로 검증한다
- 도구는 테스트가 만든 임시 읽기 계정(soc_agent_reader 멤버)으로 임시 DB를 읽는다
- 결과 값(confirmed인지)은 모델마다 달라 단언하지 않는다. 출력 계약 통과와 Agent Log만 본다
- 실제 호출 비용이 든다(검증 run 1번, 최대 [agent.l3] max_turns 턴)
"""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo

from soc.db.migrate import migrate
from soc.l3.config import load_config
from soc.l3.hunt.dev_seed import seed
from soc.l3.hunt.settings import read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier

pytestmark = [pytest.mark.llm, pytest.mark.db]

READER = "soc_agent_reader"


@pytest.fixture
def seeded(temp_database: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """시드를 넣은 임시 DB. run_agent·도구가 이 DB를 쓰게 환경변수를 바꾼다."""
    migrate(temp_database)
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(temp_database, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
    monkeypatch.setenv("DATABASE_URL", temp_database)  # run_agent가 Agent Log를 쓰는 곳
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", make_conninfo(temp_database, user=name, password=password)
    )
    try:
        yield temp_database
    finally:
        with psycopg.connect(temp_database, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def test_real_model_verifies_seeded_threat_hunt(seeded: HiddenUrl) -> None:
    with psycopg.connect(seeded, autocommit=True) as conn:
        hunt_id = seed(conn, now=datetime.now(UTC)).hunt_ids["threat"]
    settings = read_hunt_settings(load_config()["l3"])

    HuntVerifier(seeded, settings).handle(hunt_id)  # 기본 실행 함수는 run_agent

    with psycopg.connect(seeded) as conn:
        status, attempts, details = conn.execute(
            "SELECT status, attempts, details FROM hunts WHERE id = %s", (hunt_id,)
        ).fetchone()  # type: ignore[misc]
        (logs,) = conn.execute(
            "SELECT count(*) FROM agent_logs WHERE subject_type = 'hunt' AND subject_id = %s",
            (hunt_id,),
        ).fetchone()  # type: ignore[misc]
        (tickets,) = conn.execute(
            "SELECT count(*) FROM tickets WHERE hunt_id = %s", (hunt_id,)
        ).fetchone()  # type: ignore[misc]
    assert attempts == 1
    # 실패하면 details.verify_failures의 실패 종류(failure)만 보인다. 본문은 보이지 않는다
    failures = [f["failure"] for f in details.get("verify_failures", [])]
    assert status in ("confirmed", "rejected", "inconclusive"), failures
    assert logs >= 1
    assert tickets == (1 if status == "confirmed" else 0)
