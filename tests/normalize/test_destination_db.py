"""목적지 엔티티와 OCSF·자산 스냅샷이 함께 저장되는지 확인한다(#302)."""

import json
from pathlib import Path

import psycopg
import pytest
from conftest import HiddenUrl

from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.normalize.config import Settings
from soc.normalize.run import run

pytestmark = pytest.mark.db

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "normalize" / "destination.json"


@pytest.mark.parametrize(
    ("case_name", "table", "destination", "ocsf_path"),
    [
        ("alert_flat_destination", "alerts", "192.0.2.20", "{evidences,0,dst_endpoint,ip}"),
        ("base_destination", "events", "192.0.2.24", "{unmapped,destination,ip}"),
    ],
)
def test_destination_survives_storage_asset_lookup_and_repeated_run(
    temp_database: HiddenUrl, case_name: str, table: str, destination: str, ocsf_path: str
) -> None:
    cases = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    case = next(case for case in cases if case["case"] == case_name)
    migrate(temp_database)
    raw_id = new_id("raw")
    settings = Settings(
        batch_size=10,
        lease_seconds=600,
        connect_timeout_seconds=5,
        asset_statement_timeout_ms=5000,
    )
    original_text = json.dumps(case["original"], ensure_ascii=True)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
            " VALUES (%s, %s, 'elk-test', 'test/destination', %s, %s)",
            (raw_id, case["kind"], to_datetime(1793754000000), original_text),
        )
        asset_id = conn.execute(
            "INSERT INTO assets (name, criticality) VALUES ('destination-test', 4)"
            " RETURNING asset_id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO asset_identifiers (asset_id, entity_type, entity_value)"
            " VALUES (%s, 'ip', %s)",
            (asset_id, destination),
        )

        first = run(settings, conn, "destination-first")
        second = run(settings, conn, "destination-second")

        assert (first.succeeded, first.failed, second.claimed) == (1, 0, 0)
        rows = conn.execute(
            f"SELECT entities, ocsf, assets, ocsf #>> %s FROM {table} WHERE raw_id = %s",
            (ocsf_path, raw_id),
        ).fetchall()
        assert len(rows) == 1
        entities, ocsf, assets, stored_destination = rows[0]
        assert {"type": "ip", "value": destination, "role": "dst"} in entities
        assert {"type": "ip", "value": "198.51.100.7", "role": "src"} in entities
        assert stored_destination == destination
        if table == "events":
            assert ocsf["class_uid"] == 0
            assert ocsf["unmapped"] == {"destination": {"ip": "192.0.2.24"}}
            assert "dst_endpoint" not in ocsf
        else:
            assert ocsf["evidences"] == [{"dst_endpoint": {"ip": "192.0.2.20"}}]
        assert assets == [
            {
                "entity": {"type": "ip", "value": destination},
                "name": "destination-test",
                "criticality": 4,
                "owner": None,
            }
        ]
        assert (
            conn.execute(
                "SELECT original_text FROM raw_records WHERE id = %s", (raw_id,)
            ).fetchone()[0]
            == original_text
        )
