"""#81: the demo runner (scripts/demo_run.py) without a database.

What needs PostgreSQL (creating databases, reading results) runs in
tests/flow/test_demo_flow.py.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from soc.config import load_config
from soc.db.connection import DatabaseConnectionError

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / "tests" / "fixtures" / "flow"
PASSWORD = "hunter-two-example"
URL = f"postgresql://soc:{PASSWORD}@127.0.0.1:5432/soc"
READONLY_URL = f"postgresql://soc_reader:{PASSWORD}@127.0.0.1:5432/soc"


def _load_script():
    spec = importlib.util.spec_from_file_location("demo_run", ROOT / "scripts" / "demo_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_script()


def result(raw_id, rule_id, path, count=1, alert=None, ticket=None):
    return runner.AlertResult(
        alert_id=f"al_{raw_id}",
        raw_id=raw_id,
        rule_id=rule_id,
        count=count,
        path=path,
        alert_decision=alert,
        ticket_id=None if ticket is None else f"tk_{raw_id}",
        ticket_decision=ticket,
    )


def flow_results():
    """The results tests/fixtures/flow/expected*.csv describe."""
    rows = [
        result(
            "raw_wazuh_alert.jsonl_1", "5706", "l1_entity_lookup", 1, "l1_escalated", "closed_fp"
        ),
        result(
            "raw_wazuh_alert.jsonl_2",
            "31101",
            "l1_entity_lookup",
            3,
            "l1_escalated",
            "l2_escalated",
        ),
        result("raw_wazuh_alert.jsonl_3", "31101", "deduplicated"),
        result("raw_wazuh_alert.jsonl_4", "31101", "deduplicated"),
        result("raw_wazuh_alert.jsonl_5", "31104", "scenario_ticket", 1, None, "l2_escalated"),
        result("raw_wazuh_alert.jsonl_6", "31516", "l1_entity_lookup", 1, "l1_escalated", "held"),
        result("raw_wazuh_alert.jsonl_7", "86601", "l1_entity_lookup", 1, "held"),
    ]
    return {row.raw_id: row for row in rows}


def compare(results, **kwargs):
    return runner.compare(
        runner.read_expected(FLOW / "expected.csv"),
        runner.read_expected_counts(FLOW / "expected_counts.csv"),
        results,
        **kwargs,
    )


# --- database names and URLs ------------------------------------------------------


def test_database_url_changes_only_the_database_name():
    assert runner.database_url(URL, "zt_demo81") == (
        f"postgresql://soc:{PASSWORD}@127.0.0.1:5432/zt_demo81"
    )
    assert runner.database_url(URL + "?sslmode=disable", "zt_x").endswith("/zt_x?sslmode=disable")


@pytest.mark.parametrize("name", ["", "Demo", "zt-demo", "zt;drop", "a" * 64, "1zt"])
def test_database_name_must_be_a_plain_identifier(name):
    with pytest.raises(runner.RunnerError):
        runner.database_url(URL, name)


def test_grant_is_skipped_when_both_urls_use_the_same_account():
    """Nothing connects: there is no separate account to grant to."""
    assert "skipped" in runner.grant_readonly(URL, runner.database_url(URL, "other"), "zt_demo81")
    assert "skipped" in runner.grant_readonly(URL, None, "zt_demo81")


def test_grant_names_the_readonly_account_but_never_its_password(monkeypatch):
    executed = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            executed.append(statement)

    opened = []
    monkeypatch.setattr(runner, "admin_connection", lambda url: opened.append(url) or Connection())

    message = runner.grant_readonly(URL, READONLY_URL, "zt_demo81")

    assert opened == [runner.database_url(URL, "zt_demo81")]  # granted inside the new database
    assert len(executed) == 1
    assert "soc_reader" in message
    assert PASSWORD not in message


def test_step_environment_points_both_accounts_at_the_new_database(tmp_path):
    env = runner.step_environ(
        {"DATABASE_URL": URL, "DATABASE_READONLY_URL": READONLY_URL, "PATH": "/bin"},
        tmp_path / "settings.toml",
        "zt_demo81",
    )
    assert env["DATABASE_URL"].endswith("/zt_demo81")
    assert env["DATABASE_READONLY_URL"].startswith("postgresql://soc_reader:")
    assert env["DATABASE_READONLY_URL"].endswith("/zt_demo81")
    assert env["ZT_CONFIG"] == str(tmp_path / "settings.toml")
    assert env["PATH"] == "/bin"


# --- comparison -------------------------------------------------------------------


def test_results_that_match_the_expected_tables():
    report = compare(flow_results())
    assert report.mismatches == []
    assert (report.rows, report.matched, report.paths_matched) == (5, 5, 5)


def test_branch_only_comparison_ignores_decisions():
    results = flow_results()
    for raw_id, row in results.items():
        results[raw_id] = runner.AlertResult(**(vars(row) | {"alert_decision": None}))
    assert compare(results, decisions=False).mismatches == []
    assert compare(results).mismatches != []


def test_a_wrong_path_and_a_lost_alert_are_both_reported():
    results = flow_results()
    results["raw_wazuh_alert.jsonl_5"] = result(
        "raw_wazuh_alert.jsonl_5", "31104", "l1_entity_lookup", 1, "l1_escalated", "l2_escalated"
    )
    del results["raw_wazuh_alert.jsonl_3"]

    report = compare(results)

    assert "raw_wazuh_alert.jsonl_5: path, alert decision" in report.mismatches
    assert any(m.startswith("counts 31101:") for m in report.mismatches)
    # 31104 is still a representative, so its counts stay right.
    assert not any(m.startswith("counts 31104:") for m in report.mismatches)
    assert any(m.startswith("count sum") for m in report.mismatches)
    assert report.matched == 4


def test_stable_results_leave_out_the_random_ticket_id():
    first = flow_results()
    second = {
        raw_id: runner.AlertResult(
            **(vars(row) | {"ticket_id": None if row.ticket_id is None else "tk_other"})
        )
        for raw_id, row in first.items()
    }
    assert runner.stable(first) == runner.stable(second)


# --- check ------------------------------------------------------------------------


def settings():
    return load_config(FLOW / "settings.toml", environ={})


def models(*names):
    return 200, json.dumps({"data": [{"id": name} for name in names]}).encode()


def answering(models_reply, qdrant_status=200):
    def get(url, _headers):
        if url.endswith("/readyz"):
            return qdrant_status, b""
        if url.endswith("/models"):
            if isinstance(models_reply, Exception):
                raise models_reply
            return models_reply
        raise AssertionError(url)

    return get


def connected(_settings, _environ):
    class Connection:
        def close(self):
            pass

    return Connection()


def test_check_passes_when_everything_is_there():
    configured = settings()
    problems = runner.check(
        configured,
        {"DATABASE_URL": URL, "DATABASE_READONLY_URL": READONLY_URL},
        [FLOW / "assets.csv"],
        get=answering(models(f"{configured.llm.model}:latest", configured.embedder.model)),
        connect_db=connected,
    )
    assert problems == []


def test_check_lists_everything_missing_without_a_password(tmp_path):
    configured = settings()

    def refused(_settings, _environ):
        raise DatabaseConnectionError("Could not connect using DATABASE_URL: ***")

    problems = runner.check(
        configured,
        {"DATABASE_URL": URL},
        [tmp_path / "missing.csv"],
        get=answering(models(configured.llm.model), qdrant_status=503),
        connect_db=refused,
    )

    text = "\n".join(problems)
    assert "DATABASE_READONLY_URL is not set" in text
    assert "PostgreSQL: cannot connect" in text
    assert "Qdrant" in text
    assert f"model {configured.embedder.model} not found" in text
    assert f"model {configured.llm.model} not found" not in text
    assert "missing.csv" in text
    assert PASSWORD not in text


def test_check_reports_an_unreachable_llm_server_and_missing_replay_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)  # the replay files are not under this root
    problems = runner.check(
        settings(),
        {"DATABASE_URL": URL, "DATABASE_READONLY_URL": READONLY_URL},
        [],
        get=answering(OSError("refused")),
        connect_db=connected,
    )
    assert any(problem.startswith("LLM server: not reachable") for problem in problems)
    missing = [p.split(" (")[0] for p in problems if p.startswith("replay file missing")]
    assert missing == [
        "replay file missing: tests/fixtures/flow/wazuh_alert.jsonl",
        "replay file missing: tests/fixtures/flow/access.log",
    ]


def test_full_stops_before_creating_anything_when_check_fails(monkeypatch, capsys):
    monkeypatch.setattr(runner, "check", lambda *_args, **_kwargs: ["Qdrant: not reachable"])
    monkeypatch.setattr(runner, "create_database", lambda *_args: pytest.fail("created a database"))

    code = runner.main(
        ["full", "--db", "zt_demo81", "--config", str(FLOW / "settings.toml")],
        environ={"DATABASE_URL": URL, "DATABASE_READONLY_URL": READONLY_URL},
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "Qdrant: not reachable" in err
    assert PASSWORD not in err


def test_show_needs_both_database_urls(capsys):
    code = runner.main(["show", "--db", "zt_demo81"], environ={"DATABASE_URL": URL})
    assert code == 1
    assert "DATABASE_READONLY_URL" in capsys.readouterr().err


def test_show_screen_forwards_api_from_the_same_origin():
    # #97: the screen calls the relative /api and its dev server forwards it to the API.
    settings = load_config(ROOT / "config" / "demo" / "settings.toml", environ={})
    env = runner.screen_environ(
        {"PATH": "/bin", "VITE_API_BASE_URL": "http://elsewhere.example.com/api"}, settings
    )
    assert env["VITE_USE_MOCK"] == "false"
    assert env["API_PROXY_TARGET"] == f"http://{settings.api.host}:{settings.api.port}"
    assert "VITE_API_BASE_URL" not in env
    assert env["PATH"] == "/bin"
