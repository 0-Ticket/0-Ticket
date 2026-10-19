"""In-memory branch store (C21) for tests. Passes the same contract tests as PostgreSQL."""

from soc.store.branches.base import DuplicateBranchError, StoredBranch
from soc.store.branches.checks import check_branch, check_limit, check_path, check_subject_type


class FakeBranchStore:
    def __init__(self):
        self._rows = []  # StoredBranch, in save order
        self._seq = 0
        self.closed = False

    def save(self, record):
        record = check_branch(record)
        for row in self._rows:
            if row.record.branch_id == record.branch_id or (
                row.record.subject_type == record.subject_type
                and row.record.subject_id == record.subject_id
            ):
                raise DuplicateBranchError("this subject or branch_id already has a C21")
        self._seq += 1
        stored = StoredBranch(self._seq, record)
        self._rows.append(stored)
        return stored

    def get(self, subject_type, subject_id):
        check_subject_type(subject_type)
        for row in self._rows:
            if row.record.subject_type == subject_type and row.record.subject_id == subject_id:
                return row.record
        return None

    def list_by_path(self, path, after_seq, limit):
        check_path(path)
        check_limit(limit)
        after = after_seq or 0
        found = [row for row in self._rows if row.record.path == path and row.seq > after]
        return tuple(found[:limit])

    def close(self):
        self.closed = True


def fake_branches_factory(settings, environ):
    return FakeBranchStore()
