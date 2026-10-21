"""#81: the demo flow from ingest to the L1 result API, on a temporary database.

The commands run in demo order through their own ``main()``: migrate, lookup load,
ingest, normalize, branch, l1. The input is the small sample in
tests/fixtures/flow/ replayed by ``direct``; the SIEM MCP is the direct adapter; the
LLM, the vector store and the embedder are fakes the settings select by name
(tests/flow/fakes.py). No dataset and no model is needed, so CI runs it.

Every check reads on a new connection after the commands closed theirs, so a write
that was never committed shows up here (#83).

Marked `db`: needs PostgreSQL through DATABASE_URL (`uv run pytest -m db`). The
account must be allowed to create databases, as the CI service and the compose
account are.
"""

import importlib.util
import os
import sys
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from fakes import FakeLLMProvider, fake_siem_registries, l1_registries
from fastapi.testclient import TestClient
from psycopg import sql

import soc.branch.__main__ as branch_command
import soc.db.migrate as migrate_command
import soc.ingest.__main__ as ingest_command
import soc.l1.__main__ as l1_command
import soc.normalize.__main__ as normalize_command
import soc.normalize.lookup.load as lookup_command
from soc.api.app import create_app
from soc.api.readers import open_readers
from soc.config import load_config
from soc.db import connect
from soc.ingest.connector import to_c2
from soc.ingest.siem.direct import DirectSiemConnector
from soc.normalize.normalizer import Normalizer

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / "tests" / "fixtures" / "flow"
SETTINGS = FLOW / "settings.toml"


