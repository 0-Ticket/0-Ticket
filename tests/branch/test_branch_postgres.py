"""Boxes 10-13 on PostgreSQL: the sample alerts take the same paths as with the fakes (db)."""

import pytest
from branch_fixtures import alert_data, store_alerts
from test_branch_runner import NOW, settings
from test_postgres_store import conn  # noqa: F401  (fixture)

from soc.branch.ids import scenario_ticket_id_for
from soc.branch.rules import load_scenario_rules
from soc.branch.runner import Brancher
from soc.l1.tickets import TicketService
from soc.store.branches.postgres import PostgresBranchStore
from soc.store.postgresql.tickets import PostgresTicketStore
from soc.store.records.postgres import PostgresRecordStore

pytestmark = pytest.mark.db


def test_sample_alerts_branch_on_postgres_and_rerun_changes_nothing(conn):  # noqa: F811
    records = PostgresRecordStore(conn, 0, lambda: NOW)
    branches = PostgresBranchStore(conn)
    tickets = PostgresTicketStore(conn)
    alerts = store_alerts(records, alert_data())
    brancher = Brancher(
        records,
        branches,
        TicketService(tickets, clock=lambda: NOW),
        load_scenario_rules(None, ["web"]),
        settings(batch_size=3),
        lambda: NOW,
    )

    assert [r.read for r in brancher.branch_pending()] == [3, 3, 1, 0]
    paths = {a.alert_id: branches.get("alert", a.alert_id).path for a in alerts}
    assert paths["al_web_repeat"] == paths["al_sqli_repeat"] == "deduplicated"
    assert paths["al_sqli"] == "scenario_ticket"
    assert records.get_alert_record("al_web_first").count == 2
    assert records.get_alert_record("al_sqli").count == 2
    assert tickets.get(scenario_ticket_id_for("al_sqli"))["origin"] == "scenario"

    # Read everything again: each alert already has a C21, so nothing changes.
    conn.execute("DELETE FROM branch_position")
    conn.commit()
    run = brancher.branch_once()
    assert (run.read, run.skipped) == (3, 3)
    assert records.get_alert_record("al_web_first").count == 2
