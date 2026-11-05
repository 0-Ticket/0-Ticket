"""W04 정책 API와 단발 Alert 분기를 손으로 만든 샘플과 임시 PostgreSQL로 확인한다."""

import json
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg.types.json import Jsonb
from starlette.testclient import TestClient

from soc.api.app import create_app
from soc.api.config import load_settings
from soc.contracts import to_datetime
from soc.db.migrate import MIGRATIONS_DIR, MigrationError, migrate
from soc.l1.ticketing import exit_code, main, run
from soc.ticketing import TicketingPolicy, replace_active_policy

pytestmark = pytest.mark.db

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "ticketing" / "alerts.json").read_text(encoding="utf-8")
)
BY_CASE = {row["case"]: row for row in FIXTURE}
NOW_MS = 1_793_680_000_000


@pytest.fixture
def migrated_database(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(migrated_database: HiddenUrl) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        yield connection


@pytest.fixture
def api_client(
    migrated_database: HiddenUrl, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", migrated_database)
    with TestClient(create_app(load_settings())) as client:
        yield client


def seed_cases(
    conn: psycopg.Connection, names: tuple[str, ...] | None = None
) -> dict[str, dict[str, Any]]:
    """fixture 원본과 W02 결과 위치를 넣어 실제 분기 후보를 만든다."""
    selected = [row for row in FIXTURE if names is None or row["case"] in names]
    for case in selected:
        raw_id = case["raw_id"]
        raw_kind = "event" if case["normalization"]["result_kind"] == "event" else "alert"
        conn.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original)"
            " VALUES (%s, %s, 'fixture', %s, %s, %s)",
            (
                raw_id,
                raw_kind,
                f"ticketing/{case['case']}",
                to_datetime(NOW_MS),
                Jsonb({"fixture_case": case["case"]}),
            ),
        )
        alert = case.get("alert")
        if alert is not None:
            conn.execute(
                "INSERT INTO alerts"
                " (id, raw_id, time, severity, title, rule_id, entities, assets,"
                " triage, ocsf, details)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    alert["id"],
                    raw_id,
                    to_datetime(alert["time"]),
                    alert["severity"],
                    alert["title"],
                    alert["rule_id"],
                    Jsonb(alert["entities"]),
                    Jsonb(alert["assets"]),
                    Jsonb(alert["triage"]) if alert["triage"] is not None else None,
                    Jsonb(alert["ocsf"]),
                    Jsonb(alert["details"]),
                ),
            )
        normalization = case["normalization"]
        if normalization["result_kind"] == "event":
            conn.execute(
                "INSERT INTO events"
                " (id, raw_id, time, ocsf_class, summary, entities, assets, ocsf, details)"
                " VALUES (%s, %s, %s, 4002, 'fixture event', '[]', '[]', %s, '{}')",
                (
                    normalization["result_id"],
                    raw_id,
                    to_datetime(NOW_MS),
                    Jsonb({"class_uid": 4002}),
                ),
            )
        conn.execute(
            "INSERT INTO normalize_status (raw_id, status, result_kind, result_id)"
            " VALUES (%s, %s, %s, %s)",
            (
                raw_id,
                normalization["status"],
                normalization["result_kind"],
                normalization["result_id"],
            ),
        )
    return {case["case"]: case for case in selected}


def insert_ticket(
    conn: psycopg.Connection,
    *,
    ticket_id: str,
    origin: str,
    alert_ids: list[str],
    status: str = "new",
    hunt_id: str | None = None,
    entities: list[dict[str, Any]] | None = None,
    verdict: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO tickets"
        " (id, origin, status, alert_ids, hunt_id, entities, verdict,"
        " created_at, updated_at, details)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}')",
        (
            ticket_id,
            origin,
            status,
            alert_ids,
            hunt_id,
            Jsonb(entities or []),
            Jsonb(verdict) if verdict is not None else None,
            to_datetime(NOW_MS),
            to_datetime(NOW_MS),
        ),
    )


