"""L2 Ticket 분류 문맥과 Incident 후보를 읽는 공개 진입점."""

from dataclasses import dataclass
from datetime import datetime

import psycopg

from soc.l2.branch.candidates import Candidate, rank_candidates
from soc.l2.branch.context import BranchContext, build_context
from soc.l2.branch.read import read_branch_data
from soc.l2.config import BranchSettings


@dataclass(frozen=True)
class BranchResult:
    context: BranchContext
    candidates: tuple[Candidate, ...]


def build_branch(
    conn: psycopg.Connection,
    ticket_id: str,
    now: datetime,
    settings: BranchSettings,
) -> BranchResult:
    """Ticket 하나에 필요한 문맥과 순위 매긴 열린 Incident 후보를 돌려준다."""
    rows = read_branch_data(conn, ticket_id, now, settings.candidate_window_ms)
    context = build_context(rows, settings)
    return BranchResult(context, rank_candidates(context.signals, rows.incidents, settings))


__all__ = ["BranchResult", "build_branch"]
