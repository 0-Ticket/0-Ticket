"""The in-memory fake follows the same queue contract as the PostgreSQL queue."""

import pytest
from evidence_fakes import FakeEvidenceQueue
from evidence_queue_contract import EvidenceQueueContract


class TestFakeEvidenceQueue(EvidenceQueueContract):
    @pytest.fixture
    def make_queue(self):
        queue = FakeEvidenceQueue()  # Every "connection" sees the same table.
        return lambda: queue
