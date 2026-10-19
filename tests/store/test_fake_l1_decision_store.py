"""The fake L1 decision store passes the same contract tests as PostgreSQL (C23)."""

import pytest
from fake_l1_decision_store import FakeL1DecisionStore
from l1_decision_store_contract import L1DecisionStoreContract


class TestFakeL1DecisionStoreContract(L1DecisionStoreContract):
    @pytest.fixture
    def make_store(self):
        return FakeL1DecisionStore
