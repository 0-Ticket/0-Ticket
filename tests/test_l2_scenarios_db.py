"""L2 분류 시나리오(#356)를 임시 DB에서 그래프 단계부터 저장까지 확인한다(db 마커).

LLM은 부르지 않는다. 후보가 있는 케이스는 가짜 `run`이 답한다. 실제 모델의 판단은 사람이 따로
확인한다(tests/test_l2_scenarios_llm.py). 샘플은 tests/fixtures/l2/scenarios/cases.json이다.

`expect`는 D-027대로 동작할 때의 결과다. 분류가 "불일치(결함)"인 케이스는 지금 코드가 이 결과를
내지 못한다는 뜻이라 strict xfail로 둔다. 고치면 이 표시를 지운다.
"""

from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from scenario_support import CASES, NOW, Built, build_case, fill_incident

from soc.agent import AgentResult
from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import BranchSettings

pytestmark = pytest.mark.db

SETTINGS = BranchSettings(candidate_window_ms=86_400_000, max_candidates=5, max_incident_tickets=10)


class FakeRun:
    """후보가 있을 때만 불리는 가짜 `run`. 부른 작업을 모으고 정해 둔 답을 낸다."""

    def __init__(self, decision: str, on_call: Any = None) -> None:
        self.decision = decision
        self.on_call = on_call
        self.tasks: list[Any] = []

    def __call__(self, task: Any) -> AgentResult:
        self.tasks.append(task)
        if self.on_call is not None:
            self.on_call()
        first = task.data["candidates"][0]["incident_id"]
        existing = self.decision == "existing"
        return AgentResult(
            ok=True,
            output={
                "decision": self.decision,
                "incident_id": first if existing else None,
                "confidence": 0.9,
                "reason": "가짜 모델",
                "similar_ticket_ids": [],
            },
            failure=None,
            detail=None,
            run_id="run_01a19f93-1150-7000-8000-000000000601",
        )


def params() -> list[Any]:
    out = []
    for case in CASES:
        marks = []
        if case["classification"] == "불일치(결함)":
            marks.append(
                pytest.mark.xfail(
                    strict=True, reason="결함 후보(#356): 지금 코드가 D-027 결과를 못 낸다"
                )
            )
        out.append(pytest.param(case, id=case["case"], marks=marks))
    return out


def outcome(
    conn: psycopg.Connection, built: Built, fake: FakeRun
) -> tuple[list[str], str, dict[str, Any]]:
    """(후보 이름 목록, 지금 Ticket이 붙은 곳 "new" 또는 "existing:이름", l2_branch 상세)."""
    names = {incident_id: name for name, incident_id in built.incidents.items()}
    candidates = [names[c["incident_id"]] for task in fake.tasks for c in task.data["candidates"]]
    row = conn.execute(
        "SELECT status, details->'l2_branch' FROM tickets WHERE id = %s",
        (built.current_ticket_id,),
    ).fetchone()
    assert row[0] == "linked"
    joined = conn.execute(
        "SELECT id FROM incidents WHERE %s = ANY(ticket_ids)", (built.current_ticket_id,)
    ).fetchone()[0]
    result = "new" if joined not in names else f"existing:{names[joined]}"
    return candidates, result, row[1]


@pytest.mark.parametrize("case", params())
def test_scenario_matches_the_graph_rules(temp_database: HiddenUrl, case: dict[str, Any]) -> None:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        built = build_case(conn, case)
        race = case.get("race_fill")
        fake = FakeRun(
            case.get("fake_decision", "new"),
            on_call=(lambda: fill_incident(conn, case, built.incidents[race])) if race else None,
        )
        L2BranchWorker(temp_database, SETTINGS, run=fake, clock=lambda: to_datetime(NOW)).handle(
            built.current_ticket_id
        )

        candidates, result, details = outcome(conn, built, fake)

    expect = case["expect"]
    assert (details["coverage"], details["reason"]) == (expect["coverage"], expect["reason"])
    assert candidates == expect["candidates"]
    assert bool(fake.tasks) == expect["llm_called"]
    assert result == expect["result"]
    fallback = expect.get("fallback", None if expect["llm_called"] else expect["reason"])
    assert details["decision_fallback"] == fallback


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("5-same-local-ip-different-environments", ["111111111111", "i-0aaaaaaaaaaaaaaaa"]),
        ("5b-same-local-ip-same-environment", ["111111111111", "i-0aaaaaaaaaaaaaaaa"]),
        ("5c-same-public-src-different-environments", ["111111111111", "i-0aaaaaaaaaaaaaaaa"]),
        ("1a-same-source-same-src-ip", None),
    ],
)
def test_candidate_input_carries_the_path_alerts_target_hosts(
    temp_database: HiddenUrl, name: str, expected: list[str] | None
) -> None:
    case = next(item for item in CASES if item["case"] == name)
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        built = build_case(conn, case)
        fake = FakeRun("new")
        L2BranchWorker(temp_database, SETTINGS, run=fake, clock=lambda: to_datetime(NOW)).handle(
            built.current_ticket_id
        )

    summary = fake.tasks[0].data["candidates"][0]
    assert summary.get("target_hosts") == expected
    assert ("target_hosts" in summary) == (expected is not None)
