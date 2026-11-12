"""목적지 엔티티와 OCSF·자산 스냅샷이 함께 저장되는지 확인한다(#302)."""

import json
from pathlib import Path

import psycopg
import pytest

from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.normalize.config import Settings
from soc.normalize.run import run

pytestmark = pytest.mark.db

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "normalize" / "destination.json"


def test_destination_survives_storage_asset_lookup_and_repeated_run(temp_database) -> None:
    cases = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    case = next(case for case in cases if case["case"] == "alert_flat_destination")
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
            " VALUES (%s, 'alert', 'elk-test', 'test/destination', %s, %s)",
            (raw_id, to_datetime(1793754000000), original_text),
        )
        asset_id = conn.execute(
            "INSERT INTO assets (name, criticality) VALUES ('destination-test', 4)"
            " RETURNING asset_id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO asset_identifiers (asset_id, entity_type, entity_value)"
            " VALUES (%s, 'ip', '192.0.2.20')",
            (asset_id,),
        )

        first = run(settings, conn, "destination-first")
        second = run(settings, conn, "destination-second")

        assert (first.succeeded, first.failed, second.claimed) == (1, 0, 0)
        rows = conn.execute(
            "SELECT entities, ocsf, assets FROM alerts WHERE raw_id = %s", (raw_id,)
        ).fetchall()
        assert len(rows) == 1
        entities, ocsf, assets = rows[0]
        assert {"type": "ip", "value": "192.0.2.20", "role": "dst"} in entities
        assert {"type": "ip", "value": "198.51.100.7", "role": "src"} in entities
        assert ocsf["evidences"] == [{"dst_endpoint": {"ip": "192.0.2.20"}}]
        assert assets == [
            {
                "entity": {"type": "ip", "value": "192.0.2.20"},
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
