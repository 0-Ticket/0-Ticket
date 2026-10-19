"""In-memory L1 decision store (C23) for tests. Passes the same contract tests as PostgreSQL."""

from soc.store.l1_decisions.base import DecisionPage, DuplicateDecisionError
from soc.store.l1_decisions.checks import (
    check_decision,
    check_list_args,
    check_subject_type,
    decode_decision_cursor,
)
from soc.store.paging import DEFAULT_PAGE_LIMIT, encode_cursor


class FakeL1DecisionStore:
    def __init__(self):
        self._rows = []  # (seq, C23)
        self.closed = False

    def save(self, record):
        record = check_decision(record)
        if any(row.decision_id == record.decision_id for _, row in self._rows):
            raise DuplicateDecisionError("this decision_id is already stored")
        self._rows.append((len(self._rows) + 1, record))
        return record

    def get(self, subject_type, subject_id):
        check_subject_type(subject_type)
        for _, row in self._newest_first():
            if row.subject_type == subject_type and row.subject_id == subject_id:
                return row
        return None

    def list(
        self,
        *,
        subject_type=None,
        decision=None,
        reason=None,
        cursor=None,
        limit=DEFAULT_PAGE_LIMIT,
    ):
        check_list_args(subject_type, decision, reason, limit)
        after = decode_decision_cursor(cursor)
        found = [
            (seq, row)
            for seq, row in self._newest_first()
            if (subject_type is None or row.subject_type == subject_type)
            and (decision is None or row.decision == decision)
            and (reason is None or row.reason == reason)
            and (after is None or (row.created_at, seq) < after)
        ]
        page = found[:limit]
        more = len(found) > limit
        next_cursor = encode_cursor([page[-1][1].created_at, page[-1][0]]) if more else None
        return DecisionPage(tuple(row for _, row in page), next_cursor)

    def close(self):
        self.closed = True

    def _newest_first(self):
        return sorted(self._rows, key=lambda item: (item[1].created_at, item[0]), reverse=True)


def fake_l1_decisions_factory(settings, environ):
    return FakeL1DecisionStore()
