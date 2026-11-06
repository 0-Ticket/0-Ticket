"""개발 시드 확인 인자, 재실행·충돌·기존 시드 간 격리."""

from copy import deepcopy

import psycopg
import pytest
from test_api_ui import SEED, insert_row

from soc.agent.dev_l1 import remove_seed as remove_l1
from soc.api import dev_seed
from soc.db.migrate import migrate
from soc.l3.hunt.dev_seed import remove_seed as remove_l3


def test_no_confirmation_never_connects(monkeypatch, capsys):
    def forbidden(*a, **kw):
        raise AssertionError("must not connect")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    assert dev_seed.main([]) == 2
    assert "--yes" in capsys.readouterr().err


def test_missing_database_is_safe(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert dev_seed.main(["--yes"]) == 2


@pytest.mark.db
def test_seed_idempotent_and_old_seed_removal_is_isolated(temp_database):
    migrate(temp_database)
    with psycopg.connect(temp_database) as conn:
        foreign = []
        for i, profile in enumerate(["dev-seed", "dev-seed-l1", "real-cycle"]):
            row = deepcopy(SEED["raw_records"][0])
            row.update(id=f"raw_01a19f93-9999-7000-8000-{i:012d}", siem_profile=profile)
            insert_row(conn, "raw_records", row)
            foreign.append(row["id"])
        conn.commit()
        first = dev_seed.seed(conn)
        assert first["cases"] == 1 and first["tickets"] == 8
        assert all(n == 0 for n in dev_seed.seed(conn).values())
        assert (
            conn.execute(
                "SELECT count(*) FROM raw_records WHERE id=ANY(%s)", (foreign,)
            ).fetchone()[0]
            == 3
        )
        conn.commit()
        remove_l1(conn)
        remove_l3(conn)
        conn.commit()
        assert conn.execute(
            "SELECT count(*) FROM raw_records WHERE siem_profile='dev-seed-ui'"
        ).fetchone()[0] == len(SEED["raw_records"])
        assert (
            conn.execute(
                "SELECT count(*) FROM hunts WHERE details->>'seed_source'='dev-seed-ui'"
            ).fetchone()[0]
            == 5
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM raw_records WHERE siem_profile='real-cycle'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.db
def test_conflicting_row_rolls_back_all_new_rows(temp_database):
    migrate(temp_database)
    with psycopg.connect(temp_database) as conn:
        row = deepcopy(SEED["raw_records"][-1])
        row["original"] = {"message": "existing"}
        insert_row(conn, "raw_records", row)
        conn.commit()
        with pytest.raises(dev_seed.SeedConflict):
            dev_seed.seed(conn)
        assert conn.execute("SELECT count(*) FROM raw_records").fetchone()[0] == 1
        assert conn.execute("SELECT original FROM raw_records").fetchone()[0] == {
            "message": "existing"
        }


@pytest.mark.db
def test_explicit_command_and_seed_label_on_api(temp_database, monkeypatch):
    from starlette.testclient import TestClient

    from soc.api.app import create_app
    from soc.api.config import load_settings

    migrate(temp_database)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    assert dev_seed.main(["--yes"]) == 0
    assert dev_seed.main(["--yes"]) == 0
    c = TestClient(create_app(load_settings()))
    for table in ["alerts", "events", "tickets", "incidents", "cases"]:
        r = c.get("/api/" + table)
        assert r.status_code == 200
        assert all(x["seed_source"] == "dev-seed-ui" for x in r.json()["items"])


def test_seed_fixture_uses_separate_marker():
    for table, rows in dev_seed.load_seed().items():
        for row in rows:
            if table == "raw_records":
                assert row["siem_profile"] == "dev-seed-ui"
            if "details" in row:
                assert row["details"]["seed_source"] == "dev-seed-ui"
                assert "dev_seed" not in row["details"]
