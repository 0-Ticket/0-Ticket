"""Branching run (boxes 10-13, stage 0): C5 -> C21, in arrival order, by rules only.

Each run reads one page of alerts after the saved position. For each alert:

1. An alert that already has a C21 is done and skipped.
2. A duplicate (``dedup.find_first_alert_id``) is counted on its first alert
   and gets C21 ``deduplicated``. Duplicates are checked before scenarios, so a
   repeat of a scenario alert makes no second Ticket.
3. Any other alert is saved as a duplicate representative first (if it has
   entities). Then an alert a scenario rule matches gets a ``scenario``
   Ticket and C21 ``scenario_ticket``.
4. The rest get C21 ``l1_entity_lookup`` only. L1 (box 14) reads these
   records itself; this run never calls L1 or an LLM.

The side effects (merge, representative, Ticket) come first and the C21 last,
so "a C21 exists" means "this alert is done". A run stopped in between is
finished by the next one: a merge or representative already saved is not
repeated, the representative lookup leaves the alert itself out, and the Ticket
ID comes from the alert ID, so the Ticket already made is reused. The position
is saved at the end of the page. This assumes one branching worker at a time.

C21 ``reason.entity`` is the alert's representative entity (the first of
``alert_entities``). ``reason.rule_id`` is the alert's ``rule_id`` for
``deduplicated`` and the matched scenario rule's ``id`` for ``scenario_ticket``
(docs/architecture.md 25). For ``l1_entity_lookup`` it is None, unless the alert
has no entity at all: C21 needs one of the two, so the alert's ``rule_id`` is kept.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from soc.config import BranchSettings
from soc.contracts import AlertRecord, BranchResult, validate_contract
from soc.l1.entities import alert_entities
from soc.l1.tickets import TicketService
from soc.store.branches.base import BranchStore
from soc.store.records.base import RecordStore

from .dedup import dedup_key, find_first_alert_id
from .ids import branch_id_for, scenario_ticket_id_for
from .rules import ScenarioRules

PATHS = ("deduplicated", "scenario_ticket", "l1_entity_lookup")


@dataclass(frozen=True)
class BranchRun:
    """One page: alerts read, already branched ones skipped, and C21 saved per path."""

    read: int
    skipped: int
    paths: dict[str, int] = field(default_factory=lambda: dict.fromkeys(PATHS, 0))
    last_seq: int | None = None


@dataclass(frozen=True)
class Brancher:
    records: RecordStore
    branches: BranchStore
    tickets: TicketService
    rules: ScenarioRules
    settings: BranchSettings
    clock: Callable[[], int]

    def branch_once(self) -> BranchRun:
        """Branch the next ``batch_size`` alerts and save the position after them."""
        position = self.records.load_branch_position()
        alerts = self.records.list_alert_records(position, self.settings.batch_size)
        if not alerts:
            return BranchRun(0, 0, last_seq=position)
        paths = dict.fromkeys(PATHS, 0)
        skipped = 0
        for stored in alerts:
            path = self._branch(stored.record)
            if path is None:
                skipped += 1
            else:
                paths[path] += 1
        last_seq = alerts[-1].seq
        self.records.save_branch_position(last_seq)
        return BranchRun(len(alerts), skipped, paths, last_seq)

    def branch_pending(self) -> list[BranchRun]:
        """Run until nothing is left. The last run reads 0."""
        runs = []
        while True:
            run = self.branch_once()
            runs.append(run)
            if run.read == 0:
                return runs

    def _branch(self, alert: AlertRecord) -> str | None:
        """Branch one alert; None if it was already branched."""
        if self.branches.get("alert", alert.alert_id) is not None:
            return None
        entities = alert_entities(alert)
        entity = entities[0] if entities else None
        key = dedup_key(alert)
        first_id = find_first_alert_id(alert, key, self.records, self.settings.dedup_window_minutes)
        if first_id is not None:
            self.records.merge_duplicate(first_id, alert.alert_id, alert.last_seen)
            return self._save(alert, "deduplicated", alert.rule_id, entity)
        if key is not None:
            self.records.save_dedup_representative(alert.alert_id, key, alert.first_seen)
        rule = self.rules.match(alert)
        if rule is not None:
            ticket_id = scenario_ticket_id_for(alert.alert_id)
            if self.tickets.get(ticket_id) is None:
                self.tickets.create(
                    alert.model_dump(mode="json"),
                    origin="scenario",
                    entities=entities,
                    handling_type=rule.handling_type,
                    specialist=rule.specialist,
                    ticket_id=ticket_id,
                )
            return self._save(alert, "scenario_ticket", rule.id, entity)
        rule_id = alert.rule_id if entity is None else None
        return self._save(alert, "l1_entity_lookup", rule_id, entity)

    def _save(self, alert: AlertRecord, path: str, rule_id: str | None, entity) -> str:
        record: BranchResult = validate_contract(
            "BranchResult",
            {
                "branch_id": branch_id_for("alert", alert.alert_id),
                "subject_type": "alert",
                "subject_id": alert.alert_id,
                "path": path,
                "reason": {"rule_id": rule_id, "entity": entity},
                "created_at": self.clock(),
            },
        )
        self.branches.save(record)
        return path
