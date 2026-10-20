"""Box 25 stage 0: duplicates -> scenario Tickets -> L1 entity lookup (K56, K65)."""

import pytest
from branch_fixtures import MINUTE, T, alert_data, at, store_alerts
from fake_branch_store import FakeBranchStore
from fake_store import FakeRecordStore
from fake_ticket_store import FakeTicketStore

from soc.branch.ids import scenario_ticket_id_for
from soc.branch.rules import load_scenario_rules
from soc.branch.runner import Brancher
from soc.config import BranchSettings
from soc.contracts import validate_contract
from soc.l1.entities import alert_entities
from soc.l1.tickets import TicketService

NOW = T + 60 * MINUTE


def settings(**changes):
    values = {
        "dedup_window_minutes": 10,
        "batch_size": 500,
        "rules_dir": "",
        **changes,
    }
    return BranchSettings(**values)


class Setup:
    def __init__(self, items=None, branches=None, tickets=None, **changes):
        self.records = FakeRecordStore()
        self.branches = branches or FakeBranchStore()
        self.ticket_store = tickets or FakeTicketStore()
        self.alerts = store_alerts(self.records, alert_data() if items is None else items)
        self.brancher = Brancher(
            self.records,
            self.branches,
            TicketService(self.ticket_store, clock=lambda: NOW),
            load_scenario_rules(None, ["web"]),
            settings(**changes),
            lambda: NOW,
        )

    def path(self, alert_id):
        branch = self.branches.get("alert", alert_id)
        return None if branch is None else branch.path

    def reason(self, alert_id):
        return self.branches.get("alert", alert_id).reason.model_dump(mode="json")

    def alert(self, alert_id):
        return self.records.get_alert_record(alert_id)

    def snapshot(self):
        return (
            {a.alert_id: self.branches.get("alert", a.alert_id) for a in self.alerts},
            {a.alert_id: self.alert(a.alert_id) for a in self.alerts},
            dict(self.ticket_store.tickets),
        )


def test_each_sample_alert_takes_its_path():
    s = Setup()
    runs = s.brancher.branch_pending()

    assert [r.read for r in runs] == [7, 0]
    assert runs[0].paths == {"deduplicated": 2, "scenario_ticket": 1, "l1_entity_lookup": 4}
    assert {a.alert_id: s.path(a.alert_id) for a in s.alerts} == {
        "al_web_first": "l1_entity_lookup",
        "al_web_repeat": "deduplicated",
        "al_web_late": "l1_entity_lookup",
        "al_web_other_host": "l1_entity_lookup",
        "al_sqli": "scenario_ticket",
        "al_plain": "l1_entity_lookup",
        "al_sqli_repeat": "deduplicated",
    }
    assert s.records.load_branch_position() == runs[0].last_seq


def test_dedup_merges_into_first_alert():
    s = Setup()
    s.brancher.branch_pending()

    first = s.alert("al_web_first")
    assert (first.count, first.first_seen, first.last_seen) == (2, T, T + 5 * MINUTE)
    assert s.reason("al_web_repeat") == {
        "rule_id": "2008983",
        "entity": {"type": "ip", "value": "198.51.100.23"},
    }
    # The duplicate itself is kept as it was.
    assert s.alert("al_web_repeat").count == 1


def test_dedup_window_boundary():
    first = alert_data()[0]
    inside = at(first, "al_inside", 0)
    inside.update(time=T + 10 * MINUTE - 1, first_seen=T + 10 * MINUTE - 1)
    inside["last_seen"] = inside["time"]
    outside = at(first, "al_outside", 10)
    s = Setup([first, inside, outside])
    s.brancher.branch_pending()

    assert s.path("al_inside") == "deduplicated"
    assert s.path("al_outside") == "l1_entity_lookup"
    assert s.alert(first["alert_id"]).count == 2


def test_window_is_fixed_to_the_first_alerts_first_seen():
    first = alert_data()[0]
    items = [first] + [at(first, f"al_repeat_{m}", m) for m in (4, 8, 12, 16)]
    s = Setup(items)
    s.brancher.branch_pending()

    # 12 is past first + 10 even though 8 was merged: 12 starts a new window.
    assert [s.path(i["alert_id"]) for i in items] == [
        "l1_entity_lookup",
        "deduplicated",
        "deduplicated",
        "l1_entity_lookup",
        "deduplicated",
    ]
    assert s.alert(first["alert_id"]).count == 3
    assert s.alert("al_repeat_12").count == 2


def test_other_entity_set_or_rule_is_not_a_duplicate():
    first = alert_data()[0]
    other_rule = at(first, "al_other_rule", 1, rule_id="2008984")
    more_entities = at(first, "al_with_user", 2, user="alice")
    s = Setup([first, other_rule, more_entities])
    s.brancher.branch_pending()

    assert s.path("al_other_rule") == "l1_entity_lookup"
    assert s.path("al_with_user") == "l1_entity_lookup"
    assert s.alert(first["alert_id"]).count == 1


def test_first_alert_is_found_behind_many_alerts_of_the_same_ip():
    first = alert_data()[0]
    # Before #87 candidates were read by src_ip up to dedup_scan_limit; now the
    # representative table is looked up by key, however many alerts share the IP.
    others = [at(first, f"al_other_{n}", 0.01 * n, rule_id=f"other_{n}") for n in range(1, 30)]
    repeats = [at(first, f"al_repeat_{m}", m) for m in (1, 2, 3)]
    items = [first, *others, *repeats]
    s = Setup(items)
    s.brancher.branch_pending()

    assert [s.path(i["alert_id"]) for i in repeats] == ["deduplicated"] * 3
    assert {s.path(i["alert_id"]) for i in others} == {"l1_entity_lookup"}
    assert s.alert(first["alert_id"]).count == 4


