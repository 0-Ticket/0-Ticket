"""Branching speed (boxes 10-13, #87): DB work per alert does not grow with stored alerts (db).

Before #87 an alert read up to dedup_scan_limit recent alerts of its IP to find
its first alert, so each alert cost more as alerts piled up from one source.
Now the first alert is one lookup in the representative table.
"""

from dataclasses import dataclass, field

import pytest
from branch_fixtures import alert_data, at, store_alerts
from test_branch_runner import NOW, settings
from test_postgres_store import conn  # noqa: F401  (fixture)

from soc.branch.rules import load_scenario_rules
from soc.branch.runner import Brancher
from soc.l1.tickets import TicketService
from soc.store.branches.postgres import PostgresBranchStore
from soc.store.postgresql.tickets import PostgresTicketStore
from soc.store.records.postgres import PostgresRecordStore

pytestmark = pytest.mark.db

ALERTS = 5_000


class _CountingCursor:
    def __init__(self, counter, cursor):
        self._counter = counter
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        self._counter.rows += row is not None
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        self._counter.rows += len(rows)
        return rows

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class CountingConnection:
    """The test connection, counting statements run and rows read through it."""

    def __init__(self, connection):
        self._connection = connection
        self.queries = 0
        self.rows = 0

    def execute(self, *args, **kwargs):
        self.queries += 1
        return _CountingCursor(self, self._connection.execute(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._connection, name)


@dataclass(frozen=True)
class CountingBrancher(Brancher):
    counter: CountingConnection = None
    cost: list = field(default_factory=list)  # (path, statements, rows) per alert

    def _branch(self, alert):
        queries, rows = self.counter.queries, self.counter.rows
        path = super()._branch(alert)
        self.cost.append((path, self.counter.queries - queries, self.counter.rows - rows))
        return path


def _same_source_alerts():
    """5,000 alerts from one source IP: 5 rules x 4 targets, one every 3 seconds."""
    base = alert_data()[0]
    return [
        at(
            base,
            f"al_perf_{n:05d}",
            n * 0.05,
            rule_id=f"perf_{n % 5}",
            dst_ip=f"192.0.2.{n % 4 + 1}",
        )
        for n in range(ALERTS)
    ]


def test_queries_per_alert_do_not_grow(conn):  # noqa: F811
    counter = CountingConnection(conn)
    records = PostgresRecordStore(counter, 0, lambda: NOW)
    store_alerts(PostgresRecordStore(conn, 0, lambda: NOW), _same_source_alerts())
    brancher = CountingBrancher(
        records,
        PostgresBranchStore(counter),
        TicketService(PostgresTicketStore(conn), clock=lambda: NOW),
        load_scenario_rules(None, ["web"]),
        settings(),
        lambda: NOW,
        counter=counter,
    )

    brancher.branch_pending()

    cost = brancher.cost
    assert len(cost) == ALERTS
    paths = {path for path, _, _ in cost}
    assert paths == {"deduplicated", "l1_entity_lookup"}
    # 20 rule x target keys over 250 minutes: a new representative per key every 10 minutes.
    assert sum(path == "l1_entity_lookup" for path, _, _ in cost) == 20 * 25
    for path in paths:
        early = {(q, r) for p, q, r in cost[:1_000] if p == path}
        late = {(q, r) for p, q, r in cost[-1_000:] if p == path}
        # The same statements and rows read per alert at the start and after 4,000 alerts.
        assert early == late
        assert len(early) == 1
        ((queries, rows),) = early
        assert queries <= 6 and rows <= 3
