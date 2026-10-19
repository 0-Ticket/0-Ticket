"""The fake branch store passes the same contract tests as PostgreSQL (box 25, C21)."""

import pytest
from branch_store_contract import BranchStoreContract
from fake_branch_store import FakeBranchStore


class TestFakeBranchStoreContract(BranchStoreContract):
    @pytest.fixture
    def make_store(self):
        return FakeBranchStore
