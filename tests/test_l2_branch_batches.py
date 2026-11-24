"""후보가 5개를 넘을 때의 이어가기와 최종 비교를 DB 없이 검증한다."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from soc.agent import AgentResult
from soc.l2.branch import candidates as candidate_module
from soc.l2.branch.decide import Candidate
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import BranchSettings
from soc.store.qdrant import SearchHit


def test_tied_score_pages_are_reloaded_without_missing_hits(monkeypatch) -> None:
    monkeypatch.setattr(candidate_module, "_PAGE", 2)
    hits = tuple(SearchHit(str(n), 1.0, {"linked": True}) for n in range(3))

    class Store:
        def search(self, _vector, limit, _filter, *, offset=0, score_threshold=0):
            assert score_threshold == 0.8
            if limit == 3:
                return hits
            return (hits[0], hits[1]) if offset == 0 else (hits[1], hits[2]) if offset == 2 else ()

        def count(self):
            return 3

    found = candidate_module._search_all(SimpleNamespace(store=Store()), [1.0], 0.8)
    assert {hit.point_id for hit in found} == {"0", "1", "2"}


def test_twelve_candidates_resume_after_three_calls(monkeypatch) -> None:
    tickets = [f"tkt_01a19f93-1150-7000-8000-{n:012d}" for n in range(12)]
    candidates = tuple(
        Candidate(
            {
                "id": f"inc_01a19f93-1150-7000-8000-{n:012d}",
                "title": f"case {n}",
                "ticket_ids": [tickets[n]],
                "created_at": 1000,
                "updated_at": 2000,
            },
            (),
            ticket_id=tickets[n],
            score=0.9,
        )
        for n in range(12)
    )
    context = SimpleNamespace(
        ticket={"id": "tkt_01a19f93-1150-7000-8000-000000000099"},
        alerts=(),
        events=(),
        hunt=None,
        evidence_ids=(),
        missing_evidence_count=0,
    )
    calls = []
    saved = []
    decisions = []

    def run(task):
        calls.append(task)
        choice = task.data["candidates"][0]
        return AgentResult(
            ok=True,
            output={
                "decision": "existing",
                "incident_id": choice["incident_id"],
                "similar_ticket_ids": [choice["representative_ticket_id"]],
            },
            failure=None,
            detail=None,
            run_id="run_01a19f93-1150-7000-8000-000000000001",
        )

    monkeypatch.setattr("soc.l2.branch.worker._record", lambda _c, _t, s: saved.append(deepcopy(s)))
    monkeypatch.setattr(
        L2BranchWorker,
        "_finish",
        lambda _self, _conn, _ctx, decision, *_args: decisions.append(decision),
    )
    worker = L2BranchWorker(
        "unused",
        BranchSettings(86_400_000, 5, 10),
        run=run,
        clock=lambda: datetime.now(UTC),
    )
    snapshot = [{"incident_id": c.incident["id"]} for c in candidates]
    state = {"progress": {}}
    worker._classify(None, context, candidates, state, 1000, None, snapshot)
    assert len(calls) == 3
    assert not decisions
    assert saved[-1]["progress"] == {
        "phase": "final",
        "pool": [candidates[n].incident["id"] for n in (0, 5, 10)],
        "cursor": 0,
        "winners": [],
    }
    worker._classify(None, context, candidates, saved[-1], 1000, None, snapshot)
    assert len(calls) == 4
    assert decisions[0].incident_id == candidates[0].incident["id"]
    assert all(len(call.data["candidates"]) <= 5 for call in calls)
