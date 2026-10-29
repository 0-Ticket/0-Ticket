"""Shared contract tests every L1 decision store (C23, boxes 11, 27) must pass.

Subclass ``L1DecisionStoreContract`` in a ``Test*`` class and provide
``make_store``: a function returning a fresh, empty store.
"""

import json
from pathlib import Path

import pytest

from soc.contracts import ContractValidationError, L1DecisionRecord, validate_contract
from soc.store.l1_decisions.base import DecisionPage, DuplicateDecisionError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_decisions():
    path = FIXTURES / "l1_decisions" / "l1_decisions.json"
    return [validate_contract("L1DecisionRecord", item) for item in json.loads(path.read_text())]


def dump(model):
    return model.model_dump(mode="json")


def decision(decision_id, subject_id, created_at, decision="held", reason="llm_failure"):
    return validate_contract(
        "L1DecisionRecord",
        {
            "decision_id": decision_id,
            "subject_type": "ticket" if subject_id.startswith("tk_") else "alert",
            "subject_id": subject_id,
            "decision": decision,
            "confidence": None,
            "reason": reason,
            "created_at": created_at,
        },
    )


def ids(page):
    return [item.decision_id for item in page.items]


def walk(store, limit, **filters):
    """Every item over all pages, and the number of pages."""
    seen, cursor, pages = [], None, 0
    while True:
        page = store.list(cursor=cursor, limit=limit, **filters)
        pages += 1
        seen += ids(page)
        if page.next_cursor is None:
            return seen, pages
        cursor = page.next_cursor


class L1DecisionStoreContract:
    @pytest.fixture
    def store(self, make_store):
        return make_store()

    @pytest.fixture
    def filled(self, store):
        for item in load_decisions():
            store.save(item)
        return store

    def test_saved_decision_is_returned_by_subject(self, store):
        for item in load_decisions():
            assert dump(store.save(item)) == dump(item)
            found = store.get(item.subject_type, item.subject_id)
            assert isinstance(found, L1DecisionRecord)
            assert dump(found) == dump(item)

    def test_unknown_subject_is_none(self, store):
        assert store.get("alert", "al_missing") is None

    def test_get_returns_the_latest_record_of_a_subject(self, store):
        store.save(decision("ld_a", "tk_one", 10))
        store.save(decision("ld_b", "tk_one", 30, decision="closed_fp", reason=None))
        store.save(decision("ld_c", "tk_one", 20))
        assert store.get("ticket", "tk_one").decision_id == "ld_b"

    def test_same_created_at_latest_save_wins(self, store):
        store.save(decision("ld_a", "tk_one", 10))
        store.save(decision("ld_b", "tk_one", 10))
        assert store.get("ticket", "tk_one").decision_id == "ld_b"

    def test_same_decision_id_is_saved_once(self, store):
        store.save(decision("ld_a", "tk_one", 10))
        with pytest.raises(DuplicateDecisionError):
            store.save(decision("ld_a", "tk_two", 20))
        assert store.get("ticket", "tk_two") is None

    def test_invalid_decision_is_rejected(self, store):
        bad = L1DecisionRecord.model_validate(
            {**dump(load_decisions()[0]), "decision": "closed_fp"}
        )
        with pytest.raises(ContractValidationError):
            store.save(bad)
        assert store.get("alert", bad.subject_id) is None

    def test_list_is_newest_first(self, filled):
        page = filled.list()
        assert isinstance(page, DecisionPage)
        # Two share created_at; the one saved later comes first.
        assert ids(page) == [
            "ld_sample_ticket_held",
            "ld_sample_ticket_closed",
            "ld_sample_alert_escalated",
            "ld_sample_alert_held",
        ]
        assert page.next_cursor is None

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            ({"subject_type": "alert"}, ["ld_sample_alert_escalated", "ld_sample_alert_held"]),
            ({"decision": "held"}, ["ld_sample_ticket_held", "ld_sample_alert_held"]),
            ({"reason": "below_threshold"}, ["ld_sample_alert_held"]),
            ({"subject_type": "ticket", "decision": "held"}, ["ld_sample_ticket_held"]),
            ({"subject_type": "alert", "decision": "closed_fp"}, []),
            ({"subject_id": "al_sample_wpscan"}, ["ld_sample_alert_held"]),
            ({"subject_id": "al_missing"}, []),
            (
                {"subject_type": "ticket", "subject_id": "tk_sample_held"},
                ["ld_sample_ticket_held"],
            ),
            ({"subject_type": "alert", "subject_id": "tk_sample_held"}, []),
        ],
    )
    def test_list_filters(self, filled, filters, expected):
        assert ids(filled.list(**filters)) == expected

    def test_subject_id_lists_the_whole_history_newest_first(self, store):
        # ``get`` keeps only the latest record; box 27 shows every decision of a subject.
        store.save(decision("ld_a", "tk_one", 10))
        store.save(decision("ld_b", "tk_one", 30, decision="closed_fp", reason=None))
        store.save(decision("ld_c", "tk_one", 20))
        store.save(decision("ld_other", "tk_two", 40))
        assert ids(store.list(subject_id="tk_one")) == ["ld_b", "ld_c", "ld_a"]

    def test_subject_id_pages_without_gaps_or_repeats(self, store):
        for index in range(5):
            store.save(decision(f"ld_{index}", "tk_one", 10 + index))
        store.save(decision("ld_other", "tk_two", 99))
        seen, pages = walk(store, 2, subject_id="tk_one")
        assert seen == ["ld_4", "ld_3", "ld_2", "ld_1", "ld_0"]
        assert pages == 3

    @pytest.mark.parametrize("limit", [1, 2, 3])
    def test_pages_have_no_gaps_or_repeats(self, filled, limit):
        seen, pages = walk(filled, limit)
        assert seen == ids(filled.list())
        assert pages == -(-4 // limit)

    def test_cursor_keeps_the_filter_order(self, filled):
        seen, _ = walk(filled, 1, decision="held")
        assert seen == ["ld_sample_ticket_held", "ld_sample_alert_held"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"subject_type": "incident"},
            {"subject_id": ""},
            {"decision": "closed_benign"},
            {"reason": "timeout"},
            {"limit": 0},
            {"limit": 201},
            {"cursor": "not-a-cursor"},
            {"cursor": "WyJ4Il0="},  # ["x"]: valid base64 JSON, wrong shape
        ],
    )
    def test_list_rejects_bad_arguments(self, store, kwargs):
        with pytest.raises(ValueError):
            store.list(**kwargs)

    def test_get_rejects_unknown_subject_type(self, store):
        with pytest.raises(ValueError, match="subject_type"):
            store.get("incident", "in_x")
