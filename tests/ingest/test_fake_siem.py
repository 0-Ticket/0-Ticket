"""The fake SIEM passes the same adapter contract tests as real adapters (K66)."""

import pytest
from adapter_contract import AdapterContract
from fake_siem import FakeSiem

TOKEN = "fake-token-not-a-secret"


class TestFakeSiemContract(AdapterContract):
    @pytest.fixture
    def connector(self):
        return FakeSiem("https://siem.example.com", TOKEN)

    @pytest.fixture
    def unhealthy_connector(self):
        return FakeSiem("https://siem.example.com", TOKEN, reachable=False)

    @pytest.fixture
    def forbidden_text(self):
        return [TOKEN]
