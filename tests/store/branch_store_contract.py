"""Shared contract tests every branch store (C21, box 25) must pass.

Subclass ``BranchStoreContract`` in a ``Test*`` class and provide ``make_store``:
a function returning a fresh, empty store. The in-memory fake and the
PostgreSQL store use it; a new backend reuses it.
"""

import json
from pathlib import Path

import pytest

from soc.contracts import BranchResult, ContractValidationError, validate_contract
from soc.store.branches.base import DuplicateBranchError, StoredBranch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_branches():
    path = FIXTURES / "branches" / "branch_results.json"
    return [validate_contract("BranchResult", item) for item in json.loads(path.read_text())]


def dump(model):
    return model.model_dump(mode="json")


def branch(branch_id, subject_id, path="l1_entity_lookup", subject_type="alert"):
    return validate_contract(
        "BranchResult",
        {
            "branch_id": branch_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "path": path,
            "reason": {"rule_id": "r1", "entity": None},
            "created_at": 1,
        },
    )


class BranchStoreContract:
    @pytest.fixture
    def store(self, make_store):
        return make_store()

    def test_saved_branch_is_returned_by_subject(self, store):
        for item in load_branches():
            stored = store.save(item)
            assert isinstance(stored, StoredBranch)
            assert dump(stored.record) == dump(item)
            found = store.get(item.subject_type, item.subject_id)
            assert isinstance(found, BranchResult)
            assert dump(found) == dump(item)

    def test_unbranched_subject_is_none(self, store):
        assert store.get("alert", "al_missing") is None

    def test_subject_type_is_part_of_the_subject(self, store):
        store.save(load_branches()[0])
        assert store.get("ticket", load_branches()[0].subject_id) is None

    def test_same_subject_is_saved_once(self, store):
        first = load_branches()[0]
        store.save(first)
        again = branch("br_other_id", first.subject_id, path="deduplicated")
        with pytest.raises(DuplicateBranchError):
            store.save(again)
        assert dump(store.get("alert", first.subject_id)) == dump(first)

    def test_same_branch_id_is_saved_once(self, store):
        first = load_branches()[0]
        store.save(first)
        with pytest.raises(DuplicateBranchError):
            store.save(branch(first.branch_id, "al_another"))
        assert store.get("alert", "al_another") is None

    def test_invalid_branch_is_rejected(self, store):
        bad = BranchResult.model_validate({**dump(load_branches()[0]), "subject_id": "tk_x"})
        with pytest.raises(ContractValidationError):
            store.save(bad)
        assert store.get("alert", "tk_x") is None

    def test_list_by_path_pages_in_save_order(self, store):
        saved = [store.save(item) for item in load_branches()]
        assert [s.seq for s in saved] == sorted(s.seq for s in saved)
        assert len({s.seq for s in saved}) == len(saved)
        lookups = [s for s in saved if s.record.path == "l1_entity_lookup"]

        first = store.list_by_path("l1_entity_lookup", None, 1)
        rest = store.list_by_path("l1_entity_lookup", first[-1].seq, 1)
        assert [(s.seq, dump(s.record)) for s in first + rest] == [
            (s.seq, dump(s.record)) for s in lookups
        ]
        assert store.list_by_path("l1_entity_lookup", rest[-1].seq, 1) == ()
        assert [s.record.path for s in store.list_by_path("deduplicated", None, 10)] == [
            "deduplicated"
        ]

    def test_list_by_path_rejects_bad_arguments(self, store):
        with pytest.raises(ValueError, match="limit"):
            store.list_by_path("l1_entity_lookup", None, 0)
        with pytest.raises(ValueError, match="path"):
            store.list_by_path("nope", None, 10)

    def test_get_rejects_unknown_subject_type(self, store):
        with pytest.raises(ValueError, match="subject_type"):
            store.get("incident", "in_x")