def test_ticketing_api_reads_fallback_then_prefers_active_database_policy(
    conn: psycopg.Connection,
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from soc import ticketing

    (tmp_path / "default.toml").write_text(
        '[ticketing]\nmode = "auto"\nscenario_rule_ids = []\n', encoding="utf-8"
    )
    (tmp_path / "local.toml").write_text(
        '[ticketing]\nmode = "scenario"\nscenario_rule_ids = ["local-rule"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ticketing, "CONFIG_DIR", tmp_path)

    fallback = api_client.get("/api/ticketing-policy")
    assert fallback.status_code == 200
    assert fallback.json() == {"mode": "scenario", "scenario_rule_ids": ["local-rule"]}

    replace_active_policy(conn, TicketingPolicy("auto", ()))
    active = api_client.get("/api/ticketing-policy")
    assert active.status_code == 200
    assert active.json() == {"mode": "auto", "scenario_rule_ids": []}


def test_ticketing_api_put_replaces_policy_and_rejects_invalid_body_without_changes(
    conn: psycopg.Connection, api_client: TestClient
) -> None:
    replace_active_policy(conn, TicketingPolicy("auto", ()))

    replaced = api_client.put(
        "/api/ticketing-policy",
        json={"mode": "scenario", "scenario_rule_ids": ["scenario-rule"]},
    )
    assert replaced.status_code == 200
    assert replaced.json() == {"mode": "scenario", "scenario_rule_ids": ["scenario-rule"]}

    empty = api_client.put(
        "/api/ticketing-policy", json={"mode": "scenario", "scenario_rule_ids": []}
    )
    assert empty.status_code == 200
    assert empty.json() == {"mode": "scenario", "scenario_rule_ids": []}

    marker = "BODY-MUST-NOT-LEAK"
    rejected = api_client.put(
        "/api/ticketing-policy",
        json={"mode": "auto", "scenario_rule_ids": marker},
    )
    assert rejected.status_code == 422
    assert rejected.json() == {"error": "invalid_body", "fields": ["scenario_rule_ids"]}
    assert marker not in rejected.text
    assert api_client.get("/api/ticketing-policy").json() == {
        "mode": "scenario",
        "scenario_rule_ids": [],
    }


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO ticketing_policy VALUES (2, 'auto', '{}')",
        "INSERT INTO ticketing_policy VALUES (1, 'manual', '{}')",
        "INSERT INTO ticketing_policy VALUES (1, 'auto', ARRAY['rule', NULL])",
    ],
    ids=["singleton_id", "mode", "nonnull_rule_ids"],
)
def test_ticketing_policy_table_rejects_invalid_rows(
    conn: psycopg.Connection, statement: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(statement)


def test_auto_mode_uses_only_successful_alert_results_and_is_idempotent(
    conn: psycopg.Connection,
) -> None:
    cases = seed_cases(
        conn, ("auto_alert", "already_triaged", "event_result", "failed_normalization")
    )

    first = run(conn, TicketingPolicy("auto", ()), clock=lambda: NOW_MS)
    second = run(conn, TicketingPolicy("auto", ()), clock=lambda: NOW_MS + 1)

    assert (first.candidates, first.created, first.pending, first.failed) == (1, 1, 0, 0)
    assert (second.candidates, second.created, second.pending, second.failed) == (0, 0, 0, 0)
    ticket = conn.execute(
        "SELECT origin, status, alert_ids, entities, verdict FROM tickets"
    ).fetchone()
    alert = cases["auto_alert"]["alert"]
    assert ticket == ("auto", "new", [alert["id"]], alert["entities"], None)
    assert conn.execute("SELECT triage FROM alerts WHERE id = %s", (alert["id"],)).fetchone() == (
        None,
    )


def test_scenario_mode_creates_match_and_marks_nonmatches_pending(
    conn: psycopg.Connection,
) -> None:
    cases = seed_cases(
        conn,
        (
            "scenario_match",
            "scenario_mismatch",
            "scenario_null_rule",
            "already_triaged",
            "event_result",
            "failed_normalization",
        ),
    )

    result = run(conn, TicketingPolicy("scenario", ("scenario-rule",)), clock=lambda: NOW_MS)

    assert (result.candidates, result.created, result.pending, result.failed) == (3, 1, 2, 0)
    created_id = cases["scenario_match"]["alert"]["id"]
    assert conn.execute("SELECT origin, alert_ids FROM tickets").fetchone() == (
        "scenario",
        [created_id],
    )
    for name in ("scenario_mismatch", "scenario_null_rule"):
        alert_id = cases[name]["alert"]["id"]
        assert conn.execute("SELECT triage FROM alerts WHERE id = %s", (alert_id,)).fetchone() == (
            {"status": "pending", "verdict": None},
        )


def test_empty_scenario_rule_list_marks_alert_pending(conn: psycopg.Connection) -> None:
    cases = seed_cases(conn, ("scenario_match",))

    result = run(conn, TicketingPolicy("scenario", ()), clock=lambda: NOW_MS)

    alert_id = cases["scenario_match"]["alert"]["id"]
    assert (result.created, result.pending) == (0, 1)
    assert conn.execute("SELECT count(*) FROM tickets").fetchone() == (0,)
    assert conn.execute(
        "SELECT triage ->> 'status' FROM alerts WHERE id = %s", (alert_id,)
    ).fetchone() == ("pending",)


def test_active_database_policy_overrides_the_supplied_fallback(
    conn: psycopg.Connection,
) -> None:
    cases = seed_cases(conn, ("auto_alert",))
    replace_active_policy(conn, TicketingPolicy("scenario", ("default-rule",)))

    result = run(conn, TicketingPolicy("auto", ()), clock=lambda: NOW_MS)

    assert result.created == 1
    assert conn.execute("SELECT origin FROM tickets").fetchone() == ("scenario",)
    assert conn.execute(
        "SELECT triage FROM alerts WHERE id = %s", (cases["auto_alert"]["alert"]["id"],)
    ).fetchone() == (None,)


def test_policy_is_read_once_per_alert_and_later_alert_uses_new_commit(
    conn: psycopg.Connection,
) -> None:
    cases = seed_cases(conn, ("auto_alert", "scenario_match"))
    replace_active_policy(conn, TicketingPolicy("auto", ()))
    calls = 0

    def update_policy_between_alerts() -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            with conn.transaction():
                replace_active_policy(conn, TicketingPolicy("scenario", ()))
        return NOW_MS + calls

    result = run(conn, clock=update_policy_between_alerts)

    assert (result.created, result.pending) == (1, 1)
    assert conn.execute(
        "SELECT alert_ids[1], origin FROM tickets ORDER BY alert_ids[1]"
    ).fetchone() == (cases["auto_alert"]["alert"]["id"], "auto")
    assert conn.execute(
        "SELECT triage ->> 'status' FROM alerts WHERE id = %s",
        (cases["scenario_match"]["alert"]["id"],),
    ).fetchone() == ("pending",)


def test_existing_ticket_inserted_after_candidate_snapshot_is_reused_unchanged(
    conn: psycopg.Connection,
) -> None:
    cases = seed_cases(conn, ("auto_alert",))
    alert = cases["auto_alert"]["alert"]
    original = {
        "origin": "auto",
        "status": "closed",
        "alert_ids": [alert["id"]],
        "verdict": {
            "decision": "benign",
            "confidence": 0.8,
            "reason": "reviewed fixture",
            "evidence_ids": [alert["id"]],
            "decided_at": NOW_MS,
        },
    }
    inserted = False

    def insert_existing_ticket() -> int:
        nonlocal inserted
        if not inserted:
            inserted = True
            insert_ticket(
                conn,
                ticket_id="tkt_01a19f93-1150-7000-8000-000000000201",
                origin=original["origin"],
                alert_ids=original["alert_ids"],
                status=original["status"],
                verdict=original["verdict"],
                entities=alert["entities"],
            )
        return NOW_MS

    result = run(conn, TicketingPolicy("auto", ()), clock=insert_existing_ticket)

    assert (result.candidates, result.skipped, result.created) == (1, 1, 0)
    assert conn.execute("SELECT origin, status, alert_ids, verdict FROM tickets").fetchone() == (
        original["origin"],
        original["status"],
        original["alert_ids"],
        original["verdict"],
    )


def test_failed_alert_rolls_back_and_is_retried_on_next_run(conn: psycopg.Connection) -> None:
    cases = seed_cases(conn, ("auto_alert", "scenario_match"))
    rejected_id = cases["auto_alert"]["alert"]["id"]
    replace_active_policy(conn, TicketingPolicy("auto", ()))
    conn.execute(
        """
        CREATE FUNCTION reject_fixture_ticket() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.alert_ids[1] = 'alt_01a19f93-1150-7000-8000-000000000101' THEN
                RAISE EXCEPTION 'fixture insert failure';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    conn.execute(
        "CREATE TRIGGER reject_fixture_ticket BEFORE INSERT ON tickets"
        " FOR EACH ROW EXECUTE FUNCTION reject_fixture_ticket()"
    )

    failed = run(conn, clock=lambda: NOW_MS)

    assert (failed.failed, failed.created) == (1, 1)
    assert conn.execute("SELECT count(*) FROM tickets").fetchone() == (1,)
    assert conn.execute("SELECT triage FROM alerts WHERE id = %s", (rejected_id,)).fetchone() == (
        None,
    )

    conn.execute("DROP TRIGGER reject_fixture_ticket ON tickets")
    conn.execute("DROP FUNCTION reject_fixture_ticket()")
    retried = run(conn, clock=lambda: NOW_MS + 1)

    assert (retried.failed, retried.created) == (0, 1)
    assert conn.execute("SELECT count(*) FROM tickets").fetchone() == (2,)


def test_one_shot_command_processes_alerts_and_reports_counters(
    migrated_database: HiddenUrl,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from soc import ticketing

    with psycopg.connect(migrated_database, autocommit=True) as setup:
        seed_cases(setup, ("auto_alert",))
    (tmp_path / "default.toml").write_text(
        '[ticketing]\nmode = "auto"\nscenario_rule_ids = []\n', encoding="utf-8"
    )
    monkeypatch.setattr(ticketing, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv("DATABASE_URL", migrated_database)

    result = main()

    assert result == 0
    assert capsys.readouterr().out.strip() == (
        "candidates=1 created=1 pending=0 skipped=0 failed=0"
    )


def test_failed_run_uses_failure_exit_code(conn: psycopg.Connection) -> None:
    seed_cases(conn, ("auto_alert",))
    conn.execute(
        """
        CREATE FUNCTION reject_fixture_ticket() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'fixture insert failure';
        END;
        $$
        """
    )
    conn.execute(
        "CREATE TRIGGER reject_fixture_ticket BEFORE INSERT ON tickets"
        " FOR EACH ROW EXECUTE FUNCTION reject_fixture_ticket()"
    )

    result = run(conn, TicketingPolicy("auto", ()), clock=lambda: NOW_MS)

    assert result.failed == 1
    assert exit_code(result) == 1


def test_concurrent_runs_create_at_most_one_ticket(migrated_database: HiddenUrl) -> None:
    with psycopg.connect(migrated_database, autocommit=True) as setup:
        seed_cases(setup, ("auto_alert",))
    barrier = Barrier(2)

    def execute() -> Any:
        with psycopg.connect(migrated_database, autocommit=True) as connection:

            def wait_for_both_candidates() -> int:
                barrier.wait(timeout=10)
                return NOW_MS

            return run(connection, TicketingPolicy("auto", ()), clock=wait_for_both_candidates)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=20) for future in [pool.submit(execute), pool.submit(execute)]
        ]

    assert sum(result.created for result in results) == 1
    assert sum(result.failed for result in results) == 0
    with psycopg.connect(migrated_database) as verify:
        assert verify.execute("SELECT count(*) FROM tickets").fetchone() == (1,)


def test_migration_keeps_l3_multi_alerts_but_limits_w04_tickets(
    conn: psycopg.Connection,
) -> None:
    alert_ids = [
        "alt_01a19f93-1150-7000-8000-000000000301",
        "alt_01a19f93-1150-7000-8000-000000000302",
    ]
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_ticket(
            conn,
            ticket_id="tkt_01a19f93-1150-7000-8000-000000000301",
            origin="auto",
            alert_ids=alert_ids,
        )

    insert_ticket(
        conn,
        ticket_id="tkt_01a19f93-1150-7000-8000-000000000302",
        origin="auto",
        alert_ids=[alert_ids[0]],
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_ticket(
            conn,
            ticket_id="tkt_01a19f93-1150-7000-8000-000000000303",
            origin="scenario",
            alert_ids=[alert_ids[0]],
        )

    hunt_id = "hnt_01a19f93-1150-7000-8000-000000000301"
    conn.execute(
        "INSERT INTO hunts"
        " (id, hunt_run_id, status, hypothesis, attack_techniques, confidence, reason,"
        " evidence_ids, entities, attempts, verified_at, created_at, updated_at, details)"
        " VALUES (%s, %s, 'confirmed', 'fixture hunt', '{}', 0.8, 'fixture', '{}',"
        " '[]', 1, %s, %s, %s, '{}')",
        (hunt_id, "hrn_01a19f93-1150-7000-8000-000000000301", *([to_datetime(NOW_MS)] * 3)),
    )
    insert_ticket(
        conn,
        ticket_id="tkt_01a19f93-1150-7000-8000-000000000304",
        origin="l3",
        alert_ids=alert_ids,
        hunt_id=hunt_id,
    )
    assert conn.execute(
        "SELECT alert_ids FROM tickets WHERE hunt_id = %s", (hunt_id,)
    ).fetchone() == (alert_ids,)


def test_migration_refuses_existing_multi_alert_w04_ticket_without_rewriting(
    temp_database: HiddenUrl, tmp_path: Path
) -> None:
    legacy_dir = tmp_path / "legacy_migrations"
    legacy_dir.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name != "0104_l1_ticketing.sql":
            shutil.copyfile(migration, legacy_dir / migration.name)
    migrate(temp_database, legacy_dir)
    ids = [
        "alt_01a19f93-1150-7000-8000-000000000401",
        "alt_01a19f93-1150-7000-8000-000000000402",
    ]
    with psycopg.connect(temp_database, autocommit=True) as legacy:
        insert_ticket(
            legacy,
            ticket_id="tkt_01a19f93-1150-7000-8000-000000000401",
            origin="auto",
            alert_ids=ids,
        )

    with pytest.raises(MigrationError):
        migrate(temp_database, MIGRATIONS_DIR)

    with psycopg.connect(temp_database) as verify:
        assert verify.execute(
            "SELECT alert_ids FROM tickets WHERE id = %s",
            ("tkt_01a19f93-1150-7000-8000-000000000401",),
        ).fetchone() == (ids,)
        assert verify.execute("SELECT to_regclass('public.ticketing_policy')").fetchone() == (None,)
