"""The in-memory Lookup store follows the same contract as PostgreSQL (box 5)."""

import pytest
from fake_lookup_store import FakeLookupStore
from lookup_store_contract import LookupStoreContract


class TestFakeLookupStoreContract(LookupStoreContract):
    @pytest.fixture
    def make_store(self):
        return FakeLookupStore
