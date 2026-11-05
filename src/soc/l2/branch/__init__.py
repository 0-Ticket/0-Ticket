"""L2 Ticket 분류 문맥을 읽고 워커를 만드는 공개 진입점."""

import psycopg

from soc.l2.branch.context import BranchContext, build_context
from soc.l2.branch.read import read_branch_data


def build_branch(
    conn: psycopg.Connection,
    ticket_id: str,
) -> BranchContext:
    """Ticket 하나에 필요한 구조화된 분류 문맥을 돌려준다."""
    return build_context(read_branch_data(conn, ticket_id))


__all__ = ["build_branch"]