def test_reversed_pair_is_a_duplicate():
    first = alert_data()[0]
    reversed_pair = at(first, "al_reversed", 2, src_ip=first["dst_ip"], dst_ip=first["src_ip"])
    s = Setup([first, reversed_pair])
    s.brancher.branch_pending()

    # The entity set has no direction: the same two IPs swapped are the same entities.
    assert s.path("al_reversed") == "deduplicated"
    assert s.alert(first["alert_id"]).count == 2
    assert s.reason("al_reversed")["entity"] == {"type": "ip", "value": first["dst_ip"]}


def test_alerts_with_only_the_same_user_are_duplicates():
    first = at(alert_data()[5], "al_user", 0, src_ip=None, dst_ip=None, host="  ", user="alice")
    repeat = at(first, "al_user_repeat", 3)
    other = at(first, "al_user_other", 4, user="bob")
    s = Setup([first, repeat, other])
    s.brancher.branch_pending()

    assert [s.path(a) for a in ("al_user", "al_user_repeat", "al_user_other")] == [
        "l1_entity_lookup",
        "deduplicated",
        "l1_entity_lookup",
    ]


def test_alerts_without_entities_are_never_duplicates():
    bare = at(alert_data()[5], "al_bare", 0, src_ip=None, dst_ip=None, host="  ", user=None)
    again = at(bare, "al_bare_again", 1)
    s = Setup([bare, again])
    s.brancher.branch_pending()

    assert s.path("al_bare_again") == "l1_entity_lookup"
    assert s.alert("al_bare").count == 1


def test_scenario_creates_ticket():
    s = Setup()
    s.brancher.branch_pending()

    sqli = s.alert("al_sqli")
    ticket = s.ticket_store.get(scenario_ticket_id_for("al_sqli"))
    validate_contract("Ticket", ticket)
    assert ticket["origin"] == "scenario"
    assert ticket["status"] == "new"
    assert (ticket["handling_type"], ticket["specialist"]) == ("web_attack", "web")
    assert ticket["alert_ids"] == ["al_sqli"]
    assert ticket["entities"] == alert_entities(sqli)
    assert ticket["priority"] == 4 * 5
    assert s.reason("al_sqli") == {
        "rule_id": "sample_web_sqli",
        "entity": {"type": "ip", "value": "203.0.113.7"},
    }


def test_scenario_duplicate_joins_its_first_alert_without_a_new_ticket():
    s = Setup()
    s.brancher.branch_pending()

    assert list(s.ticket_store.tickets) == [scenario_ticket_id_for("al_sqli")]
    assert s.alert("al_sqli").count == 2
    assert s.reason("al_sqli_repeat")["rule_id"] == "2019401"


def test_other_goes_to_l1_lookup():
    s = Setup()
    s.brancher.branch_pending()

    assert s.reason("al_plain") == {
        "rule_id": None,
        "entity": {"type": "ip", "value": "203.0.113.9"},
    }
    assert all(t["alert_ids"] != ["al_plain"] for t in s.ticket_store.tickets.values())


def test_alert_without_entities_keeps_its_rule_id():
    bare = at(alert_data()[5], "al_bare", 0, src_ip=None, dst_ip=None, host="  ", user=None)
    s = Setup([bare])
    s.brancher.branch_pending()

    assert s.path("al_bare") == "l1_entity_lookup"
    assert s.reason("al_bare") == {"rule_id": "2010000", "entity": None}


def test_one_page_at_a_time():
    s = Setup(batch_size=3)
    first = s.brancher.branch_once()
    assert (first.read, first.skipped) == (3, 0)
    assert s.path(s.alerts[3].alert_id) is None
    runs = s.brancher.branch_pending()
    assert [r.read for r in runs] == [3, 1, 0]
    assert runs[-1].last_seq == s.records.load_branch_position()


def test_rerun_is_idempotent():
    s = Setup()
    s.brancher.branch_pending()
    before = s.snapshot()

    assert [r.read for r in s.brancher.branch_pending()] == [0]
    # Even reading every alert again changes nothing: each one already has a C21.
    s.records._branch_position = None
    run = s.brancher.branch_once()
    assert (run.read, run.skipped) == (7, 7)
    assert s.snapshot() == before


class FailOnce(FakeBranchStore):
    """Fails the first C21 save of the given alerts, after the side effect was made."""

    def __init__(self, alert_ids):
        super().__init__()
        self.fail = set(alert_ids)

    def save(self, record):
        if record.subject_id in self.fail:
            self.fail.discard(record.subject_id)
            raise RuntimeError("stopped before the C21 was saved")
        return super().save(record)


@pytest.mark.parametrize(
    "stopped_at", ["al_web_first", "al_web_repeat", "al_sqli", "al_sqli_repeat"]
)
def test_rerun_after_a_stop_gives_the_clean_result(stopped_at):
    clean = Setup()
    clean.brancher.branch_pending()

    s = Setup(branches=FailOnce([stopped_at]))
    with pytest.raises(RuntimeError):
        s.brancher.branch_pending()
    assert s.records.load_branch_position() is None
    s.brancher.branch_pending()

    assert s.snapshot() == clean.snapshot()
