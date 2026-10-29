"""The evidence queue backend is chosen by setting (docs/extensibility.md, evidence_queues)."""

import re
from pathlib import Path

import pytest
from evidence_fakes import FakeEvidenceQueue, FakeTicketStore, load

from soc.config import ConfigError, load_config
from soc.l1.evidence import EVIDENCE_QUEUES, open_evidence_queue
from soc.l1.evidence.postgresql import create_postgresql_evidence_queue
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.tickets import TicketService
from soc.plugins import PluginRegistry

ROOT = Path(__file__).resolve().parents[3]
CORE_FILES = ("base.py", "checks.py", "service.py", "handlers.py")


def test_default_settings_pick_postgresql():
    assert load_config(environ={}).evidence_queue.backend == "postgresql"


def test_postgresql_is_registered_in_the_repo():
    assert EVIDENCE_QUEUES.group == "evidence_queues"
    assert EVIDENCE_QUEUES.get("postgresql") is create_postgresql_evidence_queue


def test_fake_queue_replaces_postgresql_by_setting(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text('[evidence_queue]\nbackend = "fake"\n', encoding="utf-8")
    settings = load_config(org, environ={})
    queue = FakeEvidenceQueue()
    calls = []
    registry = PluginRegistry("evidence_queues")
    registry.register("fake", lambda s, e: calls.append((s, e)) or queue)

    opened = open_evidence_queue(settings, environ={"X": "1"}, registry=registry)

    assert opened is queue
    assert calls == [(settings, {"X": "1"})]
    svc = EvidenceQueueService.from_settings(
        settings,
        handlers={"siem_mcp": lambda request, *, agent: {"records": []}},
        tickets=TicketService(FakeTicketStore()),
        environ={},
        registry=registry,
    )
    svc.enqueue(
        agent="l1",
        requester_type="alert",
        requester_id="al_sample",
        request_type="siem_mcp",
        params=load("siem_mcp_alert_request.json")["params"],
    )
    assert svc.process_next()["status"] == "completed"


@pytest.mark.parametrize(
    "body",
    [
        '[evidence_queue]\nbackend = "Postgres-SQL"\n',
        "[evidence_queue]\nmax_retries = -1\n",
    ],
)
def test_invalid_queue_settings_fail(tmp_path, body):
    org = tmp_path / "org.toml"
    org.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(org, environ={})


@pytest.mark.parametrize("name", CORE_FILES)
def test_core_has_no_backend_name_branch(name):
    source = (ROOT / "src/soc/l1/evidence" / name).read_text(encoding="utf-8")
    assert not re.search(r"postgres|psycopg", source, re.IGNORECASE)
