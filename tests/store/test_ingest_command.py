"""`python -m soc.ingest`: one run by default, until nothing new with --all (boxes 4, 5)."""

from pathlib import Path

from fake_store import FakeRecordStore

from soc.ingest.__main__ import main
from soc.plugins import PluginRegistry

ROOT = Path(__file__).resolve().parents[2]
DIRECT_CONFIG = ROOT / "tests" / "fixtures" / "ingest" / "direct.toml"


def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)  # The direct settings use paths from the repo root.
    org = tmp_path / "org.toml"
    org.write_text(
        DIRECT_CONFIG.read_text(encoding="utf-8").replace(
            '[siem]\nadapter = "direct"', '[siem]\nadapter = "direct"\nbatch_size = 4'
        ),
        encoding="utf-8",
    )
    store = FakeRecordStore()
    stores = PluginRegistry("stores")
    stores.register("postgresql.records", lambda s, e: store)
    return {"ZT_CONFIG": str(org)}, store, stores


def stored(store):
    return sum(len(store.list_source_records(kind, None, 100)) for kind in ("alert", "event"))


def test_ingest_command_runs_once_by_default(tmp_path, monkeypatch, capsys):
    environ, store, stores = setup(tmp_path, monkeypatch)

    assert main([], environ=environ, stores=stores) == 0

    assert stored(store) == 4
    assert capsys.readouterr().out.splitlines() == ["fetched 4, stored 4, duplicates 0, skipped 1"]
    assert store.closed


def test_ingest_command_with_all_runs_until_nothing_new(tmp_path, monkeypatch, capsys):
    environ, store, stores = setup(tmp_path, monkeypatch)

    assert main(["--all"], environ=environ, stores=stores) == 0

    assert stored(store) == 6
    assert capsys.readouterr().out.splitlines() == [
        # The sample has one line that is not valid JSON; the adapter skips it.
        "fetched 4, stored 4, duplicates 0, skipped 1",
        "fetched 2, stored 2, duplicates 0, skipped 0",
        "fetched 0, stored 0, duplicates 0, skipped 0",
    ]