def _load_runner():
    spec = importlib.util.spec_from_file_location("demo_run", ROOT / "scripts" / "demo_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


@pytest.fixture
def new_database():
    """Create empty databases on the DATABASE_URL server; drop them afterwards."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    created = []

    def make() -> str:
        name = f"zt_flow_{uuid.uuid4().hex[:12]}"
        runner.create_database(url, name)
        created.append(name)
        return runner.database_url(url, name)

    yield make
    for name in created:
        with closing(runner.admin_connection(url)) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def use_database(monkeypatch, tmp_path):
    """Point the commands at one database and the flow settings, as the runner does."""
    monkeypatch.chdir(ROOT)  # the sample paths in the settings are read from the repo root

    def use(url: str, settings_text: str | None = None) -> None:
        org = tmp_path / f"settings_{uuid.uuid4().hex[:8]}.toml"
        text = settings_text or SETTINGS.read_text(encoding="utf-8")
        artifacts = tmp_path / "agent_log"
        org.write_text(f'{text}\n[agent_log]\nartifact_dir = "{artifacts}"\n', encoding="utf-8")
        monkeypatch.setenv("ZT_CONFIG", str(org))
        monkeypatch.setenv("DATABASE_URL", url)
        # The same account reads; the read-only connection still refuses writes.
        monkeypatch.setenv("DATABASE_READONLY_URL", url)

    return use


def run_flow(provider: FakeLLMProvider, *, connectors=None, siem_mcp=None) -> None:
    migrate_command.main()
    assert lookup_command.main(["assets", str(FLOW / "assets.csv")]) == 0
    assert lookup_command.main(["users", str(FLOW / "users.csv")]) == 0
    assert ingest_command.main(["--all"], siem=connectors) == 0
    assert normalize_command.main(["--all"]) == 0
    assert branch_command.main(["--all"]) == 0
    assert l1_command.main(["--all"], siem=siem_mcp, **l1_registries(provider)) == 0


def read_back():
    """A new connection, opened after every command closed its own."""
    return closing(connect(load_config()))


def flow_results():
    with read_back() as conn:
        return runner.collect_results(conn)


def flow_report(results):
    return runner.compare(
        runner.read_expected(FLOW / "expected.csv"),
        runner.read_expected_counts(FLOW / "expected_counts.csv"),
        results,
    )


def by_rule(results, rule_id):
    return [row for row in results.values() if row.rule_id == rule_id]


def snapshot():
    """Row counts of every table the flow writes, and the result per raw_id."""
    tables = (
        "source_records",
        "alert_records",
        "event_records",
        "branch_results",
        "tickets",
        "l1_decisions",
        "evidence_requests",
        "agent_steps",
    )
    with read_back() as conn:
        counts = {
            table: conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in tables
        }
    return counts, runner.stable(flow_results())


def test_flow_matches_the_expected_tables(new_database, use_database):
    use_database(new_database())
    provider = FakeLLMProvider()

    run_flow(provider)

    report = flow_report(flow_results())
    assert report.mismatches == []
    assert report.matched == 5
    assert provider.calls == {"entity_lookup": 4, "web_specialist": 3, "ticket_triage": 4}


def test_duplicates_are_deduplicated_and_counted(new_database, use_database):
    use_database(new_database())
    run_flow(FakeLLMProvider())

    rows = by_rule(flow_results(), "31101")
    assert sorted(row.path for row in rows) == [
        "deduplicated",
        "deduplicated",
        "l1_entity_lookup",
    ]
    representative = next(row for row in rows if row.path != "deduplicated")
    assert representative.count == 3
    with read_back() as conn:
        total = conn.execute(
            "SELECT sum((a.record::jsonb ->> 'count')::int) FROM alert_records a "
            "JOIN branch_results b ON b.subject_id = a.alert_id WHERE b.path <> 'deduplicated'"
        ).fetchone()[0]
        alerts = conn.execute("SELECT count(*) FROM alert_records").fetchone()[0]
    assert total == alerts == 7


def test_scenario_alert_ends_with_specialist_finding_and_ticket_verdict(new_database, use_database):
    use_database(new_database())
    run_flow(FakeLLMProvider())

    (scenario,) = by_rule(flow_results(), "31104")
    assert scenario.path == "scenario_ticket"
    assert scenario.alert_decision is None  # the scenario skips the entity lookup
    with read_back() as conn:
        ticket = conn.execute(
            "SELECT payload FROM tickets WHERE payload -> 'alert_ids' ? %s", (scenario.alert_id,)
        ).fetchone()[0]
        (request,) = [
            row[0]
            for row in conn.execute(
                "SELECT payload FROM evidence_requests WHERE requester_id = %s",
                (ticket["ticket_id"],),
            )
        ]
        decisions = conn.execute(
            "SELECT decision FROM l1_decisions WHERE subject_id = %s", (ticket["ticket_id"],)
        ).fetchall()
        steps = conn.execute(
            "SELECT payload FROM agent_steps WHERE subject_type = 'ticket' AND subject_id = %s "
            "ORDER BY step",
            (ticket["ticket_id"],),
        ).fetchall()
        cited = request["result"]["finding"]["evidence"][0]
        event = conn.execute(
            "SELECT record::jsonb FROM event_records WHERE event_id = %s", (cited["ref_id"],)
        ).fetchone()

    assert ticket["origin"] == "scenario"
    assert ticket["status"] in {"closed_fp", "l2_escalated"}
    assert ticket["status"] == "l2_escalated"
    assert ticket["verdict"]["verdict"] == "tp"
    assert request["request_type"] == "specialist_agent"
    assert request["status"] == "completed"
    assert request["result"]["finding"]["succeeded"] == "yes"
    # The specialist found the web shell in the same source's HTTP flow.
    assert cited["ref_type"] == "event"
    assert "shell.php" in event[0]["http_url"]
    assert decisions == [("l2_escalated",)]
    used = {(step[0]["agent"], step[0]["action"], step[0]["tool"]) for step in steps}
    assert ("web_specialist", "tool_call", "query_http_flow") in used
    assert ("web_specialist", "llm_call", None) in used
    assert ("l1", "llm_call", None) in used


def test_other_alerts_get_l1_escalated_or_held(new_database, use_database):
    use_database(new_database())
    run_flow(FakeLLMProvider())

    looked_up = [row for row in flow_results().values() if row.path == "l1_entity_lookup"]
    assert {row.alert_decision for row in looked_up} == {"l1_escalated", "held"}
    with read_back() as conn:
        for row in looked_up:
            steps = conn.execute(
                "SELECT count(*) FROM agent_steps WHERE subject_type = 'alert' AND subject_id = %s",
                (row.alert_id,),
            ).fetchone()[0]
            assert steps > 0
        held = conn.execute(
            "SELECT reason FROM l1_decisions WHERE subject_type = 'alert' AND decision = 'held'"
        ).fetchall()
    assert held == [("below_threshold",)]
    (smtp,) = by_rule(flow_results(), "86601")
    assert (smtp.alert_decision, smtp.ticket_decision) == ("held", None)


def test_running_again_on_the_same_database_changes_nothing(new_database, use_database):
    use_database(new_database())
    run_flow(FakeLLMProvider())
    before = snapshot()

    provider = FakeLLMProvider()
    run_flow(provider)

    assert snapshot() == before
    assert provider.calls == {}  # decided alerts and Tickets are skipped


def test_running_on_a_new_database_gives_the_same_result(new_database, use_database):
    use_database(new_database())
    run_flow(FakeLLMProvider())
    first = snapshot()

    use_database(new_database())
    run_flow(FakeLLMProvider())

    assert snapshot() == first


def test_api_returns_the_flow_results(new_database, use_database):
    use_database(new_database())
    run_flow(FakeLLMProvider())
    results = flow_results()
    (scenario,) = by_rule(results, "31104")
    (smtp,) = by_rule(results, "86601")

    readers = open_readers(load_config())
    try:
        client = TestClient(create_app(readers))
        decisions = client.get("/api/l1/decisions", params={"limit": 100}).json()["items"]
        ticket = client.get(f"/api/tickets/{scenario.ticket_id}").json()
        alert = client.get(f"/api/alerts/{smtp.alert_id}/l1").json()
    finally:
        readers.close()

    assert {(item["subject_type"], item["decision"]) for item in decisions} == {
        ("alert", "l1_escalated"),
        ("alert", "held"),
        ("ticket", "closed_fp"),
        ("ticket", "l2_escalated"),
        ("ticket", "held"),
    }
    assert len(decisions) == 8
    assert ticket["ticket"]["status"] == "l2_escalated"
    assert ticket["findings"][0]["succeeded"] == "yes"
    assert [item["decision"] for item in ticket["decisions"]] == ["l2_escalated"]
    assert alert["branch"]["path"] == "l1_entity_lookup"
    assert [item["decision"] for item in alert["decisions"]] == ["held"]
    assert alert["steps"]


def _fake_siem_contents():
    """What the fake SIEM holds: the same sample, read once here. How it indexes
    them (time, IPs) is the fake adapter's own business."""
    settings = load_config(SETTINGS, environ={})
    connector = DirectSiemConnector(settings.siem.direct)
    normalizer = Normalizer.from_settings(settings)
    items = list(connector.fetch(None, 100).items)
    index = []
    for item in items:
        normalized = normalizer.normalize(to_c2(item), 0)
        index.append((normalized.time, {normalized.src_ip, normalized.dst_ip} - {None}))
    return items, index


def test_fake_siem_runs_the_same_flow_by_setting_only(new_database, use_database):
    """K66: only ``[siem] adapter`` changes; the core and the agents run unchanged."""
    text = SETTINGS.read_text(encoding="utf-8").replace('adapter = "direct"', 'adapter = "fake"', 1)
    use_database(new_database(), text)
    items, index = _fake_siem_contents()
    connectors, adapters, siem_mcp = fake_siem_registries(items, index)

    run_flow(FakeLLMProvider(), connectors=connectors, siem_mcp=adapters)

    assert load_config().siem.adapter == "fake"
    assert flow_report(flow_results()).mismatches == []
    assert siem_mcp.queries  # L1 read SIEM context through the fake adapter
