"""In-memory fake SIEM MCP adapter for tests (box 15, K18, K66).

Like any adapter it answers a SiemQuery with C2 content without source_record_id;
the core assigns the ID. It reads its address from settings and its token from the
environment variable settings name, the way a real adapter would.

The records come from tests/fixtures/l1/mcp/siem_records.jsonl. Which field holds
which entity is this fake's own business: a real adapter translates the query into
its SIEM's query language instead.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from soc.config import SiemSettings, load_config, read_secret
from soc.ingest.siem.base import HealthStatus
from soc.l1.mcp.siem.base import SiemQuery, SiemUnavailableError
from soc.plugins import PluginRegistry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "l1" / "mcp"
RECORDS_FILE = FIXTURES / "siem_records.jsonl"
ENTITY_FIELDS = {"ip": "src_ip", "host": "host", "user": "user"}
TIME_FIELD = "time"

TOKEN = "fake-token-not-a-secret"
ENV = {"SIEM_TOKEN": TOKEN}
BASE_URL = "https://siem.example.com"
# The organization settings a test runs with: the fake adapter and one agent's tools.
FAKE_CONFIG = (
    f'[siem]\nadapter = "fake"\nbase_url = "{BASE_URL}"\n\n'
    '[mcp.allowed_tools]\nl1 = ["query_siem"]\n'
)


def fixture_records() -> tuple[dict[str, Any], ...]:
    lines = RECORDS_FILE.read_text(encoding="utf-8").splitlines()
    return tuple(json.loads(line) for line in lines if line.strip())


class FakeSiemMcp:
    def __init__(
        self,
        base_url: str,
        token: str,
        records: Sequence[Mapping[str, Any]] | None = None,
        reachable: bool = True,
    ):
        self.base_url = base_url
        self._token = token
        self._records = tuple(dict(record) for record in (records or fixture_records()))
        self._reachable = reachable
        self.queries: list[SiemQuery] = []

    def query(self, query: SiemQuery) -> tuple[Mapping[str, Any], ...]:
        self.queries.append(query)
        if not self._reachable:
            raise SiemUnavailableError(f"cannot reach {self.base_url}")
        field = ENTITY_FIELDS.get(query.entity.type)
        if field is None:
            return ()
        matched = [
            record
            for record in self._records
            if record["kind"] == query.kind
            and record["fields"].get(field) == query.entity.value
            and query.start_at <= record["fields"][TIME_FIELD] <= query.end_at
        ]
        matched.sort(key=lambda record: record["fields"][TIME_FIELD])
        return tuple(matched[: query.limit])

    def health_check(self) -> HealthStatus:
        if not self._reachable:
            return HealthStatus(ok=False, detail=f"cannot reach {self.base_url}")
        return HealthStatus(ok=True, detail=f"connected to {self.base_url}")


def fake_factory(settings: SiemSettings, environ: Mapping[str, str]) -> FakeSiemMcp:
    return FakeSiemMcp(settings.base_url, read_secret(settings.token_env, environ))


def fake_registry(factory=fake_factory) -> PluginRegistry:
    registry = PluginRegistry("siem_mcp_adapters")
    registry.register("fake", factory)
    return registry


def org_settings(tmp_path, body=FAKE_CONFIG):
    org = tmp_path / "org.toml"
    org.write_text(body, encoding="utf-8")
    return load_config(org, environ={})
