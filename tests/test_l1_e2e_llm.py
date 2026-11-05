"""실제 LLM으로 L1 판정 1건(#215, llm 마커). 기본 실행과 CI에서는 돌지 않는다.

DB도 쓰지만 db 마커는 붙이지 않는다. CI의 db job(uv run pytest -m db)이 이 테스트를
고르지 않게 하기 위해서다.

실행: DATABASE_URL=… LLM_API_KEY=… uv run pytest -m llm tests/test_l1_e2e_llm.py
- 모델 연결은 config/local.toml의 [llm](키는 환경변수 LLM_API_KEY), 도구 허용 목록도 그 설정을 쓴다.
  ELK가 없으면 [tools.allowed] l1에서 query_siem을 뺀다(docs/notes/215-executor-l1-e2e.md)
- 임시 DB에 L1 시드를 넣고 위협 Alert 하나를 L1 워커 없이 run_agent로 판정한다
- 도구는 테스트가 만든 임시 읽기 계정(soc_agent_reader 멤버)으로 임시 DB를 읽는다
- decision 값은 모델마다 달라 단언하지 않는다. Verdict 계약 통과·근거 장부·Agent Log만 본다
- 실제 호출 비용이 든다(run 1번, 최대 [agent.l1] max_turns 턴)
"""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo

from soc.agent import run_agent
from soc.agent.dev_l1 import build_task, load_seed, seed, seeded_alerts, task_prompt
from soc.contracts import validate_contract
from soc.db.migrate import migrate

pytestmark = pytest.mark.llm

READER = "soc_agent_reader"
SCENARIO = "malicious_powershell"


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
        seed(admin, now=datetime.now(UTC))
    monkeypatch.setenv("DATABASE_URL", temp_database)  # run_agent가 Agent Log를 쓰는 곳
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", make_conninfo(temp_database, user=name, password=password)
    )
    try:
        yield temp_database
    finally:
        with psycopg.connect(temp_database, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def test_real_model_judges_seeded_alert(seeded: HiddenUrl) -> None:
    with psycopg.connect(seeded, autocommit=True) as conn:
        alert = next(a.alert for a in seeded_alerts(conn) if a.scenario == SCENARIO)

    result = run_agent(build_task(alert, task_prompt(load_seed())))

    # 실패하면 실패 종류(failure)만 보인다. detail은 안전한 문장이지만 단언 메시지에 넣지 않는다
    assert result.ok, result.failure
    validate_contract("verdict", result.output)  # run_agent가 이미 검사했다. 한 번 더 본다
    with psycopg.connect(seeded) as conn:
        rows = conn.execute(
            "SELECT id, kind, outcome FROM agent_logs WHERE run_id = %s ORDER BY seq",
            (result.run_id,),
        ).fetchall()
        known = {
            r[0]
            for r in conn.execute(
                "SELECT id FROM alerts UNION ALL SELECT id FROM events"
            ).fetchall()
        }
    assert any(kind == "model" for _, kind, _ in rows)
    # 인용한 근거는 Alert·Event이거나 이 run의 성공한 도구 호출 기록이다(근거 장부)
    tool_ok = {i for i, kind, outcome in rows if kind == "tool" and outcome == "ok"}
    assert set(result.cited_evidence_ids) <= known | tool_ok
    assert result.output["evidence_ids"] == result.cited_evidence_ids
    assert result.usage["turns"] >= 1
