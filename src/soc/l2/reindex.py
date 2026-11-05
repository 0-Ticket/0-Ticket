"""PostgreSQL의 Incident 소속 관계로 L2 Ticket 벡터 색인을 복구한다."""

import psycopg

from soc.l2.branch.context import build_context
from soc.l2.branch.embed import embedding_text
from soc.l2.branch.read import read_branch_data
from soc.store import Embedder, VectorStore


def reindex(
    database_url: str,
    embedder: Embedder,
    store: VectorStore,
    *,
    recreate: bool = False,
) -> dict[str, int]:
    """일관된 linked Ticket을 색인하고 처리·성공·실패 건수를 돌려준다."""
    if recreate and store.exists():
        store.drop_collection()
    store.ensure_collection()

    with psycopg.connect(database_url, autocommit=True) as conn:
        incident_rows = conn.execute("SELECT id, ticket_ids FROM incidents").fetchall()
        memberships: dict[str, list[str]] = {}
        for incident_id, ticket_ids in incident_rows:
            for ticket_id in ticket_ids:
                memberships.setdefault(ticket_id, []).append(incident_id)
        rows = conn.execute(
            "SELECT id, status FROM tickets WHERE status = 'linked' OR id = ANY(%s)",
            (list(memberships),),
        ).fetchall()
        tickets = {ticket_id: status for ticket_id, status in rows}

        succeeded = 0
        failed = 0
        subjects = set(memberships) | {
            ticket_id for ticket_id, status in tickets.items() if status == "linked"
        }
        for ticket_id in sorted(subjects):
            incident_ids = memberships.get(ticket_id, [])
            if len(incident_ids) != 1 or tickets.get(ticket_id) != "linked":
                failed += 1
                continue
            try:
                context = build_context(read_branch_data(conn, ticket_id, expected_status="linked"))
                text = embedding_text(context)
                if text:
                    store.upsert(
                        ticket_id.removeprefix("tkt_"),
                        embedder.embed(text),
                        {"incident_id": incident_ids[0]},
                    )
                succeeded += 1
            except Exception:
                failed += 1

    return {"processed": len(subjects), "succeeded": succeeded, "failed": failed}
