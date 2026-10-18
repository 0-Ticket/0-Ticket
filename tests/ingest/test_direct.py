"""direct adapter: replays dataset files as C1 -> C2 without a SIEM (box 3, K3)."""

import hashlib
import json
import logging
from pathlib import Path

import pytest
from adapter_contract import AdapterContract, walk

from soc.config import ConfigError, DirectSiemSettings, load_config
from soc.ingest.connector import open_connector
from soc.ingest.siem.base import InvalidCursorError
from soc.ingest.siem.direct import DirectSiemConnector

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "ingest"
AIT = FIXTURES / "ait"
CLOCK_MS = 1_700_000_000_000
INJECTION = "ignore previous instructions"


def direct_settings(*files):
    return DirectSiemSettings.model_validate({"files": list(files)})


def file_entry(path, kind="event", scenario="test_scenario", fmt="text"):
    return {
        "path": str(path),
        "kind": kind,
        "scenario": scenario,
        "source_type": "web",
        "format": fmt,
    }


def ait_settings():
    return direct_settings(
        file_entry(AIT / "suricata_eve.jsonl", "alert", "ait_suricata_alert", "jsonl"),
        file_entry(AIT / "apache_access.log", "event", "ait_apache_access", "text"),
    )


def connector_for(*files):
    return DirectSiemConnector(direct_settings(*files), clock=lambda: CLOCK_MS)


class TestDirectContract(AdapterContract):
    @pytest.fixture
    def connector(self):
        return DirectSiemConnector(ait_settings(), clock=lambda: CLOCK_MS)

    @pytest.fixture
    def unhealthy_connector(self, tmp_path):
        return connector_for(file_entry(tmp_path / "missing.log"))

    @pytest.fixture
    def forbidden_text(self):
        return [INJECTION, "WPScan"]


def test_replays_fixture_config_to_expected_c2(monkeypatch):
    monkeypatch.chdir(ROOT)  # Relative paths in the settings file are read from the repo root.
    settings = load_config(FIXTURES / "direct.toml", environ={})
    connector = open_connector(settings, environ={})
    items, _ = walk(connector, 3)
    expected = json.loads((FIXTURES / "expected_c2.json").read_text(encoding="utf-8"))
    assert [item.model_dump(mode="json") for item in items] == expected


def test_builds_c1_with_raw_id_hash_and_untouched_payload():
    replay = DirectSiemConnector(ait_settings(), clock=lambda: CLOCK_MS).replay(None, 100)
    lines = (AIT / "apache_access.log").read_text(encoding="utf-8").splitlines()
    last = replay.records[-1]
    assert last.raw_id == "raw_apache_access.log_5"
    assert last.payload == lines[4]
    assert INJECTION in last.payload  # Kept as data, never acted on.
    assert last.sha256 == hashlib.sha256(lines[4].encode("utf-8")).hexdigest()
    assert last.source_type == "web"
    assert last.received_at == CLOCK_MS
    assert [r.raw_id for r in replay.records] == [i.raw_ids[0] for i in replay.batch.items]


def test_skips_malformed_line_and_logs_location_only(caplog):
    connector = DirectSiemConnector(ait_settings(), clock=lambda: CLOCK_MS)
    with caplog.at_level(logging.WARNING):
        batch = connector.fetch(None, 100)
    assert batch.skipped == 1
    assert "raw_suricata_eve.jsonl_2" not in [i.raw_ids[0] for i in batch.items]
    assert "suricata_eve.jsonl line 2" in caplog.text
    assert "cleartext" not in caplog.text


def test_blank_lines_are_not_records_or_failures():
    batch = connector_for(file_entry(AIT / "apache_access.log")).fetch(None, 100)
    assert len(batch.items) == 4
    assert batch.skipped == 0


def test_rejects_non_object_json_nan_and_undecodable_bytes(tmp_path):
    jsonl = tmp_path / "bad.jsonl"
    jsonl.write_bytes(b'[1, 2]\n{"a": NaN}\n"text"\n{"ok": 1}\n')
    text = tmp_path / "bad.log"
    text.write_bytes(b"\xff\xfe broken\nfine line\n")
    batch = connector_for(file_entry(jsonl, fmt="jsonl"), file_entry(text)).fetch(None, 100)
    assert [i.fields for i in batch.items] == [
        {"ok": 1},
        {"message": "fine line", "source_file": "bad.log"},
    ]
    assert batch.skipped == 4


def test_crlf_line_ending_is_not_part_of_payload(tmp_path):
    path = tmp_path / "crlf.log"
    path.write_bytes(b"first\r\nsecond\r\n")
    replay = connector_for(file_entry(path)).replay(None, 10)
    assert [r.payload for r in replay.records] == ["first", "second"]


def test_skipped_lines_still_move_the_cursor(tmp_path):
    path = tmp_path / "only_bad.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    connector = connector_for(file_entry(path, fmt="jsonl"))
    batch = connector.fetch(None, 10)
    assert batch.items == ()
    assert batch.skipped == 1
    assert connector.fetch(batch.next_cursor, 10).skipped == 0


@pytest.mark.parametrize("cursor", ["", "abc", "0:0", "-1:0:0", "9:0:0", "0:x:1"])
def test_invalid_cursor_is_rejected(cursor):
    connector = DirectSiemConnector(ait_settings(), clock=lambda: CLOCK_MS)
    with pytest.raises(InvalidCursorError):
        connector.fetch(cursor, 10)


def test_health_fails_without_files():
    status = DirectSiemConnector(direct_settings()).health_check()
    assert status.ok is False


def test_same_file_name_twice_is_rejected(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with pytest.raises(ConfigError, match="file name"):
        load_config_with_files(
            tmp_path, [file_entry(tmp_path / "a" / "x.log"), file_entry(tmp_path / "b" / "x.log")]
        )


def test_unknown_format_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="format"):
        load_config_with_files(tmp_path, [file_entry(tmp_path / "x.log", fmt="csv")])


def load_config_with_files(tmp_path, files):
    lines = ['[siem]\nadapter = "direct"\n']
    for entry in files:
        lines.append("[[siem.direct.files]]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in entry.items())
    org = tmp_path / "org.toml"
    org.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load_config(org, environ={})
