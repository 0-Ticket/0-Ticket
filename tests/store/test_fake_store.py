"""The fake store passes the same contract tests as PostgreSQL (boxes 6, 7)."""

import pytest
from fake_store import FakeRecordStore
from store_contract import Clock, RecordStoreContract


class TestFakeRecordStoreContract(RecordStoreContract):
    @pytest.fixture
    def make_store(self):
        def make(retention_days=0, clock=None):
            return FakeRecordStore(retention_days, clock or Clock())

        return make
